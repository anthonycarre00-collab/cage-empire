/* ============================================================
   CAGE EMPIRE — The Archive Screen ("THE ARCHIVE")
   ============================================================
   Phase INFO-SCREENS-BATCH-1 §2. Replaces the placeholder
   Past Events nav item. Renders the player's book of past
   cards — the Attachment reward ("I remember that card").

   What the player sees:
     - Section header: "THE ARCHIVE" (gold accent) + subtitle
       "Your past cards" (ownership language).
     - Filter bar: date-from + date-to + search + min-rating.
     - Event list: each event row shows event name, date, venue,
       rating voice phrase (instant classic / solid night /
       lackluster), main event result (winner over loser via
       method R-round), net profit with voice caption.
     - Click event → expand to show full card (each fight:
       Red vs Blue, result_label, finish_round, winner
       highlighted with gold left border + W chip).
     - Pagination: 10 events/page.
     - Voice empty state: "The archive is empty. Once you run
       your first card, it'll live here forever."

   Voice compliance (CONVENTIONS §14 + REWARD_REVIEW Principle 2
   + Principle 5):
     - Ownership: "YOUR PAST CARDS" subtitle.
     - No raw rating ints — voice phrases only.
     - Net profit shown as $ figure (player owns the money) +
       voice caption ("in the black" / "took a bath").
     - No tabloid clichés — business-page register.
   ============================================================ */

window.CE = window.CE || {};

