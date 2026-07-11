# rotk-net MCP server

A [Model Context Protocol](https://modelcontextprotocol.io) server that
gives AI assistants (Claude Code, Claude Desktop, any MCP host)
**read-only** tools over rotk.net's public JSON API (`/api/v1`). Its
main job: helping find data-quality issues — characters without
factions, undated events, geo-less locations, leaderless factions — so
they can be fixed through the admin UI.

Zero dependencies beyond Python 3.10+ and `requests`: it speaks the MCP
JSON-RPC protocol over stdio directly, no SDK install needed.

## Read-only, twice over

The server only ever issues GET requests, and the API it talks to is
itself structurally read-only (a blueprint-level guard 405s any write
method). There is nothing this server can change.

## Tools

| Tool | What it does |
|---|---|
| `rotk_api_index` | The endpoint catalogue — every resource, its filters, what its payload joins in. |
| `rotk_list` | Paginated list of any resource with endpoint-specific filters (`{"q": "Cao", "sort": "mentions"}`). |
| `rotk_get` | One resource with its full joined payload. Chapters by chapter number, year-maps by year, everything else by id. |
| `rotk_find_data_gaps` | Whole-resource data-quality sweeps: 20+ checks like `characters_without_faction`, `events_with_unparsed_dates`, `locations_without_geo`, `factions_without_leaders`, `year_maps_missing_years`. Returns the offending rows. |
| `rotk_fetch` | Escape hatch — GET any `/api/v1` path directly. |

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `ROTK_API_BASE` | `https://rotk.net` | Where requests go. Point at `http://localhost` to audit a dev database. |
| `ROTK_API_TIMEOUT` | `30` | Per-request timeout (seconds). |

## Using it from Claude Code

The repo-root `.mcp.json` registers the server project-wide — open a
Claude Code session in this repo, approve the `rotk` server when
prompted, and the tools appear (check with `/mcp`). Then just ask:

- *"Run the `factions_without_leaders` gap check and summarize what needs doing."*
- *"Find events with unparseable dates and propose corrected date strings."*
- *"Which era years have no territory map yet?"*
- *"List the 20 most-mentioned characters without a portrait."*

To audit local dev data instead of production, edit `.mcp.json`'s
`ROTK_API_BASE` (or export it before launching).

## Diagnostics

```bash
python3 mcp_server/rotk_mcp.py --selftest   # offline protocol check
python3 mcp_server/rotk_mcp.py --smoke      # live GET <base>/api/v1/
```

## Future (v2)

Write support — fixing data *through* the MCP — needs the site API to
grow authenticated write endpoints first. Until then the workflow is:
MCP finds and reports, fixes happen in the admin UI (which the reports
link to by id).
