(function () {
  // Bootstrap "lg" breakpoint is 992px; below that we use a modal instead
  // of the sticky sidebar (which has just stacked under the prose).
  var MOBILE_QUERY = '(max-width: 991.98px)';

  function isMobile() {
    return window.matchMedia(MOBILE_QUERY).matches;
  }

  // ---- Link-style cookie (click vs hover) -------------------------------
  // Cookie-backed so it survives across sessions like a real preference.
  // Hover only fires on desktop — on mobile we always fall back to click.
  var LINK_STYLE_COOKIE = 'rotk_link_style';
  var LINK_STYLES = ['click', 'hover'];
  var DEFAULT_LINK_STYLE = 'click';

  function setCookie(name, value, days) {
    var expires = '';
    if (days) {
      var d = new Date();
      d.setTime(d.getTime() + days * 24 * 60 * 60 * 1000);
      expires = '; expires=' + d.toUTCString();
    }
    document.cookie = name + '=' + encodeURIComponent(value) +
      expires + '; path=/; SameSite=Lax';
  }
  function getCookie(name) {
    var parts = document.cookie ? document.cookie.split(';') : [];
    for (var i = 0; i < parts.length; i++) {
      var kv = parts[i].trim();
      if (kv.indexOf(name + '=') === 0) {
        return decodeURIComponent(kv.substring(name.length + 1));
      }
    }
    return null;
  }
  function getLinkStyle() {
    var v = getCookie(LINK_STYLE_COOKIE);
    return LINK_STYLES.indexOf(v) >= 0 ? v : DEFAULT_LINK_STYLE;
  }
  function setLinkStyle(v) {
    if (LINK_STYLES.indexOf(v) < 0) return;
    setCookie(LINK_STYLE_COOKIE, v, 365);
  }

  function sidebarAccordionBody() {
    return document.querySelector('#collapseOne .accordion-body');
  }

  function returnPanelsToSidebar() {
    var modalBody = document.getElementById('character-modal-body');
    var sidebar = sidebarAccordionBody();
    if (!modalBody || !sidebar) return;
    // querySelector restricts to elements — using .firstChild looped over
    // whitespace text nodes too, which don't have .style.
    Array.prototype.forEach.call(
      modalBody.querySelectorAll('.character-panel'),
      function (panel) {
        panel.style.display = 'none';   // hidden in the sidebar; next click re-reveals
        sidebar.appendChild(panel);
      }
    );
  }

  var modalInstance = null;
  function getOrInitModal() {
    if (modalInstance) return modalInstance;
    var modalEl = document.getElementById('character-modal');
    if (!modalEl || typeof bootstrap === 'undefined') return null;
    modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
    // Always move panels back when the modal hides so the sidebar's DOM
    // is whole again (matters if the user resizes to desktop while the
    // modal is up — Bootstrap will hide it, our handler restores state).
    modalEl.addEventListener('hidden.bs.modal', returnPanelsToSidebar);
    return modalInstance;
  }

  function showCharacter(characterId) {
    var panel = document.getElementById('character-panel-' + characterId);
    if (!panel) return;

    if (isMobile()) {
      // Move-into-modal approach. If another panel is already in the
      // modal body (e.g. from a prior open), return it to the sidebar
      // first so we don't pile them up.
      returnPanelsToSidebar();
      var modal = getOrInitModal();
      var modalBody = document.getElementById('character-modal-body');
      if (!modal || !modalBody) return;
      panel.style.display = 'block';
      modalBody.appendChild(panel);
      modal.show();
      return;
    }

    // Desktop: original behaviour — show the panel in the sticky sidebar,
    // open the accordion if it's collapsed.
    document.querySelectorAll('div.character-panel').forEach(function (p) {
      p.style.display = 'none';
    });
    panel.style.display = 'block';

    // Scroll the freshly-shown panel into view within the sticky sidebar
    // so the user lands on the character info even when the click came
    // from the Chapter Characters list further down the column. Defer
    // until after the accordion finishes expanding (otherwise the
    // target's final position is wrong and the scroll lands short).
    var doScrollPanel = function () {
      panel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    };

    var collapseElement = document.getElementById('collapseOne');
    if (collapseElement && !collapseElement.classList.contains('show')) {
      var accordionButton = document.querySelector('#sidebar-character-info .accordion-button');
      if (accordionButton) {
        collapseElement.addEventListener('shown.bs.collapse', doScrollPanel, { once: true });
        accordionButton.click();
      } else {
        doScrollPanel();
      }
    } else {
      doScrollPanel();
    }
  }

  // Two click sources reveal the same Character Info panel:
  //   .character-ref          — inline badge tagged in the prose
  //   .chapter-character-link — row in the "Chapter Characters" sidebar list
  // Both carry data-character-id; we just hand it to showCharacter().
  document.addEventListener('click', function (event) {
    var target = event.target.closest('.character-ref, .chapter-character-link');
    if (!target) {
      return;
    }
    var characterId = target.getAttribute('data-character-id');
    if (characterId) {
      showCharacter(characterId);
    }
  });

  // Event / location inline refs open the matching sidebar accordion,
  // briefly highlight the specific row, and (on desktop only) scroll the
  // RIGHT SIDEBAR — never the main page — so the row lands at the top of
  // the sticky panel. We skip scrolling on mobile: the sidebar stacks
  // under the prose there, so any scroll would move the page and yank the
  // reader off their paragraph.
  // Persistent "last clicked" marker — makes the target findable even
  // if the scroll lands imperfectly. One at a time across the sidebar.
  function markSelected(item) {
    document.querySelectorAll('.sidebar-selected').forEach(function (el) {
      el.classList.remove('sidebar-selected');
    });
    item.classList.add('sidebar-selected');
  }

  // Scroll ONLY the sticky right sidebar (its own overflow container) so
  // `el` sits near the top of the sidebar viewport. Uses the sidebar's
  // own scrollTo — the window is never touched. No-op on mobile, where
  // the sidebar is in normal flow and scrolling would move the page.
  var SIDEBAR_TOP_PAD = 6;
  function scrollSidebarTo(el) {
    if (isMobile() || !el) return;
    var sidebar = document.querySelector('.chapter-sidebar');
    if (!sidebar || !sidebar.scrollTo) return;
    var delta = el.getBoundingClientRect().top -
                sidebar.getBoundingClientRect().top - SIDEBAR_TOP_PAD;
    sidebar.scrollTo({ top: sidebar.scrollTop + delta, behavior: 'smooth' });
  }

  function showAccordionItem(collapseId, itemId) {
    var collapseEl = document.getElementById(collapseId);
    var item = itemId ? document.getElementById(itemId) : null;
    if (!item) return;

    markSelected(item);

    // CSS animates a yellow-fade-out via the .sidebar-flash class.
    // Re-trigger by removing + re-adding (with a reflow in between) so
    // a second click on the same item flashes again.
    item.classList.remove('sidebar-flash');
    void item.offsetWidth;
    item.classList.add('sidebar-flash');

    // Scroll the sidebar (only) so the row lands at the top of the panel.
    var scrollToItem = function () { scrollSidebarTo(item); };
    // Opening/closing accordion panels keeps shifting layout after
    // shown.bs.collapse fires for the opening panel alone. A second
    // corrective scroll after Bootstrap's ~350ms transition has fully
    // settled re-targets the row wherever it ended up.
    var scrollTwice = function () {
      scrollToItem();
      setTimeout(scrollToItem, 420);
    };

    if (collapseEl && typeof bootstrap !== 'undefined') {
      var inst = bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false });
      if (collapseEl.classList.contains('show')) {
        scrollTwice();
      } else {
        collapseEl.addEventListener('shown.bs.collapse', scrollTwice, { once: true });
        inst.show();
      }
    } else {
      scrollTwice();
    }
  }

  // Open the Map accordion, highlight the location on the map, and
  // scroll the Map section to the top of the sticky sidebar. Used
  // when an inline .location-ref is clicked for a geo-positioned
  // location; non-geo locations fall back to the old Locations-
  // accordion behaviour.
  //
  // Scrolls the sidebar (only) so the Province Map heading (#sidebar-map)
  // sits at the top of the sticky panel — the main page never moves.
  function showLocationOnMap(locationId) {
    var mapApi = window.rotkChapterProvinceMap;
    if (!mapApi) return false;
    // Returns false when the location has no province-map placement —
    // let the caller fall back to the Locations accordion.
    if (!mapApi.showLocation(parseInt(locationId, 10))) return false;
    var mapAccordion = document.getElementById('collapseMap');
    var mapHeader = document.getElementById('sidebar-map');
    if (!mapAccordion || !mapHeader) return true;
    var doScroll = function () {
      scrollSidebarTo(mapHeader);
      setTimeout(function () { scrollSidebarTo(mapHeader); }, 420);
    };
    if (mapAccordion.classList.contains('show')) {
      doScroll();
    } else {
      mapAccordion.addEventListener('shown.bs.collapse', doScroll, { once: true });
    }
    return true;
  }

  // A Locations-list row that carries a province-map pin behaves exactly
  // like clicking that location in the prose: open the Province Map
  // accordion, pan/highlight the pin, and scroll the sidebar up to the
  // map. Shared by the click + keyboard handlers below.
  function activateLocationPinRow(row) {
    if (!row) return;
    var rid = row.getAttribute('data-on-province-map');
    if (rid && showLocationOnMap(rid)) markSelected(row);
  }

  document.addEventListener('click', function (event) {
    var ev = event.target.closest('.event-ref');
    if (ev) {
      var eid = ev.getAttribute('data-event-id');
      showAccordionItem('collapseEvents', eid ? 'event-item-' + eid : null);
      return;
    }
    // Locations-list row with a map pin — same treatment as a prose click.
    var pinRow = event.target.closest('li[data-on-province-map]');
    if (pinRow) {
      // Let inner controls (edit pencil, URL links) work normally.
      if (event.target.closest('a, button')) return;
      activateLocationPinRow(pinRow);
      return;
    }
    var loc = event.target.closest('.location-ref');
    if (loc) {
      var lid = loc.getAttribute('data-location-id');
      if (!lid) return;
      // Locations placed on a province map get the map treatment;
      // others have no pin to show, so fall back to the Locations
      // accordion + row-flash like before.
      var item = document.getElementById('location-item-' + lid);
      var onMap = item && item.hasAttribute('data-on-province-map');
      if (onMap && showLocationOnMap(lid)) {
        // The map takes the scroll, but the Locations list still marks
        // this row as the last-clicked location so it's findable when
        // the reader opens that accordion.
        markSelected(item);
        return;
      }
      showAccordionItem('collapseLocations', 'location-item-' + lid);
    }
  });

  // Keyboard activation for the role="button" Locations-list rows.
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    var row = event.target.closest &&
              event.target.closest('li[data-on-province-map]');
    if (!row) return;
    event.preventDefault();
    activateLocationPinRow(row);
  });

  // Hover-to-open for .character-ref. Desktop only — on touch / mobile
  // the dropdown is hidden and click stays the only trigger. A short
  // debounce delay so casual cursor flyovers don't keep swapping the
  // sidebar panel; clearing on mouseleave keeps a quick out-and-back
  // from queuing a stale show.
  var hoverTimer = null;
  document.addEventListener('mouseover', function (event) {
    if (isMobile()) return;
    if (getLinkStyle() !== 'hover') return;
    var ref = event.target.closest('.character-ref');
    if (!ref) return;
    var characterId = ref.getAttribute('data-character-id');
    if (!characterId) return;
    if (hoverTimer) clearTimeout(hoverTimer);
    hoverTimer = setTimeout(function () { showCharacter(characterId); }, 180);
  });
  document.addEventListener('mouseout', function (event) {
    if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }
  });

  // Wire the dropdown once the DOM is parsed. value is initialised from
  // the cookie so reloading the page reflects the saved preference.
  function initLinkStylePicker() {
    var picker = document.getElementById('link-style-picker');
    if (!picker) return;
    picker.value = getLinkStyle();
    picker.addEventListener('change', function () { setLinkStyle(picker.value); });
  }
  if (document.readyState !== 'loading') initLinkStylePicker();
  else document.addEventListener('DOMContentLoaded', initLinkStylePicker);
})();
