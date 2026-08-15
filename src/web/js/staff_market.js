/* ============================================================
   CAGE EMPIRE — Staff Market Screen ("Staff Market")
   ============================================================
   Phase E4 (docs/MASTER_PLAN.md §3 Phase E4 + docs/ECON_STAFF_PLAN.md
   §4-5 + task brief).

   Renders the free-agent staff pool into #screen-content using live
   data fetched via window.CE.bridge.getStaffMarketData(page, filters).

   Per task brief + ECON_STAFF_PLAN §5.3:
     - 7-column table (sharp corners — "ledger" feel, mirrors Free Agents):
       Name | Age | Role | Skill (voice phrase) | Salary Ask |
       Contract Ask | Action.
     - Sticky hire bar at the bottom: shows selected staff +
       estimated cost + Hire button.
     - Filters: role_type (Coach/Scout/Doctor/Cutman/GM/Commentator),
       skill tier (world-class/established/promising/unproven), search.
     - Pagination: 20 rows/page (matches Free Agents).
     - NEVER displays raw skill_level integer — only the voice phrase.
     - NEVER displays raw potential/ceiling — staff don't have potential.

   Hire flow (mirrors Free Agents' sign-free-agent modal):
     1. Click row → row selected, hire bar updates with staff details
        + estimated cost (bridge.estimateStaffHireCost).
     2. Click "Bring Him Onto Your Team" → modal with salary +
        signing_bonus + contract_length sliders (gradient tracks like
        the Event Builder's). Acceptance indicator updates live as
        the player drags sliders.
     3. On confirm: bridge.hireStaff(staff_id, salary, signing_bonus,
        contract_length) → if salary >= salary_ask × 0.9, hire
        succeeds → toast + refresh list.
     4. If rejected: toast shows the staff's floor + the player can
        re-open the modal and try a higher offer.

   Voice/design (per CONVENTIONS §14 + task brief):
     - Skill level shown as voice phrase ("world-class", "established",
       "promising", "unproven") — NEVER the raw 0-100 number.
     - Role labels: "Coach", "Scout", "Doctor", "Cutman",
       "General Manager", "Commentator".
     - Empty state: "No staff available in your market. Try widening
       your search."
     - Ownership language: "YOUR STAFF", "Bring Him Onto Your Team".
     - Section headers with gold accent bars + 📋 icon.
   ============================================================ */

window.CE = window.CE || {};

