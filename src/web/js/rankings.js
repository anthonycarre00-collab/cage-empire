/* ============================================================
   CAGE EMPIRE — The Rankings Screen ("THE RANKINGS")
   ============================================================
   Phase INFO-SCREENS-BATCH-1 §3. Replaces the placeholder
   Rankings nav item. Renders the player's promo's divisional
   top 15 — the matchmaking context the player needs.

   What the player sees:
     - Section header: "THE RANKINGS" (gold accent) + subtitle
       "The divisional picture".
     - Filter bar: weight-class dropdown (grouped by Men's /
       Women's optgroups) + gender toggle.
     - Champion strip (if a champ exists): name, reign length,
       defense count, clickable → Fighter Profile.
     - Rankings table: rank # (with ▲▼→ rank-change symbol),
       fighter name (clickable → Fighter Profile), record (mono),
       streak (mono), momentum phrase (italic), title chip if
       champion, last-fight date.
     - Voice empty state: "No rankings data for this division
       yet."

   Voice compliance (CONVENTIONS §14 + REWARD_REVIEW §1.1):
     - NEVER show rankings.rating (ELO float) — only rank #.
     - Momentum comes from fighter_descriptors (SHORT phrase).
     - Rank change is derived from last fight outcome (▲ win,
       ▼ loss, → draw/no fight).
     - No raw potential/ceiling numbers — only voice phrases.
   ============================================================ */

window.CE = window.CE || {};

