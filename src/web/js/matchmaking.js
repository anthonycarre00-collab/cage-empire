/* ============================================================
   CAGE EMPIRE — Matchmaking V2 ("The Heartbeat")
   ============================================================
   Per docs/MASTER_PLAN_MATCHMAKING_V2.md (MM1.1–MM1.6).

   TWO-ROW LAYOUT (BIG and BOLD):
     TOP ROW    : MATCHUP ZONE — Red Corner | VS strip | Blue Corner
                  (the decision zone — dominates the screen).
     BOTTOM ROW : CARD LIST (60%) + STATUS PANEL (40%)
                  - card list shows staged/booked fights as BIG drag-
                    drop cards (80px+ tall, slot labels: MAIN EVENT /
                    CO-MAIN / PRELIM 1 / PRELIM 2 / …).
                  - status panel shows "Confirm card to see projected
                    revenue" during build, OR the full projection
                    after the card is confirmed.

   CARD CONFIRMATION FLOW (MM1.4):
     1. Player picks Red Corner + Blue Corner via the roster browser
        overlay (no DB writes).
     2. Player clicks ADD TO CARD → fight is staged in JS memory
        (state.stagedFights). No DB write yet.
     3. Player can add/remove/reorder staged fights freely.
     4. Player clicks CONFIRM CARD → bridge.confirmCard writes all
        fights to DB in one transaction + returns the projection.
     5. After confirmation, the card is LOCKED (gold border). Player
        can RE-OPEN CARD to wipe + go back to build mode.

   "MIGHT" ADVICE (MM1.3 — NO definitive predictions):
     - The Compare modal shows the radar chart + 3 might-framed
       voice phrases (style_matchup_phrase, early_read_phrase,
       excitement_phrase) + the matchup_phrase chip (voice tier
       ONLY — no raw 73/100 score).
     - NO "Predicted Winner" cell, NO "Predicted Method" cell, NO
       "Confidence" cell, NO "Upset Risk" line.

   FIGHTER INFO (MM1.2 — 9 fields in each corner slot):
     1. Portrait (120×120)
     2. Name + nickname (18px)
     3. Rank chip (gold if champion, silver if top-5, steel else)
     4. Title chip (🥇 LW Champion or —)
     5. Popularity tier label (Cult Hero / Rising Star / Mid Level / Unknown)
     6. Momentum indicator (▲/▼/→ + streak number)
     7. Record + WC + age + style (single dense line)
     8. Rivalry indicator (⚔ RIVALRY chip on the VS strip, pulsing)
     9. Recent form (last 5 fights as W/L/D chips)
   ============================================================ */

window.CE = window.CE || {};

