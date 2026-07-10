/* Yearly Maps admin: populate the shared upload/edit modal from the
 * clicked row's data attributes, and manage the "factions on this map"
 * chip list.
 *
 * Bootstrap fires 'show.bs.modal' with relatedTarget = the button that
 * triggered it, so one modal serves all 97 year rows. The file input is
 * required only when the year has no image yet — with an existing image,
 * leaving it empty saves attribution/factions only.
 *
 * Factions: rows carry data-factions='[{"id":1,"name":"Wei"},...]'. The
 * modal shows them as removable chips; Add resolves the "Name #id"
 * datalist convention. The full current set is serialised into the
 * hidden faction_ids CSV on every change — the server replaces the M2M
 * wholesale on Save.
 */
document.addEventListener('DOMContentLoaded', function () {
  var modal = document.getElementById('yearmap-modal');
  if (!modal) return;

  var chipList = modal.querySelector('#yearmap-modal-faction-list');
  var searchInput = modal.querySelector('#yearmap-modal-faction-search');
  var addBtn = modal.querySelector('#yearmap-modal-faction-add');
  var idsField = modal.querySelector('#yearmap-modal-faction-ids');

  var factions = [];   // [{id, name}] — current chip state

  function syncHidden() {
    idsField.value = factions.map(function (f) { return f.id; }).join(',');
  }

  // Perceived luminance of a #rrggbb colour, 0 (black) → 1 (white).
  // Used to pick a readable close-button variant per chip.
  function luminance(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return 0;
    var n = parseInt(m[1], 16);
    var r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  }

  function renderChips() {
    chipList.innerHTML = '';
    factions.forEach(function (f) {
      var chip = document.createElement('span');
      chip.className = 'badge rounded-pill d-inline-flex align-items-center gap-1';
      // badge_widget conventions: unset bg (null/'') → Bootstrap primary;
      // unset border → none.
      if (f.bg) {
        chip.style.backgroundColor = f.bg;
      } else {
        chip.classList.add('text-bg-primary');
      }
      if (f.font) chip.style.color = f.font;
      if (f.border) chip.style.border = '2px solid ' + f.border;
      chip.appendChild(document.createTextNode(f.name));
      var x = document.createElement('button');
      x.type = 'button';
      // White × on light text (dark chip), black × otherwise.
      x.className = 'btn-close' +
        (luminance(f.font || '#ffffff') > 0.5 ? ' btn-close-white' : '');
      x.style.fontSize = '0.6em';
      x.setAttribute('aria-label', 'Remove ' + f.name);
      x.addEventListener('click', function () {
        factions = factions.filter(function (g) { return g.id !== f.id; });
        renderChips();
      });
      chip.appendChild(x);
      chipList.appendChild(chip);
    });
    syncHidden();
  }

  function addFromSearch() {
    var raw = (searchInput.value || '').trim();
    var m = raw.match(/#(\d+)\s*$/);
    if (!m) return;   // nothing picked from the datalist yet
    var id = parseInt(m[1], 10);
    var name = raw.replace(/\s*#\d+\s*$/, '');

    // Pull the faction's colours off the matching datalist option so
    // the fresh chip renders like the saved ones.
    var font = '', bg = '', border = '';
    var options = document.querySelectorAll('#yearmap-factions-datalist option');
    for (var i = 0; i < options.length; i++) {
      if (options[i].value === raw) {
        font = options[i].getAttribute('data-font') || '';
        bg = options[i].getAttribute('data-bg') || '';
        border = options[i].getAttribute('data-border') || '';
        break;
      }
    }

    var exists = factions.some(function (f) { return f.id === id; });
    if (!exists) {
      factions.push({ id: id, name: name,
                      font: font || null, bg: bg || null,
                      border: border || null });
      renderChips();
    }
    searchInput.value = '';
  }

  addBtn.addEventListener('click', addFromSearch);
  searchInput.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      event.preventDefault();   // don't submit the whole modal form
      addFromSearch();
    }
  });

  modal.addEventListener('show.bs.modal', function (event) {
    var btn = event.relatedTarget;
    if (!btn) return;

    var year = btn.getAttribute('data-year');
    var hasImage = !!btn.getAttribute('data-has-image');

    modal.querySelector('#yearmap-modal-form').action =
      btn.getAttribute('data-action');
    modal.querySelector('#yearmap-modal-title').textContent =
      'Map for ' + year + ' AD';

    var fileInput = modal.querySelector('#yearmap-modal-file');
    fileInput.value = '';
    fileInput.required = !hasImage;
    modal.querySelector('#yearmap-modal-file-help').textContent = hasImage
      ? 'Optional — leave empty to keep the current image and only update the attribution / factions.'
      : 'Required — this year has no map yet.';

    modal.querySelector('#yearmap-modal-site').value =
      btn.getAttribute('data-source-site') || '';
    modal.querySelector('#yearmap-modal-url').value =
      btn.getAttribute('data-source-url') || '';

    try {
      factions = JSON.parse(btn.getAttribute('data-factions') || '[]');
    } catch (e) {
      factions = [];
    }
    searchInput.value = '';
    renderChips();
  });
});
