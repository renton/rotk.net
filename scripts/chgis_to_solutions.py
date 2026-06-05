"""One-off converter from CHGIS v6 shapefiles → solutions JSON
for `flask apply-location-geo`.

Inputs:
  /tmp/locations.json                              (dump from `flask dump-locations`)
  /tmp/chgis/v6_time_pref_pgn_utf_wgs84.{shp,dbf} (commandery polygons)
  /tmp/chgis/v6_time_pref_pts_utf_wgs84.{shp,dbf} (commandery centroids)
  /tmp/chgis/v6_time_cnty_pts_utf_wgs84.{shp,dbf} (county centroids)

Outputs:
  /tmp/chgis/out/locations-geo-provinces.json
  /tmp/chgis/out/locations-geo-commanderies.json
  /tmp/chgis/out/locations-geo-counties.json
  /tmp/chgis/out/match-report.txt

Each output entry is in the shape `flask apply-location-geo` expects:
  {"id": <loc.id>, "latitude": ..., "longitude": ..., "geojson": {...},
   "notes_append": "[geo] derived from CHGIS v6 ... (BEG=YYY END=YYY)"}

Matching strategy:
  - Strip the type-suffix from BOTH sides (English "Commandery", CHGIS "Jun")
    and lowercase + alphanumeric-only to get a comparable key.
  - Prefer polygons over points when both exist.
  - Prefer the CHGIS record whose validity window centers closest to our
    era midpoint (~232 AD) when several match the same key.

Era window: 184 AD (Yellow Turbans) to 280 AD (Wu falls). A CHGIS record
is in-era when BEG_YR <= 280 and END_YR >= 184.
"""
import json
import os
import re
import shapefile

ERA_LO, ERA_HI = 184, 280
ERA_MID = (ERA_LO + ERA_HI) / 2

