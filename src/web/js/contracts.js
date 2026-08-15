/* ============================================================
   CAGE EMPIRE — Deals (Contracts) Screen ("DEALS")
   ============================================================
   Phase P2-FINANCE-CONTRACTS §2 (docs/P2_PLAN_FINANCE_CONTRACTS.md).
   Replaces the placeholder `contracts` nav item. Renders the player's
   promo's active fighter + staff contracts — the Empire Builder
   fantasy's commitment ledger.

   What the player sees:
     - Section header: "DEALS" (gold accent) + subtitle showing the
       active contract count ("92 active contracts").
     - Expiring Soon alert (if any ≤30 days): red banner "⚠ X
       contracts expire within 30 days. Time to talk extensions."
     - Filter bar: All / Expiring Soon (≤60 days) / Fighters / Staff
       + name search input.
     - Fighter Contracts table:
         * Fighter name (clickable → Fighter Profile).
         * Salary (monospace, e.g. "$200K/yr").
         * Start date → End date.
         * Days until expiry (color-coded: red ≤30d, yellow ≤60d,
           green >60d).
         * Win bonus (voice phrase: "75% win bonus" or "—").
         * Status chip (Active / Expiring).
     - Staff Contracts table:
         * Staff name.
         * Role (GM / Doctor / Commentator / Scout / Cutman).
         * Skill (voice phrase: "world-class" / "established" /
           "promising" / "unproven").
         * Salary (monospace).
         * End date + days until expiry (color-coded).
     - Click contract row → expand to show full details (buyout
       clause, exclusivity, bonus structure breakdown).
     - Empty state: "No deals on the table. Sign some fighters or
       staff."

   Voice compliance (CONVENTIONS §14):
     - Skill level → voice phrase, NEVER raw 0-100 int.
     - Salary amounts OK as dollar figures (they're contracts).
     - Days-until-expiry OK as a number (it's a countdown).
     - Bonus structure → voice phrase ("75% win bonus" / "—").
     - Fighter name hyperlinks → Fighter Profile.
   ============================================================ */

window.CE = window.CE || {};