window.CE.matchmaking = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    eventId: null,
    event: null,
    promo: null,
    eligibleFighters: [],
    rivalryPartnerIds: {},        // fighter_id -> {heat, type, label}
    bookedFights: [],             // from DB (legacy or post-confirm)
    cardConfirmed: false,
    stagedFights: [],             // JS-staged fights during build
    cardPreview: null,
    lastProjection: null,         // full projection (after confirm)
    // Corner selection
    redCorner: null,              // fighter brief
    blueCorner: null,             // fighter brief
    // Roster browser overlay
    rosterOpen: false,
    rosterCorner: null,           // 'red' | 'blue'
    rosterFilter: 'all',
    rosterSearch: '',
    // Portraits cache (fighter_id -> data_uri)
    portraitCache: {},
    // Drag-drop state
    _draggedStagedIdx: null,
    _dragOverIdx: null,
    // P5.1 — Booking Adviser state.
    suggestedMatchups: [],       // [{red_fighter, blue_fighter, reason_chip, reason_phrase, quality_phrase}]
    suggestionsOpen: true,       // collapsible panel — open by default
    suggestionsLoading: false,
  };

  // ============================================================
  // HELPERS
  // ============================================================
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function fmtCash(n) {
    n = Number(n || 0);
    var neg = n < 0;
    var abs = Math.abs(n);
    var s;
    if (abs >= 1e9) s = '$' + (abs / 1e9).toFixed(2) + 'B';
    else if (abs >= 1e6) s = '$' + (abs / 1e6).toFixed(1) + 'M';
    else if (abs >= 1e3) s = '$' + (abs / 1e3).toFixed(0) + 'K';
    else s = '$' + Math.round(abs).toLocaleString();
    return (neg ? '-' : '') + s;
  }

  function fighterInitials(name) {
    if (!name) return '?';
    var parts = name.split(' ').filter(function (p) { return p; });
    if (parts.length === 0) return '?';
    if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
    return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
  }

  function slotLabel(slot, idx) {
    if (slot === 'main_event') return 'MAIN EVENT';
    if (slot === 'co_main') return 'CO-MAIN';
    if (slot === 'featured_prelim') return 'FEATURED PRELIM';
    if (slot === 'prelim') {
      // For prelims, show "PRELIM N" where N is the index (3rd fight onwards).
      return 'PRELIM ' + (idx - 1);
    }
    if (slot === 'opener') return 'OPENER';
    return String(slot || '').toUpperCase();
  }

  function slotClass(slot) {
    if (slot === 'main_event') return 'ce-mm-fight-card-v2--main-event';
    if (slot === 'co_main') return 'ce-mm-fight-card-v2--co-main';
    return '';
  }

  function slotSlotClass(slot) {
    if (slot === 'main_event') return 'ce-mm-fight-card-v2__slot--main-event';
    if (slot === 'co_main') return 'ce-mm-fight-card-v2__slot--co-main';
    return 'ce-mm-fight-card-v2__slot--prelim';
  }

  function autoCardSlot(idx) {
    if (idx === 0) return 'main_event';
    if (idx === 1) return 'co_main';
    if (idx <= 3) return 'featured_prelim';
    return 'prelim';
  }

  function rankChipClass(rank_num, holds_title) {
    if (holds_title) return 'ce-mm-chip-v2--rank-champion';
    if (rank_num && rank_num >= 1 && rank_num <= 5) {
      return 'ce-mm-chip-v2--rank-top5';
    }
    return 'ce-mm-chip-v2--rank-steel';
  }

  function rankLabel(rank_str, weight_class_short, holds_title) {
    if (holds_title) {
      return '🥇 ' + (weight_class_short || '') + ' CHAMP';
    }
    if (!rank_str || rank_str === 'Unranked') {
      return (weight_class_short || '—') + ' unranked';
    }
    return rank_str + ' ' + (weight_class_short || '');
  }

  function momentumChipClass(momentum_label) {
    if (!momentum_label) return 'ce-mm-chip-v2--momentum-flat';
    if (momentum_label.color === 'hot') return 'ce-mm-chip-v2--momentum-hot';
    if (momentum_label.color === 'cold') return 'ce-mm-chip-v2--momentum-cold';
    return 'ce-mm-chip-v2--momentum-flat';
  }

  function momentumLabel(momentum_label) {
    if (!momentum_label) return '';
    var s = momentum_label.arrow + ' ' + momentum_label.label;
    if (momentum_label.streak_str) s += ' · ' + momentum_label.streak_str;
    return s;
  }

  function popularityChipClass(tier) {
    if (tier === 'Cult Hero') return 'ce-mm-chip-v2--popularity-cult';
    return 'ce-mm-chip-v2--popularity';
  }

  // ============================================================
  // PORTRAIT FETCHING (lazy, cached)
  // ============================================================
  function fetchPortrait(fighterId, callback) {
    if (!fighterId) { callback(null); return; }
    if (state.portraitCache[fighterId] !== undefined) {
      callback(state.portraitCache[fighterId]);
      return;
    }
    window.CE.bridge.getFighterPortrait(fighterId).then(function (result) {
      var uri = (result && result.has_portrait) ? result.data_uri : null;
      state.portraitCache[fighterId] = uri;
      callback(uri);
    }).catch(function () {
      state.portraitCache[fighterId] = null;
      callback(null);
    });
  }

  function portraitBgStyle(fighterId) {
    var cached = state.portraitCache[fighterId];
    if (cached) {
      return ' style="background-image:url(\'' + cached + '\')"';
    }
    return '';
  }

  function portraitInner(fighter, fallbackName) {
    var fid = fighter ? fighter.fighter_id : null;
    if (state.portraitCache[fid]) return '';
    return escapeHtml(fighterInitials(fallbackName || (fighter && fighter.name)));
  }

  // ============================================================
  // RENDER — EVENT STRIP
  // ============================================================
  function renderEventStrip() {
    var ev = state.event;
    if (!ev) return '';
    var p = state.promo || {};
    var statusBadge = state.cardConfirmed
      ? '<span class="ce-mm-v2__status-badge ce-mm-v2__status-badge--confirmed">CARD CONFIRMED</span>'
      : '<span class="ce-mm-v2__status-badge ce-mm-v2__status-badge--building">BUILDING CARD</span>';
    return '' +
      '<div class="ce-mm-v2__event-strip">' +
        '<div>' +
          '<div class="ce-mm-v2__event-name">' + escapeHtml(ev.event_name || 'Event') + '</div>' +
          '<div class="ce-mm-v2__event-meta">' + escapeHtml(ev.event_date || '') + ' · ' +
            escapeHtml(ev.venue_name || '') + ' · ' +
            (ev.venue_capacity || 0).toLocaleString() + ' seats</div>' +
        '</div>' +
        '<div class="ce-mm-v2__event-levers">' +
          statusBadge +
          '<span class="ce-mm-v2__lever-chip">Ticket <strong>$' + (ev.ticket_price || 80) + '</strong></span>' +
          '<span class="ce-mm-v2__lever-chip">Mkt <strong>' + escapeHtml(fmtCash(ev.marketing_spend || 0)) + '</strong></span>' +
          (ev.is_ppv ? '<span class="ce-mm-v2__lever-chip">PPV <strong>$' + (ev.ppv_price || 60) + '</strong></span>' : '') +
          '<span class="ce-mm-v2__lever-chip">Cash <strong>' + escapeHtml(p.cash_display || '') + '</strong></span>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — MATCHUP ZONE (top row, 55% height)
  // ============================================================
  function renderCornerSlot(corner) {
    var fighter = corner === 'red' ? state.redCorner : state.blueCorner;
    var cornerClass = 'ce-mm-corner-v2 ce-mm-corner-v2--' + corner;
    if (fighter) cornerClass += ' ce-mm-corner-v2--filled';
    var label = corner === 'red' ? 'RED CORNER' : 'BLUE CORNER';

    if (!fighter) {
      return '<div class="' + cornerClass + '">' +
        '<div class="ce-mm-corner-v2__header">' +
          '<span class="ce-mm-corner-v2__label">' + label + '</span>' +
        '</div>' +
        '<div class="ce-mm-corner-v2__empty">' +
          '<div class="ce-mm-corner-v2__empty-icon">⚔</div>' +
          '<div class="ce-mm-corner-v2__empty-text">No fighter picked.</div>' +
          '<button class="ce-mm-corner-v2__pick-btn" data-pick-corner="' + corner + '" type="button">' +
            'Pick ' + (corner === 'red' ? 'Red' : 'Blue') + ' Corner' +
          '</button>' +
        '</div>' +
      '</div>';
    }

    var fid = fighter.fighter_id;
    var rankCls = rankChipClass(fighter.rank_num, fighter.title_chip && fighter.title_chip.holds_title);
    var rankLbl = rankLabel(fighter.rank_str, fighter.weight_class_short, fighter.title_chip && fighter.title_chip.holds_title);
    var titleChip = (fighter.title_chip && fighter.title_chip.holds_title)
      ? '<span class="ce-mm-chip-v2 ce-mm-chip-v2--title">🥇 ' + escapeHtml(fighter.title_chip.title_label) + '</span>'
      : '<span class="ce-mm-chip-v2 ce-mm-chip-v2--title-none">— No Title</span>';
    var popChip = '<span class="ce-mm-chip-v2 ' + popularityChipClass(fighter.popularity_tier) + '">' +
      escapeHtml(fighter.popularity_tier || 'Unknown') + '</span>';
    var momCls = momentumChipClass(fighter.momentum_label);
    var momLbl = momentumLabel(fighter.momentum_label);
    var momChip = '<span class="ce-mm-chip-v2 ' + momCls + '">' + escapeHtml(momLbl) + '</span>';
    var rankChip = '<span class="ce-mm-chip-v2 ' + rankCls + '">' + escapeHtml(rankLbl) + '</span>';

    // Dense info line: record · WC · age · style
    var infoLine = '<div class="ce-mm-corner-v2__info-line">' +
      '<strong>' + escapeHtml(fighter.record_str || '0-0') + '</strong> · ' +
      escapeHtml(fighter.weight_class_short || fighter.weight_class_name || '—') + ' · ' +
      (fighter.age !== null && fighter.age !== undefined ? fighter.age + 'y' : '—') + ' · ' +
      '<strong>' + escapeHtml(fighter.style_archetype_name || 'Balanced') + '</strong>' +
    '</div>';

    // Recent form (last 5 W/L/D chips)
    var formHtml = '<div class="ce-mm-corner-v2__form">' +
      '<span class="ce-mm-corner-v2__form-label">Form</span>';
    if (fighter.recent_form && fighter.recent_form.length) {
      fighter.recent_form.forEach(function (b) {
        formHtml += '<div class="ce-mm-form-chip ce-mm-form-chip--' + b.letter + '">' + b.letter + '</div>';
      });
    } else {
      formHtml += '<span class="ce-mm-form-empty">No pro fights</span>';
    }
    formHtml += '</div>';

    // Portrait (120×120)
    var portraitStyle = portraitBgStyle(fid);
    var portraitHtml = '<div class="ce-mm-corner-v2__portrait"' + portraitStyle + '>' +
      portraitInner(fighter, fighter.name) + '</div>';

    // Name + nickname
    var nameHtml = '<div class="ce-mm-corner-v2__name">' + escapeHtml(fighter.name || '') + '</div>';
    var nickHtml = fighter.nickname
      ? '<div class="ce-mm-corner-v2__nickname">"' + escapeHtml(fighter.nickname) + '"</div>'
      : '';

    return '<div class="' + cornerClass + '">' +
      '<div class="ce-mm-corner-v2__header">' +
        '<span class="ce-mm-corner-v2__label">' + label + '</span>' +
        '<button class="ce-mm-corner-v2__clear" data-clear-corner="' + corner + '" type="button" title="Clear corner" aria-label="Clear ' + corner + ' corner">×</button>' +
      '</div>' +
      portraitHtml +
      nameHtml +
      nickHtml +
      '<div class="ce-mm-corner-v2__chips">' + rankChip + titleChip + popChip + momChip + '</div>' +
      infoLine +
      formHtml +
    '</div>';
  }

  function renderVsStrip() {
    var rivalry = null;
    if (state.redCorner && state.blueCorner) {
      var blueId = state.blueCorner.fighter_id;
      // Check if blue is in the rivalry partner list for red.
      if (state.rivalryPartnerIds[blueId]) {
        rivalry = state.rivalryPartnerIds[blueId];
      }
    }
    var rivalryHtml = '';
    if (rivalry) {
      rivalryHtml = '<div class="ce-mm-vs-strip__rivalry">' +
        '<div class="ce-mm-vs-strip__rivalry-icon">⚔</div>' +
        '<div class="ce-mm-vs-strip__rivalry-label">RIVALRY</div>' +
        '<div class="ce-mm-vs-strip__rivalry-sub">' + escapeHtml(rivalry.label || 'Heat ' + rivalry.heat) + '</div>' +
      '</div>';
    }
    return '<div class="ce-mm-vs-strip">' +
      '<div class="ce-mm-vs-strip__vs">VS</div>' +
      rivalryHtml +
    '</div>';
  }

  function renderMatchupZone() {
    var canAdd = state.redCorner && state.blueCorner &&
      state.redCorner.fighter_id !== state.blueCorner.fighter_id;
    if (canAdd && state.redCorner.weight_class_id !== state.blueCorner.weight_class_id) {
      canAdd = false;
    }
    if (canAdd && state.redCorner.gender !== state.blueCorner.gender) {
      canAdd = false;
    }
    return '<div class="ce-mm-v2__matchup-zone">' +
      renderCornerSlot('red') +
      renderVsStrip() +
      renderCornerSlot('blue') +
    '</div>' +
    '<div class="ce-mm-v2__action-bar">' +
      (state.cardConfirmed
        ? '<button class="ce-mm-action-btn ce-mm-action-btn--ghost" data-reopen-card type="button">Re-open Card</button>'
        : '<button class="ce-mm-action-btn ce-mm-action-btn--primary" data-add-to-card type="button"' +
          (canAdd ? '' : ' disabled') + '>＋ Add to Card</button>') +
    '</div>';
  }

  // ============================================================
  // RENDER — CARD LIST (bottom left, 60%)
  // ============================================================
  function renderCardList() {
    var fights = state.cardConfirmed ? state.bookedFights : state.stagedFights;
    var headerTitle = state.cardConfirmed ? 'CONFIRMED CARD' : 'STAGED CARD';
    var countStr = fights.length + ' fight' + (fights.length !== 1 ? 's' : '');

    if (!fights.length) {
      return '<div class="ce-mm-card-list-v2">' +
        '<div class="ce-mm-card-list-v2__header">' +
          '<span class="ce-mm-card-list-v2__title">' + headerTitle + '</span>' +
          '<span class="ce-mm-card-list-v2__count">' + countStr + '</span>' +
        '</div>' +
        '<div class="ce-mm-card-list-v2__body">' +
          '<div class="ce-mm-card-list-v2__empty">' +
            'No fights staged yet.<br>' +
            '<strong>Pick Red + Blue corners above</strong>, then hit "Add to Card".<br>' +
            'When the card is built, hit CONFIRM CARD to lock it in.' +
          '</div>' +
        '</div>' +
      '</div>';
    }

    var cardsHtml = '';
    fights.forEach(function (f, idx) {
      cardsHtml += renderFightCard(f, idx);
    });
    return '<div class="ce-mm-card-list-v2">' +
      '<div class="ce-mm-card-list-v2__header">' +
        '<span class="ce-mm-card-list-v2__title">' + headerTitle + '</span>' +
        '<span class="ce-mm-card-list-v2__count"><strong>' + fights.length + '</strong> · ' +
          (fights.length === 1 ? 'fight' : 'fights') + '</span>' +
      '</div>' +
      '<div class="ce-mm-card-list-v2__body" id="ce-mm-card-list-body">' +
        cardsHtml +
      '</div>' +
    '</div>';
  }

  function renderFightCard(f, idx) {
    var slot = f.card_slot || autoCardSlot(idx);
    var slotLbl = slotLabel(slot, idx);
    var cls = slotClass(slot);
    if (state.cardConfirmed) cls += ' ce-mm-fight-card-v2--confirmed';
    if (idx === state._dragOverIdx) cls += ' ce-mm-fight-card-v2--drag-over';
    if (idx === state._draggedStagedIdx) cls += ' ce-mm-fight-card-v2--dragging';

    var red = f.red_fighter || {};
    var blue = f.blue_fighter || {};
    var analysis = f.analysis || {};
    var rivalry = f.rivalry;

    var redPortraitStyle = portraitBgStyle(red.fighter_id);
    var bluePortraitStyle = portraitBgStyle(blue.fighter_id);
    var redPortrait = '<div class="ce-mm-fight-card-v2__fighter-portrait"' + redPortraitStyle + '>' +
      portraitInner(red, red.name) + '</div>';
    var bluePortrait = '<div class="ce-mm-fight-card-v2__fighter-portrait"' + bluePortraitStyle + '>' +
      portraitInner(blue, blue.name) + '</div>';

    var redMeta = escapeHtml(red.record_str || '') +
      (red.title_chip && red.title_chip.holds_title ? ' · 🥇' : '') +
      (red.rank_str && red.rank_str !== 'Unranked' ? ' · ' + red.rank_str : '');
    var blueMeta = escapeHtml(blue.record_str || '') +
      (blue.title_chip && blue.title_chip.holds_title ? ' · 🥇' : '') +
      (blue.rank_str && blue.rank_str !== 'Unranked' ? ' · ' + blue.rank_str : '');

    // Quality chip — voice phrase TIER ONLY (NO raw score).
    var qualityColorCls = 'ce-mm-fight-card-v2__quality-chip--' + (f.matchup_color || 'default');
    var qualityChip = '<span class="ce-mm-fight-card-v2__quality-chip ' + qualityColorCls + '">' +
      escapeHtml((f.matchup_phrase || '—')) + '</span>';

    // Rivalry chip on the card (if applicable).
    var rivalryChip = (rivalry && rivalry.has_rivalry)
      ? '<span class="ce-mm-fight-card-v2__rivalry-chip" title="' + escapeHtml(rivalry.label || '') + '">⚔ ' +
        escapeHtml(rivalry.label || 'RIVALRY') + '</span>'
      : '';

    // Voice line — might-framed analysis (style_matchup_phrase preferred).
    var voiceLine = '';
    if (analysis.style_matchup_phrase) {
      voiceLine = '<div class="ce-mm-fight-card-v2__voice-line">' + escapeHtml(analysis.style_matchup_phrase) + '</div>';
    } else if (analysis.style_edge) {
      voiceLine = '<div class="ce-mm-fight-card-v2__voice-line">' + escapeHtml(analysis.style_edge) + '</div>';
    } else if (analysis.excitement_phrase) {
      voiceLine = '<div class="ce-mm-fight-card-v2__voice-line">' + escapeHtml(analysis.excitement_phrase) + '</div>';
    }

    var slotMeta = (slot === 'main_event') ? '5 rounds' : '3 rounds';
    var dragHandle = state.cardConfirmed
      ? ''  // No drag handle when confirmed (card is locked).
      : '<div class="ce-mm-fight-card-v2__drag-handle" title="Drag to reorder">⠿</div>';

    // Action buttons — Compare/Tape/Stakes/Pulse + Remove.
    var actionsHtml = '';
    if (state.cardConfirmed) {
      // Card is locked — show Compare/Tape/Stakes/Pulse but NO Remove.
      actionsHtml =
        '<button class="ce-mm-fight-card-v2__action" data-action="compare" data-fight-idx="' + idx + '" type="button" title="Compare">⚡</button>' +
        '<button class="ce-mm-fight-card-v2__action" data-action="tape" data-fight-idx="' + idx + '" type="button" title="Tale of Tape">📋</button>' +
        '<button class="ce-mm-fight-card-v2__action" data-action="stakes" data-fight-idx="' + idx + '" type="button" title="What\'s at Stake">🏆</button>' +
        '<button class="ce-mm-fight-card-v2__action" data-action="pulse" data-fight-idx="' + idx + '" type="button" title="Fan Pulse">❤</button>';
    } else {
      actionsHtml =
        '<button class="ce-mm-fight-card-v2__action" data-action="compare" data-fight-idx="' + idx + '" type="button" title="Compare">⚡</button>' +
        '<button class="ce-mm-fight-card-v2__action" data-action="tape" data-fight-idx="' + idx + '" type="button" title="Tale of Tape">📋</button>' +
        '<button class="ce-mm-fight-card-v2__action" data-action="stakes" data-fight-idx="' + idx + '" type="button" title="What\'s at Stake">🏆</button>' +
        '<button class="ce-mm-fight-card-v2__action" data-action="pulse" data-fight-idx="' + idx + '" type="button" title="Fan Pulse">❤</button>' +
        '<button class="ce-mm-fight-card-v2__action ce-mm-fight-card-v2__action--remove" data-remove-idx="' + idx + '" type="button" title="Remove from card" aria-label="Remove fight">✕</button>';
    }

    return '<div class="ce-mm-fight-card-v2 ' + cls + '" data-staged-idx="' + idx + '"' +
      (state.cardConfirmed ? '' : ' draggable="true"') + '>' +
      dragHandle +
      '<div class="ce-mm-fight-card-v2__slot ' + slotSlotClass(slot) + '">' +
        '<div class="ce-mm-fight-card-v2__slot-label">' + slotLbl + '</div>' +
        '<div class="ce-mm-fight-card-v2__slot-meta">' + slotMeta + '</div>' +
      '</div>' +
      '<div class="ce-mm-fight-card-v2__matchup">' +
        '<div class="ce-mm-fight-card-v2__fighters">' +
          '<div class="ce-mm-fight-card-v2__fighter ce-mm-fight-card-v2__fighter--red">' +
            redPortrait +
            '<div class="ce-mm-fight-card-v2__fighter-info">' +
              '<div class="ce-mm-fight-card-v2__fighter-name">' + escapeHtml(red.name || '—') + '</div>' +
              '<div class="ce-mm-fight-card-v2__fighter-meta">' + redMeta + '</div>' +
            '</div>' +
          '</div>' +
          '<div class="ce-mm-fight-card-v2__vs">vs</div>' +
          '<div class="ce-mm-fight-card-v2__fighter ce-mm-fight-card-v2__fighter--blue">' +
            '<div class="ce-mm-fight-card-v2__fighter-info">' +
              '<div class="ce-mm-fight-card-v2__fighter-name">' + escapeHtml(blue.name || '—') + '</div>' +
              '<div class="ce-mm-fight-card-v2__fighter-meta">' + blueMeta + '</div>' +
            '</div>' +
            bluePortrait +
          '</div>' +
        '</div>' +
        '<div class="ce-mm-fight-card-v2__voices">' +
          qualityChip +
          rivalryChip +
          (f.weight_class_name ? '<span class="ce-mm-fight-card-v2__voice-line" style="flex:0 0 auto;font-family:var(--font-mono);font-size:10px;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:0.04em">' + escapeHtml(f.weight_class_name) + '</span>' : '') +
        '</div>' +
        voiceLine +
        '<div class="ce-mm-fight-card-v2__actions">' + actionsHtml + '</div>' +
      '</div>' +
      (state.cardConfirmed
        ? '<div class="ce-mm-fight-card-v2__lock" title="Card confirmed — locked">🔒</div>'
        : '<div style="width:28px"></div>') +
    '</div>';
  }

  // ============================================================
  // RENDER — STATUS PANEL (bottom right, 40%)
  // ============================================================
  function renderStatusPanel() {
    if (state.cardConfirmed) {
      return renderConfirmedStatus();
    }
    // Build phase — projection hidden.
    var nStaged = state.stagedFights.length;
    // Phase F2.1 (docs/FIX_PLAN_FINANCES_ADVANCEDAY.md §F2.1) — min
    // card size enforcement. A major promo needs >= 5 fights, mid
    // tier >= 4, small >= 3. The CONFIRM button is disabled until
    // the player has staged enough fights. The backend confirm_card
    // already enforces this (rejects with error_code='min_fights_
    // not_met'); this UI gate prevents the player from clicking a
    // button that would obviously fail + tells them WHY.
    var sizeTier = (state.promo && state.promo.size_tier) || 'small';
    var minFights = sizeTier === 'major' ? 5 :
                    sizeTier === 'mid' ? 4 : 3;
    var canConfirm = nStaged >= minFights;
    var tierPhrase = sizeTier === 'major' ? 'major' :
                     sizeTier === 'mid' ? 'mid-tier' : 'small';
    var minFightsMsg = canConfirm
      ? ''
      : ('A ' + tierPhrase + ' promotion needs at least ' + minFights +
         ' fights on a card (you have ' + nStaged + '). Add more fights.');
    return '<div class="ce-mm-status-v2">' +
      '<div class="ce-mm-status-v2__header">' +
        '<span class="ce-mm-status-v2__title">Status</span>' +
        '<span class="ce-mm-status-v2__title" style="color:var(--text-secondary);font-size:10px">' +
          (nStaged === 0 ? 'No fights yet' : nStaged + ' staged') +
        '</span>' +
      '</div>' +
      '<div class="ce-mm-status-v2__body">' +
        '<div class="ce-mm-status-v2__placeholder">' +
          '<div class="ce-mm-status-v2__placeholder-icon">📊</div>' +
          '<div class="ce-mm-status-v2__placeholder-title">Confirm card to see projected revenue</div>' +
          '<div class="ce-mm-status-v2__placeholder-text">' +
            'Build the card on the left. When you\'re ready, confirm it to lock the fights in and see the projected gate, PPV, expenses, and net profit.' +
          '</div>' +
          // Phase F2.1 — min fights enforcement message (shown in red
          // when the player hasn't staged enough fights yet; hidden
          // once they meet the threshold).
          (canConfirm ? '' :
            '<div class="ce-mm-status-v2__min-fights-msg">' +
              escapeHtml(minFightsMsg) +
            '</div>') +
          (canConfirm
            ? '<button class="ce-mm-status-v2__cta" data-confirm-card type="button">🔒 Confirm Card · ' + nStaged + ' Fight' + (nStaged !== 1 ? 's' : '') + '</button>'
            : '<div class="ce-mm-status-v2__placeholder-tip">Stage at least ' + minFights + ' fight' + (minFights !== 1 ? 's' : '') + ' to confirm (' + nStaged + ' / ' + minFights + ' staged)</div>') +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function renderConfirmedStatus() {
    var p = state.lastProjection;
    var cp = state.cardPreview || {};
    if (!p || !p.ok || !p.show_projection) {
      // Card is confirmed but projection isn't loaded yet — fetch.
      return '<div class="ce-mm-status-v2">' +
        '<div class="ce-mm-status-v2__header">' +
          '<span class="ce-mm-status-v2__title">Status</span>' +
          '<span class="ce-mm-status-v2__title" style="color:var(--gold);font-size:10px">CONFIRMED</span>' +
        '</div>' +
        '<div class="ce-mm-status-v2__body">' +
          '<div class="ce-mm-status-v2__placeholder">' +
            '<div class="ce-mm-status-v2__placeholder-icon">📊</div>' +
            '<div class="ce-mm-status-v2__placeholder-title">Loading projection…</div>' +
          '</div>' +
        '</div>' +
      '</div>';
    }

    var drawScore = p.card_draw_score;
    var drawBarPct = drawScore !== null && drawScore !== undefined
      ? Math.max(2, Math.min(100, drawScore)) : 0;

    var netKind = p.voice_kind || 'safe';

    // Phase F1.3 — range display strings. Show quality is unknown
    // pre-event; revenue varies ±30%. The status panel shows the
    // RANGE for revenue + net, with the voice phrase below. Falls
    // back to single-number if backend didn't return range fields.
    var revRangeStr = p.revenue_range_display ||
      (fmtCash(p.total_revenue) + ' - ' + fmtCash(p.total_revenue));
    var netRangeStr = p.net_range_display ||
      (fmtCash(p.net_profit) + ' - ' + fmtCash(p.net_profit));

    var healthHtml = '';
    if (p.card_health_flags && p.card_health_flags.length) {
      p.card_health_flags.forEach(function (fl) {
        var icon = fl.severity === 'warning' ? '⚠' : 'ⓘ';
        healthHtml += '<div class="ce-mm-status-v2__health-flag ce-mm-status-v2__health-flag--' + fl.severity + '">' +
          '<span class="ce-mm-status-v2__health-flag-icon">' + icon + '</span>' +
          '<span>' + escapeHtml(fl.phrase) + '</span>' +
        '</div>';
      });
    }

    return '<div class="ce-mm-status-v2">' +
      '<div class="ce-mm-status-v2__header">' +
        '<span class="ce-mm-status-v2__title">Projected P&L</span>' +
        '<span class="ce-mm-status-v2__title" style="color:var(--gold);font-size:10px">CONFIRMED</span>' +
      '</div>' +
      '<div class="ce-mm-status-v2__body">' +
        // Phase F1.3 — variance hint (the range exists because show
        // quality is unknown pre-event).
        '<div class="ce-mm-status-v2__variance-hint">' +
          '<span class="ce-mm-status-v2__variance-icon">📊</span>' +
          '<span class="ce-mm-status-v2__variance-text">Revenue varies ±30% based on show quality — a blockbuster earns the high end, a dud falls to the low end.</span>' +
        '</div>' +
        // Card draw
        '<div class="ce-mm-status-v2__card-draw">' +
          '<div class="ce-mm-status-v2__card-draw-label">YOUR CARD DRAW</div>' +
          (p.card_draw_phrase
            ? '<div class="ce-mm-status-v2__card-draw-phrase">' + escapeHtml(p.card_draw_phrase) + '</div>'
            : '<div class="ce-mm-status-v2__card-draw-phrase" style="color:var(--text-tertiary)">No card draw yet.</div>') +
          (drawScore !== null && drawScore !== undefined
            ? '<div class="ce-mm-status-v2__card-draw-bar"><div class="ce-mm-status-v2__card-draw-bar-fill" style="width:' + drawBarPct + '%"></div></div>'
            : '') +
        '</div>' +
        // Revenue breakdown (line items — single number, known precisely
        // because they're attendance/buyrate driven, not show-quality
        // driven. The TOTAL row shows the midpoint; the range is in
        // the net banner below).
        '<div class="ce-mm-status-v2__breakdown">' +
          '<div class="ce-mm-status-v2__breakdown-title">Revenue (mid)</div>' +
          '<div class="ce-mm-status-v2__breakdown-row"><span>Gate</span><span>' + escapeHtml(p.gate_display || fmtCash(p.gate)) + '</span></div>' +
          '<div class="ce-mm-status-v2__breakdown-row"><span>Broadcast</span><span>' + escapeHtml(p.broadcast_revenue_display || fmtCash(p.broadcast_revenue)) + '</span></div>' +
          '<div class="ce-mm-status-v2__breakdown-row"><span>Sponsorship</span><span>' + escapeHtml(p.sponsorship_display || fmtCash(p.sponsorship)) + '</span></div>' +
          '<div class="ce-mm-status-v2__breakdown-row"><span>Merch</span><span>' + escapeHtml(p.merch_display || fmtCash(p.merch)) + '</span></div>' +
          '<div class="ce-mm-status-v2__breakdown-row"><span>Concessions</span><span>' + escapeHtml(p.concessions_display || fmtCash(p.concessions)) + '</span></div>' +
          '<div class="ce-mm-status-v2__breakdown-row ce-mm-status-v2__breakdown-row--total"><span>Total Revenue (mid)</span><span>' + escapeHtml(p.total_revenue_display || fmtCash(p.total_revenue)) + '</span></div>' +
        '</div>' +
        // Expense breakdown (single number — expenses are known precisely).
        '<div class="ce-mm-status-v2__breakdown">' +
          '<div class="ce-mm-status-v2__breakdown-title">Expenses</div>' +
          '<div class="ce-mm-status-v2__breakdown-row ce-mm-status-v2__breakdown-row--expense"><span>Fighter Purses</span><span>' + escapeHtml(p.fighter_purses_display || fmtCash(p.fighter_purses)) + '</span></div>' +
          '<div class="ce-mm-status-v2__breakdown-row ce-mm-status-v2__breakdown-row--expense"><span>Staff Salary</span><span>' + escapeHtml(p.staff_salary_display || fmtCash(p.staff_salary)) + '</span></div>' +
          '<div class="ce-mm-status-v2__breakdown-row ce-mm-status-v2__breakdown-row--expense"><span>Venue Rental</span><span>' + escapeHtml(p.venue_rental_display || fmtCash(p.venue_rental)) + '</span></div>' +
          '<div class="ce-mm-status-v2__breakdown-row ce-mm-status-v2__breakdown-row--expense"><span>Marketing</span><span>' + escapeHtml(p.marketing_expense_display || fmtCash(p.marketing_expense)) + '</span></div>' +
          '<div class="ce-mm-status-v2__breakdown-row ce-mm-status-v2__breakdown-row--expense"><span>Medical</span><span>' + escapeHtml(p.insurance_medical_display || fmtCash(p.insurance_medical)) + '</span></div>' +
          '<div class="ce-mm-status-v2__breakdown-row ce-mm-status-v2__breakdown-row--total"><span>Total Expenses</span><span>' + escapeHtml(p.total_expenses_display || fmtCash(p.total_expenses)) + '</span></div>' +
        '</div>' +
        // Phase F1.3 — Net profit shown as a RANGE. Color-coded by
        // voice_kind (safe=green / risky=yellow / lethal=red).
        '<div class="ce-mm-status-v2__net ce-mm-status-v2__net--' + netKind + '">' +
          '<div class="ce-mm-status-v2__net-label">PROJECTED REVENUE</div>' +
          '<div class="ce-mm-status-v2__net-value ce-mm-status-v2__net-value--range">' + escapeHtml(revRangeStr) + '</div>' +
          '<div class="ce-mm-status-v2__net-label" style="margin-top:10px">PROJECTED NET</div>' +
          '<div class="ce-mm-status-v2__net-value ce-mm-status-v2__net-value--range">' + escapeHtml(netRangeStr) + '</div>' +
          '<div class="ce-mm-status-v2__net-phrase">' + escapeHtml(p.voice_phrase || '') + '</div>' +
          '<div class="ce-mm-status-v2__net-cash-after">YOUR WAR CHEST AFTER · <strong>' + escapeHtml(p.cash_after_display || fmtCash(p.cash_after_event)) + '</strong></div>' +
        '</div>' +
        // Card health
        (healthHtml ? '<div class="ce-mm-status-v2__breakdown">' +
          '<div class="ce-mm-status-v2__breakdown-title">Card Health</div>' +
          healthHtml +
        '</div>' : '') +
        // Re-open card button
        '<button class="ce-mm-status-v2__cta ce-mm-status-v2__cta--danger" data-reopen-card type="button" style="margin-top:8px">🔓 Re-open Card</button>' +
      '</div>' +
    '</div>';
  }

  function renderBottomZone() {
    return '<div class="ce-mm-v2__bottom-zone">' +
      renderCardList() +
      renderStatusPanel() +
    '</div>' +
      renderSuggestedMatchupsPanel();
  }

  // ============================================================
  // RENDER — SUGGESTED MATCHUPS PANEL (P5.1 Booking Adviser)
  // ============================================================
  // Collapsible panel below the bottom zone. Shows 3-5 matchup
  // suggestions the player might miss — hometown fighters, top
  // contenders, rivalries, debuts, win streaks. NOT auto-booking:
  // clicking a row fills Red/Blue corners and scrolls up; the player
  // still has to hit "Add to Card" themselves.
  function renderSuggestedMatchupsPanel() {
    var open = state.suggestionsOpen;
    var count = state.suggestedMatchups.length;
    var arrow = open ? '▼' : '▶';
    var countChip = count
      ? '<span class="ce-mm-suggest__count">' + count + ' matchup' + (count !== 1 ? 's' : '') + '</span>'
      : (state.suggestionsLoading
          ? '<span class="ce-mm-suggest__count">finding angles…</span>'
          : '<span class="ce-mm-suggest__count ce-mm-suggest__count--empty">no angles right now</span>');

    var headerHtml = '<div class="ce-mm-suggest__header" data-suggest-toggle role="button" tabindex="0">' +
      '<span class="ce-mm-suggest__title">' + arrow + ' SUGGESTED MATCHUPS</span>' +
      '<span class="ce-mm-suggest__subhead">Opportunities the matchmaker sees</span>' +
      countChip +
    '</div>';

    if (!open) {
      return '<div class="ce-mm-suggest ce-mm-suggest--collapsed">' + headerHtml + '</div>';
    }

    var bodyHtml = '';
    if (state.suggestionsLoading) {
      bodyHtml = '<div class="ce-mm-suggest__loading">Mining the division for angles…</div>';
    } else if (!count) {
      bodyHtml = '<div class="ce-mm-suggest__empty">' +
        'No fresh angles to surface right now.<br>' +
        'Book a fight or two, then come back — the matchmaker will find more material.' +
      '</div>';
    } else {
      state.suggestedMatchups.forEach(function (s, idx) {
        bodyHtml += renderSuggestionRow(s, idx);
      });
    }

    return '<div class="ce-mm-suggest ce-mm-suggest--open">' +
      headerHtml +
      '<div class="ce-mm-suggest__body">' + bodyHtml + '</div>' +
    '</div>';
  }

  function renderSuggestionRow(s, idx) {
    var red = s.red_fighter || {};
    var blue = s.blue_fighter || {};

    var redPortraitStyle = portraitBgStyle(red.fighter_id);
    var bluePortraitStyle = portraitBgStyle(blue.fighter_id);
    var redPortrait = '<div class="ce-mm-suggest__portrait"' + redPortraitStyle + '>' +
      portraitInner(red, red.name) + '</div>';
    var bluePortrait = '<div class="ce-mm-suggest__portrait"' + bluePortraitStyle + '>' +
      portraitInner(blue, blue.name) + '</div>';

    var redMeta = escapeHtml(red.record_str || '') +
      (red.title_chip && red.title_chip.holds_title ? ' · 🥇' : '') +
      (red.rank_str && red.rank_str !== 'Unranked' ? ' · ' + red.rank_str : '');
    var blueMeta = escapeHtml(blue.record_str || '') +
      (blue.title_chip && blue.title_chip.holds_title ? ' · 🥇' : '') +
      (blue.rank_str && blue.rank_str !== 'Unranked' ? ' · ' + blue.rank_str : '');

    var chipClass = 'ce-mm-suggest__chip--' + (s.reason_chip || 'default').toLowerCase().replace(/\s+/g, '-');
    var reasonChip = '<span class="ce-mm-suggest__chip ' + chipClass + '">' +
      escapeHtml(s.reason_chip || 'Matchup') + '</span>';

    return '<div class="ce-mm-suggest__row" data-suggest-idx="' + idx + '" role="button" tabindex="0">' +
      '<div class="ce-mm-suggest__corner ce-mm-suggest__corner--red">' +
        redPortrait +
        '<div class="ce-mm-suggest__corner-info">' +
          '<div class="ce-mm-suggest__name">' + escapeHtml(red.display_name || red.name || 'Red') + '</div>' +
          '<div class="ce-mm-suggest__meta">' + redMeta + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="ce-mm-suggest__vs">VS</div>' +
      '<div class="ce-mm-suggest__corner ce-mm-suggest__corner--blue">' +
        bluePortrait +
        '<div class="ce-mm-suggest__corner-info">' +
          '<div class="ce-mm-suggest__name">' + escapeHtml(blue.display_name || blue.name || 'Blue') + '</div>' +
          '<div class="ce-mm-suggest__meta">' + blueMeta + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="ce-mm-suggest__reason">' +
        reasonChip +
        '<div class="ce-mm-suggest__reason-phrase">' + escapeHtml(s.reason_phrase || '') + '</div>' +
        '<div class="ce-mm-suggest__quality-phrase">' + escapeHtml(s.quality_phrase || '') + '</div>' +
      '</div>' +
      '<div class="ce-mm-suggest__cta">FILL CORNERS →</div>' +
    '</div>';
  }

  // ============================================================
  // RENDER — ROSTER BROWSER OVERLAY
  // ============================================================
  function renderRosterBrowser() {
    if (!state.rosterOpen) return '';
    var corner = state.rosterCorner || 'red';
    var cornerLabel = corner === 'red' ? 'RED CORNER' : 'BLUE CORNER';
    var cornerCls = 'ce-mm-roster__title-corner--' + corner;

    // Build filter chips.
    var filters = [
      { id: 'all', label: 'All' },
      { id: 'top15', label: 'Top 15' },
      { id: 'streak', label: 'On Streak' },
      { id: 'hometown', label: 'Hometown' },
      { id: 'champions', label: 'Champions' },
      { id: 'rivalry', label: '⚔ Rivalry' },
    ];
    // Add per-WC filters from state.eligibleFighters.
    var wcMap = {};
    state.eligibleFighters.forEach(function (f) {
      var wcId = f.weight_class_id;
      if (!wcMap[wcId]) {
        wcMap[wcId] = { id: 'wc_' + wcId, label: f.weight_class_short || f.weight_class_name || 'WC' };
      }
    });
    var wcFilters = Object.values(wcMap);

    var filterHtml = '';
    filters.forEach(function (f) {
      var active = state.rosterFilter === f.id ? ' ce-mm-roster__filter-chip--active' : '';
      filterHtml += '<div class="ce-mm-roster__filter-chip' + active + '" data-roster-filter="' + f.id + '" role="button" tabindex="0">' +
        escapeHtml(f.label) + '</div>';
    });
    wcFilters.forEach(function (f) {
      var active = state.rosterFilter === f.id ? ' ce-mm-roster__filter-chip--active' : '';
      filterHtml += '<div class="ce-mm-roster__filter-chip' + active + '" data-roster-filter="' + f.id + '" role="button" tabindex="0">' +
        escapeHtml(f.label) + '</div>';
    });
    filterHtml += '<input type="text" class="ce-mm-roster__search" id="ce-mm-roster-search" placeholder="Search by name…" value="' + escapeHtml(state.rosterSearch) + '" />';

    // Apply filters.
    var filtered = state.eligibleFighters.filter(function (f) {
      if (state.rosterFilter === 'top15') {
        if (!f.rank_num) return false;
      } else if (state.rosterFilter === 'streak') {
        if (!f.streak_phrase) return false;
      } else if (state.rosterFilter === 'hometown') {
        if (!state.event || !state.event.nation_name) return false;
        if (!f.birth_nation || f.birth_nation !== state.event.nation_name) return false;
      } else if (state.rosterFilter === 'champions') {
        if (!f.title_chip || !f.title_chip.holds_title) return false;
      } else if (state.rosterFilter === 'rivalry') {
        if (corner === 'red') return false;  // Rivalry filter only for blue (when red is picked).
        if (!state.redCorner) return false;
        if (!state.rivalryPartnerIds[f.fighter_id]) return false;
      } else if (state.rosterFilter.indexOf('wc_') === 0) {
        var wcId = parseInt(state.rosterFilter.substring(3), 10);
        if (f.weight_class_id !== wcId) return false;
      }
      if (state.rosterSearch) {
        var q = state.rosterSearch.toLowerCase();
        if (f.name.toLowerCase().indexOf(q) === -1 &&
            (f.nickname || '').toLowerCase().indexOf(q) === -1) {
          return false;
        }
      }
      return true;
    });

    var rowsHtml = '';
    if (!filtered.length) {
      rowsHtml = '<div class="ce-mm-roster__empty">No fighters match. Try a different filter.</div>';
    } else {
      filtered.forEach(function (f) {
        // If picking blue, validate same-WC + same-gender (otherwise dim).
        var incompatible = false;
        if (corner === 'blue' && state.redCorner) {
          if (f.weight_class_id !== state.redCorner.weight_class_id) incompatible = true;
          if (f.gender !== state.redCorner.gender) incompatible = true;
        }
        // Dim if already staged (can't double-book).
        var stagedIds = {};
        if (!state.cardConfirmed) {
          state.stagedFights.forEach(function (sf) {
            if (sf.red_fighter) stagedIds[sf.red_fighter.fighter_id] = true;
            if (sf.blue_fighter) stagedIds[sf.blue_fighter.fighter_id] = true;
          });
        } else {
          state.bookedFights.forEach(function (bf) {
            if (bf.red_fighter) stagedIds[bf.red_fighter.fighter_id] = true;
            if (bf.blue_fighter) stagedIds[bf.blue_fighter.fighter_id] = true;
          });
        }
        var alreadyStaged = !!stagedIds[f.fighter_id];
        var cls = 'ce-mm-roster__row';
        if (incompatible || alreadyStaged) cls += ' ce-mm-roster__row--incompatible';
        // Rivalry flag (when red corner is set, mark opponents with rivalry).
        var hasRivalry = state.redCorner && corner === 'blue' &&
          !!state.rivalryPartnerIds[f.fighter_id];
        if (hasRivalry) cls += ' ce-mm-roster__row--rivalry';

        var rankCls = 'ce-mm-roster__rank--steel';
        if (f.title_chip && f.title_chip.holds_title) rankCls = '';
        else if (f.rank_num && f.rank_num >= 1 && f.rank_num <= 5) rankCls = 'ce-mm-roster__rank--top5';
        var rankHtml = (f.rank_str && f.rank_str !== 'Unranked')
          ? '<div class="ce-mm-roster__rank ' + rankCls + '">' + escapeHtml(f.rank_str) + '</div>'
          : '<div class="ce-mm-roster__rank ' + rankCls + '">—</div>';

        var portraitStyle = portraitBgStyle(f.fighter_id);
        var portraitHtml = '<div class="ce-mm-roster__portrait"' + portraitStyle + '>' +
          portraitInner(f, f.name) + '</div>';

        // Recent form mini-chips.
        var formHtml = '<span class="ce-mm-roster__form">';
        if (f.recent_form && f.recent_form.length) {
          f.recent_form.forEach(function (b) {
            formHtml += '<div class="ce-mm-form-chip ce-mm-form-chip--' + b.letter + '">' + b.letter + '</div>';
          });
        }
        formHtml += '</span>';

        // Popularity chip + momentum chip + title chip.
        var chipsHtml = '';
        if (f.title_chip && f.title_chip.holds_title) {
          chipsHtml += '<span class="ce-mm-chip-v2 ce-mm-chip-v2--title">🥇 ' + escapeHtml(f.title_chip.title_label) + '</span>';
        }
        chipsHtml += '<span class="ce-mm-chip-v2 ' + popularityChipClass(f.popularity_tier) + '">' + escapeHtml(f.popularity_tier) + '</span>';
        if (f.momentum_label) {
          chipsHtml += '<span class="ce-mm-chip-v2 ' + momentumChipClass(f.momentum_label) + '">' + escapeHtml(momentumLabel(f.momentum_label)) + '</span>';
        }
        if (hasRivalry) {
          chipsHtml += '<span class="ce-mm-roster__rivalry-flag">⚔ ' + escapeHtml(state.rivalryPartnerIds[f.fighter_id].label || 'RIVALRY') + '</span>';
        }

        rowsHtml += '<div class="' + cls + '" data-roster-fighter-id="' + f.fighter_id + '"' +
          (incompatible || alreadyStaged ? ' data-incompatible="1"' : '') +
          ' role="button" tabindex="0">' +
          portraitHtml +
          '<div class="ce-mm-roster__info">' +
            '<div class="ce-mm-roster__name">' +
              escapeHtml(f.display_name || f.name) +
              (f.nickname ? '<span class="ce-mm-roster__nickname">"' + escapeHtml(f.nickname) + '"</span>' : '') +
            '</div>' +
            '<div class="ce-mm-roster__meta">' +
              '<span>' + escapeHtml(f.record_str || '0-0') + '</span>' +
              '<span>·</span>' +
              '<span>' + escapeHtml(f.weight_class_short || f.weight_class_name || '—') + '</span>' +
              (f.age !== null && f.age !== undefined ? '<span>· ' + f.age + 'y</span>' : '') +
              '<span>·</span>' +
              '<span>' + escapeHtml(f.style_archetype_name || 'Balanced') + '</span>' +
              chipsHtml +
              formHtml +
            '</div>' +
          '</div>' +
          rankHtml +
        '</div>';
      });
    }

    return '<div class="ce-mm-roster-overlay" id="ce-mm-roster-overlay">' +
      '<div class="ce-mm-roster">' +
        '<div class="ce-mm-roster__header">' +
          '<div class="ce-mm-roster__title">PICK FIGHTER<span class="ce-mm-roster__title-corner ' + cornerCls + '">' + cornerLabel + '</span></div>' +
          '<button class="ce-mm-roster__close" id="ce-mm-roster-close" type="button" aria-label="Close">×</button>' +
        '</div>' +
        '<div class="ce-mm-roster__filters">' + filterHtml + '</div>' +
        '<div class="ce-mm-roster__body">' + rowsHtml + '</div>' +
      '</div>' +
    '</div>';
  }

  // ============================================================
  // RENDER — FULL SCREEN
  // ============================================================
  function render() {
    var host = document.getElementById('screen-content');
    if (!host) return;

    if (!state.eventId) {
      host.innerHTML = renderPlaceholder();
      wirePlaceholder();
      return;
    }
    if (!state.event) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Loading matchmaking…</div></div>';
      return;
    }

    var html = '<div class="ce-mm-v2">' +
      renderEventStrip() +
      renderMatchupZone() +
      renderBottomZone() +
    '</div>' +
    renderRosterBrowser();
    host.innerHTML = html;
    wireEvents();
    loadVisiblePortraits();

    // If card is confirmed but projection not yet loaded, fetch it.
    if (state.cardConfirmed && !state.lastProjection) {
      fetchConfirmedProjection();
    }
  }

  function renderPlaceholder() {
    return '<div class="ce-mm-v2">' +
      '<div class="ce-mm-v2__placeholder">' +
        '<div class="ce-mm-v2__placeholder-icon">⚔</div>' +
        '<div class="ce-mm-v2__placeholder-title">No Card Selected</div>' +
        '<div class="ce-mm-v2__placeholder-body">' +
          'Go to Stack a Card to create an event first. Once the venue ' +
          'is set and the levers are dialed in, come back here to ' +
          'stack the card.' +
        '</div>' +
        '<button class="ce-mm-v2__placeholder-cta" id="ce-mm-goto-builder" type="button">Go to Stack a Card</button>' +
      '</div>' +
    '</div>';
  }

  function wirePlaceholder() {
    var btn = document.getElementById('ce-mm-goto-builder');
    if (btn) {
      btn.addEventListener('click', function () {
        window.CE.app.navigate('event_builder');
      });
    }
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    // Pick-corner buttons (opens roster browser).
    document.querySelectorAll('[data-pick-corner]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var corner = btn.getAttribute('data-pick-corner');
        openRosterBrowser(corner);
      });
    });
    // Clear-corner buttons.
    document.querySelectorAll('[data-clear-corner]').forEach(function (btn) {
      btn.addEventListener('click', function (evt) {
        evt.stopPropagation();
        var corner = btn.getAttribute('data-clear-corner');
        onClearCorner(corner);
      });
    });
    // ADD TO CARD button.
    var addBtn = document.querySelector('[data-add-to-card]');
    if (addBtn) {
      addBtn.addEventListener('click', onAddToCard);
    }
    // Confirm card button.
    var confirmBtn = document.querySelector('[data-confirm-card]');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', onConfirmCard);
    }
    // Re-open card buttons (there can be 2 — one in event strip, one in status panel).
    document.querySelectorAll('[data-reopen-card]').forEach(function (btn) {
      btn.addEventListener('click', onReopenCard);
    });
    // Remove staged fight buttons.
    document.querySelectorAll('[data-remove-idx]').forEach(function (btn) {
      btn.addEventListener('click', function (evt) {
        evt.stopPropagation();
        var idx = parseInt(btn.getAttribute('data-remove-idx'), 10);
        onRemoveStaged(idx);
      });
    });
    // Fight action buttons (Compare/Tape/Stakes/Pulse).
    document.querySelectorAll('[data-action]').forEach(function (btn) {
      btn.addEventListener('click', function (evt) {
        evt.stopPropagation();
        var action = btn.getAttribute('data-action');
        var idx = parseInt(btn.getAttribute('data-fight-idx'), 10);
        onFightAction(action, idx);
      });
    });
    // Drag-drop on staged fight cards.
    if (!state.cardConfirmed) wireDragDrop();
    // P5.1 — Suggested Matchups panel wires (toggle + click-to-fill).
    wireSuggestedMatchups();
    // Roster browser wires (only when open).
    if (state.rosterOpen) wireRosterBrowser();
  }

  // ============================================================
  // SUGGESTED MATCHUPS — wire toggle + click-to-fill (P5.1)
  // ============================================================
  function wireSuggestedMatchups() {
    var toggle = document.querySelector('[data-suggest-toggle]');
    if (toggle) {
      toggle.addEventListener('click', function () {
        state.suggestionsOpen = !state.suggestionsOpen;
        render();
      });
      toggle.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault();
          state.suggestionsOpen = !state.suggestionsOpen;
          render();
        }
      });
    }
    document.querySelectorAll('[data-suggest-idx]').forEach(function (row) {
      row.addEventListener('click', function () {
        var idx = parseInt(row.getAttribute('data-suggest-idx'), 10);
        onSuggestionClick(idx);
      });
      row.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault();
          var idx = parseInt(row.getAttribute('data-suggest-idx'), 10);
          onSuggestionClick(idx);
        }
      });
    });
  }

  function onSuggestionClick(idx) {
    if (idx < 0 || idx >= state.suggestedMatchups.length) return;
    var s = state.suggestedMatchups[idx];
    if (!s || !s.red_fighter || !s.blue_fighter) return;
    // Don't allow filling if the card is locked (confirmed) — the
    // corners can't be re-staged without re-opening the card.
    if (state.cardConfirmed) {
      showToast('Card is confirmed. Re-open the card to stage new fights.', 'info');
      return;
    }
    state.redCorner = s.red_fighter;
    state.blueCorner = s.blue_fighter;
    state.rivalryPartnerIds = {};
    // Auto-close the roster browser if open (we just filled both corners).
    state.rosterOpen = false;
    state.rosterCorner = null;
    showToast('Corners filled — hit "Add to Card" to stage this fight.', 'success');
    render();
    // Scroll to the matchup zone so the player can see the corners.
    var zone = document.querySelector('.ce-mm-v2__matchup-zone') ||
               document.querySelector('.ce-mm-v2');
    if (zone && zone.scrollIntoView) {
      zone.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function fetchSuggestedMatchups() {
    if (!state.eventId) {
      state.suggestedMatchups = [];
      state.suggestionsLoading = false;
      render();
      return;
    }
    state.suggestionsLoading = true;
    window.CE.bridge.getSuggestedMatchups(state.eventId).then(function (result) {
      state.suggestionsLoading = false;
      if (!result || !result.ok) {
        state.suggestedMatchups = [];
        // Don't toast — this is a passive panel, not a primary action.
        console.warn('[matchmaking] suggested matchups failed:',
                     result && result.error ? result.error : 'unknown');
      } else {
        state.suggestedMatchups = result.suggestions || [];
      }
      // Re-render but preserve the current roster browser state
      // (player may have it open while suggestions load).
      render();
      // Suggestions reference fighters whose portraits haven't been
      // fetched yet — trigger the lazy load.
      loadVisiblePortraits();
    }).catch(function (err) {
      state.suggestionsLoading = false;
      state.suggestedMatchups = [];
      console.warn('[matchmaking] suggested matchups error:', err);
      render();
    });
  }

  function wireRosterBrowser() {
    var overlay = document.getElementById('ce-mm-roster-overlay');
    if (!overlay) return;
    // Close on overlay click outside the modal.
    overlay.addEventListener('click', function (evt) {
      if (evt.target === overlay) closeRosterBrowser();
    });
    var closeBtn = document.getElementById('ce-mm-roster-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', closeRosterBrowser);
    }
    // Filter chips.
    document.querySelectorAll('[data-roster-filter]').forEach(function (chip) {
      chip.addEventListener('click', function () {
        state.rosterFilter = chip.getAttribute('data-roster-filter');
        render();
      });
    });
    // Search input.
    var search = document.getElementById('ce-mm-roster-search');
    if (search) {
      var searchTimer = null;
      search.addEventListener('input', function () {
        if (searchTimer) clearTimeout(searchTimer);
        searchTimer = setTimeout(function () {
          state.rosterSearch = search.value;
          // Only re-render the roster browser body, not the whole screen.
          render();
          // Refocus the search input after re-render.
          var newSearch = document.getElementById('ce-mm-roster-search');
          if (newSearch) {
            newSearch.focus();
            newSearch.setSelectionRange(state.rosterSearch.length, state.rosterSearch.length);
          }
        }, 150);
      });
    }
    // Fighter row clicks.
    document.querySelectorAll('[data-roster-fighter-id]').forEach(function (row) {
      var incompatible = row.getAttribute('data-incompatible') === '1';
      if (incompatible) return;
      row.addEventListener('click', function () {
        var fid = parseInt(row.getAttribute('data-roster-fighter-id'), 10);
        onRosterFighterClick(fid);
      });
      row.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault();
          var fid = parseInt(row.getAttribute('data-roster-fighter-id'), 10);
          onRosterFighterClick(fid);
        }
      });
    });
    // Esc closes the roster browser.
    document.addEventListener('keydown', function (evt) {
      if (evt.key === 'Escape' && state.rosterOpen) closeRosterBrowser();
    });
  }

  // ============================================================
  // ROSTER BROWSER
  // ============================================================
  function openRosterBrowser(corner) {
    state.rosterOpen = true;
    state.rosterCorner = corner;
    state.rosterFilter = 'all';
    state.rosterSearch = '';
    // If opening for blue and red is picked, fetch rivalry partners.
    if (corner === 'blue' && state.redCorner) {
      fetchRivalryPartners(state.redCorner.fighter_id);
    } else {
      render();
    }
  }

  function closeRosterBrowser() {
    state.rosterOpen = false;
    state.rosterCorner = null;
    render();
  }

  function fetchRivalryPartners(redFighterId) {
    window.CE.bridge.getRivalryPartners(redFighterId).then(function (result) {
      if (result && result.ok) {
        var map = {};
        (result.partner_ids || []).forEach(function (p) {
          map[p.fighter_id] = p;
        });
        state.rivalryPartnerIds = map;
      }
      render();
    }).catch(function (err) {
      console.error('[matchmaking] rivalry partners:', err);
      state.rivalryPartnerIds = {};
      render();
    });
  }

  function onRosterFighterClick(fid) {
    var fighter = state.eligibleFighters.find(function (f) {
      return f.fighter_id === fid;
    });
    if (!fighter) return;
    var corner = state.rosterCorner;
    if (corner === 'red') {
      state.redCorner = fighter;
      // Reset blue corner (in case the player is changing the red corner).
      state.blueCorner = null;
      // Clear rivalry map (will be refetched when blue is being picked).
      state.rivalryPartnerIds = {};
      closeRosterBrowser();
    } else if (corner === 'blue') {
      // Same-WC + same-gender check (defensive).
      if (state.redCorner) {
        if (fighter.weight_class_id !== state.redCorner.weight_class_id) {
          showToast('Pick a fighter from the same weight class as ' + state.redCorner.name + '.', 'error');
          return;
        }
        if (fighter.gender !== state.redCorner.gender) {
          showToast('Mixed-gender fights are not allowed.', 'error');
          return;
        }
      }
      state.blueCorner = fighter;
      closeRosterBrowser();
    }
  }

  function onClearCorner(corner) {
    if (corner === 'red') {
      state.redCorner = null;
      state.blueCorner = null;  // Clear blue too (can't have blue without red).
      state.rivalryPartnerIds = {};
    } else {
      state.blueCorner = null;
    }
    render();
  }

  // ============================================================
  // PORTRAIT LOADING
  // ============================================================
  function loadVisiblePortraits() {
    var idsToFetch = new Set();
    state.eligibleFighters.forEach(function (f) {
      if (state.portraitCache[f.fighter_id] === undefined && f.has_portrait) {
        idsToFetch.add(f.fighter_id);
      }
    });
    [state.redCorner, state.blueCorner].forEach(function (f) {
      if (f && state.portraitCache[f.fighter_id] === undefined && f.has_portrait) {
        idsToFetch.add(f.fighter_id);
      }
    });
    var fights = state.cardConfirmed ? state.bookedFights : state.stagedFights;
    fights.forEach(function (bf) {
      [bf.red_fighter, bf.blue_fighter].forEach(function (f) {
        if (f && state.portraitCache[f.fighter_id] === undefined && f.has_portrait) {
          idsToFetch.add(f.fighter_id);
        }
      });
    });
    // P5.1 — suggested-matchup fighters (up to 10 = 5 matchups × 2).
    state.suggestedMatchups.forEach(function (s) {
      [s.red_fighter, s.blue_fighter].forEach(function (f) {
        if (f && state.portraitCache[f.fighter_id] === undefined && f.has_portrait) {
          idsToFetch.add(f.fighter_id);
        }
      });
    });
    var ids = Array.from(idsToFetch).slice(0, 24);
    var pending = ids.length;
    if (pending === 0) return;
    ids.forEach(function (fid) {
      fetchPortrait(fid, function () {
        pending--;
        if (pending === 0) {
          // Re-render to show portraits.
          render();
        }
      });
    });
  }

  // ============================================================
  // ADD TO CARD — stage a fight in JS memory
  // ============================================================
  function onAddToCard() {
    if (!state.redCorner || !state.blueCorner) return;
    if (state.cardConfirmed) return;  // Card is locked.
    var red = state.redCorner;
    var blue = state.blueCorner;
    // Defensive — same WC + same gender.
    if (red.weight_class_id !== blue.weight_class_id) {
      showToast('Pick fighters from the same weight class.', 'error');
      return;
    }
    if (red.gender !== blue.gender) {
      showToast('Mixed-gender fights are not allowed.', 'error');
      return;
    }
    // Check if either fighter is already staged.
    var stagedIds = {};
    state.stagedFights.forEach(function (sf) {
      if (sf.red_fighter) stagedIds[sf.red_fighter.fighter_id] = true;
      if (sf.blue_fighter) stagedIds[sf.blue_fighter.fighter_id] = true;
    });
    if (stagedIds[red.fighter_id] || stagedIds[blue.fighter_id]) {
      showToast('One of these fighters is already on the card.', 'error');
      return;
    }
    var addBtn = document.querySelector('[data-add-to-card]');
    if (addBtn) { addBtn.disabled = true; addBtn.textContent = 'Staging…'; }

    // Fetch the might-framed analysis (style_matchup_phrase, etc.)
    // + rivalry heat between the two fighters.
    window.CE.bridge.getFightAnalysis(red.fighter_id, blue.fighter_id).then(function (result) {
      if (!result || !result.ok) {
        showToast('Analysis fetch failed: ' + (result && result.error ? result.error : 'unknown'), 'error');
        if (addBtn) { addBtn.disabled = false; addBtn.textContent = '＋ Add to Card'; }
        return;
      }
      var idx = state.stagedFights.length;
      var card_slot = autoCardSlot(idx);
      state.stagedFights.push({
        fight_id: null,  // Not yet in DB.
        card_slot: card_slot,
        is_title_fight: false,
        scheduled_rounds: card_slot === 'main_event' ? 5 : 3,
        weight_class_id: red.weight_class_id,
        weight_class_name: red.weight_class_name,
        red_fighter: red,
        blue_fighter: blue,
        matchup_phrase: result.matchup_phrase,
        matchup_color: result.matchup_color,
        analysis: result.analysis || {},
        rivalry: result.rivalry || { has_rivalry: false, heat: 0, type: '', label: '' },
      });
      // Clear corners.
      state.redCorner = null;
      state.blueCorner = null;
      state.rivalryPartnerIds = {};
      showToast('Staged: ' + red.name + ' vs ' + blue.name + '. Pick your next matchup!', 'success');
      render();
      // P-FIX: auto-open the roster browser for the next Red Corner pick
      // so the player can immediately start building the next fight.
      setTimeout(function () {
        openRosterBrowser('red');
      }, 100);
    }).catch(function (err) {
      showToast('Analysis fetch failed: ' + err, 'error');
      if (addBtn) { addBtn.disabled = false; addBtn.textContent = '＋ Add to Card'; }
    });
  }

  function onRemoveStaged(idx) {
    if (state.cardConfirmed) return;
    if (idx < 0 || idx >= state.stagedFights.length) return;
    if (!confirm('Remove this fight from the staged card?')) return;
    state.stagedFights.splice(idx, 1);
    // Re-derive card_slot for remaining fights (first = main_event, etc.).
    state.stagedFights.forEach(function (sf, i) {
      sf.card_slot = autoCardSlot(i);
      sf.scheduled_rounds = sf.card_slot === 'main_event' ? 5 : 3;
    });
    showToast('Fight removed from card.', 'info');
    render();
  }

  // ============================================================
  // DRAG-DROP REORDER (staged cards only — no DB write)
  // ============================================================
  function wireDragDrop() {
    var cards = document.querySelectorAll('.ce-mm-fight-card-v2[data-staged-idx]');
    cards.forEach(function (card) {
      card.addEventListener('dragstart', function (evt) {
        var idx = parseInt(card.getAttribute('data-staged-idx'), 10);
        state._draggedStagedIdx = idx;
        card.classList.add('ce-mm-fight-card-v2--dragging');
        evt.dataTransfer.effectAllowed = 'move';
        evt.dataTransfer.setData('text/plain', String(idx));
      });
      card.addEventListener('dragend', function () {
        card.classList.remove('ce-mm-fight-card-v2--dragging');
        state._draggedStagedIdx = null;
        state._dragOverIdx = null;
        render();
      });
      card.addEventListener('dragover', function (evt) {
        evt.preventDefault();
        evt.dataTransfer.dropEffect = 'move';
      });
      card.addEventListener('drop', function (evt) {
        evt.preventDefault();
        var fromIdx = state._draggedStagedIdx;
        var toIdx = parseInt(card.getAttribute('data-staged-idx'), 10);
        if (fromIdx === null || fromIdx === toIdx) return;
        // Reorder state.stagedFights.
        var moved = state.stagedFights.splice(fromIdx, 1)[0];
        state.stagedFights.splice(toIdx, 0, moved);
        // Re-derive card_slot.
        state.stagedFights.forEach(function (sf, i) {
          sf.card_slot = autoCardSlot(i);
          sf.scheduled_rounds = sf.card_slot === 'main_event' ? 5 : 3;
        });
        render();
      });
    });
  }

  // ============================================================
  // CONFIRM / RE-OPEN CARD
  // ============================================================
  function onConfirmCard() {
    if (state.cardConfirmed) return;
    if (state.stagedFights.length === 0) {
      showToast('Stage at least 1 fight to confirm.', 'error');
      return;
    }
    var btn = document.querySelector('[data-confirm-card]');
    if (btn) { btn.disabled = true; btn.textContent = 'Confirming…'; }
    var fightsParam = state.stagedFights.map(function (sf) {
      return {
        red_fighter_id: sf.red_fighter.fighter_id,
        blue_fighter_id: sf.blue_fighter.fighter_id,
        card_slot: sf.card_slot,
      };
    });
    window.CE.bridge.confirmCard(state.eventId, fightsParam).then(function (result) {
      if (!result || !result.ok) {
        showToast('Confirm failed: ' + (result && result.error ? result.error : 'unknown'), 'error');
        if (btn) { btn.disabled = false; btn.textContent = '🔒 Confirm Card'; }
        return;
      }
      state.cardConfirmed = true;
      state.lastProjection = result.projection || null;
      // Reload matchmaking data to get the persisted booked_fights.
      return reloadCard();
    }).then(function () {
      var n = state.stagedFights.length;
      var evDate = state.event ? state.event.event_date : '';
      showToast('Card confirmed! ' + n + ' fight' + (n !== 1 ? 's' : '') +
        ' booked for ' + evDate + '.', 'success');
    }).catch(function (err) {
      showToast('Confirm failed: ' + err, 'error');
      if (btn) { btn.disabled = false; btn.textContent = '🔒 Confirm Card'; }
    });
  }

  function onReopenCard() {
    if (!state.cardConfirmed) return;
    if (!confirm('Re-open the card? This removes all booked fights from the database and lets you rebuild from scratch.')) return;
    var btns = document.querySelectorAll('[data-reopen-card]');
    btns.forEach(function (b) { b.disabled = true; b.textContent = 'Re-opening…'; });
    window.CE.bridge.reopenCard(state.eventId).then(function (result) {
      if (!result || !result.ok) {
        showToast('Re-open failed: ' + (result && result.error ? result.error : 'unknown'), 'error');
        btns.forEach(function (b) { b.disabled = false; b.textContent = '🔓 Re-open Card'; });
        return;
      }
      state.cardConfirmed = false;
      state.stagedFights = [];
      state.lastProjection = null;
      state.redCorner = null;
      state.blueCorner = null;
      state.rivalryPartnerIds = {};
      showToast('Card re-opened. ' + result.removed_count + ' fight' +
        (result.removed_count !== 1 ? 's' : '') + ' removed — back to build mode.', 'info');
      return reloadCard();
    }).catch(function (err) {
      showToast('Re-open failed: ' + err, 'error');
      btns.forEach(function (b) { b.disabled = false; b.textContent = '🔓 Re-open Card'; });
    });
  }

  function fetchConfirmedProjection() {
    if (!state.eventId) return;
    window.CE.bridge.getEventPreview({ event_id: state.eventId, confirmed: true }).then(function (result) {
      state.lastProjection = result;
      render();
    }).catch(function (err) {
      console.error('[matchmaking] projection fetch:', err);
    });
  }

  // ============================================================
  // FIGHT ACTIONS — Compare + 3 other modals
  // ============================================================
  function onFightAction(action, idx) {
    var fights = state.cardConfirmed ? state.bookedFights : state.stagedFights;
    var f = fights[idx];
    if (!f) return;
    if (action === 'compare') {
      openCompareModal(f);
    } else if (action === 'tape') {
      openTaleOfTapeModal(f);
    } else if (action === 'stakes') {
      openStakesModal(f);
    } else if (action === 'pulse') {
      openFanPulseModal(f);
    }
  }

  // ============================================================
  // MODAL — Compare (might-framed analysis)
  // ============================================================
  function openCompareModal(fight) {
    var red = fight.red_fighter || {};
    var blue = fight.blue_fighter || {};
    showModalLoading('COMPARE', 'Loading attributes…');
    // Use getFightAnalysis (might-framed) for the analysis.
    window.CE.bridge.getFightAnalysis(red.fighter_id, blue.fighter_id).then(function (data) {
      if (!data || !data.ok) {
        showModalError('Compare failed', data && data.error ? data.error : 'unknown');
        return;
      }
      // Fetch the 25 attributes separately via getFightCompare (using a
      // fight_id if booked, otherwise fetch via the fighter IDs).
      if (fight.fight_id) {
        window.CE.bridge.getFightCompare(fight.fight_id).then(function (cmpData) {
          if (cmpData && cmpData.ok) {
            renderCompareModal(data, cmpData.red_attributes, cmpData.blue_attributes);
          } else {
            // Radar chart unavailable — render without it.
            renderCompareModal(data, null, null);
          }
        }).catch(function () {
          renderCompareModal(data, null, null);
        });
      } else {
        // Staged fight (not in DB) — no radar chart available.
        renderCompareModal(data, null, null);
      }
    }).catch(function (err) {
      showModalError('Compare failed', String(err));
    });
  }

  function renderCompareModal(data, redAttrs, blueAttrs) {
    var red = data.red_fighter || {};
    var blue = data.blue_fighter || {};
    var analysis = data.analysis || {};
    var rivalry = data.rivalry;

    var radarSvg = (redAttrs && blueAttrs) ? renderRadarChart(redAttrs, blueAttrs) : '';
    var radarWrap = radarSvg
      ? '<div class="ce-mm-radar__svg-wrap">' + radarSvg + '</div>' +
        '<div class="ce-mm-radar__legend">' +
          '<div class="ce-mm-radar__legend-item">' +
            '<div class="ce-mm-radar__legend-swatch" style="background:var(--crimson)"></div>' +
            '<span>' + escapeHtml(red.display_name || red.name || 'Red') + '</span>' +
          '</div>' +
          '<div class="ce-mm-radar__legend-item">' +
            '<div class="ce-mm-radar__legend-swatch" style="background:#3b82f6"></div>' +
            '<span>' + escapeHtml(blue.display_name || blue.name || 'Blue') + '</span>' +
          '</div>' +
        '</div>'
      : '<div class="ce-mm-radar__might-block" style="text-align:center;color:var(--text-tertiary)">' +
        'Radar chart available after the fight is booked.</div>';

    // MM1.3 — matchup quality chip (voice tier ONLY, NO raw score).
    var qualityColorCls = 'ce-mm-radar__quality-chip--' + (data.matchup_color || 'default');
    var qualityRow = '<div class="ce-mm-radar__quality-row">' +
      '<span class="ce-mm-radar__quality-chip ' + qualityColorCls + '" title="Early read — matchup tier">' +
      'Early read · ' + escapeHtml(data.matchup_phrase || '—') + '</span>' +
    '</div>';

    // Rivalry chip (MM1.2 #8).
    var rivalryHtml = '';
    if (rivalry && rivalry.has_rivalry) {
      rivalryHtml = '<div class="ce-mm-radar__rivalry">' +
        '<div class="ce-mm-radar__rivalry-icon">⚔</div>' +
        '<div class="ce-mm-radar__rivalry-text">' + escapeHtml(rivalry.label || 'Active rivalry — bad blood.') + '</div>' +
      '</div>';
    }

    var html = '<div class="ce-mm-radar">' +
      radarWrap +
      qualityRow +
      rivalryHtml +
      // MM1.3 — might-framed analysis blocks (NO predicted_winner,
      // NO predicted_method, NO confidence_word, NO upset_risk).
      (analysis.style_matchup_phrase
        ? '<div class="ce-mm-radar__might-block">' +
            '<div class="ce-mm-radar__might-label">STYLE MATCHUP</div>' +
            '<div class="ce-mm-radar__might-text">' + escapeHtml(analysis.style_matchup_phrase) + '</div>' +
          '</div>'
        : '') +
      (analysis.early_read_phrase
        ? '<div class="ce-mm-radar__might-block">' +
            '<div class="ce-mm-radar__might-label">EARLY READ</div>' +
            '<div class="ce-mm-radar__might-text">' + escapeHtml(analysis.early_read_phrase) + '</div>' +
          '</div>'
        : '') +
      (analysis.excitement_phrase
        ? '<div class="ce-mm-radar__might-block">' +
            '<div class="ce-mm-radar__might-label">EXCITEMENT</div>' +
            '<div class="ce-mm-radar__might-text">' + escapeHtml(analysis.excitement_phrase) + '</div>' +
          '</div>'
        : '') +
      (analysis.style_edge
        ? '<div class="ce-mm-radar__might-block">' +
            '<div class="ce-mm-radar__might-label">STYLE EDGE</div>' +
            '<div class="ce-mm-radar__might-text">' + escapeHtml(analysis.style_edge) + '</div>' +
          '</div>'
        : '') +
    '</div>';
    showModalContent('COMPARE', html);
  }

  function renderRadarChart(redAttrs, blueAttrs) {
    // 25 attributes grouped into 5 domains.
    var groups = [
      { name: 'Striking', attrs: ['punch_power', 'punch_accuracy', 'kick_power', 'kick_accuracy', 'head_movement'] },
      { name: 'Range',    attrs: ['footwork', 'clinch_striking', 'clinch_offense', 'clinch_defense'] },
      { name: 'Grappling', attrs: ['takedown_offense', 'takedown_defense', 'top_control', 'bottom_game', 'submission_offense', 'submission_defense', 'scramble_ability', 'cage_wrestling'] },
      { name: 'Physical', attrs: ['cardio', 'recovery_rate', 'speed_explosiveness', 'strength', 'durability', 'flexibility'] },
      { name: 'Mental',   attrs: ['fight_iq', 'chin', 'adaptability'] },
    ];
    function avgGroup(attrs, fighterAttrs) {
      var sum = 0, n = 0;
      attrs.forEach(function (a) {
        sum += Number(fighterAttrs[a] || 50);
        n++;
      });
      return n > 0 ? sum / n : 50;
    }
    var redPoints = groups.map(function (g) { return avgGroup(g.attrs, redAttrs); });
    var bluePoints = groups.map(function (g) { return avgGroup(g.attrs, blueAttrs); });
    var size = 320;
    var cx = size / 2, cy = size / 2;
    var maxR = size / 2 - 50;
    var nAxes = groups.length;
    var angleStep = (Math.PI * 2) / nAxes;
    var startAngle = -Math.PI / 2;
    function pointFor(value, axisIdx) {
      var r = (value / 100) * maxR;
      var angle = startAngle + axisIdx * angleStep;
      return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
    }
    var rings = '';
    [25, 50, 75, 100].forEach(function (lvl) {
      var pts = [];
      for (var i = 0; i < nAxes; i++) {
        var p = pointFor(lvl, i);
        pts.push(p[0].toFixed(1) + ',' + p[1].toFixed(1));
      }
      rings += '<polygon points="' + pts.join(' ') + '" fill="none" stroke="var(--border-subtle)" stroke-width="1" opacity="0.6" />';
    });
    var axes = '', labels = '';
    for (var i = 0; i < nAxes; i++) {
      var endP = pointFor(100, i);
      axes += '<line x1="' + cx + '" y1="' + cy + '" x2="' + endP[0].toFixed(1) + '" y2="' + endP[1].toFixed(1) + '" stroke="var(--border-subtle)" stroke-width="1" opacity="0.5" />';
      var labelR = maxR + 18;
      var labelAngle = startAngle + i * angleStep;
      var lx = cx + labelR * Math.cos(labelAngle);
      var ly = cy + labelR * Math.sin(labelAngle);
      labels += '<text x="' + lx.toFixed(1) + '" y="' + ly.toFixed(1) + '" fill="var(--text-secondary)" font-size="10" font-family="Oswald, sans-serif" font-weight="600" text-anchor="middle" dominant-baseline="middle" letter-spacing="0.04em">' + groups[i].name.toUpperCase() + '</text>';
    }
    var redPts = [];
    for (var i = 0; i < nAxes; i++) {
      var p = pointFor(redPoints[i], i);
      redPts.push(p[0].toFixed(1) + ',' + p[1].toFixed(1));
    }
    var redPoly = '<polygon points="' + redPts.join(' ') + '" fill="rgba(214, 58, 63, 0.18)" stroke="var(--crimson)" stroke-width="2" />';
    var bluePts = [];
    for (var i = 0; i < nAxes; i++) {
      var p = pointFor(bluePoints[i], i);
      bluePts.push(p[0].toFixed(1) + ',' + p[1].toFixed(1));
    }
    var bluePoly = '<polygon points="' + bluePts.join(' ') + '" fill="rgba(59, 130, 246, 0.18)" stroke="#3b82f6" stroke-width="2" />';
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size + '">' +
      rings + axes + redPoly + bluePoly + labels +
    '</svg>';
  }

  // ============================================================
  // MODAL — Tale of Tape
  // ============================================================
  function openTaleOfTapeModal(fight) {
    // For staged fights (not in DB), we can't fetch tale-of-tape via
    // fight_id. Build a minimal version from the fighter briefs we
    // already have.
    if (!fight.fight_id) {
      renderTaleOfTapeModalFromBriefs(fight);
      return;
    }
    showModalLoading('TALE OF THE TAPE', 'Loading tale of tape…');
    window.CE.bridge.getFightTaleOfTape(fight.fight_id).then(function (data) {
      if (!data || !data.ok) {
        showModalError('Tale of Tape failed', data && data.error ? data.error : 'unknown');
        return;
      }
      renderTaleOfTapeModal(data);
    }).catch(function (err) {
      showModalError('Tale of Tape failed', String(err));
    });
  }

  function renderTaleOfTapeModalFromBriefs(fight) {
    var red = fight.red_fighter || {};
    var blue = fight.blue_fighter || {};
    var data = {
      is_title_fight: false,
      card_slot: fight.card_slot,
      scheduled_rounds: fight.scheduled_rounds || 3,
      weight_class_name: fight.weight_class_name,
      red_fighter: {
        fighter_id: red.fighter_id,
        name: red.name,
        display_name: red.display_name || red.name,
        nickname: red.nickname,
        record_str: red.record_str,
        age: red.age,
        height_cm: red.height_cm,
        reach_cm: red.reach_cm,
        stance: red.stance,
        style_archetype: red.style_archetype_name,
        champion_of: red.title_chip && red.title_chip.holds_title ? red.title_chip.title_label : null,
      },
      blue_fighter: {
        fighter_id: blue.fighter_id,
        name: blue.name,
        display_name: blue.display_name || blue.name,
        nickname: blue.nickname,
        record_str: blue.record_str,
        age: blue.age,
        height_cm: blue.height_cm,
        reach_cm: blue.reach_cm,
        stance: blue.stance,
        style_archetype: blue.style_archetype_name,
        champion_of: blue.title_chip && blue.title_chip.holds_title ? blue.title_chip.title_label : null,
      },
    };
    // Last 5 from the brief.
    data.red_fighter.last_5 = red.recent_form || [];
    data.blue_fighter.last_5 = blue.recent_form || [];
    renderTaleOfTapeModal(data);
  }

  function renderTaleOfTapeModal(data) {
    var red = data.red_fighter || {};
    var blue = data.blue_fighter || {};

    function formBlocks(fighter) {
      if (!fighter.last_5 || !fighter.last_5.length) {
        return '<span style="color:var(--text-tertiary);font-size:11px">No pro fights</span>';
      }
      return fighter.last_5.map(function (b) {
        var letter = b.letter || (b.outcome === 'win' ? 'W' : (b.outcome === 'loss' ? 'L' : (b.outcome === 'draw' ? 'D' : 'N')));
        var cls = letter === 'W' ? 'ce-mm-form-chip--W' : (letter === 'L' ? 'ce-mm-form-chip--L' : (letter === 'D' ? 'ce-mm-form-chip--D' : 'ce-mm-form-chip--N'));
        return '<div class="ce-mm-form-chip ' + cls + '">' + letter + '</div>';
      }).join('');
    }

    function heightStr(h) {
      if (!h) return '—';
      var inches = Math.round(h / 2.54);
      var ft = Math.floor(inches / 12);
      var inch = inches % 12;
      return ft + '\'' + inch + '" (' + h + 'cm)';
    }

    var redPortraitStyle = portraitBgStyle(red.fighter_id);
    var bluePortraitStyle = portraitBgStyle(blue.fighter_id);
    var redPortrait = '<div class="ce-mm-tot__portrait ce-mm-tot__portrait--red"' + redPortraitStyle + '>' +
      (state.portraitCache[red.fighter_id] ? '' : escapeHtml(fighterInitials(red.name))) + '</div>';
    var bluePortrait = '<div class="ce-mm-tot__portrait ce-mm-tot__portrait--blue"' + bluePortraitStyle + '>' +
      (state.portraitCache[blue.fighter_id] ? '' : escapeHtml(fighterInitials(blue.name))) + '</div>';

    var boutType = data.is_title_fight ? 'TITLE FIGHT' : (slotLabel(data.card_slot, 0) || 'BOUT');
    var rounds = data.scheduled_rounds || 3;

    var html = '<div class="ce-mm-tot">' +
      '<div class="ce-mm-tot__header">' +
        '<div class="ce-mm-tot__corner">' +
          redPortrait +
          '<div class="ce-mm-tot__name">' + escapeHtml(red.display_name || red.name) + '</div>' +
          (red.nickname ? '<div class="ce-mm-tot__nickname">"' + escapeHtml(red.nickname) + '"</div>' : '') +
          (red.champion_of ? '<div class="ce-mm-chip-v2 ce-mm-chip-v2--title" style="margin-top:4px">🥇 ' + escapeHtml(red.champion_of) + '</div>' : '') +
        '</div>' +
        '<div class="ce-mm-tot__center">' +
          '<div class="ce-mm-tot__bout">' + escapeHtml(boutType) + ' · ' + escapeHtml(data.weight_class_name || '') + '</div>' +
          '<span class="ce-mm-tot__center-vs">VS</span>' +
          '<div class="ce-mm-tot__bout">' + rounds + ' rounds</div>' +
        '</div>' +
        '<div class="ce-mm-tot__corner">' +
          bluePortrait +
          '<div class="ce-mm-tot__name">' + escapeHtml(blue.display_name || blue.name) + '</div>' +
          (blue.nickname ? '<div class="ce-mm-tot__nickname">"' + escapeHtml(blue.nickname) + '"</div>' : '') +
          (blue.champion_of ? '<div class="ce-mm-chip-v2 ce-mm-chip-v2--title" style="margin-top:4px">🥇 ' + escapeHtml(blue.champion_of) + '</div>' : '') +
        '</div>' +
      '</div>' +
      '<div class="ce-mm-tot__grid">' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--value ce-mm-tot__cell--value-red">' + escapeHtml(red.record_str || '—') + '</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--label">Record</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--value ce-mm-tot__cell--value-blue">' + escapeHtml(blue.record_str || '—') + '</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--value">' + (red.age !== null && red.age !== undefined ? red.age : '—') + '</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--label">Age</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--value">' + (blue.age !== null && blue.age !== undefined ? blue.age : '—') + '</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--value">' + escapeHtml(heightStr(red.height_cm)) + '</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--label">Height</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--value">' + escapeHtml(heightStr(blue.height_cm)) + '</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--value">' + escapeHtml(heightStr(red.reach_cm)) + '</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--label">Reach</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--value">' + escapeHtml(heightStr(blue.reach_cm)) + '</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--value">' + escapeHtml((red.stance || 'orthodox').charAt(0).toUpperCase() + (red.stance || 'orthodox').slice(1)) + '</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--label">Stance</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--value">' + escapeHtml((blue.stance || 'orthodox').charAt(0).toUpperCase() + (blue.stance || 'orthodox').slice(1)) + '</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--value">' + escapeHtml(red.style_archetype || 'Balanced') + '</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--label">Style</div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--value">' + escapeHtml(blue.style_archetype || 'Balanced') + '</div>' +
        '<div class="ce-mm-tot__cell"><div class="ce-mm-tot__form">' + formBlocks(red) + '</div></div>' +
        '<div class="ce-mm-tot__cell ce-mm-tot__cell--label">Last 5</div>' +
        '<div class="ce-mm-tot__cell"><div class="ce-mm-tot__form">' + formBlocks(blue) + '</div></div>' +
      '</div>' +
    '</div>';
    showModalContent('TALE OF THE TAPE', html);
  }

  // ============================================================
  // MODAL — What's at Stake
  // ============================================================
  function openStakesModal(fight) {
    if (!fight.fight_id) {
      showModalContent("WHAT'S AT STAKE",
        '<div class="ce-mm-stakes">' +
          '<div class="ce-mm-stakes__row">' +
            '<div class="ce-mm-stakes__row-text" style="font-style:italic;color:var(--text-tertiary)">' +
              'Stakes are computed once the fight is booked. Stage the fight + confirm the card to see title-shot proximity + ranking implications.' +
            '</div>' +
          '</div>' +
        '</div>');
      return;
    }
    showModalLoading("WHAT'S AT STAKE", 'Loading stakes…');
    window.CE.bridge.getFightStakes(fight.fight_id).then(function (data) {
      if (!data || !data.ok) {
        showModalError('Stakes failed', data && data.error ? data.error : 'unknown');
        return;
      }
      renderStakesModal(data);
    }).catch(function (err) {
      showModalError('Stakes failed', String(err));
    });
  }

  function renderStakesModal(data) {
    var red = data.red_fighter || {};
    var blue = data.blue_fighter || {};
    var html = '<div class="ce-mm-stakes">' +
      '<div class="ce-mm-stakes__row ce-mm-stakes__row--red">' +
        '<div class="ce-mm-stakes__row-label">' + escapeHtml(red.display_name || red.name || 'Red') + '</div>' +
        '<div class="ce-mm-stakes__row-text">' + escapeHtml(data.red_implication || '') + '</div>' +
      '</div>' +
      '<div class="ce-mm-stakes__row ce-mm-stakes__row--blue">' +
        '<div class="ce-mm-stakes__row-label">' + escapeHtml(blue.display_name || blue.name || 'Blue') + '</div>' +
        '<div class="ce-mm-stakes__row-text">' + escapeHtml(data.blue_implication || '') + '</div>' +
      '</div>' +
      (data.title_shot_phrase
        ? '<div class="ce-mm-stakes__title-shot">' +
            '<div class="ce-mm-stakes__title-shot-label">TITLE SHOT PROXIMITY</div>' +
            '<div class="ce-mm-stakes__title-shot-text">' + escapeHtml(data.title_shot_phrase) + '</div>' +
          '</div>'
        : '') +
      (data.title_fight_phrase
        ? '<div class="ce-mm-stakes__title-shot">' +
            '<div class="ce-mm-stakes__title-shot-label">TITLE STATUS</div>' +
            '<div class="ce-mm-stakes__title-shot-text">' + escapeHtml(data.title_fight_phrase) + '</div>' +
          '</div>'
        : '') +
    '</div>';
    showModalContent("WHAT'S AT STAKE", html);
  }

  // ============================================================
  // MODAL — Fan Pulse
  // ============================================================
  function openFanPulseModal(fight) {
    if (!fight.fight_id) {
      // For staged fights, show the rivalry label (if any) as a
      // minimal fan pulse read.
      var rivalry = fight.rivalry;
      var html = '<div class="ce-mm-fan-pulse">' +
        (rivalry && rivalry.has_rivalry
          ? '<div class="ce-mm-fan-pulse__headline"><div class="ce-mm-fan-pulse__headline-text">' +
              escapeHtml(rivalry.label || 'Active rivalry — bad blood.') + '</div></div>' +
            '<div class="ce-mm-fan-pulse__row"><div class="ce-mm-fan-pulse__row-label">RIVALRY</div>' +
              '<div class="ce-mm-fan-pulse__row-text">' + escapeHtml(rivalry.label || 'Active rivalry.') + '</div></div>'
          : '<div class="ce-mm-fan-pulse__headline"><div class="ce-mm-fan-pulse__headline-text">No prior history between these two — a fresh chapter.</div></div>') +
        '<div class="ce-mm-fan-pulse__row"><div class="ce-mm-fan-pulse__row-label">NOTE</div>' +
          '<div class="ce-mm-fan-pulse__row-text">Full fan pulse (series history, hometown reaction) is available after the fight is booked + the card is confirmed.</div></div>' +
      '</div>';
      showModalContent('FAN PULSE', html);
      return;
    }
    showModalLoading('FAN PULSE', 'Mining the memory engine…');
    window.CE.bridge.getFightFanPulse(fight.fight_id).then(function (data) {
      if (!data || !data.ok) {
        showModalError('Fan Pulse failed', data && data.error ? data.error : 'unknown');
        return;
      }
      renderFanPulseModal(data);
    }).catch(function (err) {
      showModalError('Fan Pulse failed', String(err));
    });
  }

  function renderFanPulseModal(data) {
    var html = '<div class="ce-mm-fan-pulse">' +
      '<div class="ce-mm-fan-pulse__headline">' +
        '<div class="ce-mm-fan-pulse__headline-text">' + escapeHtml(data.fan_pulse_phrase || '') + '</div>' +
      '</div>' +
      (data.series_phrase
        ? '<div class="ce-mm-fan-pulse__row">' +
            '<div class="ce-mm-fan-pulse__row-label">SERIES HISTORY</div>' +
            '<div class="ce-mm-fan-pulse__row-text">' + escapeHtml(data.series_phrase) + '</div>' +
          '</div>'
        : '') +
      (data.rivalry_phrase
        ? '<div class="ce-mm-fan-pulse__row">' +
            '<div class="ce-mm-fan-pulse__row-label">RIVALRY</div>' +
            '<div class="ce-mm-fan-pulse__row-text">' + escapeHtml(data.rivalry_phrase) + '</div>' +
          '</div>'
        : '') +
      (data.hometown_phrases && data.hometown_phrases.length
        ? data.hometown_phrases.map(function (hp) {
            return '<div class="ce-mm-fan-pulse__row">' +
              '<div class="ce-mm-fan-pulse__row-label">HOMETOWN REACTION</div>' +
              '<div class="ce-mm-fan-pulse__row-text">' + escapeHtml(hp.phrase) + '</div>' +
            '</div>';
          }).join('')
        : '') +
      '<div class="ce-mm-fan-pulse__row">' +
        '<div class="ce-mm-fan-pulse__row-label">PREVIOUS MEETINGS</div>' +
        '<div class="ce-mm-fan-pulse__row-text">' + (data.n_previous_meetings || 0) + ' fight' + ((data.n_previous_meetings || 0) !== 1 ? 's' : '') + ' on record.</div>' +
      '</div>' +
    '</div>';
    showModalContent('FAN PULSE', html);
  }

  // ============================================================
  // MODAL HELPERS
  // ============================================================
  function showModalLoading(title, msg) {
    closeModal();
    var overlay = document.createElement('div');
    overlay.className = 'ce-mm-modal-overlay';
    overlay.id = 'ce-mm-modal';
    overlay.innerHTML = '<div class="ce-mm-modal">' +
      '<div class="ce-mm-modal-header">' +
        '<div class="ce-mm-modal-title">' + escapeHtml(title) + '</div>' +
        '<button class="ce-mm-modal-close" id="ce-mm-modal-close" type="button">×</button>' +
      '</div>' +
      '<div class="ce-mm-modal-body">' +
        '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">' + escapeHtml(msg) + '</div></div>' +
      '</div>' +
    '</div>';
    document.body.appendChild(overlay);
    wireModalClose();
  }

  function showModalContent(title, bodyHtml) {
    var overlay = document.getElementById('ce-mm-modal');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'ce-mm-modal-overlay';
      overlay.id = 'ce-mm-modal';
      document.body.appendChild(overlay);
    }
    overlay.innerHTML = '<div class="ce-mm-modal">' +
      '<div class="ce-mm-modal-header">' +
        '<div class="ce-mm-modal-title">' + escapeHtml(title) + '</div>' +
        '<button class="ce-mm-modal-close" id="ce-mm-modal-close" type="button">×</button>' +
      '</div>' +
      '<div class="ce-mm-modal-body">' + bodyHtml + '</div>' +
    '</div>';
    wireModalClose();
  }

  function showModalError(title, msg) {
    showModalContent(title, '<div class="ce-error-banner"><div class="ce-error-banner__title">' + escapeHtml(title) + '</div><div>' + escapeHtml(String(msg)) + '</div></div>');
  }

  function closeModal() {
    var overlay = document.getElementById('ce-mm-modal');
    if (overlay) overlay.remove();
  }

  function wireModalClose() {
    var overlay = document.getElementById('ce-mm-modal');
    if (!overlay) return;
    var closeBtn = document.getElementById('ce-mm-modal-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', closeModal);
    }
    overlay.addEventListener('click', function (evt) {
      if (evt.target === overlay) closeModal();
    });
    document.addEventListener('keydown', function (evt) {
      if (evt.key === 'Escape') closeModal();
    });
  }

  // ============================================================
  // TOAST
  // ============================================================
  function showToast(msg, kind) {
    var existing = document.querySelector('.ce-mm-toast');
    if (existing) existing.remove();
    var toast = document.createElement('div');
    toast.className = 'ce-mm-toast ce-mm-toast--' + (kind || 'info');
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 4500);
  }

  // ============================================================
  // RELOAD — fetch fresh matchmaking data after a mutation
  // ============================================================
  function reloadCard() {
    return window.CE.bridge.getMatchmakingData(state.eventId).then(function (data) {
      if (!data || !data.ok) {
        showToast('Reload failed: ' + (data && data.error ? data.error : 'unknown'), 'error');
        return;
      }
      state.event = data.event;
      state.promo = data.promo;
      state.eligibleFighters = data.eligible_fighters || [];
      state.bookedFights = data.booked_fights || [];
      state.cardPreview = data.card_preview || null;
      state.cardConfirmed = !!data.card_confirmed;
      // If confirmed, the stagedFights ARE the bookedFights (locked).
      if (state.cardConfirmed) {
        state.stagedFights = state.bookedFights.slice();
      } else {
        state.stagedFights = [];
      }
      render();
      // P5.1 — refresh suggestions after a card mutation (a fighter
      // booked on the card is no longer eligible for suggestions).
      fetchSuggestedMatchups();
    }).catch(function (err) {
      console.error('[matchmaking] reload failed:', err);
    });
  }

  // ============================================================
  // PUBLIC API
  // ============================================================
  function loadAndRender(eventId) {
    state.eventId = eventId ? parseInt(eventId, 10) : null;
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Loading matchmaking…</div></div>';
    }
    // P5.1 — reset suggestions on each fresh load.
    state.suggestedMatchups = [];
    state.suggestionsLoading = !!state.eventId;
    state.suggestionsOpen = true;  // default open on each load
    if (!state.eventId) {
      render();
      return Promise.resolve();
    }
    return window.CE.bridge.getMatchmakingData(state.eventId).then(function (data) {
      if (!data || !data.ok) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Matchmaking failed</div><div>' + escapeHtml(data ? data.error : 'unknown') + '</div></div>';
        }
        return;
      }
      state.event = data.event;
      state.promo = data.promo;
      state.eligibleFighters = data.eligible_fighters || [];
      state.bookedFights = data.booked_fights || [];
      state.cardPreview = data.card_preview || null;
      state.cardConfirmed = !!data.card_confirmed;
      state.redCorner = null;
      state.blueCorner = null;
      state.rivalryPartnerIds = {};
      // If confirmed, the stagedFights ARE the bookedFights (locked).
      if (state.cardConfirmed) {
        state.stagedFights = state.bookedFights.slice();
        // Fetch the projection.
        var projPromise = fetchConfirmedProjection();
        // P5.1 — also fetch suggestions (the player may still want
        // to see angles for the next card).
        fetchSuggestedMatchups();
        return projPromise;
      } else {
        state.stagedFights = [];
        state.lastProjection = null;
        render();
        // P5.1 — fetch suggestions in parallel (they render in the
        // panel below the card list once they arrive).
        fetchSuggestedMatchups();
      }
    }).catch(function (err) {
      console.error('[matchmaking] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Matchmaking failed</div><div>' + escapeHtml(String(err)) + '</div></div>';
      }
    });
  }

  return {
    loadAndRender: loadAndRender,
    render: render,
  };
})();
