// Generic id-picker resolver shared by every admin form that uses the
// "name #<id>" datalist pattern. Two opt-in attributes:
//
//   data-character-picker         (legacy)  → hidden field is `character_id`
//   data-picker-target="<name>"             → hidden field is `<name>`
//
// Each datalist option's value ends in ` #<id>` so duplicate-name rows
// disambiguate. We regex the id out of whatever's currently in the
// input and write it to the sibling hidden field in the same form, so
// the server gets an unambiguous id. CSP-friendly: external file, no
// inline.
(function () {
  var ID_SUFFIX_RE = /#(\d+)\s*$/;

  function wire(input, hiddenFieldName) {
    var form = input.closest('form');
    var hidden = form ? form.querySelector('input[name="' + hiddenFieldName + '"]') : null;
    if (!hidden) return;
    function resolve() {
      var m = ID_SUFFIX_RE.exec(input.value);
      hidden.value = m ? m[1] : '';
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
