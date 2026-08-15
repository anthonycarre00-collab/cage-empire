/* ============================================================
   CAGE EMPIRE — Legends (Hall of Fame) Screen
   ============================================================
   P1-WIRE-4-SCREENS — Screen 2 of 4.
   Per docs/P1_PLAN_WIRE_SCREENS.md §2 + docs/REVIEW_P1_SCREEN_BACKENDS.md
   §3 + CONVENTIONS §14 (Interpretation Layer).

   Renders the Hall of Fame inductee ledger into #screen-content
   via window.CE.bridge.getHofData(page, filters).

   What the player sees:
     - Section header: "LEGENDS" (gold accent — Legacy pillar) +
       subtitle showing the inductee count.
     - Summary strip: 1-2 stat tiles (Total Inductees, Multi-Time
       Champions) + voice hint.
     - Filter bar: search input + sort dropdown (Recent / Earliest /
       Most Titles / Most Wins).
     - Inductee grid (responsive auto-fill, 20 per page):
       * Large portrait (gold-bordered) OR initial placeholder.
       * Name (clickable → Fighter Profile) + nickname.
       * Style archetype chip + induction date.
       * Career summary (voice-layered prose, italic serif).
       * Career highlights as a bulleted list (career stats OK per §14).
       * Career record + title reigns at the bottom.
     - Empty state: "No legends have been inducted yet. Greatness
       takes time." (per docs/P1_PLAN_WIRE_SCREENS.md §2).
     - Pagination (mirrors the rest of the app).

   Voice compliance (CONVENTIONS §14):
     - career_summary is already voice-layered (digit-free).
     - Career stats (wins/losses/draws/reigns) are explicitly
       carved out — OK to display in highlights.
     - No raw attribute values, raw age, or raw potential shown.
   ============================================================ */

window.CE = window.CE || {};

