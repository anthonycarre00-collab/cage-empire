/* ============================================================
   CAGE EMPIRE — Bad Blood (Rivalries) Screen
   ============================================================
   P1-WIRE-4-SCREENS — Screen 1 of 4.
   Per docs/P1_PLAN_WIRE_SCREENS.md §1 + docs/REVIEW_P1_SCREEN_BACKENDS.md
   §2 + CONVENTIONS §14 (Interpretation Layer).

   Renders the rivalry ledger into #screen-content via
   window.CE.bridge.getRivalriesData(page, filters).

   What the player sees:
     - Section header: "BAD BLOOD" (crimson accent — Impact moment)
       + subtitle showing the active rivalry count.
     - Summary strip: 4 stat tiles — Active, Dormant, Boiling (heat
       80+), Title Rivalries.
     - Filter bar: type dropdown, heat-band dropdown, scope dropdown,
       search input (200ms debounce).
     - Rivalry cards (20 per page):
       * Two fighters side-by-side (names clickable → Fighter Profile)
         with career-stage chip under each.
       * VS divider with H2H record ("6-2-0") + fights count.
       * Heat meter (0-100 visual bar, color-coded by band) + voice
         phrase ("simmering" / "heating up" / "boiling over" /
         "ready to explode").
       * Type chip (color-coded: bad_blood=crimson, title_rivalry=gold,
         rematch_hungry=warning, callout=default).
       * Origin description (the voice-layer narrative).
       * Last-escalation footer ("Last escalated: 2026-09-14") or
         "Went dormant on …" for inactive rows.
     - Click a card → expand inline to show the full origin
       description (no separate modal needed — the description
       already lives on the card).
     - Pagination (mirrors staff_market + free_agents).

   Voice compliance (CONVENTIONS §14):
     - rivalry_heat (0-100 int) is OK to display — relationship
       rating, NOT a fighter attribute.
     - Heat phrase wraps the integer ("BOILING OVER · 92").
     - Head-to-head record is a career stat — OK to display.
     - Career-stage descriptors come from voice.describe_career_stage
       (already voice-layered in the DB by rivalries.py).
     - origin_description is already voice-layered.
   ============================================================ */

window.CE = window.CE || {};

