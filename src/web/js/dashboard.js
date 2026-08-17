/* ============================================================
   CAGE EMPIRE — Dashboard Screen Renderer
   ============================================================
   Renders the full Dashboard screen into #screen-content using
   live data fetched via window.CE.bridge.getDashboardData(promo_id)
   + window.CE.bridge.getWatchlist(promo_id).

   Phase 5 Task 2 — redesigned per ChatGPT §13 sports newsroom
   hierarchy. Sections now render in this order:
     1. Welcome + Logo (header scaffolding)
     2. Gradient Header ("YOUR EMPIRE") — 135deg diagonal gold→card
     3. Today's Story (top_story) — gold-bordered card
     3a. Bidding War Alerts (rival AI signing intents)
     3b. Echoes (consequences of past moves)
     4. Promotion Status — 5 stat tiles with sparkline + trend arrows
     5. Important Fighters (3 watch cards: momentum ring + form meter
        + voice phrase)
     6. Watchlist (player's watched fighters, NEW — uses getWatchlist)
     7. Upcoming (Next Event + Upcoming Cards merged)
     8. What Changed (recent transactions + signings + injuries, NEW)
     9. Threats (injured champs + expiring contracts + low cash, NEW)
    10. Opportunities (high-heat rivalries + vacant titles + free
        agents, NEW)
    11. Champions (3-col grid)
    12. Recent Results (4-col grid)
    13. World Stories (top 5 rival promo news, NEW)
    14. Recent News ("What the World Says About You", vertical list)

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
      ranking_change: 'RANKING', morale: 'MORALE', rivalry: 'RIVALRY',
      // rival-promo news topics (World Stories section)
      fighter_signing: 'SIGNING', fight_result: 'RESULT',
      event_recap: 'RECAP', small_reward: 'BUZZ',
      memory_resurfacing: 'MEMORY', event_recap_hype: 'HYPE',
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
  // PHASE 5 TASK 2 — VISUAL RICHNESS HELPERS
  // (sparkline, trend arrow, SVG momentum ring)
  // ============================================================

  /**
   * Build SVG polyline points for a cash_history sparkline.
   * Maps an array of N cash values to evenly-spaced (x, y) coords
   * inside a 120×32 viewBox. Normalises y to fit [4, 28] with some
   * headroom. Returns the points string for <polyline points="...">.
   */
  function buildSparklinePoints(history, w, h) {
    if (!history || !history.length) { return ''; }
    w = w || 120; h = h || 32;
    var min = Math.min.apply(null, history);
    var max = Math.max.apply(null, history);
    var range = max - min;
    // Avoid divide-by-zero on a flat history (all values equal).
    if (range === 0) { range = Math.max(1, Math.abs(max) || 1); }
    var pad = 4;  // top/bottom padding inside the viewBox
    var usable = h - pad * 2;
    var step = history.length > 1 ? w / (history.length - 1) : 0;
    var pts = history.map(function (v, i) {
      var x = i * step;
      // Invert y so larger cash appears higher (SVG y grows downward).
      var y = pad + (1 - (v - min) / range) * usable;
      return x.toFixed(1) + ',' + y.toFixed(1);
    });
    return pts.join(' ');
  }

  /**
   * Build a trend arrow + signed-delta span for a stat tile.
   * `current` and `previous` are numbers (cash, rep, etc.).
   * Returns an HTML string like:
   *   '<span class="ce-trend-arrow ce-trend-up">▲</span><span class="ce-trend-val ce-mono">+$1.2M</span>'
   * For zero delta: '<span class="ce-trend-arrow ce-trend-flat">●</span><span class="ce-trend-val ce-mono">no change</span>'
   * If `previous` is null/undefined, shows ● no change honestly
   * (we don't fake trends when there's no historical snapshot).
   */
  function buildTrendArrow(current, previous, fmt) {
    fmt = fmt || formatCash;
    if (previous === null || previous === undefined || isNaN(previous)) {
      return '<span class="ce-trend-arrow ce-trend-flat">●</span>' +
             '<span class="ce-trend-val ce-mono">no change</span>';
    }
    var delta = (Number(current) || 0) - Number(previous);
    if (Math.abs(delta) < 0.5) {
      return '<span class="ce-trend-arrow ce-trend-flat">●</span>' +
             '<span class="ce-trend-val ce-mono">no change</span>';
    }
    var sign = delta > 0 ? '+' : '−';
    var absDelta = Math.abs(delta);
    var cls = delta > 0 ? 'ce-trend-up' : 'ce-trend-down';
    var arrow = delta > 0 ? '▲' : '▼';
    return '<span class="ce-trend-arrow ' + cls + '">' + arrow + '</span>' +
           '<span class="ce-trend-val ce-mono ' + cls + '">' + sign + fmt(absDelta) + '</span>';
  }

  /**
   * Build an SVG-based momentum ring with stroke-dasharray + CSS
   * transition for animated fill (replaces the old conic-gradient
   * approach). The SVG is 56×56 with a 6px stroke ring.
   *
   * `pct` is 0-100 (fill percentage). `color` is the ring stroke
   * color (gold/crimson/green/etc.). `centerLabel` is the short
   * text shown inside the ring (e.g., momentum tier first letter).
   *
   * The stroke-dasharray approach: circumference = 2*PI*r. We set
   * dasharray = circumference, then animate dashoffset from
   * circumference (empty) to circumference*(1 - pct/100) (filled).
   * The 600ms ease transition on stroke-dashoffset gives the
   * animated fill effect.
   */
  function buildMomentumRingSvg(pct, color, centerLabel) {
    pct = Math.max(0, Math.min(100, pct || 0));
    color = color || '#6b7280';
    var r = 22;       // ring radius (56 - 2*6 stroke = 44 dia / 2 = 22)
    var cx = 28, cy = 28;
    var circumference = 2 * Math.PI * r;  // ≈ 138.23
    var filled = circumference * (pct / 100);
    var offset = circumference - filled;
    return '' +
      '<div class="ce-momentum-ring">' +
        '<svg width="56" height="56" viewBox="0 0 56 56">' +
          '<circle class="ce-momentum-ring-track" cx="' + cx + '" cy="' + cy + '" r="' + r + '" ' +
            'fill="none" stroke="#2a2f38" stroke-width="6" />' +
          '<circle class="ce-momentum-ring-progress" cx="' + cx + '" cy="' + cy + '" r="' + r + '" ' +
            'fill="none" stroke="' + escapeHtml(color) + '" stroke-width="6" ' +
            'stroke-linecap="round" ' +
            'stroke-dasharray="' + circumference.toFixed(2) + '" ' +
            'stroke-dashoffset="' + circumference.toFixed(2) + '" ' +
            'data-target-offset="' + offset.toFixed(2) + '" ' +
            'transform="rotate(-90 ' + cx + ' ' + cy + ')" />' +
        '</svg>' +
        '<span class="ce-momentum-ring-label" style="color:' + escapeHtml(color) + '">' +
          escapeHtml(centerLabel || '') +
        '</span>' +
      '</div>';
  }

  /**
   * Force the momentum ring to animate from empty → its target fill
   * on the next frame. Called after the section is in the DOM.
   * Without this, the ring would jump straight to its target fill
   * (the CSS transition only fires when the property CHANGES, and
   * the initial render sets the final value).
   */
  function animateMomentumRings(host) {
    if (!host) return;
    var rings = host.querySelectorAll('.ce-momentum-ring-progress');
    rings.forEach(function (ring) {
      var target = ring.getAttribute('data-target-offset');
      if (target === null || target === undefined) return;
      // First, set to fully empty (offset = circumference),
      // then on the next frame set to target — the transition
      // picks up the change.
      // We use requestAnimationFrame to ensure the empty state is
      // painted before the target is applied.
      var empty = ring.getAttribute('stroke-dasharray');
      ring.setAttribute('stroke-dashoffset', empty);
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          ring.setAttribute('stroke-dashoffset', target);
        });
      });
    });
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
      '<div class="ce-grad-header ce-gradient-header">' +
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

    // Phase 5 Task 2 — dynamic sparkline points from cash_history.
    // Falls back to a flat baseline if no history (new promo).
    var hist = (d.cash_history && d.cash_history.length)
      ? d.cash_history
      : [d.cash, d.cash, d.cash, d.cash, d.cash, d.cash, d.cash];
    var sparkPts = buildSparklinePoints(hist, 120, 32);
    var sparkColor = (d.cash >= (d.yesterday_cash || d.cash))
      ? '#4ade80'   // up/flat → green
      : '#d63a3f';  // down → crimson
    var sparkPolygonPts = sparkPts + ' 120,32 0,32';  // close to bottom for fill

    // Trend arrows: cash uses yesterday_cash (real delta); the other
    // 4 tiles honestly show ● no change (no historical snapshot).
    var cashTrend = buildTrendArrow(d.cash, d.yesterday_cash, formatCash);
    var noChangeTrend = buildTrendArrow(0, null);  // ● no change

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-green"></div><span class="ce-sec-title ce-sec-title-green">' + escapeHtml((d.promo_name || 'YOUR PROMOTION').toUpperCase()) + '\'S HEALTH</span></div>' +
        '<div class="ce-stat-grid">' +

          // Cash — with sparkline + real trend arrow
          '<div class="ce-stat-tile">' +
            '<div class="ce-stat-label">YOUR WAR CHEST</div>' +
            '<div class="ce-stat-value ce-mono ce-stat-value-green">' + formatCash(d.cash) + '</div>' +
            '<div class="ce-trend">' + cashTrend + '</div>' +
            '<div class="ce-sparkline"><svg viewBox="0 0 120 32" preserveAspectRatio="none">' +
              '<polygon points="' + escapeHtml(sparkPolygonPts) + '" fill="rgba(74,222,128,0.1)" />' +
              '<polyline points="' + escapeHtml(sparkPts) + '" fill="none" stroke="' + sparkColor + '" stroke-width="2" />' +
            '</svg></div>' +
          '</div>' +

          // Reputation (voice band) — ● no change
          '<div class="ce-stat-tile">' +
            '<div class="ce-stat-label">YOUR STANDING</div>' +
            '<div class="ce-stat-value ce-descriptor">' + escapeHtml(d.reputation_phrase) + '</div>' +
            '<div class="ce-trend">' + noChangeTrend + '</div>' +
            '<div class="ce-stat-bar"><div class="ce-stat-bar-fill ce-stat-bar-green" style="width:' + repPct + '%"></div></div>' +
          '</div>' +

          // Fan Trust (voice band) — ● no change
          '<div class="ce-stat-tile">' +
            '<div class="ce-stat-label">THE FANS\' TRUST IN YOU</div>' +
            '<div class="ce-stat-value ce-descriptor">' + escapeHtml(d.fan_trust_phrase) + '</div>' +
            '<div class="ce-trend">' + noChangeTrend + '</div>' +
            '<div class="ce-stat-bar"><div class="ce-stat-bar-fill ce-stat-bar-green" style="width:' + ftPct + '%"></div></div>' +
          '</div>' +

          // Roster — ● no change (with chips)
          '<div class="ce-stat-tile">' +
            '<div class="ce-stat-label">YOUR ROSTER</div>' +
            '<div class="ce-stat-value ce-mono">' + d.roster_count + '</div>' +
            '<div class="ce-trend">' + noChangeTrend + '</div>' +
            '<div class="ce-stat-chips">' +
              (sizeTier ? '<span class="ce-chip ce-chip-default">' + escapeHtml(sizeTier) + '</span>' : '') +
              (broadcast ? '<span class="ce-chip ce-chip-default">' + escapeHtml(broadcast) + '</span>' : '') +
            '</div>' +
          '</div>' +

          // Champions — ● no change
          '<div class="ce-stat-tile">' +
            '<div class="ce-stat-label">YOUR CHAMPIONS</div>' +
            '<div class="ce-stat-value ce-mono ce-stat-value-green">' + d.champ_count + ' of ' + (d.total_wcs || 8) + '</div>' +
            '<div class="ce-trend">' + noChangeTrend + '</div>' +
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
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">IMPORTANT FIGHTERS</span><span class="ce-sec-icon">🥊</span></div>' +
          '<div class="ce-empty-state">No one\'s making moves today. The divisions are resting.</div>' +
        '</div>';
    }

    var html = cards.map(function (w) {
      var ring = momentumRing(w.momentum_label);
      var firstLetter = (w.last5 && w.last5.length) ? w.last5[0] : 'N';
      // Phase 5 Task 2 — SVG momentum ring (replaces conic-gradient)
      // with stroke-dasharray + CSS transition (600ms ease).
      var ringSvg = buildMomentumRingSvg(ring.pct, ring.color, firstLetter);
      // Form meter W/L blocks — new modifier classes per spec
      // (--win/--loss/--draw), 16×16px in dashboard.css.
      var formBlocks = (w.last5 || []).map(function (r) {
        var mod = r === 'W' ? 'win' : r === 'L' ? 'loss' : r === 'D' ? 'draw' : 'none';
        return '<div class="ce-form-block ce-form-block--' + mod + '">' + escapeHtml(r) + '</div>';
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
      // Phase 5 Task 2 — voice italic phrase under fighter name
      // (uses momentum descriptor from fighter_descriptors).
      var voicePhrase = decodePhrase(w.momentum);

      return '' +
        '<div class="ce-watch-card ' + accentClass + '">' +
          '<div class="ce-watch-header"><span class="ce-watch-label">' + escapeHtml(w.label) + '</span><span class="ce-watch-icon">' + icon + '</span></div>' +
          '<div class="ce-watch-body">' +
            '<div class="ce-watch-portrait">' + ringSvg + '</div>' +
            '<div class="ce-watch-info">' +
              '<a class="ce-link ce-watch-name" href="#" data-fighter-id="' + w.fighter_id + '">' + escapeHtml(w.name) + '</a>' +
              '<p class="ce-watch-phrase descriptor-small">"' + escapeHtml(voicePhrase) + '"</p>' +
              '<div class="ce-watch-chips">' + careerChip + pressureChip + '</div>' +
            '</div>' +
          '</div>' +
          '<div class="ce-form-meter">' + formBlocks + '</div>' +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">IMPORTANT FIGHTERS</span><span class="ce-sec-icon">🥊</span></div>' +
        '<div class="ce-watch-grid">' + html + '</div>' +
      '</div>';
  }

  // ============================================================
  // PHASE 5 TASK 2 — WATCHLIST SECTION
  // (calls Api.get_watchlist() separately so the section can refresh
  //  in-place when the player removes a fighter, without re-fetching
  //  the entire Dashboard payload.)
  // ============================================================
  function renderWatchlist(watchlist) {
    var cards = (watchlist || []);
    if (!cards.length) {
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">YOUR WATCHLIST</span><span class="ce-sec-icon">★</span></div>' +
          '<div class="ce-empty-state">Your watchlist is empty. Tap the ☆ on a fighter\'s profile to add them here.</div>' +
        '</div>';
    }

    // Cap to 6 cards per the spec (the watchlist API caps at 12; we
    // show the first 6 on the dashboard to keep the layout compact).
    var shown = cards.slice(0, 6);

    var html = shown.map(function (w) {
      var ring = momentumRing(w.momentum_label || 'stable');
      // Use the first letter of the momentum_label (canonical tier)
      // for the ring center — falls back to "★" if no label.
      var firstLetter = (w.momentum_label && w.momentum_label.length)
        ? w.momentum_label.charAt(0).toUpperCase()
        : '★';
      var ringSvg = buildMomentumRingSvg(ring.pct, ring.color, firstLetter);
      // No last5 in get_watchlist response — show a flat 5-block
      // meter of "N" (no history yet) so the visual layout matches
      // the Important Fighters cards.
      var last5 = w.last5 || ['N','N','N','N','N'];
      var formBlocks = last5.map(function (r) {
        var mod = r === 'W' ? 'win' : r === 'L' ? 'loss' : r === 'D' ? 'draw' : 'none';
        return '<div class="ce-form-block ce-form-block--' + mod + '">' + escapeHtml(r) + '</div>';
      }).join('');
      var voicePhrase = w.momentum_phrase || '';
      var champChip = w.is_champion
        ? '<span class="ce-chip ce-chip-gold">CHAMPION</span>'
        : '';

      return '' +
        '<div class="ce-watch-card ce-watch-card--list" data-watchlist-fighter="' + w.fighter_id + '">' +
          '<div class="ce-watch-header">' +
            '<a class="ce-link ce-watch-name" href="#" data-fighter-id="' + w.fighter_id + '">' + escapeHtml(w.name) + '</a>' +
            '<a class="ce-watch-remove" href="#" data-watchlist-remove="' + w.fighter_id + '" title="Remove from watchlist">☆ Remove</a>' +
          '</div>' +
          '<div class="ce-watch-body">' +
            '<div class="ce-watch-portrait">' + ringSvg + '</div>' +
            '<div class="ce-watch-info">' +
              '<div class="ce-watch-meta ce-mono">' + escapeHtml(w.weight_class_name || '—') + ' · ' + escapeHtml(w.record || '—') + '</div>' +
              '<p class="ce-watch-phrase descriptor-small">"' + escapeHtml(voicePhrase) + '"</p>' +
              '<div class="ce-watch-chips">' + champChip + '</div>' +
            '</div>' +
          '</div>' +
          '<div class="ce-form-meter">' + formBlocks + '</div>' +
        '</div>';
    }).join('');

    var overflow = cards.length - shown.length;
    var overflowHtml = overflow > 0
      ? '<div class="ce-watch-overflow ce-mono">+ ' + overflow + ' more on your roster →</div>'
      : '';

    return '' +
      '<div class="ce-section" id="ce-watchlist-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">YOUR WATCHLIST</span><span class="ce-sec-sub ce-mono">' + cards.length + ' watched</span><span class="ce-sec-icon">★</span></div>' +
        '<div class="ce-watch-grid ce-watchlist-grid">' + html + '</div>' +
        overflowHtml +
      '</div>';
  }

  // ============================================================
  // PHASE 5 TASK 2 — "WHAT CHANGED" SECTION
  // (recent transactions + signings + injuries, last 7 days)
  // ============================================================
  function renderWhatChanged(d) {
    var txs = d.recent_transactions || [];
    var signings = d.recent_signings || [];
    var injuries = d.recent_injuries || [];
    var hasAny = txs.length || signings.length || injuries.length;
    if (!hasAny) {
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-white">WHAT CHANGED</span></div>' +
          '<div class="ce-empty-state">Nothing new has broken in the last 7 days. Advance the sim to see what develops.</div>' +
        '</div>';
    }

    // Build a merged, dated list of changes (each item has date +
    // type + description + optional fighter_id). Sort newest-first.
    var items = [];
    txs.forEach(function (t) {
      items.push({
        date: t.date || '',
        kind: 'transaction',
        badge: 'TRANSACTION',
        chipClass: 'ce-chip-default',
        body: escapeHtml(t.description || t.type || 'transaction') +
              ' <span class="ce-mono">' + (t.amount >= 0 ? '+' : '−') +
              formatCash(Math.abs(t.amount)) + '</span>',
      });
    });
    signings.forEach(function (s) {
      items.push({
        date: (s.published_at || '').split(' ')[0],
        kind: 'signing',
        badge: 'SIGNING',
        chipClass: 'ce-chip-gold',
        body: escapeHtml(s.headline || 'New signing'),
        fighter_id: s.fighter_id,
      });
    });
    injuries.forEach(function (i) {
      items.push({
        date: i.start_date || '',
        kind: 'injury',
        badge: 'INJURY',
        chipClass: 'ce-chip-danger',
        body: escapeHtml(i.fighter_name || 'A fighter') +
              ' is out with ' + escapeHtml(i.injury_type || 'an injury') +
              ' — expected back ' + escapeHtml(i.projected_return_date || 'soon') + '.',
      });
    });
    // Sort newest-first (string dates sort lexically for YYYY-MM-DD).
    items.sort(function (a, b) { return (b.date || '').localeCompare(a.date || ''); });
    // Cap to 7 to keep the section compact.
    items = items.slice(0, 7);

    var html = items.map(function (it) {
      var fighterLink = it.fighter_id
        ? ' <a class="ce-link" href="#" data-fighter-id="' + it.fighter_id + '">View →</a>'
        : '';
      return '' +
        '<div class="ce-change-item ce-change-' + it.kind + '">' +
          '<div class="ce-change-top">' +
            '<span class="ce-chip ' + it.chipClass + '">' + it.badge + '</span>' +
            '<span class="ce-change-date ce-mono">' + escapeHtml(it.date || '—') + '</span>' +
          '</div>' +
          '<p class="ce-change-body">' + it.body + fighterLink + '</p>' +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-white">WHAT CHANGED</span></div>' +
        '<div class="ce-change-list">' + html + '</div>' +
      '</div>';
  }

  // ============================================================
  // PHASE 5 TASK 2 — "THREATS" SECTION
  // (injured champions + expiring contracts + low cash + low fan trust)
  // ============================================================
  function renderThreats(d) {
    var threats = d.threats || [];
    if (!threats.length) {
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-crimson"></div><span class="ce-sec-title ce-sec-title-crimson">THREATS</span><span class="ce-sec-icon">⚠</span></div>' +
          '<div class="ce-empty-state">No threats right now — enjoy the calm.</div>' +
        '</div>';
    }

    var html = threats.map(function (t) {
      var sevClass = 'ce-threat-card--' + (t.severity || 'low');
      var fighterLink = t.fighter_id
        ? ' <a class="ce-link" href="#" data-fighter-id="' + t.fighter_id + '">View →</a>'
        : '';
      return '' +
        '<div class="ce-threat-card ' + sevClass + '">' +
          '<div class="ce-threat-top">' +
            '<span class="ce-chip ce-chip-danger">' + escapeHtml((t.kind || 'threat').toUpperCase().replace(/_/g, ' ')) + '</span>' +
            '<span class="ce-chip ce-chip-default">' + escapeHtml((t.severity || 'low').toUpperCase()) + '</span>' +
          '</div>' +
          '<p class="ce-threat-message">' + escapeHtml(t.message || '') + fighterLink + '</p>' +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-crimson"></div><span class="ce-sec-title ce-sec-title-crimson">THREATS</span><span class="ce-sec-icon">⚠</span></div>' +
        '<div class="ce-threat-list">' + html + '</div>' +
      '</div>';
  }

  // ============================================================
  // PHASE 5 TASK 2 — "OPPORTUNITIES" SECTION
  // (high-heat rivalries + vacant titles + free agent targets)
  // ============================================================
  function renderOpportunities(d) {
    var opps = d.opportunities || [];
    if (!opps.length) {
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-green"></div><span class="ce-sec-title ce-sec-title-green">OPPORTUNITIES</span><span class="ce-sec-icon">★</span></div>' +
          '<div class="ce-empty-state">No fresh opportunities on the board. Advance the sim to see what opens up.</div>' +
        '</div>';
    }

    var html = opps.map(function (o) {
      var sevClass = 'ce-opp-card--' + (o.severity || 'low');
      var fighterLink = o.fighter_id
        ? ' <a class="ce-link" href="#" data-fighter-id="' + o.fighter_id + '">View →</a>'
        : '';
      return '' +
        '<div class="ce-opp-card ' + sevClass + '">' +
          '<div class="ce-opp-top">' +
            '<span class="ce-chip ce-chip-gold">' + escapeHtml((o.kind || 'opportunity').toUpperCase().replace(/_/g, ' ')) + '</span>' +
            '<span class="ce-chip ce-chip-default">' + escapeHtml((o.severity || 'low').toUpperCase()) + '</span>' +
          '</div>' +
          '<p class="ce-opp-message">' + escapeHtml(o.message || '') + fighterLink + '</p>' +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-green"></div><span class="ce-sec-title ce-sec-title-green">OPPORTUNITIES</span><span class="ce-sec-icon">★</span></div>' +
        '<div class="ce-opp-list">' + html + '</div>' +
      '</div>';
  }

  // ============================================================
  // PHASE 5 TASK 2 — "WORLD STORIES" SECTION
  // (top 5 news items from rival promotions)
  // ============================================================
  function renderWorldStories(d) {
    var stories = d.world_stories || [];
    if (!stories.length) {
      return '' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-white">WORLD STORIES</span></div>' +
          '<div class="ce-empty-state">The wires from rival promotions are quiet. Advance the sim to see what develops.</div>' +
        '</div>';
    }

    var html = stories.map(function (s) {
      var badge = '<span class="ce-chip ce-chip-default">' + escapeHtml(topicBadge(s.topic)) + '</span>';
      var promoChip = '<span class="ce-chip ce-chip-gold">' + escapeHtml(s.promo_name || '') + '</span>';
      var linkClass = s.fighter_id ? 'ce-link' : 'ce-news-headline-plain';
      var fighterAttr = s.fighter_id ? ' data-fighter-id="' + s.fighter_id + '"' : '';
      var dateStr = (s.published_at || '').split(' ')[0];
      return '' +
        '<div class="ce-world-story">' +
          '<div class="ce-world-top">' + badge + promoChip + '<span class="ce-news-date">' + escapeHtml(dateStr) + '</span></div>' +
          '<a class="ce-news-headline ' + linkClass + '" href="#"' + fighterAttr + '>' + escapeHtml(s.headline) + '</a>' +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-section">' +
        '<div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-white">WORLD STORIES</span></div>' +
        '<div class="ce-world-list">' + html + '</div>' +
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

  // Module-level state: the promo_id of the currently-rendered
  // Dashboard. Used by refreshWatchlist() so the ☆ Remove handler
  // can re-fetch the watchlist without re-fetching the full Dashboard.
  var currentPromoId = null;
  // Cached dashboard payload — used by refreshWatchlist to re-render
  // the watchlist section in-place (the watchlist render function
  // only needs the watchlist data, but we keep the cache for safety).
  var lastDashboardData = null;

  /**
   * Render the full Dashboard into #screen-content using the
   * already-fetched payload `data`. Returns nothing.
   *
   * Phase 5 Task 2 — now accepts an optional `watchlist` arg (the
   * result of getWatchlist()). When omitted, the Watchlist section
   * renders an empty state.
   */
  function render(data, watchlist) {
    var host = document.getElementById('screen-content');
    if (!host) { return; }

    // Cache for refreshWatchlist.
    lastDashboardData = data;

    // §13 hierarchy:
    //   1. Welcome + Logo (header scaffolding)
    //   2. Gradient Header
    //   3. Today's Story (top_story)
    //   3a. Bidding War Alerts (urgent — keep high on page)
    //   3b. Echoes (consequences of past moves)
    //   4. Promotion Status (5 stat tiles + sparkline + trends)
    //   5. Important Fighters (3 watch cards)
    //   6. Watchlist (NEW — Task 3 watchlist, refreshed in-place)
    //   7. Upcoming (Next Event + Upcoming Cards merged)
    //   8. What Changed (NEW — recent transactions + signings + injuries)
    //   9. Threats (NEW — injured champs + expiring contracts + low cash)
    //  10. Opportunities (NEW — high-heat rivalries + vacant titles + FA)
    //  11. Champions
    //  12. Recent Results
    //  13. World Stories (NEW — top 5 rival promo news)
    //  14. Recent News ("What the World Says About You")
    var html = '' +
      '<div class="ce-dash">' +
        renderWelcome(data) +
        renderGradientHeader(data) +
        renderTopStory(data) +
        renderBiddingAlerts(data) +
        renderEchoes(data) +
        renderPromotionStatus(data) +
        renderFighterWatch(data) +
        renderWatchlist(watchlist) +
        renderNextEvent(data) +
        renderUpcomingCards(data) +
        renderWhatChanged(data) +
        renderThreats(data) +
        renderOpportunities(data) +
        renderChampions(data) +
        renderRecentResults(data) +
        renderWorldStories(data) +
        renderRecentNews(data) +
      '</div>';

    host.innerHTML = html;

    // Wire up fighter-name hyperlinks → navigate to Fighter Profile.
    // (Skip hyperlinks inside .ce-bid-action-block — those are
    // Counter Offer buttons, not fighter-profile links. Also skip
    // the watchlist ☆ Remove links — they have their own handler.)
    host.querySelectorAll('[data-fighter-id]').forEach(function (el) {
      // Skip if this element is a bidding-alert counter-offer button
      // (those have their own click handler via wireBiddingAlerts).
      if (el.classList.contains('ce-bid-counter-btn')) return;
      // Skip watchlist ☆ Remove links — they use data-watchlist-remove.
      if (el.classList.contains('ce-watch-remove')) return;
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

    // Phase 5 Task 2 — wire up watchlist ☆ Remove links. Each calls
    // removeFromWatchlist(fid) + refreshes ONLY the watchlist section
    // (doesn't re-fetch the whole Dashboard payload).
    host.querySelectorAll('[data-watchlist-remove]').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        var fid = link.getAttribute('data-watchlist-remove');
        if (!fid) return;
        // Optimistic: fade the card out while the API call is in-flight.
        var card = link.closest('[data-watchlist-fighter]');
        if (card) { card.classList.add('ce-watch-card--removing'); }
        window.CE.bridge.removeFromWatchlist(Number(fid)).then(function () {
          return refreshWatchlist();
        }).catch(function () {
          if (card) { card.classList.remove('ce-watch-card--removing'); }
        });
      });
    });

    // Wire up bidding alert Counter Offer buttons.
    wireBiddingAlerts();

    // Phase 5 Task 2 — kick off the momentum ring animations.
    // Slight delay (16ms ≈ 1 frame) to ensure the SVG is painted
    // before we trigger the dashoffset transition.
    setTimeout(function () { animateMomentumRings(host); }, 16);
  }

  /**
   * Re-fetch the watchlist + re-render ONLY the watchlist section
   * in-place (the rest of the Dashboard stays untouched). Called
   * after the player clicks ☆ Remove on a watch card.
   *
   * Phase 5 Task 2 — per the spec, this MUST refresh ONLY the
   * watchlist section (not the whole Dashboard). The watchlist
   * section is wrapped in #ce-watchlist-section so we can swap its
   * innerHTML without touching the rest of the DOM. We also re-wire
   * the ☆ Remove click handlers on the new DOM (the old handlers
   * were bound to elements that no longer exist).
   *
   * Falls back to a full re-render via loadAndRender if the
   * in-place swap can't be done (e.g., the section is missing).
   */
  function refreshWatchlist() {
    if (!currentPromoId && lastDashboardData) {
      currentPromoId = lastDashboardData.promo_id;
    }
    if (currentPromoId === null) {
      // Can't refresh — fall back to a full reload.
      return loadAndRender(lastDashboardData ? lastDashboardData.promo_id : null);
    }
    return window.CE.bridge.getWatchlist(currentPromoId).then(function (watchlist) {
      var section = document.getElementById('ce-watchlist-section');
      if (!section) {
        // Section isn't in the DOM (e.g., dashboard navigated away).
        // Fall back silently — no-op.
        return watchlist;
      }
      // In-place swap: replace ONLY the watchlist section's
      // innerHTML with the re-rendered content.
      section.outerHTML = renderWatchlist(watchlist);
      // Re-wire the ☆ Remove handlers on the freshly-rendered DOM.
      // (The old click handlers are gone with the old DOM nodes.)
      var host = document.getElementById('screen-content');
      if (host) {
        host.querySelectorAll('[data-watchlist-remove]').forEach(function (link) {
          // Skip if already wired (shouldn't happen, but defensive).
          if (link.__ceWatchRemoveWired) return;
          link.__ceWatchRemoveWired = true;
          link.addEventListener('click', function (evt) {
            evt.preventDefault();
            var fid = link.getAttribute('data-watchlist-remove');
            if (!fid) return;
            var card = link.closest('[data-watchlist-fighter]');
            if (card) { card.classList.add('ce-watch-card--removing'); }
            window.CE.bridge.removeFromWatchlist(Number(fid)).then(function () {
              return refreshWatchlist();
            }).catch(function () {
              if (card) { card.classList.remove('ce-watch-card--removing'); }
            });
          });
        });
        // Also re-wire fighter-name links inside the new watchlist
        // section (the global handler in render() only fires on the
        // initial render — newly-added DOM nodes need their own).
        host.querySelectorAll('#ce-watchlist-section [data-fighter-id]').forEach(function (el) {
          if (el.__ceFighterLinkWired) return;
          el.__ceFighterLinkWired = true;
          if (el.classList.contains('ce-watch-remove')) return;
          el.addEventListener('click', function (evt) {
            evt.preventDefault();
            var fid = el.getAttribute('data-fighter-id');
            if (fid) {
              window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
            }
          });
        });
        // Re-trigger momentum ring animations on the new DOM nodes.
        setTimeout(function () {
          animateMomentumRings(host.querySelector('#ce-watchlist-section'));
        }, 16);
      }
      return watchlist;
    });
  }

  /**
   * Fetch fresh dashboard data from Python + render. Called on
   * initial Dashboard load + after every Advance Day.
   *
   * Phase 5 Task 2 — now fetches the watchlist in parallel with
   * the dashboard payload (the watchlist is a separate API call so
   * it can be refreshed in-place by refreshWatchlist).
   */
  function loadAndRender(promoId) {
    currentPromoId = promoId;
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Reading the wires…</div></div>';
    }
    // Fetch both in parallel — Promise.all settles when both done.
    return Promise.all([
      window.CE.bridge.getDashboardData(promoId),
      window.CE.bridge.getWatchlist(promoId).catch(function () { return []; }),
    ]).then(function (results) {
      var data = results[0];
      var watchlist = results[1] || [];
      render(data, watchlist);
      return data;
    });
  }

  return {
    render: render,
    loadAndRender: loadAndRender,
    refreshWatchlist: refreshWatchlist
  };
})();