CHGIS_DIR = '/tmp/chgis'
OUT_DIR = '/tmp/chgis/out'
os.makedirs(OUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Name normalisation. CHGIS pinyin always has the admin-type suffix
# ("Anding Jun"); our English names always have the localized type suffix
# ("Anding Commandery"). Stripping both lets us compare apples to apples.

ENGLISH_TYPE_SUFFIXES = [
    'Province', 'Commandery', 'County', 'City', 'Settlement',
    'Pass', 'Kingdom', 'Marquisate', 'Mountain', 'River',
    'Battlefield', 'Landmark', 'Building', 'Structure',
]
CHGIS_TYPE_SUFFIXES = [
    'Jun', 'Guo', 'Houguo', 'Zhou', 'Xian', 'Dao', 'Yi',
    'Dudu', 'Tuntianduwei', 'Diannongduwei', 'Diannongjiaowei',
    'Shuguoduwei', 'Gou', 'Yin',
]

_NON_ALNUM = re.compile(r'[^a-z0-9]+')

def normkey(s, suffixes):
    if not s:
        return ''
    s = s.strip()
    # Strip trailing suffix (case-insensitive, word boundary).
    for suf in suffixes:
        pat = re.compile(rf'\s+{re.escape(suf)}\s*$', re.IGNORECASE)
        m = pat.search(s)
        if m:
            s = s[:m.start()].strip()
            break
    return _NON_ALNUM.sub('', s.lower())

# ---------------------------------------------------------------------------
# Read CHGIS layers. For each, we keep an index keyed by (norm_pinyin,
# norm_chinese, geometry) so we can chase whichever is most reliable.

def load_layer(path, want_polygon):
    """Yield (key_pinyin, key_chinese, name_py, name_ch, beg, end, geom_dict) tuples
    for every in-era record."""
    with shapefile.Reader(path) as r:
        for rec, shape in zip(r.iterRecords(), r.iterShapes()):
            d = rec.as_dict()
            beg = d.get('BEG_YR')
            end = d.get('END_YR')
            if beg is None or end is None:
                continue
            if beg > ERA_HI or end < ERA_LO:
                continue

            name_py = (d.get('NAME_PY') or '').strip()
            name_ch = (d.get('NAME_CH') or '').strip()
            # NAME_FT is traditional Chinese — useful as a fallback Chinese match.
            name_ft = (d.get('NAME_FT') or '').strip()
            type_py = (d.get('TYPE_PY') or '').strip()

            key_py = normkey(name_py, CHGIS_TYPE_SUFFIXES)
            # For Chinese names we don't need to strip suffix — CHGIS includes
            # them ("安定郡") and our data sometimes does, sometimes doesn't.
            # We'll do contains-match in both directions.
            key_ch_simp = name_ch
            key_ch_trad = name_ft

            geom = None
            if want_polygon:
                if shape.shapeType in (5, 15, 25):  # polygon / polygonZ / polygonM
                    geom = polygon_to_geojson(shape)
            else:
                if shape.shapeType in (1, 11, 21):  # point / pointZ / pointM
                    if shape.points:
                        lng, lat = shape.points[0]
                        geom = {'__point__': [lng, lat]}

            if geom is None:
                continue

            yield {
                'key_py': key_py,
                'key_ch_simp': key_ch_simp,
                'key_ch_trad': key_ch_trad,
                'name_py': name_py,
                'name_ch': name_ch,
                'type_py': type_py,
                'beg': beg,
                'end': end,
                'geom': geom,
                'mid': (beg + end) / 2.0,
            }

def polygon_to_geojson(shape):
    """Convert a pyshp polygon shape to GeoJSON. `shape.parts` is the
    start-index of each ring in `shape.points`; the first ring is the
    outer ring, subsequent rings are holes (per ESRI shapefile spec we
    treat them as outer rings of a MultiPolygon since the spec isn't
    perfectly explicit about holes vs. multipolygons)."""
    parts = list(shape.parts) + [len(shape.points)]
    rings = []
    for i in range(len(parts) - 1):
        ring = [[float(x), float(y)] for (x, y) in shape.points[parts[i]:parts[i+1]]]
        if not ring:
            continue
        # Ensure ring is closed.
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        rings.append(ring)
    if not rings:
        return None
    if len(rings) == 1:
        return {'type': 'Polygon', 'coordinates': [rings[0]]}
    # Multiple rings in a single polygon-shape: treat as MultiPolygon
    # of single-ring polygons. (CHGIS prefectures rarely have inner
    # holes; usually multi-ring means disconnected sub-areas.)
    return {'type': 'MultiPolygon',
            'coordinates': [[ring] for ring in rings]}

# ---------------------------------------------------------------------------

print('Reading CHGIS layers...')
pgn_records = list(load_layer(f'{CHGIS_DIR}/v6_time_pref_pgn_utf_wgs84', want_polygon=True))
pref_pts    = list(load_layer(f'{CHGIS_DIR}/v6_time_pref_pts_utf_wgs84', want_polygon=False))
cnty_pts    = list(load_layer(f'{CHGIS_DIR}/v6_time_cnty_pts_utf_wgs84', want_polygon=False))
print(f'  polygons in era:        {len(pgn_records)}')
print(f'  prefecture points:      {len(pref_pts)}')
print(f'  county points:          {len(cnty_pts)}')

# Build lookup tables: pinyin key → [records], chinese contains → [records]
def index(records, key_fn):
    idx = {}
    for r in records:
        k = key_fn(r)
        if not k:
            continue
        idx.setdefault(k, []).append(r)
    return idx

pgn_by_py        = index(pgn_records, lambda r: r['key_py'])
pgn_by_ch_simp   = index(pgn_records, lambda r: r['key_ch_simp'])
pgn_by_ch_trad   = index(pgn_records, lambda r: r['key_ch_trad'])

pref_by_py       = index(pref_pts, lambda r: r['key_py'])
pref_by_ch_simp  = index(pref_pts, lambda r: r['key_ch_simp'])
pref_by_ch_trad  = index(pref_pts, lambda r: r['key_ch_trad'])

cnty_by_py       = index(cnty_pts, lambda r: r['key_py'])
cnty_by_ch_simp  = index(cnty_pts, lambda r: r['key_ch_simp'])
cnty_by_ch_trad  = index(cnty_pts, lambda r: r['key_ch_trad'])

# ---------------------------------------------------------------------------

def best_record(candidates):
    """Pick the candidate whose validity window centers closest to the
    era midpoint. Tiebreak by longer record (wider validity window)."""
    if not candidates:
        return None
    return min(candidates, key=lambda r: (abs(r['mid'] - ERA_MID), -(r['end'] - r['beg'])))


def chinese_agrees(rec, ch_simp_keys, ch_trad_keys):
    """True iff `rec` shares a Chinese name with one of the candidate
    keys. Match is permissive — bare name on either side counts (so
    our '凉州' matches CHGIS '凉州' even though CHGIS sometimes adds
    a suffix). Used to disambiguate pinyin homonyms like 凉州 vs 梁州."""
    rec_simp = (rec.get('key_ch_simp') or '').strip()
    rec_trad = (rec.get('key_ch_trad') or '').strip()
    for k in ch_simp_keys:
        if k and (k == rec_simp or k in rec_simp or rec_simp in k):
            return True
    for k in ch_trad_keys:
        if k and (k == rec_trad or k in rec_trad or rec_trad in k):
            return True
    return False


def search(indexes, key_py, ch_simp_keys, ch_trad_keys, require_chinese):
    """Walk indexes in priority order. Chinese-name match always wins;
    pinyin matches are only accepted when our location has no Chinese
    name (require_chinese=False) OR when the matched record's Chinese
    name agrees with ours.

    `indexes` is a list of (by_pinyin, by_chinese_simp, by_chinese_trad)
    triples — one triple per layer (polygons / points / etc.)."""
    # Pass 1: try matching directly by Chinese name across each index.
    for _, idx_by_simp, idx_by_trad in indexes:
        cs = []
        for k in ch_simp_keys:
            if k and k in idx_by_simp:
                cs.extend(idx_by_simp[k])
        for k in ch_trad_keys:
            if k and k in idx_by_trad:
                cs.extend(idx_by_trad[k])
        if cs:
            return best_record(cs)
    # Pass 2: try pinyin, filtered by Chinese agreement if our row has Chinese.
    for idx_by_py, _, _ in indexes:
        cs = idx_by_py.get(key_py) or []
        if require_chinese:
            cs = [r for r in cs if chinese_agrees(r, ch_simp_keys, ch_trad_keys)]
        b = best_record(cs)
        if b:
            return b
    return None

# ---------------------------------------------------------------------------

print('Reading locations.json...')
locations = json.load(open('/tmp/locations.json'))
print(f'  total locations: {len(locations)}')

provinces, commanderies, counties = [], [], []
report_lines = []

stats = {
    'province_polygon': 0, 'province_point': 0, 'province_miss': 0,
    'commandery_polygon': 0, 'commandery_point': 0, 'commandery_miss': 0,
    'county_point': 0, 'county_miss': 0,
    'other_point': 0, 'other_miss': 0,
}

# Pre-collect zhou (province) records by stripping " Zhou" from the
# prefecture-point file (no zhou polygons in our era, just points).
zhou_pts = [r for r in pref_pts if r['type_py'].lower() == 'zhou']
zhou_by_py      = index(zhou_pts, lambda r: r['key_py'])
zhou_by_ch_simp = index(zhou_pts, lambda r: r['key_ch_simp'])
zhou_by_ch_trad = index(zhou_pts, lambda r: r['key_ch_trad'])

for loc in locations:
    name_en = loc.get('name', '')
    name_ch = loc.get('chinese_name', '')
    type_   = (loc.get('type') or '').strip()
    loc_id  = loc['id']

    key_py = normkey(name_en, ENGLISH_TYPE_SUFFIXES)
    key_ch = name_ch.strip()

    # Some of our Chinese names are short (e.g. "安定") while CHGIS has
    # "安定郡". Build extended key forms.
    key_ch_with_jun  = key_ch + '郡' if key_ch else ''
    key_ch_with_guo  = key_ch + '国' if key_ch else ''
    key_ch_with_zhou = key_ch + '州' if key_ch else ''
    key_ch_with_xian = key_ch + '县' if key_ch else ''
    # And the traditional-character equivalents.
    key_ch_trad_with_jun  = key_ch + '郡' if key_ch else ''   # same
    key_ch_trad_with_guo  = key_ch + '國' if key_ch else ''
    key_ch_trad_with_zhou = key_ch + '州' if key_ch else ''
    key_ch_trad_with_xian = key_ch + '縣' if key_ch else ''

    ch_simp_keys = [key_ch, key_ch_with_jun, key_ch_with_guo,
                    key_ch_with_zhou, key_ch_with_xian]
    ch_trad_keys = [key_ch, key_ch_trad_with_jun, key_ch_trad_with_guo,
                    key_ch_trad_with_zhou, key_ch_trad_with_xian]

    matched = None
    require_ch = bool(key_ch)  # disambiguate via Chinese when we have one

    zhou_idx = [(zhou_by_py, zhou_by_ch_simp, zhou_by_ch_trad)]
    pgn_idx  = [(pgn_by_py, pgn_by_ch_simp, pgn_by_ch_trad)]
    pref_idx = [(pref_by_py, pref_by_ch_simp, pref_by_ch_trad)]
    cnty_idx = [(cnty_by_py, cnty_by_ch_simp, cnty_by_ch_trad)]

    if type_ == 'Province':
        matched = search(zhou_idx, key_py, ch_simp_keys, ch_trad_keys, require_ch)
        if matched:
            provinces.append((loc, matched, 'point'))
            stats['province_point'] += 1
        else:
            provinces.append((loc, None, None))
            stats['province_miss'] += 1

    elif type_ == 'Commandery':
        # Prefer polygons; fall back to prefecture points.
        matched = search(pgn_idx, key_py, ch_simp_keys, ch_trad_keys, require_ch)
        if matched:
            commanderies.append((loc, matched, 'polygon'))
            stats['commandery_polygon'] += 1
        else:
            matched = search(pref_idx, key_py, ch_simp_keys, ch_trad_keys, require_ch)
            if matched:
                commanderies.append((loc, matched, 'point'))
                stats['commandery_point'] += 1
            else:
                commanderies.append((loc, None, None))
                stats['commandery_miss'] += 1

    elif type_ == 'County':
        matched = search(cnty_idx, key_py, ch_simp_keys, ch_trad_keys, require_ch)
        if matched:
            counties.append((loc, matched, 'point'))
            stats['county_point'] += 1
        else:
            counties.append((loc, None, None))
            stats['county_miss'] += 1

    elif type_ in ('City', 'Settlement', 'Pass', 'Structure/Building'):
        # Below county level — try the county-points file as a best
        # effort (e.g. settlement named like a known county seat).
        matched = search(cnty_idx, key_py, ch_simp_keys, ch_trad_keys, require_ch)
        if matched:
            counties.append((loc, matched, 'point'))
            stats['other_point'] += 1
        else:
            counties.append((loc, None, None))
            stats['other_miss'] += 1

# ---------------------------------------------------------------------------
# Build solutions JSON entries

def entry_for(loc, m, kind):
    if m.get('type_py', '').startswith('Zhou (derived'):
        src = (f'CHGIS v6 — province polygon derived by geometric union '
               f'of its in-era commandery polygons')
    else:
        src = (f'CHGIS v6 ({m["type_py"]}) "{m["name_py"]}" {m["name_ch"]} '
               f'(BEG={int(m["beg"])} END={int(m["end"])})')
    e = {
        'id': loc['id'],
        '_note': f'name={loc["name"]!r} matched -> {m["name_py"]} / {m["name_ch"]}',
        'notes_append':
            f'Map geometry derived from {src}. '
            f'Licensed CC BY-NC-SA-equivalent; non-commercial use only.',
    }
    if kind == 'polygon':
        e['geojson'] = m['geom']
    else:
        # point
        lng, lat = m['geom']['__point__']
        e['latitude'] = round(lat, 6)
        e['longitude'] = round(lng, 6)
    return e

def emit(filename, items):
    payload = [entry_for(loc, m, kind) for (loc, m, kind) in items if m]
    path = f'{OUT_DIR}/{filename}'
    with open(path, 'w') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f'  wrote {path:55s} ({len(payload)} entries)')
    return payload

