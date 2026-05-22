(function () {
  // Chapter picker is a plain GET form; the server redirects ?chapter_num=N
  // to the path-form URL. No JS needed for it.

  // ---- Row filtering (search + faction). ----------------------------------
  var searchInput = document.getElementById('row-filter-search');
  var factionSelect = document.getElementById('row-filter-faction');
  var rowCount = document.getElementById('row-count');
  var rows = Array.prototype.slice.call(
    document.querySelectorAll('#associations-table tbody tr.association-row')
  );

  function applyFilter() {
    if (!rows.length) return;
    var q = (searchInput && searchInput.value || '').trim().toLowerCase();
    var fid = (factionSelect && factionSelect.value) || '';
    var visible = 0;
    rows.forEach(function (row) {
      var name = row.getAttribute('data-name') || '';
      var aliases = row.getAttribute('data-aliases') || '';
      var rowFaction = row.getAttribute('data-faction-id') || '';
      var matchesQuery = !q || name.indexOf(q) !== -1 || aliases.indexOf(q) !== -1;
      var matchesFaction = !fid || rowFaction === fid;
      var show = matchesQuery && matchesFaction;
      row.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    if (rowCount) rowCount.textContent = visible;
  }

  if (searchInput) searchInput.addEventListener('input', applyFilter);
  if (factionSelect) factionSelect.addEventListener('change', applyFilter);

  // ---- Sortable column headers. -------------------------------------------
  var table = document.getElementById('associations-table');
  if (table) {
    var tbody = table.querySelector('tbody');
    var headers = table.querySelectorAll('thead th[data-sort-key]');
    var sortState = { key: null, dir: 1 };

    headers.forEach(function (th, idx) {
      th.addEventListener('click', function () {
        var key = th.getAttribute('data-sort-key');
        if (sortState.key === key) {
          sortState.dir = -sortState.dir;
        } else {
          sortState.key = key;
          sortState.dir = 1;
        }
        var colIndex = idx;
        var sorted = rows.slice().sort(function (a, b) {
          var av = a.children[colIndex].getAttribute('data-sort-value') || '';
          var bv = b.children[colIndex].getAttribute('data-sort-value') || '';
          var anum = parseFloat(av), bnum = parseFloat(bv);
          if (!isNaN(anum) && !isNaN(bnum)) {
            return (anum - bnum) * sortState.dir;
          }
          if (av < bv) return -1 * sortState.dir;
          if (av > bv) return 1 * sortState.dir;
          return 0;
        });
        sorted.forEach(function (r) { tbody.appendChild(r); });
        headers.forEach(function (h) {
          var ind = h.querySelector('.sort-indicator');
          if (ind) ind.textContent = '';
        });
        var ind = th.querySelector('.sort-indicator');
        if (ind) ind.textContent = sortState.dir > 0 ? ' ▲' : ' ▼';
      });
    });
  }

  // ---- Generic character-picker resolver. ---------------------------------
  // Any text input marked `data-character-picker` referencing a `<datalist>`
  // gets its sibling `<input name="character_id">` (same form) populated
  // with the ID of the picked option whenever the value changes. The Add
  // Character Association form and every per-row Switch form share this
  // handler.
  var datalistMaps = {};
  function nameToIdMapFor(datalistId) {
    if (datalistMaps[datalistId]) return datalistMaps[datalistId];
    var dl = document.getElementById(datalistId);
    var map = {};
    if (dl) {
      Array.prototype.forEach.call(dl.querySelectorAll('option'), function (opt) {
        var v = opt.getAttribute('value');
        var id = opt.getAttribute('data-character-id');
        if (!v || !id) return;
        // Ambiguity: if multiple options share a name, drop the ID so the
        // server gets the name alone and can flash an ambiguity error.
        if (Object.prototype.hasOwnProperty.call(map, v)) {
          map[v] = null;
        } else {
          map[v] = id;
        }
      });
    }
    datalistMaps[datalistId] = map;
    return map;
  }

  Array.prototype.forEach.call(
    document.querySelectorAll('input[data-character-picker]'),
    function (input) {
      var dlId = input.getAttribute('list');
      if (!dlId) return;
      var map = nameToIdMapFor(dlId);
      var form = input.closest('form');
      var hidden = form ? form.querySelector('input[name="character_id"]') : null;
      if (!hidden) return;
      function resolve() { hidden.value = map[input.value] || ''; }
      input.addEventListener('input', resolve);
      input.addEventListener('change', resolve);
    }
  );
})();
