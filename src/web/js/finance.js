/* ============================================================
   CAGE EMPIRE — The Books (Finance) Screen ("THE BOOKS")
   ============================================================
   Phase P2-FINANCE-CONTRACTS §1 (docs/P2_PLAN_FINANCE_CONTRACTS.md).
   Replaces the placeholder `finance` nav item. Renders the player's
   promotion finances — the Empire Builder fantasy's payoff screen.

   What the player sees:
     - Section header: "THE BOOKS" (gold accent) + subtitle showing
       the current cash ("$89.0M in the war chest").
     - Summary strip: 4 stat tiles — Current Cash, Monthly Burn
       (estimated), Reputation (voice phrase), Fan Trust (voice
       phrase).
     - Cash Flow section (last 30 days): two-column layout.
         * Revenue column (green): ticket_sales, broadcast_revenue,
           sponsorship, merchandise, concessions — each with amount
           + total.
         * Expense column (red): fighter_purse, staff_salary,
           venue_rental, marketing, medical_cost, bonus_payment —
           each with amount + total.
         * Net profit/loss (large, color-coded).
     - Recent Transactions table: date, type (color-coded chip),
       description, amount (green positive / red negative).
       Paginated 20/page. Filterable by type dropdown + search.
     - Last Event P&L card (if available): event name, date, revenue
       breakdown, expense breakdown, net profit, show rating (voice
       phrase).
     - Empty state: "The books are open. Run your first show to see
       the numbers move."

   Voice compliance (CONVENTIONS §14):
     - Reputation + fan_trust → voice phrases ("Highly Respected" /
       "Strong"), NEVER raw 0-100 ints in headers.
     - Show rating → voice phrase ("instant classic" / "solid night"
       / "lackluster"), NEVER raw int.
     - Cash amounts OK as dollar figures (the player owns the money).
     - Monthly burn OK as a dollar figure (it's a projection).
     - Fighter name hyperlinks → Fighter Profile.
   ============================================================ */

window.CE = window.CE || {};

