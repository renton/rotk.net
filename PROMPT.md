# PROMPT.md

Copy-paste this into a fresh Claude Code session started in this repo.
It walks the assistant through the codebase in the right order so you
don't spend the first ten turns re-explaining what already lives in the
docs.

---

## Paste-in prompt

> I'm resuming work on rotk.net. Before I ask you anything specific,
> get oriented — in this order:
>
> 1. Read `CLAUDE.md` end-to-end. It's the authoritative project map:
>    architecture, the polymorphic `Url` / `TagAssociation` /
>    `MatchExclusion` pattern, per-(chapter, target) keywords model,
>    duplicate-name character resolution, `build_needle_pattern`
>    rules, `book_mention_count` semantics, rescrape safety
>    guarantee, and the known-landmines list. Everything in this file
>    is load-bearing.
>
> 2. Read `HANDOFF.md`. It has the recent bug-fix chain with commit
>    hashes, unfinished threads, and the "why" behind decisions that
>    aren't obvious from code.
>
> 3. Skim `README.md`'s CLI table + "Ops runbook" section. The
>    developer flows for the deployed instance live there.
>
> 4. `git log --oneline -20` — the last twenty commit messages are
>    complete sentences and give a good sense of what's been touched
>    recently.
>
> 5. Peek at these files to ground the architecture in code:
>    - `app/models/character.py` (Character, Faction, Role, Portrait,
>      the `chapter_character` M2M with its `keywords` column, the
>      Character.get_all_name_labels helper)
>    - `app/models/match_exclusion.py` (polymorphic exclusion table)
>    - `tools/book_parser.py` (`build_needle_pattern`,
>      `count_mentions_per_character`, `find_*_mentions`,
>      `normalize_snippet`, `load_chapter_keywords`)
>    - `app/blueprints/main/views.py` — `chapter()` route
>      specifically, from the top through `replace_match`. This is
>      the most subtle code in the project: combined-pattern
>      substitution, skip-index alignment, duplicate-name candidate
>      walk, per-chapter keyword lookup, and the mention counter.
>    - `app/blueprints/admin/views.py` —
>      `chapter_associations_add` / `_remove` / `_switch` /
>      `_exclude` / `_restore`. Structure repeats for events and
>      locations.
>
> 6. Don't run any scrapers, `git push`, `git pull`, `pip install`,
>    or execute unknown binaries without asking. Reading the code and
>    running `flask` CLI commands via docker exec is fine, but check
>    with me first if a command mutates data.
>
> 7. When you commit, match the repo style: full-sentence subject
>    lines, no `fix:` / `feat:` prefixes, no trailing period. No
>    Co-Authored-By trailer.
>
> Once you're oriented, tell me you're ready and give me a two-line
> summary of what you understood as the project's state (recent
> completed work + known unfinished threads). Then I'll ask.

---

## When to use it

- Starting a new session because the current one is deep into context
  usage (~70%+). Rebuilding context beats accumulated summarisation.
- Onboarding someone else's Claude Code session on the same machine.
- Testing whether the docs actually convey the project — if a fresh
  session bounces off `CLAUDE.md` and starts asking questions the doc
  should answer, update the doc.

## When NOT to use it

- Follow-up sessions on the same day where you're only touching one
  small area — the git log is enough context. Save the token budget.
- Small isolated tweaks (CSS, copy edits) — no need to load the
  regex-tagging pipeline into a session that's just aligning a
  button.

## Maintenance

If any of the file references above go stale (renamed, moved, deleted),
update this prompt so a fresh session doesn't get sent to a dead file.
Same for the "load-bearing" claim on CLAUDE.md — if a big decision
lives elsewhere, add it to the prompt's reading list.
