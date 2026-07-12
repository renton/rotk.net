/* Province-map placement editor.
 *
 * Rides on image_panzoom.js (Leaflet CRS.Simple over the province
 * image; `panzoom:ready` hands us the map). Placement geometry lives
 * in IMAGE-PIXEL coords: a CRS.Simple latlng is (y, x), so we convert
 * on the way in/out — the server stores [x, y] pairs.
 *
 * Modes (from the location type's point_type):
 *   point  — click sets/moves a single marker (location-type FA icon)
 *   line   — freehand: mousedown starts a stroke, mousemove appends
 *            (map dragging disabled while in the mode), mouseup ends;
 *            a new stroke replaces the previous preview
 *   region — each click appends a polygon vertex (≥3 to save)
 *
 * Save POSTs {kind, geometry} JSON; Reset clears the in-progress
 * geometry; Cancel exits the mode and restores the saved layer.
 * Show pans/zooms to a saved placement and pulses it.
 */
document.addEventListener('DOMContentLoaded', function () {
  var payloadEl = document.getElementById('pme-payload');
  var mapEl = document.getElementById('pme-map');
  if (!payloadEl || !mapEl) return;

  var P = JSON.parse(payloadEl.textContent);
  var LOCATIONS = {};
  P.locations.forEach(function (l) { LOCATIONS[l.id] = l; });

  var csrfInput = document.querySelector('#pme-csrf-form input[name="csrf_token"]');
  var CSRF = csrfInput ? csrfInput.value : '';

  var toolbar = document.getElementById('pme-toolbar');
  var tbName = document.getElementById('pme-toolbar-name');
  var tbKind = document.getElementById('pme-toolbar-kind');
  var tbHint = document.getElementById('pme-toolbar-hint');
  var btnSave = document.getElementById('pme-save');
  var btnReset = document.getElementById('pme-reset');
  var btnCancel = document.getElementById('pme-cancel');

  var HINTS = {
    point: 'Click the map to set the point (click again to move it).',
    line: 'Press and drag to draw the line; release to finish. Drawing again replaces it.',
    region: 'Click each corner of the region — at least three. Save when the polygon looks right.'
  };
  var STYLE = { color: '#c0392b', weight: 3 };
  var PREVIEW_STYLE = { color: '#2980b9', weight: 3, dashArray: '6 4' };

  var map = null;
  var savedLayers = {};     // location_id -> Leaflet layer (saved state)
  var mode = null;          // {loc, kind, geometry, layer, drawing}

  // ---- geometry <-> latlng ------------------------------------------------
  function toLatLng(xy) { return [xy[1], xy[0]]; }        // [x,y] -> [lat=y, lng=x]
  function toXY(latlng) {
    return [Math.round(latlng.lng * 100) / 100,
            Math.round(latlng.lat * 100) / 100];
  }

  function iconFor(loc) {
    var cls = loc.icon || 'fa-solid fa-location-dot';
    return L.divIcon({
      className: 'pme-marker',
      html: '<i class="' + cls + '"></i>',
      iconSize: [22, 22],
      iconAnchor: [11, 11]
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;',
               '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function popupHtml(loc) {
    var editUrl = P.location_edit_url_template.replace(/0$/, String(loc.id));
    return '<div class="pme-popup">' +
      '<strong>' + escapeHtml(loc.name) + '</strong>' +
      (loc.type_name
        ? '<div class="small text-muted">' +
          (loc.icon ? '<i class="' + escapeHtml(loc.icon) + ' me-1"></i>' : '') +
          escapeHtml(loc.type_name) +
          ' <span class="fst-italic">(' + escapeHtml(loc.point_type) + ')</span></div>'
        : '') +
      '<a href="' + editUrl + '" target="_blank" rel="noopener" class="small">Edit location</a>' +
      '</div>';
  }

  function layerFor(loc, kind, geometry, preview) {
    var style = preview ? PREVIEW_STYLE : STYLE;
    var layer;
    if (kind === 'point') {
      layer = L.marker(toLatLng(geometry), { icon: iconFor(loc) });
    } else if (kind === 'line') {
      layer = L.polyline(geometry.map(toLatLng), style);
    } else {
      layer = L.polygon(geometry.map(toLatLng), style);
    }
    // Saved layers get a click popup with the location's info;
    // previews stay bare so popups don't fight placement clicks.
    if (!preview) layer.bindPopup(popupHtml(loc));
    return layer;
  }

  // ---- list row state -----------------------------------------------------
  function syncRow(locId) {
    var row = document.getElementById('pme-row-' + locId);
    if (!row) return;
    var placed = !!savedLayers[locId];
    row.querySelector('.pme-status').className =
      'pme-status ' + (placed ? 'text-success' : 'text-muted');
    row.querySelector('.pme-show').classList.toggle('d-none', !placed);
    row.querySelector('.pme-clear').classList.toggle('d-none', !placed);
  }

  function markRow(locId) {
    document.querySelectorAll('#pme-location-list .sidebar-selected')
      .forEach(function (el) { el.classList.remove('sidebar-selected'); });
    var row = document.getElementById('pme-row-' + locId);
    if (row) row.classList.add('sidebar-selected');
  }

  // ---- mode management ----------------------------------------------------
  function updateSaveEnabled() {
    if (!mode) return;
    var g = mode.geometry;
    var ok = mode.kind === 'point' ? !!g
      : mode.kind === 'line' ? (g && g.length >= 2)
      : (g && g.length >= 3);
    btnSave.disabled = !ok;
  }

  function redrawPreview() {
    if (mode.layer) { map.removeLayer(mode.layer); mode.layer = null; }
    if (!mode.geometry) { updateSaveEnabled(); return; }
    mode.layer = layerFor(mode.loc, mode.kind, mode.geometry, true);
    mode.layer.addTo(map);
    updateSaveEnabled();
  }

  function enterMode(loc) {
    if (mode) exitMode();
    mode = { loc: loc, kind: loc.point_type, geometry: null,
             layer: null, drawing: false };
    // Hide the saved layer while re-placing so previews don't overlap.
    if (savedLayers[loc.id]) map.removeLayer(savedLayers[loc.id]);
    toolbar.classList.remove('d-none');
    toolbar.classList.add('d-flex');
    tbName.textContent = loc.name;
    tbKind.textContent = '(' + loc.point_type + ')';
    tbHint.textContent = HINTS[loc.point_type] || '';
    btnSave.disabled = true;
    markRow(loc.id);
    mapEl.classList.add('pme-placing');
    if (loc.point_type === 'line') map.dragging.disable();
  }

  function exitMode() {
    if (!mode) return;
    if (mode.layer) map.removeLayer(mode.layer);
    // Restore the saved layer if we hid it.
    if (savedLayers[mode.loc.id]) savedLayers[mode.loc.id].addTo(map);
    map.dragging.enable();
    mapEl.classList.remove('pme-placing');
    toolbar.classList.add('d-none');
    toolbar.classList.remove('d-flex');
    mode = null;
  }

  // ---- placement interactions --------------------------------------------
  function onMapClick(e) {
    if (!mode) return;
    if (mode.kind === 'point') {
      mode.geometry = toXY(e.latlng);
      redrawPreview();
    } else if (mode.kind === 'region') {
      mode.geometry = mode.geometry || [];
      mode.geometry.push(toXY(e.latlng));
      redrawPreview();
    }
  }

  function onMouseDown(e) {
    if (!mode || mode.kind !== 'line') return;
    mode.drawing = true;
    mode.geometry = [toXY(e.latlng)];   // new stroke replaces previous
    redrawPreview();
  }

  function onMouseMove(e) {
    if (!mode || mode.kind !== 'line' || !mode.drawing) return;
    var xy = toXY(e.latlng);
    var g = mode.geometry;
    var last = g[g.length - 1];
    // Thin the stroke: skip points closer than ~3px to the previous.
    var dx = xy[0] - last[0], dy = xy[1] - last[1];
    if (dx * dx + dy * dy < 9) return;
    g.push(xy);
    redrawPreview();
  }

  function onMouseUp() {
    if (mode && mode.kind === 'line') mode.drawing = false;
  }

  // ---- save / reset / cancel / show / clear -------------------------------
  function saveUrl(locId, del) {
    var tmpl = del ? P.delete_url_template : P.save_url_template;
    return tmpl.replace(/0(\/delete)?$/, del ? locId + '/delete' : String(locId));
  }

  btnSave.addEventListener('click', function () {
    if (!mode || btnSave.disabled) return;
    var loc = mode.loc, kind = mode.kind, geometry = mode.geometry;
    fetch(saveUrl(loc.id, false), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json',
                 'X-CSRFToken': CSRF },
      body: JSON.stringify({ kind: kind, geometry: geometry,
                             csrf_token: CSRF })
    }).then(function (res) { return res.json().then(function (j) { return { ok: res.ok, j: j }; }); })
      .then(function (r) {
        if (!r.ok) { alert(r.j.error || 'Save failed.'); return; }
        if (savedLayers[loc.id]) map.removeLayer(savedLayers[loc.id]);
        savedLayers[loc.id] = layerFor(loc, kind, geometry, false).addTo(map);
        exitMode();
        syncRow(loc.id);
      })
      .catch(function (err) { alert('Save failed: ' + err); });
  });

  btnReset.addEventListener('click', function () {
    if (!mode) return;
    mode.geometry = null;
    mode.drawing = false;
    redrawPreview();
  });

  btnCancel.addEventListener('click', exitMode);

  document.querySelectorAll('.pme-select').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var loc = LOCATIONS[parseInt(btn.getAttribute('data-location-id'), 10)];
      if (loc) enterMode(loc);
    });
  });

  document.querySelectorAll('.pme-show').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var locId = parseInt(btn.getAttribute('data-location-id'), 10);
      var layer = savedLayers[locId];
      if (!layer) return;
      markRow(locId);
      if (layer.getBounds) {
        map.fitBounds(layer.getBounds().pad(0.5));
      } else {
        map.setView(layer.getLatLng(), Math.max(map.getZoom(), 1));
      }
      // Pulse: briefly swap style / bounce the marker via CSS class.
      if (layer.setStyle) {
        layer.setStyle({ color: '#f39c12', weight: 6 });
        setTimeout(function () { layer.setStyle(STYLE); }, 1200);
      } else if (layer._icon) {
        layer._icon.classList.add('pme-pulse');
        setTimeout(function () {
          if (layer._icon) layer._icon.classList.remove('pme-pulse');
        }, 1200);
      }
    });
  });

  document.querySelectorAll('.pme-clear').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var locId = parseInt(btn.getAttribute('data-location-id'), 10);
      var loc = LOCATIONS[locId];
      if (!loc || !confirm('Remove the placement for ' + loc.name + '?')) return;
      fetch(saveUrl(locId, true), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json',
                   'X-CSRFToken': CSRF },
        body: JSON.stringify({ csrf_token: CSRF })
      }).then(function (res) {
        if (!res.ok) { alert('Remove failed.'); return; }
        if (savedLayers[locId]) {
          map.removeLayer(savedLayers[locId]);
          delete savedLayers[locId];
        }
        syncRow(locId);
      });
    });
  });

  // ---- location list filters (commandery AND type, combined) --------------
  var typeFilter = document.getElementById('pme-type-filter');
  var commanderyFilter = document.getElementById('pme-commandery-filter');
  function applyListFilters() {
    var wantType = typeFilter ? typeFilter.value : '';
    var wantCommandery = commanderyFilter ? commanderyFilter.value : '';
    document.querySelectorAll('#pme-location-list > li').forEach(function (row) {
      var hide = false;
      if (wantType && row.getAttribute('data-type-name') !== wantType) {
        hide = true;
      }
      if (wantCommandery &&
          row.getAttribute('data-commandery-id') !== wantCommandery) {
        hide = true;
      }
      row.classList.toggle('d-none', hide);
    });
  }
  if (typeFilter) typeFilter.addEventListener('change', applyListFilters);
  if (commanderyFilter) {
    commanderyFilter.addEventListener('change', applyListFilters);
  }

  // ---- boot ---------------------------------------------------------------
  function boot(theMap) {
    map = theMap;
    map.on('click', onMapClick);
    map.on('mousedown', onMouseDown);
    map.on('mousemove', onMouseMove);
    map.on('mouseup', onMouseUp);
    Object.keys(P.placements).forEach(function (locIdStr) {
      var locId = parseInt(locIdStr, 10);
      var loc = LOCATIONS[locId];
      var pl = P.placements[locIdStr];
      if (!loc || !pl) return;
      savedLayers[locId] = layerFor(loc, pl.kind, pl.geometry, false).addTo(map);
      syncRow(locId);
    });
  }

  if (mapEl._panzoomMap) {
    boot(mapEl._panzoomMap);
  } else {
    mapEl.addEventListener('panzoom:ready', function (e) {
      boot(e.detail.map);
    }, { once: true });
  }
});
