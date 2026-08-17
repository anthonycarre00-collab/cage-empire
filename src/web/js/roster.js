/* ============================================================
   CAGE EMPIRE — Roster Screen Renderer ("The Stable")
   ============================================================
   Renders the player's roster into #screen-content using live data
   fetched via window.CE.bridge.getRosterData(promoId, page, filters).

   Per GUI_PLAN §6.2 + SCREEN_DATA_AUDIT §2:
     - 9-column table (sharp corners — "ledger" feel):
       Active dot | Name (hyperlink) | Age (mono) | WC (mono, upper)
       | Stage (SHORT italic) | Form (SHORT italic) | Record (mono)
       | Gym (text) | Nat (3-letter).
     - Filters: WC, Gender, Stage, Search (200ms debounce).
     - Pagination: 20 rows/page.
     - Sortable columns.
     - Row interactions: hover (gold tint), single click = select
       (gold left border), double click = Fighter Profile.
     - Active dot color: gold if champion, crimson if injured/suspended
       or on a losing streak (collapsing momentum), else neutral.

   Voice compliance:
     - Stage + Form use SHORT interpretation phrases (italic font).
     - Raw 0-100 attribute numbers are NEVER displayed.
   ============================================================ */

window.CE = window.CE || {};

window.CE.roster = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    promoId: null,
    page: 1,
    filters: { wc: '0', gender: 'all', stage: 'all', search: '', sort_col: 'name', sort_dir: 'asc' },
    selectedFighterId: null,
    weightClasses: [],
    _searchTimer: null,
    // CR-7: weight distribution gender toggle — default male.
    wcVizGender: 'male',
  };

  // ============================================================
  // HELPERS
  // ============================================================
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /** Sortable column metadata. */
  var COLUMNS = [
    { key: 'active',    label: '',         sortable: false, width: '40px' },
    { key: 'name',      label: 'Name',     sortable: true },
    { key: 'age',       label: 'Age',      sortable: true, mono: true, width: '60px' },
    { key: 'wc',        label: 'WC',       sortable: true, mono: true, width: '140px' },
    { key: 'stage',     label: 'WHERE THEY ARE',    sortable: true, italic: true },
    { key: 'form',      label: 'RIGHT NOW',     sortable: true, italic: true },
    { key: 'record',    label: 'RECORD UNDER YOU',   sortable: true, mono: true, width: '90px' },
    { key: 'gym',       label: 'TRAINING WITH',      sortable: true },
    { key: 'nat',       label: 'Nat',      sortable: false, mono: true, width: '60px' },
    // Phase 5 Task 3 — ★ Watch column. Always visible on the player's
    // roster (this module never renders rival rosters — those go
    // through rival_promotions.js). Clicking the star toggles watch
    // state in-place (no full roster re-render).
    { key: 'watch',     label: '★',        sortable: false, width: '44px', center: true },
  ];

  /** Stage filter options (career_phase labels). */
  var STAGE_OPTIONS = [
    { value: 'all', label: 'All Stages' },
    { value: 'prospect', label: 'Prospects' },
    { value: 'rising_contender', label: 'Rising Contenders' },
    { value: 'champion', label: 'Champions' },
    { value: 'gatekeeper', label: 'Gatekeepers' },
    { value: 'veteran', label: 'Veterans' },
    { value: 'declining', label: 'Declining' },
  ];

  /** Determine active-dot color from fighter state. */
  function activeDotClass(f) {
    if (f.is_champion) return 'ce-dot-gold';
    if (f.is_injured || f.is_suspended) return 'ce-dot-crimson';
    if (f.momentum_label === 'collapsing' || f.momentum_label === 'falling') return 'ce-dot-crimson';
    if (f.momentum_label === 'very_high') return 'ce-dot-gold';
    return 'ce-dot-neutral';
  }

  // ============================================================
  // RENDERERS
  // ============================================================

  function renderFilters() {
    var wcOptions = '<option value="0">All Weight Classes</option>';
    // Group weight classes by gender using <optgroup>
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
          '<select id="ce-roster-wc" class="ce-filter-select">' + wcOptions + '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">GENDER</label>' +
          '<select id="ce-roster-gender" class="ce-filter-select">' +
            '<option value="all"' + (state.filters.gender === 'all' ? ' selected' : '') + '>All</option>' +
            '<option value="male"' + (state.filters.gender === 'male' ? ' selected' : '') + '>Men</option>' +
            '<option value="female"' + (state.filters.gender === 'female' ? ' selected' : '') + '>Women</option>' +
          '</select>' +
        '</div>' +
        '<div class="ce-filter-group">' +
          '<label class="ce-filter-label">STAGE</label>' +
          '<select id="ce-roster-stage" class="ce-filter-select">' + stageOptions + '</select>' +
        '</div>' +
        '<div class="ce-filter-group ce-filter-search">' +
          '<label class="ce-filter-label">SEARCH</label>' +
          '<input type="text" id="ce-roster-search" class="ce-filter-input" placeholder="Name…" value="' + escapeHtml(state.filters.search || '') + '" />' +
        '</div>' +
        '<button id="ce-roster-clear" class="ce-btn ce-btn-ghost ce-filter-clear" type="button">Clear</button>' +
        '<div class="ce-filter-spacer"></div>' +
        '<div class="ce-filter-group ce-filter-actions">' +
          '<button id="ce-roster-view-profile" class="ce-btn ce-btn-secondary" type="button" disabled>Open Dossier</button>' +
        '</div>' +
      '</div>';
  }

  function renderTable(data) {
    var fighters = data.fighters || [];
    if (!fighters.length) {
      return '<div class="ce-empty-state">No one in your stable matches that. Try widening the lens.</div>';
    }

    // Header row
    var headerHtml = COLUMNS.map(function (col) {
      var w = col.width ? ' style="width:' + col.width + '"' : '';
      var centerCls = col.center ? ' ce-roster-th--center' : '';
      if (!col.sortable) {
        return '<th class="ce-roster-th' + centerCls + '"' + w + '>' + escapeHtml(col.label) + '</th>';
      }
      var isSorted = state.filters.sort_col === col.key;
      var sortIcon = isSorted ? (state.filters.sort_dir === 'asc' ? ' ▲' : ' ▼') : '';
      var sortClass = isSorted ? ' ce-roster-th--sorted' : '';
      return '<th class="ce-roster-th ce-roster-th--sortable' + sortClass + centerCls + '" data-sort-col="' + col.key + '"' + w + '>' +
        escapeHtml(col.label) + '<span class="ce-sort-icon">' + sortIcon + '</span></th>';
    }).join('');

    // Body rows
    var bodyHtml = fighters.map(function (f) {
      var dotClass = activeDotClass(f);
      var isSelected = state.selectedFighterId === f.fighter_id;
      var selectedClass = isSelected ? ' ce-roster-tr--selected' : '';
      var nickHtml = f.nickname ? ' <span class="ce-roster-nick">\'' + escapeHtml(f.nickname) + '\'</span>' : '';

      // Phase 5 Task 3 — ★ watch cell. The star glyph itself is the
      // click target (so the row's select/dblclick handlers don't
      // fire when toggling watch). data-watched is the source of truth
      // for in-place updates (avoids re-fetching the whole roster).
      var watched = !!f.is_watched;
      var starChar = watched ? '★' : '☆';
      var starCls = watched ? 'ce-watch-star ce-watch-star--on' : 'ce-watch-star ce-watch-star--off';
      var watchCell = '' +
        '<td class="ce-roster-td ce-roster-td--watch">' +
          '<span class="' + starCls + '" ' +
            'data-fighter-id="' + f.fighter_id + '" ' +
            'data-watched="' + (watched ? '1' : '0') + '" ' +
            'role="button" tabindex="0" ' +
            'title="' + (watched ? 'Remove from watchlist' : 'Add to watchlist') + '">' +
            starChar +
          '</span>' +
        '</td>';

      return '' +
        '<tr class="ce-roster-tr' + selectedClass + '" data-fighter-id="' + f.fighter_id + '">' +
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
          watchCell +
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

    // Numbered pages: current ±2 with ellipsis for gaps
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

  // CR-7: render the [Men's] [Women's] toggle for the weight-class viz.
  function renderWcVizToggle(gender) {
    return '' +
      '<div class="ce-wc-viz-toggle">' +
        '<button class="ce-wc-toggle-btn' + (gender === 'male' ? ' ce-wc-toggle-btn--active' : '') + '" data-gender="male" type="button">Men\'s</button>' +
        '<button class="ce-wc-toggle-btn' + (gender === 'female' ? ' ce-wc-toggle-btn--active' : '') + '" data-gender="female" type="button">Women\'s</button>' +
      '</div>';
  }

  function renderWeightClassViz(data) {
    var wcs = data.weight_classes || [];
    if (!wcs.length) return '';
    // CR-7: gender toggle — default male.
    var gender = state.wcVizGender || 'male';
    var filtered = wcs.filter(function (w) { return w.gender === gender; });
    if (!filtered.length) {
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">WEIGHT CLASS DISTRIBUTION</span></div>' +
          renderWcVizToggle(gender) +
          '<div class="ce-empty-state">No ' + (gender === 'male' ? 'men' : 'women') + ' on your roster.</div>' +
        '</div>';
    }
    var max = Math.max.apply(Math, filtered.map(function (w) { return w.count; }));
    var bars = filtered.map(function (w) {
      var pct = max > 0 ? Math.round((w.count / max) * 100) : 0;
      return '' +
        '<div class="ce-wc-bar-row">' +
          '<div class="ce-wc-bar-label">' + escapeHtml(w.name.toUpperCase()) + '</div>' +
          '<div class="ce-wc-bar-track"><div class="ce-wc-bar-fill" style="width:' + pct + '%"></div></div>' +
          '<div class="ce-wc-bar-count ce-mono">' + w.count + '</div>' +
        '</div>';
    }).join('');
    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">WEIGHT CLASS DISTRIBUTION</span></div>' +
        renderWcVizToggle(gender) +
        '<div class="ce-wc-viz">' + bars + '</div>' +
      '</div>';
  }

  function render(data) {
    var host = document.getElementById('screen-content');
    if (!host) return;

    // CR-7: promo logo in the section header (left of "THE STABLE").
    var logoHtml = data.promo_logo_b64
      ? '<img src="data:image/png;base64,' + data.promo_logo_b64 + '" class="ce-roster-promo-logo" alt="' + escapeHtml(data.promo_name || '') + '" />'
      : '';

    var html = '' +
      '<div class="ce-roster">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            logoHtml +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-title ce-sec-title-gold">THE STABLE</span>' +
            '<span class="ce-sec-sub ce-mono">' + (data.total || 0) + ' fighters under contract with you</span>' +
          '</div>' +
          renderFilters() +
          renderTable(data) +
          renderPagination(data) +
        '</div>' +
        renderWeightClassViz(data) +
      '</div>';

    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    // Filter dropdowns
    var wcSel = document.getElementById('ce-roster-wc');
    if (wcSel) wcSel.addEventListener('change', function () {
      state.filters.wc = wcSel.value;
      state.page = 1;
      loadAndRender(state.promoId);
    });

    var genderSel = document.getElementById('ce-roster-gender');
    if (genderSel) genderSel.addEventListener('change', function () {
      state.filters.gender = genderSel.value;
      state.page = 1;
      loadAndRender(state.promoId);
    });

    var stageSel = document.getElementById('ce-roster-stage');
    if (stageSel) stageSel.addEventListener('change', function () {
      state.filters.stage = stageSel.value;
      state.page = 1;
      loadAndRender(state.promoId);
    });

    // Search (200ms debounce)
    var searchInput = document.getElementById('ce-roster-search');
    if (searchInput) searchInput.addEventListener('input', function () {
      if (state._searchTimer) clearTimeout(state._searchTimer);
      state._searchTimer = setTimeout(function () {
        state.filters.search = searchInput.value;
        state.page = 1;
        loadAndRender(state.promoId);
      }, 200);
    });

    // Clear button
    var clearBtn = document.getElementById('ce-roster-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () {
      state.filters = { wc: '0', gender: 'all', stage: 'all', search: '', sort_col: 'name', sort_dir: 'asc' };
      state.page = 1;
      loadAndRender(state.promoId);
    });

    // Sortable column headers
    document.querySelectorAll('.ce-roster-th--sortable').forEach(function (th) {
      th.addEventListener('click', function () {
        var col = th.getAttribute('data-sort-col');
        if (state.filters.sort_col === col) {
          state.filters.sort_dir = state.filters.sort_dir === 'asc' ? 'desc' : 'asc';
        } else {
          state.filters.sort_col = col;
          state.filters.sort_dir = 'asc';
        }
        loadAndRender(state.promoId);
      });
    });

    // CR-7: weight distribution gender toggle.
    // Re-renders the whole screen (state already cached, fetch is fast).
    document.querySelectorAll('.ce-wc-toggle-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var g = btn.getAttribute('data-gender');
        if (g === state.wcVizGender) return;
        state.wcVizGender = g;
        loadAndRender(state.promoId);
      });
    });

    // Row interactions: single click = select, double click = profile
    document.querySelectorAll('.ce-roster-tr').forEach(function (tr) {
      tr.addEventListener('click', function (evt) {
        // Don't fire row-select when clicking the name hyperlink OR
        // the ★ watch star (Phase 5 Task 3) — the watch star has its
        // own click handler that calls stopPropagation, but the name
        // hyperlink's check below is the original safeguard.
        if (evt.target.closest('.ce-roster-name')) return;
        if (evt.target.closest('.ce-watch-star')) return;
        var fid = parseInt(tr.getAttribute('data-fighter-id'), 10);
        state.selectedFighterId = fid;
        // Update selected class without re-render
        document.querySelectorAll('.ce-roster-tr').forEach(function (r) {
          r.classList.toggle('ce-roster-tr--selected', parseInt(r.getAttribute('data-fighter-id'), 10) === fid);
        });
        var vpBtn = document.getElementById('ce-roster-view-profile');
        if (vpBtn) vpBtn.disabled = false;
      });
      tr.addEventListener('dblclick', function (evt) {
        if (evt.target.closest('.ce-roster-name')) return;
        if (evt.target.closest('.ce-watch-star')) return;
        var fid = parseInt(tr.getAttribute('data-fighter-id'), 10);
        window.CE.app.navigate('fighter_profile', { fighter_id: fid });
      });
    });

    // Phase 5 Task 3 — ★ watch star click handler. Toggles watch state
    // via the bridge + updates just the clicked cell in-place (no
    // full roster re-render, per spec). stopPropagation prevents the
    // row's select / dblclick handlers from also firing.
    document.querySelectorAll('.ce-watch-star').forEach(function (star) {
      function toggleWatch(evt) {
        evt.preventDefault();
        evt.stopPropagation();
        var fid = parseInt(star.getAttribute('data-fighter-id'), 10);
        if (!fid) return;
        var currentlyWatched = star.getAttribute('data-watched') === '1';
        // Grey-out the star while the request is in-flight + use a
        // local "busy" flag so double-clicks don't double-fire.
        if (star.getAttribute('data-busy') === '1') return;
        star.setAttribute('data-busy', '1');
        star.style.opacity = '0.5';
        var bridgeCall = currentlyWatched
          ? window.CE.bridge.removeFromWatchlist(fid)
          : window.CE.bridge.addToWatchlist(fid);
        bridgeCall.then(function (result) {
          if (result && result.ok) {
            var nowWatched = !currentlyWatched;
            star.setAttribute('data-watched', nowWatched ? '1' : '0');
            star.classList.toggle('ce-watch-star--on', nowWatched);
            star.classList.toggle('ce-watch-star--off', !nowWatched);
            star.textContent = nowWatched ? '★' : '☆';
            star.title = nowWatched ? 'Remove from watchlist' : 'Add to watchlist';
            showRosterToast(nowWatched ? 'Added to watchlist.' : 'Removed from watchlist.', 'success');
          } else {
            showRosterToast(
              'Watchlist: ' + (result && result.error ? result.error : 'unknown error'),
              'error'
            );
          }
          star.style.opacity = '';
          star.setAttribute('data-busy', '0');
        }).catch(function (err) {
          showRosterToast('Watchlist: ' + err, 'error');
          star.style.opacity = '';
          star.setAttribute('data-busy', '0');
        });
      }
      star.addEventListener('click', toggleWatch);
      // Keyboard accessibility — Enter / Space toggles too.
      star.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' || evt.key === ' ' || evt.key === 'Spacebar') {
          evt.preventDefault();
          toggleWatch(evt);
        }
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
        loadAndRender(state.promoId);
      });
    });

    // View Profile button
    var vpBtn = document.getElementById('ce-roster-view-profile');
    if (vpBtn) vpBtn.addEventListener('click', function () {
      if (state.selectedFighterId) {
        window.CE.app.navigate('fighter_profile', { fighter_id: state.selectedFighterId });
      }
    });
  }

  // ============================================================
  // PUBLIC API
  // ============================================================

  // Phase 5 Task 3 — minimal toast helper (mirrors the pattern in
  // fighter_profile.js's showProfileToast). Used to confirm ★ watch
  // toggles without leaving the roster screen.
  function showRosterToast(msg, kind) {
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
    }, 3500);
  }

  function loadAndRender(promoId) {
    state.promoId = promoId;
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Reading the stable…</div></div>';
    }
    return window.CE.bridge.getRosterData(promoId, state.page, state.filters).then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load roster</div><div>' + escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      // Cache weight class list for filter dropdown
      if (data.weight_classes) state.weightClasses = data.weight_classes;
      render(data);
    });
  }

  return {
    loadAndRender: loadAndRender,
    render: render,
  };
})();