window.CE.rankings = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    weightClassId: null,
    gender: 'male',
    promoFilter: 'mine',  // P4.4 — 'mine' | 'all'
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
    var parts = dateStr.split('-');
    if (parts.length !== 3) return dateStr;
    return parts[1] + '/' + parts[2] + '/' + parts[0];
  }

  /** Rank-change → CSS color class. */
  function rankChangeClass(change) {
    if (change === 'up') return 'ce-rankings__change--up';
    if (change === 'down') return 'ce-rankings__change--down';
    if (change === 'new') return 'ce-rankings__change--new';
    return 'ce-rankings__change--flat';
  }

  /** Momentum label → row accent color (matches dashboard.js MOMENTUM_RING). */
  var MOMENTUM_COLORS = {
    very_high:  'var(--green)',
    high:       'var(--gold)',
    stable:     'var(--text-secondary)',
    falling:    'var(--crimson)',
    collapsing: 'var(--danger)',
  };
  function momentumColor(label) {
    return MOMENTUM_COLORS[label] || 'var(--text-secondary)';
  }

  // ============================================================
  // RENDER — FILTER BAR
  // ============================================================
  function renderFilterBar() {
    var wcs = (state.data && state.data.weight_classes) || [];
    // Group by gender for optgroups.
    var maleWcs = wcs.filter(function (w) { return w.gender === 'male'; });
    var femaleWcs = wcs.filter(function (w) { return w.gender === 'female'; });

    function optgroup(label, list) {
      if (!list.length) return '';
      var opts = list.map(function (w) {
        var sel = (state.weightClassId === w.weight_class_id) ? ' selected' : '';
        return '<option value="' + w.weight_class_id + '"' + sel + '>' +
          escapeHtml(w.name) + '</option>';
      }).join('');
      return '<optgroup label="' + escapeHtml(label) + '">' + opts + '</optgroup>';
    }

    var selectHtml = optgroup("Men's", maleWcs) + optgroup("Women's", femaleWcs);

    var activeGender = (state.data && state.data.gender) || state.gender;
    // P4.4 — promo scope toggle (My Promotion | All Promotions).
    var activePf = (state.data && state.data.promo_filter) || state.promoFilter;

    return '' +
      '<div class="ce-rankings__filter-bar">' +
        '<div class="ce-rankings__filter-group">' +
          '<label class="ce-rankings__filter-label" for="ce-rankings-wc">WEIGHT CLASS</label>' +
          '<select id="ce-rankings-wc" class="ce-rankings__select">' + selectHtml + '</select>' +
        '</div>' +
        '<div class="ce-rankings__filter-group">' +
          '<label class="ce-rankings__filter-label">DIVISION</label>' +
          '<div class="ce-rankings__gender-toggle">' +
            '<button type="button" id="ce-rankings-male" class="ce-rankings__gender-btn' +
              (activeGender === 'male' ? ' ce-rankings__gender-btn--active' : '') +
              '">Men\'s</button>' +
            '<button type="button" id="ce-rankings-female" class="ce-rankings__gender-btn' +
              (activeGender === 'female' ? ' ce-rankings__gender-btn--active' : '') +
              '">Women\'s</button>' +
          '</div>' +
        '</div>' +
        '<div class="ce-rankings__filter-group">' +
          '<label class="ce-rankings__filter-label">SCOPE</label>' +
          '<div class="ce-rankings__promo-toggle">' +
            '<button type="button" id="ce-rankings-mine" class="ce-rankings__promo-btn' +
              (activePf === 'mine' ? ' ce-rankings__promo-btn--active' : '') +
              '">My Promotion</button>' +
            '<button type="button" id="ce-rankings-all" class="ce-rankings__promo-btn' +
              (activePf === 'all' ? ' ce-rankings__promo-btn--active' : '') +
              '">All Promotions</button>' +
          '</div>' +
        '</div>' +
        '<div class="ce-rankings__filter-info">' +
          '<span class="ce-rankings__wc-name">' +
            escapeHtml((state.data && state.data.weight_class_name) || '—') +
          '</span>' +
          '<span class="ce-rankings__promo-name">' +
            escapeHtml((state.data && state.data.player_promo_name) || 'Your Promotion') +
          '</span>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — CHAMPION STRIP
  // ============================================================
  function renderChampion() {
    var champ = state.data && state.data.champion;
    if (!champ) return '';
    var nickHtml = champ.nickname
      ? '<span class="ce-rankings__champ-nick">\'' + escapeHtml(champ.nickname) + '\'</span>'
      : '';
    return '' +
      '<div class="ce-rankings__champion">' +
        '<div class="ce-rankings__champ-crown">🥇</div>' +
        '<div class="ce-rankings__champ-info">' +
          '<div class="ce-rankings__champ-label">CHAMPION</div>' +
          '<a class="ce-rankings__champ-name ce-link" href="#" data-fighter-id="' +
            champ.fighter_id + '">' + escapeHtml(champ.name) + '</a>' +
          nickHtml +
          '<div class="ce-rankings__champ-meta">' +
            '<span class="ce-rankings__champ-reign">reigning for ' +
              escapeHtml(champ.reign_length) + '</span>' +
            '<span class="ce-rankings__sep">·</span>' +
            '<span class="ce-rankings__champ-defs">' +
              champ.title_defenses_count + ' defense' +
              (champ.title_defenses_count === 1 ? '' : 's') + '</span>' +
            '<span class="ce-rankings__sep">·</span>' +
            '<span class="ce-rankings__champ-reigns">' +
              champ.title_reigns_count + ' reign' +
              (champ.title_reigns_count === 1 ? '' : 's') + '</span>' +
          '</div>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — RANKINGS TABLE
  // ============================================================
  function renderTable() {
    var rankings = (state.data && state.data.rankings) || [];
    if (!rankings.length) {
      return '' +
        '<div class="ce-rankings__empty">' +
          '<div class="ce-rankings__empty-title">No rankings data for this division yet.</div>' +
          '<div class="ce-rankings__empty-body">Run a card. Once the division has fights, the contenders will appear.</div>' +
        '</div>';
    }

    // P4.4 — when promo_filter='all', add a CONTRACTED TO column.
    // In 'mine' mode the column is redundant (everyone's contracted to
    // the player's promo) so we hide it for noise reduction.
    var showContracted = (state.data && state.data.promo_filter) === 'all';

    var rows = rankings.map(function (r) {
      var rankCls = 'ce-rankings__rank';
      if (r.rank === 1) rankCls += ' ce-rankings__rank--top';
      else if (r.rank <= 3) rankCls += ' ce-rankings__rank--elite';
      else if (r.rank <= 5) rankCls += ' ce-rankings__rank--contender';

      var changeCls = rankChangeClass(r.rank_change);
      var momColor = momentumColor(r.momentum_label);
      // P4.4 — emphasize the player's promo's fighters in 'all' mode
      // (gold-tinted name so the player can spot their own roster at
      // a glance among the cross-promo pool).
      var nameCls = 'ce-link ce-rankings__name' +
        (showContracted && r.is_player_promo_fighter
          ? ' ce-rankings__name--player-promo' : '');
      var nameHtml = '<a class="' + nameCls + '" href="#" ' +
        'data-fighter-id="' + r.fighter_id + '">' + escapeHtml(r.name) + '</a>';
      if (r.nickname) {
        nameHtml += '<span class="ce-rankings__nick"> \'' +
          escapeHtml(r.nickname) + '\'</span>';
      }
      var titleChip = r.is_champion
        ? '<span class="ce-chip ce-chip-gold ce-rankings__title-chip">CHAMP</span>'
        : '';
      var streakHtml = r.streak_display
        ? '<span class="ce-rankings__streak ce-rankings__streak--' +
          (r.streak_display.indexOf('W') >= 0 ? 'win' : 'loss') + '">' +
          r.streak_display + '</span>'
        : '<span class="ce-rankings__streak ce-rankings__streak--none">—</span>';
      var contractedCell = showContracted
        ? '<td class="ce-rankings__contracted' +
            (r.is_player_promo_fighter ? ' ce-rankings__contracted--player' : '') +
            '">' + escapeHtml(r.contracted_to || '—') + '</td>'
        : '';

      return '' +
        '<tr class="ce-rankings__row' + (r.is_champion ? ' ce-rankings__row--champ' : '') + '">' +
          '<td class="' + rankCls + '">' +
            '<span class="ce-rankings__rank-num">#' + r.rank + '</span>' +
            '<span class="ce-rankings__change ' + changeCls + '" title="' +
              escapeHtml(r.rank_change_phrase) + '">' + r.rank_change_symbol + '</span>' +
          '</td>' +
          '<td class="ce-rankings__name-cell">' +
            '<div class="ce-rankings__name-row">' + nameHtml + titleChip + '</div>' +
            '<div class="ce-rankings__phase">' +
              (r.career_phase_short ? escapeHtml(r.career_phase_short) : '') +
            '</div>' +
          '</td>' +
          '<td class="ce-rankings__record">' + escapeHtml(r.record_display) + '</td>' +
          '<td class="ce-rankings__streak-cell">' + streakHtml + '</td>' +
          '<td class="ce-rankings__momentum" style="color:' + momColor + ';">' +
            escapeHtml(r.momentum_phrase || '—') +
          '</td>' +
          contractedCell +
          '<td class="ce-rankings__last">' + escapeHtml(formatDate(r.last_fight_date)) + '</td>' +
        '</tr>';
    }).join('');

    var contractedTh = showContracted
      ? '<th class="ce-rankings__th ce-rankings__th--contracted">CONTRACTED TO</th>'
      : '';

    return '' +
      '<div class="ce-rankings__table-wrap">' +
        '<table class="ce-rankings__table' + (showContracted ? ' ce-rankings__table--wide' : '') + '">' +
          '<thead>' +
            '<tr>' +
              '<th class="ce-rankings__th ce-rankings__th--rank">RANK</th>' +
              '<th class="ce-rankings__th ce-rankings__th--name">FIGHTER</th>' +
              '<th class="ce-rankings__th ce-rankings__th--record">RECORD</th>' +
              '<th class="ce-rankings__th ce-rankings__th--streak">STREAK</th>' +
              '<th class="ce-rankings__th ce-rankings__th--momentum">MOMENTUM</th>' +
              contractedTh +
              '<th class="ce-rankings__th ce-rankings__th--last">LAST FIGHT</th>' +
            '</tr>' +
          '</thead>' +
          '<tbody>' + rows + '</tbody>' +
        '</table>' +
      '</div>';
  }

  // ============================================================
  // MAIN RENDER
  // ============================================================
  function render() {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var html = '' +
      '<div class="ce-rankings">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">📊</span>' +
            '<span class="ce-sec-title ce-sec-title-gold">THE RANKINGS</span>' +
            '<span class="ce-sec-sub ce-mono">the divisional picture</span>' +
          '</div>' +
        '</div>' +
        renderFilterBar() +
        renderChampion() +
        renderTable() +
      '</div>';
    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    var wcSel = document.getElementById('ce-rankings-wc');
    if (wcSel) wcSel.addEventListener('change', function () {
      state.weightClassId = parseInt(wcSel.value, 10);
      // Update gender toggle to match the selected WC's gender.
      var wcs = (state.data && state.data.weight_classes) || [];
      for (var i = 0; i < wcs.length; i++) {
        if (wcs[i].weight_class_id === state.weightClassId) {
          state.gender = wcs[i].gender;
          break;
        }
      }
      loadAndRender();
    });

    var maleBtn = document.getElementById('ce-rankings-male');
    if (maleBtn) maleBtn.addEventListener('click', function () {
      state.gender = 'male';
      state.weightClassId = null;  // let server pick the first male WC
      loadAndRender();
    });
    var femaleBtn = document.getElementById('ce-rankings-female');
    if (femaleBtn) femaleBtn.addEventListener('click', function () {
      state.gender = 'female';
      state.weightClassId = null;  // let server pick the first female WC
      loadAndRender();
    });

    // P4.4 — My Promotion / All Promotions scope toggle.
    var mineBtn = document.getElementById('ce-rankings-mine');
    if (mineBtn) mineBtn.addEventListener('click', function () {
      state.promoFilter = 'mine';
      loadAndRender();
    });
    var allBtn = document.getElementById('ce-rankings-all');
    if (allBtn) allBtn.addEventListener('click', function () {
      state.promoFilter = 'all';
      loadAndRender();
    });

    // Fighter-name hyperlinks → Fighter Profile.
    document.querySelectorAll('.ce-rankings__name[data-fighter-id], .ce-rankings__champ-name[data-fighter-id]').forEach(function (link) {
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
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Computing the rankings…</div></div>';
    }
    return window.CE.bridge.getRankingsData(state.weightClassId, state.gender, state.promoFilter).then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load rankings</div><div>' +
            escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      state.data = data;
      // Keep state.weightClassId in sync with what the server picked
      // (so the dropdown shows the right selection).
      state.weightClassId = data.weight_class_id;
      state.gender = data.gender;
      // P4.4 — echo back the server-normalized promo_filter so the
      // toggle stays in sync.
      state.promoFilter = data.promo_filter || state.promoFilter;
      render();
    }).catch(function (err) {
      console.error('[rankings] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load rankings</div><div>' +
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
