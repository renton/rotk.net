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

  // Current modal state — the section text (for POST payload), the
  // chapter_id (per-section in admin list; per-page in chapter view),
  // and the DOM icon we clicked (for updating count / colour after
  // add).
  var currentSectionText = '';
  var currentChapterId = null;
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
      var deletedBadge = a.is_deleted
        ? '<span class="badge bg-secondary ms-1">Deleted</span>'
        : '';
      // Admin-only per-annotation soft-delete / restore control. The
      // action varies by state; the button carries data-annotation-id
      // + data-action so the click handler knows what to hit.
      var deleteBtn = '';
      if (meta.is_admin && a.id) {
        if (a.is_deleted) {
          deleteBtn = '<button type="button" class="btn btn-sm btn-outline-secondary annotation-restore-btn"' +
                      ' data-annotation-id="' + a.id + '">Restore</button>';
        } else {
          deleteBtn = '<button type="button" class="btn btn-sm btn-outline-danger annotation-delete-btn"' +
                      ' data-annotation-id="' + a.id + '"' +
                      ' data-confirm="Delete this annotation?">Delete</button>';
        }
      }
      return (
        '<li class="border rounded p-2 mb-2" data-annotation-row-id="' + (a.id || '') + '">' +
          '<div class="d-flex justify-content-between align-items-start gap-2 small text-muted mb-1">' +
            '<span>' + escapeHtml(a.created_by) + ' &middot; ' + escapeHtml(a.created_at) + '</span>' +
            '<span>' + badge + deletedBadge + '</span>' +
          '</div>' +
          '<div class="annotation-body" style="white-space:pre-wrap;">' + escapeHtml(a.body) + '</div>' +
          (deleteBtn ? '<div class="text-end mt-1">' + deleteBtn + '</div>' : '') +
        '</li>'
      );
    }).join('');
    threadEl.innerHTML = out;
  }

  function openModal(sectionKey, sectionText, chapterId) {
    currentSectionText = sectionText;
    currentChapterId = chapterId != null ? chapterId : meta.chapter_id;
    var entry = payload[sectionKey];
    var thread = (entry && entry.thread) || [];
    // Public readers only ever see public entries — server already
    // filtered but be defensive.
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
    // Delete / restore buttons inside the modal thread
    var delBtn = event.target.closest('.annotation-delete-btn');
    if (delBtn) {
      event.preventDefault();
      if (!window.confirm(delBtn.getAttribute('data-confirm') || 'Delete this annotation?')) return;
      handleAnnotationDelete(delBtn);
      return;
    }
    var restBtn = event.target.closest('.annotation-restore-btn');
    if (restBtn) {
      event.preventDefault();
      handleAnnotationRestore(restBtn);
      return;
    }

    // Admin list-page "Open modal" buttons — carry data-section-key
    // + data-chapter-id. Fall through so the icon handler below can
    // also match if someone renders both.
    var listBtn = event.target.closest('.open-annotation-modal-btn');
    if (listBtn) {
      event.preventDefault();
      currentIcon = listBtn;
      var lKey = listBtn.getAttribute('data-section-key') || '';
      var lChapterId = parseInt(listBtn.getAttribute('data-chapter-id') || '', 10) || null;
      var lEntry = payload[lKey];
      var lText = (lEntry && lEntry.section_text) || '';
      openModal(lKey, lText, lChapterId);
      return;
    }

    // Annotation icons injected into paragraphs on the chapter view
    var icon = event.target.closest('.annotation-icon');
    if (!icon) return;
    event.preventDefault();
    currentIcon = icon;
    var key = icon.getAttribute('data-section-key') || '';
    var entry = key ? payload[key] : null;
    // For a blue "add" icon (paragraph without annotations yet),
    // fall back to grabbing section_text from the paragraph itself.
    var sectionText = (entry && entry.section_text) || '';
    if (!sectionText) {
      var p = icon.closest('p');
      if (p) sectionText = (p.textContent || '').replace(/\s+/g, ' ').trim();
    }
    var chapterId = (entry && entry.chapter_id) || meta.chapter_id;
    openModal(key, sectionText, chapterId);
  });

  // The id sits in the MIDDLE of the delete/restore paths
  // (/admin/annotations/<id>/delete), so the server ships the URL
  // with a literal `0` placeholder segment and we substitute it here.
  function fillUrlTemplate(template, annotationId) {
    return template.replace('/0/', '/' + annotationId + '/');
  }

  // Recompute the paragraph icon's colour state from the thread —
  // called after every add / delete / restore so the icon reflects
  // reality without a page reload. Only applies on the chapter page
  // (the admin lists' buttons aren't paragraph icons).
  function updateIconState(icon, thread) {
    if (!icon || !icon.classList || !icon.classList.contains('annotation-icon')) return;
    var live = (thread || []).filter(function (a) { return !a.is_deleted; });
    var hasPublic = live.some(function (a) { return a.is_public; });
    var hasPrivate = live.some(function (a) { return !a.is_public; });

    icon.classList.remove(
      'annotation-icon-red', 'annotation-icon-black',
      'annotation-icon-blue', 'annotation-icon-add'
    );
    // Drop any existing exclamation prefix; re-added below if needed.
    var excl = icon.querySelector('.fa-circle-exclamation');
    if (excl) excl.remove();

    if (meta.is_admin && hasPrivate) {
      icon.classList.add('annotation-icon-red');
      var i = document.createElement('i');
      i.className = 'fa-solid fa-circle-exclamation text-danger me-1';
      i.setAttribute('aria-hidden', 'true');
      icon.insertBefore(i, icon.firstChild);
    } else if (hasPublic) {
      icon.classList.add('annotation-icon-black');
    } else {
      // No live annotations left → back to the hover-revealed blue
      // "add" affordance (admin only; public users shouldn't ever
      // reach this state since they can't delete).
      icon.classList.add('annotation-icon-blue', 'annotation-icon-add');
    }
  }

  function handleAnnotationDelete(btn) {
    var annotationId = btn.getAttribute('data-annotation-id');
    if (!annotationId || !meta.delete_url_template) return;
    var url = fillUrlTemplate(meta.delete_url_template, annotationId);
    var fd = new URLSearchParams();
    fd.set('csrf_token', getCsrf());
    fetch(url, {
      method: 'POST', body: fd, credentials: 'same-origin',
      headers: { 'Accept': 'application/json' },
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function () {
      // Flip the row in the in-memory payload → is_deleted = true so
      // subsequent opens reflect the change. Also re-render the modal.
      var key = currentIcon ? currentIcon.getAttribute('data-section-key') : '';
      var entry = payload[key];
      if (entry && entry.thread) {
        entry.thread.forEach(function (a) {
          if (String(a.id) === String(annotationId)) a.is_deleted = true;
        });
        // Filter based on the current "show deleted" view — on the
        // chapter page, deleted annotations shouldn't show at all;
        // on admin list pages with show_deleted=false, hide it; with
        // show_deleted=true, keep it visible with Restore.
        // Simplest: just drop deleted ones from the display unless
        // we detect show_deleted=true from meta.show_deleted (not set
        // today — a future refinement).
        var view = entry.thread.filter(function (a) { return !a.is_deleted; });
        renderThread(view);
        updateIconState(currentIcon, entry.thread);
      }
    }).catch(function (err) {
      window.alert('Delete failed: ' + err.message);
    });
  }

  function handleAnnotationRestore(btn) {
    var annotationId = btn.getAttribute('data-annotation-id');
    if (!annotationId || !meta.restore_url_template) return;
    var url = fillUrlTemplate(meta.restore_url_template, annotationId);
    var fd = new URLSearchParams();
    fd.set('csrf_token', getCsrf());
    fetch(url, {
      method: 'POST', body: fd, credentials: 'same-origin',
      headers: { 'Accept': 'application/json' },
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function () {
      var key = currentIcon ? currentIcon.getAttribute('data-section-key') : '';
      var entry = payload[key];
      if (entry && entry.thread) {
        entry.thread.forEach(function (a) {
          if (String(a.id) === String(annotationId)) a.is_deleted = false;
        });
        renderThread(entry.thread);
        updateIconState(currentIcon, entry.thread);
      }
    }).catch(function (err) {
      window.alert('Restore failed: ' + err.message);
    });
  }

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
      fd.set('chapter_id', String(currentChapterId || meta.chapter_id));
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
        // Flip the paragraph icon colour live — blue→black/red on
        // first annotation, black→red when a private one lands, etc.
        updateIconState(currentIcon, payload[sectionKey].thread);
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
