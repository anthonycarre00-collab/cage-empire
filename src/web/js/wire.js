/* ============================================================
   CAGE EMPIRE — The Wire Screen ("THE WIRE")
   ============================================================
   Phase INFO-SCREENS-BATCH-1 §1. Replaces the placeholder News
   nav item. Renders a paginated, filterable list of every
   news item in the world (16k+ rows across 24 DB topics
   collapsed to 16 UI filter groups).

   What the player sees:
     - Section header: "THE WIRE" (gold accent) + subtitle
       "What the world is saying".
     - Filter bar: topic dropdown (16 groups) + search input
       (200ms debounce) + sentiment dropdown.
     - News list: each item shows headline (clickable if
       fighter_id set → Fighter Profile), body excerpt, date,
       topic chip (color-coded by topic group), sentiment
       indicator (green/gray/red dot), source name, promo.
     - Pagination: 20 items/page.
     - Voice empty state: "The newswire is quiet. Advance a
       day and see what develops."

   Voice compliance (CONVENTIONS §14, VOICE_ENFORCEMENT):
     - No raw numbers where voice phrases exist (we show the
       sentiment tier label, not an int).
     - Headlines are shown verbatim (the news engine is the
       interpretation layer for news_items per CONVENTIONS
       §14.4).
     - Business-page register, no tabloid clichés added.
   ============================================================ */

window.CE = window.CE || {};

