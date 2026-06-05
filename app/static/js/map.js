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

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 18,
  }).addTo(map);

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
    const html =
      `<div class="map-pin" style="` +
        `background:${escapeAttr(it.bg_colour)};` +
        `border-color:${escapeAttr(it.border_colour)};` +
        `color:${escapeAttr(it.font_colour)};">` +
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
    const layer = L.geoJSON(it.geojson, {
      style: () => ({
        color: it.border_colour,
        weight: 1,
        fillColor: it.bg_colour,
        fillOpacity: 0.25,
      }),
    });
    layer.bindPopup(popupHtml(it));
    layer.addTo(map);
    return layer;
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
