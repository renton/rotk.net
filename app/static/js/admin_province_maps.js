/* Province Maps admin: populate the shared create/update modal from
 * the clicked button's data attributes. `data-mode` distinguishes
 * adding a NEW map to a province (file required) from editing an
 * existing one (file optional — label/attribution-only saves). */
document.addEventListener('DOMContentLoaded', function () {
  var modal = document.getElementById('provmap-modal');
  if (!modal) return;

  modal.addEventListener('show.bs.modal', function (event) {
    var btn = event.relatedTarget;
    if (!btn) return;

    var isCreate = btn.getAttribute('data-mode') === 'create';
    var province = btn.getAttribute('data-province') || '';

    modal.querySelector('#provmap-modal-form').action =
      btn.getAttribute('data-action');
    modal.querySelector('#provmap-modal-title').textContent = isCreate
      ? 'New map for ' + province
      : 'Edit map of ' + province;

    modal.querySelector('#provmap-modal-label').value =
      btn.getAttribute('data-label') || '';

    var fileInput = modal.querySelector('#provmap-modal-file');
    fileInput.value = '';
    fileInput.required = isCreate;
    modal.querySelector('#provmap-modal-file-help').textContent = isCreate
      ? 'Required — pick the map image for this new entry.'
      : 'Optional — leave empty to keep the current image and only update label / attribution.';

    modal.querySelector('#provmap-modal-site').value =
      btn.getAttribute('data-source-site') || '';
    modal.querySelector('#provmap-modal-url').value =
      btn.getAttribute('data-source-url') || '';
  });
});
