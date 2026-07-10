# PERFORMANCE.md

Audit of expensive work per page, what's already optimised, and what's
worth changing. Pair with `ISSUES.md` — that one tracks design/quality
debt; this one tracks runtime cost.

Status:
- ✅ already optimised
- 🔥 measurable problem worth fixing
- 🟡 marginal / opportunistic
- ⬜ deliberate non-fix (with reason)

---

## 🔥 Chapter view `/chapter/<n>` — portraits + tags N+1

**Where:** `app/templates/book/chapter.html` (sidebar character panels) and the
implicit lazy loads on `Character.portraits` + `Portrait.tags`.

**Cost:** For each of ~50 characters per chapter the template accesses
`character.portraits` (one query per character), and for each of those
portraits accesses `p.tags` (one query per portrait). Net: ~150
extra SQL round trips beyond the initial chapter+characters fetch. On the
shared postgres over docker networking that's roughly +300–750ms per
chapter view.

**Fix shape:** In `main.chapter`, after `get_characters_for_chapter` returns
the character list, re-query the same IDs with
`selectinload(Character.portraits).selectinload(Portrait.tags)` so the
session has portraits + tags pre-loaded for the template. ~6 lines of
view code, no schema change.

---

## 🔥 Factions / Roles listing — `{{ x.characters | length }}` N+1

**Where:** `app/templates/factions/factions.html` and
`app/templates/roles/roles.html`.

**Cost:** Each row's `{{ faction.characters | length }}` materialises the
faction's **full member collection** just to call `len()` on it. For
~30 factions × ~50 characters each, that loads thousands of Character
rows the page doesn't display.

**Fix shape (preferred — subquery):** Mirror the tag-image-count pattern
in `admin.tags`. One subquery groups `character` by `latest_faction_id`
(and a separate one by role association), joined to the listing query
with `add_columns(coalesce(count, 0))`. Template iterates
`(faction, member_count)` tuples.

**Fix shape (rejected — aggregate column):** `Faction.member_count` and
`Role.member_count` as columns with a `flask recount-tag-members` CLI.
Faster page render, but the underlying data changes every time you edit
a character's faction or roles — high drift risk, low payoff. Subquery
is the right answer here.

---

## 🟡 Chapter associations admin — re-strip per character

**Where:** `app/blueprints/admin/views.py:chapter_associations` calling
`find_character_mentions(chapter, character)` in a loop. The helper strips
HTML from `chapter.content` on every call.

**Cost:** ~30 KB strip × ~50 characters = ~1.5 MB of regex work per page
load. Real but not painful.

**Fix shape:** Strip the chapter content once in the view, pass the
stripped string to a thin `find_mentions_in_text(text, character, …)`
overload. ~3 lines.

---

## 🟡 Chapter associations admin — re-loaded "all characters" datalist

**Where:** Same view, the `all_characters = Character.query.…all()` that
populates the `<datalist>` used by the Add and Switch pickers.

**Cost:** ~1500 character rows on every page load. Each row is small;
this is mostly fine. Visible only if the page ever feels slow.

**Fix shape if it becomes a problem:** Cache the datalist HTML (or the
underlying tuple list) in app memory, invalidated by signals on
Character insert / update / delete. Not worth doing now.

---

## 🟡 Chapter render — skip-index + duplicate-name resolution fanout

**Where:** `app/blueprints/main/views.py:chapter()` — the `_skip_indices_for` pre-scan, the `character_html`-per-`(char_id, needle)` build, and the candidate walk in `replace_match`.

**Cost:** For each character or location with MatchExclusion rows, one full pass over the stripped chapter content with the combined pattern (filtered to matches of that specific needle) to build the skip-index set. Typical chapter with ~5 characters carrying exclusions × one scan each ≈ 5–10 ms extra beyond the base regex sweep. The duplicate-name resolution loop in `replace_match` is O(candidates-per-needle) per match; with the usual single-candidate case, it's negligible.

