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

    var collapseElement = document.getElementById('collapseOne');
    if (collapseElement && !collapseElement.classList.contains('show')) {
      var accordionButton = document.querySelector('#sidebar-character-info .accordion-button');
      if (accordionButton) {
        accordionButton.click();
      }
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

  // Event / location inline refs open the matching sidebar accordion and
  // briefly highlight the specific row. Deliberately NO scrollIntoView:
  // on mobile that would yank the whole page down to the stacked sidebar,
  // which is more jarring than helpful — the highlight gives the visual
  // cue, the reader can flick down to the sidebar themselves if they
  // want to see more.
  function showAccordionItem(collapseId, itemId) {
    var collapseEl = document.getElementById(collapseId);
    if (collapseEl && typeof bootstrap !== 'undefined') {
      bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false }).show();
    }
    var item = itemId ? document.getElementById(itemId) : null;
    if (!item) return;
    // CSS animates a yellow-fade-out via the .sidebar-flash class.
    // Re-trigger by removing + re-adding so a second click flashes again.
    item.classList.remove('sidebar-flash');
    // Force a reflow so the browser actually treats the next add as a
    // fresh class change rather than a no-op.
    void item.offsetWidth;
    item.classList.add('sidebar-flash');
  }

  document.addEventListener('click', function (event) {
    var ev = event.target.closest('.event-ref');
    if (ev) {
      var eid = ev.getAttribute('data-event-id');
      showAccordionItem('collapseEvents', eid ? 'event-item-' + eid : null);
      return;
    }
    var loc = event.target.closest('.location-ref');
    if (loc) {
      var lid = loc.getAttribute('data-location-id');
      showAccordionItem('collapseLocations', lid ? 'location-item-' + lid : null);
    }
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
