/* ============================================================
   CAGE EMPIRE — Training Camps (Gyms) Screen
   ============================================================
   P1-WIRE-4-SCREENS — Screen 4 of 4.
   Per docs/P1_PLAN_WIRE_SCREENS.md §4 + docs/REVIEW_P1_SCREEN_BACKENDS.md
   §4 + CONVENTIONS §14 (Interpretation Layer).

   Renders the training-camps + gyms ecosystem into #screen-content
   via two bridge calls: window.CE.bridge.getTrainingCampsData(page,
   filters) for the Active Camps tab, and window.CE.bridge.getGymsData
   (page, filters) for the Gym Directory tab.

   What the player sees:
     - Section header: "TRAINING CAMPS" (gold accent — Investment
       pillar) + subtitle showing the active camp count.
     - Summary strip: total gyms, active camps, completed camps.
     - Two tabs: Active Camps (default) + Gym Directory.
     - Active Camps tab:
       * Filter bar: focus dropdown, status dropdown (Active /
         Completed / All), scope dropdown (All / My Roster),
         search input.
       * Camp cards: fighter name (clickable → Fighter Profile),
         gym name, focus chip (color-coded), 3 progress meters
         (fatigue / morale / injury_risk), days-remaining
         countdown, linked event name + date.
       * Completed camps: show camp_result_summary + attribute
         changes as chips.
     - Gym Directory tab:
       * Filter bar: culture-tone dropdown, sort dropdown
         (Reputation / Facility / Dev Focus / Fighter Count),
         search input.
       * Gym cards (grid): name, city + nation, reputation badge,
         quality phrase (large gold text), 5 stat bars (facility /
         medical / sparring / dev / weight-cut support), culture
         chip (color-coded), membership cost, fighter count +
         active camps count chips.
     - Pagination on both tabs.
     - Empty states with voice-appropriate phrasing.

   Voice compliance (CONVENTIONS §14):
     - Gym stats (0-100 ints) are OK to display — gym ratings, NOT
       fighter attributes. facility_quality additionally wrapped
       in a voice phrase ('world-class' / 'elite' / 'solid' /
       'adequate' / 'bare-bones') per the brief.
     - Camp stats (fatigue / morale / injury_risk — 0-100 ints)
       are OK to display — camp-state ratings, NOT fighter attrs.
     - attribute_changes JSON contains raw deltas (+2 punch_power)
       — these are deltas, not absolute values. Fighter Profile
       already displays similar trajectory chips via the existing
       _compute_attribute_trajectory helper. We display them as
       chips here (matches that precedent).
     - No raw fighter potential / attribute values displayed.
   ============================================================ */

window.CE = window.CE || {};

