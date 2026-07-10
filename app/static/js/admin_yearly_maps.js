/* Yearly Maps admin: populate the shared upload/edit modal from the
 * clicked row's data attributes.
 *
 * Bootstrap fires 'show.bs.modal' with relatedTarget = the button that
 * triggered it, so one modal serves all 97 year rows. The file input is
 * required only when the year has no image yet — with an existing image,
 * leaving it empty saves attribution-only. */
document.addEventListener('DOMContentLoaded', function () {
    var modal = document.getElementById('yearmap-modal');
    if (!modal) return;

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
            ? 'Optional — leave empty to keep the current image and only update the attribution.'
            : 'Required — this year has no map yet.';

        modal.querySelector('#yearmap-modal-site').value =
            btn.getAttribute('data-source-site') || '';
        modal.querySelector('#yearmap-modal-url').value =
            btn.getAttribute('data-source-url') || '';
    });
});
