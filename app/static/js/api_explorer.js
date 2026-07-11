/* API Explorer (admin): pick an endpoint from the registry-driven
 * dropdown, fill the generated param form, fire a same-origin fetch()
 * and inspect the pretty-printed response.
 *
 * The endpoint catalogue arrives via the #api-endpoints JSON script tag
 * (rendered from app/blueprints/api/registry.py — one source of truth
 * for the API index, this page, and the future MCP). CSP-safe: external
 * file, same-origin requests only. */
document.addEventListener('DOMContentLoaded', function () {
  var payloadEl = document.getElementById('api-endpoints');
  if (!payloadEl) return;
  var ENDPOINTS = JSON.parse(payloadEl.textContent);

  var select = document.getElementById('api-endpoint');
  var description = document.getElementById('api-endpoint-description');
  var modeWrap = document.getElementById('api-mode-wrap');
  var detailWrap = document.getElementById('api-detail-wrap');
  var detailLabel = document.getElementById('api-detail-label');
  var detailInput = document.getElementById('api-detail-id');
  var paramsBox = document.getElementById('api-params');
  var sendBtn = document.getElementById('api-send');
  var statusEl = document.getElementById('api-status');
  var timingEl = document.getElementById('api-timing');
  var urlEl = document.getElementById('api-url');
  var copyBtn = document.getElementById('api-copy-url');
  var responseEl = document.getElementById('api-response');

  ENDPOINTS.forEach(function (e, i) {
    var opt = document.createElement('option');
    opt.value = i;
    opt.textContent = e.title;
    select.appendChild(opt);
  });

  function current() {
    return ENDPOINTS[parseInt(select.value, 10) || 0];
  }

  function mode() {
    var detail = document.getElementById('api-mode-detail');
    return (detail && detail.checked && current().detail_path)
      ? 'detail' : 'list';
  }

  function fieldId(name) { return 'api-param-' + name; }

  function renderForm() {
    var e = current();
    description.textContent = e.description || '';

    modeWrap.hidden = !e.detail_path;
    if (!e.detail_path) {
      document.getElementById('api-mode-list').checked = true;
    }
    syncMode();

    paramsBox.innerHTML = '';
    // Registry params + the implicit pagination pair.
    var params = e.params.concat([
      { name: 'page', type: 'number', label: 'Page (default 1)' },
      { name: 'per_page', type: 'number',
        label: 'Per page (max 100)' }
    ]);
    params.forEach(function (p) {
      var wrap = document.createElement('div');
      wrap.className = 'mb-2 api-list-param';
      var label = document.createElement('label');
      label.className = 'form-label small mb-0';
      label.setAttribute('for', fieldId(p.name));
      label.textContent = p.label || p.name;
      wrap.appendChild(label);

      var input;
      if (p.type === 'select') {
        input = document.createElement('select');
        input.className = 'form-select form-select-sm';
        var blank = document.createElement('option');
        blank.value = '';
        blank.textContent = '—';
        input.appendChild(blank);
        (p.choices || []).forEach(function (c) {
          var opt = document.createElement('option');
          opt.value = c;
          opt.textContent = c;
          input.appendChild(opt);
        });
      } else {
        input = document.createElement('input');
        input.type = (p.type === 'number') ? 'number' : 'text';
        input.className = 'form-control form-control-sm';
      }
      input.id = fieldId(p.name);
      input.setAttribute('data-param', p.name);
      wrap.appendChild(input);
      paramsBox.appendChild(wrap);
    });
  }

  function syncMode() {
    var e = current();
    var isDetail = mode() === 'detail';
    detailWrap.hidden = !isDetail;
    paramsBox.hidden = isDetail;
    if (e.detail_path) {
      // Show the placeholder name from the path, e.g. <chapter_num>.
      var m = e.detail_path.match(/<([^>]+)>/);
      detailLabel.textContent = m ? m[1] : 'id';
    }
  }

  function buildUrl() {
    var e = current();
    if (mode() === 'detail') {
      var idVal = (detailInput.value || '').trim();
      if (!idVal) return null;
      return e.detail_path.replace(/<[^>]+>/, encodeURIComponent(idVal));
    }
    var qs = [];
    paramsBox.querySelectorAll('[data-param]').forEach(function (input) {
      var v = (input.value || '').trim();
      if (v !== '') {
        qs.push(encodeURIComponent(input.getAttribute('data-param')) +
                '=' + encodeURIComponent(v));
      }
    });
    return e.path + (qs.length ? '?' + qs.join('&') : '');
  }

  function send() {
    var url = buildUrl();
    if (!url) {
      responseEl.textContent = 'Enter an id for a single-item request.';
      return;
    }
    var started = performance.now();
    responseEl.textContent = 'Loading…';
    fetch(url, { headers: { 'Accept': 'application/json' } })
      .then(function (res) {
        var elapsed = Math.round(performance.now() - started);
        statusEl.hidden = false;
        statusEl.textContent = 'HTTP ' + res.status;
        statusEl.className = 'badge ' +
          (res.ok ? 'text-bg-success' : 'text-bg-danger');
        timingEl.hidden = false;
        timingEl.textContent = elapsed + ' ms';
        urlEl.hidden = false;
        urlEl.textContent = url;
        urlEl.href = url;
        copyBtn.hidden = false;
        return res.text();
      })
      .then(function (text) {
        try {
          responseEl.textContent = JSON.stringify(JSON.parse(text), null, 2);
        } catch (e) {
          responseEl.textContent = text;
        }
      })
      .catch(function (err) {
        responseEl.textContent = 'Request failed: ' + err;
      });
  }

  select.addEventListener('change', renderForm);
  document.querySelectorAll('input[name="api-mode"]').forEach(function (r) {
    r.addEventListener('change', syncMode);
  });
  sendBtn.addEventListener('click', send);
  copyBtn.addEventListener('click', function () {
    navigator.clipboard.writeText(
      window.location.origin + urlEl.textContent);
  });

  renderForm();
});
