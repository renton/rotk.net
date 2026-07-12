/* Province Maps admin: populate the shared upload/edit modal from the
 * clicked row's data attributes (same pattern as admin_yearly_maps.js:
 * one modal serves every province row via show.bs.modal's
 * relatedTarget; file input required only when no image exists yet). */
document.addEventListener('DOMContentLoaded', function () {
  var modal = document.getElementById('provmap-modal');
  if (!modal) return;

  modal.addEventListener('show.bs.modal', function (event) {
    var btn = event.relatedTarget;
    if (!btn) return;

    var hasImage = !!btn.getAttribute('data-has-image');

    modal.querySelector('#provmap-modal-form').action =
      btn.getAttribute('data-action');
    modal.querySelector('#provmap-modal-title').textContent =
      'Map for ' + btn.getAttribute('data-province');

    var fileInput = modal.querySelector('#provmap-modal-file');
    fileInput.value = '';
    fileInput.required = !hasImage;
    modal.querySelector('#provmap-modal-file-help').textContent = hasImage
      ? 'Optional — leave empty to keep the current image and only update the attribution.'
      : 'Required — this province has no map yet.';

    modal.querySelector('#provmap-modal-site').value =
      btn.getAttribute('data-source-site') || '';
    modal.querySelector('#provmap-modal-url').value =
      btn.getAttribute('data-source-url') || '';
  });
});
