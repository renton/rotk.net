// Map view glue — defers all Leaflet rendering to RotkMap.create()
// (see map_base.js, also used by the chapter sidebar's mini-map).
(function () {
  'use strict';
  const items = readJson('map-items');
  window.__rotkMap = RotkMap.create({
    containerId: 'map',
    items,
    fitBounds: true,
  });

  function readJson(id) {
    const el = document.getElementById(id);
    if (!el) return [];
    try { return JSON.parse(el.textContent); }
    catch (_) { return []; }
  }
})();
