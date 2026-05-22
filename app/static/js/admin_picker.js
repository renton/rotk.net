// Generic character-picker resolver shared by every admin form that uses
// the `all-characters-datalist` pattern.
//
// Each datalist option's value ends in ` #<id>` (e.g. "Zhang Liang #42")
// so values stay unique even when two characters share a name. This
// script regexes the id out of whatever's currently in the input and
// stashes it in the sibling `<input name="character_id">` in the same
// form, so the server gets an unambiguous id.
//
// CSP-friendly: external file, no inline.
(function () {
  var ID_SUFFIX_RE = /#(\d+)\s*$/;

  Array.prototype.forEach.call(
    document.querySelectorAll('input[data-character-picker]'),
    function (input) {
      var form = input.closest('form');
      var hidden = form ? form.querySelector('input[name="character_id"]') : null;
      if (!hidden) return;
      function resolve() {
        var m = ID_SUFFIX_RE.exec(input.value);
        hidden.value = m ? m[1] : '';
      }
      input.addEventListener('input', resolve);
      input.addEventListener('change', resolve);
    }
  );
})();