**Status:** intentionally not cached. Compared to the portrait/tag N+1 above, this is comfortably in the "acceptable per-render cost" bucket. Only becomes interesting if a chapter starts carrying many-dozens of characters with exclusions; the same `Chapter.rendered_content` cache proposal below would neutralise it.

---

## 🟡 `book_mention_count` recount fanout on `rescrape-all-chapters`

**Where:** `rotk.py:rescrape_all_chapters()` — after all chapter content updates, the union of characters whose chapters changed is recounted once.

**Cost:** Bounded but real. Each character's recount walks their full `chapter_character` set (typically ~30 chapters) and does one regex scan per chapter. Union'd across a book-wide rescrape, that's ~1000 characters × ~30 chapters × ~1 ms ≈ **~30 seconds** at the end of a full rescrape. Individual `rescrape-chapter <n>` runs only recount the chapter's associated characters (~50-100 characters, sub-second).

**Status:** OK for a CLI job. Not run on a request path.

**Fix shape if it ever matters:** batch the regex work by chapter instead of by character (pre-strip each chapter's content once across the recount pass), or move to per-`chapter_character` cached counts + `SUM(mention_count) GROUP BY character_id` for the derived scalar.

---

## ✅ Pages already in a good state

- `/` (table of contents) — one query for 120 chapters; templated.
- `/characters` listing — `selectinload(Character.portraits, Character.chapters)`
  in the view, default-portrait + chapter-list dicts computed once in
  Python from the eagerly-loaded data.
- `/admin/images` — `selectinload(Portrait.tags)` on the Portrait query.
- `/admin/tags` — image counts via subquery + outerjoin (no N+1).
- `/admin/users` — paginated; one query.

---

## ⬜ Things I considered but wouldn't do now

### Cache rendered chapter HTML

The chapter view's regex substitution over ~30 KB of HTML *looks*
expensive but is actually fast (~tens of ms in Python). The N+1s above
dwarf it. If we ever do cache it:

- **As a `Chapter.rendered_content` column**: update via a CLI
  (`flask rebuild-chapter-render`) on chapter content / alias changes.
  Cheap reads, manual invalidation, drift on alias edits.
- **Via Flask-Caching against the shared Redis** in `stateful_boilerplate`:
  keyed by `chapter_num + characters_revision` (where the revision is
  bumped by signals on character / alias edits). Slightly more moving
  parts; more correct.

Don't do this until chapter views show as a real bottleneck.

### Per-mention storage (Chapter ↔ Character with count)

`chapter_character` is a plain M2M with no count column. We compute
mention counts:

- Per-chapter, per-character: live during the inline-tagging
  substitution pass (cheap, no extra scan).
- Per-character book-wide: cached on `Character.book_mention_count`,
  rebuilt by `flask recount-book-mentions`.

Promoting `chapter_character` to an association object with a `count`
column would let the chapter view skip the live computation, but the
existing live count is already O(N) over the rendered HTML — not a
target.

---

## Aggregate-field policy

`Character.book_mention_count` is the only precomputed aggregate today,
because the underlying data (chapter text + character aliases) changes
rarely. Adding more aggregate columns is appealing on a microbenchmark
but each one is **another source of drift**. Rule of thumb:

- Add an aggregate column **only if** the live computation is
  measurably expensive AND the input data is mostly stable AND there's
  a clear maintenance command (`flask recount-X`) the admin can run.
- Otherwise prefer a subquery (no drift) or do nothing (most pages are
  fine).

---

## How to re-measure

The app logs every SQL statement (`SQLALCHEMY_ECHO = True` in the base
config — see `ISSUES.md` #28 for why that's still on globally). For a
quick "is this page N+1-ing" check:

```bash
docker compose exec app flask run     # or load a page, then…
docker compose logs --tail 200 app | grep "INFO sqlalchemy.engine.Engine SELECT" | wc -l
```

If a single page view emits more than ~5 SELECTs you probably have a
lazy-load loop in the template — pop the offending view and add
`selectinload(...)` to its query.
