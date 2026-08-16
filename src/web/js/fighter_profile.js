/* ============================================================
   CAGE EMPIRE — Fighter Profile Screen Renderer
   ============================================================
   Renders the full Fighter Profile into #screen-content using live
   data fetched via window.CE.bridge.getFighterProfileData(fighterId).

   Per GUI_PLAN §6.3 + SCREEN_DATA_AUDIT §4:
     - Header card (Accent): 256px portrait + name + nickname + age
       + WC + promo + gym + identity strip (6 LONG voice phrases)
       + action buttons (Cut / Book Next Fight / Scout).
     - 6 tabs: Overview | Attributes | Personality | Career | Fights | News.
     - Overview: Bio (8-col) + Career stats (4-col) + Recent Fights
       timeline (12-col, W/L badge + opponent hyperlink + method).
     - Attributes: 26 StatBars from attribute_descriptors JSON. Top 6
       shown by default, "Show all 26" toggle reveals the rest.
     - Personality: 20 StatBars from personality_descriptors JSON.
     - Career: full fight history + title reigns.
     - Fights: same as Recent Fights but full history.
     - News: NewsCards mentioning this fighter.
     - Action buttons: Cut Fighter (danger) / Book Next Fight
       (secondary) / Scout (secondary).
     - Back button: returns to previous screen.

   Voice compliance:
     - All 26 attribute values are voice phrases, NOT raw 0-100 ints.
     - Identity strip uses LONG interpretation phrases (italic).
     - StatBars use SHORT voice phrases from descriptor JSON.
   ============================================================ */

window.CE = window.CE || {};