# ---------------------------------------------------------------------------
# Derive province polygons by unioning their in-era commanderies' polygons.
# CHGIS doesn't ship Zhou polygons for our era, but every commandery in
# a province had a polygon, and aggregating them reconstructs the
# province's geographic extent.

from shapely.geometry import shape as shp_from_geojson, mapping as shp_to_geojson
from shapely.ops import unary_union

print()
print('Deriving province polygons from commandery unions...')

# map: province name → list of shapely polygons from matched commanderies
prov_polys = {}
for (cm_loc, cm_match, kind) in commanderies:
    if kind != 'polygon' or cm_match is None:
        continue
    chain = cm_loc.get('parent_chain') or []
    # The province sits at the top of the chain — last (most distant)
    # ancestor in our dump format.
    if not chain:
        continue
    prov_name = chain[-1]
    prov_polys.setdefault(prov_name, []).append(cm_match['geom'])

# Replace any province whose name appears in prov_polys with a union
# polygon. Provinces NOT in prov_polys keep their point (from earlier),
# or fall through with no match.
prov_outputs = []
for (p_loc, p_match, p_kind) in provinces:
    pname = p_loc['name']
    geoms = prov_polys.get(pname, [])
    if geoms:
        try:
            shp_objs = [shp_from_geojson(g) for g in geoms]
            unioned = unary_union(shp_objs)
            geojson = shp_to_geojson(unioned)
            # Normalise to Polygon / MultiPolygon — unary_union can
            # collapse to a single Polygon when commanderies abut cleanly.
            if geojson['type'] not in ('Polygon', 'MultiPolygon'):
                raise ValueError(f"unexpected geom type: {geojson['type']}")
            synth = {
                'name_py': f'(derived: union of {len(geoms)} commandery polygons)',
                'name_ch': '',
                'type_py': 'Zhou (derived)',
                'beg': ERA_LO,
                'end': ERA_HI,
                'geom': geojson,
                'mid': ERA_MID,
            }
            prov_outputs.append((p_loc, synth, 'polygon'))
            stats['province_polygon'] = stats.get('province_polygon', 0) + 1
            print(f'  ✓ {pname:<20} {len(geoms)} commandery polygons -> {geojson["type"]}')
        except Exception as e:
            # Fall back to whatever the point-match gave us, if any.
            prov_outputs.append((p_loc, p_match, p_kind))
            print(f'  ✗ {pname:<20} union failed ({e}), keeping point match')
    else:
        # No commandery polygons available — keep whatever we already had.
        prov_outputs.append((p_loc, p_match, p_kind))
        if p_match is None:
            print(f'  - {pname:<20} no commandery polygons available')

