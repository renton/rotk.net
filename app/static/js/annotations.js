// Annotations UI for the chapter page.
//
// Data flow:
//   - Server ships {sha16 -> {section_text, thread[]}} JSON in a
//     <script type="application/json" id="annotations-payload">.
//   - Server injects <a.annotation-icon data-section-key="<sha16>">
//     at the start of each <p> that has annotations. Icon color
//     encodes public/private/admin state; JS doesn't recompute it.
//   - This module wires clicks on those icons + on the admin-only
//     floating blue "add" icon that follows the current text
//     selection when it lands in a paragraph.
//
// Both flows open the same Bootstrap modal (#annotation-modal),
// populate the thread from the payload (or an empty list for a
// paragraph that has none yet), and — for admins — show a form at
// the bottom that POSTs to /admin/annotations/create.
(function () {
  var payloadEl = document.getElementById('annotations-payload');
  var metaEl = document.getElementById('annotations-meta');
  if (!payloadEl || !metaEl) return;

  var payload = {};
  var meta = {};
  try {
    payload = JSON.parse(payloadEl.textContent || '{}');
    meta = JSON.parse(metaEl.textContent || '{}');
  } catch (e) { return; }

  var modalEl = document.getElementById('annotation-modal');
  var modal = (modalEl && window.bootstrap) ? new bootstrap.Modal(modalEl) : null;
  var threadEl = document.getElementById('annotation-thread');
  var ctxEl = document.getElementById('annotation-section-context');
  var addForm = document.getElementById('annotation-add-form');

  // CSRF token grabbed from the hidden form (admin only — renders if
  // meta.is_admin, but we guard anyway).
  function getCsrf() {
    var input = document.querySelector('#annotations-csrf-form input[name="csrf_token"]');
    return input ? input.value : '';
  }

  // Current modal state — the section text (for POST payload) and
  // the DOM icon we clicked (for updating count / colour after add).
  var currentSectionText = '';
  var currentIcon = null;

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function renderThread(thread) {
    if (!threadEl) return;
    if (!thread || !thread.length) {
      threadEl.innerHTML = '<li class="text-muted small">No annotations yet — be the first.</li>';
      return;
    }
    var out = thread.map(function (a) {
      var badge = a.is_public
        ? '<span class="badge bg-success">Public</span>'
        : '<span class="badge bg-danger">Private</span>';
      return (
        '<li class="border rounded p-2 mb-2">' +
          '<div class="d-flex justify-content-between align-items-start gap-2 small text-muted mb-1">' +
            '<span>' + escapeHtml(a.created_by) + ' &middot; ' + escapeHtml(a.created_at) + '</span>' +
            '<span>' + badge + '</span>' +
          '</div>' +
          '<div class="annotation-body" style="white-space:pre-wrap;">' + escapeHtml(a.body) + '</div>' +
        '</li>'
      );
    }).join('');
    threadEl.innerHTML = out;
  }

  function openModal(sectionKey, sectionText) {
    currentSectionText = sectionText;
    var entry = payload[sectionKey];
    var thread = (entry && entry.thread) || [];
    // Public readers only ever see public entries in the thread — the
    // server already stripped private ones from the payload, but be
    // defensive.
    if (!meta.is_admin) {
      thread = thread.filter(function (a) { return a.is_public; });
    }
    renderThread(thread);
    if (ctxEl) {
      var preview = (sectionText || '').slice(0, 140);
      ctxEl.textContent = preview + ((sectionText || '').length > 140 ? '…' : '');
    }
    if (addForm) {
      var body = addForm.querySelector('#annotation-body');
      var errEl = document.getElementById('annotation-form-error');
      if (body) body.value = '';
      if (errEl) { errEl.textContent = ''; errEl.hidden = true; }
    }
    if (modal) modal.show();
  }

  // ---- Click handlers -----------------------------------------------

  document.addEventListener('click', function (event) {
    var icon = event.target.closest('.annotation-icon');
    if (!icon) return;
    event.preventDefault();
    currentIcon = icon;
    var key = icon.getAttribute('data-section-key') || '';
    var entry = key ? payload[key] : null;
    // For an "add" icon on a paragraph with no annotations yet, the
    // section_text comes from the <p> the icon lives inside.
    var sectionText = (entry && entry.section_text) || '';
    if (!sectionText) {
      var p = icon.closest('p');
      if (p) {
        sectionText = (p.textContent || '').replace(/\s+/g, ' ').trim();
      }
    }
    openModal(key, sectionText);
  });

  // ---- Add form submit ----------------------------------------------

  if (addForm) {
    addForm.addEventListener('submit', function (event) {
      event.preventDefault();
      var body = addForm.querySelector('#annotation-body').value.trim();
      var isPublic = addForm.querySelector('#annotation-is-public').checked;
      var errEl = document.getElementById('annotation-form-error');
      if (!body) {
        if (errEl) { errEl.textContent = 'Annotation body is required.'; errEl.hidden = false; }
        return;
      }
      var fd = new URLSearchParams();
      fd.set('csrf_token', getCsrf());
      fd.set('chapter_id', String(meta.chapter_id));
      fd.set('section_text', currentSectionText);
      fd.set('body', body);
      fd.set('is_public', isPublic ? '1' : '0');
      fetch(meta.create_url, {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
        headers: { 'Accept': 'application/json' },
      }).then(function (r) {
        if (!r.ok) return r.json().catch(function () { return {}; }).then(function (j) {
          throw new Error(j.error || ('HTTP ' + r.status));
        });
        return r.json();
      }).then(function (data) {
        // Append to the visible thread and to the in-memory payload
        // so subsequent opens (without a page reload) also see it.
        var newRow = {
          id: data.id, body: data.body, created_at: data.created_at,
          created_by: data.created_by, is_public: data.is_public,
        };
        var sectionKey = currentIcon ? currentIcon.getAttribute('data-section-key') : '';
        // If this is the first annotation on the section, payload[sectionKey]
        // may not exist yet. Generate a placeholder key and STASH IT ON
        // THE ICON so subsequent submits in the same session reuse it —
        // otherwise every submit generates a new key + wipes the visible
        // thread from prior submits. Next page reload rebuilds keys from
        // the server-side sha16 hash anyway; this placeholder is
        // session-local.
        if (!sectionKey) {
          sectionKey = 'pending-' + Math.random().toString(36).slice(2, 10);
          if (currentIcon) currentIcon.setAttribute('data-section-key', sectionKey);
        }
        if (!payload[sectionKey]) {
          payload[sectionKey] = { section_text: currentSectionText, thread: [] };
        }
        payload[sectionKey].thread.push(newRow);
        // Filter for admin/public view same as openModal.
        var thread = payload[sectionKey].thread;
        if (!meta.is_admin) thread = thread.filter(function (a) { return a.is_public; });
        renderThread(thread);
        var bodyInput = addForm.querySelector('#annotation-body');
        if (bodyInput) bodyInput.value = '';
      }).catch(function (err) {
        if (errEl) {
          errEl.textContent = 'Could not save: ' + err.message;
          errEl.hidden = false;
        }
      });
    });
  }
})();
