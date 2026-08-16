/* ============================================================
   CAGE EMPIRE — Fight Night Screen ("FIGHT NIGHT")
   ============================================================
   Task FIGHT-NIGHT-SHOWCASE. The showcase feature — live play-by-
   play. Per docs/RESEARCH_FIGHT_NIGHT.md §7.4 + GUI_PLAN §7.1.

   3 phases per fight (state machine):
     1. PRE-FIGHT  — Tale of tape + punditry "might" analysis +
                     rivalry/memory context. 5s timer (auto-advance
                     to LIVE) with a "Skip to Fight" button.
     2. LIVE       — 4-zone fixed grid (no scroll): Commentary Feed
                     / Fight Status / Fight Tracker / Key Moments.
                     Speed controls: 1x / 2x / 4x / Pause / Skip to
                     Finish. Beats are appended one at a time at the
                     chosen speed; Zone B/C update per beat.
     3. RECAP      — Result card (winner + method + round/time) +
                     stat changes (record, title, injury) + news
                     item + key moments + (if last fight) show
                     rating panel. "Next Fight" or "Done" button.

   Entry points (wired in app.js):
     - navigate('fight_resolution', {event_id: X}) — opens Fight
       Night with the player's scheduled event. If X has unresolved
       fights, the screen previews the next one + auto-resolves on
       "Start Fight" / pre-fight timer expire.
     - navigate('fight_resolution', {fight_id: Y}) — REPLAY mode.
       Y is a resolved fight; the screen reads existing beats from
       the DB (no resolve_next_fight call).
     - navigate('fight_resolution') — no params: shows the list of
       events with unresolved fights (the player picks one).

   Voice compliance (CONVENTIONS §14 + VOICE_ENFORCEMENT.md):
     - Commentary uses serif font (Source Serif Pro 14px italic).
     - NO raw rating ints — voice phrases only ("a statement
       performance" not "perf=82").
     - Momentum shown as a visual bar that swings red/blue (not
       numbers).
     - Damage shown as glow on head/body/legs indicators (not HP).
     - Ownership language ("YOUR fighter", "YOUR champion") on
       result card.
     - Specific imagery, short fragmentary sentences, no tabloid.
   ============================================================ */

window.CE = window.CE || {};

