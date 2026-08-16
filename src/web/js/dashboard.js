/* ============================================================
   CAGE EMPIRE — Dashboard Screen Renderer
   ============================================================
   Renders the full Dashboard screen (8 sections from the approved
   prototype) into #screen-content using live data fetched via
   window.CE.bridge.getDashboardData(promo_id).

   All 8 sections (per the approved 9/10 VLM prototype):
     1. Welcome + Logo
     2. Gradient Header ("THE EMPIRE")
     3. Top Story (gold-bordered card)
     4. Promotion Status (5 stat tiles)
     5. Next Event
     6. Fighter Watch (3 cards: momentum ring + form meter)
     7. Champions (3-col grid)
     8. Recent Results (4-col grid)
     9. Recent News (vertical list)

   Voice compliance (CONVENTIONS §14, GUI_PLAN §10.2):
     - All fighter data comes from fighter_descriptors (the cache)
     - Voice phrases (italic) shown, never raw attribute numbers
     - Stats (cash, count, date) shown in mono (statboard register)
   ============================================================ */

window.CE = window.CE || {};

window.CE.dashboard = (function () {
  'use strict';

  // ============================================================
  // HELPERS
  // ============================================================

  function escapeHtml(s) {
    if (s === null || s === undefined) { return ''; }
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /** Decode 'label||phrase' format from fighter_descriptors. */
  function decodePhrase(stored) {
    if (!stored) { return ''; }
    if (stored.indexOf('||') === -1) { return stored; }
    return stored.split('||', 2)[1];
  }
  function decodeLabel(stored) {
    if (!stored) { return ''; }
    if (stored.indexOf('||') === -1) { return stored; }
    return stored.split('||', 2)[0];
  }

  /** Format cash: $50.0M / $120K / $980 */
  function formatCash(cash) {
    var n = Number(cash) || 0;
    var abs = Math.abs(n);
    if (abs >= 1_000_000_000) { return '$' + (n / 1_000_000_000).toFixed(2) + 'B'; }
    if (abs >= 1_000_000) { return '$' + (n / 1_000_000).toFixed(1) + 'M'; }
    if (abs >= 1_000)     { return '$' + Math.round(n / 1_000) + 'K'; }
    return '$' + Math.round(n).toLocaleString();
  }

  /** Momentum label → ring color + percent fill */
  var MOMENTUM_RING = {
    very_high:  { color: '#4ade80', pct: 100 },
    high:       { color: '#e0a957', pct: 75 },
    stable:     { color: '#6b7280', pct: 50 },
    falling:    { color: '#d63a3f', pct: 25 },
    collapsing: { color: '#ef4444', pct: 10 }
  };

  function momentumRing(momentumLabel) {
    return MOMENTUM_RING[momentumLabel] || { color: '#6b7280', pct: 50 };
  }

  /** Map rating tier to voice phrase + color (rating_tier in generate_dashboard_html.py). */
  function ratingTier(rating) {
    if (!rating) { return { phrase: 'unrated', color: '#6b7280' }; }
    if (rating >= 80) { return { phrase: 'a spectacular night of fights', color: '#4ade80' }; }
    if (rating >= 70) { return { phrase: 'a highly entertaining show', color: '#4ade80' }; }
    if (rating >= 60) { return { phrase: 'a solid night of fights', color: '#e0a957' }; }
    if (rating >= 50) { return { phrase: 'a decent show that failed to deliver', color: '#fbbf24' }; }
    return { phrase: 'a forgettable night for the fans', color: '#d63a3f' };
  }

  /** Map news topic to a short badge label. */
  function topicBadge(topic) {
    var badges = {
      weight_cut: 'WEIGH-IN', news_engine: 'WIRE', injury: 'INJURY',
      signing: 'SIGNING', fight: 'FIGHT', retirement: 'RETIREMENT',
      event_hype: 'HYPE', training: 'TRAINING', suspension: 'SUSPENSION',
      show_rating: 'RATING', career_arc: 'CAREER', finance: 'FINANCE',
      prospect: 'PROSPECT', cross_promo: 'CROSS-PROMO',
      inter_promo_callout: 'CALLOUT', title_change: 'TITLE',
      ranking_change: 'RANKING', morale: 'MORALE', rivalry: 'RIVALRY'
    };
    return badges[topic] || (topic || 'WIRE').toUpperCase().slice(0, 12);
  }

  /** Compute reign length string from champion_since_date to sim_date. */
  function reignLength(sinceDate, simDate) {
    if (!sinceDate || !simDate) { return '—'; }
    var since = new Date(sinceDate + 'T00:00:00Z');
    var sim = new Date(simDate + 'T00:00:00Z');
    if (isNaN(since) || isNaN(sim)) { return '—'; }
    var months = (sim.getUTCFullYear() - since.getUTCFullYear()) * 12 +
                 (sim.getUTCMonth() - since.getUTCMonth());
    if (months < 0) { return '—'; }
    if (months >= 12) { return Math.floor(months / 12) + 'y ' + (months % 12) + 'm'; }
    return months + 'm';
  }

  // ============================================================
  // SECTION RENDERERS
  // ============================================================

  function renderWelcome(d) {
    var logo = d.promo_logo_b64
      ? '<img src="data:image/png;base64,' + d.promo_logo_b64 + '" class="ce-promo-logo" alt="' + escapeHtml(d.promo_name) + '" />'
      : '<div class="ce-promo-logo" style="display:flex;align-items:center;justify-content:center;font-family:var(--font-display);font-size:24px;color:var(--gold);">' + escapeHtml(d.promo_name.charAt(0)) + '</div>';

    return '' +
      '<div class="ce-welcome-section">' +
        logo +
        '<div class="ce-welcome-text">' +
          '<h2 class="ce-welcome-title">Your Empire awaits, Promoter.</h2>' +
          '<p class="ce-welcome-sub">It\'s <strong>' + escapeHtml(d.month_name) + ' ' + d.year + '</strong>. ' +
          'Your roster sits at <strong>' + d.roster_count + '</strong>, ' +
          'your champions at <span class="ce-green"><strong>' + d.champ_count + '</strong></span>, ' +
          'your war chest at <strong>' + formatCash(d.cash) + '</strong>.</p>' +
        '</div>' +
      '</div>';
  }

  function renderGradientHeader(d) {
    return '' +
      '<div class="ce-grad-header">' +
        '<div class="ce-grad-header-content">' +
          '<span class="ce-grad-header-title">YOUR EMPIRE</span>' +
          '<span class="ce-grad-header-sub">' + escapeHtml(d.month_name) + ' ' + d.year + ' · ' + escapeHtml(d.promo_name) + '</span>' +
        '</div>' +
        '<div class="ce-chain-link"></div>' +
      '</div>';
  }

  function renderTopStory(d) {
    var ts = d.top_story || {};
    var headline = ts.headline || 'The newswire is quiet.';
    var body = ts.body || 'No stories have broken in the last 24 hours. Advance a day to see what develops.';
    var fighterLink = '';
    if (ts.fighter_name) {
      fighterLink = '<a class="ce-link" href="#" data-fighter-id="' + (ts.fighter_id || '') + '">View ' + escapeHtml(ts.fighter_name) + ' →</a>';
    }
    var chip = ts.topic ? '<span class="ce-chip ce-chip-gold">' + escapeHtml(topicBadge(ts.topic)) + '</span>' : '<span class="ce-chip ce-chip-gold">WIRE</span>';

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">TOP STORY</span></div>' +
        '<div class="ce-top-story">' +
          '<div class="ce-ts-eyebrow">BREAKING</div>' +
          '<h3 class="ce-ts-headline">' + escapeHtml(headline) + '</h3>' +
          '<p class="ce-ts-body">' + escapeHtml(body) + '</p>' +
          '<div class="ce-ts-footer">' + chip + fighterLink + '</div>' +
        '</div>' +
      '</div>';
  }

  // ----- BIDDING WAR ALERT — Phase M3.2 + P1.1 -----
  // The Empire Builder reward: surfaces rival AI signing intents the
  // player can counter-offer against. Red accent (urgent — fighter
  // could be lost in 3 days). Renders between Top Story and Echoes
  // so the player sees it on the first screen.
  //
  // P1.1 (Quick Fix): show only 3 random alerts (shuffle + slice) so
  // the section stays compact. If there are more than 3 active alerts,
  // add a "View all" link to the Free Agents screen so the player can
  // see the full list there.
  function renderBiddingAlerts(d) {
    var alerts = d.bidding_alerts || [];
    if (!alerts.length) {
      // No active alerts — render nothing (don't show an empty
      // state section; the player should see normal news flow).
      return '';
    }

    // Shuffle a copy (Fisher–Yates) and slice to 3 max. We copy so we
    // don't mutate the source data (the bridge may cache it).
    var pool = alerts.slice();
    for (var i = pool.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = pool[i]; pool[i] = pool[j]; pool[j] = tmp;
    }
    var shown = pool.slice(0, 3);
    var overflow = alerts.length - shown.length;

    var html = shown.map(function (a) {
      var daysLabel = a.days_remaining === 1
        ? '1 DAY'
        : a.days_remaining + ' DAYS';
      var urgencyClass = a.days_remaining <= 1
        ? 'ce-bid-card--urgent'
        : (a.days_remaining <= 2 ? 'ce-bid-card--warning' : '');
      var ageStr = a.fighter_age != null
        ? a.fighter_age + 'y · '
        : '';
      var nickStr = a.fighter_nickname
        ? ' <span class="ce-roster-nick">\'' + escapeHtml(a.fighter_nickname) + '\'</span>'
        : '';
      return '' +
        '<div class="ce-bid-card ' + urgencyClass + '">' +
          '<div class="ce-bid-top">' +
            '<span class="ce-chip ce-chip-danger">BIDDING WAR</span>' +
            '<span class="ce-bid-days">' + daysLabel + ' LEFT</span>' +
          '</div>' +
          '<div class="ce-bid-body">' +
            '<div class="ce-bid-info">' +
              '<div class="ce-bid-target">' +
                escapeHtml(a.rival_promo_name) +
                ' <span class="ce-bid-action">is pursuing</span> ' +
                '<a class="ce-link ce-bid-fighter" href="#" data-fighter-id="' + a.fighter_id + '">' +
                  escapeHtml(a.fighter_name) + nickStr +
                '</a>' +
              '</div>' +
              '<div class="ce-bid-meta ce-mono">' +
                ageStr + escapeHtml(a.fighter_weight_class_name) +
                ' · ' + escapeHtml(a.fighter_record_str) +
                ' · Ceiling: ' + escapeHtml(a.fighter_ceiling_phrase) +
              '</div>' +
              '<div class="ce-bid-rival">' +
                'Their offer: <span class="ce-mono">' +
                escapeHtml(a.offered_salary_display) + '</span>' +
                ' · ' + escapeHtml(a.rival_promo_size_tier_phrase) +
              '</div>' +
            '</div>' +
            '<div class="ce-bid-action-block">' +
              '<button class="ce-btn ce-btn-danger ce-bid-counter-btn" type="button" data-fighter-id="' + a.fighter_id + '">' +
                'Counter Offer' +
              '</button>' +
              '<div class="ce-bid-window">Window closes ' + escapeHtml(a.expiry_date) + '</div>' +
            '</div>' +
          '</div>' +
        '</div>';
    }).join('');

    var overflowHtml = overflow > 0
      ? '<div class="ce-bid-overflow">' +
          '<a class="ce-link ce-bid-viewall" href="#" data-nav-target="free_agents">' +
            'View all ' + (overflow + shown.length) + ' bidding wars' +
          '</a>' +
        '</div>'
      : '';

    return '' +
      '<div class="ce-section ce-bid-section">' +
        '<div class="ce-sec-header">' +
          '<div class="ce-accent-bar ce-accent-danger"></div>' +
          '<span class="ce-sec-title ce-sec-title-danger">BIDDING WAR ALERT</span>' +
          '<span class="ce-sec-icon">⚡</span>' +
        '</div>' +
        '<div class="ce-bid-list">' + html + '</div>' +
        overflowHtml +
      '</div>';
  }

  // Wire up bidding alert buttons. Called after render() so the
  // buttons exist in the DOM.
  function wireBiddingAlerts() {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var buttons = host.querySelectorAll('.ce-bid-counter-btn');
    buttons.forEach(function (btn) {
      btn.addEventListener('click', function (evt) {
        evt.preventDefault();
        var fid = btn.getAttribute('data-fighter-id');
        if (!fid) return;
        // Navigate to the Free Agents screen with the fighter
        // pre-selected (the Free Agents modal will open with the
        // fighter pre-filled, ready for the player to set terms
        // and submit a counter-offer via bridge.counterOffer).
        if (window.CE.app && typeof window.CE.app.navigate === 'function') {
          window.CE.app.navigate('free_agents', {
            fighter_id: Number(fid),
            bidding_alert: true,  // signals free_agents.js to use counter_offer
          });
        }
      });
    });
    // P1.1 — "View all" link routes to Free Agents.
    var viewAll = host.querySelector('.ce-bid-viewall');
    if (viewAll) {
      viewAll.addEventListener('click', function (evt) {
        evt.preventDefault();
        if (window.CE.app && typeof window.CE.app.navigate === 'function') {
          window.CE.app.navigate('free_agents');
        }
      });
    }
  }

  // ----- ECHOES — Phase R §1.5 + §6 Principle 4 -----
  // The Agency reward: 2-3 cards per Advance Day surfacing the
  // consequences of the player's past bookings/signings/cuts.
  // Each card has a phrase + (optional) fighter-name hyperlink.
  function renderEchoes(d) {
    var echoes = d.echoes || [];
    if (!echoes.length) {
      // No echoes yet — empty state. Only shown if player has never
      // advanced a day (no echoes have been generated yet).
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">ECHOES — YOUR MOVES, THEIR CONSEQUENCES</span></div>' +
          '<div class="ce-empty-state">Your past moves haven\'t echoed back yet. Sign a fighter, run a card, then Advance Day — you\'ll see what happens next here.</div>' +
        '</div>';
    }
    var html = echoes.map(function (e) {
      var typeLabel = {
        signing_echo: 'SIGNING',
        cut_echo: 'RELEASE',
        booking_echo: 'CARD',
        scouting_echo: 'SCOUT',
      }[e.echo_type] || 'ECHO';
      // Hyperlink: if target_fighter_id is set, link the fighter name.
      // Otherwise link the whole phrase to the link_to_screen (defaults
      // to fighter_profile).
      var linkHtml = '';
      if (e.target_fighter_id && e.fighter_name) {
        // Phrase + " → [Fighter Name]" hyperlink
        linkHtml = ' <a class="ce-link ce-echo-link" href="#" data-fighter-id="' + e.target_fighter_id + '">View ' + escapeHtml(e.fighter_name) + ' →</a>';
      }
      var chipClass = 'ce-chip-gold';
      if (e.echo_type === 'cut_echo') chipClass = 'ce-chip-danger';
      else if (e.echo_type === 'booking_echo') chipClass = 'ce-chip-default';
      return '' +
        '<div class="ce-echo-card ce-echo-' + e.echo_type + '">' +
          '<div class="ce-echo-top">' +
            '<span class="ce-chip ' + chipClass + '">' + typeLabel + '</span>' +
          '</div>' +
          '<p class="ce-echo-phrase">' + escapeHtml(e.phrase) + '</p>' +
          (linkHtml ? '<div class="ce-echo-footer">' + linkHtml + '</div>' : '') +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">ECHOES — YOUR MOVES, THEIR CONSEQUENCES</span></div>' +
        '<div class="ce-echo-grid">' + html + '</div>' +
      '</div>';
  }

  function renderPromotionStatus(d) {
    var repPct = Math.max(0, Math.min(100, d.reputation));
    var ftPct = Math.max(0, Math.min(100, d.fan_trust));
    var champPct = Math.min(100, Math.round(d.champ_count * 100 / Math.max(1, d.total_wcs || 8)));
    var sizeTier = (d.size_tier || '').toUpperCase();
    var broadcast = (d.broadcast_tier || '').toUpperCase();

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-green"></div><span class="ce-sec-title ce-sec-title-green">' + escapeHtml((d.promo_name || 'YOUR PROMOTION').toUpperCase()) + '\'S HEALTH</span></div>' +
        '<div class="ce-stat-grid">' +

          // Cash
          '<div class="ce-stat-tile">' +
            '<div class="ce-stat-label">YOUR WAR CHEST</div>' +
            '<div class="ce-stat-value ce-mono ce-stat-value-green">' + formatCash(d.cash) + '</div>' +
            '<div class="ce-trend"><span class="ce-trend-up">▲</span><span class="ce-trend-val ce-mono">stable</span></div>' +
            '<div class="ce-sparkline"><svg viewBox="0 0 120 32" preserveAspectRatio="none"><polyline points="0,20 20,18 40,16 60,14 80,12 100,10 120,8" fill="none" stroke="#4ade80" stroke-width="2"/><polygon points="0,20 20,18 40,16 60,14 80,12 100,10 120,8 120,32 0,32" fill="rgba(74,222,128,0.1)"/></svg></div>' +
          '</div>' +

          // Reputation (voice band)
          '<div class="ce-stat-tile">' +
            '<div class="ce-stat-label">YOUR STANDING</div>' +
            '<div class="ce-stat-value ce-descriptor">' + escapeHtml(d.reputation_phrase) + '</div>' +
            '<div class="ce-stat-bar"><div class="ce-stat-bar-fill ce-stat-bar-green" style="width:' + repPct + '%"></div></div>' +
          '</div>' +

          // Fan Trust (voice band)
          '<div class="ce-stat-tile">' +
            '<div class="ce-stat-label">THE FANS\' TRUST IN YOU</div>' +
            '<div class="ce-stat-value ce-descriptor">' + escapeHtml(d.fan_trust_phrase) + '</div>' +
            '<div class="ce-stat-bar"><div class="ce-stat-bar-fill ce-stat-bar-green" style="width:' + ftPct + '%"></div></div>' +
          '</div>' +

          // Roster
          '<div class="ce-stat-tile">' +
            '<div class="ce-stat-label">YOUR ROSTER</div>' +
            '<div class="ce-stat-value ce-mono">' + d.roster_count + '</div>' +
            '<div class="ce-stat-chips">' +
              (sizeTier ? '<span class="ce-chip ce-chip-default">' + escapeHtml(sizeTier) + '</span>' : '') +
              (broadcast ? '<span class="ce-chip ce-chip-default">' + escapeHtml(broadcast) + '</span>' : '') +
            '</div>' +
          '</div>' +

          // Champions
          '<div class="ce-stat-tile">' +
            '<div class="ce-stat-label">YOUR CHAMPIONS</div>' +
            '<div class="ce-stat-value ce-mono ce-stat-value-green">' + d.champ_count + ' of ' + (d.total_wcs || 8) + '</div>' +
            (d.champ_count < (d.total_wcs || 8) ? '<div class="ce-stat-sub">' + ((d.total_wcs || 8) - d.champ_count) + ' titles to capture</div>' : '') +
            '<div class="ce-stat-bar"><div class="ce-stat-bar-fill ce-stat-bar-green" style="width:' + champPct + '%"></div></div>' +
          '</div>' +

        '</div>' +
      '</div>';
  }

  function renderNextEvent(d) {
    var next = d.next_event;
    if (!next) {
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">YOUR NEXT CARD</span></div>' +
          '<div class="ce-empty-state">No events scheduled. Time to build a card.</div>' +
        '</div>';
    }
    // P3.2 (docs/COMPREHENSIVE_FIX_PLAN.md §Group D #15) — "Watch the
    // Show" replaces the old "Fight Night" sidebar entry. The button
    // is ONLY enabled on the event's scheduled date (sim_date ==
    // event_date). Before that: disabled with a hint to advance the
    // sim. On/after: enabled, navigates to fight_resolution (live
    // mode) with the event_id.
    var simDate = d.sim_date || '';
    var eventDate = next.event_date || '';
    var isEventDay = simDate && eventDate && simDate === eventDate;
    var fmtDate = formatLongDate(eventDate);
    var watchBtn;
    if (isEventDay) {
      watchBtn = '<button class="ce-fn-launch-btn ce-fn-launch-btn--ready" ' +
        'id="ce-launch-fight-night" data-event-id="' + next.event_id + '" ' +
        'title="Watch tonight\'s card play out fight by fight.">' +
        '▶ Watch the Show</button>';
    } else {
      var hint = simDate && eventDate && simDate < eventDate
        ? 'Your event is scheduled for ' + fmtDate + '. Advance the sim to that day first.'
        : 'Advance the sim to your event day to watch the show.';
      watchBtn = '<button class="ce-fn-launch-btn ce-fn-launch-btn--disabled" ' +
        'disabled title="' + escapeHtml(hint) + '">▶ Watch the Show</button>' +
        '<div class="ce-fn-launch-hint">' + escapeHtml(hint) + '</div>';
    }
    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">YOUR NEXT CARD</span></div>' +
        '<div class="ce-next-event-card">' +
          '<div class="ce-next-event-date">' + escapeHtml(next.event_date) + '</div>' +
          '<div class="ce-next-event-name">' + escapeHtml(next.promo_name) + '</div>' +
          '<div class="ce-next-event-detail">' + escapeHtml(next.event_name) + '</div>' +
          watchBtn +
        '</div>' +
      '</div>';
  }

  // P-FIX: Upcoming Cards section — shows ALL scheduled events for the
  // player's promo with fight counts + status. Per user feedback:
  // "currently there's no way to see them again once you leave the
  // matchmaking screen — events are invisible to player."
  function renderUpcomingCards(d) {
    var events = d.upcoming_events || [];
    if (!events.length) {
      return '';  // Don't show the section if no upcoming events.
    }
    var html = events.map(function (ev) {
      var fmtDate = formatLongDate(ev.event_date);
      var statusChip = ev.is_confirmed
        ? '<span class="ce-chip ce-chip-gold">CONFIRMED · ' + ev.fight_count + ' fights</span>'
        : '<span class="ce-chip ce-chip-default">DRAFT · ' + ev.fight_count + ' fights</span>';
      return '<div class="ce-upcoming-card" data-event-id="' + ev.event_id + '" role="button" tabindex="0">' +
        '<div class="ce-upcoming-card__date">' + escapeHtml(fmtDate) + '</div>' +
        '<div class="ce-upcoming-card__name">' + escapeHtml(ev.event_name || 'Untitled Event') + '</div>' +
        '<div class="ce-upcoming-card__meta">' + statusChip + '</div>' +
      '</div>';
    }).join('');
    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">UPCOMING CARDS</span><span class="ce-sec-sub ce-mono">' + events.length + ' scheduled</span></div>' +
        '<div class="ce-upcoming-list">' + html + '</div>' +
      '</div>';
  }

  function formatLongDate(dateStr) {
    if (!dateStr) return '—';
    var parts = String(dateStr).split('-');
    if (parts.length !== 3) return dateStr;
    var y = parseInt(parts[0], 10);
    var m = parseInt(parts[1], 10);
    var day = parseInt(parts[2], 10);
    var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var FULL = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    return (FULL[m - 1] || '?') + ' ' + day + ', ' + y;
  }

  function renderFighterWatch(d) {
    var cards = (d.fighter_watch || []);
    if (!cards.length) {
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">WHO\'S MAKING MOVES FOR YOU</span><span class="ce-sec-icon">🥊</span></div>' +
          '<div class="ce-empty-state">No one\'s making moves today. The divisions are resting.</div>' +
        '</div>';
    }

    var html = cards.map(function (w) {
      var ring = momentumRing(w.momentum_label);
      var firstLetter = (w.last5 && w.last5.length) ? w.last5[0] : 'N';
      var formBlocks = (w.last5 || []).map(function (r) {
        return '<div class="ce-form-block ce-form-' + r.toLowerCase() + '">' + escapeHtml(r) + '</div>';
      }).join('');
      var accentClass = w.accent === 'crimson' ? 'ce-watch-card-crimson' : '';
      var icon = w.label === 'TOP PROSPECT' ? '★'
               : w.label === 'HOTTEST STREAK' ? '🔥'
               : '▼';
      var pressureChip = w.pressure
        ? '<span class="ce-chip ce-chip-danger">' + escapeHtml(decodePhrase(w.pressure)) + '</span>'
        : '';
      // Career-phase chip: first word, capitalized (e.g., "a hungry prospect" → "A")
      var careerChip = '';
      if (w.career_phase) {
        var firstWord = w.career_phase.split(' ')[0];
        var capWord = firstWord.charAt(0).toUpperCase() + firstWord.slice(1);
        careerChip = '<span class="ce-chip ce-chip-default">' + escapeHtml(capWord) + '</span>';
      }

      return '' +
        '<div class="ce-watch-card ' + accentClass + '">' +
          '<div class="ce-watch-header"><span class="ce-watch-label">' + escapeHtml(w.label) + '</span><span class="ce-watch-icon">' + icon + '</span></div>' +
          '<div class="ce-watch-body">' +
            '<div class="ce-watch-portrait"><div class="ce-mom-ring" style="background:conic-gradient(' + ring.color + ' ' + (ring.pct * 3.6) + 'deg, #2a2f38 0deg)"><div class="ce-mom-ring-inner"><span class="ce-mom-ring-label" style="color:' + ring.color + '">' + escapeHtml(firstLetter) + '</span></div></div></div>' +
            '<div class="ce-watch-info">' +
              '<a class="ce-link ce-watch-name" href="#" data-fighter-id="' + w.fighter_id + '">' + escapeHtml(w.name) + '</a>' +
              '<p class="ce-watch-phrase">"' + escapeHtml(decodePhrase(w.momentum)) + '"</p>' +
              '<div class="ce-watch-chips">' + careerChip + pressureChip + '</div>' +
            '</div>' +
          '</div>' +
          '<div class="ce-form-meter">' + formBlocks + '</div>' +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">WHO\'S MAKING MOVES FOR YOU</span><span class="ce-sec-icon">🥊</span></div>' +
        '<div class="ce-watch-grid">' + html + '</div>' +
      '</div>';
  }

  function renderChampions(d) {
    var champs = d.champions || [];
    if (!champs.length) {
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-green"></div><span class="ce-sec-title ce-sec-title-green">YOUR CHAMPIONS</span><span class="ce-sec-icon">🏆</span></div>' +
          '<div class="ce-empty-state">No belts yet. The sport is yours for the taking.</div>' +
        '</div>';
    }
    var html = champs.map(function (c) {
      var rl = reignLength(c.champion_since_date, d.sim_date);
      var reignsChip = (c.title_reigns_count > 1)
        ? '<span class="ce-chip ce-chip-default">' + c.title_reigns_count + 'ND REIGN</span>'
        : '';
      return '' +
        '<div class="ce-champ-card">' +
          '<div class="ce-champ-wc">' + escapeHtml(c.weight_class) + '</div>' +
          '<a class="ce-link ce-champ-name" href="#" data-fighter-id="' + c.fighter_id + '">' + escapeHtml(c.name) + '</a>' +
          '<div class="ce-champ-meta">' +
            '<span class="ce-chip ce-chip-gold">' + escapeHtml(rl) + '</span>' +
            '<span class="ce-chip ce-chip-default">' + c.title_defenses_count + ' DEF</span>' +
            reignsChip +
          '</div>' +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-green"></div><span class="ce-sec-title ce-sec-title-green">YOUR CHAMPIONS</span><span class="ce-sec-icon">🏆</span></div>' +
        '<div class="ce-champ-grid">' + html + '</div>' +
      '</div>';
  }

  function renderRecentResults(d) {
    var results = d.recent_results || [];
    if (!results.length) {
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-white">CARDS YOU\'VE RUN</span></div>' +
          '<div class="ce-empty-state">No cards in the archive yet. Once you run your first show, it\'ll show up here.</div>' +
        '</div>';
    }
    var html = results.map(function (r) {
      var tier = ratingTier(r.overall_rating);
      var ratingDesc = r.rating_description || tier.phrase;
      return '' +
        '<div class="ce-result-card">' +
          '<div class="ce-result-top">' +
            '<span class="ce-result-promo">' + escapeHtml((r.promo_name || '').slice(0, 20)) + '</span>' +
            '<span class="ce-result-rating" style="color:' + tier.color + '">' + escapeHtml(tier.phrase) + '</span>' +
          '</div>' +
          '<div class="ce-result-name">' + escapeHtml((r.event_name || '').slice(0, 35)) + '</div>' +
          '<div class="ce-result-desc">"' + escapeHtml(ratingDesc) + '"</div>' +
          '<div class="ce-result-date">' + escapeHtml(r.event_date) + '</div>' +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-white">CARDS YOU\'VE RUN</span></div>' +
        '<div class="ce-results-grid">' + html + '</div>' +
      '</div>';
  }

  function renderRecentNews(d) {
    var news = d.recent_news || [];
    if (!news.length) {
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-white">WHAT THE WORLD SAYS ABOUT YOU</span></div>' +
          '<div class="ce-empty-state">The newswire is quiet. No stories have broken in the last 24 hours.</div>' +
        '</div>';
    }
    var html = news.map(function (n) {
      var badge = '<span class="ce-chip ce-chip-gold">' + escapeHtml(topicBadge(n.topic)) + '</span>';
      var bodyHtml = n.body ? '<p class="ce-news-body">' + escapeHtml(n.body) + '</p>' : '';
      var linkClass = n.fighter_id ? 'ce-link' : 'ce-news-headline-plain';
      var fighterAttr = n.fighter_id ? ' data-fighter-id="' + n.fighter_id + '"' : '';
      return '' +
        '<div class="ce-news-card">' +
          '<div class="ce-news-top">' + badge + '<span class="ce-news-date">' + escapeHtml(n.published_at) + '</span></div>' +
          '<a class="ce-news-headline ' + linkClass + '" href="#"' + fighterAttr + '>' + escapeHtml(n.headline) + '</a>' +
          bodyHtml +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-white">WHAT THE WORLD SAYS ABOUT YOU</span></div>' +
        '<div class="ce-news-list">' + html + '</div>' +
      '</div>';
  }

  // ============================================================
  // PUBLIC API
  // ============================================================

  /**
   * Render the full Dashboard into #screen-content using the
   * already-fetched payload `data`. Returns nothing.
   */
  function render(data) {
    var host = document.getElementById('screen-content');
    if (!host) { return; }

    var html = '' +
      '<div class="ce-dash">' +
        renderWelcome(data) +
        renderGradientHeader(data) +
        renderTopStory(data) +
        renderBiddingAlerts(data) +
        renderEchoes(data) +
        renderPromotionStatus(data) +
        renderNextEvent(data) +
        renderUpcomingCards(data) +
        renderFighterWatch(data) +
        renderChampions(data) +
        renderRecentResults(data) +
        renderRecentNews(data) +
      '</div>';

    host.innerHTML = html;

    // Wire up fighter-name hyperlinks → navigate to Fighter Profile.
    // (Skip hyperlinks inside .ce-bid-action-block — those are
    // Counter Offer buttons, not fighter-profile links.)
    host.querySelectorAll('[data-fighter-id]').forEach(function (el) {
      // Skip if this element is a bidding-alert counter-offer button
      // (those have their own click handler via wireBiddingAlerts).
      if (el.classList.contains('ce-bid-counter-btn')) return;
      el.addEventListener('click', function (evt) {
        evt.preventDefault();
        var fid = el.getAttribute('data-fighter-id');
        if (fid) {
          window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
        }
      });
    });

    // P3.2 — wire the "Watch the Show" launch button on the "Your
    // Next Card" section. Only enabled when sim_date == event_date
    // (the disabled state is set in renderNextEvent). On click,
    // navigates to fight_resolution (live mode) with the event_id.
    var fnLaunchBtn = document.getElementById('ce-launch-fight-night');
    if (fnLaunchBtn && !fnLaunchBtn.disabled) {
      fnLaunchBtn.addEventListener('click', function () {
        var eid = fnLaunchBtn.getAttribute('data-event-id');
        if (eid) {
          window.CE.app.navigate('fight_resolution', { event_id: Number(eid) });
        } else {
          window.CE.app.navigate('fight_resolution');
        }
      });
    }

    // Wire up upcoming card clicks — navigate to Matchmaking with the event_id.
    host.querySelectorAll('.ce-upcoming-card').forEach(function (card) {
      card.addEventListener('click', function () {
        var eid = card.getAttribute('data-event-id');
        if (eid) {
          window.CE.app.navigate('matchmaking', { event_id: Number(eid) });
        }
      });
      card.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault();
          card.click();
        }
      });
    });

    // Wire up bidding alert Counter Offer buttons.
    wireBiddingAlerts();
  }

  /**
   * Fetch fresh dashboard data from Python + render. Called on
   * initial Dashboard load + after every Advance Day.
   */
  function loadAndRender(promoId) {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Reading the wires…</div></div>';
    }
    return window.CE.bridge.getDashboardData(promoId).then(function (data) {
      render(data);
      return data;
    });
  }

  return {
    render: render,
    loadAndRender: loadAndRender
  };
})();