window.CE.staffMarket = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    page: 1,
    filters: {
      role_type: 'all',
      skill: 'all',
      search: '',
    },
    roleCounts: [],
    selectedStaff: null,
    estimatedCost: null,
    // Negotiation panel state — { salary, signingBonus, contractLength }.
    // Initialized from estimate_staff_hire_cost when the modal opens,
    // updated as the player drags sliders.
    negotiation: null,
    _searchTimer: null,
  };

  // ============================================================
  // HELPERS
  // ============================================================
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function formatCash(n) {
    n = Number(n || 0);
    if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return '$' + Math.round(n / 1e3) + 'K';
    return '$' + Math.round(n).toLocaleString();
  }

  // 7 columns per task brief. Action column is a small "View" button
  // that opens the hire modal directly (in addition to row-click).
  var COLUMNS = [
    { key: 'name',    label: 'Name',    min: '180px' },
    { key: 'age',     label: 'Age',     mono: true, width: '50px' },
    { key: 'role',    label: 'Role',    width: '140px' },
    { key: 'skill',   label: 'Skill',   width: '130px' },
    { key: 'salary',  label: 'Salary Ask', mono: true, width: '120px' },
    { key: 'length',  label: 'Contract Ask', mono: true, width: '110px' },
    { key: 'action',  label: 'Action',  width: '110px' },
  ];

  var SKILL_OPTIONS = [
    { value: 'all',           label: 'All Skill Tiers' },
    { value: 'world-class',   label: 'World-Class' },
    { value: 'established',   label: 'Established' },
    { value: 'promising',     label: 'Promising' },
    { value: 'unproven',      label: 'Unproven' },
  ];

  // ============================================================
  // RENDERERS
  // ============================================================
  function renderFilters() {
    // Role dropdown — populated from backend's role_counts (so each
    // option shows the count of available staff of that role).
    var roleOptions = '<option value="all">All Roles</option>' +
      state.roleCounts.map(function (r) {
        var sel = state.filters.role_type === r.role_type ? ' selected' : '';
        return '<option value="' + r.role_type + '"' + sel + '>' +
          escapeHtml(r.role_label) + ' (' + r.count + ')</option>';
      }).join('');

    var skillOptions = SKILL_OPTIONS.map(function (s) {
      var sel = state.filters.skill === s.value ? ' selected' : '';
      return '<option value="' + s.value + '"' + sel + '>' +
        escapeHtml(s.label) + '</option>';
    }).join('');

    return '' +
      '<div class="ce-fa-filters">' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">ROLE</label>' +
          '<select id="ce-sm-role" class="ce-filter-select">' + roleOptions + '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">SKILL TIER</label>' +
          '<select id="ce-sm-skill" class="ce-filter-select">' + skillOptions + '</select>' +
        '</div>' +
        '<div class="ce-filter-group ce-filter-search">' +
          '<label class="ce-filter-label">SEARCH</label>' +
          '<input type="text" id="ce-sm-search" class="ce-filter-input" placeholder="Name…" value="' + escapeHtml(state.filters.search || '') + '" />' +
        '</div>' +
        '<button id="ce-sm-clear" class="ce-btn ce-btn-ghost ce-filter-clear" type="button">Clear</button>' +
      '</div>';
  }

  function renderTable(data) {
    var staff = data.staff || [];
    if (!staff.length) {
      return '<div class="ce-empty-state">No staff available in your market. Try widening your search.</div>';
    }

    var headerHtml = COLUMNS.map(function (col) {
      var w = col.width ? ' style="width:' + col.width + '"' : '';
      return '<th class="ce-roster-th"' + w + '>' + escapeHtml(col.label) + '</th>';
    }).join('');

    var bodyHtml = staff.map(function (s) {
      var isSelected = state.selectedStaff && state.selectedStaff.staff_id === s.staff_id;
      var selectedClass = isSelected ? ' ce-roster-tr--selected' : '';
      // Skill tier color-coding (mirrors the ceiling-tier colors).
      var skillClass = 'ce-sm-skill--' + (s.skill_phrase || 'promising');
      var flagHtml = s.nation_flag
        ? ' <span class="ce-sm-flag" title="' + escapeHtml(s.nation_name || '') + '">' + s.nation_flag + '</span>'
        : '';

      return '' +
        '<tr class="ce-roster-tr' + selectedClass + '" data-staff-id="' + s.staff_id + '">' +
          '<td class="ce-roster-td ce-roster-td--name">' +
            '<span class="ce-sm-name">' + escapeHtml(s.name) + '</span>' + flagHtml +
            '<div class="ce-sm-specialty">' + escapeHtml(s.specialty_summary || '—') + '</div>' +
          '</td>' +
          '<td class="ce-roster-td ce-mono">' + s.age + '</td>' +
          '<td class="ce-roster-td ce-sm-role">' + escapeHtml(s.role_label) + '</td>' +
          '<td class="ce-roster-td ' + skillClass + '">' + escapeHtml(s.skill_phrase) + '</td>' +
          '<td class="ce-roster-td ce-mono">' + escapeHtml(s.salary_ask_display) + '</td>' +
          '<td class="ce-roster-td ce-mono">' + s.contract_length_ask + ' yrs</td>' +
          '<td class="ce-roster-td">' +
            '<button class="ce-btn ce-btn-ghost ce-sm-view-btn" data-staff-id="' + s.staff_id + '" type="button">View</button>' +
          '</td>' +
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
        '<div class="ce-page-info">Showing <span class="ce-mono">' + start + '–' + end + '</span> of <span class="ce-mono">' + total.toLocaleString() + '</span> free-agent staff</div>' +
        '<div class="ce-page-controls">' +
          '<button class="ce-page-btn" data-page="' + (page - 1) + '" type="button"' + (page <= 1 ? ' disabled' : '') + '>◀ Prev</button>' +
          pageHtml +
          '<span class="ce-page-indicator ce-mono">Page ' + page + ' of ' + totalPages + '</span>' +
          '<button class="ce-page-btn" data-page="' + (page + 1) + '" type="button"' + (page >= totalPages ? ' disabled' : '') + '>Next ▶</button>' +
        '</div>' +
      '</div>';
  }

  function renderHireBar() {
    if (!state.selectedStaff) {
      return '' +
        '<div class="ce-fa-signbar ce-fa-signbar--empty">' +
          '<div class="ce-fa-signbar-text">Pick someone to bring onto your team.</div>' +
        '</div>';
    }
    var s = state.selectedStaff;
    var cost = state.estimatedCost;
    var costDisplay = cost ? cost.salary_display : '…';
    var hireBtn = cost
      ? '<button class="ce-btn ce-btn-primary" id="ce-sm-hire-btn" type="button">Bring Him Onto Your Team</button>'
      : '<button class="ce-btn ce-btn-primary" id="ce-sm-hire-btn" type="button" disabled>Estimating…</button>';

    return '' +
      '<div class="ce-fa-signbar">' +
        '<div class="ce-fa-signbar-info">' +
          '<div class="ce-fa-signbar-name">' + escapeHtml(s.name) +
            ' <span class="ce-sm-flag">' + (s.nation_flag || '') + '</span>' +
          '</div>' +
          '<div class="ce-fa-signbar-meta ce-mono">' +
            escapeHtml(s.role_label) + ' · ' + s.age + 'y · ' + escapeHtml(s.skill_phrase) +
            ' · Asking ' + escapeHtml(s.salary_ask_display) +
          '</div>' +
        '</div>' +
        '<div class="ce-fa-signbar-cost">' +
          '<div class="ce-fa-signbar-cost-label">HIS ASKING PRICE</div>' +
          '<div class="ce-fa-signbar-cost-val ce-mono">' + escapeHtml(costDisplay) + '</div>' +
        '</div>' +
        hireBtn +
      '</div>';
  }

  function renderModal() {
    if (!state.selectedStaff || !state.estimatedCost) return '';
    var s = state.selectedStaff;
    var cost = state.estimatedCost;
    // Negotiation defaults — salary defaults to the asking price,
    // signing_bonus defaults to the 10% agent fee estimate, contract
    // length defaults to the staff's contract_length_ask.
    var estimateSalary = cost.salary_value || 50000;
    var estimateBonus = cost.signing_bonus_value || 0;
    if (!state.negotiation) {
      state.negotiation = {
        salary: estimateSalary,
        signingBonus: estimateBonus,
        contractLength: cost.contract_length_ask || 2,
      };
    }
    return '' +
      '<div class="ce-modal-overlay" id="ce-sm-modal" style="display:none">' +
        '<div class="ce-modal-dialog ce-fa-modal-dialog--wide">' +
          '<div class="ce-modal-header">' +
            '<div class="ce-modal-title">BRING HIM ONTO YOUR TEAM</div>' +
            '<button class="ce-modal-close" id="ce-sm-modal-close" type="button">×</button>' +
          '</div>' +
          '<div class="ce-modal-body">' +
            '<p class="ce-modal-line">Negotiate terms with <strong>' + escapeHtml(s.name) + '</strong> — ' + escapeHtml(s.role_label) + ', ' + escapeHtml(s.skill_phrase) + '.</p>' +
            '<div class="ce-fa-negotiation">' +
              // Salary
              '<div class="ce-fa-lever">' +
                '<div class="ce-fa-lever__header">' +
                  '<span class="ce-fa-lever__label">Salary (per year)</span>' +
                  '<span class="ce-fa-lever__value" id="ce-sm-salary-val">' + escapeHtml(formatCash(state.negotiation.salary)) + '</span>' +
                '</div>' +
                '<input type="range" id="ce-sm-salary" min="10000" max="500000" step="5000" value="' + state.negotiation.salary + '" />' +
                '<div class="ce-fa-lever__hint">His asking price: <span class="ce-mono">' + escapeHtml(cost.salary_display) + '</span>/yr</div>' +
              '</div>' +
              // Signing bonus
              '<div class="ce-fa-lever">' +
                '<div class="ce-fa-lever__header">' +
                  '<span class="ce-fa-lever__label">Signing Bonus (upfront)</span>' +
                  '<span class="ce-fa-lever__value" id="ce-sm-bonus-val">' + escapeHtml(formatCash(state.negotiation.signingBonus)) + '</span>' +
                '</div>' +
                '<input type="range" id="ce-sm-bonus" min="0" max="1000000" step="25000" value="' + state.negotiation.signingBonus + '" />' +
                '<div class="ce-fa-lever__hint">Deducted from your war chest immediately.</div>' +
              '</div>' +
              // Contract length
              '<div class="ce-fa-lever">' +
                '<div class="ce-fa-lever__header">' +
                  '<span class="ce-fa-lever__label">Contract Length</span>' +
                  '<span class="ce-fa-lever__value" id="ce-sm-len-val">' + state.negotiation.contractLength + ' yrs</span>' +
                '</div>' +
                '<input type="range" id="ce-sm-len" min="1" max="5" step="1" value="' + state.negotiation.contractLength + '" />' +
                '<div class="ce-fa-lever__hint">Longer = bigger total commitment, but locks him in.</div>' +
              '</div>' +
            '</div>' +
            // Live acceptance indicator (mirrors Free Agents)
            '<div class="ce-fa-acceptance" id="ce-sm-acceptance">' +
              renderAcceptance(state.negotiation, estimateSalary) +
            '</div>' +
            // Summary
            '<div class="ce-modal-contract">' +
              '<div class="ce-modal-contract-row"><span>Role:</span><span>' + escapeHtml(s.role_label) + '</span></div>' +
              '<div class="ce-modal-contract-row"><span>Skill:</span><span style="font-style:italic">' + escapeHtml(s.skill_phrase) + '</span></div>' +
              '<div class="ce-modal-contract-row"><span>Total contract value:</span><span class="ce-mono" id="ce-sm-total-val">' + escapeHtml(formatCash(state.negotiation.salary * state.negotiation.contractLength + state.negotiation.signingBonus)) + '</span></div>' +
            '</div>' +
            '<p class="ce-modal-foot">Your hire will be announced as news. Signing bonus hits your war chest today.</p>' +
          '</div>' +
          '<div class="ce-modal-footer">' +
            '<button class="ce-btn ce-btn-ghost" id="ce-sm-modal-cancel" type="button">Cancel</button>' +
            '<button class="ce-btn ce-btn-primary" id="ce-sm-modal-confirm" type="button">Make Him Yours</button>' +
          '</div>' +
        '</div>' +
      '</div>';
  }

  // Acceptance indicator — staff accepts if salary >= salary_ask × 0.9.
  // Mirrors Free Agents' renderAcceptance pattern.
  function renderAcceptance(neg, askingSalary) {
    var threshold = askingSalary * 0.9;
    var accepts = neg.salary >= threshold;
    if (accepts) {
      return '<div class="ce-fa-acceptance__indicator ce-fa-acceptance__indicator--accept">✓ He\'ll sign for this.</div>' +
        '<div class="ce-fa-acceptance__detail">Salary ' + escapeHtml(formatCash(neg.salary)) + '/yr clears his ' + escapeHtml(formatCash(threshold)) + '/yr floor.</div>';
    }
    return '<div class="ce-fa-acceptance__indicator ce-fa-acceptance__indicator--reject">✗ He\'s not interested at that number.</div>' +
      '<div class="ce-fa-acceptance__detail">Salary ' + escapeHtml(formatCash(neg.salary)) + '/yr is below his ' + escapeHtml(formatCash(threshold)) + '/yr floor. Add salary or walk away.</div>';
  }

  function updateAcceptance(askingSalary) {
    var acc = document.getElementById('ce-sm-acceptance');
    if (acc) acc.innerHTML = renderAcceptance(state.negotiation, askingSalary);
    var totalEl = document.getElementById('ce-sm-total-val');
    if (totalEl) {
      var totalValue = state.negotiation.salary * state.negotiation.contractLength + state.negotiation.signingBonus;
      totalEl.textContent = formatCash(totalValue);
    }
    // Disable the confirm button if the offer is below threshold.
    var threshold = askingSalary * 0.9;
    var confirmBtn = document.getElementById('ce-sm-modal-confirm');
    if (confirmBtn) {
      confirmBtn.disabled = state.negotiation.salary < threshold;
    }
  }

  function wireNegotiationSliders(askingSalary) {
    var salarySlider = document.getElementById('ce-sm-salary');
    if (salarySlider) {
      salarySlider.addEventListener('input', function () {
        state.negotiation.salary = parseInt(salarySlider.value, 10);
        var valEl = document.getElementById('ce-sm-salary-val');
        if (valEl) valEl.textContent = formatCash(state.negotiation.salary);
        updateAcceptance(askingSalary);
      });
    }
    var bonusSlider = document.getElementById('ce-sm-bonus');
    if (bonusSlider) {
      bonusSlider.addEventListener('input', function () {
        state.negotiation.signingBonus = parseInt(bonusSlider.value, 10);
        var valEl = document.getElementById('ce-sm-bonus-val');
        if (valEl) valEl.textContent = formatCash(state.negotiation.signingBonus);
        updateAcceptance(askingSalary);
      });
    }
    var lenSlider = document.getElementById('ce-sm-len');
    if (lenSlider) {
      lenSlider.addEventListener('input', function () {
        state.negotiation.contractLength = parseInt(lenSlider.value, 10);
        var valEl = document.getElementById('ce-sm-len-val');
        if (valEl) valEl.textContent = state.negotiation.contractLength + ' yrs';
        updateAcceptance(askingSalary);
      });
    }
    // Initial state.
    updateAcceptance(askingSalary);
  }

  function render(data) {
    var host = document.getElementById('screen-content');
    if (!host) return;

    var html = '' +
      '<div class="ce-sm">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">👔</span>' +
            '<span class="ce-sec-title ce-sec-title-gold">STAFF MARKET</span>' +
            '<span class="ce-sec-sub ce-mono">' + (data.total || 0).toLocaleString() + ' staff available</span>' +
          '</div>' +
          renderFilters() +
          renderTable(data) +
          renderPagination(data) +
        '</div>' +
      '</div>' +
      renderHireBar() +
      renderModal();

    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    // Filters
    var roleSel = document.getElementById('ce-sm-role');
    if (roleSel) roleSel.addEventListener('change', function () {
      state.filters.role_type = roleSel.value;
      state.page = 1;
      loadAndRender();
    });

    var skillSel = document.getElementById('ce-sm-skill');
    if (skillSel) skillSel.addEventListener('change', function () {
      state.filters.skill = skillSel.value;
      state.page = 1;
      loadAndRender();
    });

    var searchInput = document.getElementById('ce-sm-search');
    if (searchInput) searchInput.addEventListener('input', function () {
      if (state._searchTimer) clearTimeout(state._searchTimer);
      state._searchTimer = setTimeout(function () {
        state.filters.search = searchInput.value;
        state.page = 1;
        loadAndRender();
      }, 200);
    });

    var clearBtn = document.getElementById('ce-sm-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () {
      state.filters = { role_type: 'all', skill: 'all', search: '' };
      state.page = 1;
      loadAndRender();
    });

    // Row interactions: click = select + fetch cost
    document.querySelectorAll('.ce-roster-tr').forEach(function (tr) {
      tr.addEventListener('click', function (evt) {
        if (evt.target.closest('.ce-sm-view-btn')) return;
        var sid = parseInt(tr.getAttribute('data-staff-id'), 10);
        selectStaff(sid);
      });
    });

    // View buttons (in the Action column) — select + open modal.
    document.querySelectorAll('.ce-sm-view-btn').forEach(function (btn) {
      btn.addEventListener('click', function (evt) {
        evt.stopPropagation();
        var sid = parseInt(btn.getAttribute('data-staff-id'), 10);
        selectStaff(sid).then(function () {
          var modal = document.getElementById('ce-sm-modal');
          if (modal) modal.style.display = 'flex';
        });
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

    // Hire button → open modal
    var hireBtn = document.getElementById('ce-sm-hire-btn');
    if (hireBtn) hireBtn.addEventListener('click', function () {
      if (!state.selectedStaff || !state.estimatedCost) return;
      var modal = document.getElementById('ce-sm-modal');
      if (modal) modal.style.display = 'flex';
    });

    // Modal controls
    var modalClose = document.getElementById('ce-sm-modal-close');
    if (modalClose) modalClose.addEventListener('click', closeModal);
    var modalCancel = document.getElementById('ce-sm-modal-cancel');
    if (modalCancel) modalCancel.addEventListener('click', closeModal);
    var modalOverlay = document.getElementById('ce-sm-modal');
    if (modalOverlay) modalOverlay.addEventListener('click', function (evt) {
      if (evt.target === modalOverlay) closeModal();
    });

    var modalConfirm = document.getElementById('ce-sm-modal-confirm');
    if (modalConfirm) modalConfirm.addEventListener('click', function () {
      if (!state.selectedStaff) return;
      var sid = state.selectedStaff.staff_id;
      modalConfirm.disabled = true;
      modalConfirm.textContent = 'Hiring…';
      var neg = state.negotiation || {};
      window.CE.bridge.hireStaff(
        sid,
        neg.salary,
        neg.signingBonus,
        neg.contractLength
      ).then(function (result) {
        closeModal();
        if (result && result.ok) {
          var summary = (result.salary_display || '') + ' · ' +
            (result.contract_length || 2) + 'y deal';
          if (result.signing_bonus > 0) {
            summary += ' + ' + (result.signing_bonus_display || '') + ' bonus';
          }
          showHireToast('Hired ' + (result.staff_name || '') + ' (' + (result.role_label || '') + ') · ' + summary, 'success');
          state.selectedStaff = null;
          state.estimatedCost = null;
          state.negotiation = null;
          loadAndRender();
        } else if (result && result.rejected) {
          // Staff refused — show the error message in a toast + keep
          // the modal open so the player can adjust the offer.
          showHireToast(result.error || 'Staff refused the offer.', 'error');
          modalConfirm.disabled = false;
          modalConfirm.textContent = 'Make Him Yours';
        } else {
          showHireToast('Hire failed: ' + (result && result.error ? result.error : 'unknown'), 'error');
          modalConfirm.disabled = false;
          modalConfirm.textContent = 'Make Him Yours';
        }
      }).catch(function (err) {
        showHireToast('Hire failed: ' + err, 'error');
        modalConfirm.disabled = false;
        modalConfirm.textContent = 'Make Him Yours';
      });
    });

    // Wire the negotiation sliders (after the modal HTML is rendered).
    if (state.estimatedCost && state.estimatedCost.salary_value) {
      wireNegotiationSliders(state.estimatedCost.salary_value);
    }
  }

  function closeModal() {
    var modal = document.getElementById('ce-sm-modal');
    if (modal) modal.style.display = 'none';
    var btn = document.getElementById('ce-sm-modal-confirm');
    if (btn) { btn.disabled = false; btn.textContent = 'Make Him Yours'; }
  }

  // Returns a Promise that resolves when the staff is selected + cost
  // is fetched (so the View button's then() can open the modal).
  function selectStaff(sid) {
    // Find staff in current rendered rows
    var rows = document.querySelectorAll('.ce-roster-tr');
    var found = null;
    rows.forEach(function (r) {
      var rid = parseInt(r.getAttribute('data-staff-id'), 10);
      if (rid === sid) {
        r.classList.add('ce-roster-tr--selected');
        found = state._lastStaff && state._lastStaff[sid];
      } else {
        r.classList.remove('ce-roster-tr--selected');
      }
    });
    if (!found) return Promise.resolve();
    state.selectedStaff = found;
    state.estimatedCost = null;
    state.negotiation = null;  // reset for new staff
    // Re-render hire bar (empty cost, "Estimating…")
    var existingBar = document.querySelector('.ce-fa-signbar');
    if (existingBar) existingBar.outerHTML = renderHireBar();
    wireHireBar();
    // Fetch cost estimate
    return window.CE.bridge.estimateStaffHireCost(sid).then(function (cost) {
      state.estimatedCost = cost;
      var bar = document.querySelector('.ce-fa-signbar');
      if (bar) bar.outerHTML = renderHireBar();
      // Re-render modal too
      var modal = document.getElementById('ce-sm-modal');
      if (modal) {
        modal.outerHTML = renderModal();
      } else {
        var host = document.getElementById('screen-content');
        if (host) {
          var wrap = document.createElement('div');
          wrap.innerHTML = renderModal();
          if (wrap.firstChild) host.appendChild(wrap.firstChild);
        }
      }
      wireHireBar();
    });
  }

  function wireHireBar() {
    var hireBtn = document.getElementById('ce-sm-hire-btn');
    if (hireBtn) {
      var newBtn = hireBtn.cloneNode(true);
      hireBtn.parentNode.replaceChild(newBtn, hireBtn);
      newBtn.addEventListener('click', function () {
        if (!state.selectedStaff || !state.estimatedCost) return;
        var modal = document.getElementById('ce-sm-modal');
        if (modal) modal.style.display = 'flex';
      });
    }
    var modalClose = document.getElementById('ce-sm-modal-close');
    if (modalClose) {
      var newClose = modalClose.cloneNode(true);
      modalClose.parentNode.replaceChild(newClose, modalClose);
      newClose.addEventListener('click', closeModal);
    }
    var modalCancel = document.getElementById('ce-sm-modal-cancel');
    if (modalCancel) {
      var newCancel = modalCancel.cloneNode(true);
      modalCancel.parentNode.replaceChild(newCancel, modalCancel);
      newCancel.addEventListener('click', closeModal);
    }
    var modalConfirm = document.getElementById('ce-sm-modal-confirm');
    if (modalConfirm) {
      var newConfirm = modalConfirm.cloneNode(true);
      modalConfirm.parentNode.replaceChild(newConfirm, modalConfirm);
      newConfirm.addEventListener('click', function () {
        if (!state.selectedStaff) return;
        var sid = state.selectedStaff.staff_id;
        newConfirm.disabled = true;
        newConfirm.textContent = 'Hiring…';
        var neg = state.negotiation || {};
        window.CE.bridge.hireStaff(
          sid, neg.salary, neg.signingBonus, neg.contractLength
        ).then(function (result) {
          closeModal();
          if (result && result.ok) {
            var summary = (result.salary_display || '') + ' · ' +
              (result.contract_length || 2) + 'y deal';
            if (result.signing_bonus > 0) {
              summary += ' + ' + (result.signing_bonus_display || '') + ' bonus';
            }
            showHireToast('Hired ' + (result.staff_name || '') + ' (' + (result.role_label || '') + ') · ' + summary, 'success');
            state.selectedStaff = null;
            state.estimatedCost = null;
            state.negotiation = null;
            loadAndRender();
          } else if (result && result.rejected) {
            showHireToast(result.error || 'Staff refused the offer.', 'error');
            newConfirm.disabled = false;
            newConfirm.textContent = 'Make Him Yours';
          } else {
            showHireToast('Hire failed: ' + (result && result.error ? result.error : 'unknown'), 'error');
            newConfirm.disabled = false;
            newConfirm.textContent = 'Make Him Yours';
          }
        }).catch(function (err) {
          showHireToast('Hire failed: ' + err, 'error');
          newConfirm.disabled = false;
          newConfirm.textContent = 'Make Him Yours';
        });
      });
    }
    var modalOverlay = document.getElementById('ce-sm-modal');
    if (modalOverlay) {
      modalOverlay.addEventListener('click', function (evt) {
        if (evt.target === modalOverlay) closeModal();
      });
    }

    // Wire the negotiation sliders (after the modal HTML is re-rendered).
    if (state.estimatedCost && state.estimatedCost.salary_value) {
      wireNegotiationSliders(state.estimatedCost.salary_value);
    }
  }

  function showHireToast(msg, kind) {
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
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Scouting the staff market…</div></div>';
    }
    return window.CE.bridge.getStaffMarketData(state.page, state.filters).then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load staff market</div><div>' + escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      // Cache role counts for the filter dropdown.
      if (data.role_counts) state.roleCounts = data.role_counts;
      // Build a quick-lookup map for row clicks.
      state._lastStaff = {};
      (data.staff || []).forEach(function (s) {
        state._lastStaff[s.staff_id] = s;
      });
      render(data);
    });
  }

  return {
    loadAndRender: loadAndRender,
    render: render,
  };
})();
