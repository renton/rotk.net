(function () {
  // ---- Chapter picker: auto-submit on change. -----------------------------
  var picker = document.getElementById('chapter-picker');
  var pickerForm = document.getElementById('chapter-picker-form');
  if (picker && pickerForm) {
    // Rewrite the form action to /admin/chapter-associations/<num> on submit
    // so the URL is shareable and the back button works as expected.
    pickerForm.addEventListener('submit', function (e) {
      var num = picker.value;
      if (!num) {
        e.preventDefault();
        return;
      }
      pickerForm.action = pickerForm.action.replace(/\/?$/, '') + '/' + encodeURIComponent(num);
      // Don't send chapter_num as a query string once it's in the path.
      picker.name = '';
    });
    picker.addEventListener('change', function () {
      if (picker.value) pickerForm.submit();
    });
    // Hide the submit button when JS is available — the change handler covers it.
    var submitBtn = document.getElementById('chapter-picker-submit');
    if (submitBtn) submitBtn.style.display = 'none';
  }

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

  // ---- Add-character picker: resolve typed name -> character_id. ---------
  var addNameInput = document.getElementById('add-character-name');
  var addIdInput = document.getElementById('add-character-id');
  var dl = document.getElementById('addable-characters-datalist');
  if (addNameInput && addIdInput && dl) {
    var nameToId = {};
    Array.prototype.forEach.call(dl.querySelectorAll('option'), function (opt) {
      var v = opt.getAttribute('value');
      var id = opt.getAttribute('data-character-id');
      if (!v || !id) return;
      // Track ambiguity: if multiple options share a name, drop the ID so the
      // server gets the name only and can flash an ambiguity error.
      if (Object.prototype.hasOwnProperty.call(nameToId, v)) {
        nameToId[v] = null;
      } else {
        nameToId[v] = id;
      }
    });
    function resolveId() {
      var v = addNameInput.value;
      var id = nameToId[v];
      addIdInput.value = id || '';
    }
    addNameInput.addEventListener('input', resolveId);
    addNameInput.addEventListener('change', resolveId);
  }
})();
