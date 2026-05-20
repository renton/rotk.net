(function () {
  function showCharacter(characterId) {
    document.querySelectorAll('div.character-panel').forEach(function (panel) {
      panel.style.display = 'none';
    });

    var panel = document.getElementById('character-panel-' + characterId);
    if (!panel) {
      return;
    }
    panel.style.display = 'block';

    var collapseElement = document.getElementById('collapseOne');
    if (collapseElement && !collapseElement.classList.contains('show')) {
      var accordionButton = document.querySelector('#sidebar-character-info .accordion-button');
      if (accordionButton) {
        accordionButton.click();
      }
    }
  }

  document.addEventListener('click', function (event) {
    var target = event.target.closest('.character-ref');
    if (!target) {
      return;
    }
    var characterId = target.getAttribute('data-character-id');
    if (characterId) {
      showCharacter(characterId);
    }
  });
})();
