// Timeline view — vis-timeline glue.
//
// Three inline JSON blobs on the page (chapters, events, characters)
// drive a single vis-timeline instance. Characters get one group + one
// range item each; chapters and events live in pinned summary groups
// at the top. Filtering is client-side via a DataView so pan/zoom
// state survives filter changes.

(function () {
  'use strict';

  const chaptersData   = readJson('timeline-chapters');
  const eventsData     = readJson('timeline-events');
  const charactersData = readJson('timeline-characters');

  // --- year → Date (avoids the JS Date <100 fallback to 1900s) ---
  function yearToDate(y) {
    const whole = Math.floor(y);
    const frac  = y - whole;
    const ms    = frac * 365.25 * 24 * 60 * 60 * 1000;
    const d = new Date(0);
    d.setUTCFullYear(whole, 0, 1);
    d.setUTCHours(0, 0, 0, 0);
    return new Date(d.getTime() + ms);
  }

  function midYear(lo, hi) { return (lo + hi) / 2; }

  // --- build the gradient string for a fuzzy lifeline ---
  //
  // Item extent: [birth_lo, death_hi]. Solid section: [birth_hi, death_lo].
  // Anything outside the solid section fades toward the bar's bg colour
  // with reduced alpha at the extremes. If birth_lo == birth_hi (sharp
  // birth) the left edge is full alpha; same for death on the right.
  function lifelineGradient(b_lo, b_hi, d_lo, d_hi, bg) {
    const span = d_hi - b_lo;
    if (span <= 0) return bg;
    const solidStart = (b_hi - b_lo) / span;   // 0..1
    const solidEnd   = (d_lo - b_lo) / span;   // 0..1
    const c = hexToRgb(bg);
    const solid   = `rgba(${c.r}, ${c.g}, ${c.b}, 1)`;
    const faded   = `rgba(${c.r}, ${c.g}, ${c.b}, 0)`;
    return (
      'linear-gradient(to right, ' +
        `${faded} 0%, ` +
        `${solid} ${(solidStart * 100).toFixed(2)}%, ` +
        `${solid} ${(solidEnd * 100).toFixed(2)}%, ` +
        `${faded} 100%)`
    );
  }

  function hexToRgb(hex) {
    const h = (hex || '#6c757d').replace('#', '');
    const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
    return {
      r: parseInt(full.slice(0, 2), 16),
      g: parseInt(full.slice(2, 4), 16),
      b: parseInt(full.slice(4, 6), 16),
    };
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Looser than escapeHtml — for values going into an attribute value
  // where we still need to neutralise quotes but want to keep spaces
  // and slashes intact (Font Awesome class strings).
  function escapeAttr(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // --- build groups + items ---
  const groups = new vis.DataSet();
  const items  = new vis.DataSet();

  groups.add({
    id: '__chapters__',
    content: 'Chapters',
    className: 'tl-group-chapters',
    order: -2,
    style: 'min-height: 110px;',
  });
  groups.add({
    id: '__events__',
    content: 'Events',
    className: 'tl-group-events',
    order: -1,
    style: 'min-height: 110px;',
  });

  // Chapter markers — scroll icon, click for details.
  chaptersData.forEach(c => {
    const mid = midYear(c.year_lo, c.year_hi);
    items.add({
      id: `ch-${c.id}`,
      group: '__chapters__',
      kind: 'chapter',
      content: `<i class="fa-solid fa-scroll" aria-hidden="true"></i><span class="tl-num">${c.num}</span>`,
      start: yearToDate(mid),
      type: 'box',
      className: 'tl-chapter',
      _filterText: `${c.num} ${c.name}`.toLowerCase(),
      _data: c,
    });
  });

  // Event markers — event-type FA icon, colored to match the type.
  eventsData.forEach(e => {
    const mid = midYear(e.year_lo, e.year_hi);
    const icon = e.icon || 'fa-solid fa-flag';
    items.add({
      id: `ev-${e.id}`,
      group: '__events__',
      kind: 'event',
      content: `<i class="${escapeAttr(icon)}" aria-hidden="true"></i>`,
      start: yearToDate(mid),
      type: 'box',
      className: 'tl-event',
      style:
        `background: ${e.bg_colour};` +
        `border-color: ${e.border_colour};` +
        `color: ${e.font_colour};`,
      _filterText: e.name.toLowerCase(),
      _data: e,
    });
  });

  // Character groups + lifeline ranges.
  charactersData.forEach(ch => {
    const groupId = `char-${ch.id}`;
    const safeName = escapeHtml(ch.name);
    const chineseSuffix = ch.chinese_name
      ? ` <span class="tl-zh">${escapeHtml(ch.chinese_name)}</span>`
      : '';
    groups.add({
      id: groupId,
      content: `<a href="/characters/edit/${ch.id}">${safeName}</a>${chineseSuffix}`,
      // vis-timeline orders groups ascending by this number. birth_lo
      // is the earliest year the character could have been born, so
      // characters sort earliest-born → latest-born vertically.
      // Chapters / events live at order -2 / -1, so all characters
      // (whose birth_lo is positive AD years) stay below them.
      order: ch.birth_lo,
      _factionId: ch.faction_id,
      _filterText: `${ch.name} ${ch.chinese_name || ''}`.toLowerCase(),
    });

    const gradient = lifelineGradient(
      ch.birth_lo, ch.birth_hi, ch.death_lo, ch.death_hi, ch.bg_colour
    );
    items.add({
      id: `li-${ch.id}`,
      group: groupId,
      kind: 'character',
      content: `<span class="tl-life-label" style="color: ${ch.font_colour};">${safeName}</span>`,
      start: yearToDate(ch.birth_lo),
      end:   yearToDate(ch.death_hi),
      type: 'range',
      className: 'tl-life',
      style:
        `background: ${gradient};` +
        `border-color: ${ch.border_colour};` +
        `color: ${ch.font_colour};`,
      title:
        `${ch.name}` +
        (ch.chinese_name ? ` (${ch.chinese_name})` : '') +
        ` — ${ch.faction_name}\n` +
        `Born: ${ch.birth_str}\n` +
        `Died: ${ch.death_str}`,
      _data: ch,
    });
  });

  // --- timeline window: derive from data, with comfortable padding ---
  const allLo = [
    ...chaptersData.map(c => c.year_lo),
    ...eventsData.map(e => e.year_lo),
    ...charactersData.map(c => c.birth_lo),
  ];
  const allHi = [
    ...chaptersData.map(c => c.year_hi),
    ...eventsData.map(e => e.year_hi),
    ...charactersData.map(c => c.death_hi),
  ];
  // Fall back to the RotK era (Yellow Turbans → Jin) when no data
  // is available yet, so the empty timeline still renders a meaningful
  // numeric axis instead of collapsing to a single point.
  const dataLo = allLo.length ? Math.min(...allLo) : 150;
  const dataHi = allHi.length ? Math.max(...allHi) : 280;
  const pad = Math.max(5, (dataHi - dataLo) * 0.05);

  // Initial window — hard-anchored to the opening of the RotK era
  // (184 AD Yellow Turban Rebellion through ~200 AD around Guandu)
  // so the page lands zoomed into the busiest, most populated stretch
  // instead of dispersing icons across a century. "Fit all" expands
  // back to dataLo..dataHi on demand.
  const initialStart = 184;
  const initialEnd = 200;

  // --- filter state ---
  //
  // Declared BEFORE the DataView constructors below — vis-data invokes
  // the filter callback during construction, so `filters` must already
  // be in scope (const hoisting puts it in the temporal dead zone
  // until this line is reached).
  const filters = {
    search:  '',
    faction: '',
    show:    'all',
  };

  // Visible-only DataSets that get rebuilt on every refresh().
  //
  // Started with DataView+filter callback but vis-timeline's bookkeeping
  // didn't always re-add items that moved from filtered-out → visible
  // (e.g. switching "Faction: Wei" back to "All factions" left non-Wei
  // characters hidden). Rebuilding from scratch sidesteps that.
  const visibleItems = new vis.DataSet();
  const visibleGroups = new vis.DataSet();

  const container = document.getElementById('timeline');
  const timeline = new vis.Timeline(container, visibleItems, visibleGroups, {
    stack: true,
    stackSubgroups: true,
    orientation: 'top',
    min: yearToDate(dataLo - pad * 4),
    max: yearToDate(dataHi + pad * 4),
    start: yearToDate(initialStart),
    end: yearToDate(initialEnd),
    zoomMin: 1000 * 60 * 60 * 24 * 30,         // ~1 month
    zoomMax: 1000 * 60 * 60 * 24 * 365 * 1000, // 1000 years
    margin: { item: { vertical: 4 } },
    // Alt + wheel zooms the timeline; plain wheel passes through to the
    // page so the browser's vertical scroll keeps working normally.
    // horizontalScroll is also gated on a wheel-with-modifier, so we
    // leave it off and rely on click-drag for panning.
    horizontalScroll: false,
    zoomKey: 'altKey',
    showCurrentTime: false,
    // Sort group rows top → bottom by each group's `order` field.
    // Chapters (-2) and Events (-1) stay pinned at the top; character
    // groups carry their birth_lo (a positive AD year), so they fall
    // below in earliest-born → latest-born order.
    groupOrder: 'order',
  });

  // --- filter handlers ---
  function shouldShowItem(it) {
    if (filters.show === 'chapters'   && it.kind === 'event')     return false;
    if (filters.show === 'events'     && it.kind === 'chapter')   return false;
    if (filters.show === 'characters' && it.kind !== 'character') return false;
    if (filters.search) {
      if (it.kind === 'character') {
        const g = groups.get(it.group);
        if (g && g._filterText && !g._filterText.includes(filters.search)) return false;
      } else if (it._filterText && !it._filterText.includes(filters.search)) {
        return false;
      }
    }
    if (filters.faction && it.kind === 'character') {
      const g = groups.get(it.group);
      if (g && String(g._factionId) !== filters.faction) return false;
    }
    return true;
  }

  function shouldShowGroup(g) {
    if (g.id === '__chapters__') return filters.show !== 'events' && filters.show !== 'characters';
    if (g.id === '__events__')   return filters.show !== 'chapters' && filters.show !== 'characters';
    // Character group.
    if (filters.faction && String(g._factionId) !== filters.faction) return false;
    if (filters.search && g._filterText && !g._filterText.includes(filters.search)) return false;
    return true;
  }

  function refresh() {
    const nextGroups = groups.get().filter(shouldShowGroup);
    const nextGroupIds = new Set(nextGroups.map(g => g.id));
    const nextItems = items.get().filter(
      it => nextGroupIds.has(it.group) && shouldShowItem(it)
    );
    // clear() + add() is the safe rebuild path — assigning straight
    // through `set` would leave behind stale ids that the new payload
    // doesn't mention.
    visibleGroups.clear();
    visibleGroups.add(nextGroups);
    visibleItems.clear();
    visibleItems.add(nextItems);
    updateStats(nextGroups, nextItems);
  }

  function updateStats(curGroups, curItems) {
    const visible = curGroups.filter(g => g.id !== '__chapters__' && g.id !== '__events__').length;
    const total = charactersData.length;
    const stats = document.getElementById('timeline-stats');
    if (stats) {
      stats.textContent =
        `${visible} of ${total} characters · ${curItems.length} items on screen`;
    }
  }

  document.getElementById('timeline-search').addEventListener('input', e => {
    filters.search = e.target.value.trim().toLowerCase();
    refresh();
  });
  document.getElementById('timeline-faction').addEventListener('change', e => {
    filters.faction = e.target.value;
    refresh();
  });
  document.getElementById('timeline-show').addEventListener('change', e => {
    filters.show = e.target.value;
    refresh();
  });
  document.getElementById('timeline-fit').addEventListener('click', () => {
    timeline.fit();
  });
  // vis-timeline's zoomIn/zoomOut take a percentage (0..1). 0.4 is a
  // comfortable step — roughly 1.5× per click in either direction.
  document.getElementById('timeline-zoom-in').addEventListener('click', () => {
    timeline.zoomIn(0.4);
  });
  document.getElementById('timeline-zoom-out').addEventListener('click', () => {
    timeline.zoomOut(0.4);
  });

  // --- detail panel ---
  const detailEl = document.getElementById('timeline-detail');
  const detailBody = detailEl.querySelector('.timeline-detail-body');

  function fmtRange(lo, hi) {
    const span = hi - lo;
    if (span <= 1.01) return String(Math.floor((lo + hi) / 2));
    return `${Math.floor(lo)}–${Math.ceil(hi)}`;
  }

  function renderDetail(it) {
    const d = it._data || {};
    if (it.kind === 'chapter') {
      detailBody.innerHTML =
        `<div class="timeline-detail-kind">Chapter</div>` +
        `<h5 class="timeline-detail-title">` +
          `<a href="/chapter/${d.num}">Chapter ${d.num} — ${escapeHtml(d.name)}</a>` +
        `</h5>` +
        `<dl class="timeline-detail-meta">` +
          `<dt>Year</dt><dd>${escapeHtml(d.date_str || '')} <span class="text-muted">(${fmtRange(d.year_lo, d.year_hi)})</span></dd>` +
        `</dl>`;
    } else if (it.kind === 'event') {
      const typeBadge = d.type_name
        ? `<span class="badge" style="background:${d.bg_colour};color:${d.font_colour};border:1px solid ${d.border_colour};">` +
            (d.icon ? `<i class="${escapeAttr(d.icon)} me-1" aria-hidden="true"></i>` : '') +
            escapeHtml(d.type_name) +
          `</span>`
        : '<span class="text-muted">No type</span>';
      detailBody.innerHTML =
        `<div class="timeline-detail-kind">Event</div>` +
        `<h5 class="timeline-detail-title">${escapeHtml(d.name)}</h5>` +
        `<dl class="timeline-detail-meta">` +
          `<dt>Type</dt><dd>${typeBadge}</dd>` +
          `<dt>Year</dt><dd>${escapeHtml(d.date_str || '')} <span class="text-muted">(${fmtRange(d.year_lo, d.year_hi)})</span></dd>` +
        `</dl>`;
    } else if (it.kind === 'character') {
      detailBody.innerHTML =
        `<div class="timeline-detail-kind">Character</div>` +
        `<h5 class="timeline-detail-title">` +
          `<a href="/characters/edit/${d.id}">${escapeHtml(d.name)}</a>` +
          (d.chinese_name ? ` <span class="text-muted">${escapeHtml(d.chinese_name)}</span>` : '') +
        `</h5>` +
        `<dl class="timeline-detail-meta">` +
          `<dt>Faction</dt><dd>${escapeHtml(d.faction_name || '—')}</dd>` +
          `<dt>Born</dt><dd>${escapeHtml(d.birth_str || '—')} <span class="text-muted">(${fmtRange(d.birth_lo, d.birth_hi)})</span></dd>` +
          `<dt>Died</dt><dd>${escapeHtml(d.death_str || '—')} <span class="text-muted">(${fmtRange(d.death_lo, d.death_hi)})</span></dd>` +
        `</dl>`;
    } else {
      return false;
    }
    detailEl.hidden = false;
    return true;
  }

  timeline.on('click', (props) => {
    if (props.what === 'item' && props.item != null) {
      const it = items.get(props.item);
      if (it) renderDetail(it);
    }
  });

  document.getElementById('timeline-detail-close').addEventListener('click', () => {
    detailEl.hidden = true;
    timeline.setSelection([]);
  });
  document.getElementById('timeline-reset').addEventListener('click', () => {
    filters.search = '';
    filters.faction = '';
    filters.show = 'all';
    document.getElementById('timeline-search').value = '';
    document.getElementById('timeline-faction').value = '';
    document.getElementById('timeline-show').value = 'all';
    refresh();
    timeline.setWindow(yearToDate(initialStart), yearToDate(initialEnd));
  });

  refresh();

  function readJson(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return [];
    try { return JSON.parse(el.textContent); }
    catch (_) { return []; }
  }
})();
