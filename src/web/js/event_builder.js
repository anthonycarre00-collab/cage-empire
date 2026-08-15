/* ============================================================
   CAGE EMPIRE — Event Builder Screen ("Stack a Card")
   ============================================================
   Phase E3.1 (docs/PHASE_E3_PLAN.md §1.E3.1) + F3 UX refresh
   (docs/FIX_PLAN_CACHE_CASH_EB.md §3) + Phase M4 integration
   (docs/MASTER_PLAN_MATCHMAKING.md §1.2) + Phase P2 redesign
   (docs/COMPREHENSIVE_FIX_PLAN.md §Group B #5-7).

   Renders the Event Builder screen into #screen-content using data
   fetched via window.CE.bridge.getEventBuilderData() +
   getEventPreview(params) + createEvent(params).

   6 sections (P2 reorder — Name → Date → Venue → Business End):
     1. 🎫 STACK A CARD       — gold section header + promo strip
     2. 📛 NAME YOUR EVENT    — text input (auto-defaults to
                                "<Promo Name> <Next Number>")
     3. 📅 PICK YOUR DATE     — date input + conflict warnings
     4. 🏟 PICK YOUR VENUE    — capacity / country / region filterable
                                compact grid + ⚡ Quick Pick (P2.2)
     5. 💼 THE BUSINESS END   — sliders: ticket, marketing, ppv, is_ppv
                                (renamed from "Set Your Levers" per P2.3 —
                                Cage Empire promoter register)
     6. 📊 PROJECTED OUTCOME  — live P&L preview (debounced 200ms)

   Phase M4 integration: after createEvent succeeds, navigates to the
   Matchmaking screen with the new event_id (so the player can
   immediately start booking fights). Previously navigated to the
   dashboard — that left the player with an empty event (no fights).

   F3 (docs/FIX_PLAN_CACHE_CASH_EB.md §3) UX improvements:
       levers like ticket price; reverse for "bad" like marketing
       spend where higher = bigger expense), 16px gold thumb, value
       bubble above the thumb, min/max labels below the track.
     - Section header icons: 🎫/🏟/🎚/📊 prefixes.
     - Preview visual hierarchy: two-column Revenue | Expenses layout
       (already shipped in Phase E3) PLUS a prominent net-profit banner
       with color-coded background gradient (green/yellow/red) + the
       voice phrase below in italic + cash-after-event projection:
       "Your war chest after this card: $X".

   Voice/design: NO raw potential/ceiling numbers. PPV buys shown as
   a projected integer is OK (it's computed, not a hidden attribute).
   Ownership language: "YOUR NEXT CARD", "YOUR WAR CHEST".
   ============================================================ */

window.CE = window.CE || {};

