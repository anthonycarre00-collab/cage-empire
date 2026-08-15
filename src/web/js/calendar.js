/* ============================================================
   CAGE EMPIRE — Calendar Screen ("THE CALENDAR")
   ============================================================
   Phase MM2 (docs/MASTER_PLAN_MATCHMAKING_V2.md §2). Replaces the
   placeholder Schedule nav item. Renders a month-grid calendar
   showing player events (gold) + rival promo events (red) + today
   (blue) + past dates (greyed) + min-lead-time blocked dates
   (< 14 days, diagonal stripes) + conflict warning icons (⚠).

   Click any eligible date → detail panel shows events + conflicts
   + "Schedule Event on [Date]" button → navigates to Stack a Card
   with event_date pre-filled.

   Voice phrases: "Counter-programming risk" / "Short turnaround"
   / "Clear date". No raw potential/ceiling numbers.
   ============================================================ */

window.CE = window.CE || {};

window.CE.calendar = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    month: null,        // int 1-12
    year: null,         // int (full year)
    simDate: null,      // "YYYY-MM-DD" — current sim date
    minLeadDays: 14,
    playerPromoName: '',
    days: [],           // [{day, date, weekday, is_today, is_past, ...}]
    firstWeekday: 0,    // 0=Mon .. 6=Sun
    prevMonth: null,    // {month, year}
    nextMonth: null,    // {month, year}
    selectedDate: null, // "YYYY-MM-DD"
    loading: false,
  };

  // JS-side mirror of Python's calendar.monthrange — first weekday
  // (0=Mon) + days-in-month. Used only as a sanity check; the API
  // already returns first_weekday + n_days via days.length.
  var WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  var MONTH_NAMES = [
    '', 'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ];

  // ============================================================
  // HELPERS
  // ============================================================
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function formatDateLong(dateStr) {
    if (!dateStr) return '—';
    var parts = dateStr.split('-');
    if (parts.length !== 3) return dateStr;
    var y = parseInt(parts[0], 10);
    var m = parseInt(parts[1], 10);
    var d = parseInt(parts[2], 10);
    var dt = new Date(y, m - 1, d);
    var weekday = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][dt.getDay()];
    return weekday + ', ' + MONTH_NAMES[m] + ' ' + d + ', ' + y;
  }

  function voiceTier(day) {
    // Return {label, cssClass} based on conflict types.
    if (!day.has_conflict) {
      return { label: 'Clear date', cssClass: 'ce-cal__detail-voice--clear' };
    }
    var hasRival = (day.conflicts || []).some(function (c) {
      return c.indexOf('counter-programming') >= 0;
    });
    if (hasRival) {
      return { label: 'Counter-programming risk', cssClass: 'ce-cal__detail-voice--danger' };
    }
    return { label: 'Short turnaround', cssClass: 'ce-cal__detail-voice--warning' };
  }

  // ============================================================
  // RENDER — HEADER (month nav + legend)
  // ============================================================
  function renderHeader() {
    var monthLabel = (MONTH_NAMES[state.month] || '') + ' ' + state.year;
    return '' +
      '<div class="ce-cal__header">' +
        '<div class="ce-cal__month-nav">' +
          '<button class="ce-cal__nav-btn" id="ce-cal-prev" type="button" aria-label="Previous month">←</button>' +
          '<div class="ce-cal__month-label">' + escapeHtml(monthLabel) + '</div>' +
          '<button class="ce-cal__nav-btn" id="ce-cal-next" type="button" aria-label="Next month">→</button>' +
        '</div>' +
        '<button class="ce-cal__today-btn" id="ce-cal-today" type="button">Today</button>' +
        '<div class="ce-cal__legend">' +
          '<span class="ce-cal__legend-item"><span class="ce-cal__legend-swatch ce-cal__legend-swatch--player"></span>Your Events</span>' +
          '<span class="ce-cal__legend-item"><span class="ce-cal__legend-swatch ce-cal__legend-swatch--rival"></span>Rival Events</span>' +
          '<span class="ce-cal__legend-item"><span class="ce-cal__legend-swatch ce-cal__legend-swatch--today"></span>Today</span>' +
          '<span class="ce-cal__legend-item"><span class="ce-cal__legend-swatch ce-cal__legend-swatch--blocked"></span>Too Soon (&lt;14d)</span>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — SIM STRIP
  // ============================================================
  function renderSimStrip() {
    var sim = state.simDate || '—';
    return '' +
      '<div class="ce-cal__sim-strip">' +
        '<span>SIM DATE: <span class="ce-cal__sim-date">' + escapeHtml(sim) + '</span></span>' +
        '<span>·</span>' +
        '<span>MIN LEAD TIME: <span class="ce-cal__sim-lead">' + state.minLeadDays + ' DAYS</span></span>' +
        '<span>·</span>' +
        '<span><strong>' + escapeHtml(state.playerPromoName || 'Your Promotion') + '</strong></span>' +
      '</div>';
  }

  // ============================================================
  // RENDER — MONTH GRID
  // ============================================================
  function renderGrid() {
    if (!state.days || !state.days.length) {
      return '<div class="ce-cal__empty"><div class="ce-cal__empty-title">No days to show.</div><div>Try a different month.</div></div>';
    }
    // Weekday header row.
    var weekdayRow = '<div class="ce-cal__weekday-row">' +
      WEEKDAY_LABELS.map(function (lbl, i) {
        var weekend = (i >= 5) ? ' ce-cal__weekday-cell--weekend' : '';
        return '<div class="ce-cal__weekday-cell' + weekend + '">' + lbl + '</div>';
      }).join('') + '</div>';

    // Leading blanks (Monday-first). state.firstWeekday is 0=Mon..6=Sun
    // from Python's calendar.monthrange (matches JS WEEKDAY_LABELS order).
    var cellsHtml = '';
    for (var b = 0; b < state.firstWeekday; b++) {
      cellsHtml += '<div class="ce-cal__cell ce-cal__cell--blank"></div>';
    }
    state.days.forEach(function (day) {
      cellsHtml += renderDayCell(day);
    });

    return '' +
      '<div class="ce-cal__grid-wrap">' +
        weekdayRow +
        '<div class="ce-cal__grid" id="ce-cal-grid">' + cellsHtml + '</div>' +
      '</div>';
  }

  function renderDayCell(day) {
    var classes = ['ce-cal__cell'];
    if (day.is_today) classes.push('ce-cal__cell--today');
    if (day.is_past) classes.push('ce-cal__cell--past');
    if (day.min_lead_time_blocked) classes.push('ce-cal__cell--blocked');
    if (day.is_eligible) classes.push('ce-cal__cell--eligible');
    if (state.selectedDate === day.date) classes.push('ce-cal__cell--selected');

    var badges = '';
    if (day.is_today) {
      badges += '<span class="ce-cal__today-pill">TODAY</span>';
    }
    if (day.has_conflict) {
      badges += '<span class="ce-cal__conflict-icon" title="' +
        escapeHtml((day.conflicts || []).join(' · ')) + '">⚠</span>';
    }
    if (day.min_lead_time_blocked && !day.is_today) {
      badges += '<span class="ce-cal__blocked-pill">TOO SOON</span>';
    }

    var eventsHtml = '';
    if (day.player_events && day.player_events.length) {
      day.player_events.forEach(function (ev) {
        eventsHtml += '<div class="ce-cal__event ce-cal__event--player" title="' +
          escapeHtml(ev.event_name) + '">' +
          '<span class="ce-cal__event-name">' + escapeHtml(ev.event_name || 'Your Event') + '</span>' +
        '</div>';
      });
    }
    if (day.rival_events && day.rival_events.length) {
      day.rival_events.forEach(function (ev) {
        var logo = ev.promo_logo_b64
          ? '<img src="data:image/png;base64,' + ev.promo_logo_b64 + '" class="ce-cal__event-logo" alt="' + escapeHtml(ev.promo_name || '') + '" />'
          : '<span class="ce-cal__event-logo ce-cal__event-logo--placeholder">' + escapeHtml((ev.promo_name || '?').charAt(0)) + '</span>';
        eventsHtml += '<div class="ce-cal__event ce-cal__event--rival" title="' +
          escapeHtml(ev.promo_name + ': ' + ev.event_name) + '">' +
          logo +
          '<span class="ce-cal__event-name">' + escapeHtml(ev.promo_name || 'Rival') + '</span>' +
        '</div>';
      });
    }

    return '' +
      '<div class="' + classes.join(' ') + '" data-date="' + escapeHtml(day.date) + '"' +
        (day.is_eligible ? ' role="button" tabindex="0"' : '') + '>' +
        '<div class="ce-cal__day-num">' +
          '<span>' + day.day + '</span>' +
          (badges ? '<span class="ce-cal__day-badges">' + badges + '</span>' : '') +
        '</div>' +
        '<div class="ce-cal__events">' + eventsHtml + '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — DETAIL PANEL
  // ============================================================
  function renderDetail() {
    if (!state.selectedDate) {
      return '<div class="ce-cal__detail" id="ce-cal-detail"></div>';
    }
    var day = state.days.find(function (d) { return d.date === state.selectedDate; });
    if (!day) {
      return '<div class="ce-cal__detail" id="ce-cal-detail"></div>';
    }
    var voice = voiceTier(day);
    var visible = ' ce-cal__detail--visible';

    // Conflict lines.
    var conflictsHtml = '';
    if (day.has_conflict && day.conflicts && day.conflicts.length) {
      var lines = day.conflicts.map(function (c) {
        // Heuristic: phrases containing "counter-programming" are rival
        // (red), "short turnaround" are own (gold). Other warnings default
        // to warning (yellow).
        var lineClass = 'ce-cal__conflict-line';
        if (c.indexOf('counter-programming') >= 0) lineClass += ' ce-cal__conflict-line--rival';
        else if (c.indexOf('short turnaround') >= 0) lineClass += ' ce-cal__conflict-line--own';
        return '<div class="' + lineClass + '">' +
          '<span class="ce-cal__conflict-line-icon">⚠</span>' +
          '<span>' + escapeHtml(c) + '</span>' +
        '</div>';
      }).join('');
      conflictsHtml = '<div class="ce-cal__detail-section-title">CONFLICTS</div>' +
        '<div class="ce-cal__detail-conflicts">' + lines + '</div>';
    } else {
      conflictsHtml = '<div class="ce-cal__detail-section-title">CONFLICTS</div>' +
        '<div class="ce-cal__conflict-line" style="border-left-color: var(--green);">' +
          '<span class="ce-cal__conflict-line-icon">✓</span>' +
          '<span>No rival events within ±2 days. No own events within 7 days. Clean runway.</span>' +
        '</div>';
    }

    // Player events.
    var playerHtml = '';
    if (day.player_events && day.player_events.length) {
      var items = day.player_events.map(function (ev) {
        // P3.2 — when the selected day IS today (sim_date) and the
        // player has an event on it, show a "Watch the Show" button
        // that deep-links into fight_resolution (live mode). On any
        // other day, just show the event info (the button is on the
        // Dashboard for the upcoming-event case).
        var watchBtn = '';
        if (day.is_today && ev.event_id) {
          watchBtn = '<button class="ce-cal__watch-btn" type="button" ' +
            'data-event-id="' + ev.event_id + '" ' +
            'title="Watch tonight\'s card play out fight by fight.">' +
            '▶ Watch the Show</button>';
        } else if (ev.event_id) {
          // Future event — show a hint that the player can watch on
          // the event day (greyed-out, no click).
          watchBtn = '<button class="ce-cal__watch-btn ce-cal__watch-btn--disabled" ' +
            'disabled type="button" title="Watch the Show on the event day.">' +
            '▶ Watch the Show</button>';
        }
        return '<div class="ce-cal__detail-event-item">' +
          '<div>' +
            '<div class="ce-cal__detail-event-name">' + escapeHtml(ev.event_name || 'Your Event') + '</div>' +
            '<div class="ce-cal__detail-event-promo">Your promotion · ' + escapeHtml(ev.event_type || 'fight_night') + '</div>' +
            watchBtn +
          '</div>' +
        '</div>';
      }).join('');
      playerHtml = '<div class="ce-cal__detail-event-col">' +
        '<div class="ce-cal__detail-section-title">YOUR EVENTS</div>' + items + '</div>';
    } else {
      playerHtml = '<div class="ce-cal__detail-event-col ce-cal__detail-event-col--empty">' +
        '<div class="ce-cal__detail-section-title">YOUR EVENTS</div>' +
        '<div class="ce-cal__detail-empty-line">Nothing booked.</div>' +
      '</div>';
    }

    // Rival events.
    var rivalHtml = '';
    if (day.rival_events && day.rival_events.length) {
      var ritems = day.rival_events.map(function (ev) {
        var logo = ev.promo_logo_b64
          ? '<img src="data:image/png;base64,' + ev.promo_logo_b64 + '" alt="' + escapeHtml(ev.promo_name || '') + '" />'
          : '<img src="" alt="" style="display:none" />';
        return '<div class="ce-cal__detail-event-item">' +
          logo +
          '<div>' +
            '<div class="ce-cal__detail-event-name">' + escapeHtml(ev.event_name || 'Rival Event') + '</div>' +
            '<div class="ce-cal__detail-event-promo">' + escapeHtml(ev.promo_name || 'Rival Promo') + '</div>' +
          '</div>' +
        '</div>';
      }).join('');
      rivalHtml = '<div class="ce-cal__detail-event-col">' +
        '<div class="ce-cal__detail-section-title">RIVAL EVENTS</div>' + ritems + '</div>';
    } else {
      rivalHtml = '<div class="ce-cal__detail-event-col ce-cal__detail-event-col--empty">' +
        '<div class="ce-cal__detail-section-title">RIVAL EVENTS</div>' +
        '<div class="ce-cal__detail-empty-line">No rival shows in town.</div>' +
      '</div>';
    }

    // CTA — only enabled when eligible (future + ≥14d).
    var canSchedule = !!day.is_eligible;
    var cta = '';
    if (canSchedule) {
      cta = '<button class="ce-cal__schedule-btn" id="ce-cal-schedule" type="button">' +
        'Schedule Event on ' + escapeHtml(formatDateLong(day.date)) + '</button>';
    } else if (day.is_past) {
      cta = '<button class="ce-cal__schedule-btn" disabled type="button">Past Date — Cannot Schedule</button>';
    } else if (day.min_lead_time_blocked) {
      cta = '<button class="ce-cal__schedule-btn" disabled type="button">Too Soon — Need ' + state.minLeadDays + ' Days Lead</button>';
    }
    var clear = state.selectedDate
      ? '<button class="ce-cal__schedule-btn ce-cal__schedule-btn--secondary" id="ce-cal-clear" type="button">Clear Selection</button>'
      : '';

    return '' +
      '<div class="ce-cal__detail' + visible + '" id="ce-cal-detail">' +
        '<div class="ce-cal__detail-header">' +
          '<div class="ce-cal__detail-date">' + escapeHtml(formatDateLong(day.date)) + '</div>' +
          '<span class="ce-cal__detail-voice ' + voice.cssClass + '">' + escapeHtml(voice.label) + '</span>' +
        '</div>' +
        '<div class="ce-cal__detail-body">' +
          conflictsHtml +
        '</div>' +
        '<div class="ce-cal__detail-events">' +
          playerHtml +
          rivalHtml +
        '</div>' +
        '<div class="ce-cal__detail-actions">' +
          cta +
          clear +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // MAIN RENDER
  // ============================================================
  function render() {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var html = '' +
      '<div class="ce-cal">' +
        // 1. THE CALENDAR section header
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">📅</span>' +
            '<span class="ce-sec-title ce-sec-title-gold">THE CALENDAR</span>' +
            '<span class="ce-sec-sub ce-mono">pick a date · stack a card</span>' +
          '</div>' +
        '</div>' +
        renderHeader() +
        renderSimStrip() +
        renderGrid() +
        renderDetail() +
      '</div>';
    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    var prevBtn = document.getElementById('ce-cal-prev');
    if (prevBtn) prevBtn.addEventListener('click', function () {
      gotoMonth(state.prevMonth.month, state.prevMonth.year);
    });
    var nextBtn = document.getElementById('ce-cal-next');
    if (nextBtn) nextBtn.addEventListener('click', function () {
      gotoMonth(state.nextMonth.month, state.nextMonth.year);
    });
    var todayBtn = document.getElementById('ce-cal-today');
    if (todayBtn) todayBtn.addEventListener('click', function () {
      // Reset to sim month + clear selection.
      state.selectedDate = null;
      loadAndRender();
    });

    // Day cells + detail panel buttons.
    wireGridCells();
    wireDetailEvents();
  }

  function wireGridCells() {
    var cells = document.querySelectorAll('.ce-cal__cell--eligible');
    cells.forEach(function (cell) {
      // Skip if already wired (avoid double-bind).
      if (cell._ceWired) return;
      cell._ceWired = true;
      cell.addEventListener('click', function () {
        var date = cell.getAttribute('data-date');
        if (!date) return;
        state.selectedDate = (state.selectedDate === date) ? null : date;
        var wrap = document.querySelector('.ce-cal__grid-wrap');
        if (wrap) wrap.outerHTML = renderGrid();
        wireGridCells();
        var detail = document.getElementById('ce-cal-detail');
        if (detail) detail.outerHTML = renderDetail();
        wireDetailEvents();
      });
      cell.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault();
          cell.click();
        }
      });
    });
  }

  function wireDetailEvents() {
    var schedBtn = document.getElementById('ce-cal-schedule');
    if (schedBtn && !schedBtn._ceWired) {
      schedBtn._ceWired = true;
      schedBtn.addEventListener('click', function () {
        if (!state.selectedDate) return;
        // Navigate to Stack a Card with event_date pre-filled.
        window.CE.app.navigate('event_builder', { event_date: state.selectedDate });
      });
    }
    var clearBtn = document.getElementById('ce-cal-clear');
    if (clearBtn && !clearBtn._ceWired) {
      clearBtn._ceWired = true;
      clearBtn.addEventListener('click', function () {
        state.selectedDate = null;
        var wrap = document.querySelector('.ce-cal__grid-wrap');
        if (wrap) wrap.outerHTML = renderGrid();
        wireGridCells();
        var detail = document.getElementById('ce-cal-detail');
        if (detail) detail.outerHTML = renderDetail();
        wireDetailEvents();
      });
    }
    // P3.2 — wire any "Watch the Show" buttons on player events
    // shown in the detail panel. Only today's events get an enabled
    // button (rendered in renderDetail); future events show a
    // disabled button.
    var watchBtns = document.querySelectorAll('.ce-cal__watch-btn[data-event-id]');
    watchBtns.forEach(function (btn) {
      if (btn._ceWired) return;
      btn._ceWired = true;
      btn.addEventListener('click', function () {
        var eid = btn.getAttribute('data-event-id');
        if (eid) {
          window.CE.app.navigate('fight_resolution', { event_id: Number(eid) });
        }
      });
    });
  }

  // ============================================================
  // LOAD + RENDER
  // ============================================================
  function gotoMonth(month, year) {
    state.month = month;
    state.year = year;
    state.selectedDate = null;
    loadAndRender(month, year);
  }

  function loadAndRender(month, year) {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Loading the calendar…</div></div>';
    }
    return window.CE.bridge.getCalendarData(month, year).then(function (data) {
      if (!data || data.error || data.ok === false) {
        if (host) {
          host.innerHTML = '<div class="ce-cal"><div class="ce-cal__error-banner"><strong>Calendar error</strong><div>' +
            escapeHtml(data ? (data.error || 'unknown') : 'unknown') + '</div></div></div>';
        }
        return;
      }
      state.month = data.month;
      state.year = data.year;
      state.simDate = data.current_date;
      state.minLeadDays = data.min_lead_days || 14;
      state.playerPromoName = data.player_promo_name || 'Your Promotion';
      state.days = data.days || [];
      state.firstWeekday = data.first_weekday || 0;
      state.prevMonth = data.prev_month;
      state.nextMonth = data.next_month;
      // If user navigated back via the back stack to a previously
      // selected date, keep that selection if it's in this month.
      if (state.selectedDate) {
        var stillInMonth = state.days.some(function (d) { return d.date === state.selectedDate; });
        if (!stillInMonth) state.selectedDate = null;
      }
      render();
    }).catch(function (err) {
      console.error('[calendar] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-cal"><div class="ce-cal__error-banner"><strong>Calendar error</strong><div>' +
          escapeHtml(String(err)) + '</div></div></div>';
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
