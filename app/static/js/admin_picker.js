// Generic id-picker resolver shared by every admin form that uses the
// "name #<id>" datalist pattern. Three opt-in attributes:
//
//   data-character-picker                  (legacy)  → hidden field is `character_id`
//   data-picker-target="<name>"                      → hidden field is `<name>`
//   data-picker-keywords-target="<name>"             → companion text field name
//
// Each datalist option's value ends in ` #<id>` so duplicate-name rows
// disambiguate. We regex the id out of whatever's currently in the
// input and write it to the sibling hidden field in the same form, so
// the server gets an unambiguous id.
//
// When `data-picker-keywords-target` is set, AND the chosen option
// carries a `data-keywords` attribute (the entity's `name,aliases`
// joined), AND the target field is currently empty, we pre-fill the
// keywords field so admins don't have to retype name + aliases. Empty
// guard so we never clobber a value the admin already typed.
//
// CSP-friendly: external file, no inline.
(function () {
  var ID_SUFFIX_RE = /#(\d+)\s*$/;

  function findOptionForValue(input, value) {
    // <input list="..."> attaches to a <datalist>; look its options up
    // and find the one whose value matches what the user picked.
    var listId = input.getAttribute('list');
    if (!listId) return null;
    var list = document.getElementById(listId);
    if (!list) return null;
    var opts = list.querySelectorAll('option');
    for (var i = 0; i < opts.length; i++) {
      if (opts[i].value === value) return opts[i];
    }
    return null;
  }

  function wire(input, hiddenFieldName) {
    var form = input.closest('form');
    var hidden = form ? form.querySelector('input[name="' + hiddenFieldName + '"]') : null;
    if (!hidden) return;
    var keywordsTargetName = input.getAttribute('data-picker-keywords-target');
    var keywordsField = keywordsTargetName && form
      ? form.querySelector('[name="' + keywordsTargetName + '"]')
      : null;

    function resolve() {
      var m = ID_SUFFIX_RE.exec(input.value);
      hidden.value = m ? m[1] : '';

      // Keyword auto-fill: only when the picker resolved to an option
      // we recognise, and the keywords field is still empty (so we
      // don't trample admin edits).
      if (m && keywordsField && !keywordsField.value) {
        var opt = findOptionForValue(input, input.value);
        var kws = opt ? opt.getAttribute('data-keywords') : null;
        if (kws) keywordsField.value = kws;
      }
    }
    input.addEventListener('input', resolve);
    input.addEventListener('change', resolve);
  }

  // Legacy character pickers: target is implicitly `character_id`.
  Array.prototype.forEach.call(
    document.querySelectorAll('input[data-character-picker]'),
    function (input) { wire(input, 'character_id'); }
  );

  // Generic: explicit `data-picker-target="<hidden_field_name>"`.
  Array.prototype.forEach.call(
    document.querySelectorAll('input[data-picker-target]'),
    function (input) { wire(input, input.getAttribute('data-picker-target')); }
  );
})();