window.CE.archive = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    page: 1,
    filters: {
      date_from: '',
      date_to: '',
      search: '',
      min_rating: '',
    },
    data: null,                // last fetched list payload
    expandedEventId: null,     // event_id of the currently-expanded row
    expandedCard: null,        // {event_id, fights: [...]}
    _searchTimer: null,
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

  /** Format a YYYY-MM-DD as "Mon D, YYYY". */
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

  /** Format capacity with thousands separator. */
  function formatCapacity(n) {
    if (!n) return '—';
    return parseInt(n, 10).toLocaleString();
  }

  /** Return a fighter-name HTML span — gold link if clickable. */
  function fighterSpan(f, fallbackName) {
    if (!f) {
      return '<span class="ce-archive__fighter ce-archive__fighter--unknown">' +
        escapeHtml(fallbackName || '—') + '</span>';
    }
    var name = f.name || fallbackName || '—';
    var nick = f.nickname ? " '" + f.nickname + "'" : '';
    if (f.fighter_id) {
      return '<a class="ce-link ce-archive__fighter" href="#" data-fighter-id="' +
        f.fighter_id + '">' + escapeHtml(name) + escapeHtml(nick) + '</a>';
    }
    return '<span class="ce-archive__fighter">' + escapeHtml(name) + escapeHtml(nick) + '</span>';
  }

  // ============================================================
  // RENDER — FILTER BAR
  // ============================================================
  function renderFilterBar() {
    var f = state.filters;
    var total = (state.data && state.data.total) || 0;
    var page = (state.data && state.data.page) || 1;
    var totalPages = (state.data && state.data.total_pages) || 1;
    var summary = total === 0
      ? 'No cards on record.'
      : (total + ' card' + (total === 1 ? '' : 's') + ' in the books · page ' +
         page + ' of ' + totalPages);

    return '' +
      '<div class="ce-archive__filter-bar">' +
        '<div class="ce-archive__filters">' +
          '<div class="ce-archive__filter-group">' +
            '<label class="ce-archive__filter-label" for="ce-archive-from">FROM</label>' +
            '<input type="date" id="ce-archive-from" class="ce-archive__date-input" ' +
              'value="' + escapeHtml(f.date_from) + '" />' +
          '</div>' +
          '<div class="ce-archive__filter-group">' +
            '<label class="ce-archive__filter-label" for="ce-archive-to">TO</label>' +
            '<input type="date" id="ce-archive-to" class="ce-archive__date-input" ' +
              'value="' + escapeHtml(f.date_to) + '" />' +
          '</div>' +
          '<div class="ce-archive__filter-group">' +
            '<label class="ce-archive__filter-label" for="ce-archive-rating">MIN RATING</label>' +
            '<select id="ce-archive-rating" class="ce-archive__select">' +
              '<option value=""' + (f.min_rating === '' ? ' selected' : '') + '>Any</option>' +
              '<option value="85"' + (f.min_rating === 85 ? ' selected' : '') + '>Instant Classic (85+)</option>' +
              '<option value="75"' + (f.min_rating === 75 ? ' selected' : '') + '>Memorable (75+)</option>' +
              '<option value="65"' + (f.min_rating === 65 ? ' selected' : '') + '>Solid Night (65+)</option>' +
              '<option value="55"' + (f.min_rating === 55 ? ' selected' : '') + '>Decent (55+)</option>' +
            '</select>' +
          '</div>' +
          '<div class="ce-archive__filter-group ce-archive__filter-group--search">' +
            '<label class="ce-archive__filter-label" for="ce-archive-search">SEARCH</label>' +
            '<input type="text" id="ce-archive-search" class="ce-archive__search" ' +
              'placeholder="Event name…" value="' + escapeHtml(f.search) + '" maxlength="80" />' +
          '</div>' +
          '<button id="ce-archive-clear" type="button" class="ce-btn ce-btn-ghost ce-archive__clear-btn">Reset</button>' +
        '</div>' +
        '<div class="ce-archive__summary">' + escapeHtml(summary) + '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — EVENT LIST
  // ============================================================
  function renderList() {
    var events = (state.data && state.data.events) || [];
    if (!events.length) {
      return '' +
        '<div class="ce-archive__empty">' +
          '<div class="ce-archive__empty-title">The archive is empty.</div>' +
          '<div class="ce-archive__empty-body">Once you run your first card, it will live here forever.</div>' +
        '</div>';
    }
    var rows = events.map(function (ev) {
      var isExpanded = (state.expandedEventId === ev.event_id);
      var classes = ['ce-archive__item'];
      if (isExpanded) classes.push('ce-archive__item--expanded');

      // Rating chip — color-coded by tier (from server).
      var ratingChipHtml = ev.overall_rating
        ? '<span class="ce-chip ce-archive__rating-chip" style="border-color:' +
          ev.rating_tier_color + '; color:' + ev.rating_tier_color + ';">' +
          escapeHtml(ev.rating_tier_label) + '</span>'
        : '<span class="ce-chip ce-chip-default ce-archive__rating-chip">UNRATED</span>';

      // Main event result.
      var meHtml = '<span class="ce-archive__me-empty">no main event on file</span>';
      if (ev.main_event) {
        var me = ev.main_event;
        var winnerHtml = '<span class="ce-archive__me-winner">' +
          escapeHtml(me.winner_name) +
          (me.winner_nickname ? " <span class='ce-archive__me-nick'>'" +
            escapeHtml(me.winner_nickname) + "'</span>" : '') + '</span>';
        var loserHtml = '<span class="ce-archive__me-loser">def. ' +
          escapeHtml(me.loser_name) +
          (me.loser_nickname ? " <span class='ce-archive__me-nick'>'" +
            escapeHtml(me.loser_nickname) + "'</span>" : '') + '</span>';
        var methodHtml = '<span class="ce-archive__me-method">' +
          escapeHtml(me.result_label || '—') +
          (me.finish_round ? ' · R' + me.finish_round : '') + '</span>';
        var titleChip = me.is_title_fight
          ? '<span class="ce-chip ce-chip-gold ce-archive__title-chip">TITLE</span>'
          : '';
        meHtml = winnerHtml + ' ' + loserHtml + ' ' + methodHtml + ' ' + titleChip;
      }

      // Venue line.
      var venueParts = [];
      if (ev.venue_name) venueParts.push(escapeHtml(ev.venue_name));
      if (ev.city_name) venueParts.push(escapeHtml(ev.city_name));
      if (ev.venue_capacity) venueParts.push(formatCapacity(ev.venue_capacity) + ' seats');
      var venueHtml = venueParts.join('<span class="ce-archive__sep"> · </span>');

      // Net profit.
      var profitClass = 'ce-archive__profit--neutral';
      if (ev.net_profit > 0) profitClass = 'ce-archive__profit--positive';
      else if (ev.net_profit < 0) profitClass = 'ce-archive__profit--negative';
      var profitHtml = '<span class="ce-archive__profit ' + profitClass + '">' +
        escapeHtml(ev.net_profit_display) + '</span>' +
        '<span class="ce-archive__profit-voice">' + escapeHtml(ev.net_profit_voice) + '</span>';

      // Fight count.
      var countHtml = '<span class="ce-archive__count">' + ev.n_fights +
        ' fight' + (ev.n_fights === 1 ? '' : 's') +
        (ev.n_title_fights ? ' · ' + ev.n_title_fights + ' title' : '') +
        '</span>';

      // Expand caret.
      var caret = isExpanded ? '▾' : '▸';

      var html = '' +
        '<article class="' + classes.join(' ') + '" data-event-id="' + ev.event_id + '">' +
          '<div class="ce-archive__item-row" role="button" tabindex="0" ' +
            'data-event-id="' + ev.event_id + '">' +
            '<div class="ce-archive__item-caret">' + caret + '</div>' +
            '<div class="ce-archive__item-main">' +
              '<div class="ce-archive__item-title-row">' +
                '<span class="ce-archive__item-name">' + escapeHtml(ev.event_name) + '</span>' +
                '<span class="ce-archive__item-date">' + escapeHtml(formatDate(ev.event_date_display)) + '</span>' +
                ratingChipHtml +
              '</div>' +
              '<div class="ce-archive__item-me">' + meHtml + '</div>' +
              '<div class="ce-archive__item-meta">' +
                '<span class="ce-archive__venue">' + venueHtml + '</span>' +
                countHtml +
              '</div>' +
            '</div>' +
            '<div class="ce-archive__item-profit">' + profitHtml + '</div>' +
          '</div>' +
          (isExpanded ? renderExpandedCard(ev) : '') +
        '</article>';
      return html;
    }).join('');

    return '<div class="ce-archive__list">' + rows + '</div>';
  }

  // ============================================================
  // RENDER — EXPANDED CARD (fights list)
  // ============================================================
  function renderExpandedCard(ev) {
    if (!state.expandedCard || state.expandedCard.event_id !== ev.event_id) {
      return '<div class="ce-archive__card ce-archive__card--loading">' +
        '<div class="ce-loading"><div class="ce-loading__spinner"></div>' +
        '<div class="ce-loading__text">Loading the card…</div></div></div>';
    }
    var fights = state.expandedCard.fights || [];
    if (!fights.length) {
      return '<div class="ce-archive__card ce-archive__card--empty">' +
        '<div class="ce-archive__card-empty-title">No fights recorded.</div>' +
        '<div class="ce-archive__card-empty-body">This event predates the fight ledger.</div>' +
      '</div>';
    }
    var rows = fights.map(function (f) {
      var red = f.red || {};
      var blue = f.blue || {};

      // Winner highlight — gold left border on the winner's side.
      var redClass = 'ce-archive__corner';
      var blueClass = 'ce-archive__corner';
      if (red.is_winner) redClass += ' ce-archive__corner--winner';
      if (blue.is_winner) blueClass += ' ce-archive__corner--winner';

      var titleChip = f.is_title_fight
        ? '<span class="ce-chip ce-chip-gold ce-archive__fight-title">TITLE</span>'
        : '';
      var slotChip = '<span class="ce-archive__fight-slot">' +
        escapeHtml(f.card_slot_label) + '</span>';

      // Result block: METHOD · R# · WC.
      var resultParts = [escapeHtml(f.result_label || '—')];
      if (f.finish_round) resultParts.push('R' + f.finish_round);
      if (f.finish_time) resultParts.push(escapeHtml(f.finish_time));
      if (f.weight_class_name) resultParts.push(escapeHtml(f.weight_class_name));
      var resultHtml = '<span class="ce-archive__fight-result">' +
        resultParts.join(' · ') + '</span>';

      return '' +
        '<div class="ce-archive__fight" data-fight-id="' + f.fight_id + '">' +
          '<div class="ce-archive__fight-meta">' + slotChip + titleChip + '</div>' +
          '<div class="ce-archive__fight-body">' +
            '<div class="' + redClass + '">' +
              (red.is_winner ? '<span class="ce-archive__w-chip">W</span>' : '') +
              fighterSpan(red, '—') +
            '</div>' +
            '<div class="ce-archive__vs">vs</div>' +
            '<div class="' + blueClass + '">' +
              (blue.is_winner ? '<span class="ce-archive__w-chip">W</span>' : '') +
              fighterSpan(blue, '—') +
            '</div>' +
          '</div>' +
          '<div class="ce-archive__fight-footer">' + resultHtml + '</div>' +
        '</div>';
    }).join('');

    return '' +
      '<div class="ce-archive__card">' +
        '<div class="ce-archive__card-header">' +
          '<span class="ce-archive__card-title">FULL CARD</span>' +
          '<span class="ce-archive__card-count">' + fights.length + ' fight' +
            (fights.length === 1 ? '' : 's') + '</span>' +
        '</div>' +
        '<div class="ce-archive__fights">' + rows + '</div>' +
        // Task FIGHT-NIGHT-SHOWCASE — Replay button on the Archive's
        // expanded card. Opens Fight Night in replay mode for the
        // first fight on the card (the player can navigate to other
        // fights from there via the \"Next Fight\" button).
        '<div class="ce-archive__card-actions">' +
          '<button class="ce-archive__replay-btn" id="ce-archive-replay" data-event-id="' + ev.event_id + '">▶ Replay on Fight Night</button>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — PAGINATION
  // ============================================================
  function renderPagination() {
    var d = state.data;
    if (!d || !d.total) return '';
    var page = d.page;
    var total = d.total_pages;
    if (total <= 1) return '';

    var pages = new Set([1, total, page]);
    for (var i = -2; i <= 2; i++) {
      var p = page + i;
      if (p >= 1 && p <= total) pages.add(p);
    }
    var sorted = Array.from(pages).sort(function (a, b) { return a - b; });

    var html = '<div class="ce-archive__pagination">';
    html += '<button type="button" class="ce-page-btn" data-page="' + (page - 1) + '"' +
      (page <= 1 ? ' disabled' : '') + '>← Prev</button>';
    var prevP = 0;
    sorted.forEach(function (p) {
      if (p - prevP > 1) {
        html += '<span class="ce-page-ellipsis">…</span>';
      }
      var cls = (p === page) ? 'ce-page-btn ce-page-btn--active' : 'ce-page-btn';
      html += '<button type="button" class="' + cls + '" data-page="' + p + '">' + p + '</button>';
      prevP = p;
    });
    html += '<button type="button" class="ce-page-btn" data-page="' + (page + 1) + '"' +
      (page >= total ? ' disabled' : '') + '>Next →</button>';
    html += '</div>';
    return html;
  }

  // ============================================================
  // MAIN RENDER
  // ============================================================
  function render() {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var html = '' +
      '<div class="ce-archive">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">📦</span>' +
            '<span class="ce-sec-title ce-sec-title-gold">THE ARCHIVE</span>' +
            '<span class="ce-sec-sub ce-mono">your past cards</span>' +
          '</div>' +
        '</div>' +
        renderFilterBar() +
        renderList() +
        renderPagination() +
      '</div>';
    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    var fromInput = document.getElementById('ce-archive-from');
    if (fromInput) fromInput.addEventListener('change', function () {
      state.filters.date_from = fromInput.value;
      state.page = 1;
      loadAndRender();
    });
    var toInput = document.getElementById('ce-archive-to');
    if (toInput) toInput.addEventListener('change', function () {
      state.filters.date_to = toInput.value;
      state.page = 1;
      loadAndRender();
    });
    var ratingSel = document.getElementById('ce-archive-rating');
    if (ratingSel) ratingSel.addEventListener('change', function () {
      state.filters.min_rating = ratingSel.value ? parseInt(ratingSel.value, 10) : '';
      state.page = 1;
      loadAndRender();
    });
    var searchInput = document.getElementById('ce-archive-search');
    if (searchInput) searchInput.addEventListener('input', function () {
      if (state._searchTimer) clearTimeout(state._searchTimer);
      state._searchTimer = setTimeout(function () {
        state.filters.search = searchInput.value;
        state.page = 1;
        loadAndRender();
      }, 250);
    });
    var clearBtn = document.getElementById('ce-archive-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () {
      state.filters = { date_from: '', date_to: '', search: '', min_rating: '' };
      state.page = 1;
      loadAndRender();
    });

    // Click an event row → expand/collapse + lazy-load the card.
    document.querySelectorAll('.ce-archive__item-row').forEach(function (row) {
      row.addEventListener('click', function (evt) {
        // Don't toggle if the click was on a fighter-name link inside
        // the row (let the link navigate).
        if (evt.target.closest('.ce-archive__fighter[data-fighter-id]')) return;
        var eid = parseInt(row.getAttribute('data-event-id'), 10);
        if (!eid) return;
        toggleExpand(eid);
      });
      row.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault();
          row.click();
        }
      });
    });

    // Fighter-name hyperlinks → Fighter Profile (also inside expanded
    // cards). Re-bind every render since the expanded card is fresh.
    document.querySelectorAll('.ce-archive__fighter[data-fighter-id]').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        evt.stopPropagation();
        var fid = link.getAttribute('data-fighter-id');
        if (fid) window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
      });
    });

    // Task FIGHT-NIGHT-SHOWCASE — Replay button on the expanded card.
    // Navigates to fight_resolution in replay mode for the FIRST fight
    // on the card (the player can navigate to other fights from there
    // via the \"Next Fight\" button).
    var replayBtn = document.getElementById('ce-archive-replay');
    if (replayBtn) {
      replayBtn.addEventListener('click', function (evt) {
        evt.stopPropagation();
        // Find the first fight_id on the expanded card.
        var firstFightId = null;
        if (state.expandedCard && state.expandedCard.fights &&
            state.expandedCard.fights.length > 0) {
          firstFightId = state.expandedCard.fights[0].fight_id;
        }
        if (firstFightId) {
          window.CE.app.navigate('fight_resolution', { fight_id: Number(firstFightId) });
        } else {
          // Fallback: navigate with the event_id (live mode).
          var eid = replayBtn.getAttribute('data-event-id');
          if (eid) {
            window.CE.app.navigate('fight_resolution', { event_id: Number(eid) });
          }
        }
      });
    }

    // Pagination.
    document.querySelectorAll('.ce-archive__pagination .ce-page-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.disabled) return;
        var p = parseInt(btn.getAttribute('data-page'), 10);
        if (!p || p < 1) return;
        state.page = p;
        state.expandedEventId = null;
        state.expandedCard = null;
        loadAndRender();
        var screen = document.getElementById('ce-screen');
        if (screen) screen.scrollTop = 0;
      });
    });
  }

  function toggleExpand(eventId) {
    if (state.expandedEventId === eventId) {
      // Collapse.
      state.expandedEventId = null;
      state.expandedCard = null;
      render();
      return;
    }
    // Expand — optimistically render the loading state, then fetch.
    state.expandedEventId = eventId;
    state.expandedCard = null;
    render();
    window.CE.bridge.getEventCard(eventId).then(function (card) {
      if (!card || card.error) {
        state.expandedCard = { event_id: eventId, fights: [] };
      } else {
        state.expandedCard = card;
      }
      // Only update if the player hasn't collapsed in the meantime.
      if (state.expandedEventId === eventId) {
        render();
      }
    }).catch(function (err) {
      console.error('[archive] get_event_card failed:', err);
      state.expandedCard = { event_id: eventId, fights: [] };
      if (state.expandedEventId === eventId) render();
    });
  }

  // ============================================================
  // LOAD + RENDER
  // ============================================================
  function loadAndRender() {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Opening the archive…</div></div>';
    }
    // Build a clean filters object (drop empty values + cast min_rating).
    var filters = {
      date_from: state.filters.date_from || '',
      date_to: state.filters.date_to || '',
      search: state.filters.search || '',
      min_rating: state.filters.min_rating || '',
    };
    return window.CE.bridge.getArchiveData(state.page, filters).then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load The Archive</div><div>' +
            escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      state.data = data;
      render();
    }).catch(function (err) {
      console.error('[archive] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load The Archive</div><div>' +
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
