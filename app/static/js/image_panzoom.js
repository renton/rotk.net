/* image_panzoom.js — reusable drag-to-pan / wheel-to-zoom image viewer
 * (Google-Maps-style interaction on a plain image).
 *
 * Usage: give any element the class `image-panzoom`, a `data-panzoom-src`
 * with the image URL, and an explicit height (inline style or CSS):
 *
 *     <div class="image-panzoom" style="height: 60vh;"
 *          data-panzoom-src="/static/yearmaps/208.png"
 *          data-panzoom-alt="Territorial map of 208 AD"></div>
 *
 * Requires Leaflet (already shipped on map-bearing pages) — the widget is
 * an L.CRS.Simple map with a single image overlay, which gives dragging,
 * wheel zoom, pinch zoom, double-click zoom and +/- controls for free.
 *
 * All `.image-panzoom[data-panzoom-src]` elements are upgraded on
 * DOMContentLoaded; call window.initImagePanzoom(el) for elements added
 * dynamically later.
 *
 * Hidden-container caveat: Leaflet measures its container at init, so a
 * viewer inside a Bootstrap tab pane / collapse that starts hidden comes
 * up 0×0. A document-level shown.bs.tab / shown.bs.collapse listener
 * re-measures (invalidateSize) and does the deferred first fit for any
 * viewer revealed by the transition.
 */
(function () {
  'use strict';

  function fit(el) {
    var map = el._panzoomMap;
    if (!map || !el._panzoomBounds) return;
    map.invalidateSize();
    map.fitBounds(el._panzoomBounds);
    // Allow zooming slightly out past the fitted view, but not into
    // a speck; and keep the image from being flung fully off-screen.
    map.setMinZoom(map.getZoom() - 0.5);
    map.setMaxBounds(L.latLngBounds(el._panzoomBounds).pad(0.25));
    el._panzoomNeedsFit = false;
  }

  function initImagePanzoom(el) {
    if (el._panzoom || typeof L === 'undefined') return;
    var src = el.getAttribute('data-panzoom-src');
    if (!src) return;
    el._panzoom = true;   // double-init guard

    var alt = el.getAttribute('data-panzoom-alt') || '';
    if (alt && !el.getAttribute('aria-label')) {
      el.setAttribute('role', 'img');
      el.setAttribute('aria-label', alt);
    }

    // Load the image first — the overlay bounds come from its natural
    // pixel size, which keeps the aspect ratio true at every zoom.
    var img = new Image();
    img.onload = function () {
      var map = L.map(el, {
        crs: L.CRS.Simple,
        attributionControl: false,
        zoomSnap: 0.25,
        zoomDelta: 0.5,
        wheelPxPerZoomLevel: 90,
        minZoom: -8,          // tightened after the first fit
        maxZoom: 4,
        maxBoundsViscosity: 0.8
      });
      var bounds = [[0, 0], [img.naturalHeight, img.naturalWidth]];
      L.imageOverlay(src, bounds, { alt: alt }).addTo(map);

      el._panzoomMap = map;
      el._panzoomBounds = bounds;
      // Consumers that need the Leaflet map (e.g. the province-map
      // placement editor) listen for this instead of polling.
      el.dispatchEvent(new CustomEvent('panzoom:ready',
                                       { detail: { map: map, bounds: bounds } }));

      if (el.clientWidth > 0 && el.clientHeight > 0) {
        fit(el);
      } else {
        // Hidden right now (e.g. a non-active tab pane) — defer the
        // first fit until a shown.bs.* event reveals us.
        el._panzoomNeedsFit = true;
      }
    };
    img.src = src;
  }

  function refreshWithin(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('.image-panzoom').forEach(function (el) {
      if (!el._panzoomMap) return;
      if (el._panzoomNeedsFit) {
        fit(el);
      } else {
        el._panzoomMap.invalidateSize();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.image-panzoom[data-panzoom-src]')
      .forEach(initImagePanzoom);

    // Bootstrap fires these on the toggle (tab) / the panel (collapse);
    // both bubble to document.
    document.addEventListener('shown.bs.tab', function (event) {
      var sel = event.target.getAttribute('data-bs-target') ||
                event.target.getAttribute('href');
      if (sel) refreshWithin(document.querySelector(sel));
    });
    document.addEventListener('shown.bs.collapse', function (event) {
      refreshWithin(event.target);
    });
  });

  window.initImagePanzoom = initImagePanzoom;
})();
