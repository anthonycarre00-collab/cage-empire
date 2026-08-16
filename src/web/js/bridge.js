/* ============================================================
   CAGE EMPIRE — JS↔Python Bridge (pywebview API wrapper)
   ============================================================
   pywebview 6.x exposes the js_api instance methods as:
   window.pywebview.api.method_name(arg1, arg2, ...)
   which returns a Promise.

   CRITICAL TIMING BUG (previously mis-diagnosed):
   `window.pywebview.api` is created as an EMPTY object {} by
   pywebview's api.js (line 4) IMMEDIATELY on page load. The actual
   method population happens LATER when pywebview injects finish.js,
   which calls `window.pywebview._createApi(funcList)` and only then
   dispatches the `pywebviewready` event.

   The previous bridge treated `window.pywebview.api` being truthy
   as "ready" — but {} is truthy! So bridge calls raced ahead of
   _createApi, hit `api[methodName]` === undefined, and threw:
   "Cannot read properties of undefined (reading 'apply')".

   FIX: waitForApi() must wait for the `pywebviewready` event (or
   poll until a method actually exists on api), NOT just for the
   empty object to appear.
   ============================================================ */

window.CE = window.CE || {};

window.CE.bridge = (function () {
  'use strict';

  var _readyPromise = null;

  /**
   * Wait for window.pywebview.api to be FULLY POPULATED.
   *
   * pywebview fires `pywebviewready` AFTER _createApi() has assigned
   * every method. We listen for that event AND poll as a belt-and-
   * braces fallback (in case the event already fired before we
   * registered the listener).
   *
   * Caches the ready promise so multiple callers don't race.
   */
  function waitForApi(timeoutMs) {
    timeoutMs = timeoutMs || 15000;
    if (_readyPromise) return _readyPromise;

    _readyPromise = new Promise(function (resolve, reject) {
      var start = Date.now();

      function apiReady() {
        // Must have the api object AND at least one callable method.
        // An empty {} is NOT ready — it means finish.js hasn't run yet.
        if (!window.pywebview || !window.pywebview.api) return false;
        // Probe a known method (get_clock always exists on Api).
        var fn = window.pywebview.api.get_clock;
        return typeof fn === 'function';
      }

      if (apiReady()) { resolve(window.pywebview.api); return; }

      // Listen for the official ready event (preferred path).
      window.addEventListener('pywebviewready', function () {
        // Give _createApi a tick to finish assigning functions.
        setTimeout(function () {
          if (apiReady()) {
            resolve(window.pywebview.api);
          } else {
            // Event fired but methods still missing — keep polling.
            poll();
          }
        }, 10);
      });

      // Belt-and-braces: poll every 50ms in case we missed the event.
      function poll() {
        if (apiReady()) { resolve(window.pywebview.api); return; }
        if (Date.now() - start > timeoutMs) {
          reject(new Error('pywebview API not ready after ' + timeoutMs + 'ms. ' +
            'window.pywebview=' + (!!window.pywebview) + ', ' +
            'window.pywebview.api=' + (window.pywebview ? !!window.pywebview.api : 'n/a') + ', ' +
            'api.get_clock=' + (window.pywebview && window.pywebview.api
              ? typeof window.pywebview.api.get_clock : 'n/a')));
          return;
        }
        setTimeout(poll, 50);
      }
      poll();
    });

    return _readyPromise;
  }

  /**
   * Call a Python method by name with args.
   * Returns a Promise that resolves to the method's return value.
   */
  function callPython(methodName, args) {
    return waitForApi().then(function (api) {
      // Defensive: even after ready, double-check the method exists.
      var fn = api[methodName];
      if (typeof fn !== 'function') {
        throw new Error('Python API method "' + methodName + '" is not exposed. ' +
          'Available methods may not include it — check the Api class in app_web.py.');
      }
      var result = fn.apply(api, args || []);
      return Promise.resolve(result);
    }).then(function (result) {
      // pywebview may return a JSON string for complex types
      if (typeof result === 'string' && result.length > 0) {
        var ch = result.charAt(0);
        if (ch === '{' || ch === '[' || ch === '"') {
          try { return JSON.parse(result); } catch (e) { /* not JSON */ }
        }
      }
      return result;
    }, function (err) {
      var msg = (err && err.message) ? err.message : String(err);
      console.error('[bridge] Python call "' + methodName + '" failed:', msg);
      showError(methodName, msg);
      throw err;
    });
  }

  /**
   * Show a non-blocking error banner.
   */
  function showError(methodName, msg) {
    // Try screen-content (main app) or pregame-promo-grid (pre-game)
    var hosts = [
      document.getElementById('screen-content'),
      document.getElementById('pregame-promo-grid'),
    ];
    for (var i = 0; i < hosts.length; i++) {
      if (hosts[i]) {
        var existing = hosts[i].querySelector('.ce-error-banner');
        if (existing) existing.remove();
        var banner = document.createElement('div');
        banner.className = 'ce-error-banner';
        banner.innerHTML =
          '<div class="ce-error-banner__title">Error in ' + methodName + '</div>' +
          '<div>' + String(msg).slice(0, 500) + '</div>';
        hosts[i].prepend(banner);
        setTimeout(function () {
          if (banner.parentNode) banner.parentNode.removeChild(banner);
        }, 15000);
        break;
      }
    }
  }

  return {
    _showError: showError,

    clearErrors: function () {
      var hosts = [
        document.getElementById('screen-content'),
        document.getElementById('pregame-promo-grid'),
      ];
      hosts.forEach(function (h) {
        if (h) {
          var b = h.querySelector('.ce-error-banner');
          if (b) b.remove();
        }
      });
    },

    ready: function () { return waitForApi(); },

    // Clock + player settings
    getClock: function () { return callPython('get_clock', []); },
    getPlayerPromotion: function () { return callPython('get_player_promotion', []); },
    selectPromotion: function (promoId) { return callPython('select_promotion', [Number(promoId)]); },
    getPlayerCash: function () { return callPython('get_player_cash', []); },
    setPlayerName: function (name) { return callPython('set_player_name', [String(name)]); },
    getPlayerName: function () { return callPython('get_player_name', []); },

    // Dashboard
    getPromotionList: function () { return callPython('get_promotion_list', []); },
    getDashboardData: function (promoId) { return callPython('get_dashboard_data', [Number(promoId)]); },
    advanceDay: function () { return callPython('advance_day', []); },
    // Phase F2.2 — Sim Week + Skip to Show + random fighter (for the
    // processing overlay's profile-cycling feature). advance_days(n)
    // runs N daily ticks in a single Python call (no per-tick JS
    // round-trip); advanceToNextShow finds the next scheduled event
    // + advances to its date. Both return {ok, days_advanced,
    // new_date, clock} so the overlay can hide + the top bar can
    // refresh.
    advanceDays: function (n) { return callPython('advance_days', [Number(n || 1)]); },
    advanceToNextShow: function () { return callPython('advance_to_next_event', []); },
    // Returns {fighter_id: int|null} — used by the processing overlay
    // to cycle through random roster fighters while the sim ticks.
    getRandomFighterId: function () { return callPython('get_random_fighter_id', []); },

    // Fighter data
    getRosterData: function (promoId, page, filters) { return callPython('get_roster_data', [Number(promoId), Number(page || 1), filters || {}]); },
    getFighterProfile: function (fighterId) { return callPython('get_fighter_profile', [Number(fighterId)]); },
    getFighterProfileData: function (fighterId) { return callPython('get_fighter_profile_data', [Number(fighterId)]); },
    // DB-REVIEW-IMAGE-ASSIGNMENT E.5: fetch base64-encoded portrait
    // for a fighter. Returns {has_portrait, data_uri, mime_type} or
    // {has_portrait: false}. Server caches per fighter_id (image
    // never changes — regens get a new fighter_id).
    getFighterPortrait: function (fighterId) { return callPython('get_fighter_portrait_b64', [Number(fighterId)]); },
    getFighterDecisionHistory: function (fighterId) { return callPython('get_fighter_decision_history', [Number(fighterId)]); },
    getFreeAgents: function (page, filters) { return callPython('get_free_agents', [Number(page || 1), filters || {}]); },
    estimateSigningCost: function (fighterId) { return callPython('estimate_signing_cost', [Number(fighterId)]); },
    // Phase E3.3 — sign_free_agent now accepts negotiation params.
    signFreeAgent: function (fighterId, salary, signingBonus, contractLength, winBonusPct) {
      return callPython('sign_free_agent', [
        Number(fighterId),
        salary == null ? null : Number(salary),
        Number(signingBonus || 0),
        Number(contractLength || 2),
        Number(winBonusPct == null ? 0.5 : winBonusPct),
      ]);
    },
    cutFighter: function (fighterId) { return callPython('cut_fighter', [Number(fighterId)]); },

    // Phase M3.2 — Bidding Wars API.
    // get_bidding_alerts returns the list of active SIGNING_INTENT
    // alerts the player can counter-offer against.
    getBiddingAlerts: function () { return callPython('get_bidding_alerts', []); },
    // counter_offer submits the player's bid against a rival AI's
    // known signing intent. Returns {accepted, chosen_promo_id, reason}.
    counterOffer: function (fighterId, salary, signingBonus, contractLength, winBonusPct) {
      return callPython('counter_offer', [
        Number(fighterId),
        Number(salary || 50000),
        Number(signingBonus || 0),
        Number(contractLength || 2),
        Number(winBonusPct == null ? 0.5 : winBonusPct),
      ]);
    },

    // Phase E3.1 — Event Builder API.
    getEventBuilderData: function () { return callPython('get_event_builder_data', []); },
    getEventPreview: function (params) { return callPython('get_event_preview', [params || {}]); },
    createEvent: function (params) { return callPython('create_event', [params || {}]); },

    // Phase MM2 — Calendar Screen API.
    // get_calendar_data returns a month-grid of days with player + rival
    // events + conflict warnings. Pass {month, year} (1-12, full year).
    // Omit args to default to the current sim month.
    getCalendarData: function (month, year) {
      // Pass undefined args through as null so Python sees the default.
      var args = [];
      if (month != null) args.push(Number(month));
      else args.push(null);
      if (year != null) args.push(Number(year));
      else args.push(null);
      return callPython('get_calendar_data', args);
    },
    // get_date_conflicts returns the conflict warnings for a single date
    // (used by the event_builder date picker). Returns {voice, conflicts,
    // is_past, min_lead_time_blocked, is_eligible}.
    getDateConflicts: function (eventDate) {
      return callPython('get_date_conflicts', [String(eventDate)]);
    },

    // Phase M4 — Matchmaking API (the Heartbeat).
    // get_matchmaking_data returns the event info + eligible fighters +
    // booked fights (with matchup scores + punditry analysis).
    getMatchmakingData: function (eventId) { return callPython('get_matchmaking_data', [Number(eventId)]); },
    // book_fight creates a fight row + participants + event_cards +
    // persists the punditry analysis. Returns {ok, fight_id, matchup_score, ...}.
    bookFight: function (eventId, redFighterId, blueFighterId, cardSlot) {
      return callPython('book_fight', [
        Number(eventId),
        Number(redFighterId),
        Number(blueFighterId),
        cardSlot || null,
      ]);
    },
    // remove_fight deletes a fight from the card + reorders remaining.
    removeFight: function (fightId) { return callPython('remove_fight', [Number(fightId)]); },
    // reorder_fights updates card_slot + card_position for all fights
    // on the card (first = main_event, second = co_main, etc.).
    reorderFights: function (eventId, fightOrder) { return callPython('reorder_fights', [Number(eventId), fightOrder || []]); },
    // get_fight_analysis returns the punditry pre-fight analysis for
    // a fighter pair (without booking — for the Compare modal preview).
    getFightAnalysis: function (redFighterId, blueFighterId) {
      return callPython('get_fight_analysis', [Number(redFighterId), Number(blueFighterId)]);
    },
    // get_fight_compare returns 25 attributes for both fighters +
    // the punditry analysis (for the Compare modal radar chart).
    getFightCompare: function (fightId) { return callPython('get_fight_compare', [Number(fightId)]); },
    // get_fight_tale_of_tape returns tale-of-tape data (height/reach/
    // age/record/style/last-5 + champion status) for both fighters.
    getFightTaleOfTape: function (fightId) { return callPython('get_fight_tale_of_tape', [Number(fightId)]); },
    // get_fight_stakes returns ranking implications + title shot context.
    getFightStakes: function (fightId) { return callPython('get_fight_stakes', [Number(fightId)]); },
    // get_fight_fan_pulse returns rivalry context + hometown reaction +
    // voice-layer fan pulse verdict.
    getFightFanPulse: function (fightId) { return callPython('get_fight_fan_pulse', [Number(fightId)]); },

    // MM1.6 (Matchmaking V2) — new API methods for the card
    // confirmation flow + rivalry lookup.
    //
    // confirm_card writes a staged card (list of fights) to DB in
    // one transaction + returns the full projection. The card is
    // LOCKED (status='card_confirmed') after this call — the player
    // can "Re-open Card" to revert.
    confirmCard: function (eventId, fights) {
      return callPython('confirm_card', [Number(eventId), fights || []]);
    },
    // reopen_card removes all fights from DB + resets event status
    // to 'scheduled' (so the player can rebuild the card from
    // scratch with the projection hidden).
    reopenCard: function (eventId) {
      return callPython('reopen_card', [Number(eventId)]);
    },
    // get_rivalry_partners returns the list of fighters with an
    // active rivalry (heat >= 50) with the given fighter. Used by
    // the matchmaking screen to flag eligible opponents with a ⚔
    // chip when the Red Corner is picked.
    getRivalryPartners: function (fighterId) {
      return callPython('get_rivalry_partners', [Number(fighterId)]);
    },

    // P5.1 — Booking Adviser (suggested matchups). Returns 3-5
    // matchup suggestions for the given event. Each suggestion
    // carries the FULL fighter brief for both corners + a reason
    // chip ("Hometown" / "Title Contender" / "Bad Blood" / "Debut"
    // / "Hot Streak") + reason_phrase (voice) + quality_phrase
    // (voice). The JS renders a collapsible panel below the card
    // list; clicking a row fills Red/Blue corners (no auto-booking).
    getSuggestedMatchups: function (eventId) {
      return callPython('get_suggested_matchups', [Number(eventId)]);
    },

    // Phase E4 — Staff Market API.
    getStaffMarketData: function (page, filters) { return callPython('get_staff_market_data', [Number(page || 1), filters || {}]); },
    estimateStaffHireCost: function (staffId) { return callPython('estimate_staff_hire_cost', [Number(staffId)]); },
    hireStaff: function (staffId, salary, signingBonus, contractLength) {
      return callPython('hire_staff', [
        Number(staffId),
        salary == null ? null : Number(salary),
        Number(signingBonus || 0),
        Number(contractLength || 2),
      ]);
    },

    // P1-WIRE-4-SCREENS — Bad Blood (Rivalries).
    // get_rivalries_data returns paginated rivalries (20/page) with
    // filters {type, heat_band, scope, search}. Each row carries
    // both fighters (clickable → Fighter Profile), heat meter value,
    // voice phrase, head-to-head record, and the origin narrative.
    getRivalriesData: function (page, filters) {
      return callPython('get_rivalries_data', [Number(page || 1), filters || {}]);
    },

    // P1-WIRE-4-SCREENS — Legends (Hall of Fame).
    // get_hof_data returns paginated HoF inductees (20/page) with
    // filters {search, sort}. Each row carries the inductee's
    // career_summary (voice-layered), career_highlights (bullets),
    // record, title_reigns, and induction date.
    getHofData: function (page, filters) {
      return callPython('get_hof_data', [Number(page || 1), filters || {}]);
    },

    // P1-WIRE-4-SCREENS — Scouting.
    // get_scouting_data returns the player's signed scouts (with
    // parsed specialty JSON), recent scouting_reports, and free-agent
    // scout count. assign_scout wraps scouting.assign_scout — sets
    // the scout's current_assignment + returns the ETA date.
    getScoutingData: function () {
      return callPython('get_scouting_data', []);
    },
    assignScout: function (scoutId, targetFighterId) {
      return callPython('assign_scout', [Number(scoutId), Number(targetFighterId)]);
    },
    cancelScoutAssignment: function (scoutId) {
      return callPython('cancel_scout_assignment', [Number(scoutId)]);
    },
    getScoutingReport: function (reportId) {
      return callPython('get_scouting_report', [Number(reportId)]);
    },

    // P1-WIRE-4-SCREENS — Training Camps (Gyms).
    // get_gyms_data returns paginated gyms (20/page) with filters
    // {culture_tone, sort, search}. get_training_camps_data returns
    // paginated active camps (20/page) with filters {focus, status,
    // scope, search}. Both endpoints accept the same {page, filters}
    // shape used by the rest of the API.
    getGymsData: function (page, filters) {
      return callPython('get_gyms_data', [Number(page || 1), filters || {}]);
    },
    getTrainingCampsData: function (page, filters) {
      return callPython('get_training_camps_data', [Number(page || 1), filters || {}]);
    },

    // CR-9: Rival promotions ("The Competition" screen)
    getRivalPromotions: function () { return callPython('get_rival_promotions', []); },
    getRivalRoster: function (promoId, page, filters) { return callPython('get_rival_roster', [Number(promoId), Number(page || 1), filters || {}]); },

    // Save / Load
    listSaves: function () { return callPython('list_saves', []); },
    saveGame: function (name) { return callPython('save_game', [String(name)]); },
    loadGame: function (name) { return callPython('load_game', [String(name)]); },

    // Phase INFO-SCREENS-BATCH-1 — The Wire (news feed).
    // get_wire_data returns paginated news_items with topic +
    // sentiment filters + search. Pass {page, filters} — filters
    // is {topic, search, sentiment}. See app_web.Api.get_wire_data.
    getWireData: function (page, filters) {
      return callPython('get_wire_data', [Number(page || 1), filters || {}]);
    },

    // Phase INFO-SCREENS-BATCH-1 — The Archive (past events).
    // get_archive_data returns 10 completed events for the player's
    // promo with main-event result + rating voice phrase + net
    // profit. Filters: {date_from, date_to, search, min_rating}.
    getArchiveData: function (page, filters) {
      return callPython('get_archive_data', [Number(page || 1), filters || {}]);
    },
    // get_event_card returns the full fight list for one event
    // (Red/Blue corners, winner highlight, result_label, round).
    // Called on expand in The Archive.
    getEventCard: function (eventId) {
      return callPython('get_event_card', [Number(eventId)]);
    },

    // Phase INFO-SCREENS-BATCH-1 — The Rankings.
    // get_rankings_data returns the top-15 ranked fighters for a
    // weight class + the player's promo. Pass {wcId, gender, promoFilter}
    // (wcId wins; if null, gender picks the first WC of that gender).
    // P4.4: promoFilter="mine" (default) scopes to the player's promo,
    //       promoFilter="all" pools all promotions (contracted_to column
    //       then shows where each fighter is signed).
    getRankingsData: function (wcId, gender, promoFilter) {
      var args = [];
      args.push(wcId == null ? null : Number(wcId));
      args.push(gender || null);
      args.push(promoFilter || null);
      return callPython('get_rankings_data', args);
    },

    // Phase INFO-SCREENS-BATCH-1 — Belts (titles).
    // get_titles_data returns ALL titles across ALL promos,
    // grouped by promo with champion info + reign voice phrases.
    // No args — the player's promo is auto-detected server-side.
    getTitlesData: function () {
      return callPython('get_titles_data', []);
    },

    // P2-FINANCE-CONTRACTS — The Books (finance screen).
    // get_finance_data returns the player's promo summary (cash,
    // budget, reputation + fan_trust voice phrases), the last-30-day
    // cash flow breakdown (revenue vs expenses by type), the
    // projected monthly burn rate, paginated recent transactions
    // (filterable by transaction_type + searchable by description),
    // and the last completed event's full P&L with show rating
    // voice phrase. Pass {page, filters} — filters is
    // {transaction_type, search}.
    getFinanceData: function (page, filters) {
      return callPython('get_finance_data', [
        Number(page || 1),
        filters || {},
      ]);
    },

    // P2-FINANCE-CONTRACTS — Deals (contracts screen).
    // get_contracts_data returns the player's promo's active fighter
    // + staff contracts, with days_until_expiry (color-coded tier),
    // bonus_structure (voice phrase), skill_phrase (for staff),
    // salary, buyout, exclusivity. Pass {page, filters} — filters is
    // {tab: 'all'|'expiring_soon'|'fighters'|'staff', search}.
    getContractsData: function (page, filters) {
      return callPython('get_contracts_data', [
        Number(page || 1),
        filters || {},
      ]);
    },

    // P3-AGENT-OFFERS — Agent Offers (mystery-box talent signing).
    // get_agent_offers returns all active (unresolved) agent offers
    // for the player's promo. Each offer carries a voice-layer
    // fighter_description (NO name, NO raw attributes — the player
    // gambles on the description), an asking_price (dollar figure),
    // offer_type_label chip, + days_until_expiry with color tier.
    // resolve_agent_offer (offerId, accept) — accept=true signs the
    // fighter (deducts asking_price from promo cash + assigns
    // current_promotion_id); accept=false passes. On accept, the
    // fighter's identity is REVEALED in the response (fighter_id +
    // fighter_name + fighter_nickname) so the UI can do the
    // "It's... [Name]!" reveal + navigate to Fighter Profile.
    getAgentOffers: function () {
      return callPython('get_agent_offers', []);
    },
    resolveAgentOffer: function (offerId, accept) {
      return callPython('resolve_agent_offer', [
        Number(offerId),
        accept === undefined ? true : !!accept,
      ]);
    },

    // P4-RECORD-BOOK — The Record Book (all-time leaders).
    // get_records_data returns 11 all-time records (most wins, KOs,
    // subs, title reigns, defenses, win streak, fights, win %,
    // rivalries, oldest + youngest active fighter) + a current
    // champions list (top 12 by defenses across all promos).
    // Each record carries: title, icon, tier (gold/green/crimson/
    // white for visual variety), fighter_id (clickable → Fighter
    // Profile), fighter_name + nickname, value_display (formatted
    // number), and a voice context phrase (e.g. "32-20-4 career
    // record"). No raw potential/attribute numbers — career stats
    // only (W-L-D, age, win %, reigns, defenses are all OK per
    // CONVENTIONS §14 — they're public career facts, not hidden
    // ratings).
    getRecordsData: function () {
      return callPython('get_records_data', []);
    },

    // Task FIGHT-NIGHT-SHOWCASE — Fight Night (live play-by-play).
    //
    // resolve_next_fight resolves ONE fight on the player's scheduled
    // event (the engine picks the lowest-fight_id unresolved fight on
    // the player's promo). The event_id param is informational — the
    // engine still picks the lowest-id unresolved fight on the player's
    // promo (which is almost always on the player's next scheduled
    // event). Returns {ok, fight_id, winner_name, result_phrase,
    // beats_count, commentary_count, ...}.
    resolveNextFight: function (eventId) {
      return callPython('resolve_next_fight', [
        eventId == null ? null : Number(eventId),
      ]);
    },
    // get_fight_night_data returns the full play-by-play payload for
    // a fight. fight_id=null → preview mode (returns the next
    // unresolved fight on the player's promo WITHOUT resolving).
    // fight_id=X → returns the full data (beats + commentary + result
    // card) for fight X.
    getFightNightData: function (fightId) {
      return callPython('get_fight_night_data', [
        fightId == null ? null : Number(fightId),
      ]);
    },
    // get_event_fights returns all fights on an event with their
    // resolution status + results, for the Fight X of Y transport bar.
    getEventFights: function (eventId) {
      return callPython('get_event_fights', [Number(eventId)]);
    },

    // Generic fallback
    callPython: function (methodName, args) { return callPython(methodName, args || []); },
  };
})();
