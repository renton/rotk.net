/* chapter_province_map.js — the chapter sidebar's interactive
 * province-map panel.
 *
 * Rides on image_panzoom.js: each `.image-panzoom[data-pm-map-id]` is a
 * Leaflet CRS.Simple viewer over one province-map image. This module
 * draws that map's ProvinceMapPlacement overlays (pins / lines / regions)
 * for the chapter's own locations, runs the per-province inner map
 * switcher, and exposes `window.rotkChapterProvinceMap.showLocation(id)`
 * so a click on a prose ref or a Locations-list row opens the Map
 * accordion, activates the right province tab + map, and pans / pulses
 * the placement.
 *
 * Placement geometry is IMAGE-PIXEL [x, y]; a CRS.Simple latlng is (y, x),
 * so toLatLng swaps (same convention as province_map_editor.js).
 */
document.addEventListener('DOMContentLoaded', function () {
  'use strict';

  var dataEl = document.getElementById('chapter-province-maps-data');
  var accordionEl = document.getElementById('collapseMap');
  if (!dataEl || !accordionEl || typeof L === 'undefined') return;

  var provinces;
  try { provinces = JSON.parse(dataEl.textContent); } catch (_) { return; }
  if (!provinces || !provinces.length) return;

  var PLACED = {};             // locId -> {provinceId, mapId}
  var LAYERS = {};             // locId -> Leaflet layer
  var placementsByMap = {};    // mapId -> [placement, ...]

  provinces.forEach(function (prov) {
    (prov.maps || []).forEach(function (m) {
      placementsByMap[m.map_id] = m.placements || [];
      (m.placements || []).forEach(function (pl) {
        PLACED[pl.location_id] = { provinceId: prov.province_id, mapId: m.map_id };
      });
    });
  });

  // ---- render helpers -----------------------------------------------------
  var STYLE = { color: '#c0392b', weight: 3 };

  function toLatLng(xy) { return [xy[1], xy[0]]; }   // [x,y] -> [lat=y, lng=x]

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;',
               '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function iconFor(icon) {
    return L.divIcon({
      className: 'pme-marker',
      html: '<i class="' + (icon || 'fa-solid fa-location-dot') + '"></i>',
      iconSize: [22, 22],
      iconAnchor: [11, 11]
    });
  }

  function popupHtml(pl) {
    return '<div class="pm-popup"><strong>' + escapeHtml(pl.name) + '</strong>' +
      (pl.type_name
        ? '<div class="small text-muted">' +
          (pl.icon ? '<i class="' + escapeHtml(pl.icon) + ' me-1"></i>' : '') +
          escapeHtml(pl.type_name) + '</div>'
        : '') +
      '</div>';
  }

  function layerFor(pl) {
    var layer;
    if (pl.kind === 'point') {
      layer = L.marker(toLatLng(pl.geometry), { icon: iconFor(pl.icon) });
    } else if (pl.kind === 'line') {
      layer = L.polyline(pl.geometry.map(toLatLng), STYLE);
    } else {
      layer = L.polygon(pl.geometry.map(toLatLng), STYLE);
    }
    layer.bindPopup(popupHtml(pl));
    return layer;
  }

  // ---- draw each map's placements once its viewer is ready ----------------
  function drawOnMap(mapEl) {
    if (mapEl._pmDrawn || !mapEl._panzoomMap) return;
    mapEl._pmDrawn = true;
    var mapId = parseInt(mapEl.getAttribute('data-pm-map-id'), 10);
    (placementsByMap[mapId] || []).forEach(function (pl) {
      LAYERS[pl.location_id] = layerFor(pl).addTo(mapEl._panzoomMap);
    });
  }

  document.querySelectorAll('.image-panzoom[data-pm-map-id]').forEach(function (mapEl) {
    if (mapEl._panzoomMap) {
      drawOnMap(mapEl);
    } else {
      mapEl.addEventListener('panzoom:ready', function () { drawOnMap(mapEl); },
                             { once: true });
    }
  });

  // ---- inner map switcher (provinces with several maps) -------------------
  function ensureFitted(mapEl) {
    var lmap = mapEl && mapEl._panzoomMap;
    if (!lmap) return;
    lmap.invalidateSize();
    if (mapEl._panzoomBounds) lmap.fitBounds(mapEl._panzoomBounds);
  }

  // Reveal the given map within a province pane; hide the rest. Returns
  // the shown `.image-panzoom` element (or null).
  function showMapWrap(provinceId, mapId) {
    var pane = document.getElementById('pm-pane-' + provinceId);
    if (!pane) return null;
    var shownViewer = null;
    pane.querySelectorAll('.pm-map-wrap').forEach(function (wrap) {
      var match = parseInt(wrap.getAttribute('data-map-id'), 10) === mapId;
      wrap.classList.toggle('d-none', !match);
      if (match) shownViewer = wrap.querySelector('.image-panzoom');
    });
    var sel = pane.querySelector('.pm-map-switcher');
    if (sel) sel.value = String(mapId);
    return shownViewer;
  }

  document.querySelectorAll('.pm-map-switcher').forEach(function (sel) {
    sel.addEventListener('change', function () {
      var provinceId = parseInt(sel.getAttribute('data-province-id'), 10);
      var viewer = showMapWrap(provinceId, parseInt(sel.value, 10));
      if (viewer) ensureFitted(viewer);
    });
  });

  // ---- pan + pulse --------------------------------------------------------
  function panTo(layer, mapEl) {
    var lmap = mapEl && mapEl._panzoomMap;
    if (!lmap || !layer) return;
    if (layer.getBounds) {
      var b = layer.getBounds();
      if (b && b.isValid()) { lmap.fitBounds(b.pad(0.5)); return; }
    }
    if (layer.getLatLng) {
      lmap.setView(layer.getLatLng(), Math.max(lmap.getZoom(), 1));
    }
  }

  function pulse(layer) {
    if (!layer) return;
    if (layer.setStyle) {
      layer.setStyle({ color: '#f39c12', weight: 6 });
      setTimeout(function () { layer.setStyle(STYLE); }, 1200);
    } else if (layer._icon) {
      layer._icon.classList.add('pme-pulse');
      setTimeout(function () {
        if (layer._icon) layer._icon.classList.remove('pme-pulse');
      }, 1200);
    }
  }

  function activateProvinceTab(provinceId) {
    var btn = document.getElementById('pm-tab-' + provinceId);
    if (!btn) return;
    if (window.bootstrap && bootstrap.Tab) {
      bootstrap.Tab.getOrCreateInstance(btn).show();
    } else {
      btn.click();
    }
  }

  function doShow(locId) {
    var p = PLACED[locId];
    if (!p) return;
    activateProvinceTab(p.provinceId);
    showMapWrap(p.provinceId, p.mapId);
    var mapEl = document.querySelector(
      '.image-panzoom[data-pm-map-id="' + p.mapId + '"]');
    // Give the tab / wrap reveal a moment to lay out before measuring.
    setTimeout(function () {
      ensureFitted(mapEl);
      var layer = LAYERS[locId];
      if (!layer) return;
      panTo(layer, mapEl);
      pulse(layer);
      if (layer.openPopup) layer.openPopup();
    }, 220);
  }

  // ---- public API ---------------------------------------------------------
  window.rotkChapterProvinceMap = {
    showLocation: function (locId) {
      locId = parseInt(locId, 10);
      if (!PLACED[locId]) return false;
      var collapse = bootstrap.Collapse.getOrCreateInstance(
        accordionEl, { toggle: false });
      collapse.show();
      if (accordionEl.classList.contains('show')) {
        doShow(locId);
      } else {
        var onShown = function () {
          accordionEl.removeEventListener('shown.bs.collapse', onShown);
          doShow(locId);
        };
        accordionEl.addEventListener('shown.bs.collapse', onShown);
      }
      return true;
    }
  };

  // ---- Locations-list rows (this wiring used to live in chapter_map.js) ---
  document.querySelectorAll('[data-on-province-map]').forEach(function (row) {
    var id = parseInt(row.getAttribute('data-on-province-map'), 10);
    if (!id) return;
    var fire = function (evt) {
      var tag = (evt.target && evt.target.tagName) || '';
      if (tag === 'A' || tag === 'BUTTON' ||
          (evt.target.closest && evt.target.closest('a,button'))) return;
      evt.preventDefault();
      window.rotkChapterProvinceMap.showLocation(id);
    };
    row.addEventListener('click', fire);
    row.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') fire(e);
    });
  });
});
