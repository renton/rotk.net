// Chapter Edit admin — highlight-and-hide UI.
//
// Two flows, both AJAX:
//   Hide selected — user selects prose, clicks the Hide button, we
//     capture (match_text + surrounding context) and POST. On success
//     we wrap the selection in <s class="hidden-snippet"> so it flips
//     to strikethrough without a page reload.
//   Restore — user clicks an existing <s.hidden-snippet>; we confirm,
//     POST to /restore/<id>, and on success unwrap the <s> so the
//     text renders normally again.
//
// The chapter content container carries data-* attributes with the
// URLs and CSRF token — no other configuration needed.
(function () {
  var content = document.getElementById('chapter-edit-content');
  if (!content) return;

  var hideUrl = content.getAttribute('data-hide-url');
  var restorePrefix = content.getAttribute('data-restore-url-prefix');
  var csrfToken = content.getAttribute('data-csrf-token') || '';
  var statusEl = document.getElementById('chapter-edit-status');

  // Grab the prose scroll container — we scope selection queries to
  // it so a selection outside the prose (e.g. in the header) can't
  // be turned into a hidden snippet.
  var prose = content.querySelector('.chapter-edit-prose');

  function setStatus(msg, kind) {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.className = 'small ' + (kind === 'error' ? 'text-danger' : (kind === 'busy' ? 'text-warning' : 'text-muted'));
  }

  function postForm(url, data) {
    var body = new URLSearchParams();
    body.set('csrf_token', csrfToken);
    Object.keys(data).forEach(function (k) { body.set(k, data[k]); });
    return fetch(url, {
      method: 'POST',
      body: body,
      credentials: 'same-origin',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    }).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          throw new Error(j.error || ('HTTP ' + r.status));
        });
      }
      return r.json();
    });
  }

  // ---- Hide selected ---------------------------------------------------

  function selectionInsideProse(range) {
    if (!prose || !range) return false;
    var node = range.commonAncestorContainer;
    return prose.contains(node);
  }

  function collectContext(range) {
    // Walk up to the nearest block-level ancestor (a <p>, usually) —
    // that's the "paragraph" the selection lives in. Grab that
    // ancestor's plain text, find the selected text inside it, and
    // pull ~100 chars either side as context. Sending generous
    // context lets the server disambiguate when the same match_text
    // occurs more than once in the chapter.
    var ancestor = range.commonAncestorContainer;
    while (ancestor && ancestor.nodeType !== 1) {
      ancestor = ancestor.parentNode;
    }
    while (ancestor && ancestor !== prose) {
      var tag = ancestor.tagName;
      if (tag === 'P' || tag === 'BLOCKQUOTE' || tag === 'LI' || tag === 'DIV') break;
      ancestor = ancestor.parentNode;
    }
    var block = ancestor || prose;
    var blockText = (block.textContent || '').replace(/\s+/g, ' ');
    var matchText = range.toString().replace(/\s+/g, ' ').trim();
    var idx = blockText.indexOf(matchText);
    var before = '', after = '';
    if (idx >= 0) {
      before = blockText.substring(Math.max(0, idx - 100), idx);
      after = blockText.substring(idx + matchText.length, idx + matchText.length + 100);
    }
    return { matchText: matchText, before: before, after: after };
  }

  function wrapRangeInHiddenSnippet(range, hiddenId) {
    // Wrap the range's contents in a <s.hidden-snippet>. Range API's
    // surroundContents throws on partial-node boundaries; we use
    // extract+insert instead so cross-node selections are handled.
    var wrapper = document.createElement('s');
    wrapper.className = 'hidden-snippet';
    wrapper.setAttribute('data-hidden-id', String(hiddenId));
    var fragment = range.extractContents();
    wrapper.appendChild(fragment);
    range.insertNode(wrapper);
    // Clear the browser's selection so subsequent clicks don't
    // re-trigger the same range.
    window.getSelection().removeAllRanges();
  }

  function onHideClicked() {
    var sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
      setStatus('Select some text first.', 'error');
      return;
    }
    var range = sel.getRangeAt(0);
    if (!selectionInsideProse(range)) {
      setStatus('Selection must be within the chapter prose.', 'error');
      return;
    }
    var ctx = collectContext(range);
    if (!ctx.matchText) {
      setStatus('Empty selection.', 'error');
      return;
    }
    setStatus('Saving…', 'busy');
    postForm(hideUrl, {
      match_text: ctx.matchText,
      before: ctx.before,
      after: ctx.after,
    }).then(function (data) {
      wrapRangeInHiddenSnippet(range, data.id);
      setStatus('All changes saved', 'ok');
    }).catch(function (err) {
      setStatus('Could not hide: ' + err.message, 'error');
    });
  }

  var hideBtn = document.getElementById('hide-selected-btn');
  if (hideBtn) hideBtn.addEventListener('click', onHideClicked);

  // ---- Restore (click a strikethrough span) ---------------------------

  content.addEventListener('click', function (event) {
    var s = event.target.closest('s.hidden-snippet');
    if (!s) return;
    var id = s.getAttribute('data-hidden-id');
    if (!id) return;
    if (!window.confirm('Restore this hidden snippet? The text will show in the public chapter again.')) return;
    setStatus('Restoring…', 'busy');
    postForm(restorePrefix + id, {}).then(function () {
      // Unwrap the <s> — replace with its children.
      var parent = s.parentNode;
      while (s.firstChild) parent.insertBefore(s.firstChild, s);
      parent.removeChild(s);
      setStatus('All changes saved', 'ok');
    }).catch(function (err) {
      setStatus('Could not restore: ' + err.message, 'error');
    });
  });
})();