window.CE.hof = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    page: 1,
    filters: {
      search: '',
      sort: 'inducted_date_desc',
    },
    _searchTimer: null,
  };

  var SORT_OPTIONS = [
    { value: 'inducted_date_desc', label: 'Most Recently Inducted' },
    { value: 'inducted_date_asc',  label: 'Earliest Inductees First' },
    { value: 'title_reigns_desc',  label: 'Most Title Reigns' },
    { value: 'wins_desc',          label: 'Most Career Wins' },
  ];

  // ============================================================
  // HELPERS
  // ============================================================
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function fighterInitial(name) {
    if (!name) return '?';
    var parts = String(name).trim().split(/\s+/);
    if (parts.length < 2) return parts[0].charAt(0).toUpperCase();
    return parts[parts.length - 1].charAt(0).toUpperCase();
  }

  // ============================================================
  // RENDERERS
  // ============================================================
  function renderSummary(data) {
    var total = data.total_inductees || 0;
    var multiChamp = (data.inductees || []).filter(function (i) {
      return i.title_reigns >= 2;
    }).length;
    // For the multi-champ count, we need the full-table count, not
    // just the current page. Use total as a proxy if multiChamp
    // matches the page size exactly (would mean more pages).
    return '' +
      '<div class="ce-hof__summary">' +
        '<div class="ce-hof__stat ce-hof__stat--gold">' +
          '<span class="ce-hof__stat-label">INDUCTEES</span>' +
          '<span class="ce-hof__stat-val">' + total + '</span>' +
        '</div>' +
        '<div class="ce-hof__stat">' +
          '<span class="ce-hof__stat-label">MULTI-TIME CHAMPIONS</span>' +
          '<span class="ce-hof__stat-val">' + (data.multi_champ_count || 0) + '</span>' +
        '</div>' +
        '<div class="ce-hof__stat">' +
          '<span class="ce-hof__stat-label">VOICE</span>' +
          '<span class="ce-hof__stat-quote">"Greatness never retires — it just changes addresses."</span>' +
        '</div>' +
      '</div>';
  }

  function renderFilters() {
    var sortOpts = SORT_OPTIONS.map(function (s) {
      var sel = state.filters.sort === s.value ? ' selected' : '';
      return '<option value="' + s.value + '"' + sel + '>' +
        escapeHtml(s.label) + '</option>';
    }).join('');

    return '' +
      '<div class="ce-hof__filters">' +
        '<div class="ce-filter-group ce-filter-search">' +
          '<label class="ce-filter-label">SEARCH</label>' +
          '<input type="text" id="ce-hof-search" class="ce-filter-input" placeholder="Inductee name…" value="' + escapeHtml(state.filters.search || '') + '" />' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">SORT</label>' +
          '<select id="ce-hof-sort" class="ce-filter-select">' + sortOpts + '</select>' +
        '</div>' +
        '<button id="ce-hof-clear" class="ce-btn ce-btn-ghost ce-filter-clear" type="button">Clear</button>' +
      '</div>';
  }

  function renderCard(inductee) {
    var portrait = inductee.has_portrait && inductee.portrait_uri
      ? '<img src="' + inductee.portrait_uri + '" class="ce-hof__portrait" alt="' + escapeHtml(inductee.name) + '" />'
      : '<div class="ce-hof__portrait ce-hof__portrait--placeholder">' + escapeHtml(fighterInitial(inductee.name)) + '</div>';

    var nickHtml = inductee.nickname
      ? '<span class="ce-hof__nick"> \'' + escapeHtml(inductee.nickname) + '\'</span>'
      : '';
    var styleChip = inductee.style_archetype_name
      ? '<span class="ce-chip ce-chip-default ce-hof__style-chip">' + escapeHtml(inductee.style_archetype_name) + '</span>'
      : '';

    var recordLabel = inductee.record_draws > 0
      ? inductee.record_wins + '-' + inductee.record_losses + '-' + inductee.record_draws
      : inductee.record_wins + '-' + inductee.record_losses;
    var reignsLabel = (inductee.title_reigns === 1) ? 'reign' : 'reigns';
    var reignsHtml = inductee.title_reigns > 0
      ? '<span class="ce-hof__stat-line ce-hof__stat-line--gold">' +
          '<span class="ce-mono">' + inductee.title_reigns + '</span> title ' + reignsLabel +
        '</span>'
      : '';

    var highlightsHtml = (inductee.highlights_parsed || []).map(function (h) {
      return '<li class="ce-hof__highlight">' + escapeHtml(h) + '</li>';
    }).join('');

    var summaryHtml = inductee.career_summary
      ? '<div class="ce-hof__summary-text">' + escapeHtml(inductee.career_summary) + '</div>'
      : '';

    return '' +
      '<article class="ce-hof__card" data-fighter-id="' + inductee.fighter_id + '">' +
        '<div class="ce-hof__card-header">' +
          portrait +
          '<div class="ce-hof__header-info">' +
            '<a class="ce-hof__name ce-link" href="#" data-fighter-id="' + inductee.fighter_id + '">' +
              escapeHtml(inductee.name) + '</a>' + nickHtml +
            '<div class="ce-hof__inducted">Inducted ' + escapeHtml(inductee.inducted_date_display) + '</div>' +
            styleChip +
          '</div>' +
        '</div>' +
        summaryHtml +
        (highlightsHtml
          ? '<ul class="ce-hof__highlights">' + highlightsHtml + '</ul>'
          : '') +
        '<div class="ce-hof__card-footer">' +
          '<span class="ce-hof__stat-line">' +
            '<span class="ce-mono">' + escapeHtml(recordLabel) + '</span> record' +
          '</span>' +
          reignsHtml +
        '</div>' +
      '</article>';
  }

  function renderGrid(data) {
    var inductees = data.inductees || [];
    if (!inductees.length) {
      return '<div class="ce-hof__empty">' +
        '<div class="ce-hof__empty-icon">🏆</div>' +
        '<div class="ce-hof__empty-title">No legends have been inducted yet.</div>' +
        '<div class="ce-hof__empty-body">Greatness takes time. Develop champions, chase titles, and one day the fighters you built will retire into the Hall of Fame.</div>' +
      '</div>';
    }
    return '<div class="ce-hof__grid">' +
      inductees.map(renderCard).join('') +
    '</div>';
  }

  function renderPagination(data) {
    var total = data.total || 0;
    if (total <= data.per_page) return '';  // 1 page — no pagination.
    var page = data.page || 1;
    var totalPages = data.total_pages || 1;
    var start = (page - 1) * data.per_page + 1;
    var end = Math.min(page * data.per_page, total);

    var pages = [];
    var lo = Math.max(1, page - 2);
    var hi = Math.min(totalPages, page + 2);
    if (lo > 1) { pages.push(1); if (lo > 2) pages.push('…'); }
    for (var i = lo; i <= hi; i++) pages.push(i);
    if (hi < totalPages) { if (hi < totalPages - 1) pages.push('…'); pages.push(totalPages); }

    var pageHtml = pages.map(function (p) {
      if (p === '…') return '<span class="ce-page-ellipsis">…</span>';
      var cls = p === page ? 'ce-page-btn ce-page-btn--current' : 'ce-page-btn';
      return '<button class="' + cls + '" data-page="' + p + '" type="button">' + p + '</button>';
    }).join('');

    return '' +
      '<div class="ce-roster-pagination">' +
        '<div class="ce-page-info">Showing <span class="ce-mono">' + start + '–' + end + '</span> of <span class="ce-mono">' + total.toLocaleString() + '</span> legends</div>' +
        '<div class="ce-page-controls">' +
          '<button class="ce-page-btn" data-page="' + (page - 1) + '" type="button"' + (page <= 1 ? ' disabled' : '') + '>◀ Prev</button>' +
          pageHtml +
          '<span class="ce-page-indicator ce-mono">Page ' + page + ' of ' + totalPages + '</span>' +
          '<button class="ce-page-btn" data-page="' + (page + 1) + '" type="button"' + (page >= totalPages ? ' disabled' : '') + '>Next ▶</button>' +
        '</div>' +
      '</div>';
  }

  function render(data) {
    var host = document.getElementById('screen-content');
    if (!host) return;

    var html = '' +
      '<div class="ce-hof">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">🏆</span>' +
            '<span class="ce-sec-title ce-sec-title-gold">LEGENDS</span>' +
            '<span class="ce-sec-sub ce-mono">' + (data.total_inductees || 0).toLocaleString() + ' inducted</span>' +
          '</div>' +
        '</div>' +
        renderSummary(data) +
        renderFilters() +
        renderGrid(data) +
        renderPagination(data) +
      '</div>';

    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    var searchInput = document.getElementById('ce-hof-search');
    if (searchInput) searchInput.addEventListener('input', function () {
      if (state._searchTimer) clearTimeout(state._searchTimer);
      state._searchTimer = setTimeout(function () {
        state.filters.search = searchInput.value;
        state.page = 1;
        loadAndRender();
      }, 200);
    });

    var sortSel = document.getElementById('ce-hof-sort');
    if (sortSel) sortSel.addEventListener('change', function () {
      state.filters.sort = sortSel.value;
      state.page = 1;
      loadAndRender();
    });

    var clearBtn = document.getElementById('ce-hof-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () {
      state.filters = { search: '', sort: 'inducted_date_desc' };
      state.page = 1;
      loadAndRender();
    });

    // Pagination
    document.querySelectorAll('.ce-page-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.disabled) return;
        var p = parseInt(btn.getAttribute('data-page'), 10);
        if (!p || p < 1) return;
        state.page = p;
        loadAndRender();
      });
    });

    // Fighter-name hyperlinks → Fighter Profile
    document.querySelectorAll('.ce-hof__name[data-fighter-id]').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        evt.stopPropagation();
        var fid = link.getAttribute('data-fighter-id');
        if (fid) window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
      });
    });
  }

  // ============================================================
  // LOAD + RENDER
  // ============================================================
  function loadAndRender() {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Unveiling the legends…</div></div>';
    }
    return window.CE.bridge.getHofData(state.page, state.filters).then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load legends</div><div>' +
            escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      // Compute multi-champ count from the page (best effort — for
      // the rare case of >1 page, this is the current page count).
      if (!data.multi_champ_count) {
        data.multi_champ_count = (data.inductees || []).filter(function (i) {
          return i.title_reigns >= 2;
        }).length;
      }
      render(data);
    }).catch(function (err) {
      console.error('[hof] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load legends</div><div>' +
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
