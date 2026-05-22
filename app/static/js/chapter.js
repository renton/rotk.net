(function () {
  // Bootstrap "lg" breakpoint is 992px; below that we use a modal instead
  // of the sticky sidebar (which has just stacked under the prose).
  var MOBILE_QUERY = '(max-width: 991.98px)';

  function isMobile() {
    return window.matchMedia(MOBILE_QUERY).matches;
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
})();
