# HANDOFF.md

Session-to-session context transfer. When this hand-off is out of date,
delete or overwrite it — the git log + `CLAUDE.md` are the sources of
truth. This file exists to save a fresh Claude Code session from
re-deriving decisions that already have answers.

Last updated: 2026-06-22, end of the "class=2 scraper fix + per-chapter
keywords + duplicate-name exclusions" thread.

---

## Recent bug-fix chain (most-recent-first)

Each entry: **commit** — one-line what/why. Grep for these hashes if
you want the diff.

- **`11f25f9`** — `Location.geojson = ""` bug. `new_location` did
  `form.populate_obj(location)` without overriding `geojson` with the
  validator's parsed value, so blank input stored the JSON scalar `""`.
  `has_geo` checks tightened to truthy. Legacy dirty rows: run
  `flask clean-empty-location-geojson`.
- **`cdb3180`** — `book_mention_count` semantic. Previously a global
  string-match; now association-aware (walks each character's own
  `chapter_character` M2M with per-chapter keywords). Duplicate-name
  characters (two "Lady Cao"s) no longer over-count each other.
  Recount fires on assoc add/remove/switch, edit-character label
  change, rescrape, and the existing bulk CLI.
- **`f7a1ab5`** — scraper missed `<td class="2">` (indented
  commentary / quoted-letter blocks). 255 blocks across 74 chapters
  were silently dropped. Fixed; safe rescrape CLIs added
  (`rescrape-chapter`, `rescrape-all-chapters`) that update the row
  in place (no cascade deletion).
- **`8c5c9ac`** — skip-index alignment. `_skip_indices_for` used a
  per-needle regex but `replace_match` matched with the combined
  (longest-first) pattern, so occurrence indices diverged when one
  needle was a prefix of another. Skip-index now iterates the same
  combined pattern filtered to the target needle.
- **`5f6d08a`** — duplicate-name character resolution. `needle_to_character_id`
  (single) → `needle_to_character_ids` (list). First candidate whose
  MatchExclusion set doesn't contain the current occurrence claims
  the pill. Enables the split-exclusion admin workflow.
- **`e7dbfc2` + `9233c4d`** — `build_needle_pattern` improvements:
  longest-first sort (`"Cao|Cao Cao"` used to swallow `Cao Cao` as
  just `Cao`), `\s+` between tokens (matches `Wang\nYun` across a
  line break), `(?=\W|$)` trailing context (matches `Wang Yun:` and
  other punctuation).
- **`d70f319`** — per-(chapter, target) keywords. Added
  `chapter_character.keywords`, `event_chapter.keywords`,
  `chapter_location.keywords` columns via migration 0012. Admin
  `chapter_associations_add` / `event_associations_add` /
  `location_associations_add` now write to the association row, not
  the global `aliases` field. Backfill via
  `flask backfill-association-keywords`.
- **`f0e7ace`** — Character-side snippet exclusion parity with
  Location. AJAX in the admin page (shared JS with the location
  editor); chapter render honours it via the same
  `character_skip_indices` mechanism as locations.
- **`d03baae`** — MatchExclusion introduced (target_type polymorphic).
  Fingerprint = whitespace-normalised `(before_snippet, match_text, after_snippet)`.
  Content-addressed by design, not position-based — survives content
  shifts as long as the ~60-char window stays the same.

The full arc predating this thread: `git log --oneline` reads
top-to-bottom. Every commit message is a full sentence, no cryptic
`fix` / `wip` markers.

---

## Design decisions that aren't obvious from code

Roughly in "someone will re-derive this if they don't read the doc"
order. All are also captured in `CLAUDE.md`'s "How data flows" and
"Conventions worth knowing" sections — this list is the elevator
version.

1. **Per-chapter keywords over global aliases** (mig 0012). Rationale:
   "resync should be per-chapter, not global" — editing keywords on
   chapter 5 should only change chapter 5's inline tagging. Global
   aliases remain as fallback for pre-backfill rows.
2. **MatchExclusion is content-addressed, not position-based.** Storing
   `(chapter_id, character_id, char_offset)` would invalidate on every
   upstream paragraph insert. Storing surrounding text survives most
   content shifts.
