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
  // How the map is framed. On first reveal we "cover" the container (fill
  // it, cropping the longer axis) rather than image_panzoom's default
  // "contain" fit, which leaves the map looking small in the narrow
  // sidebar. Focusing a location zooms in only modestly from there so the
  // surrounding area stays visible.
  var POINT_FOCUS_DELTA = 0.5;   // zoom levels in from the cover view for a pin
  var SHAPE_FOCUS_PAD = 1.5;     // extra fitBounds padding for a line/region
  var HIGHLIGHT_STYLE = { color: '#f39c12', weight: 5 };

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

  // ---- framing ------------------------------------------------------------
  // Fill the container with the map image (cover, not contain), centred.
  // Runs once per viewer on first reveal; later reveals just re-measure so
  // a reader's manual zoom/pan is preserved.
  function frameContainer(mapEl) {
    var lmap = mapEl && mapEl._panzoomMap;
    var b = mapEl && mapEl._panzoomBounds;
    if (!lmap || !b) return;
    lmap.invalidateSize();
    var size = lmap.getSize();
    if (!size.x || !size.y) return;         // still hidden — try again later
    var imgH = b[1][0], imgW = b[1][1];
    // CRS.Simple: screen px = map units * 2^zoom, so the zoom that makes the
    // image fill an axis is log2(containerPx / imagePx). Cover = the larger.
    var zW = Math.log(size.x / imgW) / Math.LN2;
    var zH = Math.log(size.y / imgH) / Math.LN2;
    var cover = Math.max(zW, zH);
    var maxZ = lmap.getMaxZoom();
    if (cover > maxZ) cover = maxZ;
    lmap.setView([imgH / 2, imgW / 2], cover, { animate: false });
    mapEl._pmCoverZoom = cover;
    mapEl._pmFramed = true;
  }

  // Cover-frame the visible viewer(s) inside a revealed container (first
  // time only); otherwise just re-measure.
  function frameVisibleIn(container) {
    if (!container || !container.querySelectorAll) return;
    container.querySelectorAll('.image-panzoom[data-pm-map-id]')
      .forEach(function (el) {
        if (el.offsetParent === null) return;   // hidden (d-none / collapsed)
        if (el._pmFramed) {
          if (el._panzoomMap) el._panzoomMap.invalidateSize();
        } else {
          frameContainer(el);
        }
      });
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
      if (!viewer) return;
      if (viewer._pmFramed) {
        if (viewer._panzoomMap) viewer._panzoomMap.invalidateSize();
      } else {
        frameContainer(viewer);
      }
    });
  });

  // ---- focus (pan + modest zoom, keeping surroundings in view) ------------
  function focusLayer(layer, mapEl) {
    var lmap = mapEl && mapEl._panzoomMap;
    if (!lmap || !layer) return;
    if (layer.getBounds) {
      var b = layer.getBounds();
      if (b && b.isValid()) { lmap.fitBounds(b.pad(SHAPE_FOCUS_PAD)); return; }
    }
    if (layer.getLatLng) {
      // Zoom in only a little from the province cover view so the reader
      // still sees the surrounding area.
      var base = (mapEl._pmCoverZoom !== undefined)
        ? mapEl._pmCoverZoom : lmap.getZoom();
      var z = Math.min(lmap.getMaxZoom(), base + POINT_FOCUS_DELTA);
      lmap.setView(layer.getLatLng(), z);
    }
  }

  // The last-focused placement stays highlighted (golden) until another
  // is chosen, so the reader keeps a visual anchor after the pan settles.
  var activeLayer = null;

  function clearHighlight() {
    if (!activeLayer) return;
    if (activeLayer.setStyle) {
      activeLayer.setStyle(STYLE);
    } else if (activeLayer._icon) {
      activeLayer._icon.classList.remove('pm-marker-active');
    }
    activeLayer = null;
  }

  function highlight(layer) {
    if (!layer) return;
    clearHighlight();
    activeLayer = layer;
    if (layer.setStyle) {
      // Brief thick flash, then settle into the persistent highlight.
      layer.setStyle({ color: '#f39c12', weight: 7 });
      setTimeout(function () {
        if (activeLayer === layer) layer.setStyle(HIGHLIGHT_STYLE);
      }, 600);
    } else if (layer._icon) {
      layer._icon.classList.add('pm-marker-active');
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
      // Establish the cover baseline (and _pmCoverZoom) if this viewer
      // hasn't been shown yet, so the focus zoom is relative to it.
      if (mapEl && !mapEl._pmFramed) frameContainer(mapEl);
      else if (mapEl && mapEl._panzoomMap) mapEl._panzoomMap.invalidateSize();
      var layer = LAYERS[locId];
      if (!layer) return;
      focusLayer(layer, mapEl);
      highlight(layer);
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

  // ---- cover-frame each viewer the first time it's revealed --------------
  // image_panzoom.js registers its own shown.bs.* handlers first (it loads
  // before us) and does its contain-fit; ours runs after and overrides to
  // the cover framing.
  document.addEventListener('shown.bs.collapse', function (e) {
    if (e.target && e.target.id === 'collapseMap') frameVisibleIn(e.target);
  });
  document.addEventListener('shown.bs.tab', function (e) {
    var sel = e.target.getAttribute('data-bs-target');
    if (sel && sel.indexOf('#pm-pane-') === 0) {
      frameVisibleIn(document.querySelector(sel));
    }
  });

  // Locations-list row clicks are handled in chapter.js (so they share
  // the prose click's sidebar-scroll-to-map behaviour) — they call
  // rotkChapterProvinceMap.showLocation() through showLocationOnMap().
});