window.CE.wire = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    page: 1,
    filters: {
      topic: 'all',
      search: '',
      sentiment: 'all',
    },
    data: null,        // last fetched payload (for re-render on filter change)
    _searchTimer: null,
  };

  // ============================================================
  // HELPERS
  // ============================================================
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;');
  }

  /**
   * Sentiment → display metadata.
   * 'positive' (green) / 'neutral' (gray) / 'negative' (red).
   */
  function sentimentMeta(sent) {
    if (sent === 'positive') {
      return { label: 'Bullish', dot: 'ce-wire__sent--positive', chip: 'ce-chip-green' };
    }
    if (sent === 'negative') {
      return { label: 'Bearish', dot: 'ce-wire__sent--negative', chip: 'ce-chip-crimson' };
    }
    return { label: 'Neutral', dot: 'ce-wire__sent--neutral', chip: 'ce-chip-default' };
  }

  /**
   * Topic group → chip CSS class (color-coded by category).
   * This gives the player a quick visual scan: same color = same
   * category of news.
   */
  var TOPIC_CHIP = {
    'All Topics':    'ce-chip-default',
    'Signings':      'ce-chip-gold',
    'Injuries':      'ce-chip-crimson',
    'Suspensions':   'ce-chip-crimson',
    'Weigh-ins':     'ce-chip-default',
    'Fight Results': 'ce-chip-gold',
    'Card Reviews':  'ce-chip-gold',
    'Title Scene':   'ce-chip-gold',
    'Careers':       'ce-chip-default',
    'Bad Blood':     'ce-chip-crimson',
    'Finance':       'ce-chip-green',
    'Training Camps': 'ce-chip-default',
    'Staff':         'ce-chip-default',
    'Legacy':        'ce-chip-gold',
    'Milestones':    'ce-chip-gold',
    'The Wire':      'ce-chip-default',
  };

  function topicChipClass(label) {
    return TOPIC_CHIP[label] || 'ce-chip-default';
  }

  // ============================================================
  // RENDER — FILTER BAR
  // ============================================================
  function renderFilterBar() {
    var opts = (state.data && state.data.topic_options) || [];
    var optHtml = opts.map(function (o) {
      var sel = (state.filters.topic === o.value) ? ' selected' : '';
      return '<option value="' + escapeHtml(o.value) + '"' + sel + '>' +
        escapeHtml(o.label) + '</option>';
    }).join('');

    var sentOpts = [
      { v: 'all', l: 'All Sentiment' },
      { v: 'positive', l: 'Bullish Only' },
      { v: 'neutral', l: 'Neutral Only' },
      { v: 'negative', l: 'Bearish Only' },
    ];
    var sentHtml = sentOpts.map(function (o) {
      var sel = (state.filters.sentiment === o.v) ? ' selected' : '';
      return '<option value="' + o.v + '"' + sel + '>' + o.l + '</option>';
    }).join('');

    // Result count summary — voice phrased.
    var total = (state.data && state.data.total) || 0;
    var page = (state.data && state.data.page) || 1;
    var perPage = (state.data && state.data.per_page) || 20;
    var totalPages = (state.data && state.data.total_pages) || 1;
    var startIdx = total === 0 ? 0 : (page - 1) * perPage + 1;
    var endIdx = Math.min(page * perPage, total);
    var summary = total === 0
      ? 'The newswire is quiet.'
      : ('Showing ' + startIdx + '–' + endIdx + ' of ' + total +
         ' · page ' + page + ' of ' + totalPages);

    return '' +
      '<div class="ce-wire__filter-bar">' +
        '<div class="ce-wire__filters">' +
          '<div class="ce-wire__filter-group">' +
            '<label class="ce-wire__filter-label" for="ce-wire-topic">TOPIC</label>' +
            '<select id="ce-wire-topic" class="ce-wire__select">' + optHtml + '</select>' +
          '</div>' +
          '<div class="ce-wire__filter-group">' +
            '<label class="ce-wire__filter-label" for="ce-wire-sentiment">SENTIMENT</label>' +
            '<select id="ce-wire-sentiment" class="ce-wire__select">' + sentHtml + '</select>' +
          '</div>' +
          '<div class="ce-wire__filter-group ce-wire__filter-group--search">' +
            '<label class="ce-wire__filter-label" for="ce-wire-search">SEARCH</label>' +
            '<input type="text" id="ce-wire-search" class="ce-wire__search" ' +
              'placeholder="Headlines, bodies, fighter names…" ' +
              'value="' + escapeHtml(state.filters.search) + '" maxlength="120" />' +
          '</div>' +
          '<button id="ce-wire-clear" type="button" class="ce-btn ce-btn-ghost ce-wire__clear-btn">Reset</button>' +
        '</div>' +
        '<div class="ce-wire__summary">' + escapeHtml(summary) + '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — NEWS LIST
  // ============================================================
  function renderList() {
    var items = (state.data && state.data.items) || [];
    if (!items.length) {
      return '' +
        '<div class="ce-wire__empty">' +
          '<div class="ce-wire__empty-title">The newswire is quiet.</div>' +
          '<div class="ce-wire__empty-body">Advance a day and see what develops.</div>' +
        '</div>';
    }
    var rows = items.map(function (it) {
      var sent = sentimentMeta(it.sentiment);
      var chipCls = topicChipClass(it.topic_group_label);

      // Headline — clickable if fighter_id is set.
      var headlineHtml;
      if (it.fighter_id) {
        headlineHtml = '<a class="ce-link ce-wire__headline" href="#" ' +
          'data-fighter-id="' + it.fighter_id + '">' +
          escapeHtml(it.headline) + '</a>';
      } else {
        headlineHtml = '<span class="ce-wire__headline ce-wire__headline--plain">' +
          escapeHtml(it.headline) + '</span>';
      }

      // Meta line: date · source · promo (if any) · fighter name (if any).
      var metaParts = [];
      metaParts.push('<span class="ce-wire__meta-date">' +
        escapeHtml(it.published_at_display || '—') + '</span>');
      if (it.source_name) {
        metaParts.push('<span class="ce-wire__meta-source">' +
          escapeHtml(it.source_name) + '</span>');
      }
      if (it.promo_name) {
        metaParts.push('<span class="ce-wire__meta-promo">' +
          escapeHtml(it.promo_name) + '</span>');
      }
      if (it.fighter_name) {
        metaParts.push('<span class="ce-wire__meta-fighter">' +
          escapeHtml(it.fighter_name) + '</span>');
      }

      return '' +
        '<article class="ce-wire__item" data-news-id="' + it.news_item_id + '">' +
          '<div class="ce-wire__item-head">' +
            '<div class="ce-wire__item-chips">' +
              '<span class="ce-chip ' + chipCls + '">' +
                escapeHtml(it.topic_group_label) + '</span>' +
              '<span class="ce-wire__sent ' + sent.dot + '" title="' +
                escapeHtml(sent.label) + '"></span>' +
            '</div>' +
            '<div class="ce-wire__item-meta">' + metaParts.join('<span class="ce-wire__meta-sep">·</span>') + '</div>' +
          '</div>' +
          '<div class="ce-wire__item-body">' +
            headlineHtml +
            '<div class="ce-wire__excerpt">' + escapeHtml(it.body_excerpt) + '</div>' +
          '</div>' +
        '</article>';
    }).join('');

    return '<div class="ce-wire__list">' + rows + '</div>';
  }

  // ============================================================
  // RENDER — PAGINATION
  // ============================================================
  function renderPagination() {
    var d = state.data;
    if (!d || !d.total) return '';
    var page = d.page;
    var total = d.total_pages;
    if (total <= 1) return '';

    // Build a compact page list: first, last, ±2 around current.
    var pages = new Set([1, total, page]);
    for (var i = -2; i <= 2; i++) {
      var p = page + i;
      if (p >= 1 && p <= total) pages.add(p);
    }
    var sorted = Array.from(pages).sort(function (a, b) { return a - b; });

    var html = '<div class="ce-wire__pagination">';
    html += '<button type="button" class="ce-page-btn" data-page="' + (page - 1) + '"' +
      (page <= 1 ? ' disabled' : '') + '>← Prev</button>';
    var prevP = 0;
    sorted.forEach(function (p) {
      if (p - prevP > 1) {
        html += '<span class="ce-page-ellipsis">…</span>';
      }
      var cls = (p === page) ? 'ce-page-btn ce-page-btn--active' : 'ce-page-btn';
      html += '<button type="button" class="' + cls + '" data-page="' + p + '">' + p + '</button>';
      prevP = p;
    });
    html += '<button type="button" class="ce-page-btn" data-page="' + (page + 1) + '"' +
      (page >= total ? ' disabled' : '') + '>Next →</button>';
    html += '</div>';
    return html;
  }

  // ============================================================
  // MAIN RENDER
  // ============================================================
  function render() {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var html = '' +
      '<div class="ce-wire">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">📰</span>' +
            '<span class="ce-sec-title ce-sec-title-gold">THE WIRE</span>' +
            '<span class="ce-sec-sub ce-mono">what the world is saying</span>' +
          '</div>' +
        '</div>' +
        renderFilterBar() +
        renderList() +
        renderPagination() +
      '</div>';
    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    var topicSel = document.getElementById('ce-wire-topic');
    if (topicSel) topicSel.addEventListener('change', function () {
      state.filters.topic = topicSel.value;
      state.page = 1;
      loadAndRender();
    });

    var sentSel = document.getElementById('ce-wire-sentiment');
    if (sentSel) sentSel.addEventListener('change', function () {
      state.filters.sentiment = sentSel.value;
      state.page = 1;
      loadAndRender();
    });

    var searchInput = document.getElementById('ce-wire-search');
    if (searchInput) searchInput.addEventListener('input', function () {
      if (state._searchTimer) clearTimeout(state._searchTimer);
      state._searchTimer = setTimeout(function () {
        state.filters.search = searchInput.value;
        state.page = 1;
        loadAndRender();
      }, 200);
    });

    var clearBtn = document.getElementById('ce-wire-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () {
      state.filters = { topic: 'all', search: '', sentiment: 'all' };
      state.page = 1;
      loadAndRender();
    });

    // Fighter-name hyperlinks → Fighter Profile.
    document.querySelectorAll('.ce-wire__headline[data-fighter-id]').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        var fid = link.getAttribute('data-fighter-id');
        if (fid) window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
      });
    });

    // Pagination.
    document.querySelectorAll('.ce-wire__pagination .ce-page-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.disabled) return;
        var p = parseInt(btn.getAttribute('data-page'), 10);
        if (!p || p < 1) return;
        state.page = p;
        loadAndRender();
        // Scroll the list back to top after a page change.
        var list = document.querySelector('.ce-wire__list');
        if (list) list.scrollTop = 0;
        var screen = document.getElementById('ce-screen');
        if (screen) screen.scrollTop = 0;
      });
    });
  }

  // ============================================================
  // LOAD + RENDER
  // ============================================================
  function loadAndRender() {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Reading the wires…</div></div>';
    }
    return window.CE.bridge.getWireData(state.page, state.filters).then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load The Wire</div><div>' +
            escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      state.data = data;
      render();
    }).catch(function (err) {
      console.error('[wire] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load The Wire</div><div>' +
          escapeHtml(String(err)) + '</div></div>';
      }
    });
  }

  // ============================================================
  // PUBLIC API
  // ============================================================
  return {
    loadAndRender: loadAndRender,
    render: render,
    state: state,
  };
})();