window.CE.rivalries = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    page: 1,
    filters: {
      type: 'all',
      heat_band: 'all',
      scope: 'all',
      search: '',
    },
    byType: [],
    _searchTimer: null,
    _expandedRivalryId: null,
  };

  var TYPE_OPTIONS = [
    { value: 'all',              label: 'All Types' },
    { value: 'bad_blood',        label: 'Bad Blood' },
    { value: 'title_rivalry',    label: 'Title Rivalry' },
    { value: 'rematch_hungry',   label: 'Rematch Hungry' },
    { value: 'callout',          label: 'Callout' },
    { value: 'style_clash',      label: 'Style Clash' },
    { value: 'disrespect',       label: 'Disrespect' },
    { value: 'stolen_opportunity', label: 'Stolen Opportunity' },
  ];

  var HEAT_BAND_OPTIONS = [
    { value: 'all',       label: 'All Heat Bands' },
    { value: 'boiling',   label: 'Ready to Explode (80-100)' },
    { value: 'hot',       label: 'Boiling Over (60-79)' },
    { value: 'warm',      label: 'Heating Up (40-59)' },
    { value: 'simmering', label: 'Simmering (20-39)' },
    { value: 'cold',      label: 'Cold / Dormant (0-19)' },
  ];

  var SCOPE_OPTIONS = [
    { value: 'all',                label: 'All Rivalries' },
    { value: 'player_promo',       label: 'My Promotion' },
  ];

  // ============================================================
  // HELPERS
  // ============================================================
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function formatDate(dateStr) {
    if (!dateStr) return '—';
    var parts = String(dateStr).split('-');
    if (parts.length !== 3) return dateStr;
    var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var m = parseInt(parts[1], 10);
    return (MONTHS[m - 1] || '?') + ' ' + parseInt(parts[2], 10) + ', ' + parts[0];
  }

  /** Heat-band CSS class — drives the heat-meter color. */
  function heatBandClass(heat) {
    var h = Number(heat || 0);
    if (h >= 80) return 'boiling';
    if (h >= 60) return 'hot';
    if (h >= 40) return 'warm';
    if (h >= 20) return 'simmering';
    return 'cold';
  }

  /** Type-chip CSS class — color-coded rivalry type badge. */
  function typeChipClass(rtype) {
    switch (rtype) {
      case 'bad_blood':          return 'ce-chip ce-chip-crimson';
      case 'title_rivalry':      return 'ce-chip ce-chip-gold';
      case 'rematch_hungry':     return 'ce-chip ce-chip-warning';
      case 'callout':            return 'ce-chip ce-chip-default';
      case 'style_clash':        return 'ce-chip ce-chip-default';
      case 'disrespect':         return 'ce-chip ce-chip-crimson';
      case 'stolen_opportunity': return 'ce-chip ce-chip-warning';
      default:                   return 'ce-chip ce-chip-default';
    }
  }

  /** First letter of the fighter's last name — placeholder portrait. */
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
    return '' +
      '<div class="ce-riv__summary">' +
        '<div class="ce-riv__stat">' +
          '<span class="ce-riv__stat-label">ACTIVE</span>' +
          '<span class="ce-riv__stat-val">' + (data.active_count || 0) + '</span>' +
        '</div>' +
        '<div class="ce-riv__stat">' +
          '<span class="ce-riv__stat-label">DORMANT</span>' +
          '<span class="ce-riv__stat-val">' + (data.dormant_count || 0) + '</span>' +
        '</div>' +
        '<div class="ce-riv__stat ce-riv__stat--boiling">' +
          '<span class="ce-riv__stat-label">READY TO EXPLODE</span>' +
          '<span class="ce-riv__stat-val">' + (data.boiling_count || 0) + '</span>' +
        '</div>' +
        '<div class="ce-riv__stat ce-riv__stat--gold">' +
          '<span class="ce-riv__stat-label">TITLE RIVALRIES</span>' +
          '<span class="ce-riv__stat-val">' + (data.title_rivalry_count || 0) + '</span>' +
        '</div>' +
      '</div>';
  }

  function renderFilters() {
    var typeOpts = TYPE_OPTIONS.map(function (t) {
      var sel = state.filters.type === t.value ? ' selected' : '';
      return '<option value="' + t.value + '"' + sel + '>' +
        escapeHtml(t.label) + '</option>';
    }).join('');

    var heatOpts = HEAT_BAND_OPTIONS.map(function (h) {
      var sel = state.filters.heat_band === h.value ? ' selected' : '';
      return '<option value="' + h.value + '"' + sel + '>' +
        escapeHtml(h.label) + '</option>';
    }).join('');

    var scopeOpts = SCOPE_OPTIONS.map(function (s) {
      var sel = state.filters.scope === s.value ? ' selected' : '';
      return '<option value="' + s.value + '"' + sel + '>' +
        escapeHtml(s.label) + '</option>';
    }).join('');

    return '' +
      '<div class="ce-riv__filters">' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">TYPE</label>' +
          '<select id="ce-riv-type" class="ce-filter-select">' + typeOpts + '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">HEAT</label>' +
          '<select id="ce-riv-heat" class="ce-filter-select">' + heatOpts + '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">SCOPE</label>' +
          '<select id="ce-riv-scope" class="ce-filter-select">' + scopeOpts + '</select>' +
        '</div>' +
        '<div class="ce-filter-group ce-filter-search">' +
          '<label class="ce-filter-label">SEARCH</label>' +
          '<input type="text" id="ce-riv-search" class="ce-filter-input" placeholder="Fighter name…" value="' + escapeHtml(state.filters.search || '') + '" />' +
        '</div>' +
        '<button id="ce-riv-clear" class="ce-btn ce-btn-ghost ce-filter-clear" type="button">Clear</button>' +
      '</div>';
  }

  function renderFighterSide(fighter, sideClass) {
    var stageHtml = fighter.career_stage
      ? '<div class="ce-riv__fighter-stage">' + escapeHtml(fighter.career_stage) + '</div>'
      : '';
    var nickHtml = fighter.nickname
      ? '<span class="ce-riv__fighter-nick"> \'' + escapeHtml(fighter.nickname) + '\'</span>'
      : '';
    return '' +
      '<div class="ce-riv__fighter ' + sideClass + '">' +
        '<div class="ce-riv__fighter-portrait">' + escapeHtml(fighterInitial(fighter.name)) + '</div>' +
        '<div class="ce-riv__fighter-info">' +
          '<a class="ce-riv__fighter-name ce-link" href="#" data-fighter-id="' + fighter.id + '">' +
            escapeHtml(fighter.name) + '</a>' + nickHtml +
          stageHtml +
        '</div>' +
      '</div>';
  }

  function renderRivalryCard(riv) {
    var isExpanded = state._expandedRivalryId === riv.rivalry_id;
    var heatClass = heatBandClass(riv.rivalry_heat);
    var chipCls = typeChipClass(riv.rivalry_type);
    var heatPct = Math.max(0, Math.min(100, Number(riv.rivalry_heat || 0)));
    var heatBar = '' +
      '<div class="ce-riv__heat-meter">' +
        '<div class="ce-riv__heat-bar ce-riv__heat-bar--' + heatClass + '" style="width:' + heatPct + '%"></div>' +
      '</div>';
    var heatLabel = '' +
      '<span class="ce-riv__heat-phrase ce-riv__heat-phrase--' + heatClass + '">' +
        escapeHtml((riv.heat_phrase || '').toUpperCase()) +
      '</span>';

    var footerDate = riv.is_active
      ? (riv.last_escalation_date
          ? 'Last escalated ' + escapeHtml(formatDate(riv.last_escalation_date))
          : 'Simmering since ' + escapeHtml(formatDate(riv.created_at)))
      : 'Went dormant on ' + escapeHtml(formatDate(riv.updated_at));

    var statusChip = riv.is_active
      ? ''
      : '<span class="ce-chip ce-chip-default ce-riv__dormant-chip">DORMANT</span>';

    var fightsLabel = (riv.fights_count === 1) ? '1 fight' : (riv.fights_count + ' fights');

    // CLEANUP-AND-FIX Bug 9 — show "Haven't met yet" when the
    // rivalry has no recorded fights OR when the head_to_head is
    // 0-0 / 0-0-0 despite fights_count > 0 (data-drift case).
    var h2hDisplay = riv.head_to_head || '';
    var fc = Number(riv.fights_count || 0);
    var zeroZero = (h2hDisplay === '0-0' || h2hDisplay === '0-0-0');
    if (fc === 0 || (fc > 0 && zeroZero)) {
      h2hDisplay = "Haven't met yet";
    }

    var originHtml = '';
    if (isExpanded && riv.origin_description) {
      originHtml = '<div class="ce-riv__origin">' +
        escapeHtml(riv.origin_description) + '</div>';
    }

    return '' +
      '<article class="ce-riv__card' + (isExpanded ? ' ce-riv__card--expanded' : '') +
        (riv.is_active ? '' : ' ce-riv__card--dormant') + '" data-rivalry-id="' + riv.rivalry_id + '">' +
        '<div class="ce-riv__card-top">' +
          '<span class="' + chipCls + '">' + escapeHtml(riv.type_label) + '</span>' +
          statusChip +
          '<span class="ce-riv__fights">' + escapeHtml(fightsLabel) + '</span>' +
        '</div>' +
        '<div class="ce-riv__vs-row">' +
          renderFighterSide(riv.fighter_a, 'ce-riv__fighter--a') +
          '<div class="ce-riv__vs">' +
            '<div class="ce-riv__vs-label">VS</div>' +
            '<div class="ce-riv__h2h ce-mono">' + escapeHtml(h2hDisplay) + '</div>' +
          '</div>' +
          renderFighterSide(riv.fighter_b, 'ce-riv__fighter--b') +
        '</div>' +
        '<div class="ce-riv__heat-row">' +
          '<div class="ce-riv__heat-meter-wrap">' +
            heatBar +
          '</div>' +
          '<div class="ce-riv__heat-label">' + heatLabel + '</div>' +
        '</div>' +
        (riv.origin_description && !isExpanded
          ? '<div class="ce-riv__origin-preview">' +
              escapeHtml(riv.origin_description.slice(0, 140)) +
              (riv.origin_description.length > 140 ? '…' : '') +
            '</div>'
          : '') +
        originHtml +
        '<div class="ce-riv__footer">' +
          '<span class="ce-riv__footer-date">' + footerDate + '</span>' +
          '<span class="ce-riv__expand-hint">' +
            (isExpanded ? '▲ Collapse' : '▼ Expand story') + '</span>' +
        '</div>' +
      '</article>';
  }

  function renderList(data) {
    var rivalries = data.rivalries || [];
    if (!rivalries.length) {
      return '<div class="ce-riv__empty">' +
        '<div class="ce-riv__empty-title">No bad blood brewing.</div>' +
        '<div class="ce-riv__empty-body">Rivalries develop over time — through callouts, title fights, and close decisions. Advance a few days and the heat will rise.</div>' +
      '</div>';
    }
    return '<div class="ce-riv__list">' +
      rivalries.map(renderRivalryCard).join('') +
    '</div>';
  }

  function renderPagination(data) {
    var total = data.total || 0;
    var page = data.page || 1;
    var totalPages = data.total_pages || 1;
    var start = total === 0 ? 0 : (page - 1) * data.per_page + 1;
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
        '<div class="ce-page-info">Showing <span class="ce-mono">' + start + '–' + end + '</span> of <span class="ce-mono">' + total.toLocaleString() + '</span> rivalries</div>' +
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
      '<div class="ce-riv">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-crimson"></div>' +
            '<span class="ce-sec-icon">💢</span>' +
            '<span class="ce-sec-title ce-sec-title-crimson">BAD BLOOD</span>' +
            '<span class="ce-sec-sub ce-mono">' + (data.active_count || 0).toLocaleString() + ' active rivalries · ' + (data.total || 0).toLocaleString() + ' tracked</span>' +
          '</div>' +
        '</div>' +
        renderSummary(data) +
        renderFilters() +
        renderList(data) +
        renderPagination(data) +
      '</div>';

    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    var typeSel = document.getElementById('ce-riv-type');
    if (typeSel) typeSel.addEventListener('change', function () {
      state.filters.type = typeSel.value;
      state.page = 1;
      loadAndRender();
    });

    var heatSel = document.getElementById('ce-riv-heat');
    if (heatSel) heatSel.addEventListener('change', function () {
      state.filters.heat_band = heatSel.value;
      state.page = 1;
      loadAndRender();
    });

    var scopeSel = document.getElementById('ce-riv-scope');
    if (scopeSel) scopeSel.addEventListener('change', function () {
      state.filters.scope = scopeSel.value;
      state.page = 1;
      loadAndRender();
    });

    var searchInput = document.getElementById('ce-riv-search');
    if (searchInput) searchInput.addEventListener('input', function () {
      if (state._searchTimer) clearTimeout(state._searchTimer);
      state._searchTimer = setTimeout(function () {
        state.filters.search = searchInput.value;
        state.page = 1;
        loadAndRender();
      }, 200);
    });

    var clearBtn = document.getElementById('ce-riv-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () {
      state.filters = { type: 'all', heat_band: 'all', scope: 'all', search: '' };
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
    document.querySelectorAll('.ce-riv__fighter-name[data-fighter-id]').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        evt.stopPropagation();
        var fid = link.getAttribute('data-fighter-id');
        if (fid) window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
      });
    });

    // Card expand/collapse
    document.querySelectorAll('.ce-riv__card').forEach(function (card) {
      card.addEventListener('click', function (evt) {
        // Don't toggle when clicking on a link or button inside the card.
        if (evt.target.closest('.ce-riv__fighter-name')) return;
        if (evt.target.closest('button')) return;
        var rid = parseInt(card.getAttribute('data-rivalry-id'), 10);
        if (!rid) return;
        state._expandedRivalryId = (state._expandedRivalryId === rid) ? null : rid;
        loadAndRender();
      });
    });
  }

  // ============================================================
  // LOAD + RENDER
  // ============================================================
  function loadAndRender() {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Surveying the bad blood…</div></div>';
    }
    return window.CE.bridge.getRivalriesData(state.page, state.filters).then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load rivalries</div><div>' +
            escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      render(data);
    }).catch(function (err) {
      console.error('[rivalries] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load rivalries</div><div>' +
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