window.CE.contracts = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    page: 1,
    filters: { tab: 'all', search: '' },
    data: null,
    expandedContractIds: new Set(),
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

  /** expiry_tier → CSS class for the days-until-expiry cell. */
  function expiryClass(tier) {
    switch (tier) {
      case 'critical': return 'ce-contracts__days--critical';
      case 'soon':     return 'ce-contracts__days--soon';
      case 'ok':       return 'ce-contracts__days--ok';
      case 'expired':  return 'ce-contracts__days--expired';
      default:         return 'ce-contracts__days--unknown';
    }
  }

  /** expiry_tier → status chip label (Active / Expiring / Expired). */
  function expiryStatusLabel(tier) {
    switch (tier) {
      case 'critical': return 'EXPIRING';
      case 'soon':     return 'EXPIRING';
      case 'expired':  return 'EXPIRED';
      default:         return 'ACTIVE';
    }
  }

  /** expiry_tier → status chip CSS class. */
  function expiryStatusClass(tier) {
    switch (tier) {
      case 'critical':
      case 'soon':     return 'ce-chip ce-chip-warning ce-contracts__status-chip';
      case 'expired':  return 'ce-chip ce-chip-crimson ce-contracts__status-chip';
      default:         return 'ce-chip ce-chip-green ce-contracts__status-chip';
    }
  }

  /** Format days_until_expiry as a display string. */
  function daysDisplay(days) {
    if (days === null || days === undefined) return '—';
    if (days < 0) return 'expired';
    if (days === 0) return 'today';
    if (days === 1) return '1 day';
    return days + ' days';
  }

  // ============================================================
  // RENDER — SECTION HEADER
  // ============================================================
  function renderHeader(counts) {
    var totalActive = (counts && counts.total_active) || 0;
    var sub = totalActive + ' active contract' + (totalActive === 1 ? '' : 's');
    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header">' +
          '<div class="ce-accent-bar ce-accent-gold"></div>' +
          '<span class="ce-sec-icon">✍</span>' +
          '<span class="ce-sec-title ce-sec-title-gold">DEALS</span>' +
          '<span class="ce-sec-sub ce-contracts__sec-sub">' + escapeHtml(sub) + '</span>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — EXPIRING SOON ALERT BANNER
  // ============================================================
  function renderExpiringAlert(counts) {
    if (!counts || !counts.expiring_30d) return '';
    var n = counts.expiring_30d;
    var noun = n === 1 ? 'contract' : 'contracts';
    return '' +
      '<div class="ce-contracts__alert" role="alert">' +
        '<span class="ce-contracts__alert-icon">⚠</span>' +
        '<span class="ce-contracts__alert-text">' +
          '<strong>' + n + '</strong> ' + noun + ' expire within 30 days. ' +
          'Time to talk extensions.' +
        '</span>' +
      '</div>';
  }

  // ============================================================
  // RENDER — FILTER BAR (tabs + search)
  // ============================================================
  function renderFilterBar() {
    var activeTab = (state.data && state.data.filter && state.data.filter.tab) || state.filters.tab;
    var counts = (state.data && state.data.counts) || {};

    function tabBtn(id, label, count) {
      var isActive = (activeTab === id) ? ' ce-contracts__tab--active' : '';
      var badge = (typeof count === 'number' && count > 0)
        ? '<span class="ce-contracts__tab-badge">' + count + '</span>'
        : '';
      return '<button type="button" class="ce-contracts__tab' + isActive +
        '" data-tab="' + id + '">' + escapeHtml(label) + badge + '</button>';
    }

    return '' +
      '<div class="ce-contracts__filter-bar">' +
        '<div class="ce-contracts__tabs">' +
          tabBtn('all', 'All', counts.total_active) +
          tabBtn('expiring_soon', 'Expiring Soon', counts.expiring_60d) +
          tabBtn('fighters', 'Fighters', counts.active_fighter_contracts) +
          tabBtn('staff', 'Staff', counts.active_staff_contracts) +
        '</div>' +
        '<div class="ce-contracts__search-wrap">' +
          '<input type="text" id="ce-contracts-search" class="ce-contracts__search-input" ' +
            'placeholder="Search by name…" value="' +
            escapeHtml(state.filters.search) + '" />' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — FIGHTER CONTRACTS TABLE
  // ============================================================
  function renderFighterContracts(fc) {
    var items = (fc && fc.items) || [];
    if (!items.length) {
      return '' +
        '<div class="ce-contracts__section">' +
          '<div class="ce-contracts__section-title">FIGHTER CONTRACTS</div>' +
          '<div class="ce-contracts__empty">' +
            '<div class="ce-contracts__empty-title">No fighter contracts match.</div>' +
            '<div class="ce-contracts__empty-body">Sign fighters on the Open Market to fill your stable.</div>' +
          '</div>' +
        '</div>';
    }

    var rows = items.map(function (c) {
      return renderFighterRow(c);
    }).join('');

    return '' +
      '<div class="ce-contracts__section">' +
        '<div class="ce-contracts__section-title">FIGHTER CONTRACTS ' +
          '<span class="ce-contracts__section-count">(' + fc.total + ')</span>' +
        '</div>' +
        '<div class="ce-contracts__table-wrap">' +
          '<table class="ce-contracts__table">' +
            '<thead>' +
              '<tr>' +
                '<th class="ce-contracts__th ce-contracts__th--name">FIGHTER</th>' +
                '<th class="ce-contracts__th ce-contracts__th--salary">SALARY</th>' +
                '<th class="ce-contracts__th ce-contracts__th--dates">CONTRACT</th>' +
                '<th class="ce-contracts__th ce-contracts__th--days">EXPIRES IN</th>' +
                '<th class="ce-contracts__th ce-contracts__th--bonus">BONUS</th>' +
                '<th class="ce-contracts__th ce-contracts__th--status">STATUS</th>' +
              '</tr>' +
            '</thead>' +
            '<tbody>' + rows + '</tbody>' +
          '</table>' +
        '</div>' +
        renderPagination(fc) +
      '</div>';
  }

  function renderFighterRow(c) {
    var daysCls = expiryClass(c.expiry_tier);
    var statusCls = expiryStatusClass(c.expiry_tier);
    var statusLabel = expiryStatusLabel(c.expiry_tier);
    var nameHtml = '<a class="ce-link ce-contracts__name" href="#" ' +
      'data-fighter-id="' + c.fighter_id + '">' + escapeHtml(c.fighter_name) + '</a>';
    if (c.nickname) {
      nameHtml += '<span class="ce-contracts__nick"> \'' +
        escapeHtml(c.nickname) + '\'</span>';
    }
    var isExpanded = state.expandedContractIds.has(c.contract_id);
    var rowCls = 'ce-contracts__row' + (isExpanded ? ' ce-contracts__row--expanded' : '');
    var expandIcon = isExpanded ? '▼' : '▶';

    return '' +
      '<tr class="' + rowCls + '" data-contract-id="' + c.contract_id + '">' +
        '<td class="ce-contracts__td ce-contracts__td--name">' +
          '<span class="ce-contracts__expand">' + expandIcon + '</span>' + nameHtml +
        '</td>' +
        '<td class="ce-contracts__td ce-contracts__td--salary ce-mono">' +
          escapeHtml(c.salary_display) +
        '</td>' +
        '<td class="ce-contracts__td ce-contracts__td--dates ce-mono">' +
          '<span class="ce-contracts__date-start">' +
            escapeHtml(formatDate(c.start_date_display)) +
          '</span>' +
          '<span class="ce-contracts__date-arrow">→</span>' +
          '<span class="ce-contracts__date-end">' +
            escapeHtml(formatDate(c.end_date_display)) +
          '</span>' +
        '</td>' +
        '<td class="ce-contracts__td ce-contracts__td--days ' + daysCls + '">' +
          escapeHtml(daysDisplay(c.days_until_expiry)) +
        '</td>' +
        '<td class="ce-contracts__td ce-contracts__td--bonus">' +
          escapeHtml(c.bonus_phrase) +
        '</td>' +
        '<td class="ce-contracts__td ce-contracts__td--status">' +
          '<span class="' + statusCls + '">' + statusLabel + '</span>' +
        '</td>' +
      '</tr>' +
      (isExpanded ? renderExpandedFighterRow(c) : '');
  }

  function renderExpandedFighterRow(c) {
    var bonusBreakdown = c.bonus_phrase;
    if (c.bonus_structure && typeof c.bonus_structure === 'string') {
      // Try to parse for pretty display.
      try {
        var parsed = JSON.parse(c.bonus_structure);
        if (parsed && typeof parsed === 'object') {
          var keys = Object.keys(parsed);
          if (keys.length) {
            bonusBreakdown = keys.map(function (k) {
              var v = parsed[k];
              if (k === 'win_bonus_pct') {
                return k + ': ' + (Math.round((v || 0) * 100)) + '%';
              }
              return k + ': ' + v;
            }).join(' · ');
          }
        }
      } catch (e) { /* keep as-is */ }
    }
    var buyout = (c.buyout_clause !== null && c.buyout_clause !== undefined)
      ? c.buyout_display : '—';
    var exclusive = c.exclusive_flag ? 'Exclusive' : 'Non-exclusive';
    return '' +
      '<tr class="ce-contracts__detail-row">' +
        '<td colspan="6" class="ce-contracts__detail-cell">' +
          '<div class="ce-contracts__detail-grid">' +
            renderDetailItem('CONTRACT TYPE', escapeHtml((c.contract_type || 'standard').replace('_', ' '))) +
            renderDetailItem('BUYOUT CLAUSE', escapeHtml(buyout)) +
            renderDetailItem('EXCLUSIVITY', escapeHtml(exclusive)) +
            renderDetailItem('BONUS STRUCTURE', escapeHtml(bonusBreakdown)) +
            renderDetailItem('STATUS', escapeHtml(c.status_label)) +
            renderDetailItem('CONTRACT ID', '#' + c.contract_id) +
          '</div>' +
        '</td>' +
      '</tr>';
  }

  function renderDetailItem(label, value) {
    return '' +
      '<div class="ce-contracts__detail-item">' +
        '<div class="ce-contracts__detail-label">' + label + '</div>' +
        '<div class="ce-contracts__detail-value">' + value + '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — STAFF CONTRACTS TABLE
  // ============================================================
  function renderStaffContracts(sc) {
    var items = (sc && sc.items) || [];
    if (!items.length) {
      return '' +
        '<div class="ce-contracts__section">' +
          '<div class="ce-contracts__section-title">STAFF CONTRACTS</div>' +
          '<div class="ce-contracts__empty">' +
            '<div class="ce-contracts__empty-title">No staff contracts match.</div>' +
            '<div class="ce-contracts__empty-body">Hire staff on the Staff Market to build the team behind your roster.</div>' +
          '</div>' +
        '</div>';
    }

    var rows = items.map(function (c) {
      return renderStaffRow(c);
    }).join('');

    return '' +
      '<div class="ce-contracts__section">' +
        '<div class="ce-contracts__section-title">STAFF CONTRACTS ' +
          '<span class="ce-contracts__section-count">(' + sc.total + ')</span>' +
        '</div>' +
        '<div class="ce-contracts__table-wrap">' +
          '<table class="ce-contracts__table">' +
            '<thead>' +
              '<tr>' +
                '<th class="ce-contracts__th ce-contracts__th--name">STAFF</th>' +
                '<th class="ce-contracts__th ce-contracts__th--role">ROLE</th>' +
                '<th class="ce-contracts__th ce-contracts__th--skill">SKILL</th>' +
                '<th class="ce-contracts__th ce-contracts__th--salary">SALARY</th>' +
                '<th class="ce-contracts__th ce-contracts__th--dates">CONTRACT</th>' +
                '<th class="ce-contracts__th ce-contracts__th--days">EXPIRES IN</th>' +
                '<th class="ce-contracts__th ce-contracts__th--status">STATUS</th>' +
              '</tr>' +
            '</thead>' +
            '<tbody>' + rows + '</tbody>' +
          '</table>' +
        '</div>' +
      '</div>';
  }

  function renderStaffRow(c) {
    var daysCls = expiryClass(c.expiry_tier);
    var statusCls = expiryStatusClass(c.expiry_tier);
    var statusLabel = expiryStatusLabel(c.expiry_tier);
    var isExpanded = state.expandedContractIds.has(c.contract_id);
    var rowCls = 'ce-contracts__row' + (isExpanded ? ' ce-contracts__row--expanded' : '');
    var expandIcon = isExpanded ? '▼' : '▶';

    return '' +
      '<tr class="' + rowCls + '" data-contract-id="' + c.contract_id + '">' +
        '<td class="ce-contracts__td ce-contracts__td--name">' +
          '<span class="ce-contracts__expand">' + expandIcon + '</span>' +
          '<span class="ce-contracts__staff-name">' + escapeHtml(c.staff_name) + '</span>' +
        '</td>' +
        '<td class="ce-contracts__td ce-contracts__td--role">' +
          escapeHtml(c.role_label) +
        '</td>' +
        '<td class="ce-contracts__td ce-contracts__td--skill ce-contracts__skill--' +
          escapeHtml(c.skill_phrase) + '">' +
          escapeHtml(c.skill_phrase) +
        '</td>' +
        '<td class="ce-contracts__td ce-contracts__td--salary ce-mono">' +
          escapeHtml(c.salary_display) +
        '</td>' +
        '<td class="ce-contracts__td ce-contracts__td--dates ce-mono">' +
          '<span class="ce-contracts__date-start">' +
            escapeHtml(formatDate(c.start_date_display)) +
          '</span>' +
          '<span class="ce-contracts__date-arrow">→</span>' +
          '<span class="ce-contracts__date-end">' +
            escapeHtml(formatDate(c.end_date_display)) +
          '</span>' +
        '</td>' +
        '<td class="ce-contracts__td ce-contracts__td--days ' + daysCls + '">' +
          escapeHtml(daysDisplay(c.days_until_expiry)) +
        '</td>' +
        '<td class="ce-contracts__td ce-contracts__td--status">' +
          '<span class="' + statusCls + '">' + statusLabel + '</span>' +
        '</td>' +
      '</tr>' +
      (isExpanded ? renderExpandedStaffRow(c) : '');
  }

  function renderExpandedStaffRow(c) {
    var buyout = (c.buyout_clause !== null && c.buyout_clause !== undefined)
      ? c.buyout_display : '—';
    var exclusive = c.exclusive_flag ? 'Exclusive' : 'Non-exclusive';
    return '' +
      '<tr class="ce-contracts__detail-row">' +
        '<td colspan="7" class="ce-contracts__detail-cell">' +
          '<div class="ce-contracts__detail-grid">' +
            renderDetailItem('ROLE', escapeHtml(c.role_label)) +
            renderDetailItem('SKILL', escapeHtml(c.skill_phrase)) +
            renderDetailItem('BUYOUT CLAUSE', escapeHtml(buyout)) +
            renderDetailItem('EXCLUSIVITY', escapeHtml(exclusive)) +
            renderDetailItem('STATUS', escapeHtml(c.status_label)) +
            renderDetailItem('CONTRACT ID', '#' + c.contract_id) +
          '</div>' +
        '</td>' +
      '</tr>';
  }

  // ============================================================
  // RENDER — PAGINATION (fighter contracts only)
  // ============================================================
  function renderPagination(fc) {
    if (!fc || fc.total_pages <= 1) return '';
    var html = '<div class="ce-contracts__pagination">';
    var page = fc.page;
    var total = fc.total_pages;
    html += '<button type="button" class="ce-page-btn" data-page="' + (page - 1) + '"' +
      (page <= 1 ? ' disabled' : '') + '>‹ Prev</button>';
    var pages = computePageList(page, total);
    pages.forEach(function (p) {
      if (p === '…') {
        html += '<span class="ce-page-btn ce-page-btn--ellipsis" disabled>…</span>';
      } else {
        var cls = (p === page) ? 'ce-page-btn ce-page-btn--active' : 'ce-page-btn';
        html += '<button type="button" class="' + cls + '" data-page="' + p + '">' + p + '</button>';
      }
    });
    html += '<button type="button" class="ce-page-btn" data-page="' + (page + 1) + '"' +
      (page >= total ? ' disabled' : '') + '>Next ›</button>';
    html += '</div>';
    return html;
  }

  function computePageList(current, total) {
    if (total <= 7) {
      var arr = [];
      for (var i = 1; i <= total; i++) arr.push(i);
      return arr;
    }
    var pages = [1];
    var lo = Math.max(2, current - 1);
    var hi = Math.min(total - 1, current + 1);
    if (lo > 2) pages.push('…');
    for (var j = lo; j <= hi; j++) pages.push(j);
    if (hi < total - 1) pages.push('…');
    pages.push(total);
    return pages;
  }

  // ============================================================
  // RENDER — EMPTY STATE
  // ============================================================
  function renderEmptyState() {
    return '' +
      '<div class="ce-contracts__empty-state">' +
        '<div class="ce-contracts__empty-state-icon">✍</div>' +
        '<div class="ce-contracts__empty-state-title">No deals on the table.</div>' +
        '<div class="ce-contracts__empty-state-body">Sign some fighters or staff.</div>' +
      '</div>';
  }

  // ============================================================
  // MAIN RENDER
  // ============================================================
  function render() {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var d = state.data;
    if (!d) return;

    // Truly empty state: no contracts at all.
    var hasAny = (d.counts && d.counts.total_active > 0);
    if (!hasAny && !state.filters.search) {
      host.innerHTML = '' +
        '<div class="ce-contracts">' +
          renderHeader(d.counts) +
          renderEmptyState() +
        '</div>';
      return;
    }

    var html = '' +
      '<div class="ce-contracts">' +
        renderHeader(d.counts) +
        renderExpiringAlert(d.counts) +
        renderFilterBar() +
        renderFighterContracts(d.fighter_contracts) +
        renderStaffContracts(d.staff_contracts) +
      '</div>';
    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    // Tab buttons
    document.querySelectorAll('.ce-contracts__tab[data-tab]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.filters.tab = btn.getAttribute('data-tab');
        state.page = 1;
        state.expandedContractIds.clear();
        loadAndRender();
      });
    });

    // Search input (250ms debounce)
    var searchInput = document.getElementById('ce-contracts-search');
    if (searchInput) {
      var debounce = null;
      searchInput.addEventListener('input', function () {
        if (debounce) clearTimeout(debounce);
        debounce = setTimeout(function () {
          state.filters.search = searchInput.value;
          state.page = 1;
          loadAndRender();
        }, 250);
      });
    }

    // Pagination buttons
    document.querySelectorAll('.ce-contracts__pagination .ce-page-btn[data-page]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.disabled) return;
        var p = parseInt(btn.getAttribute('data-page'), 10);
        if (!isNaN(p) && p >= 1) {
          state.page = p;
          loadAndRender();
        }
      });
    });

    // Fighter-name hyperlinks → Fighter Profile.
    document.querySelectorAll('.ce-contracts__name[data-fighter-id]').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        evt.stopPropagation();
        var fid = link.getAttribute('data-fighter-id');
        if (fid) window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
      });
    });

    // Row click → expand/collapse detail panel.
    document.querySelectorAll('.ce-contracts__row[data-contract-id]').forEach(function (row) {
      row.addEventListener('click', function (evt) {
        // Don't toggle when the user clicked a fighter-name link
        // (handled above with stopPropagation, but defensive).
        if (evt.target.closest('.ce-contracts__name')) return;
        var cid = parseInt(row.getAttribute('data-contract-id'), 10);
        if (isNaN(cid)) return;
        if (state.expandedContractIds.has(cid)) {
          state.expandedContractIds.delete(cid);
        } else {
          state.expandedContractIds.add(cid);
        }
        // Re-render in place — easier than mutating the DOM directly.
        render();
      });
    });
  }

  // ============================================================
  // LOAD + RENDER
  // ============================================================
  function loadAndRender() {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Opening the deal room…</div></div>';
    }
    return window.CE.bridge.getContractsData(state.page, state.filters).then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load contracts</div><div>' +
            escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      state.data = data;
      // Echo back server-normalized page (in case of clamp).
      if (data.fighter_contracts && data.fighter_contracts.page) {
        state.page = data.fighter_contracts.page;
      }
      render();
    }).catch(function (err) {
      console.error('[contracts] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load contracts</div><div>' +
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
