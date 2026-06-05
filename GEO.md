# GEO.md — Geographic data on `/map`

How locations on rotk.net got their lat/lng and polygon boundaries:
sources, licenses, conversion steps, what's covered and what isn't.

This file exists to make the workflow reproducible and to honour the
attribution requirements of the upstream data sets we pulled from. If
you're refreshing the data, start with the "Reproducing the build"
section near the bottom.

---

## The goal

`/map` plots every active `Location` row that has either a
`(latitude, longitude)` point or a stored `geojson` polygon. Render
precedence is enforced in `app/blueprints/main/views.py:map_view()` —
lat/lng wins, polygon falls through, neither means the row is omitted.

We wanted:

- **Provinces (16)** — boundary polygons. Each Han province
  (Bing, You, Ji, Yan, Qing, Xu, Yu, Si, Jing, Yang, Yi, Liang,
  Jiao) and its Three Kingdoms / Jin successors (Yong, Guang, Ning).
- **Commanderies (140)** — boundary polygons where available, fall
  back to centroid points.
- **Counties (408)** — centroid points. Polygons don't exist at this
  level for our era in any free dataset.
- **Cities / Settlements / Passes / Buildings / Mountains / Rivers /
  Battlefields (~199)** — centroid points where sourceable. Most
  aren't covered by historical-GIS datasets at all.

Era covered: **184 AD (Yellow Turban Rebellion) to 280 AD (fall of
Wu)** — administrative geography shifted across that window, so any
single-snapshot dataset is approximate; see "Known limitations" below.

---

## Primary source: CHGIS v6

