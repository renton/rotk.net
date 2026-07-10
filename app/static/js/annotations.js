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
  var addFloater = document.getElementById('annotation-add-floater');

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
    var entry = payload[key];
    // If the icon has no payload entry (e.g. the floating add-icon
    // for an empty paragraph), pull section text off the icon's
    // ephemeral state.
    var sectionText = (entry && entry.section_text) || icon.getAttribute('data-section-text') || '';
    openModal(key, sectionText);
  });

  // ---- Selection-triggered add-floater (admin only) -----------------

  function findAncestorP(node) {
    while (node && node.nodeType !== 1) node = node.parentNode;
    while (node) {
      if (node.tagName === 'P') return node;
      node = node.parentNode;
    }
    return null;
  }

  function isInsideProse(node) {
    var page = document.querySelector('.page-copy');
    return page ? page.contains(node) : false;
  }

  function positionFloater(p) {
    if (!addFloater) return;
    var rect = p.getBoundingClientRect();
    var docTop = window.pageYOffset + rect.top;
    var docLeft = window.pageXOffset + rect.left - 26;   // ~24px to left
    addFloater.style.top = docTop + 'px';
    addFloater.style.left = Math.max(4, docLeft) + 'px';
    addFloater.style.display = '';
    var text = (p.textContent || '').replace(/\s+/g, ' ').trim();
    addFloater.setAttribute('data-section-text', text);
    // section_key = sha of section_text; simpler to just use empty
    // string and let openModal fall back to data-section-text.
    addFloater.setAttribute('data-section-key', '');
  }

  function hideFloater() {
    if (addFloater) addFloater.style.display = 'none';
  }

  if (meta.is_admin && addFloater) {
    document.addEventListener('selectionchange', function () {
      var sel = document.getSelection();
      if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
        hideFloater();
        return;
      }
      var range = sel.getRangeAt(0);
      if (!isInsideProse(range.commonAncestorContainer)) {
        hideFloater();
        return;
      }
      var p = findAncestorP(range.commonAncestorContainer);
      if (!p) {
        hideFloater();
        return;
      }
      positionFloater(p);
    });
    // Keep the floater in the right spot when the user scrolls.
    window.addEventListener('scroll', function () {
      if (addFloater.style.display !== 'none') {
        // Re-derive from the current selection's paragraph.
        var sel = document.getSelection();
        if (sel && sel.rangeCount > 0 && !sel.isCollapsed) {
          var p = findAncestorP(sel.getRangeAt(0).commonAncestorContainer);
          if (p) positionFloater(p);
        }
      }
    }, { passive: true });
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
        // may not exist yet. Create it.
        if (!sectionKey) {
          // Compute a sha16 client-side — we don't strictly need it to
          // match the server's hash (next page load will rebuild
          // everything correctly). Use a placeholder key derived from
          // the section text length + a random suffix.
          sectionKey = 'pending-' + Math.random().toString(36).slice(2, 10);
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