# Province stats: recompute now that polygons replaced some points
stats['province_polygon'] = sum(1 for _, m, k in prov_outputs if k == 'polygon')
stats['province_point']   = sum(1 for _, m, k in prov_outputs if k == 'point')
stats['province_miss']    = sum(1 for _, m, k in prov_outputs if m is None)

print()
print('Writing solutions files...')
emit('locations-geo-provinces.json',    prov_outputs)
emit('locations-geo-commanderies.json', commanderies)
emit('locations-geo-counties.json',     counties)

# ---------------------------------------------------------------------------
# Match report — every location, matched or not, with reason.

with open(f'{OUT_DIR}/match-report.txt', 'w') as fp:
    fp.write(f'CHGIS v6 → rotk.net Location matching report\n')
    fp.write(f'Era window: {ERA_LO}-{ERA_HI} AD\n\n')
    fp.write(f'STATS:\n')
    for k, v in stats.items():
        fp.write(f'  {k:30s} {v}\n')
    fp.write(f'\n\n')

    def section(title, items):
        fp.write(f'==== {title} ({len(items)}) ====\n')
        for loc, m, kind in items:
            if m:
                fp.write(f'  ✓ [{loc["id"]:>5}] {loc["name"]!s:35s}'
                         f' -> {kind:8s} {m["name_py"]!s:25s}'
                         f' {m["name_ch"]} ({int(m["beg"])}-{int(m["end"])})\n')
            else:
                fp.write(f'  ✗ [{loc["id"]:>5}] {loc["name"]!s:35s}'
                         f' no match\n')
        fp.write('\n')

    section('PROVINCES',    prov_outputs)
    section('COMMANDERIES', commanderies)
    section('COUNTIES + below-county',     counties)

print(f'  wrote {OUT_DIR}/match-report.txt')

print()
print('STATS:')
for k, v in stats.items():
    print(f'  {k:30s} {v}')
