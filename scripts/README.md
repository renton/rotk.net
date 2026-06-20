# scripts/

One-off helper scripts that aren't part of the running app. Each is
self-documenting in its file header.

## chgis_to_solutions.py

Converts CHGIS v6 time-series shapefiles into JSON files consumable by
`flask apply-location-geo`. Run once per data refresh.

**Inputs (not in this repo — license forbids redistribution):**

| File from CHGIS v6 Dataverse | DOI |
|---|---|
| `v6_time_pref_pgn_utf_wgs84.zip` (prefecture / commandery polygons) | [doi:10.7910/DVN/I0Q7SM](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/I0Q7SM) |
| `v6_time_pref_pts_utf_wgs84.zip` (prefecture / commandery centroids) | [doi:10.7910/DVN/WW1PD6](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/WW1PD6) |
| `v6_time_cnty_pts_utf_wgs84.zip` (county centroids) | [doi:10.7910/DVN/Q9VOF5](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/Q9VOF5) |

Download each from Harvard Dataverse (free academic use, requires
attribution, **no redistribution** — keep the bundles outside the repo)
and unzip in some local working directory.

**Reproducing the conversion:**

```bash
# 1. Dump locations from the prod DB (or your local one)
docker compose exec -T app flask dump-locations > /tmp/locations.json

# 2. Set up a throwaway venv with pyshp + shapely
python3 -m venv /tmp/chgis/venv
/tmp/chgis/venv/bin/pip install pyshp shapely

# 3. Place the three CHGIS shapefile bundles in /tmp/chgis/ and unzip
cd /tmp/chgis
unzip v6_time_pref_pgn_utf_wgs84.zip
unzip v6_time_pref_pts_utf_wgs84.zip
unzip v6_time_cnty_pts_utf_wgs84.zip

# 4. Run the converter
/tmp/chgis/venv/bin/python scripts/chgis_to_solutions.py

# 5. Outputs land in /tmp/chgis/out/ — copy into solutions/
cp /tmp/chgis/out/locations-geo-provinces.json    solutions/locations-geo-chgis-provinces.json
cp /tmp/chgis/out/locations-geo-commanderies.json solutions/locations-geo-chgis-commanderies.json
cp /tmp/chgis/out/locations-geo-counties.json     solutions/locations-geo-chgis-counties.json

# 6. Apply (dry-run first, then --apply)
docker compose exec app flask apply-location-geo solutions/locations-geo-chgis-provinces.json
docker compose exec app flask apply-location-geo solutions/locations-geo-chgis-provinces.json --apply
# repeat for commanderies and counties
```

**What it does:**

For each Location, it tries to match against a CHGIS record by Chinese
name first (disambiguates pinyin homonyms like 凉州 / 梁州) then by
stripped pinyin. The era window is 184–280 AD (Yellow Turbans → fall of
Wu). It picks the record whose validity window centres closest to the
era midpoint when several candidates apply.

Provinces don't get their own polygons from CHGIS for our era, so the
script derives each province polygon as the **geometric union** of the
in-era commandery polygons that belong to it (per the `parent_chain`
in the locations dump).

**License reminder.** Every output entry's `notes_append` carries the
CHGIS attribution, which `apply-location-geo` writes into the
Location's `notes` column. The /map view also shows the attribution
panel below the canvas. Don't strip these — they're required by
CHGIS's CC-BY-NC-SA-equivalent terms.
