// AJAX swap for the location-associations admin snippet pools.
//
// Each snippet sits inside one of two <ul>s in its row's td:
//   .snippets-list-live      — still tagged in the chapter prose
//   .snippets-list-excluded  — admin marked as a wrong match
//
// Clicking × on a live snippet (or ↺ on an excluded one) posts the
// exclude / restore form via fetch() with Accept: application/json.
// The server returns the new state (exclusion id, or ok + fingerprint
// for restores), and we move the <li> between the two pools without
// reloading the page. The counts in each <summary> update as the
// items shuffle.
//
// admin_confirm.js runs first (capture phase) — if the admin cancels
// the confirm dialog, defaultPrevented is true and we bail without
// firing the fetch.
(function () {
  function ajaxPost(form) {
    var fd = new FormData(form);
    return fetch(form.action, {
      method: 'POST',
      body: fd,
      headers: { 'Accept': 'application/json' },
      credentials: 'same-origin',
    }).then(function (r) {
      if (!r.ok) return r.json().catch(function () { return {}; })
                  .then(function (j) { throw new Error(j.error || ('HTTP ' + r.status)); });
      return r.json();
    });
  }

  function getCsrfToken(form) {
    // Reuse the form's existing csrf_token hidden input for any new
    // forms we synthesise client-side (the restore form on a
    // freshly-excluded snippet).
    var input = form.querySelector('input[name="csrf_token"]');
    return input ? input.value : '';
  }

  // ---- DOM helpers --------------------------------------------------

  function findCell(form) { return form.closest('[data-snippets-cell]'); }

  function updateCount(cell, kind) {
    // kind: 'live' or 'excluded'
    var detailsSel = '.snippets-' + kind;
    var listSel    = '.snippets-list-' + kind;
    var countSel   = '.snippet-' + kind + '-count';
    var pluralSel  = '.snippet-' + kind + '-plural';

    var details = cell.querySelector(detailsSel);
    var list    = cell.querySelector(listSel);
    var n = list ? list.children.length : 0;

    var c = details && details.querySelector(countSel);
    var p = details && details.querySelector(pluralSel);
    if (c) c.textContent = String(n);
    if (p) p.textContent = (n === 1) ? '' : 's';

    if (details) {
      if (n === 0) { details.setAttribute('hidden', ''); details.setAttribute('data-empty', ''); details.open = false; }
      else         { details.removeAttribute('hidden'); details.removeAttribute('data-empty'); }
    }
    if (kind === 'live') {
      var emptyMsg = cell.querySelector('.snippets-empty-live');
      if (emptyMsg) emptyMsg.hidden = (n !== 0);
    }
  }

  function makeRestoreForm(cell, exclusionId, csrfToken) {
    // Mirror the server-rendered restore form. The action URL prefix
    // (everything up to and including the trailing '/') is held on
    // the .snippets-excluded element so we can append the new id
    // without doing a Flask url_for round-trip.
    var details = cell.querySelector('.snippets-excluded');
    var prefix = details ? details.getAttribute('data-restore-url-prefix') : '';
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = prefix + exclusionId;
    form.className = 'd-inline restore-snippet-form';

    var csrf = document.createElement('input');
    csrf.type = 'hidden';
    csrf.name = 'csrf_token';
    csrf.value = csrfToken;
    form.appendChild(csrf);

    var btn = document.createElement('button');
    btn.type = 'submit';
    btn.className = 'btn btn-sm btn-outline-secondary py-0 px-2';
    btn.title = 'Restore this snippet';
    btn.innerHTML = '&#8634;';   // ↺
    form.appendChild(btn);
    return form;
  }

  function makeExcludeForm(cell, fingerprint, csrfToken) {
    // Inverse of makeRestoreForm: rebuild the exclude form when a
    // snippet is being un-excluded back into the live pool.
    var actionUrl = cell.querySelector('.exclude-snippet-form');
    var liveDetails = cell.querySelector('.snippets-live');
    // Prefer to crib the action URL from any sibling exclude form
    // (they're all the same URL per-location). Falls back to the
    // restore-prefix's parent path if there are zero live snippets.
    var actionAttr = actionUrl ? actionUrl.getAttribute('action') : null;
    if (!actionAttr) {
      var prefix = cell.querySelector('.snippets-excluded')
                       .getAttribute('data-restore-url-prefix');
      // prefix ends in "/restore/" — replace tail with "/exclude".
      actionAttr = prefix.replace(/\/restore\/$/, '/exclude');
    }
    var locName = cell.getAttribute('data-location-name') || '';

    var form = document.createElement('form');
    form.method = 'POST';
    form.action = actionAttr;
    form.className = 'd-inline exclude-snippet-form';
    form.setAttribute('data-confirm', 'Mark this snippet as a wrong match for ' + locName + '?');

    function hidden(name, value) {
      var i = document.createElement('input');
      i.type = 'hidden'; i.name = name; i.value = value;
      form.appendChild(i);
    }
    hidden('csrf_token', csrfToken);
    hidden('match_text', fingerprint.match_text);
    hidden('before_snippet', fingerprint.before_snippet);
    hidden('after_snippet', fingerprint.after_snippet);

    var btn = document.createElement('button');
    btn.type = 'submit';
    btn.className = 'btn btn-sm btn-outline-danger py-0 px-2';
    btn.title = 'Exclude this snippet';
    btn.innerHTML = '&times;';
    form.appendChild(btn);
    return form;
  }

  // ---- exclude flow -------------------------------------------------

  function handleExclude(form) {
    var cell = findCell(form);
    var li = form.closest('.snippet-item');
    if (!cell || !li) return;

    ajaxPost(form).then(function (data) {
      // Transform the <li> in place: strikethrough body, swap form,
      // store the new exclusion id. Then move it to the excluded list.
      var body = li.querySelector('.snippet-body');
      if (body) {
        var inner = body.innerHTML;
        // Wrap whatever was inside the body in <s>…</s>.
        body.innerHTML = '<s>' + inner + '</s>';
      }
      li.classList.add('text-muted');
      li.setAttribute('data-exclusion-id', data.id);

      var newForm = makeRestoreForm(cell, data.id, getCsrfToken(form));
      form.replaceWith(newForm);

      var excludedList = cell.querySelector('.snippets-list-excluded');
      excludedList.appendChild(li);

      updateCount(cell, 'live');
      updateCount(cell, 'excluded');
    }).catch(function (err) {
      window.alert('Could not exclude snippet: ' + err.message);
    });
  }

  // ---- restore flow -------------------------------------------------

  function handleRestore(form) {
    var cell = findCell(form);
    var li = form.closest('.snippet-item');
    if (!cell || !li) return;

    ajaxPost(form).then(function (data) {
      // Un-strikethrough the body, rebuild the exclude form, move
      // back to the live pool.
      var body = li.querySelector('.snippet-body');
      if (body) {
        var s = body.querySelector('s');
        if (s) body.innerHTML = s.innerHTML;
      }
      li.classList.remove('text-muted');
      li.removeAttribute('data-exclusion-id');

      var fingerprint = {
        match_text:     data.match_text     || li.getAttribute('data-match-text') || '',
        before_snippet: data.before_snippet || li.getAttribute('data-before-snippet') || '',
        after_snippet:  data.after_snippet  || li.getAttribute('data-after-snippet') || '',
      };
      var newForm = makeExcludeForm(cell, fingerprint, getCsrfToken(form));
      form.replaceWith(newForm);

      var liveList = cell.querySelector('.snippets-list-live');
      liveList.appendChild(li);

      updateCount(cell, 'live');
      updateCount(cell, 'excluded');
    }).catch(function (err) {
      window.alert('Could not restore snippet: ' + err.message);
    });
  }

  // ---- submit handler ----------------------------------------------

  document.addEventListener('submit', function (event) {
    // admin_confirm.js runs in the capture phase. If the user cancelled,
    // the event is already defaultPrevented — bail before posting.
    if (event.defaultPrevented) return;
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    if (form.classList.contains('exclude-snippet-form')) {
      event.preventDefault();
      handleExclude(form);
    } else if (form.classList.contains('restore-snippet-form')) {
      event.preventDefault();
      handleRestore(form);
    }
  });

  // ---- Init: re-sync counts on page load ----------------------------
  //
  // The server-rendered "show N snippets" / "M excluded snippets"
  // counts come from find_location_mentions + a DB query. If anything
  // ever desyncs (a fingerprint that doesn't match between save and
  // render, a cached page that's serving a stale count, etc.) the
  // visible LI count is the source of truth — recompute from it once
  // the DOM is parsed so what the admin sees always reflects what's
  // actually in the two pools.
  function syncAllCounts() {
    var cells = document.querySelectorAll('[data-snippets-cell]');
    for (var i = 0; i < cells.length; i++) {
      updateCount(cells[i], 'live');
      updateCount(cells[i], 'excluded');
    }
  }
  if (document.readyState !== 'loading') syncAllCounts();
  else document.addEventListener('DOMContentLoaded', syncAllCounts);
})();