window.CE.fightNight = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    phase: 'loading',           // 'loading'|'prefight'|'live'|'recap'|'empty'
    mode: 'live',               // Always 'live' — replay mode removed (CLEANUP-AND-FIX Bug 8)
    event_id: null,             // the player's scheduled event (live mode)
    fight_id: null,             // the fight being shown (resolved by API)
    fight_data: null,           // the full payload from get_fight_night_data
    speed: 1,                   // 1 | 2 | 4 | 0 (paused)
    beat_index: 0,              // current beat being shown (live phase)
    beat_timer: null,           // setInterval handle for beat replay
    prefight_timer: null,       // setInterval handle for prefight countdown
    prefight_elapsed: 0,        // ms elapsed in prefight
    prefight_duration: 5000,    // 5s pre-fight build-up
    cum_momentum: 0,            // running momentum (live phase)
    red_damage: 0,              // running damage to red (live)
    blue_damage: 0,             // running damage to blue (live)
    events_with_unresolved: [], // for the no-params "list of events" view
  };

  // Speed → ms per beat mapping. 1x is intentionally slower than real-
  // time (a 5-round fight at 1x takes ~2-5 minutes per the spec).
  var SPEED_MS = { 1: 800, 2: 400, 4: 200 };

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
    var y = parseInt(parts[0], 10);
    var m = parseInt(parts[1], 10);
    var d = parseInt(parts[2], 10);
    var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return (MONTHS[m - 1] || '?') + ' ' + d + ', ' + y;
  }

  function formatTime(seconds) {
    if (!seconds || seconds < 0) seconds = 0;
    var m = Math.floor(seconds / 60);
    var s = Math.floor(seconds % 60);
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function decodePhrase(stored) {
    if (!stored) return '';
    var parts = String(stored).split('||');
    return parts.length >= 2 ? parts[1] : stored;
  }

  /** Return the fighter-name HTML span — gold link if clickable. */
  function fighterSpan(f) {
    if (!f) return '<span class="ce-fn__empty-context">—</span>';
    var name = f.name || '—';
    var nick = f.nickname ? ' "' + f.nickname + '"' : '';
    if (f.fighter_id) {
      return '<a class="ce-link" href="#" data-fighter-id="' +
        f.fighter_id + '">' + escapeHtml(name) + escapeHtml(nick) + '</a>';
    }
    return '<span>' + escapeHtml(name) + escapeHtml(nick) + '</span>';
  }

  function fighterInitial(name) {
    if (!name) return '?';
    return name.charAt(0).toUpperCase();
  }

  /** Get an <img> tag for the fighter portrait, or a letter fallback. */
  function portraitHtml(f, size_class) {
    size_class = size_class || '';
    if (f && f.portrait_data_uri) {
      return '<img src="' + f.portrait_data_uri + '" alt="' +
        escapeHtml(f.name || 'Fighter') + '" class="ce-fn__tape-portrait ' +
        size_class + '" />';
    }
    var initial = fighterInitial((f && f.name) || '');
    return '<div class="ce-fn__tape-portrait ' + size_class + '">' +
      escapeHtml(initial) + '</div>';
  }

  function portraitHtmlStatus(f, size_class) {
    size_class = size_class || '';
    if (f && f.portrait_data_uri) {
      return '<img src="' + f.portrait_data_uri + '" alt="' +
        escapeHtml(f.name || 'Fighter') + '" class="ce-fn__status-portrait ' +
        size_class + '" />';
    }
    var initial = fighterInitial((f && f.name) || '');
    return '<div class="ce-fn__status-portrait ' + size_class + '">' +
      escapeHtml(initial) + '</div>';
  }

  /** Momentum bar visual: shifts red/blue based on cum_momentum. */
  function momentumBarHtml(cum_momentum) {
    // cum_momentum is signed: positive favors red, negative favors blue.
    // Cap at ±300 for visual purposes (a knockdown = +80, near_finish = +60).
    var cap = 300;
    var pct = Math.min(Math.abs(cum_momentum) / cap, 1) * 50; // max 50% from center
    var redWidth, blueWidth;
    if (cum_momentum >= 0) {
      redWidth = pct;
      blueWidth = 0;
    } else {
      redWidth = 0;
      blueWidth = pct;
    }
    return '' +
      '<div class="ce-fn__momentum-bar">' +
        '<div class="ce-fn__momentum-fill-red" style="width:' + redWidth + '%; right:50%;"></div>' +
        '<div class="ce-fn__momentum-fill-blue" style="width:' + blueWidth + '%; left:50%;"></div>' +
        '<div class="ce-fn__momentum-center"></div>' +
      '</div>';
  }

  /** Damage indicator: 0=none, 1=light, 2=heavy, 3=critical. */
  function damageZoneClass(dmg_value) {
    if (!dmg_value || dmg_value <= 0) return '';
    if (dmg_value < 15) return ' ce-fn__dmg-zone--hit-1';
    if (dmg_value < 35) return ' ce-fn__dmg-zone--hit-2';
    return ' ce-fn__dmg-zone--hit-3';
  }

  function phaseLabel(phase) {
    var m = {
      'standing': 'STANDING',
      'clinch': 'CLINCH',
      'cage': 'CAGE',
      'ground_top': 'TOP CONTROL',
      'ground_bottom': 'BOTTOM',
      'scramble': 'SCRAMBLE',
    };
    return m[phase] || phase.toUpperCase();
  }

  function phaseClass(phase) {
    return 'ce-fn__phase-pill--' + phase;
  }

  /** Convert result_type to a voice phrase for the recap. */
  function resultPhraseVoice(result_type, finish_round, finish_time) {
    if (!result_type) return '';
    var round_word = roundWord(finish_round);
    var time_phrase = finishTimePhrase(finish_time);
    var m = {
      'ko_tko': 'by KO/TKO in the ' + round_word + ' round' + time_phrase,
      'submission': 'by submission in the ' + round_word + ' round' + time_phrase,
      'doctor_stoppage': 'by doctor stoppage after the ' + round_word + ' round',
      'corner_stoppage': 'by corner stoppage after the ' + round_word + ' round',
      'dq': 'by DQ in the ' + round_word + ' round' + time_phrase,
      'unanimous_decision': 'by unanimous decision',
      'split_decision': 'by split decision',
      'majority_decision': 'by majority decision',
      'decision': 'by decision',
      'draw': 'via draw',
      'no_contest': 'via no contest',
    };
    return m[result_type] || result_type.replace('_', ' ');
  }

  function roundWord(r) {
    var m = { 1: 'first', 2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth' };
    return m[r] || 'championship';
  }

  function finishTimePhrase(t) {
    if (!t || t === '5:00' || t === '0:00') return '';
    try {
      var parts = t.split(':');
      if (parts.length !== 2) return '';
      var total = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
      if (total < 60) return ' in the opening minute';
      if (total < 120) return ' past the midway mark';
      if (total < 180) return ' late in the round';
      if (total < 240) return ' as the round wound down';
      return ' deep into the round';
    } catch (e) { return ''; }
  }

  // ============================================================
  // ENTRY POINT
  // ============================================================
  function loadAndRender() {
    var params = window.CE.app ? window.CE.app.getActiveParams() : {};
    state.event_id = params.event_id || params.eventId || null;
    state.fight_id = params.fight_id || params.fightId || null;
    // CLEANUP-AND-FIX Bug 8 — replay mode removed. state.mode is
    // always 'live'. When a fight_id is provided AND the fight is
    // already resolved, we jump straight to renderRecap (no
    // beat-by-beat animation). Otherwise we fall through to live
    // resolution.
    state.mode = 'live';

    // P3.4 — defensive: release any stale advance-day lock from a
    // previous Fight Night session that was interrupted (e.g. the
    // player navigated away mid-fight via the sidebar). The lock
    // will be re-acquired when startLive() runs.
    setAdvanceDayLock(false);

    renderLoading();

    if (state.fight_id) {
      // Direct navigation to a fight — load its data. If it's
      // already resolved, show the recap directly (no animation).
      // If unresolved (rare — deep-link to a scheduled but
      // unplayed fight), fall through to live mode.
      window.CE.bridge.getFightNightData(state.fight_id).then(function (data) {
        if (!data || !data.ok) {
          renderEmpty(data && data.message ? data.message :
            'Could not load this fight.');
          return;
        }
        state.fight_data = data;
        if (data.is_resolved) {
          // Skip pre-fight + live — go straight to the result.
          // Release any advance-day lock since we're not animating.
          setAdvanceDayLock(false);
          renderRecap();
        } else {
          startPreFight();
        }
      }).catch(function (err) {
        console.error('[fight_night] getFightNightData failed:', err);
        renderEmpty('Could not load this fight.');
      });
    } else {
      // Live mode — preview the next unresolved fight on the player's promo.
      window.CE.bridge.getFightNightData(null).then(function (data) {
        if (!data || !data.ok) {
          renderEmpty(data && data.message ?
            data.message : 'No unresolved fights on your schedule.');
          return;
        }
        state.fight_data = data;
        startPreFight();
      }).catch(function (err) {
        console.error('[fight_night] getFightNightData failed:', err);
        renderEmpty('Could not load Fight Night.');
      });
    }
  }

  // ============================================================
  // PHASE 1 — PRE-FIGHT BUILD-UP
  // ============================================================
  function startPreFight() {
    state.phase = 'prefight';
    state.prefight_elapsed = 0;
    renderPreFight();
    // Start the pre-fight timer (auto-advances to LIVE after 5s).
    if (state.prefight_timer) clearInterval(state.prefight_timer);
    state.prefight_timer = setInterval(function () {
      state.prefight_elapsed += 100;
      var pct = (state.prefight_elapsed / state.prefight_duration) * 100;
      var fill = document.querySelector('.ce-fn__prefight-timer-fill');
      if (fill) fill.style.width = Math.min(pct, 100) + '%';
      if (state.prefight_elapsed >= state.prefight_duration) {
        clearInterval(state.prefight_timer);
        startLive();
      }
    }, 100);
  }

  function renderLoading() {
    state.phase = 'loading';
    var host = document.getElementById('screen-content');
    if (!host) return;
    host.innerHTML = '<div class="ce-fn">' +
      '<div class="ce-fn__loading">' +
        '<div class="ce-loading__spinner"></div>' +
        '<div class="ce-fn__loading-text">Walking to the cage…</div>' +
      '</div>' +
    '</div>';
  }

  function renderEmpty(message) {
    state.phase = 'empty';
    // P3.4 — release the advance-day lock when there's no fight to
    // watch (the player shouldn't be locked out of advancing just
    // because Fight Night has nothing to show).
    setAdvanceDayLock(false);
    var host = document.getElementById('screen-content');
    if (!host) return;
    host.innerHTML = '<div class="ce-fn">' +
      '<div class="ce-fn__empty">' +
        '<div class="ce-fn__empty-icon">🔥</div>' +
        '<div class="ce-fn__empty-title">Fight Night Awaits</div>' +
        '<div class="ce-fn__empty-body">' + escapeHtml(message || 'No unresolved fights on your schedule. Build a card, then come back to fight it out.') + '</div>' +
        '<button class="ce-fn__action-btn ce-fn__action-btn--secondary" id="ce-fn-empty-back">Back to Dashboard</button>' +
      '</div>' +
    '</div>';
    var backBtn = document.getElementById('ce-fn-empty-back');
    if (backBtn) backBtn.addEventListener('click', function () {
      window.CE.app.navigate('dashboard');
    });
  }

  function renderPreFight() {
    var d = state.fight_data;
    if (!d) return;
    var host = document.getElementById('screen-content');
    if (!host) return;

    var red = d.red || {};
    var blue = d.blue || {};

    // Tale of Tape.
    var tapeStats = '' +
      '<div class="ce-fn__tape-stats">' +
        tapeRow('RECORD', red.record_str || '—', blue.record_str || '—') +
        tapeRow('WEIGHT CLASS', d.fight.weight_class_name || '—', d.fight.weight_class_name || '—') +
        tapeRow('RANK', red.rank_str || 'Unranked', blue.rank_str || 'Unranked') +
        tapeRow('STYLE', red.style_archetype_name || '—', blue.style_archetype_name || '—') +
        tapeRow('AGE', red.age != null ? red.age : '—', blue.age != null ? blue.age : '—') +
        tapeRow('STREAK', red.streak_phrase || '—', blue.streak_phrase || '—') +
      '</div>';

    // Punditry "might" analysis (from matchup_analyses).
    var pundit_card = '';
    if (d.matchup_analysis && d.matchup_analysis.analysis_text) {
      pundit_card = '' +
        '<div class="ce-fn__context-card">' +
          '<div class="ce-fn__context-card-title">PUNDITRY · EARLY READ</div>' +
          '<div class="ce-fn__context-card-body">' + escapeHtml(d.matchup_analysis.analysis_text) + '</div>' +
          (d.matchup_analysis.style_edge ?
            '<div class="ce-fn__context-card-chips"><span class="ce-chip ce-chip-default">' + escapeHtml(d.matchup_analysis.style_edge) + '</span></div>' : '') +
        '</div>';
    } else {
      pundit_card = '' +
        '<div class="ce-fn__context-card">' +
          '<div class="ce-fn__context-card-title">PUNDITRY · EARLY READ</div>' +
          '<div class="ce-fn__empty-context">The pundits are still weighing this one. A close fight on paper.</div>' +
        '</div>';
    }

    // Rivalry context.
    var rivalry_card = '';
    if (d.rivalry && d.rivalry.bad_blood) {
      rivalry_card = '' +
        '<div class="ce-fn__context-card ce-fn__context-card--rivalry">' +
          '<div class="ce-fn__context-card-title">⚔ BAD BLOOD</div>' +
          '<div class="ce-fn__context-card-body">' +
            escapeHtml(d.rivalry.rivalry_type_label || 'These two have history.') +
            (d.rivalry.fights_count > 0 ?
              ' They\'ve met ' + d.rivalry.fights_count + ' time' + (d.rivalry.fights_count === 1 ? '' : 's') +
              ' before — ' + d.rivalry.red_wins + ' to ' + d.rivalry.blue_wins +
              (d.rivalry.draws > 0 ? ' with ' + d.rivalry.draws + ' draw' + (d.rivalry.draws === 1 ? '' : 's') : '') + '.' : '') +
          '</div>' +
          (d.rivalry.origin_description ?
            '<div class="ce-fn__context-card-body" style="font-size:12px;">"' + escapeHtml(d.rivalry.origin_description) + '"</div>' : '') +
        '</div>';
    }

    // Previous meetings (memory context).
    var memory_card = '';
    if (d.previous_meetings && d.previous_meetings.length > 0) {
      var meetings_count = d.previous_meetings.length;
      var red_wins = 0, blue_wins = 0, draws = 0;
      d.previous_meetings.forEach(function (m) {
        if (m.outcome_red === 'win') red_wins++;
        else if (m.outcome_red === 'loss') blue_wins++;
        else if (m.outcome_red === 'draw') draws++;
      });
      var series_phrase;
      if (red_wins === blue_wins) {
        series_phrase = 'series tied ' + red_wins + '-' + blue_wins +
          (draws > 0 ? '-' + draws : '');
      } else if (red_wins > blue_wins) {
        series_phrase = escapeHtml(red.name) + ' leads ' + red_wins + '-' + blue_wins +
          (draws > 0 ? '-' + draws : '');
      } else {
        series_phrase = escapeHtml(blue.name) + ' leads ' + blue_wins + '-' + red_wins +
          (draws > 0 ? '-' + draws : '');
      }
      var meeting_word = meetings_count === 1 ? 'First meeting' :
        (meetings_count === 2 ? 'Second meeting' :
        (meetings_count === 3 ? 'Third meeting' :
        (meetings_count === 4 ? 'Fourth meeting' : 'Rubber match')));
      memory_card = '' +
        '<div class="ce-fn__context-card ce-fn__context-card--memory">' +
          '<div class="ce-fn__context-card-title">PREVIOUS MEETINGS</div>' +
          '<div class="ce-fn__context-card-body">' + meeting_word + ' — ' + series_phrase + '.</div>' +
        '</div>';
    }

    // Title fight badge (if applicable).
    var title_badge = d.fight.is_title_fight ?
      '<span class="ce-fn__title-badge">🥇 TITLE FIGHT</span>' : '';

    host.innerHTML = '' +
      '<div class="ce-fn">' +
        '<div class="ce-fn__prefight-timer"><div class="ce-fn__prefight-timer-fill"></div></div>' +
        '<div class="ce-fn__prefight">' +
          '<div class="ce-fn__prefight-header">' +
            '<div class="ce-fn__prefight-eyebrow">FIGHT NIGHT · ' + escapeHtml(d.event.event_name || 'TEST CARD') + ' · ' + escapeHtml(formatDate(d.event.event_date)) + '</div>' +
            '<button class="ce-fn__prefight-skip-btn" id="ce-fn-skip-prefight">▶ Skip to Fight</button>' +
          '</div>' +
          '<div class="ce-fn__tape">' +
            '<div class="ce-fn__tape-corner ce-fn__tape-corner--red">' +
              portraitHtml(red) +
              '<div class="ce-fn__tape-name">' + escapeHtml(red.name || '—') + '</div>' +
              (red.nickname ? '<div class="ce-fn__tape-nickname">\'' + escapeHtml(red.nickname) + '\'</div>' : '') +
              '<div class="ce-fn__tape-record">' + escapeHtml(red.record_str || '—') + '</div>' +
              '<div class="ce-fn__tape-corner-chips">' +
                (red.rank_str && red.rank_str !== 'Unranked' ? '<span class="ce-chip ce-chip-default">' + escapeHtml(red.rank_str) + '</span>' : '') +
                (red.title_chip && red.title_chip.holds_title ? '<span class="ce-chip ce-chip-gold">CHAMP</span>' : '') +
                '<span class="ce-chip ce-chip-default">' + escapeHtml(red.style_archetype_name || 'Balanced') + '</span>' +
              '</div>' +
            '</div>' +
            '<div class="ce-fn__tape-vs">' +
              title_badge +
              '<div>VS</div>' +
              '<div class="ce-fn__tape-vs-small">' + escapeHtml(d.fight.card_slot_label || 'PRELIM') + '</div>' +
            '</div>' +
            '<div class="ce-fn__tape-corner ce-fn__tape-corner--blue">' +
              portraitHtml(blue) +
              '<div class="ce-fn__tape-name">' + escapeHtml(blue.name || '—') + '</div>' +
              (blue.nickname ? '<div class="ce-fn__tape-nickname">\'' + escapeHtml(blue.nickname) + '\'</div>' : '') +
              '<div class="ce-fn__tape-record">' + escapeHtml(blue.record_str || '—') + '</div>' +
              '<div class="ce-fn__tape-corner-chips">' +
                (blue.rank_str && blue.rank_str !== 'Unranked' ? '<span class="ce-chip ce-chip-default">' + escapeHtml(blue.rank_str) + '</span>' : '') +
                (blue.title_chip && blue.title_chip.holds_title ? '<span class="ce-chip ce-chip-gold">CHAMP</span>' : '') +
                '<span class="ce-chip ce-chip-default">' + escapeHtml(blue.style_archetype_name || 'Balanced') + '</span>' +
              '</div>' +
            '</div>' +
            tapeStats +
          '</div>' +
          '<div class="ce-fn__context-grid">' +
            pundit_card +
            (rivalry_card || memory_card) +
            (rivalry_card && memory_card ?
              '<div class="ce-fn__context-card ce-fn__context-card--show" style="grid-column:1/-1;">' +
                '<div class="ce-fn__context-card-title">SHOW CONTEXT</div>' +
                '<div class="ce-fn__context-card-body">A fight with weight. The result will reshape the division.</div>' +
              '</div>' : '') +
          '</div>' +
        '</div>' +
      '</div>';

    var skipBtn = document.getElementById('ce-fn-skip-prefight');
    if (skipBtn) skipBtn.addEventListener('click', function () {
      if (state.prefight_timer) clearInterval(state.prefight_timer);
      startLive();
    });
  }

  function tapeRow(label, red_val, blue_val) {
    return '' +
      '<div class="ce-fn__tape-stat-red">' + escapeHtml(red_val) + '</div>' +
      '<div class="ce-fn__tape-stat-label">' + escapeHtml(label) + '</div>' +
      '<div class="ce-fn__tape-stat-blue">' + escapeHtml(blue_val) + '</div>';
  }

  // ============================================================
  // PHASE 2 — LIVE FIGHT (4-zone fixed grid)
  // ============================================================
  function startLive() {
    state.phase = 'live';
    // P3.4 — disable "Advance Day" during live commentary. The user
    // complaint #5: "Advance Day header should be disabled during
    // live commentary." Re-enabled when the fight completes (recap)
    // or the player exits. The button is wired in app.js::wireAdvanceDay;
    // we just toggle its disabled state from here.
    setAdvanceDayLock(true);

    // In live mode (not replay), we need to resolve the fight first.
    // If state.fight_data.is_resolved is true (replay mode), skip
    // the resolve call.
    if (state.mode === 'live' && !state.fight_data.is_resolved) {
      // Resolve the next fight, then re-load the data.
      renderResolving();
      window.CE.bridge.resolveNextFight(state.event_id).then(function (result) {
        if (!result || !result.ok) {
          setAdvanceDayLock(false);
          renderEmpty(result && result.message ?
            result.message : 'Could not resolve this fight.');
          return;
        }
        state.fight_id = result.fight_id;
        // Now load the full fight data (with beats).
        return window.CE.bridge.getFightNightData(result.fight_id);
      }).then(function (data) {
        if (!data || !data.ok) {
          setAdvanceDayLock(false);
          renderEmpty('Could not load the resolved fight.');
          return;
        }
        state.fight_data = data;
        renderLive();
        startBeatReplay();
      }).catch(function (err) {
        console.error('[fight_night] resolve_next_fight failed:', err);
        setAdvanceDayLock(false);
        renderEmpty('Could not resolve this fight.');
      });
    } else {
      renderLive();
      startBeatReplay();
    }
  }

  // P3.4 — toggle the "Advance Day" button's disabled state. Called
  // with `true` at the start of live commentary, `false` when the
  // fight completes (recap) or the player exits. Defensive: the
  // button may not exist (e.g. during pre-game), so guard with a
  // null check.
  function setAdvanceDayLock(locked) {
    var btn = document.getElementById('advance-day-btn');
    if (!btn) return;
    btn.disabled = !!locked;
    if (locked) {
      btn.classList.add('ce-top-bar__btn--locked');
    } else {
      btn.classList.remove('ce-top-bar__btn--locked');
    }
  }

  function renderResolving() {
    var host = document.getElementById('screen-content');
    if (!host) return;
    host.innerHTML = '<div class="ce-fn">' +
      '<div class="ce-fn__loading">' +
        '<div class="ce-loading__spinner"></div>' +
        '<div class="ce-fn__loading-text">The fight is on…</div>' +
      '</div>' +
    '</div>';
  }

  function renderLive() {
    var d = state.fight_data;
    if (!d) return;
    var host = document.getElementById('screen-content');
    if (!host) return;

    var red = d.red || {};
    var blue = d.blue || {};

    // Reset live-phase state.
    state.beat_index = 0;
    state.cum_momentum = 0;
    state.red_damage = 0;
    state.blue_damage = 0;
    state.speed = 1;

    host.innerHTML = '' +
      '<div class="ce-fn">' +
        '<header class="ce-fn__header">' +
          '<div class="ce-fn__title-block">' +
            '<div class="ce-fn__event-name">' + escapeHtml(d.event.event_name || 'Fight Night') + '</div>' +
            '<div class="ce-fn__event-meta">' + escapeHtml(formatDate(d.event.event_date)) + (d.event.venue_name ? ' · ' + escapeHtml(d.event.venue_name) : '') + '</div>' +
          '</div>' +
          '<div class="ce-fn__header-spacer"></div>' +
          // P3.4 — beat counter is hidden via CSS (.ce-fn__progress-count
          // { display: none }). Kept in the DOM for debugging + future
          // toggling; the user complaint #6 said "No of beats should be
          // hidden" so we don't render it visibly.
          '<div class="ce-fn__progress">' +
            '<span class="ce-fn__progress-count" id="ce-fn-beat-counter">Beat 0 / ' + (d.beats ? d.beats.length : 0) + '</span>' +
          '</div>' +
          '<div class="ce-fn__speed-controls">' +
            '<button class="ce-fn__speed-btn" data-speed="0" id="ce-fn-speed-pause" title="Pause">⏸ Pause</button>' +
            '<button class="ce-fn__speed-btn ce-fn__speed-btn--active" data-speed="1" id="ce-fn-speed-1">▶ 1x</button>' +
            '<button class="ce-fn__speed-btn" data-speed="2" id="ce-fn-speed-2">▶▶ 2x</button>' +
            '<button class="ce-fn__speed-btn" data-speed="4" id="ce-fn-speed-4">▶▶▶ 4x</button>' +
          '</div>' +
          // P3.4 — large, prominent "Skip to End" button. Separate
          // from the smaller ⏭ Skip to Finish button (which lived in
          // the speed-control group). This is the marquee "I'm done
          // watching, show me the result" affordance.
          '<button class="ce-fn__skip-end-btn" id="ce-fn-skip-end" title="Skip to the result">⏭ Skip to End</button>' +
          '<button class="ce-fn__exit-btn" id="ce-fn-exit-live">Exit</button>' +
        '</header>' +
        '<div class="ce-fn__live">' +
          // Zone A — Commentary Feed
          '<div class="ce-fn__zone ce-fn__zone-a">' +
            '<div class="ce-fn__zone-header">' +
              '<span class="ce-fn__zone-title">COMMENTARY FEED</span>' +
              '<span class="ce-fn__zone-meta" id="ce-fn-commentary-meta">—</span>' +
            '</div>' +
            '<div class="ce-fn__zone-body" id="ce-fn-commentary-feed" style="padding:0;"></div>' +
          '</div>' +
          // Zone B — Fight Status
          '<div class="ce-fn__zone ce-fn__zone-b">' +
            '<div class="ce-fn__zone-header">' +
              '<span class="ce-fn__zone-title">FIGHT STATUS</span>' +
              '<span class="ce-fn__zone-meta" id="ce-fn-status-meta">—</span>' +
            '</div>' +
            '<div class="ce-fn__zone-body" style="padding:0;">' +
              '<div class="ce-fn__status">' +
                '<div class="ce-fn__status-fighters">' +
                  '<div class="ce-fn__status-corner">' +
                    portraitHtmlStatus(red) +
                    '<div class="ce-fn__status-name">' + escapeHtml(red.name || '—') + '</div>' +
                    '<div class="ce-fn__status-record">' + escapeHtml(red.record_str || '—') + '</div>' +
                    '<div class="ce-fn__status-damage" id="ce-fn-dmg-red">' +
                      '<div class="ce-fn__dmg-zone" title="Head">H</div>' +
                      '<div class="ce-fn__dmg-zone" title="Body">B</div>' +
                      '<div class="ce-fn__dmg-zone" title="Legs">L</div>' +
                    '</div>' +
                  '</div>' +
                  '<div class="ce-fn__status-corner ce-fn__status-corner--blue">' +
                    portraitHtmlStatus(blue) +
                    '<div class="ce-fn__status-name">' + escapeHtml(blue.name || '—') + '</div>' +
                    '<div class="ce-fn__status-record">' + escapeHtml(blue.record_str || '—') + '</div>' +
                    '<div class="ce-fn__status-damage" id="ce-fn-dmg-blue">' +
                      '<div class="ce-fn__dmg-zone" title="Head">H</div>' +
                      '<div class="ce-fn__dmg-zone" title="Body">B</div>' +
                      '<div class="ce-fn__dmg-zone" title="Legs">L</div>' +
                    '</div>' +
                  '</div>' +
                '</div>' +
                '<div class="ce-fn__status-scorecard" id="ce-fn-scorecard">' +
                  '<div class="ce-fn__scorecard-row">' +
                    '<span class="ce-fn__scorecard-round-label">RD</span>' +
                    '<span class="ce-fn__scorecard-cell">RED</span>' +
                    '<span class="ce-fn__scorecard-cell">BLUE</span>' +
                  '</div>' +
                '</div>' +
                '<div class="ce-fn__status-momentum">' +
                  '<div class="ce-fn__momentum-label">MOMENTUM</div>' +
                  '<div id="ce-fn-momentum">' + momentumBarHtml(0) + '</div>' +
                  '<div class="ce-fn__momentum-corners">' +
                    '<span class="ce-fn__momentum-corner--red">' + escapeHtml(red.name || 'RED') + '</span>' +
                    '<span class="ce-fn__momentum-corner--blue">' + escapeHtml(blue.name || 'BLUE') + '</span>' +
                  '</div>' +
                '</div>' +
              '</div>' +
            '</div>' +
          '</div>' +
          // Zone C — Fight Tracker
          '<div class="ce-fn__zone ce-fn__zone-c">' +
            '<div class="ce-fn__zone-header">' +
              '<span class="ce-fn__zone-title">FIGHT TRACKER</span>' +
              '<span class="ce-fn__zone-meta" id="ce-fn-tracker-meta">—</span>' +
            '</div>' +
            '<div class="ce-fn__zone-body" style="padding:0;">' +
              '<div class="ce-fn__tracker">' +
                '<div class="ce-fn__tracker-tile">' +
                  '<div class="ce-fn__tracker-label">ROUND CLOCK</div>' +
                  '<div class="ce-fn__tracker-value ce-fn__tracker-value--gold" id="ce-fn-round-clock">5:00</div>' +
                '</div>' +
                '<div class="ce-fn__tracker-tile">' +
                  '<div class="ce-fn__tracker-label">CURRENT ROUND</div>' +
                  '<div class="ce-fn__tracker-value" id="ce-fn-current-round">1</div>' +
                '</div>' +
                '<div class="ce-fn__tracker-tile">' +
                  '<div class="ce-fn__tracker-label">PHASE</div>' +
                  '<div class="ce-fn__phase-pill ce-fn__phase-pill--standing" id="ce-fn-phase-pill">STANDING</div>' +
                '</div>' +
                '<div class="ce-fn__tracker-tile">' +
                  '<div class="ce-fn__tracker-label">CONTROL TIME</div>' +
                  '<div class="ce-fn__tracker-value ce-fn__tracker-value--small" id="ce-fn-control-time">0:00</div>' +
                '</div>' +
              '</div>' +
            '</div>' +
          '</div>' +
          // Zone D — Key Moments
          '<div class="ce-fn__zone ce-fn__zone-d">' +
            '<div class="ce-fn__zone-header">' +
              '<span class="ce-fn__zone-title">KEY MOMENTS</span>' +
              '<span class="ce-fn__zone-meta" id="ce-fn-moments-meta">—</span>' +
            '</div>' +
            '<div class="ce-fn__zone-body" id="ce-fn-moments-list" style="padding:0;">' +
              '<div class="ce-fn__moments">' +
                '<div class="ce-fn__moments-empty">No key moments yet.</div>' +
              '</div>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';

    wireLiveControls();
  }

  function wireLiveControls() {
    // Speed control buttons.
    var speedBtns = document.querySelectorAll('.ce-fn__speed-btn[data-speed]');
    speedBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var speed = parseInt(btn.getAttribute('data-speed'), 10);
        setSpeed(speed);
      });
    });
    // Pause button.
    var pauseBtn = document.getElementById('ce-fn-speed-pause');
    if (pauseBtn) pauseBtn.addEventListener('click', function () {
      togglePause();
    });
    // P3.4 — Skip to End button (large, prominent — replaces the old
    // ⏭ Skip to Finish button that lived in the speed-control group).
    // Both call skipToFinish() — the difference is visual prominence.
    var skipEndBtn = document.getElementById('ce-fn-skip-end');
    if (skipEndBtn) skipEndBtn.addEventListener('click', function () {
      skipToFinish();
    });
    // Exit button.
    var exitBtn = document.getElementById('ce-fn-exit-live');
    if (exitBtn) exitBtn.addEventListener('click', function () {
      if (state.beat_timer) clearInterval(state.beat_timer);
      // P3.4 — re-enable Advance Day when the player exits the live phase.
      setAdvanceDayLock(false);
      window.CE.app.navigate('dashboard');
    });
  }

  function setSpeed(speed) {
    state.speed = speed;
    // Update the active button.
    var btns = document.querySelectorAll('.ce-fn__speed-btn[data-speed]');
    btns.forEach(function (b) {
      var b_speed = parseInt(b.getAttribute('data-speed'), 10);
      if (b_speed === speed) {
        b.classList.add('ce-fn__speed-btn--active');
      } else {
        b.classList.remove('ce-fn__speed-btn--active');
      }
    });
    // Reset the pause button visual state.
    var pauseBtn = document.getElementById('ce-fn-speed-pause');
    if (pauseBtn) {
      pauseBtn.classList.toggle('ce-fn__speed-btn--active', speed === 0);
    }
    // Restart the timer if we're playing (paused → playing).
    if (speed > 0 && state.phase === 'live' && !state.beat_timer) {
      scheduleNextBeat();
    }
  }

  function togglePause() {
    if (state.speed === 0) {
      // Currently paused — resume at 1x.
      setSpeed(1);
    } else {
      // Currently playing — pause.
      setSpeed(0);
    }
  }

  function scheduleNextBeat() {
    if (state.beat_timer) clearTimeout(state.beat_timer);
    if (state.speed === 0) return;  // paused
    var ms = SPEED_MS[state.speed] || 800;
    state.beat_timer = setTimeout(function () {
      state.beat_timer = null;
      replayNextBeat();
    }, ms);
  }

  function replayNextBeat() {
    var d = state.fight_data;
    if (!d || !d.beats || state.beat_index >= d.beats.length) {
      // All beats replayed — advance to recap.
      finishLive();
      return;
    }
    var beat = d.beats[state.beat_index];
    // P3.5 — before appending the first beat, render any extra
    // segments with beat_index = -1 (the ring announcer intro).
    if (state.beat_index === 0) {
      appendExtraSegmentsForBeatIndex(-1);
    }
    appendBeat(beat);
    // P3.5 — after appending this beat, render any extra segments
    // (pundit / crowd) whose beat_index matches this beat.
    appendExtraSegmentsForBeatIndex(state.beat_index - 1);
    updateStatusZones(beat);
    state.beat_index += 1;
    scheduleNextBeat();
  }

  // P3.5 — render extra commentary segments (announcer / pundit /
  // crowd) for a given beat_index. Called by replayNextBeat: once
  // with beat_index=-1 before the first beat (announcer intro), and
  // once with beat_index=N after the Nth beat (pundit/crowd). The
  // extra_segments array is part of the get_fight_night_data payload.
  function appendExtraSegmentsForBeatIndex(beatIdx) {
    var d = state.fight_data;
    if (!d || !d.extra_segments || !d.extra_segments.length) return;
    var feed = document.getElementById('ce-fn-commentary-feed');
    if (!feed) return;
    var commentaryDiv = feed.querySelector('.ce-fn__commentary');
    if (!commentaryDiv) return;
    d.extra_segments.forEach(function (seg) {
      if (seg.beat_index !== beatIdx) return;
      var segDiv = document.createElement('div');
      // CSS class drives the styling per segment_type.
      segDiv.className = 'ce-fn__beat ce-fn__beat--' + seg.segment_type;
      var speakerLabel = '';
      if (seg.segment_type === 'pundit' && seg.speaker_name) {
        speakerLabel = '<div class="ce-fn__beat-speaker">' +
          escapeHtml(seg.speaker_name.toUpperCase()) + '</div>';
      } else if (seg.segment_type === 'announcer') {
        speakerLabel = '<div class="ce-fn__beat-speaker">RING ANNOUNCER</div>';
      } else if (seg.segment_type === 'crowd') {
        speakerLabel = '<div class="ce-fn__beat-speaker">CROWD</div>';
      }
      // Announcer + crowd have no timestamp; pundit gets the current
      // beat's timestamp (passed in via state.beat_index — but we
      // don't have it here, so we omit the timestamp on pundit too;
      // the speaker label is enough context).
      segDiv.innerHTML = speakerLabel +
        '<div class="ce-fn__beat-text">' + escapeHtml(seg.text || '') + '</div>';
      commentaryDiv.appendChild(segDiv);
    });
    feed.scrollTop = feed.scrollHeight;
  }

  function appendBeat(beat) {
    var feed = document.getElementById('ce-fn-commentary-feed');
    if (!feed) return;
    var commentaryDiv = feed.querySelector('.ce-fn__commentary');
    if (!commentaryDiv) {
      commentaryDiv = document.createElement('div');
      commentaryDiv.className = 'ce-fn__commentary';
      feed.appendChild(commentaryDiv);
    }

    var d = state.fight_data;
    var red_id = d.red ? d.red.fighter_id : null;
    var blue_id = d.blue ? d.blue.fighter_id : null;

    // Determine the corner color of the initiator.
    var corner_class = '';
    if (beat.initiator_fighter_id === red_id) {
      corner_class = 'ce-fn__beat--red';
    } else if (beat.initiator_fighter_id === blue_id) {
      corner_class = 'ce-fn__beat--blue';
    }

    // Highlight class for knockdowns / near-finishes / big momentum.
    var highlight_class = '';
    if (beat.outcome === 'knockdown' || beat.outcome === 'near_finish') {
      highlight_class = 'ce-fn__beat--highlight';
    } else if (Math.abs(beat.momentum_shift || 0) > 50) {
      highlight_class = 'ce-fn__beat--highlight';
    }

    // Detect round-ending beat (next beat has different round_number).
    var is_round_end = (state.beat_index === d.beats.length - 1) ||
      (d.beats[state.beat_index + 1] &&
       d.beats[state.beat_index + 1].round_number !== beat.round_number);

    var round_end_class = is_round_end ? ' ce-fn__beat--round-end' : '';

    // Timestamp: "R2 · B7"
    var timestamp = 'R' + beat.round_number + ' · B' + beat.beat_number;

    var beatDiv = document.createElement('div');
    beatDiv.className = 'ce-fn__beat ' + corner_class + highlight_class + round_end_class;
    beatDiv.innerHTML = '' +
      '<div class="ce-fn__beat-timestamp">' + escapeHtml(timestamp) + '</div>' +
      '<div class="ce-fn__beat-text">' + escapeHtml(beat.commentary_text || '…') + '</div>';
    commentaryDiv.appendChild(beatDiv);

    // Auto-scroll to the bottom of the feed.
    feed.scrollTop = feed.scrollHeight;

    // Update the beat counter.
    var counter = document.getElementById('ce-fn-beat-counter');
    if (counter) {
      counter.textContent = 'Beat ' + (state.beat_index + 1) + ' / ' + d.beats.length;
    }
    // Update commentary meta.
    var cmeta = document.getElementById('ce-fn-commentary-meta');
    if (cmeta) {
      cmeta.textContent = phaseLabel(beat.phase);
    }
  }

  function updateStatusZones(beat) {
    var d = state.fight_data;
    var red_id = d.red ? d.red.fighter_id : null;
    var blue_id = d.blue ? d.blue.fighter_id : null;

    // Update cumulative momentum.
    // momentum_shift is signed from the initiator's perspective:
    // positive = initiator's favor. Convert to red's perspective.
    var shift = beat.momentum_shift || 0;
    if (beat.initiator_fighter_id === red_id) {
      state.cum_momentum += shift;
    } else if (beat.initiator_fighter_id === blue_id) {
      state.cum_momentum -= shift;
    }
    // Update the momentum bar.
    var momEl = document.getElementById('ce-fn-momentum');
    if (momEl) momEl.innerHTML = momentumBarHtml(state.cum_momentum);

    // Update damage indicators. Damage is dealt BY the initiator, so
    // the target takes it.
    if (beat.damage_dealt && beat.damage_dealt > 0) {
      if (beat.target_fighter_id === red_id) {
        state.red_damage += beat.damage_dealt;
      } else if (beat.target_fighter_id === blue_id) {
        state.blue_damage += beat.damage_dealt;
      }
    }
    updateDamageIndicators();

    // Update fight tracker.
    // Round clock: estimate based on beat_number within the round.
    // The engine writes 12-28 beats per round; assume ~5min/round.
    var beats_in_round = 18; // average
    var total_beats_this_round = 1;
    for (var i = state.beat_index; i >= 0; i--) {
      if (d.beats[i].round_number === beat.round_number) {
        total_beats_this_round++;
      } else {
        break;
      }
    }
    var fraction = Math.min(beat.beat_number / beats_in_round, 1);
    var remaining_sec = Math.max(0, 300 - Math.floor(fraction * 300));
    var clockEl = document.getElementById('ce-fn-round-clock');
    if (clockEl) clockEl.textContent = formatTime(remaining_sec);

    var roundEl = document.getElementById('ce-fn-current-round');
    if (roundEl) roundEl.textContent = beat.round_number;

    var phaseEl = document.getElementById('ce-fn-phase-pill');
    if (phaseEl) {
      phaseEl.textContent = phaseLabel(beat.phase);
      phaseEl.className = 'ce-fn__phase-pill ' + phaseClass(beat.phase);
    }

    // Control time: sum of control_time_delta for clinch/cage/ground phases.
    var ctrl_sec = 0;
    for (var j = 0; j <= state.beat_index; j++) {
      var b = d.beats[j];
      if (b.control_time_delta) {
        ctrl_sec += b.control_time_delta;
      }
    }
    var ctrlEl = document.getElementById('ce-fn-control-time');
    if (ctrlEl) ctrlEl.textContent = formatTime(ctrl_sec);

    // Tracker meta.
    var tmeta = document.getElementById('ce-fn-tracker-meta');
    if (tmeta) {
      tmeta.textContent = phaseLabel(beat.phase);
    }

    // Status meta.
    var smeta = document.getElementById('ce-fn-status-meta');
    if (smeta) {
      smeta.textContent = 'R' + beat.round_number + ' · B' + beat.beat_number;
    }

    // Update the scorecard if this beat ended a round.
    var is_round_end = (state.beat_index === d.beats.length - 1) ||
      (d.beats[state.beat_index + 1] &&
       d.beats[state.beat_index + 1].round_number !== beat.round_number);
    if (is_round_end) {
      updateScorecard(beat.round_number);
    }

    // Update key moments list (Zone D) — show highlights whose
    // beat_index is <= state.beat_index. We don't have a direct
    // beat_index → highlight mapping, so we approximate by showing
    // highlights for rounds that have completed.
    updateKeyMoments(beat.round_number);
  }

  function updateDamageIndicators() {
    // Update the 3 damage zones (head/body/legs) for each fighter.
    // Distribute the cumulative damage across zones based on action
    // types we've seen. Simplified: 50% head, 30% body, 20% legs.
    var d = state.fight_data;
    var red_dmg = state.red_damage;
    var blue_dmg = state.blue_damage;
    var dmgZones = ['head', 'body', 'legs'];

    var redContainer = document.getElementById('ce-fn-dmg-red');
    if (redContainer) {
      var zones = redContainer.querySelectorAll('.ce-fn__dmg-zone');
      var dmg_values = [red_dmg * 0.5, red_dmg * 0.3, red_dmg * 0.2];
      zones.forEach(function (zone, i) {
        zone.className = 'ce-fn__dmg-zone' + damageZoneClass(dmg_values[i]);
      });
    }
    var blueContainer = document.getElementById('ce-fn-dmg-blue');
    if (blueContainer) {
      var zones = blueContainer.querySelectorAll('.ce-fn__dmg-zone');
      var dmg_values = [blue_dmg * 0.5, blue_dmg * 0.3, blue_dmg * 0.2];
      zones.forEach(function (zone, i) {
        zone.className = 'ce-fn__dmg-zone' + damageZoneClass(dmg_values[i]);
      });
    }
  }

  function updateScorecard(round_just_ended) {
    var d = state.fight_data;
    var scorecardEl = document.getElementById('ce-fn-scorecard');
    if (!scorecardEl || !d.rounds) return;

    // Find the round_winner_fighter_id for each completed round.
    var red_id = d.red ? d.red.fighter_id : null;
    var blue_id = d.blue ? d.blue.fighter_id : null;
    var rowsHtml = '<div class="ce-fn__scorecard-row">' +
      '<span class="ce-fn__scorecard-round-label">RD</span>' +
      '<span class="ce-fn__scorecard-cell">RED</span>' +
      '<span class="ce-fn__scorecard-cell">BLUE</span>' +
    '</div>';
    d.rounds.forEach(function (r) {
      if (r.round_number > round_just_ended) return;
      var red_won = r.round_winner_fighter_id === red_id;
      var blue_won = r.round_winner_fighter_id === blue_id;
      rowsHtml += '<div class="ce-fn__scorecard-row">' +
        '<span class="ce-fn__scorecard-round-label">' + r.round_number + '</span>' +
        '<span class="ce-fn__scorecard-cell ' + (red_won ? 'ce-fn__scorecard-cell--won' : 'ce-fn__scorecard-cell--lost') + '">' + (red_won ? '10' : '9') + '</span>' +
        '<span class="ce-fn__scorecard-cell ' + (blue_won ? 'ce-fn__scorecard-cell--won' : 'ce-fn__scorecard-cell--lost') + '">' + (blue_won ? '10' : '9') + '</span>' +
      '</div>';
    });
    scorecardEl.innerHTML = rowsHtml;
  }

  function updateKeyMoments(current_round) {
    var d = state.fight_data;
    var momentsList = document.getElementById('ce-fn-moments-list');
    if (!momentsList || !d.highlights || d.highlights.length === 0) return;

    // Show highlights in chronological order. We don't have a per-
    // highlight beat_index, so show all highlights once we're past
    // the first round (the highlights list is for completed moments).
    var html = '<div class="ce-fn__moments">';
    d.highlights.forEach(function (h) {
      var is_major = h.importance >= 85;
      html += '<div class="ce-fn__moment' + (is_major ? ' ce-fn__moment-importance--high' : '') + '">' +
        '<div class="ce-fn__moment-meta">' + (is_major ? 'KEY MOMENT' : 'HIGHLIGHT') + '</div>' +
        '<div class="ce-fn__moment-text">' + escapeHtml(h.text) + '</div>' +
      '</div>';
    });
    html += '</div>';
    momentsList.innerHTML = html;

    var mmeta = document.getElementById('ce-fn-moments-meta');
    if (mmeta) mmeta.textContent = d.highlights.length + ' moment' + (d.highlights.length === 1 ? '' : 's');
  }

  function skipToFinish() {
    if (state.beat_timer) {
      clearTimeout(state.beat_timer);
      state.beat_timer = null;
    }
    // Append all remaining beats instantly, then advance to recap.
    var d = state.fight_data;
    if (!d || !d.beats) {
      finishLive();
      return;
    }
    // P3.5 — if we're at the very start (no beats appended yet),
    // render the announcer intro first.
    if (state.beat_index === 0) {
      appendExtraSegmentsForBeatIndex(-1);
    }
    while (state.beat_index < d.beats.length) {
      appendBeat(d.beats[state.beat_index]);
      // P3.5 — render any extra segments (pundit/crowd) for this
      // beat too, so the skipped-to-the-end feed still has the
      // announcer/pundit/crowd texture.
      appendExtraSegmentsForBeatIndex(state.beat_index - 1);
      // Don't call updateStatusZones — too many DOM updates.
      state.beat_index += 1;
    }
    // Final update of status zones (so the scorecard + momentum
    // reflect the final state).
    if (d.beats.length > 0) {
      var last_beat = d.beats[d.beats.length - 1];
      // Update cumulative momentum from all beats.
      var red_id = d.red ? d.red.fighter_id : null;
      var blue_id = d.blue ? d.blue.fighter_id : null;
      var cum = 0;
      d.beats.forEach(function (b) {
        var shift = b.momentum_shift || 0;
        if (b.initiator_fighter_id === red_id) cum += shift;
        else if (b.initiator_fighter_id === blue_id) cum -= shift;
        if (b.damage_dealt && b.damage_dealt > 0) {
          if (b.target_fighter_id === red_id) state.red_damage += b.damage_dealt;
          else if (b.target_fighter_id === blue_id) state.blue_damage += b.damage_dealt;
        }
      });
      state.cum_momentum = cum;
      var momEl = document.getElementById('ce-fn-momentum');
      if (momEl) momEl.innerHTML = momentumBarHtml(state.cum_momentum);
      updateDamageIndicators();
      // Scorecard for all completed rounds.
      var max_round = last_beat.round_number;
      for (var r = 1; r <= max_round; r++) updateScorecard(r);
      updateKeyMoments(max_round);

      var counter = document.getElementById('ce-fn-beat-counter');
      if (counter) counter.textContent = 'Beat ' + d.beats.length + ' / ' + d.beats.length;
    }
    finishLive();
  }

  function finishLive() {
    if (state.beat_timer) {
      clearTimeout(state.beat_timer);
      state.beat_timer = null;
    }
    // P3.4 — re-enable "Advance Day" when the live phase ends. The
    // fight is complete; the player can now advance to the next day.
    setAdvanceDayLock(false);
    // Brief delay before transitioning to recap (so the player can
    // read the final beat).
    setTimeout(function () {
      startRecap();
    }, 800);
  }

  // ============================================================
  // PHASE 3 — POST-FIGHT RECAP
  // ============================================================
  function startRecap() {
    state.phase = 'recap';
    renderRecap();
  }

  function renderRecap() {
    var d = state.fight_data;
    if (!d) return;
    var host = document.getElementById('screen-content');
    if (!host) return;

    var red = d.red || {};
    var blue = d.blue || {};
    var r = d.result || {};
    var is_title = d.fight.is_title_fight;
    var title_changed = r.title_changed;

    // Determine winner/loser corners.
    var winner, loser, winner_corner, loser_corner;
    if (r.winner_id === red.fighter_id) {
      winner = red; loser = blue;
      winner_corner = 'red'; loser_corner = 'blue';
    } else if (r.winner_id === blue.fighter_id) {
      winner = blue; loser = red;
      winner_corner = 'blue'; loser_corner = 'red';
    } else {
      // Draw / NC — neither is winner.
      winner = null; loser = null;
    }

    var method_phrase = resultPhraseVoice(r.result_type, r.finish_round, r.finish_time);

    // Result card.
    var result_card_class = is_title ? 'ce-fn__result-card--title' : '';
    var result_card;
    if (winner) {
      result_card = '' +
        '<div class="ce-fn__result-card ' + result_card_class + '">' +
          '<div class="ce-fn__result-fighter ce-fn__result-fighter--' + loser_corner + '">' +
            '<div class="ce-fn__result-fighter-label">LOSER</div>' +
            '<div class="ce-fn__result-fighter-name">' + escapeHtml(loser.name || '—') + '</div>' +
            '<div class="ce-fn__result-fighter-record">' + escapeHtml(loser.record_str || '—') + '</div>' +
          '</div>' +
          '<div class="ce-fn__result-method">' +
            '<div class="ce-fn__result-fighter-label" style="color:var(--gold);">WINNER</div>' +
            '<div class="ce-fn__result-method-phrase">' + escapeHtml(winner.name || '—') + '</div>' +
            '<div class="ce-fn__result-method-detail">' + escapeHtml(method_phrase) + '</div>' +
            (title_changed ? '<div class="ce-fn__title-badge" style="margin-top:8px;">🥇 TITLE CHANGES HANDS</div>' : '') +
          '</div>' +
          '<div class="ce-fn__result-fighter ce-fn__result-fighter--winner">' +
            '<div class="ce-fn__result-fighter-label">WINNER</div>' +
            '<div class="ce-fn__result-fighter-name">' + escapeHtml(winner.name || '—') + '</div>' +
            '<div class="ce-fn__result-fighter-record">' + escapeHtml(winner.record_str || '—') + '</div>' +
          '</div>' +
        '</div>';
    } else {
      // Draw / NC.
      result_card = '' +
        '<div class="ce-fn__result-card">' +
          '<div class="ce-fn__result-fighter">' +
            '<div class="ce-fn__result-fighter-label">RED CORNER</div>' +
            '<div class="ce-fn__result-fighter-name">' + escapeHtml(red.name || '—') + '</div>' +
            '<div class="ce-fn__result-fighter-record">' + escapeHtml(red.record_str || '—') + '</div>' +
          '</div>' +
          '<div class="ce-fn__result-method">' +
            '<div class="ce-fn__result-method-phrase">' + escapeHtml(method_phrase || 'DRAW') + '</div>' +
          '</div>' +
          '<div class="ce-fn__result-fighter">' +
            '<div class="ce-fn__result-fighter-label">BLUE CORNER</div>' +
            '<div class="ce-fn__result-fighter-name">' + escapeHtml(blue.name || '—') + '</div>' +
            '<div class="ce-fn__result-fighter-record">' + escapeHtml(blue.record_str || '—') + '</div>' +
          '</div>' +
        '</div>';
    }

    // Performance + fan reaction phrases.
    var perf_tile = '' +
      '<div class="ce-fn__recap-tile">' +
        '<div class="ce-fn__recap-tile-label">PERFORMANCE</div>' +
        '<div class="ce-fn__recap-tile-value">' + escapeHtml(r.performance_rating_phrase || '—') + '</div>' +
      '</div>';
    var fan_tile = '' +
      '<div class="ce-fn__recap-tile">' +
        '<div class="ce-fn__recap-tile-label">CROWD REACTION</div>' +
        '<div class="ce-fn__recap-tile-value">' + escapeHtml(r.fan_reaction_rating_phrase || '—') + '</div>' +
      '</div>';

    // Title change tile.
    var title_tile = '';
    if (is_title) {
      if (title_changed) {
        title_tile = '' +
          '<div class="ce-fn__recap-tile ce-fn__recap-tile--title">' +
            '<div class="ce-fn__recap-tile-label">🥇 TITLE CHANGE</div>' +
            '<div class="ce-fn__recap-tile-value">' + escapeHtml(winner ? winner.name : '') + ' is the new champion.</div>' +
            '<div class="ce-fn__recap-tile-sub">A new era begins.</div>' +
          '</div>';
      } else {
        title_tile = '' +
          '<div class="ce-fn__recap-tile ce-fn__recap-tile--title">' +
            '<div class="ce-fn__recap-tile-label">🥇 TITLE DEFENDED</div>' +
            '<div class="ce-fn__recap-tile-value">The champion retains.</div>' +
          '</div>';
      }
    }

    // Injury tile (if any injuries from the resolve_next_fight result).
    var injury_tile = '';
    // We don't have direct access to the resolve_next_fight result
    // here in replay mode. We'd need to query the injuries table by
    // fight_id — but the get_fight_night_data payload doesn't include
    // injuries. For now, omit the injury tile in the recap (the news
    // item will mention it if there is one).
    // TODO: add injuries to the get_fight_night_data payload.

    // News item preview.
    var news_card = '';
    // Try to read news from the result payload (live mode) or skip
    // (replay mode — we don't have the news item in fight_data).
    // For replay mode, we'd need to add news to fight_data. Skip for now.

    // Key moments feed (highlights).
    var moments_html = '';
    if (d.highlights && d.highlights.length > 0) {
      moments_html = '<div class="ce-fn__recap-highlights">';
      d.highlights.forEach(function (h) {
        var is_major = h.importance >= 85;
        moments_html += '<div class="ce-fn__recap-highlight' +
          (is_major ? ' ce-fn__recap-highlight--major' : '') + '">' +
          escapeHtml(h.text) + '</div>';
      });
      moments_html += '</div>';
    }

    // Show rating panel (only if last fight on card).
    var show_rating_html = '';
    if (d.is_last_fight_on_card && d.show_rating) {
      var sr = d.show_rating;
      show_rating_html = '' +
        '<div class="ce-fn__show-rating">' +
          '<div class="ce-fn__show-rating-eyebrow">SHOW VERDICT</div>' +
          '<div class="ce-fn__show-rating-phrase">' + escapeHtml(sr.rating_description || sr.overall_rating_phrase) + '</div>' +
          '<div class="ce-fn__show-rating-axes">' +
            showAxis('FAN', sr.fan_rating) +
            showAxis('COMMERCIAL', sr.commercial_rating) +
            showAxis('EXCITEMENT', sr.excitement_rating) +
            showAxis('QUALITY', sr.quality_rating) +
            showAxis('OVERALL', sr.overall_rating) +
          '</div>' +
        '</div>';
    }

    // Action buttons.
    // CLEANUP-AND-FIX Bug 8 — Replay button removed (replay mode
    // eliminated). The recap is shown directly when navigating to a
    // resolved fight, so the player can't re-trigger animation.
    var actions_html = '<div class="ce-fn__recap-actions">';
    if (d.next_unresolved_fight_id) {
      actions_html += '<button class="ce-fn__action-btn" id="ce-fn-next-fight">▶ Next Fight</button>';
    } else if (d.is_last_fight_on_card) {
      actions_html += '<button class="ce-fn__action-btn" id="ce-fn-done">✓ Done</button>';
    } else {
      actions_html += '<button class="ce-fn__action-btn" id="ce-fn-done">✓ Done</button>';
    }
    actions_html += '<button class="ce-fn__action-btn ce-fn__action-btn--secondary" id="ce-fn-back-dashboard">Dashboard</button>';
    actions_html += '</div>';

    host.innerHTML = '' +
      '<div class="ce-fn">' +
        '<header class="ce-fn__header">' +
          '<div class="ce-fn__title-block">' +
            '<div class="ce-fn__event-name">' + escapeHtml(d.event.event_name || 'Fight Night') + '</div>' +
            '<div class="ce-fn__event-meta">FIGHT RECAP · ' + escapeHtml(formatDate(d.event.event_date)) + '</div>' +
          '</div>' +
          '<div class="ce-fn__header-spacer"></div>' +
          '<button class="ce-fn__exit-btn" id="ce-fn-exit-recap">Exit</button>' +
        '</header>' +
        '<div class="ce-fn__recap">' +
          '<div class="ce-fn__recap-header">' +
            '<div class="ce-fn__recap-eyebrow">FIGHT RECAP · ' + escapeHtml(d.fight.card_slot_label || 'FIGHT') + '</div>' +
          '</div>' +
          result_card +
          '<div class="ce-fn__recap-grid">' +
            perf_tile + fan_tile +
            (title_tile || injury_tile) +
          '</div>' +
          (moments_html ? '<div class="ce-fn__context-card"><div class="ce-fn__context-card-title">KEY MOMENTS</div>' + moments_html + '</div>' : '') +
          show_rating_html +
          actions_html +
        '</div>' +
      '</div>';

    wireRecapControls();
  }

  function showAxis(label, value) {
    var v = Math.max(0, Math.min(100, value || 0));
    return '' +
      '<div class="ce-fn__show-axis">' +
        '<div class="ce-fn__show-axis-label">' + escapeHtml(label) + '</div>' +
        '<div class="ce-fn__show-axis-bar"><div class="ce-fn__show-axis-bar-fill" style="width:' + v + '%;"></div></div>' +
      '</div>';
  }

  function wireRecapControls() {
    var nextBtn = document.getElementById('ce-fn-next-fight');
    if (nextBtn) nextBtn.addEventListener('click', function () {
      // Reload Fight Night for the next unresolved fight.
      state.fight_id = null;
      state.event_id = state.fight_data ? state.fight_data.event_id : null;
      state.fight_data = null;
      state.mode = 'live';
      loadAndRender();
    });
    var doneBtn = document.getElementById('ce-fn-done');
    if (doneBtn) doneBtn.addEventListener('click', function () {
      window.CE.app.navigate('dashboard');
    });
    // CLEANUP-AND-FIX Bug 8 — Replay button + handler removed.
    var dashboardBtn = document.getElementById('ce-fn-back-dashboard');
    if (dashboardBtn) dashboardBtn.addEventListener('click', function () {
      window.CE.app.navigate('dashboard');
    });
    var exitBtn = document.getElementById('ce-fn-exit-recap');
    if (exitBtn) exitBtn.addEventListener('click', function () {
      window.CE.app.navigate('dashboard');
    });
    // Fighter-name hyperlinks in the recap.
    document.querySelectorAll('.ce-fn__recap a[data-fighter-id]').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        var fid = link.getAttribute('data-fighter-id');
        if (fid) window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
      });
    });
  }

  // ============================================================
  // PUBLIC API
  // ============================================================
  return {
    loadAndRender: loadAndRender,
    state: state,
  };
})();
