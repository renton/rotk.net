# Triage solutions

Tracked-in-git JSON files that `flask apply-triage-decisions` can apply to
the chapter ↔ entity tagging data. One file per chapter (e.g.
`chapter-10.json`).

## Workflow

```
# 1. Dump the chapter's current matches on the VPS
docker compose exec app flask dump-chapter-triage 10 > /tmp/triage10.json

# 2. Copy to laptop and have the LLM author solutions/chapter-N.json
#    (see schema below)

# 3. Commit the solutions file, pull on the VPS

# 4. Dry-run first
docker compose exec app flask apply-triage-decisions solutions/chapter-10.json

# 5. Apply
docker compose exec app flask apply-triage-decisions solutions/chapter-10.json --apply
```

## File schema

```json
{
  "chapter_num": 10,
  "decisions": [
    {
      "target_type": "location",
      "target_id": 62,
      "action": "exclude",
      "match_text": "Yu",
      "before_snippet": "...had conspired with three officials---Court Counselors Ma ",
      "after_snippet": " and Chong Shao, and Imperial Commander..."
    },
    {
      "target_type": "location",
      "target_id": 1456,
      "action": "remove_m2m"
    }
  ]
}
```

### Fields

- `chapter_num` (int, required) — the chapter the decisions apply to.
- `decisions[]`:
  - `target_type` — `"location"`, `"character"`, or `"event"`.
  - `target_id` — the entity's row id (from the dump's `entity_id`).
  - `action` — one of:
    - `"exclude"` — add a `MatchExclusion` row so this specific snippet
      stops being inline-tagged. Idempotent.
    - `"restore"` — delete a `MatchExclusion` matching the fingerprint.
    - `"remove_m2m"` — drop the chapter ↔ target association row
      entirely. The entity record itself is untouched.
  - For `exclude` and `restore`: `match_text`, `before_snippet`,
    `after_snippet` (copy verbatim from the dump's `snippet` object).
  - For `remove_m2m`: no extra fields.

## Notes

- Dry-run is the default. `--apply` writes; removal-class actions get a
  default-`N` confirm.
- Audit (`created_by` / `last_edited_by`) is stamped automatically by
  the ORM hooks — same as admin UI edits.
- Re-running the same solutions file is safe (idempotent skip for
  already-excluded snippets / already-removed M2M rows).
