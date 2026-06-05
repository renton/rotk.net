// map_base.js — shared Leaflet rendering used by both `/map` and the
// per-chapter mini-map in the chapter sidebar. Exposes a single
// `window.RotkMap.create({...})` factory that returns a controller
// object: `{ map, highlight(id), invalidate() }`.
//
// Inputs (`items`): array of objects in the same shape the /map view
// emits — { id, name, chinese_name, type_name, icon, bg_colour,
// font_colour, border_colour, latitude, longitude, geojson }. The
// factory picks a pin for lat/lng items and a polygon overlay for
// geojson items; lat/lng takes precedence when both are set.

(function () {
  'use strict';

  function create({ containerId, items, fitBounds = true, mapOptions = {} }) {
    const defaults = {
      minZoom: 3,
      maxZoom: 12,
      center: [34.0, 110.0],
      zoom: 5,
    };
    const opts = Object.assign({}, defaults, mapOptions);
    const map = L.map(containerId, {
      minZoom: opts.minZoom,
      maxZoom: opts.maxZoom,
    }).setView(opts.center, opts.zoom);

    L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}',
      {
        attribution:
          'Tiles &copy; <a href="https://www.esri.com/" target="_blank" rel="noopener">Esri</a>' +
          ' &mdash; sources: USGS, NOAA, AAFC, NRCan',
        maxZoom: 13,
      }
    ).addTo(map);

    const layersById = {};
    (items || []).forEach(it => {
      let layer = null;
      if (it.latitude != null && it.longitude != null) {
        layer = addPin(map, it);
      } else if (it.geojson) {
        layer = addPolygon(map, it);
      }
      if (layer) layersById[it.id] = layer;
    });

    if (fitBounds && Object.keys(layersById).length) {
      const group = L.featureGroup(Object.values(layersById));
      try {
        map.fitBounds(group.getBounds(), { padding: [30, 30], maxZoom: 7 });
      } catch (_) { /* empty bounds */ }
    }

    return {
      map,
      // Pan to + open the popup for a given Location id, with a
      // brief CSS flash so the user can spot which one was clicked.
      highlight(id) {
        const layer = layersById[id];
        if (!layer) return false;
        try {
          if (layer.getLatLng) {
            map.panTo(layer.getLatLng());
          } else if (layer.getBounds) {
            map.fitBounds(layer.getBounds(), { padding: [40, 40], maxZoom: 7 });
          }
        } catch (_) { /* swallow — keep popup behaviour even if pan fails */ }
        if (layer.openPopup) {
          // Defer so panTo's animation settles before the popup opens.
          setTimeout(() => layer.openPopup(), 80);
        }
        flashLayer(layer);
        return true;
      },
      // Call after the map's container becomes visible — Leaflet needs
      // this to recompute its tile grid when initialised inside an
      // accordion / tab / display:none element.
      invalidate() { map.invalidateSize(); },
    };
  }

  function addPin(map, it) {
    const typeColor = colorForType(it.type_name, it.bg_colour);
    const html =
      `<div class="map-pin" style="` +
        `background:${typeColor};` +
        `border-color:${darken(typeColor)};` +
        `color:#ffffff;">` +
        (it.icon ? `<i class="${escapeAttr(it.icon)}" aria-hidden="true"></i>` : '') +
      `</div>`;
    const icon = L.divIcon({
      className: '',
      html,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
    const marker = L.marker([it.latitude, it.longitude], { icon, title: it.name });
    marker.bindPopup(popupHtml(it));
    marker.addTo(map);
    return marker;
  }

  function addPolygon(map, it) {
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

  function popupHtml(it) {
    const chinese = it.chinese_name
      ? `<span class="map-popup-zh">${escapeHtml(it.chinese_name)}</span>` : '';
    const type = it.type_name
      ? `<div class="map-popup-type">${escapeHtml(it.type_name)}</div>` : '';
    return (
      `<div class="map-popup-title">` +
        `<a href="/locations/edit/${it.id}">${escapeHtml(it.name)}</a>${chinese}` +
      `</div>` + type
    );
  }

  // Brief visual pulse on the layer to draw the eye after a click —
  // a yellow border that fades over ~700ms.
  function flashLayer(layer) {
    if (!layer.setStyle && !(layer.getElement && layer.getElement())) return;
    // Pins: marker.getElement() returns the wrapper div.
    const el = layer.getElement && layer.getElement();
    if (el) {
      el.classList.remove('map-pin-flash');
      // Force reflow so the animation restarts on repeat clicks.
      void el.offsetWidth;
      el.classList.add('map-pin-flash');
      return;
    }
    // Polygons: cycle the weight + colour briefly via setStyle.
    if (layer.setStyle) {
      const orig = (layer.options && layer.options.style && layer.options.style()) || {};
      layer.setStyle({ weight: 3, color: '#ffc107' });
      setTimeout(() => layer.setStyle({ weight: orig.weight || 1.5, color: orig.color || '#666' }), 700);
    }
  }

  // -------- shared helpers (colour hash, escape) --------

  function hashHue(s) {
    let h = 5381;
    s = String(s || '');
    for (let i = 0; i < s.length; i++) {
      h = ((h * 33) ^ s.charCodeAt(i)) | 0;
    }
    return ((h % 360) + 360) % 360;
  }

  function colorForType(typeName, fallback) {
    const norm = (fallback || '').toLowerCase().replace(/[^a-f0-9]/g, '');
    const isWhite = norm === '' || norm === 'fff' || norm === 'ffffff';
    if (!isWhite) return fallback;
    const hue = hashHue('type:' + (typeName || 'unknown'));
    return `hsl(${hue}, 55%, 45%)`;
  }

  function darken(s) {
    const m = /hsl\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)%\s*,\s*(-?\d+(?:\.\d+)?)%\s*\)/i.exec(s);
    if (m) {
      const h = parseFloat(m[1]);
      const sat = parseFloat(m[2]);
      const li = Math.max(0, parseFloat(m[3]) - 12);
      return `hsl(${h}, ${sat}%, ${li}%)`;
    }
    return '#444';
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

  // Expose under a single global. Both /map and the chapter sidebar
  // load this file first, then call RotkMap.create(...).
  window.RotkMap = { create };
})();