window.CE.fighterProfile = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    fighterId: null,
    data: null,
    activeTab: 'overview',
    showAllAttributes: false,
    showAllPersonality: false,
    showAllFights: false,
  };

  // ============================================================
  // HELPERS
  // ============================================================
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /** Format a cash value for display. */
  function formatCash(n) {
    n = Number(n) || 0;
    if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return '$' + Math.round(n / 1e3) + 'K';
    return '$' + Math.round(n).toLocaleString();
  }

  /** Map result_type to a short label. */
  function resultLabel(rt) {
    if (!rt) return '';
    var m = {
      unanimous_decision: 'UD', split_decision: 'SD', majority_decision: 'MD',
      ko_tko: 'KO/TKO', submission: 'SUB', tko_stoppage: 'TKO', ko: 'KO',
      dq: 'DQ', draw: 'DRAW', no_contest: 'NC', nc: 'NC',
    };
    return m[rt.toLowerCase()] || rt.toUpperCase().slice(0, 6);
  }

  /** Map attribute phrase to a tier (gold/steel/crimson). */
  function phraseTier(phrase) {
    if (!phrase) return 'steel';
    var p = phrase.toLowerCase();
    // Elite-tier phrases → gold
    var eliteWords = ['elite', 'world-class', 'exceptional', 'lethal', 'master',
                      'devastating', 'top-tier', 'elite-level', 'powerful',
                      'explosive', 'iron', 'titanium', 'granite'];
    for (var i = 0; i < eliteWords.length; i++) {
      if (p.indexOf(eliteWords[i]) !== -1) return 'gold';
    }
    // Weak-tier phrases → crimson
    var weakWords = ['poor', 'weak', 'fragile', 'limited', 'vulnerable',
                     'soft', 'can be rocked', 'questionable', 'shaky',
                     'below-average', 'lacking'];
    for (var j = 0; j < weakWords.length; j++) {
      if (p.indexOf(weakWords[j]) !== -1) return 'crimson';
    }
    return 'steel';
  }

  /** "Important" attribute keys — shown by default in the top 6. */
  var TOP_ATTRIBUTES = [
    'punch_power', 'punch_accuracy', 'chin', 'cardio', 'fight_iq', 'footwork'
  ];
  var TOP_PERSONALITY = [
    'aggression', 'composure', 'killer_instinct', 'discipline', 'patience', 'ego'
  ];

  /** Convert snake_case key to Title Case label. */
  function humanize(key) {
    if (!key) return '';
    return key.split('_').map(function (w) {
      return w.charAt(0).toUpperCase() + w.slice(1);
    }).join(' ');
  }

  // CR-3b (docs/CR1_4_PLAN.md §3.3): gender-correct pronoun helper.
  // Fighter Profile is per-fighter, so section titles + empty states
  // can use gendered pronouns. Returns {he, his, him, hes} where
  // hes = "HE'S"/"SHE'S"/"THEY'RE" (already-contracted form for use
  // in titles like 'WHAT HE'S DONE LATELY' → 'WHAT ' + p.hes + ...).
  // All values are UPPERCASE to match the existing voice style.
  // For unknown/neutral gender, falls back to THEY/THEIR/THEM.
  function pronouns(gender) {
    if (gender === 'female') return { he: 'SHE', his: 'HER', him: 'HER', hes: "SHE'S" };
    if (gender === 'male')   return { he: 'HE',  his: 'HIS', him: 'HIM', hes: "HE'S" };
    return { he: 'THEY', his: 'THEIR', him: 'THEM', hes: "THEY'RE" };
  }

  // ============================================================
  // RENDERERS
  // ============================================================

  function renderHeader(h) {
    // DB-REVIEW-IMAGE-ASSIGNMENT E.5: render real portrait if
    // h.has_portrait is true. The actual image bytes are fetched
    // asynchronously via window.CE.bridge.getFighterPortrait() (the
    // base64 payload is 50-100KB — too big to embed in the profile
    // response). Client-side cache in window.CE._portraitCache
    // (keyed by fighter_id) means re-renders don't re-fetch.
    //
    // States:
    //   1. has_portrait=false → ce-fp-portrait--placeholder (static).
    //   2. has_portrait=true + cached in window.CE._portraitCache →
    //      inline <img> rendered immediately (no async fetch).
    //   3. has_portrait=true + not cached → ce-fp-portrait--loading
    //      with initial-letter placeholder + async fetch. On
    //      response, replace innerHTML with <img>. If the API
    //      returns has_portrait=false (corrupted file — 263 of the
    //      415 uploads), switch from --loading to --placeholder to
    //      stop the pulse animation.
    var portrait = '';
    var portraitId = 'ce-fp-portrait-' + h.fighter_id;
    window.CE._portraitCache = window.CE._portraitCache || {};
    var cached = window.CE._portraitCache[h.fighter_id];

    if (h.has_portrait && cached) {
      // State 2: cached — render <img> inline.
      portrait = '' +
        '<div class="ce-fp-portrait' + (h.is_champion ? ' ce-fp-portrait--champ' : '') + '" id="' + portraitId + '">' +
          '<img src="' + cached + '" class="ce-fp-portrait-img" alt="' + escapeHtml(h.name) + '" />' +
          (h.is_champion ? '<div class="ce-fp-portrait-crown">★</div>' : '') +
        '</div>';
    } else if (h.has_portrait) {
      // State 3: loading — render placeholder + async fetch.
      portrait = '' +
        '<div class="ce-fp-portrait ce-fp-portrait--loading' + (h.is_champion ? ' ce-fp-portrait--champ' : '') + '" id="' + portraitId + '">' +
          '<div class="ce-fp-portrait-initial">' + escapeHtml((h.last_name || '?').charAt(0).toUpperCase()) + '</div>' +
          (h.is_champion ? '<div class="ce-fp-portrait-crown">★</div>' : '') +
        '</div>';
    } else {
      // State 1: placeholder (no portrait_path set — 4049 generated
      // fighters, or the file is corrupted at the DB level).
      portrait = '' +
        '<div class="ce-fp-portrait ce-fp-portrait--placeholder' + (h.is_champion ? ' ce-fp-portrait--champ' : '') + '">' +
          '<div class="ce-fp-portrait-initial">' + escapeHtml((h.last_name || '?').charAt(0).toUpperCase()) + '</div>' +
          (h.is_champion ? '<div class="ce-fp-portrait-crown">★</div>' : '') +
        '</div>';
    }

    var identityStripHtml = ['career_phase', 'momentum', 'pressure', 'narrative', 'legacy', 'trajectory']
      .map(function (key) {
        var item = h.identity_strip[key] || {};
        var label = key.replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
        var phrase = item.long || '—';
        return '' +
          '<div class="ce-fp-strip-item">' +
            '<div class="ce-fp-strip-label">' + escapeHtml(label.toUpperCase()) + '</div>' +
            '<div class="ce-fp-strip-phrase">' + escapeHtml(phrase) + '</div>' +
          '</div>';
      }).join('');

    // Action buttons — Phase R §4.4 ownership renames (player-roster
    // fighters use ownership labels; non-roster keeps the original).
    // CR-3b: gendered pronoun in "Book His/Her/Their Next Fight".
    var pAct = pronouns(h.gender);
    var actions = '';
    if (h.is_on_player_roster) {
      actions += '<button class="ce-btn ce-btn-danger" id="ce-fp-cut-btn" type="button">Release from Your Stable</button>';
      actions += '<button class="ce-btn ce-btn-secondary" id="ce-fp-book-btn" type="button">Book ' + pAct.his.charAt(0) + pAct.his.slice(1).toLowerCase() + ' Next Fight</button>';
    } else if (!h.is_retired) {
      actions += '<button class="ce-btn ce-btn-secondary" id="ce-fp-scout-btn" type="button">🔍 Send a Scout</button>';
    }
    if (h.is_free_agent) {
      actions += '<button class="ce-btn ce-btn-primary" id="ce-fp-sign-btn" type="button">Bring Into Your Stable</button>';
    }

    // Promo line + meta line — CR-1 (docs/CR1_4_PLAN.md §1.2):
    // show the actual promotion name (e.g. "ALPHA COMBAT FEDERATION")
    // instead of the "YOUR promotion" placeholder. Phase R §4.4 keeps
    // the "Your [WC]" ownership cue on the meta line for roster
    // fighters. Non-roster fighters keep the original neutral labels.
    var promoLine, metaLine;
    if (h.is_on_player_roster) {
      promoLine = 'Fights for ' + escapeHtml(h.promo_name) + ' · Trains at ' + escapeHtml(h.gym_name);
      metaLine = h.age + ' years old · Your ' + escapeHtml(h.wc_name) + ' · ' + escapeHtml(h.stance || '') + ' stance';
    } else {
      promoLine = h.promo_name + ' · ' + escapeHtml(h.gym_name);
      metaLine = h.age + 'y · ' + escapeHtml(h.wc_name) + ' · ' + escapeHtml(h.stance || '') + ' stance';
    }
    if (h.height_cm) metaLine += ' · ' + h.height_cm + 'cm / ' + (h.reach_cm || '—') + 'cm reach';

    return '' +
      '<div class="ce-fp-header' + (h.is_champion ? ' ce-fp-header--champ' : '') + '">' +
        portrait +
        '<div class="ce-fp-header-info">' +
          '<div class="ce-fp-header-topline">' +
            '<a class="ce-fp-back" href="#" id="ce-fp-back">← Back</a>' +
          '</div>' +
          '<h2 class="ce-fp-name">' + escapeHtml(h.name) + '</h2>' +
          (h.nickname ? '<div class="ce-fp-nick">"' + escapeHtml(h.nickname) + '"</div>' : '') +
          '<div class="ce-fp-meta">' + escapeHtml(metaLine) + '</div>' +
          '<div class="ce-fp-promo">' + escapeHtml(promoLine) + '</div>' +
          (h.style_name && h.style_name !== '—' ? '<div class="ce-fp-style"><span class="ce-chip ce-chip-default">' + escapeHtml(h.style_name) + '</span>' +
            (h.personality_archetype_name && h.personality_archetype_name !== '—' ? ' <span class="ce-chip ce-chip-default">' + escapeHtml(h.personality_archetype_name) + '</span>' : '') +
          '</div>' : '') +
          (h.career_health_desc ? '<div class="ce-fp-health"><span class="ce-chip ce-chip-warning">Health: ' + escapeHtml(h.career_health_desc) + '</span></div>' : '') +
          '<div class="ce-fp-strip">' + identityStripHtml + '</div>' +
          (h.overall_desc ? '<div class="ce-fp-overall">' + escapeHtml(h.overall_desc) + '</div>' : '') +
          '<div class="ce-fp-actions">' + actions + '</div>' +
        '</div>' +
      '</div>';
  }

  function renderTabBar() {
    var tabs = [
      { id: 'overview',    label: 'Overview' },
      { id: 'attributes',  label: 'Attributes' },
      { id: 'personality', label: 'Personality' },
      { id: 'career',      label: 'Career' },
      { id: 'fights',      label: 'Fights' },
      { id: 'news',        label: 'News' },
    ];
    var html = tabs.map(function (t) {
      var cls = state.activeTab === t.id ? 'ce-fp-tab ce-fp-tab--active' : 'ce-fp-tab';
      return '<button class="' + cls + '" data-tab="' + t.id + '" type="button">' + escapeHtml(t.label) + '</button>';
    }).join('');
    return '<div class="ce-fp-tabs">' + html + '</div>';
  }

  // ----- Tab: Overview -----
  function renderOverview(data) {
    var h = data.header;
    var cs = data.career_stats;
    var bio = data.bio;

    // Phase R §4.4: ownership renames for stat tile labels + section
    // titles apply ONLY when fighter is on the player's roster. Non-
    // roster fighters keep the original neutral labels (the player
    // doesn't "own" them yet).
    // CR-3b (docs/CR1_4_PLAN.md §3.3): gendered pronouns in section
    // titles + empty states. p.he/p.his/p.him/p.hes are uppercase.
    var onRoster = h.is_on_player_roster;
    var p = pronouns(h.gender);
    var LBL_BIO = onRoster ? ('WHO ' + p.he + ' IS') : 'BIO';
    var LBL_CAREER = onRoster ? (p.his + ' CAREER SO FAR') : 'CAREER';
    var LBL_RECENT_FIGHTS = onRoster ? ('WHAT ' + p.hes + ' DONE LATELY') : 'RECENT FIGHTS';
    var LBL_RECORD = onRoster ? 'RECORD UNDER YOUR PROMOTION' : 'RECORD';
    var LBL_WIN_STREAK = onRoster ? 'CURRENT WIN STREAK' : 'WIN STREAK';
    var LBL_LOSS_STREAK = onRoster ? 'CURRENT LOSS STREAK' : 'LOSS STREAK';
    var LBL_TITLE_REIGNS = onRoster ? 'BELTS HELD' : 'TITLE REIGNS';
    var LBL_CAREER_HEALTH = onRoster ? ('WHERE ' + p.his + ' BODY IS AT') : 'CAREER HEALTH';
    var LBL_TOTAL_FIGHTS = onRoster ? ('FIGHTS UNDER ' + p.his + ' BELT') : 'TOTAL FIGHTS';
    var bioEmpty = onRoster
      ? ('We don\'t have a read on ' + p.him.toLowerCase() + ' yet.')
      : 'No biography on file.';
    var fightsEmpty = onRoster
      ? (p.he.charAt(0) + p.he.slice(1).toLowerCase() + ' hasn\'t made ' + p.his.toLowerCase() + ' walk yet.')
      : 'No fights on record yet.';

    // Career stats (4-col)
    var statsHtml = '' +
      '<div class="ce-fp-stat-tile">' +
        '<div class="ce-fp-stat-label">' + LBL_RECORD + '</div>' +
        '<div class="ce-fp-stat-val ce-mono">' + escapeHtml(cs.record_str) + '</div>' +
      '</div>' +
      '<div class="ce-fp-stat-tile">' +
        '<div class="ce-fp-stat-label">' + LBL_WIN_STREAK + '</div>' +
        '<div class="ce-fp-stat-val ce-mono ' + (cs.win_streak > 0 ? 'c-green' : '') + '">' + cs.win_streak + '</div>' +
      '</div>' +
      '<div class="ce-fp-stat-tile">' +
        '<div class="ce-fp-stat-label">' + LBL_LOSS_STREAK + '</div>' +
        '<div class="ce-fp-stat-val ce-mono ' + (cs.loss_streak > 0 ? 'c-crimson' : '') + '">' + cs.loss_streak + '</div>' +
      '</div>' +
      '<div class="ce-fp-stat-tile">' +
        '<div class="ce-fp-stat-label">' + LBL_TITLE_REIGNS + '</div>' +
        '<div class="ce-fp-stat-val ce-mono c-gold">' + cs.title_reigns + '</div>' +
      '</div>' +
      '<div class="ce-fp-stat-tile">' +
        '<div class="ce-fp-stat-label">' + LBL_CAREER_HEALTH + '</div>' +
        '<div class="ce-fp-stat-val ce-mono">' + cs.career_health + '</div>' +
        '<div class="ce-stat-bar"><div class="ce-stat-bar-fill ce-stat-bar-gold" style="width:' + Math.max(0, Math.min(100, cs.career_health)) + '%"></div></div>' +
      '</div>' +
      '<div class="ce-fp-stat-tile">' +
        '<div class="ce-fp-stat-label">' + LBL_TOTAL_FIGHTS + '</div>' +
        '<div class="ce-fp-stat-val ce-mono">' + data.total_fights + '</div>' +
      '</div>';

    // Recent Fights timeline (5 most recent, with toggle)
    var recentFights = data.recent_fights || [];
    var fightsToShow = state.showAllFights ? recentFights : recentFights.slice(0, 5);
    var fightsHtml = fightsToShow.map(renderFightRow).join('');
    var toggleFights = recentFights.length > 5
      ? '<button class="ce-btn ce-btn-ghost ce-fp-toggle" id="ce-fp-toggle-fights" type="button">' +
          (state.showAllFights ? 'Show last 5 ▲' : 'Show all ' + recentFights.length + ' ▼') +
        '</button>'
      : '';

    // "Your History with [Fighter]" — Phase R §4. Only rendered for
    // fighters on the player's roster. The data.your_history field is
    // null for non-roster fighters (computed server-side only when
    // header.is_on_player_roster is true).
    var yourHistoryHtml = renderYourHistory(data);

    return '' +
      '<div class="ce-fp-tab-content ce-fp-overview">' +
        yourHistoryHtml +
        '<div class="ce-fp-grid-12">' +
          '<div class="ce-fp-bio ce-fp-col-8">' +
            '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">' + LBL_BIO + '</span></div>' +
            (bio.text
              ? '<p class="ce-fp-bio-text">' + escapeHtml(bio.text) + '</p>'
              : '<div class="ce-empty-state">' + bioEmpty + '</div>') +
          '</div>' +
          '<div class="ce-fp-stats ce-fp-col-4">' +
            '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">' + LBL_CAREER + '</span></div>' +
            '<div class="ce-fp-stat-grid">' + statsHtml + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="ce-fp-recent-fights">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">' + LBL_RECENT_FIGHTS + '</span>' +
            '<span class="ce-sec-sub ce-mono">' + data.total_fights + ' total</span>' +
          '</div>' +
          (fightsHtml
            ? '<div class="ce-fp-timeline">' + fightsHtml + '</div>' + toggleFights
            : '<div class="ce-empty-state">' + fightsEmpty + '</div>') +
        '</div>' +
      '</div>';
  }

  // ----- "Your History with [Fighter]" (Phase R §4) -----
  // Renders 4 lines linking the player's past decisions to current
  // consequences for this fighter. Each line is a small stat tile
  // with a label + value + optional hyperlink.
  function renderYourHistory(data) {
    var yh = data.your_history;
    if (!yh) return '';  // non-roster fighter — section hidden
    var h = data.header;
    var name = h.name;

    // 1. Signed: [Date] ([N]-month contract, $X)
    var signLine = '—';
    if (yh.sign_date) {
      var contractStr = '';
      if (yh.contract_months) {
        var monthsLabel = yh.contract_months >= 12
          ? (Math.floor(yh.contract_months / 12) + 'y ' + (yh.contract_months % 12) + 'm')
          : (yh.contract_months + 'm');
        contractStr = ' · ' + monthsLabel + ' deal';
        if (yh.contract_salary) {
          contractStr += ' · ' + formatCash(yh.contract_salary) + '/fight';
        }
      }
      signLine = escapeHtml(yh.sign_date) + contractStr;
    }

    // 2. Record under you: W-L-D
    var ru = yh.record_under_you || {wins: 0, losses: 0, draws: 0};
    var recordStr = ru.wins + '-' + ru.losses + '-' + ru.draws;

    // 3. Biggest win: Method vs Opponent at Event
    var biggestWinStr = '—';
    var biggestWinOpponentId = null;
    if (yh.biggest_win) {
      var bw = yh.biggest_win;
      biggestWinStr = escapeHtml(bw.method) + ' vs ' + escapeHtml(bw.opponent_name);
      if (bw.event_name) {
        biggestWinStr += ' at ' + escapeHtml(bw.event_name);
      }
      biggestWinOpponentId = bw.opponent_id;
    }

    // 4. Contract expires in [N] days
    var expiryStr = '—';
    var expiryClass = '';
    if (yh.contract_expires_in_days !== null && yh.contract_expires_in_days !== undefined) {
      var d = yh.contract_expires_in_days;
      if (d < 0) {
        expiryStr = 'expired ' + Math.abs(d) + 'd ago';
        expiryClass = 'c-crimson';
      } else if (d <= 30) {
        expiryStr = d + ' days';
        expiryClass = 'c-crimson';
      } else if (d <= 90) {
        expiryStr = d + ' days';
        expiryClass = 'c-gold';
      } else {
        expiryStr = d + ' days';
      }
    }

    // Decision count chip (e.g. "3 decisions logged")
    var nDecisions = (yh.decisions || []).length;
    var decisionsChip = nDecisions
      ? '<span class="ce-chip ce-chip-default">' + nDecisions + ' decision' + (nDecisions !== 1 ? 's' : '') + ' logged</span>'
      : '';

    return '' +
      '<div class="ce-fp-your-history">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div>' +
          '<span class="ce-sec-title ce-sec-title-gold">YOUR HISTORY WITH ' + escapeHtml(name.toUpperCase()) + '</span>' +
          decisionsChip +
        '</div>' +
        '<div class="ce-fp-yh-grid">' +
          '<div class="ce-fp-yh-tile">' +
            '<div class="ce-fp-yh-label">SIGNED</div>' +
            '<div class="ce-fp-yh-val">' + signLine + '</div>' +
            '<div class="ce-fp-yh-link"><a class="ce-link" href="#" data-screen-target="contracts">View on Deals →</a></div>' +
          '</div>' +
          '<div class="ce-fp-yh-tile">' +
            '<div class="ce-fp-yh-label">RECORD UNDER YOU</div>' +
            '<div class="ce-fp-yh-val ce-mono">' + recordStr + '</div>' +
          '</div>' +
          '<div class="ce-fp-yh-tile">' +
            '<div class="ce-fp-yh-label">BIGGEST WIN</div>' +
            '<div class="ce-fp-yh-val">' + biggestWinStr + '</div>' +
            (biggestWinOpponentId
              ? '<div class="ce-fp-yh-link"><a class="ce-link" href="#" data-fighter-id="' + biggestWinOpponentId + '">View ' + escapeHtml(yh.biggest_win.opponent_name) + ' →</a></div>'
              : '') +
          '</div>' +
          '<div class="ce-fp-yh-tile">' +
            '<div class="ce-fp-yh-label">CONTRACT EXPIRES IN</div>' +
            '<div class="ce-fp-yh-val ce-mono ' + expiryClass + '">' + expiryStr + '</div>' +
          '</div>' +
        '</div>' +
      '</div>';
  }

  function renderFightRow(f) {
    var badgeClass = f.outcome === 'win' ? 'ce-fp-badge--win'
                   : f.outcome === 'loss' ? 'ce-fp-badge--loss'
                   : 'ce-fp-badge--neutral';
    var badgeText = f.badge || 'N';
    var titleChip = f.title_at_stake ? '<span class="ce-chip ce-chip-gold">TITLE</span>' : '';
    var methodLine = escapeHtml(f.result_label || '—') +
      ' · R' + (f.finish_round || '—') +
      (f.finish_time ? ' ' + escapeHtml(f.finish_time) : '');

    return '' +
      '<div class="ce-fp-fight">' +
        '<div class="ce-fp-fight-badge ' + badgeClass + '">' + escapeHtml(badgeText) + '</div>' +
        '<div class="ce-fp-fight-body">' +
          '<div class="ce-fp-fight-top">' +
            '<span class="ce-fp-fight-vs">vs</span> ' +
            '<a class="ce-link ce-fp-fight-opp" href="#" data-fighter-id="' + f.opponent_id + '">' + escapeHtml(f.opponent_name) + '</a>' +
            (f.opponent_nickname ? ' <span class="ce-fp-fight-opp-nick">\'' + escapeHtml(f.opponent_nickname) + '\'</span>' : '') +
            ' <span class="ce-fp-fight-method">' + methodLine + '</span>' +
            ' ' + titleChip +
          '</div>' +
          '<div class="ce-fp-fight-meta ce-mono">' + escapeHtml(f.event_date) + (f.wc_name ? ' · ' + escapeHtml(f.wc_name) : '') + '</div>' +
        '</div>' +
      '</div>';
  }

  // ----- Tab: Attributes (26 StatBars) -----
  function renderAttributes(data) {
    var attrs = data.attributes || {};
    var keys = Object.keys(attrs);
    if (!keys.length) {
      return '<div class="ce-fp-tab-content"><div class="ce-empty-state">No attribute data on file.</div></div>';
    }
    var topKeys = TOP_ATTRIBUTES.filter(function (k) { return attrs[k]; });
    var otherKeys = keys.filter(function (k) { return TOP_ATTRIBUTES.indexOf(k) === -1; });
    var showAll = state.showAllAttributes;

    // CR-2: pass per-attribute trajectory chip from backend payload.
    // Falls back to {} if attribute_trajectory is missing (old cache).
    var traj = data.attribute_trajectory || {};
    var topBars = topKeys.map(function (k) { return renderStatBar(k, attrs[k], traj[k]); }).join('');
    var otherBars = otherKeys.map(function (k) { return renderStatBar(k, attrs[k], traj[k]); }).join('');

    var toggle = otherKeys.length > 0
      ? '<button class="ce-btn ce-btn-ghost ce-fp-toggle" id="ce-fp-toggle-attrs" type="button">' +
          (showAll ? 'Show top 6 ▲' : 'Show all ' + keys.length + ' ▼') +
        '</button>'
      : '';

    // Phase R §4.4: ownership rename for player-roster fighters.
    // CR-3b: gendered pronoun in the section title.
    var p = pronouns(data.header.gender);
    var sectionLabel = data.header.is_on_player_roster
      ? ('WHAT ' + p.he + ' BRINGS TO THE CAGE')
      : 'FIGHTER ATTRIBUTES';

    return '' +
      '<div class="ce-fp-tab-content ce-fp-attributes">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">' + sectionLabel + '</span></div>' +
        '<p class="ce-fp-tab-help">Voice phrases from the scouting desk — never raw numbers.</p>' +
        '<div class="ce-fp-statbars ce-fp-statbars--top">' + topBars + '</div>' +
        (showAll ? '<div class="ce-fp-statbars ce-fp-statbars--rest">' + otherBars + '</div>' : '') +
        toggle +
      '</div>';
  }

  // ----- Tab: Personality (20 StatBars) -----
  function renderPersonality(data) {
    var pers = data.personality || {};
    var keys = Object.keys(pers);
    if (!keys.length) {
      return '<div class="ce-fp-tab-content"><div class="ce-empty-state">No personality data on file.</div></div>';
    }
    var topKeys = TOP_PERSONALITY.filter(function (k) { return pers[k]; });
    var otherKeys = keys.filter(function (k) { return TOP_PERSONALITY.indexOf(k) === -1; });
    var showAll = state.showAllPersonality;

    // CR-2: personality bars get no trajectory chip (pass null).
    var topBars = topKeys.map(function (k) { return renderStatBar(k, pers[k], null); }).join('');
    var otherBars = otherKeys.map(function (k) { return renderStatBar(k, pers[k], null); }).join('');

    var toggle = otherKeys.length > 0
      ? '<button class="ce-btn ce-btn-ghost ce-fp-toggle" id="ce-fp-toggle-pers" type="button">' +
          (showAll ? 'Show top 6 ▲' : 'Show all ' + keys.length + ' ▼') +
        '</button>'
      : '';

    // Phase R §4.4: ownership rename for player-roster fighters.
    // CR-3b: gendered pronoun in the section title.
    var p = pronouns(data.header.gender);
    var sectionLabel = data.header.is_on_player_roster
      ? ('WHO ' + p.he + ' IS WHEN THE DOOR CLOSES')
      : 'PERSONALITY';

    return '' +
      '<div class="ce-fp-tab-content ce-fp-personality">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">' + sectionLabel + '</span></div>' +
        '<p class="ce-fp-tab-help">The traits that shape how this fighter handles pressure, success, and failure.</p>' +
        '<div class="ce-fp-statbars ce-fp-statbars--top">' + topBars + '</div>' +
        (showAll ? '<div class="ce-fp-statbars ce-fp-statbars--rest">' + otherBars + '</div>' : '') +
        toggle +
      '</div>';
  }

  function renderStatBar(key, phrase, trajectory) {
    var tier = phraseTier(phrase);
    var label = humanize(key);
    // Use the phrase text as the bar fill width proxy:
    // tier gold = 100%, steel = 60%, crimson = 25%
    var pct = tier === 'gold' ? 100 : tier === 'crimson' ? 25 : 60;
    // CR-2 (docs/CR1_4_PLAN.md §2.3): trajectory chip — green
    // (surging/growing) → gray (stable) → orange/red (declining/
    // decaying). The 3rd arg is the per-attribute trajectory dict
    // from get_fighter_profile_data. Pass null/undefined for
    // personality bars (no trajectory there).
    var chipHtml = '';
    if (trajectory && trajectory.state) {
      var icons = { surging: '▲▲', growing: '▲', stable: '→', declining: '▼', decaying: '▼▼' };
      var icon = icons[trajectory.state] || '→';
      var reason = trajectory.reason || '';
      chipHtml = '<span class="ce-fp-trajectory ce-fp-trajectory--' + trajectory.state +
        '" title="' + escapeHtml(reason) + '">' + icon + '</span>';
    }
    return '' +
      '<div class="ce-fp-statbar">' +
        '<div class="ce-fp-statbar-label">' + escapeHtml(label) + '</div>' +
        '<div class="ce-fp-statbar-phrase">' + escapeHtml(phrase || '—') + chipHtml + '</div>' +
        '<div class="ce-fp-statbar-track"><div class="ce-fp-statbar-fill ce-fp-statbar-fill--' + tier + '" style="width:' + pct + '%"></div></div>' +
      '</div>';
  }

  // ----- Tab: Career -----
  function renderCareer(data) {
    var cs = data.career_stats;
    var reigns = data.title_reigns || [];
    var fights = data.recent_fights || [];

    var reignsHtml = reigns.length
      ? reigns.map(function (r) {
          return '' +
            '<div class="ce-fp-reign">' +
              '<div class="ce-fp-reign-wc">' + escapeHtml(r.wc_name) + '</div>' +
              '<div class="ce-fp-reign-promo">' + escapeHtml(r.promo_name) + '</div>' +
              '<div class="ce-fp-reign-meta ce-mono">Since ' + escapeHtml(r.champion_since_date) + ' · ' + escapeHtml(r.reign_length) + '</div>' +
              '<div class="ce-fp-reign-defenses">' +
                '<span class="ce-chip ce-chip-gold">' + r.title_defenses_count + ' DEF</span>' +
                (r.title_reigns_count > 1 ? '<span class="ce-chip ce-chip-default">' + r.title_reigns_count + 'ND REIGN</span>' : '') +
              '</div>' +
            '</div>';
        }).join('')
      : '<div class="ce-empty-state">No title reigns on record.</div>';

    var fightsHtml = fights.length
      ? fights.map(renderFightRow).join('')
      : '<div class="ce-empty-state">No fights on record.</div>';

    // Phase R §4.4: ownership renames for player-roster fighters.
    // CR-3b: gendered pronouns in section titles.
    var onRoster = data.header.is_on_player_roster;
    var p = pronouns(data.header.gender);
    var LBL_TITLE_REIGNS = onRoster ? 'BELTS WON' : 'TITLE REIGNS';
    var LBL_FIGHT_HISTORY = onRoster ? ('THE FIGHTS THAT DEFINED ' + p.him) : 'FIGHT HISTORY';

    return '' +
      '<div class="ce-fp-tab-content ce-fp-career">' +
        '<div class="ce-fp-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">' + LBL_TITLE_REIGNS + '</span></div>' +
          '<div class="ce-fp-reigns">' + reignsHtml + '</div>' +
        '</div>' +
        '<div class="ce-fp-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">' + LBL_FIGHT_HISTORY + '</span>' +
            '<span class="ce-sec-sub ce-mono">' + data.total_fights + ' total</span>' +
          '</div>' +
          '<div class="ce-fp-timeline">' + fightsHtml + '</div>' +
        '</div>' +
      '</div>';
  }

  // ----- Tab: Fights (full history) -----
  function renderFights(data) {
    var fights = data.recent_fights || [];
    var fightsHtml = fights.length
      ? fights.map(renderFightRow).join('')
      : '<div class="ce-empty-state">No fights on record yet.</div>';
    // Phase R §4.4: ownership rename for player-roster fighters.
    // CR-3b: gendered pronoun in the section title.
    var p = pronouns(data.header.gender);
    var sectionLabel = data.header.is_on_player_roster
      ? ('THE FIGHTS THAT DEFINED ' + p.him)
      : 'FIGHT HISTORY';
    return '' +
      '<div class="ce-fp-tab-content ce-fp-fights">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">' + sectionLabel + '</span>' +
          '<span class="ce-sec-sub ce-mono">' + data.total_fights + ' total (showing last ' + fights.length + ')</span>' +
        '</div>' +
        '<div class="ce-fp-timeline">' + fightsHtml + '</div>' +
      '</div>';
  }

  // ----- Tab: News -----
  function renderNews(data) {
    var news = data.news || [];
    // Phase R §4.4: ownership rename for player-roster fighters.
    // CR-3b: gendered pronoun in the section title. "THEY'RE" stays
    // (refers to the press/public, not the fighter).
    var p = pronouns(data.header.gender);
    var sectionLabel = data.header.is_on_player_roster
      ? ('WHAT THEY\'RE SAYING ABOUT ' + p.him)
      : 'NEWS';
    if (!news.length) {
      return '' +
        '<div class="ce-fp-tab-content ce-fp-news">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">' + sectionLabel + '</span></div>' +
          '<div class="ce-empty-state">The newswire hasn\'t mentioned this fighter yet.</div>' +
        '</div>';
    }
    var newsHtml = news.map(function (n) {
      var badge = '<span class="ce-chip ce-chip-default">' + escapeHtml((n.topic || 'wire').toUpperCase().slice(0, 12)) + '</span>';
      var body = n.body ? '<p class="ce-news-body">' + escapeHtml(n.body) + '</p>' : '';
      return '' +
        '<div class="ce-news-card">' +
          '<div class="ce-news-top">' + badge + '<span class="ce-news-date">' + escapeHtml(n.published_at) + '</span></div>' +
          '<div class="ce-news-headline ce-news-headline-plain">' + escapeHtml(n.headline) + '</div>' +
          body +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-fp-tab-content ce-fp-news">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">' + sectionLabel + '</span>' +
          '<span class="ce-sec-sub ce-mono">' + news.length + ' recent mentions</span>' +
        '</div>' +
        '<div class="ce-news-list">' + newsHtml + '</div>' +
      '</div>';
  }

  function renderScoutingReport(data) {
    var sr = data.scouting_report;
    if (!sr) {
      // For player's fighters, no scouting report is expected.
      // For non-player fighters, show empty state.
      if (data.header && data.header.is_on_player_roster) return '';
      return '' +
        '<div class="ce-fp-scouting">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-crimson"></div><span class="ce-sec-title ce-sec-title-crimson">SCOUTING REPORT</span></div>' +
          '<div class="ce-empty-state">No scouting report on file. Send a scout to gather intel.</div>' +
        '</div>';
    }
    return '' +
      '<div class="ce-fp-scouting">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-crimson"></div><span class="ce-sec-title ce-sec-title-crimson">SCOUTING REPORT</span></div>' +
        '<div class="ce-fp-scouting-card">' +
          '<div class="ce-fp-scouting-top">' +
            '<span class="ce-fp-scouting-scout">' + escapeHtml(sr.scout_name) + '</span>' +
            '<span class="ce-fp-scouting-date ce-mono">' + escapeHtml(sr.report_date) + '</span>' +
            '<span class="ce-chip ce-chip-default">' + escapeHtml(sr.confidence) + '</span>' +
          '</div>' +
          (sr.ceiling_phrase ? '<div class="ce-fp-scouting-ceiling">Ceiling: <strong class="c-gold">' + escapeHtml(sr.ceiling_phrase) + '</strong></div>' : '') +
          (sr.report_text ? '<p class="ce-fp-scouting-text">' + escapeHtml(sr.report_text) + '</p>' : '') +
        '</div>' +
      '</div>';
  }

  function render(data) {
    if (!data || data.error) {
      var host = document.getElementById('screen-content');
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load fighter</div><div>' + escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
      }
      return;
    }
    state.data = data;
    var host = document.getElementById('screen-content');
    if (!host) return;

    var tabContent = '';
    if (state.activeTab === 'overview') tabContent = renderOverview(data);
    else if (state.activeTab === 'attributes') tabContent = renderAttributes(data);
    else if (state.activeTab === 'personality') tabContent = renderPersonality(data);
    else if (state.activeTab === 'career') tabContent = renderCareer(data);
    else if (state.activeTab === 'fights') tabContent = renderFights(data);
    else if (state.activeTab === 'news') tabContent = renderNews(data);

    var html = '' +
      '<div class="ce-fp">' +
        renderHeader(data.header) +
        renderScoutingReport(data) +
        renderTabBar() +
        tabContent +
      '</div>';

    host.innerHTML = html;
    wireEvents();
    // DB-REVIEW-IMAGE-ASSIGNMENT E.5: kick off async portrait
    // load for fighters with has_portrait=true but not yet cached.
    // Cached fighters were already rendered as inline <img> in
    // renderHeader (no fetch needed).
    if (data.header && data.header.has_portrait &&
        !(window.CE._portraitCache && window.CE._portraitCache[data.fighter_id])) {
      loadPortrait(data.header, data.fighter_id);
    }
  }

  // DB-REVIEW-IMAGE-ASSIGNMENT E.5: async-load the fighter portrait
  // and replace the loading placeholder with an <img>. Caches the
  // data_uri in window.CE._portraitCache so subsequent re-renders
  // (e.g. tab switches that re-render the header) don't re-fetch.
  function loadPortrait(h, fighterId) {
    if (!h || !h.has_portrait) return Promise.resolve();
    window.CE._portraitCache = window.CE._portraitCache || {};
    var portraitId = 'ce-fp-portrait-' + fighterId;
    return window.CE.bridge.getFighterPortrait(fighterId).then(function (resp) {
      if (resp && resp.has_portrait && resp.data_uri) {
        window.CE._portraitCache[fighterId] = resp.data_uri;
        var el = document.getElementById(portraitId);
        if (el) {
          el.classList.remove('ce-fp-portrait--loading');
          el.classList.add('ce-fp-portrait--loaded');
          // Preserve the champion crown overlay if present.
          var crown = el.querySelector('.ce-fp-portrait-crown');
          el.innerHTML = '<img src="' + resp.data_uri + '" class="ce-fp-portrait-img" alt="' + escapeHtml(h.name) + '" />';
          if (crown) el.appendChild(crown);
        }
      } else {
        // API returned has_portrait=false (corrupted file or
        // missing). Switch from --loading to --placeholder to stop
        // the pulse animation + show the static initial letter.
        var el2 = document.getElementById(portraitId);
        if (el2) {
          el2.classList.remove('ce-fp-portrait--loading');
          el2.classList.add('ce-fp-portrait--placeholder');
        }
      }
    }).catch(function (err) {
      // Network/bridge error — also degrade to placeholder.
      var el3 = document.getElementById(portraitId);
      if (el3) {
        el3.classList.remove('ce-fp-portrait--loading');
        el3.classList.add('ce-fp-portrait--placeholder');
      }
    });
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    // Back button
    var backBtn = document.getElementById('ce-fp-back');
    if (backBtn) backBtn.addEventListener('click', function (evt) {
      evt.preventDefault();
      window.CE.app.navigateBack();
    });

    // Tab switching
    document.querySelectorAll('.ce-fp-tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        state.activeTab = tab.getAttribute('data-tab');
        // Re-render only the tabs + content (preserve header)
        render(state.data);
      });
    });

    // Toggles
    var toggleAttrs = document.getElementById('ce-fp-toggle-attrs');
    if (toggleAttrs) toggleAttrs.addEventListener('click', function () {
      state.showAllAttributes = !state.showAllAttributes;
      render(state.data);
    });
    var togglePers = document.getElementById('ce-fp-toggle-pers');
    if (togglePers) togglePers.addEventListener('click', function () {
      state.showAllPersonality = !state.showAllPersonality;
      render(state.data);
    });
    var toggleFights = document.getElementById('ce-fp-toggle-fights');
    if (toggleFights) toggleFights.addEventListener('click', function () {
      state.showAllFights = !state.showAllFights;
      render(state.data);
    });

    // Opponent name hyperlinks in Recent Fights → re-navigate to Fighter Profile.
    // Also catches hyperlinks inside the "Your History with [Fighter]" section
    // (Phase R §4) — biggest_win opponent link uses the same data-fighter-id
    // attribute, so a single querySelectorAll covers both.
    document.querySelectorAll('[data-fighter-id]').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        var fid = link.getAttribute('data-fighter-id');
        if (fid) window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
      });
    });

    // "View on Deals" + other data-screen-target hyperlinks (Phase R §4).
    // These navigate to placeholder screens (contracts, past_events, etc.).
    // The placeholder screen will render with the standard "coming soon"
    // message — explicit click handler so the href="#" doesn't scroll.
    document.querySelectorAll('[data-screen-target]').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        var target = link.getAttribute('data-screen-target');
        if (target && window.CE.app && window.CE.app.navigate) {
          window.CE.app.navigate(target);
        }
      });
    });

    // Action buttons
    var cutBtn = document.getElementById('ce-fp-cut-btn');
    if (cutBtn) cutBtn.addEventListener('click', function () {
      if (!state.data) return;
      var fid = state.data.fighter_id;
      var name = state.data.header.name;
      // Phase R §4.4: ownership-rewrite for the cut confirm dialog.
      // CR-3b: gendered pronouns ("He'll"/"She'll"/"They'll" +
      // "his"/"her"/"their"). Inline mapping for sentence-case.
      var g = state.data.header.gender;
      var ll = g === 'female' ? 'She\'ll' : g === 'male' ? 'He\'ll' : 'They\'ll';
      var hes_lc = g === 'female' ? 'she' : g === 'male' ? 'he' : 'they';
      var his_lc = g === 'female' ? 'her' : g === 'male' ? 'his' : 'their';
      if (!confirm('Release ' + name + ' from your stable? ' + ll + ' become a free agent, ' + his_lc + ' contract will be terminated, and any titles ' + hes_lc + ' holds will be vacated.')) return;
      cutBtn.disabled = true;
      cutBtn.textContent = 'Releasing…';
      window.CE.bridge.cutFighter(fid).then(function (result) {
        if (result && result.ok) {
          showProfileToast('Released ' + name + '.', 'success');
          // Navigate back to roster after a brief delay
          setTimeout(function () {
            window.CE.app.navigateBack();
          }, 800);
        } else {
          showProfileToast('Cut failed: ' + (result && result.error ? result.error : 'unknown'), 'error');
          cutBtn.disabled = false;
          cutBtn.textContent = 'Release from Your Stable';
        }
      }).catch(function (err) {
        showProfileToast('Cut failed: ' + err, 'error');
        cutBtn.disabled = false;
        cutBtn.textContent = 'Release from Your Stable';
      });
    });

    var bookBtn = document.getElementById('ce-fp-book-btn');
    if (bookBtn) bookBtn.addEventListener('click', function () {
      // Matchmaking screen not built yet — show toast
      showProfileToast('Matchmaking screen coming soon. Fighter queued for next card.', 'info');
    });

    var scoutBtn = document.getElementById('ce-fp-scout-btn');
    if (scoutBtn) scoutBtn.addEventListener('click', function () {
      // Scouting service not wired yet — show toast
      showProfileToast('Scouting pipeline is being prepped. Report will appear here once filed.', 'info');
    });

    var signBtn = document.getElementById('ce-fp-sign-btn');
    if (signBtn) signBtn.addEventListener('click', function () {
      if (!state.data) return;
      var fid = state.data.fighter_id;
      var name = state.data.header.name;
      // Phase R §4.3: ownership-rewrite for the sign confirm dialog.
      if (!confirm('Bring ' + name + ' into your stable?\n\nAn estimated cost will be charged and a 12-month contract created.')) return;
      signBtn.disabled = true;
      signBtn.textContent = 'Signing…';
      window.CE.bridge.signFreeAgent(fid).then(function (result) {
        if (result && result.ok) {
          showProfileToast('Signed ' + name + ' for ' + (result.cost_display || ''), 'success');
          // Reload profile to refresh action button state
          loadAndRender(fid);
        } else {
          showProfileToast('Sign failed: ' + (result && result.error ? result.error : 'unknown'), 'error');
          signBtn.disabled = false;
          signBtn.textContent = 'Bring Into Your Stable';
        }
      }).catch(function (err) {
        showProfileToast('Sign failed: ' + err, 'error');
        signBtn.disabled = false;
        signBtn.textContent = 'Bring Into Your Stable';
      });
    });
  }

  function showProfileToast(msg, kind) {
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
  function loadAndRender(fighterId) {
    state.fighterId = Number(fighterId);
    state.activeTab = 'overview';
    state.showAllAttributes = false;
    state.showAllPersonality = false;
    state.showAllFights = false;
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Reading the dossier…</div></div>';
    }
    return window.CE.bridge.getFighterProfileData(state.fighterId).then(function (data) {
      render(data);
    });
  }

  return {
    loadAndRender: loadAndRender,
    render: render,
  };
})();
