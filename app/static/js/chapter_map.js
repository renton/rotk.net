// chapter_map.js — drives the per-chapter mini-map in the sidebar.
//
// Lazy-initialises Leaflet only when the Map accordion is first
// expanded (Leaflet doesn't lay out tiles correctly inside a
// display:none container). After init it also re-invalidates the
// size on every subsequent open in case the container width changed.
//
// Clicking a location item in the sidebar's Locations accordion
// (rows with `data-show-on-map="<id>"`) opens the Map accordion
// and highlights the corresponding pin / polygon.

(function () {
  'use strict';

  const accordionEl = document.getElementById('collapseMap');
  const mapEl = document.getElementById('chapter-map');
  const itemsEl = document.getElementById('chapter-map-items');
  if (!accordionEl || !mapEl || !itemsEl) {
    // No positioned locations for this chapter — accordion was
    // rendered empty; nothing to wire up.
    bindLocationClicks(null);
    return;
  }

  let controller = null;

  function initIfNeeded() {
    if (controller) {
      controller.invalidate();
      return controller;
    }
    let items = [];
    try { items = JSON.parse(itemsEl.textContent); } catch (_) { items = []; }
    controller = RotkMap.create({
      containerId: 'chapter-map',
      items,
      fitBounds: true,
      mapOptions: { zoom: 5 },
    });
    return controller;
  }

  // Bootstrap fires `shown.bs.collapse` after the open animation
  // settles — that's when Leaflet can measure the container.
  accordionEl.addEventListener('shown.bs.collapse', () => initIfNeeded());

  bindLocationClicks(() => {
    // 1. Open the Map accordion if it's closed. Bootstrap's API
    //    no-ops if the panel is already shown.
    const collapse = bootstrap.Collapse.getOrCreateInstance(accordionEl, { toggle: false });
    collapse.show();
    // 2. Wait for the show animation so the map exists and has size,
    //    then highlight. If the panel was already open, the listener
    //    on the trigger element won't fire — fall back to a short
    //    timeout that runs the highlight anyway.
    return initIfNeeded();
  });

  // Public API so chapter.js can route inline .location-ref clicks to
  // the map (open accordion + highlight) without redoing the open /
  // highlight dance itself.
  window.rotkChapterMap = {
    showLocation(id) {
      const collapse = bootstrap.Collapse.getOrCreateInstance(accordionEl, { toggle: false });
      collapse.show();
      if (accordionEl.classList.contains('show')) {
        initIfNeeded().highlight(id);
      } else {
        const onShown = () => {
          accordionEl.removeEventListener('shown.bs.collapse', onShown);
          initIfNeeded().highlight(id);
        };
        accordionEl.addEventListener('shown.bs.collapse', onShown);
      }
    },
  };

  function bindLocationClicks(ensureMapReady) {
    document.querySelectorAll('[data-show-on-map]').forEach(row => {
      const id = parseInt(row.getAttribute('data-show-on-map'), 10);
      if (!id) return;
      const fire = (evt) => {
        // Allow normal interaction on inner links/buttons.
        const tag = (evt.target && evt.target.tagName) || '';
        if (tag === 'A' || tag === 'BUTTON' || evt.target.closest('a,button')) return;
        evt.preventDefault();
        if (!ensureMapReady) return;
        const ctl = ensureMapReady();
        // If the accordion was already open, `shown` won't fire and
        // ctl is ready immediately. If it just opened, give the
        // animation a moment then highlight.
        const accordionOpen = accordionEl.classList.contains('show');
        if (accordionOpen) {
          ctl.highlight(id);
        } else {
          const onShown = () => {
            accordionEl.removeEventListener('shown.bs.collapse', onShown);
            initIfNeeded().highlight(id);
          };
          accordionEl.addEventListener('shown.bs.collapse', onShown);
        }
      };
      row.addEventListener('click', fire);
      row.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') fire(e);
      });
    });
  }
})();