3. **`needle_to_character_ids` is a list, not an id.** Duplicate-name
   characters (two "Lady Cao"s both associated with chapter N) each
   contribute their own exclusion set. Renderer walks candidates,
   first-non-excluding wins. Enables split-exclusion admin workflow.
4. **`build_needle_pattern` rules that all matter:**
   - longest-first alternation (Python's `|` is leftmost-first)
   - `\s+` between multi-word tokens (line-break tolerance)
   - `(?=\W|$)` trailing context (colons, parens, brackets)
   - Callers must whitespace-collapse `match.group(0)` before dict lookup.
5. **Rescrape never deletes.** `rescrape-chapter` / `rescrape-all-chapters`
   UPDATE `chapter.name` + `chapter.content` in place. Delete-and-rescrape
   would cascade-delete every FK dependent (associations, keywords,
   exclusions).
6. **Book-mention count is a cached scalar, refreshed on every relevant
   edit.** Explicit calls at all mutation points (add, remove, switch,
   rescrape, edit_character label changes, `new_character`). No hooks
   — considered them; the raw-SQL keyword UPDATE path bypasses ORM
   events so hooks alone don't cover it.
7. **Chapter content is the source of truth for match positions.**
   Nothing is pre-rendered / pre-indexed. Every chapter view does the
   full regex sweep. Fine for current traffic; see `PERFORMANCE.md`
   for the caching options if it ever isn't.

---

## Open threads / known unfinished

- **Event-side per-snippet exclusion UI**. Schema supports it
  (`match_exclusion.target_type` is polymorphic), but no UI wired.
  Would mirror the Location/Character implementation exactly.
- **`courtesty_name` typo**. Ripples through models, forms, templates,
  and one CLI. Coordinated rename pending — ISSUES #19.
- **Portrait per-source scraping**. Only Koei is wired
  (`tools/image_scrapers/koei.py`). Other Wikimedia / fandom sources
  would follow the same pattern.
- **Chapter dates for chapters 1-120**. Column exists (`chapter.date`),
  header displays it, `flask apply-chapter-dates` writes bulk from
  JSON, but most chapters are still empty. Bulk-dating workflow via
  `flask dump-chapters-for-dating` → LLM → `apply-chapter-dates` is
  ready.
- **Timeline / map views** — half-built. `/map` exists;
  `tools.date_parser` is early. See `GEO.md`.

---

## Verification checklist for a fresh session on ambrose

If a new Claude session picks up this project, these are the
non-obvious "is everything OK" checks after a `git pull`:

- [ ] `docker compose exec app flask apply-migrations` — safe to
      run any time; skips already-applied files.
- [ ] `docker compose restart app` — always safe; needed after any
      Python change (bind-mount handles templates + static without
      restart).
- [ ] `docker compose logs app | tail -50` — verify boot didn't
      error. Common failure mode: a new endpoint referenced from a
      template before the Python route was defined; template render
      500s at load time.
- [ ] `flask backfill-association-keywords --dry-run` — if it
      prints "Nothing to backfill" you're good. If it wants to seed
      thousands of rows, someone hasn't run the post-migration
      backfill.
- [ ] `flask clean-empty-location-geojson --dry-run` — if it prints
      "No bad geojson rows" you're good.

None of these are urgent for a fresh session; they're the "sanity
before making changes" list.

---

## Local development notes

The user (ren) develops on the ambrose VM directly via SSH tunnel;
Docker Compose runs there and the changes are live on
`https://rotk.net`. Repo-root `docker-compose.override.yml` is meant
to auto-apply on ambrose — don't propose moving it. Bind-mount is on
so template/JS/CSS changes hot-reload; Python changes need
`docker compose restart app`.

Git rules from `~/.claude/CLAUDE.md`:

- Can `git commit` without asking (match repo commit style — full
  sentence, no prefixes).
- **Never** `git push` or `git pull`. User does those. If you think a
  push is needed, say so and stop.
- **Never** download from the web without asking (`curl`, `wget`,
  `pip install`, etc.). WebFetch/WebSearch tools are the exception —
  those route through Anthropic.
- **Never** execute binaries you didn't write / weren't asked to run.