[**China Historical Geographic Information System, Version 6**](https://chgis.fas.harvard.edu/)
is the standard digitised version of Tan Qixiang's
*Historical Atlas of China* (中国历史地图集). Joint project of the
Center for Historical Geographical Studies (Fudan University,
Shanghai) and the Fairbank Center for Chinese Studies (Harvard
University). Released December 2016.

We pulled three time-series shapefiles from the
[V6 Time Series Dataverse](https://dataverse.harvard.edu/dataverse/chgis_v6_time):

| Dataset | DOI | File | Size |
|---|---|---|---|
| [V6 Time Series Prefecture Polygons](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/I0Q7SM) | `doi:10.7910/DVN/I0Q7SM` | `v6_time_pref_pgn_utf_wgs84.zip` | 31 MB |
| [V6 Time Series Prefecture Points](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/WW1PD6) | `doi:10.7910/DVN/WW1PD6` | `v6_time_pref_pts_utf_wgs84.zip` | 288 KB |
| [V6 Time Series County Points](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/Q9VOF5) | `doi:10.7910/DVN/Q9VOF5` | `v6_time_cnty_pts_utf_wgs84.zip` | 544 KB |

All UTF-8 encoded, WGS84 datum (the right coordinate system for
Leaflet / web mapping).

### Schema (what's in each shapefile)

Both polygon and point shapefiles carry the same attribute set:

| Field | Meaning |
|---|---|
| `NAME_PY` | Pinyin name with admin-type suffix (e.g. `Anding Jun`) |
| `NAME_CH` | Simplified Chinese (e.g. `安定郡`) |
| `NAME_FT` | Traditional Chinese (e.g. `安定郡`) |
| `TYPE_PY` / `TYPE_CH` | Admin type — `Jun` / 郡 (Commandery), `Zhou` / 州 (Prefecture/Province), `Xian` / 县 (County), `Guo` / 国 (Kingdom), `Houguo` / 侯国 (Marquess Kingdom), etc. |
| `BEG_YR` / `END_YR` | Validity window in calendar years (negative = BCE) |
| `X_COOR` / `Y_COOR` | Centroid (mostly meaningful on the point files) |

The polygon shapefile has 3,830 records covering 221 BCE → 1911 CE;
of those, **103 are valid in our 184–280 AD window** — almost all of
them commanderies (`Jun` or `Houguo`).

### License

[CHGIS V6 End Users License Agreement](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/I0Q7SM)
— equivalent to **CC BY-NC-SA 4.0**:

- **BY**: attribution required. Every derived map / data file must
  cite *"CHGIS Version 6. © Fairbank Center for Chinese Studies of
  Harvard University and Center for Historical Geographical Studies
  at Fudan University, December 2016."*
- **NC**: academic / educational use only; no commercial use without
  a separate licence from the CHGIS Management Committee.
- **SA / no redistribution of raw files**: end users obtain the data
  via direct download from the official distributors. We do **not**
  commit the raw `.shp` / `.dbf` / `.zip` bundles to this repo —
  reproducers fetch them themselves following the steps below.

What we do commit: the **derived** lat/lng and GeoJSON polygon
values per Location row, plus an attribution line on each row's
`notes` column and a visible credits panel on the `/map` page itself.

---

## The conversion script

`scripts/chgis_to_solutions.py` does the matching. Self-documented in
its file header; the short version:

1. **Read all three shapefiles** with `pyshp` (pure-Python; no GDAL
   dependency). Filter to records whose validity window overlaps
   `184 ≤ BEG_YR ≤ 280 AND END_YR ≥ 184`.
2. **Build name indexes** keyed by both Chinese (`NAME_CH` /
   `NAME_FT`) and stripped pinyin (`NAME_PY` minus the type suffix
   `Jun` / `Zhou` / `Xian` / etc.).
3. **Match each Location** in `flask dump-locations` output against
   the right layer for its type — Province → Zhou points / derived
   polygons; Commandery → polygons first, points if no polygon;
   County / sub-county → County points.
4. **Disambiguate** by Chinese-name agreement when our Location has a
   `chinese_name`. This catches collisions like 凉州 (Liang, NW
   frontier) vs 梁州 (Liang, SW) that share the same pinyin.
5. **Derive province polygons via union.** CHGIS doesn't ship Zhou
   polygons for our era — they only have Zhou centroid points. So
   each province polygon is computed as the geometric union
   (`shapely.ops.unary_union`) of all the in-era commandery polygons
   whose `parent_chain` ends with that province. Provinces with no
   commandery polygons fall back to the hand-drawn polygons in
   `solutions/locations-geo-fallback-provinces.json`.
6. **Pick the best record** when several candidates match — the one
   whose validity window centres closest to the era midpoint
   (~232 AD), with longer-lived records as the tiebreak.
7. **Emit three JSON solutions files** in the shape
   `flask apply-location-geo` consumes (one per administrative
   level).

### What got matched

| Layer | Total Locations | Matched | Polygons | Points | Missed |
|---|---:|---:|---:|---:|---:|
| Provinces | 16 | 9 | 5 (derived from commandery unions) | 4 | 7 |
| Commanderies | 140 | 109 | 18 | 91 | 31 |
| Counties | 408 | 322 | — | 322 | 86 |
| Cities / Settlements / Passes / Buildings | ~199 | 9 | — | 9 | ~190 |
| **Totals** | **~763** | **~449** | **23** | **426** | **~314** |

(County `missed` excludes the 62 type-less rows in our dump. The
sub-county hits are name-coincidence matches against the county
points file.)

### The 7 missing provinces

CHGIS v6 simply doesn't include time-series records for these Han
provinces in our era — Tan Qixiang's atlas treats them as static
across the period, so their boundaries aren't in the time-coded
shapefile:

- **Ji Province** (冀州)
- **Qing Province** (青州)
- **Si Province** (司隸州) — CHGIS has *Si Zhou* 司州 (280-316), but
  that's the *post-Han* successor with a different administrative
  identity; the disambiguator correctly rejects it
- **Yan Province** (兗州)
- **Yong Province** (雍州)
- **You Province** (幽州)
- **Yu Province** (豫州)

These fall back to the original hand-drawn polygons in
`solutions/locations-geo-fallback-provinces.json` — approximate
outlines covering the broad geographic extent of each, drawn from
training-data knowledge of Han geography. Every entry's
`notes_append` flags the approximation explicitly so the row's audit
trail makes the source clear.

---

## Reproducing the build

```bash
# 1. Dump locations from the DB (run inside the app container).
docker compose exec -T app flask dump-locations > /tmp/locations.json

# 2. Set up a throwaway venv for the converter.
mkdir -p /tmp/chgis && python3 -m venv /tmp/chgis/venv
/tmp/chgis/venv/bin/pip install pyshp shapely

# 3. Download the three CHGIS shapefile bundles into /tmp/chgis/.
#    The URLs below are stable Dataverse direct-download links;
#    file IDs come from each dataset's published version.
cd /tmp/chgis
curl -sSL -o v6_time_pref_pgn_utf_wgs84.zip \
    https://dataverse.harvard.edu/api/access/datafile/2966510
curl -sSL -o v6_time_pref_pts_utf_wgs84.zip \
    https://dataverse.harvard.edu/api/access/datafile/2970286
curl -sSL -o v6_time_cnty_pts_utf_wgs84.zip \
    https://dataverse.harvard.edu/api/access/datafile/3048165

# 4. Unzip in place — the converter looks for the .shp / .dbf / .prj
#    files next to each other in /tmp/chgis/.
unzip -o v6_time_pref_pgn_utf_wgs84.zip
unzip -o v6_time_pref_pts_utf_wgs84.zip
unzip -o v6_time_cnty_pts_utf_wgs84.zip

# 5. Run the converter. Outputs land in /tmp/chgis/out/.
cd /home/renton/projects/rotk.net   # (or wherever your checkout is)
/tmp/chgis/venv/bin/python scripts/chgis_to_solutions.py

# 6. Copy the three result files into solutions/ and review the
#    match report.
cp /tmp/chgis/out/locations-geo-provinces.json    solutions/locations-geo-chgis-provinces.json
cp /tmp/chgis/out/locations-geo-commanderies.json solutions/locations-geo-chgis-commanderies.json
cp /tmp/chgis/out/locations-geo-counties.json     solutions/locations-geo-chgis-counties.json
less /tmp/chgis/out/match-report.txt              # per-row matched/missed log

# 7. Apply the migration that adds the geojson column.
docker compose exec app flask apply-migrations

# 8. Dry-run each solutions file (no writes), in this order:
docker compose exec app flask apply-location-geo solutions/locations-geo-chgis-provinces.json
docker compose exec app flask apply-location-geo solutions/locations-geo-chgis-commanderies.json
docker compose exec app flask apply-location-geo solutions/locations-geo-chgis-counties.json
docker compose exec app flask apply-location-geo solutions/locations-geo-fallback-provinces.json

# 9. Re-run each with --apply to write. Apply the CHGIS files FIRST,
#    then the fallback provinces — the fallback file only contains
#    the 7 CHGIS-uncovered provinces so it can't clobber CHGIS data.
docker compose exec app flask apply-location-geo solutions/locations-geo-chgis-provinces.json     --apply
docker compose exec app flask apply-location-geo solutions/locations-geo-chgis-commanderies.json  --apply
docker compose exec app flask apply-location-geo solutions/locations-geo-chgis-counties.json      --apply
docker compose exec app flask apply-location-geo solutions/locations-geo-fallback-provinces.json  --apply
```

After that, `/map` should be populated with roughly 450 located rows.
Spot-check a province polygon (e.g. **Jing Province** — Hubei +
Hunan) and a major commandery (e.g. **Nanyang Commandery**) to make
sure the shape lands in the right region.

---

## Known limitations

- **Borders aren't a single point in time.** Administrative divisions
  shifted across the 184–280 AD window. Yong Province split from
  Liang ~213 AD; Guang split from Jiao 226 AD; Ning split from Yi
  ~271 AD. CHGIS time-codes each record but the union we compute is
  the cumulative extent across the era, not a year-specific snapshot.
  Year-cursor support is captured as ISSUES #50.

- **Si Province lacks any usable CHGIS record.** The Han-era 司隸校尉部
  ("Sili", capital district) is a distinct administrative entity from
  the post-Han 司州 (Si Zhou) and CHGIS v6 only has the latter. The
  fallback polygon is hand-drawn.

- **Sub-county coverage is sparse.** CHGIS stops at County. Cities,
  settlements, passes, mountains, battlefields, and fictional /
  legendary buildings (~190 of our rows) aren't in any free
  historical-GIS dataset. ISSUES #51 plans the follow-up work:
  hand-curate the famous landmarks (Chibi, Hulao Pass, Wuzhang
  Plains, Bowang Slope, etc.) from training data, then SPARQL-pull
  the long tail from Wikidata.

- **Some 95 counties missed CHGIS match.** Possible causes: county
  was renamed before or after CHGIS's recorded window, our
  transliteration / Chinese form differs from CHGIS's, or the
  county's CHGIS validity window doesn't overlap 184-280 AD.
  Inspect them in `/tmp/chgis/out/match-report.txt` line-by-line —
  most can be fixed by adjusting our `chinese_name` to match CHGIS's
  `NAME_CH`, or by adding a hand-curated point entry to a
  `solutions/locations-geo-county-fixes.json` follow-up file.

---

## Base map tiles

[OpenStreetMap](https://www.openstreetmap.org/) raster tiles via
`*.tile.openstreetmap.org` are the base layer. License:
[Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/)
— free, with attribution required. The Leaflet attribution control
shows the standard "© OpenStreetMap contributors" badge in the
bottom-right of every map tile area; the credits panel below the
canvas on `/map` includes a fuller credit + link to the ODbL.

The CSP at `app/__init__.py:_build_csp()` allows
`https://*.tile.openstreetmap.org` under `img-src`. If we ever swap
to a different tile provider (MapTiler, Stadia, Carto), update both
the Leaflet tile URL in `app/static/js/map.js` and the CSP entry.

---

## Citing rotk.net's derived map data

Anyone using the `/map` view or downstream copies of our
`location.geojson` / `location.latitude` / `location.longitude` values
must include both of the following:

1. *"CHGIS Version 6. © Fairbank Center for Chinese Studies of
   Harvard University and Center for Historical Geographical Studies
   at Fudan University, December 2016."* — for any polygon or point
   originally derived from CHGIS (i.e. any row whose `notes` includes
   the `[geo]` `CHGIS v6` line).

2. *"Map tiles © OpenStreetMap contributors, licensed under
   [ODbL](https://opendatacommons.org/licenses/odbl/)."* — for the
   base map.

The `/map` page itself does this in the credits panel below the
canvas; this file is the longer-form record.
