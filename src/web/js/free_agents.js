/* ============================================================
   CAGE EMPIRE — Free Agents Screen Renderer ("Open Market")
   ============================================================
   Renders the free-agent pool into #screen-content using live data
   fetched via window.CE.bridge.getFreeAgents(page, filters).

   Per GUI_PLAN §6.4 + SCREEN_DATA_AUDIT §3:
     - 8-column table (sharp corners — "ledger" feel):
       Name (hyperlink) | Age | WC | Stage (SHORT italic) | Ceiling
       (voice phrase or "????") | Form (SHORT italic) | Record (mono)
       | Gym.
     - Sticky sign bar at the bottom: shows selected fighter +
       estimated cost + Sign button.
     - Ceiling display: voice phrase ("Elite", "High", etc.) if
       scouted, else "????" (4 question marks, mono).
     - Filters: WC, Ceiling, Search (200ms debounce).
     - Pagination: 20 rows/page.
     - NEVER displays raw potential integer.

   Sign flow:
     1. Click row → row selected, sign bar updates with fighter
        details + estimated cost (bridge.estimateSigningCost).
     2. Click "Sign for $X" → ModalDialog confirmation.
     3. On confirm: bridge.signFreeAgent(fighterId) → refresh list.
   ============================================================ */

window.CE = window.CE || {};

