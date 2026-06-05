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

  // --- build groups + items ---
  const groups = new vis.DataSet();
  const items  = new vis.DataSet();

  groups.add({
    id: '__chapters__',
    content: 'Chapters',
    className: 'tl-group-chapters',
    order: -2,
  });
  groups.add({
    id: '__events__',
    content: 'Events',
    className: 'tl-group-events',
    order: -1,
  });

  // Chapter points.
  chaptersData.forEach(c => {
    const mid = midYear(c.year_lo, c.year_hi);
    items.add({
      id: `ch-${c.id}`,
      group: '__chapters__',
      kind: 'chapter',
      content: `<a href="/chapter/${c.num}" title="${escapeHtml(c.name)} — ${escapeHtml(c.date_str)}">${c.num}</a>`,
      start: yearToDate(mid),
      type: 'point',
      className: 'tl-chapter',
      _filterText: `${c.num} ${c.name}`.toLowerCase(),
    });
  });

  // Event points.
  eventsData.forEach(e => {
    const mid = midYear(e.year_lo, e.year_hi);
    items.add({
      id: `ev-${e.id}`,
      group: '__events__',
      kind: 'event',
      content: `<span title="${escapeHtml(e.name)} — ${escapeHtml(e.date_str)}">${escapeHtml(e.name)}</span>`,
      start: yearToDate(mid),
      type: 'point',
      className: 'tl-event',
      style: `--tl-dot: ${e.bg_colour}; --tl-dot-border: ${e.border_colour};`,
      _filterText: e.name.toLowerCase(),
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

  // --- DataView for filtering ---
  const itemView = new vis.DataView(items, {
    filter: function (it) { return shouldShowItem(it); },
  });
  const groupView = new vis.DataView(groups, {
    filter: function (g) { return shouldShowGroup(g); },
  });

  const container = document.getElementById('timeline');
  const timeline = new vis.Timeline(container, itemView, groupView, {
    stack: true,
    stackSubgroups: true,
    orientation: 'top',
    min: yearToDate(dataLo - pad * 4),
    max: yearToDate(dataHi + pad * 4),
    start: yearToDate(dataLo - pad),
    end: yearToDate(dataHi + pad),
    zoomMin: 1000 * 60 * 60 * 24 * 30,         // ~1 month
    zoomMax: 1000 * 60 * 60 * 24 * 365 * 1000, // 1000 years
    margin: { item: { vertical: 4 } },
    horizontalScroll: true,
    zoomKey: 'ctrlKey',
    showCurrentTime: false,
    format: {
      // The default formatter renders the year axis fine for AD dates;
      // it auto-falls back through years/months/days as the zoom level
      // changes. Nothing to override unless we add BC-era display.
    },
  });

  // --- filter state + handlers ---
  const filters = {
    search:  '',
    faction: '',
    show:    'all',
  };

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
    itemView.refresh();
    groupView.refresh();
    updateStats();
  }

  function updateStats() {
    const visible = groupView.getIds().filter(id => id !== '__chapters__' && id !== '__events__').length;
    const total = charactersData.length;
    const itemsCount = itemView.length;
    const stats = document.getElementById('timeline-stats');
    if (stats) {
      stats.textContent =
        `${visible} of ${total} characters · ${itemsCount} items on screen`;
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
  document.getElementById('timeline-reset').addEventListener('click', () => {
    filters.search = '';
    filters.faction = '';
    filters.show = 'all';
    document.getElementById('timeline-search').value = '';
    document.getElementById('timeline-faction').value = '';
    document.getElementById('timeline-show').value = 'all';
    refresh();
    timeline.fit();
  });

  refresh();

  function readJson(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return [];
    try { return JSON.parse(el.textContent); }
    catch (_) { return []; }
  }
})();
