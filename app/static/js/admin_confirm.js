// Generic confirm-on-submit handler for admin actions.
// Add `data-confirm="message"` to any <form> on the page; the user gets a
// native confirm() before submission. CSP-friendly (external script, no
// inline handlers).
(function () {
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    var message = form.getAttribute('data-confirm');
    if (message && !window.confirm(message)) {
      event.preventDefault();
    }
  }, true);  // capture phase so we run before the default submit
})();