window.CE.freeAgents = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    page: 1,
    // CR-4 (docs/CR1_4_PLAN.md §4.3): added gender, age_range,
    // nationality filters. Sort defaults to ceiling DESC (unscouted
    // always last, enforced server-side).
    filters: {
      wc: '0', ceiling: 'all', search: '',
      gender: 'all', age_range: 'all', nationality: 'all',
      sort_col: 'ceiling', sort_dir: 'desc',
    },
    selectedFighter: null,
    estimatedCost: null,
    // Phase E3.3 — negotiation panel state (salary, signing_bonus,
    // contract_length, win_bonus_pct). Reset to null when a new
    // fighter is selected; renderModal() initializes it from the
    // estimate_signing_cost value when the modal first opens.
    negotiation: null,
    // Phase M3.2 — when true, the confirm button uses counterOffer
    // instead of signFreeAgent. Set when the player navigated here
    // from the Dashboard's "Counter Offer" button (a bidding alert
    // is active for the selected fighter).
    biddingAlert: false,
    weightClasses: [],
    nationalities: [],
    _searchTimer: null,
  };

  // ============================================================
  // HELPERS
  // ============================================================
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function formatCash(n) {
    n = Number(n) || 0;
    if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return '$' + Math.round(n / 1e3) + 'K';
    return '$' + Math.round(n).toLocaleString();
  }

  // CR-4 (docs/CR1_4_PLAN.md §4.3): name/age/wc/ceiling/record are
  // now sortable. Stage, Form, Gym stay non-sortable (no meaningful
  // order on voice phrases, and gym is too sparse).
  var COLUMNS = [
    { key: 'name',    label: 'Name',    sortable: true, min: '160px' },
    { key: 'age',     label: 'Age',     sortable: true, mono: true, width: '60px' },
    { key: 'wc',      label: 'WC',      sortable: true, mono: true, width: '140px' },
    { key: 'stage',   label: 'Stage',   sortable: false, italic: true },
    { key: 'ceiling', label: 'Ceiling', sortable: true, width: '120px' },
    { key: 'form',    label: 'Form',    sortable: false, italic: true },
    { key: 'record',  label: 'Record',  sortable: true, mono: true, width: '90px' },
    { key: 'gym',     label: 'Gym',     sortable: false },
  ];

  var CEILING_OPTIONS = [
    { value: 'all', label: 'All Ceilings' },
    { value: 'elite', label: 'Elite' },
    { value: 'high', label: 'High' },
    { value: 'above_avg', label: 'Above-Average' },
    { value: 'avg', label: 'Average' },
    { value: 'below_avg', label: 'Below-Average' },
    { value: 'low', label: 'Low' },
  ];

  // ============================================================
  // RENDERERS
  // ============================================================
  function renderFilters() {
    // CR-3a (docs/CR1_4_PLAN.md §3.2): weight classes grouped by
    // gender using <optgroup label="Men's">…</optgroup>. Mirrors the
    // roster.js pattern. weightClasses now comes directly from the
    // backend payload (with gender + count fields).
    var wcOptions = '<option value="0">All Weight Classes</option>';
    var mensClasses = state.weightClasses.filter(function (w) { return w.gender === 'male'; });
    var womensClasses = state.weightClasses.filter(function (w) { return w.gender === 'female'; });
    var otherClasses = state.weightClasses.filter(function (w) { return w.gender !== 'male' && w.gender !== 'female'; });
    function optgroup(label, classes) {
      if (!classes.length) return '';
      return '<optgroup label="' + escapeHtml(label) + '">' +
        classes.map(function (w) {
          return '<option value="' + w.id + '"' + (String(state.filters.wc) === String(w.id) ? ' selected' : '') + '>' +
            escapeHtml(w.name.toUpperCase()) + ' (' + w.count + ')</option>';
        }).join('') +
        '</optgroup>';
    }
    wcOptions += optgroup("Men's", mensClasses);
    wcOptions += optgroup("Women's", womensClasses);
    wcOptions += optgroup('Other', otherClasses);

    var ceilingOptions = CEILING_OPTIONS.map(function (c) {
      return '<option value="' + c.value + '"' + (state.filters.ceiling === c.value ? ' selected' : '') + '>' +
        escapeHtml(c.label) + '</option>';
    }).join('');

    // CR-4: gender filter (All / Men / Women)
    var genderOptions = ['all', 'male', 'female'].map(function (g) {
      var lbl = g === 'male' ? 'Men' : g === 'female' ? 'Women' : 'All';
      return '<option value="' + g + '"' + (state.filters.gender === g ? ' selected' : '') + '>' + lbl + '</option>';
    }).join('');

    // CR-4: age_range filter (All / Prospects / Prime / Veterans)
    var ageOptions = [
      { value: 'all', label: 'All Ages' },
      { value: 'prospect', label: 'Prospects (≤25)' },
      { value: 'prime', label: 'Prime (26-32)' },
      { value: 'veteran', label: 'Veterans (33+)' },
    ].map(function (a) {
      return '<option value="' + a.value + '"' + (state.filters.age_range === a.value ? ' selected' : '') + '>' +
        escapeHtml(a.label) + '</option>';
    }).join('');

    // CR-4: nationality filter (populated from backend payload — top 20)
    var natOptions = '<option value="all">All Nationalities</option>' +
      state.nationalities.map(function (n) {
        return '<option value="' + n.id + '"' + (String(state.filters.nationality) === String(n.id) ? ' selected' : '') + '>' +
          escapeHtml(n.name) + ' (' + n.count + ')</option>';
      }).join('');

    return '' +
      '<div class="ce-fa-filters">' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">WEIGHT CLASS</label>' +
          '<select id="ce-fa-wc" class="ce-filter-select">' + wcOptions + '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">GENDER</label>' +
          '<select id="ce-fa-gender" class="ce-filter-select">' + genderOptions + '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">AGE</label>' +
          '<select id="ce-fa-age" class="ce-filter-select">' + ageOptions + '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">NATIONALITY</label>' +
          '<select id="ce-fa-nat" class="ce-filter-select">' + natOptions + '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">CEILING</label>' +
          '<select id="ce-fa-ceiling" class="ce-filter-select">' + ceilingOptions + '</select>' +
        '</div>' +
        '<div class="ce-filter-group ce-filter-search">' +
          '<label class="ce-filter-label">SEARCH</label>' +
          '<input type="text" id="ce-fa-search" class="ce-filter-input" placeholder="Name…" value="' + escapeHtml(state.filters.search || '') + '" />' +
        '</div>' +
        '<button id="ce-fa-clear" class="ce-btn ce-btn-ghost ce-filter-clear" type="button">Clear</button>' +
      '</div>';
  }

  function renderTable(data) {
    var fighters = data.fighters || [];
    if (!fighters.length) {
      return '<div class="ce-empty-state">The market is quiet. Your next star hasn\'t surfaced yet.</div>';
    }

    // CR-4: sortable column headers — mirror roster.js pattern.
    // data-sort-col attribute is read by the click handler in
    // wireEvents() to toggle sort_col + sort_dir + refetch.
    var headerHtml = COLUMNS.map(function (col) {
      var w = col.width ? ' style="width:' + col.width + '"' : '';
      if (!col.sortable) {
        return '<th class="ce-roster-th"' + w + '>' + escapeHtml(col.label) + '</th>';
      }
      var isSorted = state.filters.sort_col === col.key;
      var sortIcon = isSorted ? (state.filters.sort_dir === 'asc' ? ' ▲' : ' ▼') : '';
      var sortClass = isSorted ? ' ce-roster-th--sorted' : '';
      return '<th class="ce-roster-th ce-roster-th--sortable' + sortClass + '" data-sort-col="' + col.key + '"' + w + '>' +
        escapeHtml(col.label) + '<span class="ce-sort-icon">' + sortIcon + '</span></th>';
    }).join('');

    var bodyHtml = fighters.map(function (f) {
      var isSelected = state.selectedFighter && state.selectedFighter.fighter_id === f.fighter_id;
      var selectedClass = isSelected ? ' ce-roster-tr--selected' : '';
      var nickHtml = f.nickname ? ' <span class="ce-roster-nick">\'' + escapeHtml(f.nickname) + '\'</span>' : '';
      var ceilingClass = f.ceiling_scouted ? 'ce-fa-ceiling--scouted' : 'ce-fa-ceiling--unknown';
      var ceilingDisplay = f.ceiling_scouted ? escapeHtml(f.ceiling_display) : '????';

      return '' +
        '<tr class="ce-roster-tr' + selectedClass + '" data-fighter-id="' + f.fighter_id + '">' +
          '<td class="ce-roster-td ce-roster-td--name">' +
            '<a class="ce-link ce-fa-name" href="#" data-fighter-id="' + f.fighter_id + '">' +
              escapeHtml(f.name) + '</a>' + nickHtml +
          '</td>' +
          '<td class="ce-roster-td ce-mono">' + f.age + '</td>' +
          '<td class="ce-roster-td ce-mono ce-roster-wc">' + escapeHtml(f.wc_name) + '</td>' +
          '<td class="ce-roster-td ce-roster-stage">' + escapeHtml(f.stage_short || '—') + '</td>' +
          '<td class="ce-roster-td ce-mono ' + ceilingClass + '">' + ceilingDisplay + '</td>' +
          '<td class="ce-roster-td ce-roster-form">' + escapeHtml(f.form_short || '—') + '</td>' +
          '<td class="ce-roster-td ce-mono ce-roster-record">' + escapeHtml(f.record_str) + '</td>' +
          '<td class="ce-roster-td ce-roster-gym">' + escapeHtml(f.gym_name) + '</td>' +
        '</tr>';
    }).join('');

    return '' +
      '<div class="ce-roster-table-wrap">' +
        '<table class="ce-roster-table">' +
          '<thead><tr>' + headerHtml + '</tr></thead>' +
          '<tbody>' + bodyHtml + '</tbody>' +
        '</table>' +
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
        '<div class="ce-page-info">Showing <span class="ce-mono">' + start + '–' + end + '</span> of <span class="ce-mono">' + total.toLocaleString() + '</span> free agents</div>' +
        '<div class="ce-page-controls">' +
          '<button class="ce-page-btn" data-page="' + (page - 1) + '" type="button"' + (page <= 1 ? ' disabled' : '') + '>◀ Prev</button>' +
          pageHtml +
          // CR-4: "Page X of Y" indicator next to the Next button.
          '<span class="ce-page-indicator ce-mono">Page ' + page + ' of ' + totalPages + '</span>' +
          '<button class="ce-page-btn" data-page="' + (page + 1) + '" type="button"' + (page >= totalPages ? ' disabled' : '') + '>Next ▶</button>' +
        '</div>' +
      '</div>';
  }

  function renderSignBar() {
    if (!state.selectedFighter) {
      return '' +
        '<div class="ce-fa-signbar ce-fa-signbar--empty">' +
          '<div class="ce-fa-signbar-text">Pick someone to see what he\'ll cost you.</div>' +
        '</div>';
    }
    var f = state.selectedFighter;
    var cost = state.estimatedCost;
    var costDisplay = cost ? cost.cost_display : '…';
    var signBtn = cost
      ? '<button class="ce-btn ce-btn-primary" id="ce-fa-sign-btn" type="button">Sign for ' + escapeHtml(costDisplay) + '</button>'
      : '<button class="ce-btn ce-btn-primary" id="ce-fa-sign-btn" type="button" disabled>Estimating…</button>';

    return '' +
      '<div class="ce-fa-signbar">' +
        '<div class="ce-fa-signbar-info">' +
          '<div class="ce-fa-signbar-name">' + escapeHtml(f.name) +
            (f.nickname ? ' <span class="ce-roster-nick">\'' + escapeHtml(f.nickname) + '\'</span>' : '') +
          '</div>' +
          '<div class="ce-fa-signbar-meta ce-mono">' +
            escapeHtml(f.wc_name) + ' · ' + f.age + 'y · ' + escapeHtml(f.record_str) +
            ' · Ceiling: ' + (f.ceiling_scouted ? escapeHtml(f.ceiling_display) : '????') +
          '</div>' +
        '</div>' +
        '<div class="ce-fa-signbar-cost">' +
          '<div class="ce-fa-signbar-cost-label">WHAT HE\'LL COST YOU</div>' +
          '<div class="ce-fa-signbar-cost-val ce-mono">' + escapeHtml(costDisplay) + '</div>' +
        '</div>' +
        signBtn +
      '</div>';
  }

  function renderModal() {
    if (!state.selectedFighter || !state.estimatedCost) return '';
    var f = state.selectedFighter;
    var cost = state.estimatedCost;
    // Phase E3.3 — negotiation panel defaults. salary defaults to
    // estimate_signing_cost so the modal opens with the "fair" offer
    // pre-loaded. Player can drag sliders lower to negotiate down
    // (risk: fighter refuses) or higher (overpay to lock him in).
    var estimateValue = cost.cost_value || 50000;
    if (!state.negotiation) {
      state.negotiation = {
        salary: estimateValue,
        signingBonus: 0,
        contractLength: 2,
        winBonusPct: 0.5,
      };
    }
    return '' +
      '<div class="ce-modal-overlay" id="ce-fa-modal" style="display:none">' +
        '<div class="ce-modal-dialog ce-fa-modal-dialog--wide">' +
          '<div class="ce-modal-header">' +
            '<div class="ce-modal-title">BRING HIM INTO YOUR STABLE</div>' +
            '<button class="ce-modal-close" id="ce-fa-modal-close" type="button">×</button>' +
          '</div>' +
          '<div class="ce-modal-body">' +
            '<p class="ce-modal-line">Negotiate terms with <strong>' + escapeHtml(f.name) + '</strong>.</p>' +
            '<div class="ce-fa-negotiation">' +
              // Salary
              '<div class="ce-fa-lever">' +
                '<div class="ce-fa-lever__header">' +
                  '<span class="ce-fa-lever__label">Salary (per year)</span>' +
                  '<span class="ce-fa-lever__value" id="ce-fa-salary-val">' + escapeHtml(formatCash(state.negotiation.salary)) + '</span>' +
                '</div>' +
                '<input type="range" id="ce-fa-salary" min="10000" max="500000" step="5000" value="' + state.negotiation.salary + '" />' +
                '<div class="ce-fa-lever__hint">His expectation: <span class="ce-mono">' + escapeHtml(cost.cost_display) + '</span>/yr</div>' +
              '</div>' +
              // Signing bonus
              '<div class="ce-fa-lever">' +
                '<div class="ce-fa-lever__header">' +
                  '<span class="ce-fa-lever__label">Signing Bonus (upfront)</span>' +
                  '<span class="ce-fa-lever__value" id="ce-fa-bonus-val">' + escapeHtml(formatCash(state.negotiation.signingBonus)) + '</span>' +
                '</div>' +
                '<input type="range" id="ce-fa-bonus" min="0" max="1000000" step="25000" value="' + state.negotiation.signingBonus + '" />' +
                '<div class="ce-fa-lever__hint">Deducted from your war chest immediately.</div>' +
              '</div>' +
              // Contract length
              '<div class="ce-fa-lever">' +
                '<div class="ce-fa-lever__header">' +
                  '<span class="ce-fa-lever__label">Contract Length</span>' +
                  '<span class="ce-fa-lever__value" id="ce-fa-len-val">' + state.negotiation.contractLength + ' yrs</span>' +
                '</div>' +
                '<input type="range" id="ce-fa-len" min="1" max="5" step="1" value="' + state.negotiation.contractLength + '" />' +
                '<div class="ce-fa-lever__hint">Longer = bigger total commitment, but locks him in.</div>' +
              '</div>' +
              // Win bonus %
              '<div class="ce-fa-lever">' +
                '<div class="ce-fa-lever__header">' +
                  '<span class="ce-fa-lever__label">Win Bonus</span>' +
                  '<span class="ce-fa-lever__value" id="ce-fa-win-val">' + Math.round(state.negotiation.winBonusPct * 100) + '%</span>' +
                '</div>' +
                '<input type="range" id="ce-fa-win" min="0" max="100" step="5" value="' + Math.round(state.negotiation.winBonusPct * 100) + '" />' +
                '<div class="ce-fa-lever__hint">% of base purse paid per win. 50% is the standard.</div>' +
              '</div>' +
            '</div>' +
            // Live acceptance indicator
            '<div class="ce-fa-acceptance" id="ce-fa-acceptance">' +
              renderAcceptance(state.negotiation, estimateValue) +
            '</div>' +
            // Summary
            '<div class="ce-modal-contract">' +
              '<div class="ce-modal-contract-row"><span>Weight class:</span><span>' + escapeHtml(f.wc_name) + '</span></div>' +
              '<div class="ce-modal-contract-row"><span>Stage:</span><span style="font-style:italic">' + escapeHtml(f.stage_short || '—') + '</span></div>' +
              '<div class="ce-modal-contract-row"><span>Total contract value:</span><span class="ce-mono" id="ce-fa-total-val">' + escapeHtml(formatCash(state.negotiation.salary * state.negotiation.contractLength + state.negotiation.signingBonus)) + '</span></div>' +
            '</div>' +
            (state.biddingAlert
              ? '<p class="ce-modal-foot" style="color:var(--crimson);font-weight:600">⚠ BIDDING WAR — your offer competes against the rival promo\'s. The fighter chooses the better deal.</p>'
              : '<p class="ce-modal-foot">Your signing will be announced as news. Signing bonus hits your war chest today.</p>'
            ) +
          '</div>' +
          '<div class="ce-modal-footer">' +
            '<button class="ce-btn ce-btn-ghost" id="ce-fa-modal-cancel" type="button">Cancel</button>' +
            '<button class="ce-btn ' + (state.biddingAlert ? 'ce-btn-danger' : 'ce-btn-primary') + '" id="ce-fa-modal-confirm" type="button">' + (state.biddingAlert ? 'Counter Offer' : 'Make Him Yours') + '</button>' +
          '</div>' +
        '</div>' +
      '</div>';
  }

  // Phase E3.3 — render the live acceptance indicator.
  // Fighter accepts if total_value ≥ estimate × 0.9 where
  // total_value = salary × contract_length + signing_bonus.
  function renderAcceptance(neg, estimateValue) {
    var totalValue = (neg.salary * neg.contractLength) + neg.signingBonus;
    var threshold = estimateValue * 0.9;
    var accepts = totalValue >= threshold;
    // Voice phrases per spec.
    if (accepts) {
      return '<div class="ce-fa-acceptance__indicator ce-fa-acceptance__indicator--accept">✓ He\'ll sign for this.</div>' +
        '<div class="ce-fa-acceptance__detail">Total value ' + escapeHtml(formatCash(totalValue)) + ' clears his expectation of ' + escapeHtml(formatCash(threshold)) + '.</div>';
    }
    return '<div class="ce-fa-acceptance__indicator ce-fa-acceptance__indicator--reject">✗ He\'s not interested at that number.</div>' +
      '<div class="ce-fa-acceptance__detail">Total value ' + escapeHtml(formatCash(totalValue)) + ' is below his ' + escapeHtml(formatCash(threshold)) + ' floor. Add salary, bonus, or years.</div>';
  }

  // Phase E3.3 — update the acceptance indicator + total value
  // (called on every slider input).
  function updateAcceptance(estimateValue) {
    var acc = document.getElementById('ce-fa-acceptance');
    if (acc) acc.innerHTML = renderAcceptance(state.negotiation, estimateValue);
    var totalEl = document.getElementById('ce-fa-total-val');
    if (totalEl) {
      var totalValue = state.negotiation.salary * state.negotiation.contractLength + state.negotiation.signingBonus;
      totalEl.textContent = formatCash(totalValue);
    }
    // Disable the confirm button if the offer is below threshold.
    var confirmBtn = document.getElementById('ce-fa-modal-confirm');
    if (confirmBtn) {
      var totalValue2 = state.negotiation.salary * state.negotiation.contractLength + state.negotiation.signingBonus;
      var threshold = estimateValue * 0.9;
      confirmBtn.disabled = totalValue2 < threshold;
    }
  }

  // Phase E3.3 — wire the negotiation sliders.
  function wireNegotiationSliders(estimateValue) {
    var salarySlider = document.getElementById('ce-fa-salary');
    if (salarySlider) {
      salarySlider.addEventListener('input', function () {
        state.negotiation.salary = parseInt(salarySlider.value, 10);
        var valEl = document.getElementById('ce-fa-salary-val');
        if (valEl) valEl.textContent = formatCash(state.negotiation.salary);
        updateAcceptance(estimateValue);
      });
    }
    var bonusSlider = document.getElementById('ce-fa-bonus');
    if (bonusSlider) {
      bonusSlider.addEventListener('input', function () {
        state.negotiation.signingBonus = parseInt(bonusSlider.value, 10);
        var valEl = document.getElementById('ce-fa-bonus-val');
        if (valEl) valEl.textContent = formatCash(state.negotiation.signingBonus);
        updateAcceptance(estimateValue);
      });
    }
    var lenSlider = document.getElementById('ce-fa-len');
    if (lenSlider) {
      lenSlider.addEventListener('input', function () {
        state.negotiation.contractLength = parseInt(lenSlider.value, 10);
        var valEl = document.getElementById('ce-fa-len-val');
        if (valEl) valEl.textContent = state.negotiation.contractLength + ' yrs';
        updateAcceptance(estimateValue);
      });
    }
    var winSlider = document.getElementById('ce-fa-win');
    if (winSlider) {
      winSlider.addEventListener('input', function () {
        var pct = parseInt(winSlider.value, 10);
        state.negotiation.winBonusPct = pct / 100;
        var valEl = document.getElementById('ce-fa-win-val');
        if (valEl) valEl.textContent = pct + '%';
        // Win bonus doesn't affect acceptance threshold (it's per-win,
        // not guaranteed), so no updateAcceptance call here.
      });
    }
    // Initial state: set the confirm button disabled if default offer
    // is below threshold (shouldn't happen since salary defaults to
    // estimate_signing_cost, but defensive).
    updateAcceptance(estimateValue);
  }

  function render(data) {
    var host = document.getElementById('screen-content');
    if (!host) return;

    var html = '' +
      '<div class="ce-fa">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-title ce-sec-title-gold">OPEN MARKET</span>' +
            '<span class="ce-sec-sub ce-mono">' + (data.total || 0).toLocaleString() + ' fighters waiting for your call</span>' +
          '</div>' +
          renderFilters() +
          renderTable(data) +
          renderPagination(data) +
        '</div>' +
      '</div>' +
      renderSignBar() +
      renderModal();

    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    // Filters
    var wcSel = document.getElementById('ce-fa-wc');
    if (wcSel) wcSel.addEventListener('change', function () {
      state.filters.wc = wcSel.value;
      state.page = 1;
      loadAndRender();
    });

    // CR-4: new filter dropdowns (gender, age_range, nationality).
    var genderSel = document.getElementById('ce-fa-gender');
    if (genderSel) genderSel.addEventListener('change', function () {
      state.filters.gender = genderSel.value;
      state.page = 1;
      loadAndRender();
    });

    var ageSel = document.getElementById('ce-fa-age');
    if (ageSel) ageSel.addEventListener('change', function () {
      state.filters.age_range = ageSel.value;
      state.page = 1;
      loadAndRender();
    });

    var natSel = document.getElementById('ce-fa-nat');
    if (natSel) natSel.addEventListener('change', function () {
      state.filters.nationality = natSel.value;
      state.page = 1;
      loadAndRender();
    });

    var ceilSel = document.getElementById('ce-fa-ceiling');
    if (ceilSel) ceilSel.addEventListener('change', function () {
      state.filters.ceiling = ceilSel.value;
      state.page = 1;
      loadAndRender();
    });

    var searchInput = document.getElementById('ce-fa-search');
    if (searchInput) searchInput.addEventListener('input', function () {
      if (state._searchTimer) clearTimeout(state._searchTimer);
      state._searchTimer = setTimeout(function () {
        state.filters.search = searchInput.value;
        state.page = 1;
        loadAndRender();
      }, 200);
    });

    var clearBtn = document.getElementById('ce-fa-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () {
      // CR-4: reset all filters (including the new ones).
      state.filters = {
        wc: '0', ceiling: 'all', search: '',
        gender: 'all', age_range: 'all', nationality: 'all',
        sort_col: 'ceiling', sort_dir: 'desc',
      };
      state.page = 1;
      loadAndRender();
    });

    // CR-4: sortable column headers — toggle sort_col + sort_dir.
    // Mirrors roster.js:313-324 pattern.
    document.querySelectorAll('.ce-roster-th--sortable').forEach(function (th) {
      th.addEventListener('click', function () {
        var col = th.getAttribute('data-sort-col');
        if (state.filters.sort_col === col) {
          state.filters.sort_dir = state.filters.sort_dir === 'asc' ? 'desc' : 'asc';
        } else {
          state.filters.sort_col = col;
          state.filters.sort_dir = 'asc';
        }
        loadAndRender();
      });
    });

    // Row interactions: single click = select + fetch cost
    document.querySelectorAll('.ce-roster-tr').forEach(function (tr) {
      tr.addEventListener('click', function (evt) {
        if (evt.target.closest('.ce-fa-name')) return;
        var fid = parseInt(tr.getAttribute('data-fighter-id'), 10);
        selectFighter(fid);
      });
      tr.addEventListener('dblclick', function (evt) {
        if (evt.target.closest('.ce-fa-name')) return;
        var fid = parseInt(tr.getAttribute('data-fighter-id'), 10);
        window.CE.app.navigate('fighter_profile', { fighter_id: fid });
      });
    });

    // Name hyperlinks → Fighter Profile
    document.querySelectorAll('.ce-fa-name').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        var fid = link.getAttribute('data-fighter-id');
        if (fid) window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
      });
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

    // Sign button → open modal
    var signBtn = document.getElementById('ce-fa-sign-btn');
    if (signBtn) signBtn.addEventListener('click', function () {
      if (!state.selectedFighter || !state.estimatedCost) return;
      var modal = document.getElementById('ce-fa-modal');
      if (modal) modal.style.display = 'flex';
    });

    // Modal controls
    var modalClose = document.getElementById('ce-fa-modal-close');
    if (modalClose) modalClose.addEventListener('click', closeModal);
    var modalCancel = document.getElementById('ce-fa-modal-cancel');
    if (modalCancel) modalCancel.addEventListener('click', closeModal);
    var modalOverlay = document.getElementById('ce-fa-modal');
    if (modalOverlay) modalOverlay.addEventListener('click', function (evt) {
      if (evt.target === modalOverlay) closeModal();
    });

    var modalConfirm = document.getElementById('ce-fa-modal-confirm');
    if (modalConfirm) modalConfirm.addEventListener('click', function () {
      if (!state.selectedFighter) return;
      var fid = state.selectedFighter.fighter_id;
      modalConfirm.disabled = true;
      modalConfirm.textContent = 'Signing…';
      // Phase E3.3 — pass the negotiation params to the backend.
      var neg = state.negotiation || {};
      window.CE.bridge.signFreeAgent(
        fid,
        neg.salary,
        neg.signingBonus,
        neg.contractLength,
        neg.winBonusPct
      ).then(function (result) {
        closeModal();
        if (result && result.ok) {
          var summary = (result.cost_display || '') + '/yr';
          if (result.signing_bonus > 0) {
            summary += ' + ' + (result.signing_bonus_display || '') + ' bonus';
          }
          summary += ' · ' + (result.contract_length || 2) + 'y deal';
          showSignToast('Signed ' + (state._lastSelectedName || '') + ' · ' + summary, 'success');
          state.selectedFighter = null;
          state.estimatedCost = null;
          state.negotiation = null;  // reset for next signing
          loadAndRender();
        } else {
          showSignToast('Sign failed: ' + (result && result.error ? result.error : 'unknown'), 'error');
          modalConfirm.disabled = false;
          modalConfirm.textContent = 'Make Him Yours';
        }
      }).catch(function (err) {
        showSignToast('Sign failed: ' + err, 'error');
        modalConfirm.disabled = false;
        modalConfirm.textContent = 'Make Him Yours';
      });
    });

    // Phase E3.3 — wire the negotiation sliders (after the modal HTML
    // has been rendered). Pass the estimate_value so the acceptance
    // threshold can be computed.
    if (state.estimatedCost && state.estimatedCost.cost_value) {
      wireNegotiationSliders(state.estimatedCost.cost_value);
    }
  }

  function closeModal() {
    var modal = document.getElementById('ce-fa-modal');
    if (modal) modal.style.display = 'none';
    var btn = document.getElementById('ce-fa-modal-confirm');
    if (btn) { btn.disabled = false; btn.textContent = 'Make Him Yours'; }
  }

  function selectFighter(fid) {
    // Find fighter in current rendered rows
    var rows = document.querySelectorAll('.ce-roster-tr');
    var found = null;
    rows.forEach(function (r) {
      var rid = parseInt(r.getAttribute('data-fighter-id'), 10);
      if (rid === fid) {
        r.classList.add('ce-roster-tr--selected');
        // Rebuild selectedFighter from row data (we cached it on render)
        found = state._lastFighters && state._lastFighters[fid];
      } else {
        r.classList.remove('ce-roster-tr--selected');
      }
    });
    if (!found) return;
    state.selectedFighter = found;
    state._lastSelectedName = found.name;
    state.estimatedCost = null;
    // Phase E3.3 — reset negotiation state when a new fighter is
    // selected. renderModal() will re-initialize it from the new
    // estimate_signing_cost value.
    state.negotiation = null;
    // Re-render sign bar (empty cost, "Estimating…")
    var existingBar = document.querySelector('.ce-fa-signbar');
    if (existingBar) {
      existingBar.outerHTML = renderSignBar();
    }
    // Re-wire sign button + modal
    wireSignBar();
    // Fetch cost estimate
    window.CE.bridge.estimateSigningCost(fid).then(function (cost) {
      state.estimatedCost = cost;
      var bar = document.querySelector('.ce-fa-signbar');
      if (bar) {
        bar.outerHTML = renderSignBar();
      }
      // Re-render modal too
      var modal = document.getElementById('ce-fa-modal');
      if (modal) {
        modal.outerHTML = renderModal();
      } else {
        // Append modal to host
        var host = document.getElementById('screen-content');
        if (host) {
          var wrap = document.createElement('div');
          wrap.innerHTML = renderModal();
          if (wrap.firstChild) host.appendChild(wrap.firstChild);
        }
      }
      wireSignBar();
    });
  }

  function wireSignBar() {
    var signBtn = document.getElementById('ce-fa-sign-btn');
    if (signBtn) {
      // Remove old listeners by cloning
      var newBtn = signBtn.cloneNode(true);
      signBtn.parentNode.replaceChild(newBtn, signBtn);
      newBtn.addEventListener('click', function () {
        if (!state.selectedFighter || !state.estimatedCost) return;
        var modal = document.getElementById('ce-fa-modal');
        if (modal) modal.style.display = 'flex';
      });
    }
    var modalClose = document.getElementById('ce-fa-modal-close');
    if (modalClose) {
      var newClose = modalClose.cloneNode(true);
      modalClose.parentNode.replaceChild(newClose, modalClose);
      newClose.addEventListener('click', closeModal);
    }
    var modalCancel = document.getElementById('ce-fa-modal-cancel');
    if (modalCancel) {
      var newCancel = modalCancel.cloneNode(true);
      modalCancel.parentNode.replaceChild(newCancel, modalCancel);
      newCancel.addEventListener('click', closeModal);
    }
    var modalConfirm = document.getElementById('ce-fa-modal-confirm');
    if (modalConfirm) {
      var newConfirm = modalConfirm.cloneNode(true);
      modalConfirm.parentNode.replaceChild(newConfirm, modalConfirm);
      newConfirm.addEventListener('click', function () {
        if (!state.selectedFighter) return;
        var fid = state.selectedFighter.fighter_id;
        newConfirm.disabled = true;
        newConfirm.textContent = 'Signing…';
        // Phase E3.3 — pass the negotiation params to the backend.
        var neg = state.negotiation || {};
        // Phase M3.2 — if this fighter has an active bidding alert,
        // use counterOffer instead of signFreeAgent. The bidding
        // alert flag is set when the player navigated here from the
        // Dashboard's "Counter Offer" button.
        var useCounterOffer = !!state.biddingAlert;
        var apiCall = useCounterOffer
          ? window.CE.bridge.counterOffer(
              fid, neg.salary, neg.signingBonus,
              neg.contractLength, neg.winBonusPct
            )
          : window.CE.bridge.signFreeAgent(
              fid, neg.salary, neg.signingBonus,
              neg.contractLength, neg.winBonusPct
            );
        apiCall.then(function (result) {
          closeModal();
          if (result && result.ok) {
            if (useCounterOffer && result.accepted !== undefined) {
              // counter_offer response — different shape than
              // sign_free_agent. Build a summary from the result.
              if (result.accepted) {
                var summary = (result.cost_display || '') + '/yr';
                if (result.signing_bonus > 0) {
                  summary += ' + ' + (result.signing_bonus_display || '') + ' bonus';
                }
                summary += ' · ' + (result.contract_length || 2) + 'y deal';
                showSignToast(
                  'WON THE BID — ' +
                  (state.selectedFighter ? state.selectedFighter.name : '') +
                  ' · ' + summary, 'success'
                );
              } else {
                showSignToast(
                  'LOST THE BID — ' +
                  (result.chosen_promo_name || 'rival promo') +
                  ' signed ' +
                  (state.selectedFighter ? state.selectedFighter.name : ''),
                  'error'
                );
              }
            } else {
              // sign_free_agent response (the old path).
              var summary2 = (result.cost_display || '') + '/yr';
              if (result.signing_bonus > 0) {
                summary2 += ' + ' + (result.signing_bonus_display || '') + ' bonus';
              }
              summary2 += ' · ' + (result.contract_length || 2) + 'y deal';
              showSignToast(
                'Signed ' + (state.selectedFighter ? state.selectedFighter.name : '') +
                ' · ' + summary2, 'success'
              );
            }
            state.selectedFighter = null;
            state.estimatedCost = null;
            state.negotiation = null;
            state.biddingAlert = false;
            loadAndRender();
          } else if (result && result.blocked_by_bidding_alert) {
            // sign_free_agent blocked because there's a pending
            // bidding alert — redirect the player to counter_offer.
            showSignToast(
              'BIDDING WAR: ' + (result.rival_promo_name || 'Rival') +
              ' is pursuing this fighter. Use Counter Offer to compete.',
              'error'
            );
            state.biddingAlert = true;
            // Re-render the modal so the confirm button uses
            // counterOffer on the next click.
            var modal = document.getElementById('ce-fa-modal');
            if (modal) {
              modal.outerHTML = renderModal();
              wireSignBar();
            }
            newConfirm.disabled = false;
            newConfirm.textContent = 'Counter Offer';
          } else {
            showSignToast('Sign failed: ' + (result && result.error ? result.error : 'unknown'), 'error');
            newConfirm.disabled = false;
            newConfirm.textContent = useCounterOffer ? 'Counter Offer' : 'Make Him Yours';
          }
        }).catch(function (err) {
          showSignToast('Sign failed: ' + err, 'error');
          newConfirm.disabled = false;
          newConfirm.textContent = useCounterOffer ? 'Counter Offer' : 'Make Him Yours';
        });
      });
    }
    var modalOverlay = document.getElementById('ce-fa-modal');
    if (modalOverlay) {
      modalOverlay.addEventListener('click', function (evt) {
        if (evt.target === modalOverlay) closeModal();
      });
    }

    // Phase E3.3 — wire the negotiation sliders (after the modal HTML
    // has been re-rendered via wireSignBar). Pass the estimate_value
    // so the acceptance threshold can be computed.
    if (state.estimatedCost && state.estimatedCost.cost_value) {
      wireNegotiationSliders(state.estimatedCost.cost_value);
    }
  }

  function showSignToast(msg, kind) {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var existing = host.querySelector('.ce-toast');
    if (existing) existing.remove();
    var toast = document.createElement('div');
    toast.className = 'ce-toast ce-toast--' + (kind || 'info');
    toast.textContent = msg;
    host.appendChild(toast);
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 4000);
  }

  // ============================================================
  // PUBLIC API
  // ============================================================
  function loadAndRender() {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Scanning the open market…</div></div>';
    }
    return window.CE.bridge.getFreeAgents(state.page, state.filters).then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load free agents</div><div>' + escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      // CR-3a + CR-4: backend now returns weight_classes (with gender
      // + count fields for the optgroup dropdown) and nationalities
      // (top 20 by FA count, for the nationality filter dropdown) in
      // the payload. Cache them so renderFilters can populate.
      if (data.weight_classes && data.weight_classes.length) {
        state.weightClasses = data.weight_classes;
      }
      if (data.nationalities) {
        state.nationalities = data.nationalities;
      }
      // Build a quick-lookup map for row clicks
      state._lastFighters = {};
      (data.fighters || []).forEach(function (f) {
        state._lastFighters[f.fighter_id] = f;
      });
      render(data);
    });
  }

  // Phase M3.2 — load the Free Agents screen with a fighter pre-
  // selected + the bidding-alert flag set. Called from app.navigate
  // when the player clicks "Counter Offer" on a Dashboard bidding
  // alert. After render, the fighter is selected + the modal opens
  // with the confirm button labeled "Counter Offer" (uses
  // bridge.counterOffer instead of bridge.signFreeAgent).
  function loadAndRenderWithBiddingAlert(fighterId) {
    state.biddingAlert = true;
    return loadAndRender().then(function () {
      // Pre-select the fighter (the selectFighter helper handles
      // the row highlight + sign bar + modal initialization).
      // Use setTimeout(0) so the render has flushed to the DOM
      // before we try to select the row.
      setTimeout(function () {
        var rows = document.querySelectorAll('.ce-roster-tr');
        var found = false;
        rows.forEach(function (r) {
          if (parseInt(r.getAttribute('data-fighter-id'), 10) === Number(fighterId)) {
            found = true;
          }
        });
        if (found) {
          selectFighter(Number(fighterId));
          // Open the modal automatically so the player can
          // immediately adjust their offer.
          setTimeout(function () {
            var modal = document.getElementById('ce-fa-modal');
            if (modal) modal.style.display = 'flex';
            // Update confirm button label.
            var confirmBtn = document.getElementById('ce-fa-modal-confirm');
            if (confirmBtn) confirmBtn.textContent = 'Counter Offer';
            // Re-wire so the new label sticks.
            wireSignBar();
            var confirmBtn2 = document.getElementById('ce-fa-modal-confirm');
            if (confirmBtn2) confirmBtn2.textContent = 'Counter Offer';
          }, 150);
        } else {
          // Fighter not on the current page — try to find which
          // page has them (defensive: just show a toast).
          showSignToast(
            'Fighter not on this page — adjust filters or scroll to find him, then click his row to counter-offer.',
            'error'
          );
        }
      }, 100);
    });
  }

  return {
    loadAndRender: loadAndRender,
    loadAndRenderWithBiddingAlert: loadAndRenderWithBiddingAlert,
    render: render,
  };
})();
