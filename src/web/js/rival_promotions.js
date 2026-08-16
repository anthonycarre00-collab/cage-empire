/* ============================================================
   CAGE EMPIRE — "The Competition" Screen (Rival Promotions)
   ============================================================
   Per CR-9 (docs/CR5_9_PLAN.md §5):
     - Two views in one screen:
       1. List view (default): grid of rival promo cards.
       2. Roster view (when a promo is selected): read-only table
          of that promo's fighters.
     - Read-only: NO Sign/Cut/Book actions. The player can SEE
       rival rosters but cannot interact with their fighters
       (poaching is a Phase E3 feature).
     - Scouting safety: rival roster exposes only stage/form voice
       phrases + record — NEVER potential/ceiling/scouting info.
     - Fighter name hyperlinks → Fighter Profile (so the player
       can drill into a rival's fighter dossier).

   Voice compliance:
     - Reputation + fan trust use voice phrases (not raw numbers).
     - Stage + Form use SHORT interpretation phrases (italic).
   ============================================================ */

window.CE = window.CE || {};

window.CE.rivalPromotions = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    view: 'list',  // 'list' or 'roster'
    selectedPromoId: null,
    selectedPromoName: '',
    page: 1,
    filters: {
      wc: '0', gender: 'all', stage: 'all', search: '',
      sort_col: 'name', sort_dir: 'asc',
    },
    weightClasses: [],
    _searchTimer: null,
    _rivalList: null,  // cached so back-from-roster is instant
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

  /** Same column shape as roster.js — read-only, no action column. */
  var COLUMNS = [
    { key: 'active', label: '',         sortable: false, width: '40px' },
    { key: 'name',   label: 'Name',     sortable: true },
    { key: 'age',    label: 'Age',      sortable: true, mono: true, width: '60px' },
    { key: 'wc',     label: 'WC',       sortable: true, mono: true, width: '140px' },
    { key: 'stage',  label: 'WHERE THEY ARE', sortable: true, italic: true },
    { key: 'form',   label: 'RIGHT NOW',      sortable: true, italic: true },
    { key: 'record', label: 'RECORD',         sortable: true, mono: true, width: '90px' },
    { key: 'gym',    label: 'TRAINING WITH',  sortable: true },
    { key: 'nat',    label: 'Nat',      sortable: false, mono: true, width: '60px' },
  ];

  var STAGE_OPTIONS = [
    { value: 'all', label: 'All Stages' },
    { value: 'prospect', label: 'Prospects' },
    { value: 'rising_contender', label: 'Rising Contenders' },
    { value: 'champion', label: 'Champions' },
    { value: 'gatekeeper', label: 'Gatekeepers' },
    { value: 'veteran', label: 'Veterans' },
    { value: 'declining', label: 'Declining' },
  ];

  function activeDotClass(f) {
    if (f.is_champion) return 'ce-dot-gold';
    if (f.is_injured || f.is_suspended) return 'ce-dot-crimson';
    if (f.momentum_label === 'collapsing' || f.momentum_label === 'falling') return 'ce-dot-crimson';
    if (f.momentum_label === 'very_high') return 'ce-dot-gold';
    return 'ce-dot-neutral';
  }

  // ============================================================
  // LIST VIEW — grid of rival promo cards
  // ============================================================
  function renderListView(promos) {
    if (!promos || !promos.length) {
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-title ce-sec-title-gold">THE COMPETITION</span>' +
          '</div>' +
          '<div class="ce-empty-state">You\'re alone at the top. No rival promotions detected.</div>' +
        '</div>';
    }

    var cards = promos.map(function (p) {
      var logo = p.logo_b64
        ? '<img src="data:image/png;base64,' + p.logo_b64 + '" class="ce-rival-card__logo" alt="' + escapeHtml(p.name) + '" />'
        : '<div class="ce-rival-card__logo ce-rival-card__logo--placeholder">' + escapeHtml((p.name || '?').charAt(0)) + '</div>';

      // Voice phrases (CR-9 §5.5: no raw numbers in UI where phrases exist).
      var repPhrase = p.reputation_phrase || '—';
      var trustPhrase = p.fan_trust_phrase || '—';

      return '' +
        '<div class="ce-rival-card" data-promo-id="' + p.promotion_id + '">' +
          logo +
          '<div class="ce-rival-card__name">' + escapeHtml(p.name) + '</div>' +
          '<div class="ce-rival-card__meta">' +
            (p.size_tier ? '<span class="ce-chip ce-chip-default">' + escapeHtml(p.size_tier) + '</span>' : '') +
            (p.broadcast_tier ? '<span class="ce-chip ce-chip-default">' + escapeHtml(p.broadcast_tier) + '</span>' : '') +
          '</div>' +
          '<div class="ce-rival-card__phrases">' +
            '<div class="ce-rival-card__phrase-row">' +
              '<span class="ce-rival-card__phrase-label">REPUTATION</span>' +
              '<span class="ce-rival-card__phrase-val">' + escapeHtml(repPhrase) + '</span>' +
            '</div>' +
            '<div class="ce-rival-card__phrase-row">' +
              '<span class="ce-rival-card__phrase-label">FAN TRUST</span>' +
              '<span class="ce-rival-card__phrase-val">' + escapeHtml(trustPhrase) + '</span>' +
            '</div>' +
          '</div>' +
          '<div class="ce-rival-card__stats">' +
            '<div class="ce-rival-card__stat">' +
              '<span class="ce-rival-card__stat-num ce-mono">' + p.roster_count + '</span>' +
              '<span class="ce-rival-card__stat-lbl">FIGHTERS</span>' +
            '</div>' +
            '<div class="ce-rival-card__stat">' +
              '<span class="ce-rival-card__stat-num ce-mono">' + p.champ_count + '</span>' +
              '<span class="ce-rival-card__stat-lbl">CHAMPIONS</span>' +
            '</div>' +
          '</div>' +
          '<button class="ce-btn ce-btn-secondary ce-rival-card__view-btn" data-promo-id="' + p.promotion_id + '" data-promo-name="' + escapeHtml(p.name) + '" type="button">View Roster</button>' +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-rival-list">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-title ce-sec-title-gold">THE COMPETITION</span>' +
            '<span class="ce-sec-sub ce-mono">' + promos.length + ' promotions vying for the same talent, the same fans, the same belts.</span>' +
          '</div>' +
          '<div class="ce-rival-grid">' + cards + '</div>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // ROSTER VIEW — read-only fighter table
  // ============================================================
  function renderFilters(data) {
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

    var stageOptions = STAGE_OPTIONS.map(function (s) {
      return '<option value="' + s.value + '"' + (state.filters.stage === s.value ? ' selected' : '') + '>' +
        escapeHtml(s.label) + '</option>';
    }).join('');

    return '' +
      '<div class="ce-roster-filters">' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">WEIGHT CLASS</label>' +
          '<select id="ce-rival-wc" class="ce-filter-select">' + wcOptions + '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">GENDER</label>' +
          '<select id="ce-rival-gender" class="ce-filter-select">' +
            '<option value="all"' + (state.filters.gender === 'all' ? ' selected' : '') + '>All</option>' +
            '<option value="male"' + (state.filters.gender === 'male' ? ' selected' : '') + '>Men</option>' +
            '<option value="female"' + (state.filters.gender === 'female' ? ' selected' : '') + '>Women</option>' +
          '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">STAGE</label>' +
          '<select id="ce-rival-stage" class="ce-filter-select">' + stageOptions + '</select>' +
        '</div>' +
        '<div class="ce-filter-group ce-filter-search">' +
          '<label class="ce-filter-label">SEARCH</label>' +
          '<input type="text" id="ce-rival-search" class="ce-filter-input" placeholder="Name…" value="' + escapeHtml(state.filters.search || '') + '" />' +
        '</div>' +
        '<button id="ce-rival-clear" class="ce-btn ce-btn-ghost ce-filter-clear" type="button">Clear</button>' +
        '<div class="ce-filter-spacer"></div>' +
        // CR-9: NO action buttons (read-only) — no "Open Dossier".
        '<div class="ce-filter-group ce-filter-actions">' +
          '<span class="ce-rival-readonly-badge">READ-ONLY</span>' +
        '</div>' +
      '</div>';
  }

  function renderTable(data) {
    var fighters = data.fighters || [];
    if (!fighters.length) {
      return '<div class="ce-empty-state">Their stable is empty. Looks like an opportunity.</div>';
    }

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
      var dotClass = activeDotClass(f);
      var nickHtml = f.nickname ? ' <span class="ce-roster-nick">\'' + escapeHtml(f.nickname) + '\'</span>' : '';
      return '' +
        '<tr class="ce-roster-tr" data-fighter-id="' + f.fighter_id + '">' +
          '<td class="ce-roster-td ce-roster-td--dot"><span class="ce-dot ' + dotClass + '"></span></td>' +
          '<td class="ce-roster-td ce-roster-td--name">' +
            '<a class="ce-link ce-roster-name" href="#" data-fighter-id="' + f.fighter_id + '">' +
              escapeHtml(f.name) + '</a>' + nickHtml +
          '</td>' +
          '<td class="ce-roster-td ce-mono">' + f.age + '</td>' +
          '<td class="ce-roster-td ce-mono ce-roster-wc">' + escapeHtml(f.wc_name) + '</td>' +
          '<td class="ce-roster-td ce-roster-stage">' + escapeHtml(f.stage_short || '—') + '</td>' +
          '<td class="ce-roster-td ce-roster-form">' + escapeHtml(f.form_short || '—') + '</td>' +
          '<td class="ce-roster-td ce-mono ce-roster-record">' + escapeHtml(f.record_str) + '</td>' +
          '<td class="ce-roster-td ce-roster-gym">' + escapeHtml(f.gym_name) + '</td>' +
          '<td class="ce-roster-td ce-mono ce-roster-nat">' + escapeHtml(f.nat_code) + '</td>' +
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
        '<div class="ce-page-info">Showing <span class="ce-mono">' + start + '–' + end + '</span> of <span class="ce-mono">' + total + '</span></div>' +
        '<div class="ce-page-controls">' +
          '<button class="ce-page-btn" data-page="' + (page - 1) + '" type="button"' + (page <= 1 ? ' disabled' : '') + '>◀ Prev</button>' +
          pageHtml +
          '<button class="ce-page-btn" data-page="' + (page + 1) + '" type="button"' + (page >= totalPages ? ' disabled' : '') + '>Next ▶</button>' +
        '</div>' +
      '</div>';
  }

  function renderRosterView(data) {
    var promoName = state.selectedPromoName || data.promo_name || 'Rival Promotion';
    return '' +
      '<div class="ce-rival-roster">' +
        '<div class="ce-section">' +
          '<div class="ce-rival-roster-header">' +
            '<button class="ce-btn ce-btn-ghost ce-rival-back-btn" id="ce-rival-back" type="button">◀ Back to Competition</button>' +
            '<div class="ce-sec-header">' +
              '<div class="ce-accent-bar ce-accent-gold"></div>' +
              '<span class="ce-sec-title ce-sec-title-gold">VIEWING: ' + escapeHtml(promoName.toUpperCase()) + '</span>' +
              '<span class="ce-sec-sub ce-mono ce-rival-readonly-tag">(read-only)</span>' +
            '</div>' +
          '</div>' +
          renderFilters(data) +
          renderTable(data) +
          renderPagination(data) +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireListEvents() {
    // "View Roster" buttons on each card
    document.querySelectorAll('.ce-rival-card__view-btn').forEach(function (btn) {
      btn.addEventListener('click', function (evt) {
        evt.stopPropagation();
        var pid = parseInt(btn.getAttribute('data-promo-id'), 10);
        var pname = btn.getAttribute('data-promo-name') || '';
        state.view = 'roster';
        state.selectedPromoId = pid;
        state.selectedPromoName = pname;
        state.page = 1;
        state.filters = { wc: '0', gender: 'all', stage: 'all', search: '', sort_col: 'name', sort_dir: 'asc' };
        loadAndRender();
      });
    });

    // Card body click also opens roster (same as button)
    document.querySelectorAll('.ce-rival-card').forEach(function (card) {
      card.addEventListener('click', function () {
        var pid = parseInt(card.getAttribute('data-promo-id'), 10);
        var nameEl = card.querySelector('.ce-rival-card__name');
        var pname = nameEl ? nameEl.textContent : '';
        state.view = 'roster';
        state.selectedPromoId = pid;
        state.selectedPromoName = pname;
        state.page = 1;
        state.filters = { wc: '0', gender: 'all', stage: 'all', search: '', sort_col: 'name', sort_dir: 'asc' };
        loadAndRender();
      });
    });
  }

  function wireRosterEvents() {
    // Back button
    var backBtn = document.getElementById('ce-rival-back');
    if (backBtn) backBtn.addEventListener('click', function () {
      state.view = 'list';
      state.selectedPromoId = null;
      state.page = 1;
      loadAndRender();
    });

    // Filter dropdowns
    var wcSel = document.getElementById('ce-rival-wc');
    if (wcSel) wcSel.addEventListener('change', function () {
      state.filters.wc = wcSel.value;
      state.page = 1;
      loadAndRender();
    });

    var genderSel = document.getElementById('ce-rival-gender');
    if (genderSel) genderSel.addEventListener('change', function () {
      state.filters.gender = genderSel.value;
      state.page = 1;
      loadAndRender();
    });

    var stageSel = document.getElementById('ce-rival-stage');
    if (stageSel) stageSel.addEventListener('change', function () {
      state.filters.stage = stageSel.value;
      state.page = 1;
      loadAndRender();
    });

    var searchInput = document.getElementById('ce-rival-search');
    if (searchInput) searchInput.addEventListener('input', function () {
      if (state._searchTimer) clearTimeout(state._searchTimer);
      state._searchTimer = setTimeout(function () {
        state.filters.search = searchInput.value;
        state.page = 1;
        loadAndRender();
      }, 200);
    });

    var clearBtn = document.getElementById('ce-rival-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () {
      state.filters = { wc: '0', gender: 'all', stage: 'all', search: '', sort_col: 'name', sort_dir: 'asc' };
      state.page = 1;
      loadAndRender();
    });

    // Sortable headers
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

    // Name hyperlinks → Fighter Profile
    document.querySelectorAll('.ce-roster-name').forEach(function (link) {
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
        if (!p || p < 1 || p > 1000) return;
        state.page = p;
        loadAndRender();
      });
    });
  }

  // ============================================================
  // RENDER DISPATCH
  // ============================================================
  function render(view, data) {
    var host = document.getElementById('screen-content');
    if (!host) return;
    if (view === 'list') {
      host.innerHTML = renderListView(data);
      wireListEvents();
    } else {
      host.innerHTML = renderRosterView(data);
      wireRosterEvents();
    }
  }

  // ============================================================
  // PUBLIC API
  // ============================================================
  function loadAndRender() {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Scouting the competition…</div></div>';
    }

    if (state.view === 'list') {
      // Use cached list if available (back-from-roster is instant).
      if (state._rivalList) {
        render('list', state._rivalList);
        return Promise.resolve();
      }
      return window.CE.bridge.getRivalPromotions().then(function (promos) {
        if (!promos) promos = [];
        if (!Array.isArray(promos) && promos && promos.error) {
          if (host) {
            host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load rival promotions</div><div>' + escapeHtml(promos.error) + '</div></div>';
          }
          return;
        }
        state._rivalList = promos;
        render('list', promos);
      }).catch(function () {});
    }

    // Roster view
    return window.CE.bridge.getRivalRoster(state.selectedPromoId, state.page, state.filters).then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load rival roster</div><div>' + escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      if (data.weight_classes) state.weightClasses = data.weight_classes;
      if (data.promo_name) state.selectedPromoName = data.promo_name;
      render('roster', data);
    }).catch(function () {});
  }

  return { loadAndRender: loadAndRender };
})();
