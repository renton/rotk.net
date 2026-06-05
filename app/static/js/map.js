// Map view — Leaflet glue.
//
// One inline JSON blob (`#map-items`) drives the entire page. Each
// item has either lat/lng (renders as a pin) or geojson (renders as
// a polygon overlay). The route enforces precedence — a row with
// BOTH only ships lat/lng — so this code never has to choose.

(function () {
  'use strict';

  const items = readJson('map-items');

  // Centered on Luoyang-ish (~34.7N, 112.5E) at a zoom that frames
  // the Three Kingdoms-era heartland. The bounds-fit at the end will
  // override if any items actually sit somewhere far from this.
  const map = L.map('map', {
    minZoom: 3,
    maxZoom: 12,
  }).setView([34.0, 110.0], 5);

  // ESRI World Terrain Base — shaded relief + water with no roads or
  // labels, so modern Chinese geography doesn't clutter a Three
  // Kingdoms era map. Tile URL pattern uses {y}/{x} order
  // (server.arcgisonline.com is ArcGIS-style, not OSM-style).
  L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}',
    {
      attribution:
        'Tiles &copy; <a href="https://www.esri.com/" target="_blank" rel="noopener">Esri</a>' +
        ' &mdash; sources: USGS, NOAA, AAFC, NRCan',
      maxZoom: 13,
    }
  ).addTo(map);

  const layers = [];

  items.forEach(it => {
    if (it.latitude != null && it.longitude != null) {
      layers.push(addPin(it));
    } else if (it.geojson) {
      layers.push(addPolygon(it));
    }
  });

  // If we added anything, fit the view to the layer bounds so the
  // user doesn't open the page to a sea of OSM with no markers in
  // sight. Skipped when there are no positioned locations yet.
  if (layers.length) {
    const group = L.featureGroup(layers);
    map.fitBounds(group.getBounds(), { padding: [40, 40], maxZoom: 7 });
  }

  function addPin(it) {
    // Per-location-type colour: hash the type_name into a stable HSL
    // hue so all "Commandery" pins share one colour, all "County"
    // pins another, etc. Falls back to the type's stored bg_colour
    // when it's set to something other than white.
    const typeColor = colorForType(it.type_name, it.bg_colour);
    const html =
      `<div class="map-pin" style="` +
        `background:${typeColor};` +
        `border-color:${darkenHex(typeColor)};` +
        `color:#ffffff;">` +
        (it.icon ? `<i class="${escapeAttr(it.icon)}" aria-hidden="true"></i>` : '') +
      `</div>`;
    const icon = L.divIcon({
      className: '',  // suppress Leaflet's default class
      html,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
    const marker = L.marker([it.latitude, it.longitude], { icon, title: it.name }).addTo(map);
    marker.bindPopup(popupHtml(it));
    return marker;
  }

  function addPolygon(it) {
    // Per-polygon colour: hash the location name. Translucent fill
    // (alpha 0.3) so terrain shows through; full-opacity border in
    // the same hue for crispness. Same name → same colour every
    // page load.
    const hue = hashHue(it.name);
    const fill = `hsl(${hue}, 65%, 50%)`;
    const layer = L.geoJSON(it.geojson, {
      style: () => ({
        color: fill,
        weight: 1.5,
        fillColor: fill,
        fillOpacity: 0.3,
      }),
    });
    layer.bindPopup(popupHtml(it));
    layer.addTo(map);
    return layer;
  }

  // -------- colour helpers --------

  // djb2-ish hash → HSL hue 0..359. Deterministic per string, so the
  // colour assignment is stable across page loads.
  function hashHue(s) {
    let h = 5381;
    s = String(s || '');
    for (let i = 0; i < s.length; i++) {
      h = ((h * 33) ^ s.charCodeAt(i)) | 0;
    }
    return ((h % 360) + 360) % 360;
  }

  function colorForType(typeName, fallback) {
    // If the LocationType had a real (non-white) bg_colour configured
    // via the admin UI, use it. Otherwise hash the type name to get a
    // stable per-type colour. We deliberately don't trust an
    // unconfigured "#ffffff" since it would render the pin invisible.
    const norm = (fallback || '').toLowerCase().replace(/[^a-f0-9]/g, '');
    const isWhite = norm === '' || norm === 'fff' || norm === 'ffffff';
    if (!isWhite) return fallback;
    const hue = hashHue('type:' + (typeName || 'unknown'));
    return `hsl(${hue}, 55%, 45%)`;
  }

  // Darken an HSL string (or hex) by ~12% for the border. Cheap
  // implementation: parse the lightness out of "hsl(h, s%, l%)" and
  // drop it; for anything else just fall back to a fixed darker grey.
  function darkenHex(s) {
    const m = /hsl\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)%\s*,\s*(-?\d+(?:\.\d+)?)%\s*\)/i.exec(s);
    if (m) {
      const h = parseFloat(m[1]);
      const sat = parseFloat(m[2]);
      const li = Math.max(0, parseFloat(m[3]) - 12);
      return `hsl(${h}, ${sat}%, ${li}%)`;
    }
    return '#444';
  }

  function popupHtml(it) {
    const chinese = it.chinese_name
      ? `<span class="map-popup-zh">${escapeHtml(it.chinese_name)}</span>` : '';
    const type = it.type_name
      ? `<div class="map-popup-type">${escapeHtml(it.type_name)}</div>` : '';
    return (
      `<div class="map-popup-title">` +
        `<a href="/locations/edit/${it.id}">${escapeHtml(it.name)}</a>${chinese}` +
      `</div>` +
      type
    );
  }

  function readJson(id) {
    const el = document.getElementById(id);
    if (!el) return [];
    try { return JSON.parse(el.textContent); }
    catch (_) { return []; }
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
  function escapeAttr(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
})();