window.CE.gyms = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    activeTab: 'camps',  // 'camps' | 'gyms'
    camps: {
      page: 1,
      filters: { focus: 'all', status: 'active', scope: 'all', search: '' },
      data: null,
      _searchTimer: null,
    },
    gyms: {
      page: 1,
      filters: { culture_tone: 'all', sort: 'reputation_desc', search: '' },
      data: null,
      _searchTimer: null,
    },
  };

  var FOCUS_OPTIONS = [
    { value: 'all',          label: 'All Focuses' },
    { value: 'striking',     label: 'Striking' },
    { value: 'grappling',    label: 'Grappling' },
    { value: 'wrestling',    label: 'Wrestling' },
    { value: 'submission',   label: 'Submission' },
    { value: 'conditioning', label: 'Conditioning' },
    { value: 'clinch',       label: 'Clinch' },
    { value: 'general',      label: 'General' },
    { value: 'weight_cut',   label: 'Weight Cut' },
  ];

  var STATUS_OPTIONS = [
    { value: 'active',    label: 'Active' },
    { value: 'completed', label: 'Completed' },
    { value: 'all',       label: 'All' },
  ];

  var SCOPE_OPTIONS = [
    { value: 'all',       label: 'All Promotions' },
    { value: 'my_roster', label: 'My Roster' },
  ];

  var CULTURE_OPTIONS = [
    { value: 'all',         label: 'All Cultures' },
    { value: 'predator',    label: 'Predator' },
    { value: 'loose',       label: 'Loose' },
    { value: 'disciplined', label: 'Disciplined' },
    { value: 'balanced',    label: 'Balanced' },
  ];

  var SORT_OPTIONS = [
    { value: 'reputation_desc',    label: 'Reputation' },
    { value: 'facility_desc',      label: 'Facility Quality' },
    { value: 'dev_focus_desc',     label: 'Development Focus' },
    { value: 'fighter_count_desc', label: 'Fighter Count' },
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

  function formatDate(dateStr) {
    if (!dateStr) return '—';
    var parts = String(dateStr).split('-');
    if (parts.length !== 3) return dateStr;
    var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var m = parseInt(parts[1], 10);
    return (MONTHS[m - 1] || '?') + ' ' + parseInt(parts[2], 10);
  }

  function focusChipClass(focus) {
    switch (focus) {
      case 'striking':     return 'ce-chip ce-chip-crimson';
      case 'grappling':    return 'ce-chip ce-chip-default';
      case 'wrestling':    return 'ce-chip ce-chip-warning';
      case 'submission':   return 'ce-chip ce-chip-default';
      case 'conditioning': return 'ce-chip ce-chip-green';
      case 'clinch':       return 'ce-chip ce-chip-default';
      case 'weight_cut':   return 'ce-chip ce-chip-warning';
      default:             return 'ce-chip ce-chip-gold';
    }
  }

  function cultureChipClass(tone) {
    switch (tone) {
      case 'predator':    return 'ce-chip ce-chip-crimson';
      case 'loose':       return 'ce-chip ce-chip-warning';
      case 'disciplined': return 'ce-chip ce-chip-gold';
      default:            return 'ce-chip ce-chip-default';
    }
  }

  // ============================================================
  // RENDERERS — SUMMARY
  // ============================================================
  function renderSummary() {
    var gymsTotal = (state.gyms.data && state.gyms.data.total_gyms) || 0;
    var campsActive = (state.camps.data && state.camps.data.active_count) || 0;
    var campsCompleted = (state.camps.data && state.camps.data.completed_count) || 0;
    return '' +
      '<div class="ce-gym__summary">' +
        '<div class="ce-gym__stat ce-gym__stat--gold">' +
          '<span class="ce-gym__stat-label">GYMS</span>' +
          '<span class="ce-gym__stat-val">' + gymsTotal + '</span>' +
        '</div>' +
        '<div class="ce-gym__stat">' +
          '<span class="ce-gym__stat-label">ACTIVE CAMPS</span>' +
          '<span class="ce-gym__stat-val">' + campsActive + '</span>' +
        '</div>' +
        '<div class="ce-gym__stat">' +
          '<span class="ce-gym__stat-label">COMPLETED</span>' +
          '<span class="ce-gym__stat-val">' + campsCompleted + '</span>' +
        '</div>' +
      '</div>';
  }

  function renderTabs() {
    var campsActive = state.activeTab === 'camps' ? ' ce-gym__tab--active' : '';
    var gymsActive = state.activeTab === 'gyms' ? ' ce-gym__tab--active' : '';
    return '' +
      '<div class="ce-gym__tabs">' +
        '<button class="ce-gym__tab' + campsActive + '" data-tab="camps" type="button">Active Camps</button>' +
        '<button class="ce-gym__tab' + gymsActive + '" data-tab="gyms" type="button">Gym Directory</button>' +
      '</div>';
  }

  // ============================================================
  // RENDERERS — CAMPS TAB
  // ============================================================
  function renderCampsFilters() {
    var f = state.camps.filters;
    var focusOpts = FOCUS_OPTIONS.map(function (o) {
      var sel = f.focus === o.value ? ' selected' : '';
      return '<option value="' + o.value + '"' + sel + '>' + escapeHtml(o.label) + '</option>';
    }).join('');
    var statusOpts = STATUS_OPTIONS.map(function (o) {
      var sel = f.status === o.value ? ' selected' : '';
      return '<option value="' + o.value + '"' + sel + '>' + escapeHtml(o.label) + '</option>';
    }).join('');
    var scopeOpts = SCOPE_OPTIONS.map(function (o) {
      var sel = f.scope === o.value ? ' selected' : '';
      return '<option value="' + o.value + '"' + sel + '>' + escapeHtml(o.label) + '</option>';
    }).join('');
    return '' +
      '<div class="ce-gym__filters">' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">FOCUS</label>' +
          '<select id="ce-gym-camp-focus" class="ce-filter-select">' + focusOpts + '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">STATUS</label>' +
          '<select id="ce-gym-camp-status" class="ce-filter-select">' + statusOpts + '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">SCOPE</label>' +
          '<select id="ce-gym-camp-scope" class="ce-filter-select">' + scopeOpts + '</select>' +
        '</div>' +
        '<div class="ce-filter-group ce-filter-search">' +
          '<label class="ce-filter-label">SEARCH</label>' +
          '<input type="text" id="ce-gym-camp-search" class="ce-filter-input" placeholder="Fighter name…" value="' + escapeHtml(f.search || '') + '" />' +
        '</div>' +
        '<button id="ce-gym-camp-clear" class="ce-btn ce-btn-ghost ce-filter-clear" type="button">Clear</button>' +
      '</div>';
  }

  function renderMeter(label, value, kind) {
    var v = Math.max(0, Math.min(100, Number(value || 0)));
    var cls = 'ce-gym__meter-bar--' + kind;
    if (kind === 'risk' && v >= 60) cls = 'ce-gym__meter-bar--danger';
    else if (kind === 'risk' && v >= 30) cls = 'ce-gym__meter-bar--warning';
    else if (kind === 'fatigue' && v >= 60) cls = 'ce-gym__meter-bar--warning';
    return '' +
      '<div class="ce-gym__meter">' +
        '<div class="ce-gym__meter-label">' + escapeHtml(label) + '</div>' +
        '<div class="ce-gym__meter-track">' +
          '<div class="ce-gym__meter-bar ' + cls + '" style="width:' + v + '%"></div>' +
        '</div>' +
        '<div class="ce-gym__meter-val ce-mono">' + v + '</div>' +
      '</div>';
  }

  function renderCampCard(camp) {
    var f = camp.fighter || {};
    var g = camp.gym || {};
    var ev = camp.event || null;
    var nickHtml = f.nickname ? ' <span class="ce-gym__camp-nick">\'' + escapeHtml(f.nickname) + '\'</span>' : '';
    var daysLabel;
    if (camp.days_remaining == null) {
      daysLabel = '';
    } else if (camp.days_remaining > 0) {
      daysLabel = 'Ends in ' + camp.days_remaining + 'd';
    } else if (camp.days_remaining === 0) {
      daysLabel = 'Ends today';
    } else {
      daysLabel = 'Ended ' + Math.abs(camp.days_remaining) + 'd ago';
    }

    var eventHtml = ev
      ? '<div class="ce-gym__camp-event ce-mono">For ' + escapeHtml(ev.name) + ' · ' + escapeHtml(formatDate(ev.date)) + '</div>'
      : '';

    var metersHtml = '' +
      '<div class="ce-gym__meters">' +
        renderMeter('FATIGUE', camp.camp_fatigue, 'fatigue') +
        renderMeter('MORALE', camp.camp_morale, 'morale') +
        renderMeter('INJURY RISK', camp.camp_injury_risk, 'risk') +
      '</div>';

    var attrHtml = '';
    if (camp.attribute_changes && Object.keys(camp.attribute_changes).length) {
      var chips = Object.keys(camp.attribute_changes).map(function (attr) {
        var gain = camp.attribute_changes[attr];
        var sign = gain > 0 ? '+' : '';
        var prettyAttr = attr.replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
        return '<span class="ce-chip ce-chip-green ce-gym__attr-chip">' +
          sign + gain + ' ' + escapeHtml(prettyAttr) + '</span>';
      }).join('');
      attrHtml = '<div class="ce-gym__camp-attr">' +
        '<span class="ce-gym__camp-attr-label">GAINS</span> ' + chips + '</div>';
    }

    var summaryHtml = camp.camp_result_summary
      ? '<div class="ce-gym__camp-summary">' + escapeHtml(camp.camp_result_summary) + '</div>'
      : '';

    return '' +
      '<article class="ce-gym__camp-card">' +
        '<div class="ce-gym__camp-header">' +
          '<div class="ce-gym__camp-portrait">' + escapeHtml(fighterInitial(f.name)) + '</div>' +
          '<div class="ce-gym__camp-info">' +
            '<a class="ce-gym__camp-name ce-link" href="#" data-fighter-id="' + f.id + '">' +
              escapeHtml(f.name || '—') + '</a>' + nickHtml +
            '<div class="ce-gym__camp-meta ce-mono">' +
              'at ' + escapeHtml(g.name || '—') +
              ' · ' + escapeHtml(formatDate(camp.start_date)) + ' → ' + escapeHtml(formatDate(camp.end_date)) +
              (daysLabel ? ' · ' + escapeHtml(daysLabel) : '') +
            '</div>' +
            eventHtml +
          '</div>' +
          '<span class="' + focusChipClass(camp.camp_focus) + ' ce-gym__focus-chip">' +
            escapeHtml(camp.camp_focus_label) +
          '</span>' +
        '</div>' +
        metersHtml +
        attrHtml +
        summaryHtml +
      '</article>';
  }

  function renderCampsList(data) {
    var camps = data.camps || [];
    if (!camps.length) {
      var isMyRoster = state.camps.filters.scope === 'my_roster';
      var title = isMyRoster
        ? 'Your fighters aren\'t in camp right now.'
        : 'No camps match your filters.';
      var body = isMyRoster
        ? 'Camps start automatically when you schedule a fight — your fighter spends the 14 days before the event at their gym, building fatigue and sharpening skills.'
        : 'Try widening your filters, or clear them to see the full camp ledger.';
      return '<div class="ce-gym__empty">' +
        '<div class="ce-gym__empty-icon">🏋</div>' +
        '<div class="ce-gym__empty-title">' + escapeHtml(title) + '</div>' +
        '<div class="ce-gym__empty-body">' + escapeHtml(body) + '</div>' +
      '</div>';
    }
    return '<div class="ce-gym__camp-list">' +
      camps.map(renderCampCard).join('') +
    '</div>';
  }

  function renderCampsPagination(data) {
    return renderPagination(data, 'camp');
  }

  // ============================================================
  // RENDERERS — GYMS TAB
  // ============================================================
  function renderGymsFilters() {
    var f = state.gyms.filters;
    var cultureOpts = CULTURE_OPTIONS.map(function (o) {
      var sel = f.culture_tone === o.value ? ' selected' : '';
      return '<option value="' + o.value + '"' + sel + '>' + escapeHtml(o.label) + '</option>';
    }).join('');
    var sortOpts = SORT_OPTIONS.map(function (o) {
      var sel = f.sort === o.value ? ' selected' : '';
      return '<option value="' + o.value + '"' + sel + '>' + escapeHtml(o.label) + '</option>';
    }).join('');
    return '' +
      '<div class="ce-gym__filters">' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">CULTURE</label>' +
          '<select id="ce-gym-gym-culture" class="ce-filter-select">' + cultureOpts + '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">SORT</label>' +
          '<select id="ce-gym-gym-sort" class="ce-filter-select">' + sortOpts + '</select>' +
        '</div>' +
        '<div class="ce-filter-group ce-filter-search">' +
          '<label class="ce-filter-label">SEARCH</label>' +
          '<input type="text" id="ce-gym-gym-search" class="ce-filter-input" placeholder="Gym name…" value="' + escapeHtml(f.search || '') + '" />' +
        '</div>' +
        '<button id="ce-gym-gym-clear" class="ce-btn ce-btn-ghost ce-filter-clear" type="button">Clear</button>' +
      '</div>';
  }

  function renderStatBar(label, value) {
    var v = Math.max(0, Math.min(100, Number(value || 0)));
    var cls = 'ce-gym__gym-stat-bar--';
    if (v >= 75) cls += 'gold';
    else if (v >= 50) cls += 'mid';
    else cls += 'low';
    return '' +
      '<div class="ce-gym__gym-stat">' +
        '<div class="ce-gym__gym-stat-row">' +
          '<span class="ce-gym__gym-stat-label">' + escapeHtml(label) + '</span>' +
          '<span class="ce-gym__gym-stat-val ce-mono">' + v + '</span>' +
        '</div>' +
        '<div class="ce-gym__gym-stat-track">' +
          '<div class="ce-gym__gym-stat-bar ' + cls + '" style="width:' + v + '%"></div>' +
        '</div>' +
      '</div>';
  }

  function renderGymCard(gym) {
    var locParts = [];
    if (gym.city) locParts.push(gym.city);
    if (gym.nation) locParts.push(gym.nation);
    var locHtml = locParts.length
      ? '<div class="ce-gym__gym-loc ce-mono">' + escapeHtml(locParts.join(', ')) + '</div>'
      : '';
    var cultureChip = '<span class="' + cultureChipClass(gym.culture_tone) + ' ce-gym__culture-chip">' +
      escapeHtml(gym.culture_tone_label) + '</span>';
    return '' +
      '<article class="ce-gym__gym-card">' +
        '<div class="ce-gym__gym-header">' +
          '<div class="ce-gym__gym-info">' +
            '<div class="ce-gym__gym-name">' + escapeHtml(gym.name) + '</div>' +
            locHtml +
          '</div>' +
          '<div class="ce-gym__gym-rep">' +
            '<span class="ce-gym__gym-rep-val ce-mono">' + gym.reputation + '</span>' +
            '<span class="ce-gym__gym-rep-label">REP</span>' +
          '</div>' +
        '</div>' +
        '<div class="ce-gym__gym-quality">' +
          '<span class="ce-gym__gym-quality-label">QUALITY</span>' +
          '<span class="ce-gym__gym-quality-phrase">' + escapeHtml(gym.quality_phrase) + '</span>' +
        '</div>' +
        '<div class="ce-gym__gym-stats">' +
          renderStatBar('Facility', gym.facility_quality) +
          renderStatBar('Medical', gym.medical_support) +
          renderStatBar('Sparring', gym.sparring_depth) +
          renderStatBar('Dev Focus', gym.development_focus) +
          renderStatBar('Weight Cut', gym.weight_cut_support) +
        '</div>' +
        '<div class="ce-gym__gym-footer">' +
          cultureChip +
          '<span class="ce-gym__gym-cost ce-mono">' + escapeHtml(gym.membership_cost_display) + '</span>' +
          '<span class="ce-chip ce-chip-default ce-gym__gym-count-chip">' +
            gym.fighter_count + (gym.fighter_count === 1 ? ' fighter' : ' fighters') +
          '</span>' +
          (gym.active_camps_count > 0
            ? '<span class="ce-chip ce-chip-gold ce-gym__gym-count-chip">' +
                gym.active_camps_count + (gym.active_camps_count === 1 ? ' camp' : ' camps') + '</span>'
            : '') +
        '</div>' +
      '</article>';
  }

  function renderGymsGrid(data) {
    var gyms = data.gyms || [];
    if (!gyms.length) {
      return '<div class="ce-gym__empty">' +
        '<div class="ce-gym__empty-icon">🏋</div>' +
        '<div class="ce-gym__empty-title">No gyms match your filters.</div>' +
        '<div class="ce-gym__empty-body">Try widening your search, or clear the filters to see the full gym ecosystem.</div>' +
      '</div>';
    }
    return '<div class="ce-gym__grid">' +
      gyms.map(renderGymCard).join('') +
    '</div>';
  }

  function renderGymsPagination(data) {
    return renderPagination(data, 'gym');
  }

  // ============================================================
  // RENDERERS — PAGINATION (shared)
  // ============================================================
  function renderPagination(data, kind) {
    var total = data.total || 0;
    var page = data.page || 1;
    var totalPages = data.total_pages || 1;
    if (total <= data.per_page) return '';
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
      return '<button class="' + cls + '" data-page="' + p + '" data-kind="' + kind + '" type="button">' + p + '</button>';
    }).join('');

    var noun = (kind === 'camp') ? 'camps' : 'gyms';
    return '' +
      '<div class="ce-roster-pagination">' +
        '<div class="ce-page-info">Showing <span class="ce-mono">' + start + '–' + end + '</span> of <span class="ce-mono">' + total.toLocaleString() + '</span> ' + noun + '</div>' +
        '<div class="ce-page-controls">' +
          '<button class="ce-page-btn" data-page="' + (page - 1) + '" data-kind="' + kind + '" type="button"' + (page <= 1 ? ' disabled' : '') + '>◀ Prev</button>' +
          pageHtml +
          '<span class="ce-page-indicator ce-mono">Page ' + page + ' of ' + totalPages + '</span>' +
          '<button class="ce-page-btn" data-page="' + (page + 1) + '" data-kind="' + kind + '" type="button"' + (page >= totalPages ? ' disabled' : '') + '>Next ▶</button>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // MAIN RENDER
  // ============================================================
  function render() {
    var host = document.getElementById('screen-content');
    if (!host) return;

    var tabBody = '';
    if (state.activeTab === 'camps') {
      var cd = state.camps.data;
      tabBody = cd
        ? renderCampsFilters() + renderCampsList(cd) + renderCampsPagination(cd)
        : '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Loading camps…</div></div>';
    } else {
      var gd = state.gyms.data;
      tabBody = gd
        ? renderGymsFilters() + renderGymsGrid(gd) + renderGymsPagination(gd)
        : '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Loading gyms…</div></div>';
    }

    var html = '' +
      '<div class="ce-gym">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">🏋</span>' +
            '<span class="ce-sec-title ce-sec-title-gold">TRAINING CAMPS</span>' +
            '<span class="ce-sec-sub ce-mono">' +
              ((state.camps.data && state.camps.data.active_count) || 0) + ' active camps · ' +
              ((state.gyms.data && state.gyms.data.total_gyms) || 0) + ' gyms' +
            '</span>' +
          '</div>' +
        '</div>' +
        renderSummary() +
        renderTabs() +
        tabBody +
      '</div>';

    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    // Tab switcher
    document.querySelectorAll('.ce-gym__tab').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var newTab = btn.getAttribute('data-tab') || 'camps';
        if (state.activeTab === newTab) return;
        state.activeTab = newTab;
        render();
        // Load if not yet loaded.
        if (newTab === 'camps' && !state.camps.data) loadCamps();
        if (newTab === 'gyms' && !state.gyms.data) loadGyms();
      });
    });

    // Camps filters
    var campFocus = document.getElementById('ce-gym-camp-focus');
    if (campFocus) campFocus.addEventListener('change', function () {
      state.camps.filters.focus = campFocus.value;
      state.camps.page = 1;
      loadCamps();
    });
    var campStatus = document.getElementById('ce-gym-camp-status');
    if (campStatus) campStatus.addEventListener('change', function () {
      state.camps.filters.status = campStatus.value;
      state.camps.page = 1;
      loadCamps();
    });
    var campScope = document.getElementById('ce-gym-camp-scope');
    if (campScope) campScope.addEventListener('change', function () {
      state.camps.filters.scope = campScope.value;
      state.camps.page = 1;
      loadCamps();
    });
    var campSearch = document.getElementById('ce-gym-camp-search');
    if (campSearch) campSearch.addEventListener('input', function () {
      if (state.camps._searchTimer) clearTimeout(state.camps._searchTimer);
      state.camps._searchTimer = setTimeout(function () {
        state.camps.filters.search = campSearch.value;
        state.camps.page = 1;
        loadCamps();
      }, 200);
    });
    var campClear = document.getElementById('ce-gym-camp-clear');
    if (campClear) campClear.addEventListener('click', function () {
      state.camps.filters = { focus: 'all', status: 'active', scope: 'all', search: '' };
      state.camps.page = 1;
      loadCamps();
    });

    // Gyms filters
    var gymCulture = document.getElementById('ce-gym-gym-culture');
    if (gymCulture) gymCulture.addEventListener('change', function () {
      state.gyms.filters.culture_tone = gymCulture.value;
      state.gyms.page = 1;
      loadGyms();
    });
    var gymSort = document.getElementById('ce-gym-gym-sort');
    if (gymSort) gymSort.addEventListener('change', function () {
      state.gyms.filters.sort = gymSort.value;
      state.gyms.page = 1;
      loadGyms();
    });
    var gymSearch = document.getElementById('ce-gym-gym-search');
    if (gymSearch) gymSearch.addEventListener('input', function () {
      if (state.gyms._searchTimer) clearTimeout(state.gyms._searchTimer);
      state.gyms._searchTimer = setTimeout(function () {
        state.gyms.filters.search = gymSearch.value;
        state.gyms.page = 1;
        loadGyms();
      }, 200);
    });
    var gymClear = document.getElementById('ce-gym-gym-clear');
    if (gymClear) gymClear.addEventListener('click', function () {
      state.gyms.filters = { culture_tone: 'all', sort: 'reputation_desc', search: '' };
      state.gyms.page = 1;
      loadGyms();
    });

    // Pagination
    document.querySelectorAll('.ce-page-btn[data-kind]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.disabled) return;
        var p = parseInt(btn.getAttribute('data-page'), 10);
        var kind = btn.getAttribute('data-kind');
        if (!p || p < 1) return;
        if (kind === 'camp') {
          state.camps.page = p;
          loadCamps();
        } else {
          state.gyms.page = p;
          loadGyms();
        }
      });
    });

    // Fighter-name hyperlinks → Fighter Profile
    document.querySelectorAll('.ce-gym__camp-name[data-fighter-id]').forEach(function (link) {
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
  function loadCamps() {
    return window.CE.bridge.getTrainingCampsData(
      state.camps.page, state.camps.filters
    ).then(function (data) {
      if (!data || data.error) {
        state.camps.data = null;
        render();
        return;
      }
      state.camps.data = data;
      render();
    }).catch(function (err) {
      console.error('[gyms] camps load failed:', err);
      state.camps.data = null;
      render();
    });
  }

  function loadGyms() {
    return window.CE.bridge.getGymsData(
      state.gyms.page, state.gyms.filters
    ).then(function (data) {
      if (!data || data.error) {
        state.gyms.data = null;
        render();
        return;
      }
      state.gyms.data = data;
      render();
    }).catch(function (err) {
      console.error('[gyms] gyms load failed:', err);
      state.gyms.data = null;
      render();
    });
  }

  function loadAndRender() {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Loading training camps…</div></div>';
    }
    // Fetch both tabs in parallel so the summary strip populates
    // immediately + the active tab is ready to render.
    return Promise.all([loadCamps(), loadGyms()]);
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