window.CE.eventBuilder = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    promo: null,
    venues: [],
    countries: [],         // P2.2 — unique nations for the dropdown
    regions: [],           // P2.2 — unique regions for the dropdown
    weightClasses: [],
    fightersByWc: [],
    // P2.1 — event name (auto-defaulted to "<Promo> <Next N>" by the
    // backend; the player can override).
    eventName: '',
    defaultEventName: '',
    venueFilter: 'all',  // 'all' | 'small' | 'mid' | 'large'
    countryFilter: 1,    // P2.2 — default to United States (nation_id=1)
    regionFilter: 0,     // P2.2 — 0 = all regions, else region_id
    selectedVenueId: null,
    selectedVenue: null,
    // Lever values (defaults per spec).
    ticketPrice: 80,
    marketingSpend: 0,
    ppvPrice: 60,
    isPpv: false,
    // Last preview result (so the CTA bar can show net profit).
    lastPreview: null,
    // Debounce timer for preview fetch.
    _previewTimer: null,
    _previewInFlight: false,
    // MM2 — date picker state.
    // event_date: "YYYY-MM-DD" string. Default sim_date + 30 days
    // (WMMA5's 1-month minimum, more lenient than the engine's 14-day
    // floor for faster early-game pace — see docs/RESEARCH_WMMA5_FM_V2.md
    // §4 Priority 4A). Set from navigation params (calendar pre-fill)
    // or initialized on first load.
    eventDate: null,
    simDate: null,           // current sim date "YYYY-MM-DD"
    minLeadDays: 14,
    dateConflicts: null,     // last get_date_conflicts result
    _dateConflictsInFlight: false,
    _dateConflictsTimer: null,
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
    if (abs >= 1e6) s = '$' + (abs / 1e6).toFixed(1) + 'M';
    else if (abs >= 1e3) s = '$' + (abs / 1e3).toFixed(0) + 'K';
    else s = '$' + Math.round(abs).toLocaleString();
    return (neg ? '-' : '') + s;
  }

  function venueTier(cap) {
    if (cap < 5000) return 'small';
    if (cap < 15000) return 'mid';
    return 'large';
  }

  function venueTierLabel(t) {
    if (t === 'small') return 'small (<5k)';
    if (t === 'mid') return 'mid (5-15k)';
    if (t === 'large') return 'large (15k+)';
    return 'all';
  }

  // ============================================================
  // RENDER — PROMO STRIP
  // ============================================================
  function renderPromoStrip() {
    var p = state.promo;
    if (!p) return '';
    var cashClass = p.is_cash_negative ? ' ce-eb-promo-strip__cash--negative' : '';
    return '' +
      '<div class="ce-eb-promo-strip">' +
        '<div class="ce-eb-promo-strip__name">' + escapeHtml(p.name) + '</div>' +
        '<div class="ce-eb-promo-strip__meta">REP <span>' + escapeHtml(p.reputation_phrase) + '</span></div>' +
        '<div class="ce-eb-promo-strip__meta">TRUST <span>' + escapeHtml(p.fan_trust_phrase) + '</span></div>' +
        '<div class="ce-eb-promo-strip__meta">TIER <span>' + escapeHtml((p.broadcast_tier || '').toUpperCase()) + '</span></div>' +
        '<div class="ce-eb-promo-strip__cash' + cashClass + '">YOUR WAR CHEST · ' + escapeHtml(p.cash_display) + '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — VENUE GRID (P2.2: capacity + country + region filter)
  // ============================================================
  function renderVenueFilters() {
    var tiers = [
      { id: 'all', label: 'All Capacities' },
      { id: 'small', label: 'Small (<5k)' },
      { id: 'mid', label: 'Mid (5-15k)' },
      { id: 'large', label: 'Large (15k+)' },
    ];
    var tierChips = tiers.map(function (t) {
      var active = state.venueFilter === t.id ? ' ce-chip--active' : '';
      return '<div class="ce-chip ce-chip-default' + active + '" data-venue-filter="' + t.id + '" role="button" tabindex="0">' +
        escapeHtml(t.label) + '</div>';
    }).join('');
    // P2.2 — country + region dropdowns. Region dropdown filters to
    // regions of the currently-selected country (or all regions when
    // country is "all").
    var countryOpts = '<option value="0"' + (state.countryFilter === 0 ? ' selected' : '') +
      '>All Countries</option>' +
      state.countries.map(function (c) {
        var sel = state.countryFilter === c.id ? ' selected' : '';
        return '<option value="' + c.id + '"' + sel + '>' + escapeHtml(c.name) + '</option>';
      }).join('');
    var regionPool = state.regions.filter(function (r) {
      if (state.countryFilter === 0) return true;
      return r.country_id === state.countryFilter;
    });
    var regionOpts = '<option value="0"' + (state.regionFilter === 0 ? ' selected' : '') +
      '>All Regions</option>' +
      regionPool.map(function (r) {
        var sel = state.regionFilter === r.id ? ' selected' : '';
        return '<option value="' + r.id + '"' + sel + '>' + escapeHtml(r.name) + '</option>';
      }).join('');
    return '<div class="ce-eb-venue-filters">' +
      '<div class="ce-eb-venue-filter-chips">' + tierChips + '</div>' +
      '<div class="ce-eb-venue-filter-selects">' +
        '<label class="ce-eb-filter-label">Country ' +
          '<select id="ce-eb-country-filter" class="ce-eb-filter-select">' +
            countryOpts +
          '</select>' +
        '</label>' +
        '<label class="ce-eb-filter-label">Region ' +
          '<select id="ce-eb-region-filter" class="ce-eb-filter-select">' +
            regionOpts +
          '</select>' +
        '</label>' +
      '</div>' +
    '</div>';
  }

  function renderVenueGrid() {
    if (!state.venues.length) {
      return '<div class="ce-eb-empty">No venues available in your region. Try expanding your market reach.</div>';
    }
    var filtered = state.venues.filter(function (v) {
      if (state.venueFilter !== 'all' &&
          venueTier(v.capacity) !== state.venueFilter) return false;
      // P2.2 — country filter (skip when 0 = all).
      if (state.countryFilter && v.nation_id !== state.countryFilter) return false;
      // P2.2 — region filter (skip when 0 = all). When the country
      // filter is set, regions outside that country are already
      // filtered out — the region dropdown only offers in-country
      // regions, so this check is a no-op in that case.
      if (state.regionFilter && v.region_id !== state.regionFilter) return false;
      return true;
    });
    if (!filtered.length) {
      return '<div class="ce-eb-empty">No venues match this filter. Try a different capacity range, country, or region.</div>';
    }
    return '<div class="ce-eb-venue-grid">' + filtered.map(function (v) {
      var selected = state.selectedVenueId === v.venue_id ? ' ce-eb-venue-card--selected' : '';
      var icon = v.icon || '🏛';
      var flag = v.nation_flag || '🏳';
      var nationName = v.nation_name || '';
      // P2.2 — compact venue card. Capacity icon + name on row 1,
      // city/flag on row 2, capacity (mono) on row 3, type chip +
      // rental on row 4. Tighter padding + smaller fonts than F3 so
      // the grid fits ~4 cards per row at 1200px (was 3 cards).
      return '<div class="ce-eb-venue-card' + selected + '" data-venue-id="' + v.venue_id + '" role="button" tabindex="0" aria-pressed="' + (selected ? 'true' : 'false') + '">' +
        '<div class="ce-eb-venue-card__check" aria-hidden="true">✓</div>' +
        '<div class="ce-eb-venue-card__head">' +
          '<span class="ce-eb-venue-card__icon">' + icon + '</span>' +
          '<span class="ce-eb-venue-card__name">' + escapeHtml(v.name) + '</span>' +
        '</div>' +
        '<div class="ce-eb-venue-card__city">' +
          '<span class="ce-eb-venue-card__flag">' + flag + '</span>' +
          '<span>' + escapeHtml(v.city_name) + (nationName ? ', ' + escapeHtml(nationName) : '') + '</span>' +
        '</div>' +
        '<div class="ce-eb-venue-card__capacity">' +
          v.capacity.toLocaleString() + ' <span class="ce-eb-venue-card__capacity-unit">seats</span>' +
        '</div>' +
        '<div class="ce-eb-venue-card__chips">' +
          '<span class="ce-eb-venue-card__type">' + escapeHtml((v.venue_type || '').toUpperCase()) + '</span>' +
          '<span class="ce-eb-venue-card__rent">$' + v.rental_cost_per_seat + '/seat</span>' +
        '</div>' +
      '</div>';
    }).join('') + '</div>';
  }

  // F3 — Quick Pick recommendation engine. Returns the venue_id that
  // best matches the player's promo size_tier:
  //   'major' → largest available arena (cap >= 15k)
  //   'mid'   → mid-size ballroom (5k-15k, highest cap in that band)
  //   'small' → smallest venue (cheapest rental, fits a small promo)
  // Ties broken by best capacity/cost ratio (most seats per dollar).
  // Returns null if no venues match.
  function pickRecommendedVenue() {
    if (!state.venues.length) return null;
    var p = state.promo || {};
    var sizeTier = p.size_tier || 'small';
    var pool = state.venues.slice();
    // P-FIX: exclude already-selected venue so Quick Pick suggests variety.
    if (state.selectedVenueId) {
      pool = pool.filter(function (v) { return v.venue_id !== state.selectedVenueId; });
      if (!pool.length) pool = state.venues.slice();  // fallback if only 1 venue
    }
    var candidate;
    if (sizeTier === 'major') {
      // Prefer arenas (15k+) — pick a RANDOM one from the top 5 (not always the same).
      var arenas = pool.filter(function (v) { return v.capacity >= 15000; })
        .sort(function (a, b) { return b.capacity - a.capacity; }).slice(0, 5);
      candidate = arenas[Math.floor(Math.random() * arenas.length)] || arenas[0];
    } else if (sizeTier === 'mid') {
      // Mid-size (5k-15k) — pick a RANDOM one from the top 5.
      var mids = pool.filter(function (v) {
        return v.capacity >= 5000 && v.capacity < 15000;
      }).sort(function (a, b) { return b.capacity - a.capacity; }).slice(0, 5);
      candidate = mids[Math.floor(Math.random() * mids.length)] || mids[0];
    }
    if (!candidate) {
      // Fallback for 'small' (or major/mid with no matching venue):
      // pick a RANDOM small venue (not always the same one).
      var smalls = pool.slice().sort(function (a, b) {
        return a.capacity - b.capacity;
      }).slice(0, 5);
      candidate = smalls[Math.floor(Math.random() * smalls.length)] || smalls[0];
    }
    return candidate || null;
  }

  // F3 — Quick Pick button. Auto-selects the recommended venue +
  // sets default levers + fires the preview + shows a toast.
  function doQuickPick() {
    var venue = pickRecommendedVenue();
    if (!venue) {
      showToast('No venues available — try expanding your market reach.', 'error');
      return;
    }
    // Set state — defaults per F3 spec.
    state.selectedVenueId = venue.venue_id;
    state.selectedVenue = venue;
    state.ticketPrice = 80;
    state.marketingSpend = 50000;
    state.ppvPrice = 60;
    state.isPpv = !!(state.promo && state.promo.can_run_ppv);
    // Re-render the venue grid (selected state) + levers (in case PPV
    // toggle changed). Then fire the preview immediately.
    // P2.2 — also re-render the filters so the new venue's country/
    // region are visible (in case the player had filters set that
    // excluded the recommended venue).
    state.venueFilter = 'all';
    state.countryFilter = 0;
    state.regionFilter = 0;
    var gridHost = document.querySelector('.ce-eb-venue-grid');
    if (gridHost) gridHost.outerHTML = renderVenueGrid();
    var filterHost = document.querySelector('.ce-eb-venue-filters');
    if (filterHost) filterHost.outerHTML = renderVenueFilters();
    wireVenueCards();
    wireVenueFilterChips();
    var leversHost = document.querySelector('.ce-eb-levers');
    if (leversHost) leversHost.outerHTML = renderLevers();
    wireLevers();
    updateCtaSummary();
    fetchPreview();
    showToast('⚡ Quick pick: ' + venue.name + ' — best value for your promo', 'success');
  }

  // ============================================================
  // RENDER — NAME YOUR EVENT (P2.1)
  // Text input pre-filled with the auto-generated default name from
  // the backend ("<Promo Name> <Next Number>"). The player can override
  // it; create_event sends the final value to the server.
  // ============================================================
  function renderEventName() {
    var val = state.eventName || state.defaultEventName || '';
    return '<div class="ce-eb-event-name">' +
      '<label class="ce-eb-event-name__label" for="ce-eb-event-name-input">EVENT NAME</label>' +
      '<input type="text" id="ce-eb-event-name-input" class="ce-eb-event-name__input" value="' +
        escapeHtml(val) + '" maxlength="80" placeholder="Name your card…" />' +
      '<div class="ce-eb-event-name__hint">Auto-named from your promo + event number. Edit if you want to make it your own.</div>' +
    '</div>';
  }

  // ============================================================
  // RENDER — LEVERS (THE BUSINESS END — renamed per P2.3)
  // ============================================================
  // Each slider gets a gradient track + value bubble + min/max labels.
  // "good" levers (ticket price, ppv price) use red→yellow→green
  // (low end = caution, high end = reward).
  // "bad" levers (marketing spend) use green→yellow→red (low = safe,
  // high = overspend).
  function renderSlider(opts) {
    // opts: { id, label, min, max, step, value, format, kind, hint }
    // kind: 'good' | 'bad' — drives the gradient direction.
    var valDisplay = opts.format(opts.value);
    var gradClass = opts.kind === 'bad'
      ? ' ce-eb-slider--bad'
      : ' ce-eb-slider--good';
    // Compute the % position for the value bubble. Clamped 0-100.
    var pct = 0;
    if (opts.max > opts.min) {
      pct = Math.max(0, Math.min(100,
        ((opts.value - opts.min) / (opts.max - opts.min)) * 100));
    }
    return '' +
      '<div class="ce-eb-lever">' +
        '<div class="ce-eb-lever__header">' +
          '<span class="ce-eb-lever__label">' + escapeHtml(opts.label) + '</span>' +
          '<span class="ce-eb-lever__value" id="' + opts.id + '-val">' + escapeHtml(valDisplay) + '</span>' +
        '</div>' +
        '<div class="ce-eb-slider-wrap' + gradClass + '">' +
          '<div class="ce-eb-slider-bubble" id="' + opts.id + '-bubble" style="left:' + pct + '%">' + escapeHtml(valDisplay) + '</div>' +
          '<input type="range" id="' + opts.id + '" min="' + opts.min + '" max="' + opts.max + '" step="' + opts.step + '" value="' + opts.value + '" aria-label="' + escapeHtml(opts.label) + '" />' +
        '</div>' +
        '<div class="ce-eb-slider-axis">' +
          '<span class="ce-eb-slider-axis__min">' + escapeHtml(opts.format(opts.min)) + '</span>' +
          '<span class="ce-eb-slider-axis__max">' + escapeHtml(opts.format(opts.max)) + '</span>' +
        '</div>' +
        '<div class="ce-eb-lever__hint">' + escapeHtml(opts.hint || '') + '</div>' +
      '</div>';
  }

  function renderLevers() {
    var p = state.promo;
    var canPpv = p && p.can_run_ppv;
    var ppvDisabled = !canPpv;
    var ppvHint = canPpv
      ? 'Only available on PPV-tier broadcasts (ppv_global / ppv_streaming).'
      : 'Your broadcast tier doesn\'t support PPV. Upgrade your broadcast deal first.';
    var ppvRowClass = canPpv ? '' : ' ce-eb-toggle--disabled';

    // F3 — sliders using the gradient-track + bubble renderer.
    //   Ticket price = "good" lever (red→yellow→green as price rises;
    //   but note higher price = lower fill rate, so the gradient is
    //   a *direction* hint, not a "always go right" hint).
    //   Marketing spend = "bad" lever (green at $0, red at $500K —
    //   overspending is a real risk).
    //   PPV price = "good" lever.
    var ticketSlider = renderSlider({
      id: 'ce-eb-ticket', label: 'Ticket Price',
      min: 20, max: 300, step: 5, value: state.ticketPrice,
      format: function (v) { return '$' + Number(v); },
      kind: 'good',
      hint: 'Higher price = more revenue/head but lower fill rate.',
    });
    var mktSlider = renderSlider({
      id: 'ce-eb-mkt', label: 'Marketing Spend',
      min: 0, max: 500000, step: 10000, value: state.marketingSpend,
      format: function (v) { return fmtCash(v); },
      kind: 'bad',
      hint: 'Boosts fill rate + PPV buys. Caps at +30% fill, 2× PPV.',
    });
    var ppvSlider = state.isPpv ? renderSlider({
      id: 'ce-eb-ppv', label: 'PPV Price',
      min: 30, max: 80, step: 5, value: state.ppvPrice,
      format: function (v) { return '$' + Number(v); },
      kind: 'good',
      hint: 'Higher price = more revenue/buy but fewer buys.',
    }) : '';

    return '' +
      '<div class="ce-eb-levers">' +
        ticketSlider +
        mktSlider +
        // is_ppv toggle (kept as-is — toggle, not slider)
        '<div class="ce-eb-lever ce-eb-lever--toggle">' +
          '<span class="ce-eb-lever__label">PPV Event</span>' +
          '<div class="ce-eb-toggle' + (state.isPpv ? ' ce-eb-toggle--on' : '') + ppvRowClass + '" id="ce-eb-ppv-toggle" role="switch" aria-checked="' + (state.isPpv ? 'true' : 'false') + '" tabindex="' + (canPpv ? '0' : '-1') + '">' +
            '<div class="ce-eb-toggle__thumb"></div>' +
          '</div>' +
          '<div class="ce-eb-lever__hint">' + escapeHtml(ppvHint) + '</div>' +
        '</div>' +
        ppvSlider +
      '</div>';
  }

  // ============================================================
  // RENDER — DATE PICKER (MM2 §2.3)
  // Adds a "PICK YOUR DATE" section between PICK YOUR VENUE and
  // SET YOUR LEVERS. Default = sim_date + 30 days (per WMMA5's
  // 1-month minimum, more lenient than the engine's 14-day floor
  // for faster early-game pace). Validates ≥ 14 days from sim date
  // + shows conflict warnings (rival ±2 days, own ±7 days).
  // Voice: "Clear date" / "Counter-programming risk" / "Short
  // turnaround".
  // ============================================================
  function renderDatePicker() {
    var dateVal = state.eventDate || '';
    var minDate = '';  // min attribute for the date input
    if (state.simDate) {
      // Earliest pickable = sim_date + min_lead_days (14 days).
      var parts = state.simDate.split('-');
      if (parts.length === 3) {
        var dt = new Date(parseInt(parts[0], 10),
                           parseInt(parts[1], 10) - 1,
                           parseInt(parts[2], 10));
        dt.setDate(dt.getDate() + state.minLeadDays);
        minDate = dt.getFullYear() + '-' +
          String(dt.getMonth() + 1).padStart(2, '0') + '-' +
          String(dt.getDate()).padStart(2, '0');
      }
    }

    // Voice + conflict warning block.
    var voiceHtml = '';
    var conflicts = state.dateConflicts;
    if (conflicts && conflicts.ok) {
      var voice = conflicts.voice || 'Clear date';
      var voiceClass = 'ce-eb-date-voice--clear';
      if (voice === 'Counter-programming risk') voiceClass = 'ce-eb-date-voice--danger';
      else if (voice === 'Short turnaround') voiceClass = 'ce-eb-date-voice--warning';
      voiceHtml = '<div class="ce-eb-date-voice ' + voiceClass + '">' +
        escapeHtml(voice) + '</div>';
      // Conflict lines.
      if (conflicts.conflicts && conflicts.conflicts.length) {
        var lines = conflicts.conflicts.map(function (c) {
          var lineClass = 'ce-eb-date-conflict-line';
          if (c.kind === 'rival') lineClass += ' ce-eb-date-conflict-line--rival';
          else if (c.kind === 'own') lineClass += ' ce-eb-date-conflict-line--own';
          return '<div class="' + lineClass + '">' +
            '<span class="ce-eb-date-conflict-icon">⚠</span>' +
            '<span>' + escapeHtml(c.phrase) + '</span>' +
          '</div>';
        }).join('');
        voiceHtml += '<div class="ce-eb-date-conflicts">' + lines + '</div>';
      } else if (conflicts.is_eligible) {
        voiceHtml += '<div class="ce-eb-date-conflicts">' +
          '<div class="ce-eb-date-conflict-line ce-eb-date-conflict-line--clear">' +
            '<span class="ce-eb-date-conflict-icon">✓</span>' +
            '<span>No rival shows within ±2 days. Clean runway.</span>' +
          '</div></div>';
      }
      // Ineligible warnings.
      if (conflicts.is_past) {
        voiceHtml += '<div class="ce-eb-date-conflicts">' +
          '<div class="ce-eb-date-conflict-line ce-eb-date-conflict-line--danger">' +
            '<span class="ce-eb-date-conflict-icon">✕</span>' +
            '<span>That date is in the past. Pick a future date.</span>' +
          '</div></div>';
      } else if (conflicts.min_lead_time_blocked) {
        voiceHtml += '<div class="ce-eb-date-conflicts">' +
          '<div class="ce-eb-date-conflict-line ce-eb-date-conflict-line--danger">' +
            '<span class="ce-eb-date-conflict-icon">✕</span>' +
            '<span>Too soon — fighters need at least ' + state.minLeadDays + ' days to prepare. Pick a later date.</span>' +
          '</div></div>';
      }
    } else if (state.eventDate) {
      voiceHtml = '<div class="ce-eb-date-voice ce-eb-date-voice--loading">Checking conflicts…</div>';
    }

    return '' +
      '<div class="ce-eb-date-picker">' +
        '<div class="ce-eb-date-row">' +
          '<label class="ce-eb-date-label" for="ce-eb-date">EVENT DATE</label>' +
          '<input type="date" id="ce-eb-date" class="ce-eb-date-input" value="' +
            escapeHtml(dateVal) + '"' +
            (minDate ? ' min="' + minDate + '"' : '') +
            ' />' +
          '<button class="ce-btn ce-btn-ghost ce-eb-date-calendar" id="ce-eb-date-calendar" type="button" title="Open the Calendar">📅 Calendar</button>' +
        '</div>' +
        '<div class="ce-eb-date-hint">' +
          'Default: sim date + 30 days. Minimum lead: ' + state.minLeadDays + ' days.' +
          (state.simDate ? ' Sim date: <strong>' + escapeHtml(state.simDate) + '</strong>.' : '') +
        '</div>' +
        voiceHtml +
      '</div>';
  }

  // ============================================================
  // RENDER — PROJECTED OUTCOME (F3: visual hierarchy)
  // Phase F1.3 — preview shows a RANGE (low - high), not a single
  // number. Show quality is unknown pre-event, so revenue varies
  // ±30% based on how the fights actually go. Expenses are known
  // precisely (those line items stay single-number). The NET banner
  // now shows "PROJECTED NET" as a range + voice phrase.
  // ============================================================
  function renderPreview() {
    if (!state.selectedVenueId) {
      return '<div class="ce-eb-preview"><div class="ce-eb-preview__empty">Pick a venue to see your projected outcome.</div></div>';
    }
    var p = state.lastPreview;
    if (!p || !p.ok) {
      return '<div class="ce-eb-preview"><div class="ce-eb-preview__loading">Calculating…</div></div>';
    }
    var netClass = 'ce-eb-net-banner--' + (p.voice_kind || 'safe');
    var phraseClass = ' ce-eb-net-banner__phrase--' + (p.voice_kind || 'safe');
    // Phase F1.3 — range display. The range reflects show-quality
    // variance (worst-case dud -20% → best-case blockbuster +30%).
    // The midpoint cash_after (legacy single number) is retained for
    // the war-chest-after hint — the range endpoints are too wide
    // to anchor the "what's left in the bank" question.
    var cashAfterMid = p.cash_after_event != null ? p.cash_after_event : 0;
    var cashAfterDisplay = p.cash_after_display || fmtCash(cashAfterMid);

    // Range strings — fall back to the legacy single-number if the
    // backend hasn't returned the range fields (defensive).
    var revRangeStr = p.revenue_range_display ||
      (fmtCash(p.total_revenue) + ' - ' + fmtCash(p.total_revenue));
    var netRangeStr = p.net_range_display ||
      (fmtCash(p.net_profit) + ' - ' + fmtCash(p.net_profit));

    var ppvBlock = '';
    if (state.isPpv) {
      ppvBlock =
        '<div class="ce-eb-preview__row ce-eb-preview__row--sub"><span>PPV Buys (projected)</span><span>' + (p.ppv_buys || 0).toLocaleString() + '</span></div>' +
        '<div class="ce-eb-preview__row ce-eb-preview__row--sub"><span>PPV Revenue (your split)</span><span>' + escapeHtml(fmtCash(p.ppv_revenue)) + '</span></div>';
    }

    return '' +
      '<div class="ce-eb-preview">' +
        // Phase F1.3 — show-quality variance hint above the columns.
        '<div class="ce-eb-preview__variance-hint">' +
          '<span class="ce-eb-preview__variance-icon">📊</span>' +
          '<span class="ce-eb-preview__variance-text">' +
            'Show quality is unknown pre-event — revenue varies ±30% based on how the fights land. ' +
            'A blockbuster card earns the high end; a dud falls to the low end.' +
          '</span>' +
        '</div>' +
        '<div class="ce-eb-preview__cols">' +
          // Revenue column
          '<div>' +
            '<div class="ce-eb-preview__col-title ce-eb-preview__col-title--revenue">Revenue</div>' +
            '<div class="ce-eb-preview__row"><span>Attendance</span><span>' + (p.attendance || 0).toLocaleString() + ' / ' + (state.selectedVenue ? state.selectedVenue.capacity.toLocaleString() : '—') + '</span></div>' +
            '<div class="ce-eb-preview__row ce-eb-preview__row--sub"><span>Fill Rate</span><span>' + (((p.fill_rate || 0) * 100).toFixed(0)) + '%</span></div>' +
            '<div class="ce-eb-preview__row"><span>Gate Receipts</span><span>' + escapeHtml(fmtCash(p.gate)) + '</span></div>' +
            '<div class="ce-eb-preview__row"><span>Broadcast</span><span>' + escapeHtml(fmtCash(p.broadcast_revenue)) + '</span></div>' +
            ppvBlock +
            '<div class="ce-eb-preview__row"><span>Sponsorship</span><span>' + escapeHtml(fmtCash(p.sponsorship)) + '</span></div>' +
            '<div class="ce-eb-preview__row"><span>Merchandise</span><span>' + escapeHtml(fmtCash(p.merch)) + '</span></div>' +
            '<div class="ce-eb-preview__row"><span>Concessions</span><span>' + escapeHtml(fmtCash(p.concessions)) + '</span></div>' +
            '<div class="ce-eb-preview__row ce-eb-preview__row--total"><span>Total Revenue (mid)</span><span>' + escapeHtml(fmtCash(p.total_revenue)) + '</span></div>' +
          '</div>' +
          // Expense column
          '<div>' +
            '<div class="ce-eb-preview__col-title ce-eb-preview__col-title--expense">Expenses</div>' +
            '<div class="ce-eb-preview__row"><span>Fighter Purses (est.)</span><span>' + escapeHtml(fmtCash(p.fighter_purses)) + '</span></div>' +
            '<div class="ce-eb-preview__row"><span>Staff Salary</span><span>' + escapeHtml(fmtCash(p.staff_salary)) + '</span></div>' +
            '<div class="ce-eb-preview__row"><span>Venue Rental</span><span>' + escapeHtml(fmtCash(p.venue_rental)) + '</span></div>' +
            '<div class="ce-eb-preview__row"><span>Marketing Spend</span><span>' + escapeHtml(fmtCash(p.marketing_expense)) + '</span></div>' +
            '<div class="ce-eb-preview__row"><span>Insurance + Medical</span><span>' + escapeHtml(fmtCash(p.insurance_medical)) + '</span></div>' +
            '<div class="ce-eb-preview__row ce-eb-preview__row--total"><span>Total Expenses</span><span>' + escapeHtml(fmtCash(p.total_expenses)) + '</span></div>' +
          '</div>' +
        '</div>' +
        // F3: net profit banner with color-coded gradient background +
        // voice phrase + cash-after-event projection.
        // Phase F1.3 — banner now shows the RANGE ("$X.XM - $Y.YM")
        // instead of a single number. The midpoint cash-after stays
        // single-number (the war-chest-after question is a real
        // number, not a range — expenses are known, only revenue varies).
        '<div class="ce-eb-net-banner ' + netClass + '">' +
          '<div class="ce-eb-net-banner__row">' +
            '<div class="ce-eb-net-banner__cell">' +
              '<div class="ce-eb-net-banner__label">PROJECTED REVENUE</div>' +
              '<div class="ce-eb-net-banner__value ce-eb-net-banner__value--range">' + escapeHtml(revRangeStr) + '</div>' +
            '</div>' +
            '<div class="ce-eb-net-banner__cell ce-eb-net-banner__cell--right">' +
              '<div class="ce-eb-net-banner__label">YOUR WAR CHEST AFTER THIS CARD</div>' +
              '<div class="ce-eb-net-banner__cash-after">' + escapeHtml(cashAfterDisplay) + '</div>' +
            '</div>' +
          '</div>' +
          '<div class="ce-eb-net-banner__row ce-eb-net-banner__row--net">' +
            '<div class="ce-eb-net-banner__cell">' +
              '<div class="ce-eb-net-banner__label">PROJECTED NET</div>' +
              '<div class="ce-eb-net-banner__value ce-eb-net-banner__value--range">' + escapeHtml(netRangeStr) + '</div>' +
            '</div>' +
          '</div>' +
          '<div class="ce-eb-net-banner__phrase' + phraseClass + '">' + escapeHtml(p.voice_phrase || '') + '</div>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — STICKY CTA BAR
  // ============================================================
  function renderCta() {
    var venueName = state.selectedVenue ? state.selectedVenue.name : '—';
    // Phase F1.3 — show the net RANGE in the CTA bar (low - high).
    var netStr = '—';
    if (state.lastPreview && state.lastPreview.ok) {
      if (state.lastPreview.net_range_display) {
        netStr = state.lastPreview.net_range_display;
      } else if (state.lastPreview.net_profit != null) {
        netStr = fmtCash(state.lastPreview.net_profit);
      }
    }
    var dateStr = state.eventDate || '—';
    // P2.1 — show the event name in the CTA summary so the player can
    // verify their chosen name before scheduling.
    var eventName = (state.eventName || state.defaultEventName || '').trim() || 'Untitled';
    // Schedule button enabled only when venue + date are valid + date is eligible.
    var dateOk = !!(state.eventDate && state.dateConflicts && state.dateConflicts.ok && state.dateConflicts.is_eligible);
    var canSchedule = !!state.selectedVenueId && dateOk;
    return '' +
      '<div class="ce-eb-cta">' +
        '<div class="ce-eb-cta__summary">' +
          '<strong>' + escapeHtml(eventName) + '</strong> · ' +
          escapeHtml(venueName) + ' · ' +
          'Date <strong>' + escapeHtml(dateStr) + '</strong> · ' +
          'Ticket <strong>$' + state.ticketPrice + '</strong> · ' +
          'Marketing <strong>' + escapeHtml(fmtCash(state.marketingSpend)) + '</strong>' +
          (state.isPpv ? ' · PPV <strong>$' + state.ppvPrice + '</strong>' : '') +
          ' · Projected Net <strong>' + escapeHtml(netStr) + '</strong>' +
        '</div>' +
        '<button class="ce-btn ce-btn-primary" id="ce-eb-schedule" type="button"' +
          (canSchedule ? '' : ' disabled') + '>Stack This Card</button>' +
      '</div>';
  }

  // ============================================================
  // MAIN RENDER
  // ============================================================
  function render() {
    var host = document.getElementById('screen-content');
    if (!host) return;
    if (!state.promo) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Loading your war chest…</div></div>';
      return;
    }
    var html = '' +
      '<div class="ce-eb">' +
        // 1. STACK A CARD (F3: section header icon 🎫)
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">🎫</span>' +
            '<span class="ce-sec-title ce-sec-title-gold">STACK A CARD</span>' +
            '<span class="ce-sec-sub ce-mono">your next event</span>' +
          '</div>' +
          renderPromoStrip() +
        '</div>' +
        // 2. NAME YOUR EVENT (P2.1 — moved to the top of the build flow
        //    per docs/COMPREHENSIVE_FIX_PLAN.md §Group B #5).
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">📛</span>' +
            '<span class="ce-sec-title">NAME YOUR EVENT</span>' +
            '<span class="ce-sec-sub ce-mono">give the card a name</span>' +
          '</div>' +
          renderEventName() +
        '</div>' +
        // 3. PICK YOUR DATE (P2.1 — moved ABOVE PICK YOUR VENUE per the
        //    reorder spec: Name → Date → Venue → Business End).
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">📅</span>' +
            '<span class="ce-sec-title">PICK YOUR DATE</span>' +
            '<span class="ce-sec-sub ce-mono">when the cage door closes</span>' +
          '</div>' +
          renderDatePicker() +
        '</div>' +
        // 4. PICK YOUR VENUE (F3: section header icon 🏟 + Quick Pick)
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">🏟</span>' +
            '<span class="ce-sec-title">PICK YOUR VENUE</span>' +
            '<span class="ce-sec-sub ce-mono">' + state.venues.length + ' venues available</span>' +
            '<button class="ce-btn ce-btn-ghost ce-eb-quickpick" id="ce-eb-quickpick" type="button">⚡ Quick Pick</button>' +
          '</div>' +
          renderVenueFilters() +
          renderVenueGrid() +
        '</div>' +
        // 5. THE BUSINESS END (P2.3 — renamed from "Set Your Levers".
        //    Cage Empire promoter register: this is where the money
        //    decisions happen — ticket price, marketing spend, PPV.)
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">💼</span>' +
            '<span class="ce-sec-title">THE BUSINESS END</span>' +
            '<span class="ce-sec-sub ce-mono">ticket · marketing · ppv</span>' +
          '</div>' +
          renderLevers() +
        '</div>' +
        // 6. PROJECTED OUTCOME (F3: section header icon 📊)
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">📊</span>' +
            '<span class="ce-sec-title">PROJECTED OUTCOME</span>' +
            '<span class="ce-sec-sub ce-mono">live preview</span>' +
          '</div>' +
          renderPreview() +
        '</div>' +
      '</div>' +
      renderCta();
    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // LIVE PREVIEW — debounced fetch
  // ============================================================
  function schedulePreview() {
    if (state._previewTimer) clearTimeout(state._previewTimer);
    state._previewTimer = setTimeout(fetchPreview, 200);
  }

  function fetchPreview() {
    if (!state.selectedVenueId) {
      state.lastPreview = null;
      // Just re-render the preview + CTA.
      var prevHost0 = document.querySelector('.ce-eb-preview');
      if (prevHost0) prevHost0.outerHTML = '<div class="ce-eb-preview"><div class="ce-eb-preview__empty">Pick a venue to see your projected outcome.</div></div>';
      updateCtaSummary();
      return;
    }
    if (state._previewInFlight) return;
    state._previewInFlight = true;
    var params = {
      venue_id: state.selectedVenueId,
      ticket_price: state.ticketPrice,
      marketing_spend: state.marketingSpend,
      ppv_price: state.ppvPrice,
      is_ppv: state.isPpv ? 1 : 0,
    };
    window.CE.bridge.getEventPreview(params).then(function (result) {
      state.lastPreview = result;
      // Re-render just the preview block + the CTA bar.
      var prevHost = document.querySelector('.ce-eb-preview');
      if (prevHost) {
        var wrap = document.createElement('div');
        wrap.innerHTML = renderPreview();
        if (wrap.firstChild) prevHost.replaceWith(wrap.firstChild);
      } else {
        // Fallback: preview host not found — re-render the whole screen.
        render();
      }
      updateCtaSummary();
    }).catch(function (err) {
      console.error('[eventBuilder] preview failed:', err);
      // Show error in preview area
      var prevHost = document.querySelector('.ce-eb-preview');
      if (prevHost) {
        prevHost.innerHTML = '<div class="ce-eb-preview__empty">Preview error: ' + escapeHtml(String(err.message || err)) + '</div>';
      }
    }).then(function () {
      state._previewInFlight = false;
    });
  }

  function updateCtaSummary() {
    // Update only the CTA summary text + button state without
    // re-rendering the whole bar (preserves the button's click handler).
    var bar = document.querySelector('.ce-eb-cta__summary');
    if (!bar) return;
    var venueName = state.selectedVenue ? state.selectedVenue.name : '—';
    // Phase F1.3 — show the net RANGE in the CTA bar (low - high)
    // instead of the single midpoint number. Falls back to legacy
    // single-number display if the backend didn't return range fields.
    var netStr = '—';
    if (state.lastPreview && state.lastPreview.ok) {
      if (state.lastPreview.net_range_display) {
        netStr = state.lastPreview.net_range_display;
      } else if (state.lastPreview.net_profit != null) {
        netStr = fmtCash(state.lastPreview.net_profit);
      }
    }
    var dateStr = state.eventDate || '—';
    // P2.1 — include the event name (player-typed or auto-default).
    var eventName = (state.eventName || state.defaultEventName || '').trim() || 'Untitled';
    bar.innerHTML =
      '<strong>' + escapeHtml(eventName) + '</strong> · ' +
      escapeHtml(venueName) + ' · ' +
      'Date <strong>' + escapeHtml(dateStr) + '</strong> · ' +
      'Ticket <strong>$' + state.ticketPrice + '</strong> · ' +
      'Marketing <strong>' + escapeHtml(fmtCash(state.marketingSpend)) + '</strong>' +
      (state.isPpv ? ' · PPV <strong>$' + state.ppvPrice + '</strong>' : '') +
      ' · Projected Net <strong>' + escapeHtml(netStr) + '</strong>';
    var btn = document.getElementById('ce-eb-schedule');
    if (btn) {
      // MM2 §2.3 — schedule button enabled only when venue selected +
      // date eligible (future + ≥ min_lead_days).
      var dateOk = !!(state.eventDate && state.dateConflicts &&
                      state.dateConflicts.ok && state.dateConflicts.is_eligible);
      btn.disabled = !(state.selectedVenueId && dateOk);
    }
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  // F3 — slider bubble updater. Reads the slider's current value,
  // recomputes the % position, and moves the bubble + updates its
  // label. Called on every 'input' event.
  function updateSliderBubble(sliderId, formatter) {
    var slider = document.getElementById(sliderId);
    if (!slider) return;
    var bubble = document.getElementById(sliderId + '-bubble');
    var valEl = document.getElementById(sliderId + '-val');
    var value = Number(slider.value);
    var min = Number(slider.min);
    var max = Number(slider.max);
    var pct = max > min
      ? ((value - min) / (max - min)) * 100
      : 0;
    pct = Math.max(0, Math.min(100, pct));
    var display = formatter ? formatter(value) : String(value);
    if (bubble) {
      bubble.style.left = pct + '%';
      bubble.textContent = display;
    }
    if (valEl) valEl.textContent = display;
  }

  function wireSlider(sliderId, formatter, onChange) {
    var slider = document.getElementById(sliderId);
    if (!slider) return;
    slider.addEventListener('input', function () {
      updateSliderBubble(sliderId, formatter);
      if (onChange) onChange(Number(slider.value));
    });
    // Set initial bubble position on render.
    updateSliderBubble(sliderId, formatter);
  }

  function wireVenueFilterChips() {
    document.querySelectorAll('[data-venue-filter]').forEach(function (chip) {
      chip.addEventListener('click', function () {
        state.venueFilter = chip.getAttribute('data-venue-filter');
        var gridHost = document.querySelector('.ce-eb-venue-grid');
        var filterHost = document.querySelector('.ce-eb-venue-filters');
        if (filterHost) filterHost.outerHTML = renderVenueFilters();
        if (gridHost) gridHost.outerHTML = renderVenueGrid();
        wireVenueCards();
        wireVenueFilterChips();
      });
      chip.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault();
          chip.click();
        }
      });
    });

    // P2.2 — wire the country + region dropdowns. When the country
    // changes, the region dropdown re-renders to only show regions in
    // the selected country (and the region filter resets if the
    // previously-selected region isn't in the new country). When the
    // region changes, only the grid re-renders.
    var countrySel = document.getElementById('ce-eb-country-filter');
    if (countrySel) {
      countrySel.addEventListener('change', function () {
        state.countryFilter = parseInt(countrySel.value, 10) || 0;
        // Reset region filter if it's no longer valid for this country.
        if (state.regionFilter) {
          var stillValid = state.regions.some(function (r) {
            return r.id === state.regionFilter &&
              (state.countryFilter === 0 || r.country_id === state.countryFilter);
          });
          if (!stillValid) state.regionFilter = 0;
        }
        var filterHost = document.querySelector('.ce-eb-venue-filters');
        var gridHost = document.querySelector('.ce-eb-venue-grid');
        if (filterHost) filterHost.outerHTML = renderVenueFilters();
        if (gridHost) gridHost.outerHTML = renderVenueGrid();
        wireVenueCards();
        wireVenueFilterChips();
      });
    }
    var regionSel = document.getElementById('ce-eb-region-filter');
    if (regionSel) {
      regionSel.addEventListener('change', function () {
        state.regionFilter = parseInt(regionSel.value, 10) || 0;
        var gridHost = document.querySelector('.ce-eb-venue-grid');
        if (gridHost) gridHost.outerHTML = renderVenueGrid();
        wireVenueCards();
      });
    }
  }

  // P2.1 — wire the event-name input. Updates state.eventName on input
  // (no preview fetch — name doesn't affect finance projections) + the
  // CTA summary so the player sees the name live.
  function wireEventName() {
    var input = document.getElementById('ce-eb-event-name-input');
    if (!input) return;
    input.addEventListener('input', function () {
      state.eventName = input.value || '';
      updateCtaSummary();
    });
  }

  function wireEvents() {
    wireVenueFilterChips();
    wireVenueCards();
    wireDatePicker();
    wireEventName();

    // F3 — Quick Pick button
    var quickBtn = document.getElementById('ce-eb-quickpick');
    if (quickBtn) quickBtn.addEventListener('click', doQuickPick);

    // F3 — sliders (bubble updates on input + schedulePreview).
    wireLevers();

    // Schedule button — Phase M4: navigates to Matchmaking after
    // creating the event (instead of the dashboard), so the player
    // can immediately start stacking the card. Per docs/MASTER_PLAN_
    // MATCHMAKING.md §1.2 — the 3-screen flow: Stack a Card →
    // Matchmaking → Fight Night (future).
    //
    // MM2 §2.3: now passes event_date from the date picker (was
    // previously omitted → defaulted to +14 days server-side).
    // P2.1: also passes event_name from the NAME YOUR EVENT input.
    var scheduleBtn = document.getElementById('ce-eb-schedule');
    if (scheduleBtn) {
      scheduleBtn.addEventListener('click', function () {
        if (!state.selectedVenueId) return;
        // Date eligibility check (defensive — button should already
        // be disabled when ineligible).
        if (!state.eventDate) {
          showToast('Pick a date first.', 'error');
          return;
        }
        if (state.dateConflicts && state.dateConflicts.ok &&
            !state.dateConflicts.is_eligible) {
          showToast('That date is not eligible — pick a future date at least ' +
            state.minLeadDays + ' days out.', 'error');
          return;
        }
        scheduleBtn.disabled = true;
        scheduleBtn.textContent = 'Stacking…';
        // P2.1 — final event name = player-typed value OR auto-default.
        var finalName = (state.eventName || state.defaultEventName || '').trim();
        var params = {
          venue_id: state.selectedVenueId,
          event_date: state.eventDate,
          event_name: finalName,
          ticket_price: state.ticketPrice,
          marketing_spend: state.marketingSpend,
          ppv_price: state.ppvPrice,
          is_ppv: state.isPpv ? 1 : 0,
        };
        window.CE.bridge.createEvent(params).then(function (result) {
          if (result && result.ok) {
            showToast('Card stacked: ' + (result.event_name || '') + ' on ' + (result.event_date || '') + '. Now book the fights.', 'success');
            setTimeout(function () {
              // Phase M4: navigate to the Matchmaking screen with the
              // new event_id (instead of the dashboard).
              window.CE.app.navigate('matchmaking', { event_id: result.event_id });
            }, 1000);
          } else {
            showToast('Stack failed: ' + (result && result.error ? result.error : 'unknown'), 'error');
            scheduleBtn.disabled = false;
            scheduleBtn.textContent = 'Stack This Card';
          }
        }).catch(function (err) {
          showToast('Stack failed: ' + err, 'error');
          scheduleBtn.disabled = false;
          scheduleBtn.textContent = 'Stack This Card';
        });
      });
    }
  }

  // Re-wire just the venue cards (after filter change).
  function wireVenueCards() {
    document.querySelectorAll('.ce-eb-venue-card').forEach(function (card) {
      card.addEventListener('click', function () {
        var vid = parseInt(card.getAttribute('data-venue-id'), 10);
        selectVenue(vid);
      });
      card.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault();
          var vid = parseInt(card.getAttribute('data-venue-id'), 10);
          selectVenue(vid);
        }
      });
    });
  }

  // Re-wire just the levers (after PPV toggle re-renders levers block).
  function wireLevers() {
    // Ticket price slider — "good" lever.
    wireSlider('ce-eb-ticket',
      function (v) { return '$' + v; },
      function (v) {
        state.ticketPrice = v;
        schedulePreview();
      });
    // Marketing spend slider — "bad" lever.
    wireSlider('ce-eb-mkt',
      function (v) { return fmtCash(v); },
      function (v) {
        state.marketingSpend = v;
        schedulePreview();
      });
    // PPV price slider — "good" lever (only present when is_ppv on).
    wireSlider('ce-eb-ppv',
      function (v) { return '$' + v; },
      function (v) {
        state.ppvPrice = v;
        schedulePreview();
      });

    // PPV toggle
    var ppvToggle = document.getElementById('ce-eb-ppv-toggle');
    if (ppvToggle) {
      var togglePpv = function () {
        if (!state.promo || !state.promo.can_run_ppv) return;
        state.isPpv = !state.isPpv;
        var leversHost = document.querySelector('.ce-eb-levers');
        if (leversHost) leversHost.outerHTML = renderLevers();
        wireLevers();
        schedulePreview();
      };
      ppvToggle.addEventListener('click', togglePpv);
      ppvToggle.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault();
          togglePpv();
        }
      });
    }
  }

  // ============================================================
  // DATE PICKER WIRING (MM2 §2.3)
  // On change: validate the date, fetch conflict warnings, re-render
  // the picker section + update CTA. Debounced 250ms so rapid typing
  // doesn't spam the backend.
  // ============================================================
  function wireDatePicker() {
    var dateInput = document.getElementById('ce-eb-date');
    if (dateInput) {
      dateInput.addEventListener('change', function () {
        state.eventDate = dateInput.value || null;
        state.dateConflicts = null;
        // Re-render the picker (shows "Checking conflicts…") + disable
        // the CTA until the conflict check completes.
        var pickerHost = document.querySelector('.ce-eb-date-picker');
        if (pickerHost) pickerHost.outerHTML = renderDatePicker();
        wireDatePicker();
        updateCtaSummary();
        scheduleDateConflictsFetch();
      });
    }
    var calBtn = document.getElementById('ce-eb-date-calendar');
    if (calBtn) {
      calBtn.addEventListener('click', function () {
        // Navigate to the Calendar screen. The player can pick a date
        // there + click "Schedule Event on [Date]" to come back here
        // with the date pre-filled.
        window.CE.app.navigate('schedule');
      });
    }
  }

  function scheduleDateConflictsFetch() {
    if (state._dateConflictsTimer) clearTimeout(state._dateConflictsTimer);
    state._dateConflictsTimer = setTimeout(fetchDateConflicts, 200);
  }

  function fetchDateConflicts() {
    if (!state.eventDate) {
      state.dateConflicts = null;
      return;
    }
    if (state._dateConflictsInFlight) return;
    state._dateConflictsInFlight = true;
    window.CE.bridge.getDateConflicts(state.eventDate).then(function (result) {
      state.dateConflicts = result;
      // Re-render the picker section + CTA (button state may change).
      var pickerHost = document.querySelector('.ce-eb-date-picker');
      if (pickerHost) pickerHost.outerHTML = renderDatePicker();
      wireDatePicker();
      updateCtaSummary();
    }).catch(function (err) {
      console.error('[eventBuilder] date conflicts fetch failed:', err);
    }).then(function () {
      state._dateConflictsInFlight = false;
    });
  }

  function selectVenue(vid) {
    state.selectedVenueId = vid;
    state.selectedVenue = state.venues.find(function (v) { return v.venue_id === vid; }) || null;
    // Re-render the venue grid (to show the selected style).
    var gridHost = document.querySelector('.ce-eb-venue-grid');
    if (gridHost) gridHost.outerHTML = renderVenueGrid();
    wireVenueCards();
    updateCtaSummary();
    fetchPreview();
  }

  // ============================================================
  // TOAST
  // ============================================================
  function showToast(msg, kind) {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var existing = host.querySelector('.ce-eb-toast');
    if (existing) existing.remove();
    var toast = document.createElement('div');
    toast.className = 'ce-eb-toast ce-eb-toast--' + (kind || 'info');
    toast.textContent = msg;
    host.appendChild(toast);
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 4000);
  }

  // ============================================================
  // PUBLIC API
  // ============================================================
  // MM2 §2.3: loadAndRender now accepts an optional params arg with
  // event_date (pre-filled by the Calendar screen). If no event_date
  // is supplied, we default to sim_date + 30 days (WMMA5's 1-month
  // minimum, more lenient than the engine's 14-day floor for faster
  // early-game pace — see docs/RESEARCH_WMMA5_FM_V2.md §4 P4A).
  function loadAndRender(params) {
    params = params || {};
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Loading your war chest…</div></div>';
    }
    // Read navigation params (app.js → getActiveParams) so the calendar
    // can pre-fill the date.
    var navParams = {};
    try {
      if (window.CE.app && typeof window.CE.app.getActiveParams === 'function') {
        navParams = window.CE.app.getActiveParams() || {};
      }
    } catch (e) { /* ignore */ }
    var prefilledDate = params.event_date || navParams.event_date || null;

    return window.CE.bridge.getEventBuilderData().then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load event builder</div><div>' + escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      state.promo = data.promo || null;
      state.venues = data.venues || [];
      // P2.2 — countries + regions power the venue filter dropdowns.
      state.countries = data.countries || [];
      state.regions = data.regions || [];
      // P2.1 — auto-generated default event name. The JS pre-fills the
      // input with this; the player can override before scheduling.
      state.defaultEventName = data.default_event_name || '';
      state.eventName = state.defaultEventName;
      state.weightClasses = data.weight_classes || [];
      state.fightersByWc = data.fighters_by_wc || [];
      // Reset transient state in case the user navigates away + back.
      state.selectedVenueId = null;
      state.selectedVenue = null;
      state.lastPreview = null;
      // P2.2 — reset venue filters on entry (no carry-over from a
      // prior visit).
      state.venueFilter = 'all';
      state.countryFilter = 0;
      state.regionFilter = 0;
      // Default is_ppv to ON if the promo's broadcast tier is PPV-capable
      // (ppv_global / ppv_streaming). This matches Phase E2 behavior
      // (where ppv-tier promos always used the PPV formula) and avoids
      // the "player forgot to toggle PPV on their ppv_global show"
      // UX trap. Non-PPV promos default to off (the toggle is disabled
      // anyway via the can_run_ppv check).
      state.isPpv = !!(state.promo && state.promo.can_run_ppv);
      state.ticketPrice = 80;
      state.marketingSpend = 0;
      state.ppvPrice = 60;
      // MM2 §2.3 — set the default event_date.
      // 1. If the calendar pre-filled a date, use it.
      // 2. Otherwise default to sim_date + 30 days (need to fetch the
      //    sim clock first — getEventBuilderData doesn't return it).
      if (prefilledDate) {
        state.eventDate = prefilledDate;
      } else {
        state.eventDate = null; // set below after clock fetch
      }
      state.dateConflicts = null;
      // Fetch the clock so we know the sim date (for default date +
      // min-date attribute on the date input).
      var clockPromise = window.CE.bridge.getClock().then(function (clock) {
        if (clock && clock.current_date) {
          state.simDate = clock.current_date;
          if (!state.eventDate) {
            // Default: sim_date + 30 days.
            var parts = clock.current_date.split('-');
            if (parts.length === 3) {
              var dt = new Date(parseInt(parts[0], 10),
                                 parseInt(parts[1], 10) - 1,
                                 parseInt(parts[2], 10));
              dt.setDate(dt.getDate() + 30);
              state.eventDate = dt.getFullYear() + '-' +
                String(dt.getMonth() + 1).padStart(2, '0') + '-' +
                String(dt.getDate()).padStart(2, '0');
            }
          }
        }
      }).catch(function () { /* non-fatal */ });
      return clockPromise.then(function () {
        render();
        // Initial conflict fetch (debounced).
        if (state.eventDate) scheduleDateConflictsFetch();
      });
    }).catch(function (err) {
      console.error('[eventBuilder] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load event builder</div><div>' + escapeHtml(String(err)) + '</div></div>';
      }
    });
  }

  return {
    loadAndRender: loadAndRender,
    render: render,
  };
})();