window.CE.finance = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    page: 1,
    filters: { transaction_type: 'all', search: '' },
    data: null,
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

  function formatDate(dateStr) {
    if (!dateStr) return '—';
    var parts = String(dateStr).split('-');
    if (parts.length !== 3) return dateStr;
    return parts[1] + '/' + parts[2] + '/' + parts[0];
  }

  /** Net profit → CSS class for color-coding. */
  function netClass(net) {
    if (net > 0) return 'ce-finance__net--positive';
    if (net < 0) return 'ce-finance__net--negative';
    return 'ce-finance__net--flat';
  }

  /** Transaction-type → CSS chip class (revenue=green, expense=red). */
  function typeChipClass(isRevenue) {
    if (isRevenue === true) return 'ce-chip ce-chip-green ce-finance__type-chip';
    if (isRevenue === false) return 'ce-chip ce-chip-crimson ce-finance__type-chip';
    return 'ce-chip ce-chip-default ce-finance__type-chip';
  }

  // ============================================================
  // RENDER — SECTION HEADER
  // ============================================================
  function renderHeader(promo) {
    var cashSub = (promo && promo.cash_display)
      ? '<span class="ce-mono">' + escapeHtml(promo.cash_display) + '</span> in the war chest'
      : 'your war chest';
    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header">' +
          '<div class="ce-accent-bar ce-accent-gold"></div>' +
          '<span class="ce-sec-icon">💰</span>' +
          '<span class="ce-sec-title ce-sec-title-gold">THE BOOKS</span>' +
          '<span class="ce-sec-sub ce-finance__sec-sub">' + cashSub + '</span>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — SUMMARY STRIP (4 stat tiles)
  // ============================================================
  function renderSummaryStrip(promo, burn) {
    var burnDisplay = (burn && burn.has_data)
      ? burn.monthly_burn_display + '<span class="ce-finance__tile-unit">/mo</span>'
      : '—';
    var burnSub = (burn && burn.has_data)
      ? 'projected burn'
      : 'no recent expenses';
    return '' +
      '<div class="ce-finance__summary-strip">' +
        renderStatTile('CURRENT CASH', (promo && promo.cash_display) || '—',
                       'war chest', 'gold') +
        renderStatTile('MONTHLY BURN', burnDisplay, burnSub, 'crimson') +
        renderStatTile('REPUTATION',
                       (promo && promo.reputation_phrase) || '—',
                       'the world sees you', 'gold') +
        renderStatTile('FAN TRUST',
                       (promo && promo.fan_trust_phrase) || '—',
                       'the faithful', 'green') +
      '</div>';
  }

  function renderStatTile(label, value, sub, accent) {
    return '' +
      '<div class="ce-finance__tile ce-finance__tile--' + accent + '">' +
        '<div class="ce-finance__tile-label">' + escapeHtml(label) + '</div>' +
        '<div class="ce-finance__tile-value">' + value + '</div>' +
        '<div class="ce-finance__tile-sub">' + escapeHtml(sub) + '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — CASH FLOW (last 30 days, two columns)
  // ============================================================
  function renderCashFlow(cf) {
    if (!cf || !cf.has_data) {
      return '' +
        '<div class="ce-finance__cashflow">' +
          '<div class="ce-finance__cashflow-empty">' +
            '<div class="ce-finance__cashflow-empty-title">The ledger is quiet.</div>' +
            '<div class="ce-finance__cashflow-empty-body">No transactions in the last 30 days. Run a card to see the numbers move.</div>' +
          '</div>' +
        '</div>';
    }
    var revRows = cf.revenue.map(function (r) {
      return renderCashFlowRow(r, true);
    }).join('');
    var expRows = cf.expenses.map(function (e) {
      return renderCashFlowRow(e, false);
    }).join('');

    var netCls = netClass(cf.net_profit);
    var netSign = cf.net_profit > 0 ? '+' : (cf.net_profit < 0 ? '−' : '');

    return '' +
      '<div class="ce-finance__cashflow">' +
        '<div class="ce-finance__cashflow-header">' +
          '<span class="ce-finance__cashflow-eyebrow">CASH FLOW</span>' +
          '<span class="ce-finance__cashflow-window">last 30 days</span>' +
        '</div>' +
        '<div class="ce-finance__cashflow-grid">' +
          '<div class="ce-finance__cashflow-col ce-finance__cashflow-col--rev">' +
            '<div class="ce-finance__cashflow-col-header">' +
              '<span class="ce-finance__cashflow-col-title">REVENUE</span>' +
              '<span class="ce-finance__cashflow-col-total">' +
                escapeHtml(cf.revenue_total ? formatSignedCash(cf.revenue_total) : '$0') +
              '</span>' +
            '</div>' +
            '<div class="ce-finance__cashflow-rows">' + revRows + '</div>' +
          '</div>' +
          '<div class="ce-finance__cashflow-col ce-finance__cashflow-col--exp">' +
            '<div class="ce-finance__cashflow-col-header">' +
              '<span class="ce-finance__cashflow-col-title">EXPENSES</span>' +
              '<span class="ce-finance__cashflow-col-total">' +
                escapeHtml(cf.expense_total ? formatSignedCash(cf.expense_total) : '$0') +
              '</span>' +
            '</div>' +
            '<div class="ce-finance__cashflow-rows">' + expRows + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="ce-finance__net ' + netCls + '">' +
          '<span class="ce-finance__net-label">NET PROFIT (30D)</span>' +
          '<span class="ce-finance__net-value">' + netSign + escapeHtml(cf.net_profit_display) + '</span>' +
        '</div>' +
      '</div>';
  }

  function renderCashFlowRow(row, isRevenue) {
    var sign = isRevenue ? '+' : '−';
    return '' +
      '<div class="ce-finance__cf-row">' +
        '<span class="ce-finance__cf-label">' + escapeHtml(row.label) + '</span>' +
        '<span class="ce-finance__cf-count">×' + row.count + '</span>' +
        '<span class="ce-finance__cf-amount ce-finance__cf-amount--' +
          (isRevenue ? 'rev' : 'exp') + '">' + sign + escapeHtml(row.display) +
        '</span>' +
      '</div>';
  }

  function formatSignedCash(n) {
    // _format_cash already adds $; we just prepend + for positive.
    var s = String(n);
    if (!s.startsWith('$') && !s.startsWith('-')) s = '$' + s;
    return '+' + s;
  }

  // ============================================================
  // RENDER — LAST EVENT P&L
  // ============================================================
  function renderLastEventPL(le) {
    if (!le) return '';
    var revRows = le.revenue.map(function (r) {
      return renderPLEntry(r, true);
    }).join('');
    var expRows = le.expenses.map(function (e) {
      return renderPLEntry(e, false);
    }).join('');
    var netCls = netClass(le.net_profit);
    var netSign = le.net_profit > 0 ? '+' : (le.net_profit < 0 ? '−' : '');

    var ratingHtml = '';
    if (le.show_rating) {
      var sr = le.show_rating;
      ratingHtml = '' +
        '<div class="ce-finance__pl-rating" style="color:' + sr.rating_color + ';">' +
          '<span class="ce-finance__pl-rating-label">FAN VERDICT</span>' +
          '<span class="ce-finance__pl-rating-phrase">' + escapeHtml(sr.rating_phrase) + '</span>' +
          '<span class="ce-chip ce-finance__pl-rating-chip" style="border-color:' +
            sr.rating_color + ';color:' + sr.rating_color + ';background:rgba(0,0,0,0.2);">' +
            escapeHtml(sr.rating_tier) + '</span>' +
        '</div>';
    }

    return '' +
      '<div class="ce-finance__pl">' +
        '<div class="ce-finance__pl-header">' +
          '<div class="ce-finance__pl-eyebrow">LAST CARD P&L</div>' +
          '<div class="ce-finance__pl-name">' + escapeHtml(le.event_name) + '</div>' +
          '<div class="ce-finance__pl-date ce-mono">' + escapeHtml(le.event_date_display) + '</div>' +
        '</div>' +
        '<div class="ce-finance__pl-body">' +
          '<div class="ce-finance__pl-col ce-finance__pl-col--rev">' +
            '<div class="ce-finance__pl-col-title">REVENUE</div>' +
            '<div class="ce-finance__pl-rows">' + revRows + '</div>' +
            '<div class="ce-finance__pl-col-total ce-finance__pl-col-total--rev">' +
              '+' + escapeHtml(formatCashNum(le.revenue_total)) + '</div>' +
          '</div>' +
          '<div class="ce-finance__pl-col ce-finance__pl-col--exp">' +
            '<div class="ce-finance__pl-col-title">EXPENSES</div>' +
            '<div class="ce-finance__pl-rows">' + expRows + '</div>' +
            '<div class="ce-finance__pl-col-total ce-finance__pl-col-total--exp">' +
              '−' + escapeHtml(formatCashNum(le.expense_total)) + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="ce-finance__pl-net ' + netCls + '">' +
          '<span class="ce-finance__pl-net-label">NET PROFIT</span>' +
          '<span class="ce-finance__pl-net-value">' + netSign + escapeHtml(le.net_profit_display) + '</span>' +
        '</div>' +
        ratingHtml +
      '</div>';
  }

  function renderPLEntry(row, isRevenue) {
    var sign = isRevenue ? '+' : '−';
    return '' +
      '<div class="ce-finance__pl-row">' +
        '<span class="ce-finance__pl-row-label">' + escapeHtml(row.label) + '</span>' +
        '<span class="ce-finance__pl-row-amount ce-finance__pl-row-amount--' +
          (isRevenue ? 'rev' : 'exp') + '">' + sign + escapeHtml(row.display) +
        '</span>' +
      '</div>';
  }

  function formatCashNum(n) {
    // Mirror Python _format_cash for the JS-side last_event totals.
    n = Number(n || 0);
    if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return '$' + (n / 1e3).toFixed(0) + 'K';
    return '$' + Math.round(n).toLocaleString();
  }

  // ============================================================
  // RENDER — FILTER BAR (transaction_type + search)
  // ============================================================
  function renderFilterBar() {
    var typeOpts = (state.data && state.data.type_options) || [];
    var optsHtml = typeOpts.map(function (opt) {
      var sel = (state.filters.transaction_type === opt.value) ? ' selected' : '';
      return '<option value="' + escapeHtml(opt.value) + '"' + sel + '>' +
        escapeHtml(opt.label) + '</option>';
    }).join('');

    return '' +
      '<div class="ce-finance__filter-bar">' +
        '<div class="ce-finance__filter-group">' +
          '<label class="ce-finance__filter-label" for="ce-finance-type">TYPE</label>' +
          '<select id="ce-finance-type" class="ce-finance__select">' + optsHtml + '</select>' +
        '</div>' +
        '<div class="ce-finance__filter-group ce-finance__filter-group--search">' +
          '<label class="ce-finance__filter-label" for="ce-finance-search">SEARCH</label>' +
          '<input type="text" id="ce-finance-search" class="ce-finance__search-input" ' +
            'placeholder="Search descriptions…" value="' + escapeHtml(state.filters.search) + '" />' +
        '</div>' +
        '<div class="ce-finance__filter-info">' +
          '<span class="ce-finance__filter-count" id="ce-finance-count"></span>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — TRANSACTIONS TABLE
  // ============================================================
  function renderTransactions(tx) {
    var items = (tx && tx.items) || [];
    var countEl = document.getElementById('ce-finance-count');
    if (countEl) {
      countEl.textContent = tx.total + ' transaction' + (tx.total === 1 ? '' : 's');
    }
    if (!items.length) {
      return '' +
        '<div class="ce-finance__tx-empty">' +
          '<div class="ce-finance__tx-empty-title">No transactions match.</div>' +
          '<div class="ce-finance__tx-empty-body">Try clearing the filters or running a card.</div>' +
        '</div>';
    }
    var rows = items.map(function (it) {
      var chipCls = typeChipClass(it.is_revenue);
      var amtCls = it.is_revenue
        ? 'ce-finance__tx-amount ce-finance__tx-amount--rev'
        : 'ce-finance__tx-amount ce-finance__tx-amount--exp';
      var sign = it.is_revenue ? '+' : '−';
      var descHtml = escapeHtml(it.description || '—');
      if (it.fighter_name) {
        descHtml += ' <a class="ce-link ce-finance__tx-fighter" href="#" data-fighter-id="' +
          it.fighter_id + '">' + escapeHtml(it.fighter_name) + '</a>';
      }
      return '' +
        '<tr class="ce-finance__tx-row">' +
          '<td class="ce-finance__tx-date ce-mono">' + escapeHtml(formatDate(it.transaction_date_display)) + '</td>' +
          '<td class="ce-finance__tx-type"><span class="' + chipCls + '">' + escapeHtml(it.type_label) + '</span></td>' +
          '<td class="ce-finance__tx-desc">' + descHtml + '</td>' +
          '<td class="' + amtCls + '">' + sign + escapeHtml(it.amount_display) + '</td>' +
        '</tr>';
    }).join('');

    return '' +
      '<div class="ce-finance__tx-table-wrap">' +
        '<table class="ce-finance__tx-table">' +
          '<thead>' +
            '<tr>' +
              '<th class="ce-finance__tx-th ce-finance__tx-th--date">DATE</th>' +
              '<th class="ce-finance__tx-th ce-finance__tx-th--type">TYPE</th>' +
              '<th class="ce-finance__tx-th ce-finance__tx-th--desc">DESCRIPTION</th>' +
              '<th class="ce-finance__tx-th ce-finance__tx-th--amount">AMOUNT</th>' +
            '</tr>' +
          '</thead>' +
          '<tbody>' + rows + '</tbody>' +
        '</table>' +
      '</div>' +
      renderPagination(tx);
  }

  function renderPagination(tx) {
    if (!tx || tx.total_pages <= 1) return '';
    var html = '<div class="ce-finance__pagination">';
    var page = tx.page;
    var total = tx.total_pages;
    // Prev button
    html += '<button type="button" class="ce-page-btn" data-page="' + (page - 1) + '"' +
      (page <= 1 ? ' disabled' : '') + '>‹ Prev</button>';
    // Page number buttons (max 7 shown, with ellipsis).
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
    // Compact pagination: always show first/last + 2 around current.
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
  // MAIN RENDER
  // ============================================================
  function render() {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var d = state.data;
    if (!d) return;

    // Empty state: no promo data (error) OR no transactions + no cash flow.
    var isEmpty = !d.promo || (d.transactions.total === 0 &&
                               !(d.cash_flow_30d && d.cash_flow_30d.has_data));
    if (isEmpty && d.promo) {
      // Even on empty transactions we show the summary strip + empty
      // state — the player should see their cash/reputation regardless.
      // (Real empty = no transactions ever recorded.)
    }

    var html = '' +
      '<div class="ce-finance">' +
        renderHeader(d.promo) +
        (d.promo ? renderSummaryStrip(d.promo, d.monthly_burn) : '') +
        (d.cash_flow_30d ? renderCashFlow(d.cash_flow_30d) : '') +
        (d.last_event_pl ? renderLastEventPL(d.last_event_pl) : '') +
        renderFilterBar() +
        renderTransactions(d.transactions) +
      '</div>';
    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    var typeSel = document.getElementById('ce-finance-type');
    if (typeSel) typeSel.addEventListener('change', function () {
      state.filters.transaction_type = typeSel.value;
      state.page = 1;
      loadAndRender();
    });

    var searchInput = document.getElementById('ce-finance-search');
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
    document.querySelectorAll('.ce-finance__pagination .ce-page-btn[data-page]').forEach(function (btn) {
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
    document.querySelectorAll('.ce-finance__tx-fighter[data-fighter-id]').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
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
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Opening the books…</div></div>';
    }
    return window.CE.bridge.getFinanceData(state.page, state.filters).then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load finance data</div><div>' +
            escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      state.data = data;
      // Echo back server-normalized page (in case of clamp).
      state.page = data.transactions.page || state.page;
      render();
    }).catch(function (err) {
      console.error('[finance] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load finance data</div><div>' +
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
