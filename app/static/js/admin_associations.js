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

  // The generic character-picker resolver moved to admin_picker.js so it
  // can be reused on other admin pages (image manager, etc.) without
  // dragging this file's row-sort/filter logic along.
})();
