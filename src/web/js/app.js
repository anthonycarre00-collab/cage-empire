/* ============================================================
   CAGE EMPIRE — App Logic (navigation, state, pre-game)
   ============================================================
   FLOW:
   1. App launches → pre-game screen loads (full screen, no shell)
   2. Pre-game fetches promotion list via bridge
   3. Player clicks a promotion → bridge.selectPromotion()
   4. Pre-game hides → app shell (top bar + sidebar) shows
   5. Dashboard renders with the selected promotion's data
   6. On next launch: if promo already selected, skip pre-game
   ============================================================ */

window.CE = window.CE || {};

window.CE.app = (function () {
  'use strict';

  var state = {
    promoId: null,
    activeScreen: null,
    activeParams: {},
    _navStack: [],  // back-navigation stack (cap 10, FIFO overflow)
    _staleScreens: new Set(),  // screens needing refresh after advanceDay
  };

  // ============================================================
  // NAV CONFIG — sidebar groups + items
  // ============================================================
  var NAV_GROUPS = [
    { label: 'HOME', items: [
      { id: 'dashboard', name: 'The Empire', icon: '🏛' },
      { id: 'schedule', name: 'Calendar', icon: '📅' },
      { id: 'news', name: 'The Wire', icon: '📰' },
    ]},
    { label: 'FIGHTERS', items: [
      { id: 'roster', name: 'The Stable', icon: '🥊' },
      { id: 'free_agents', name: 'Open Market', icon: '🏪' },
      { id: 'scouting', name: 'Scouting', icon: '🔍' },
      { id: 'agent_offers', name: 'Agent Offers', icon: '🤝' },
      { id: 'hall_of_fame', name: 'Legends', icon: '🏆' },
    ]},
    { label: 'EVENTS', items: [
      { id: 'event_builder', name: 'Stack a Card', icon: '🎫' },
      { id: 'matchmaking', name: 'Matchmaking', icon: '⚔' },
      { id: 'past_events', name: 'The Archive', icon: '📦' },
    ]},
    { label: 'BUSINESS', items: [
      { id: 'finance', name: 'The Books', icon: '💰' },
      { id: 'contracts', name: 'Deals', icon: '✍' },
      { id: 'staff_market', name: 'Staff Market', icon: '👔' },
      { id: 'rival_promotions', name: 'The Competition', icon: '⚔' },
      { id: 'gyms', name: 'Training Camps', icon: '🏋' },
    ]},
    { label: 'WORLD', items: [
      { id: 'rankings', name: 'The Rankings', icon: '📊' },
      { id: 'titles', name: 'Belts', icon: '🥇' },
      { id: 'rivalries', name: 'Bad Blood', icon: '💢' },
      { id: 'records', name: 'The Record Book', icon: '📖' },
    ]},
  ];

  var PLACEHOLDER_PHRASES = {
    roster: { title: 'Your stable is ready.', body: 'Every fighter on your roster. Their stories, their form, their potential.' },
    free_agents: { title: 'The market is open.', body: 'Unsigned talent. Some are proven. Some are gambles. All are available.' },
    scouting: { title: 'The scouts are waiting.', body: 'Send them out. Find the next great one before anyone else does.' },
    agent_offers: { title: 'Your phone is quiet.', body: 'When agents come knocking with mystery talent, you\'ll find them here.' },
    hall_of_fame: { title: 'Legends never die.', body: 'The fighters who shaped the sport. Their stories live here.' },
    schedule: { title: 'The calendar is clear.', body: 'Build a card. Give the fans something to remember.' },
    news: { title: 'The newswire is quiet.', body: 'No stories have broken. Advance a day and see what develops.' },
    event_builder: { title: 'Time to stack a card.', body: 'Pick a venue, set the levers, then head to Matchmaking to book the fights.' },
    matchmaking: { title: 'Pick two fighters.', body: 'See the tale of the tape. Find the right matchup. Watch the projection rise.' },
    fight_resolution: { title: 'Fight Night awaits.', body: 'The cage is ready. The fans are waiting.' },
    past_events: { title: 'The archive is empty.', body: 'Once you run your first card, it will live here forever.' },
    finance: { title: 'The books are open.', body: 'Every dollar in, every dollar out. Run a tight ship.' },
    contracts: { title: 'No deals on the table.', body: 'When fighters need new contracts, they will appear here.' },
    rival_promotions: { title: 'The competition is out there.', body: 'They are signing fighters. They are booking shows. Keep up.' },
    gyms: { title: 'Training camps are ready.', body: 'Send your fighters to develop. The right camp changes careers.' },
    staff_market: { title: 'The staff market is open.', body: 'Coaches, scouts, doctors, cutmen, GMs, commentators. Build the team behind your roster.' },
    rankings: { title: 'The rankings are live.', body: 'Who is climbing. Who is falling. The divisional picture.' },
    titles: { title: 'The belts are waiting.', body: 'Every champion, every reign, every title fight.' },
    rivalries: { title: 'No bad blood brewing.', body: 'Rivalries develop over time. When they do, they will be here.' },
    records: { title: 'The record book is open.', body: 'All-time leaders. The names that echo through the sport.' },
  };

  // ============================================================
  // PRE-GAME SCREEN
  // ============================================================
  function showPregame() {
    var pregame = document.getElementById('ce-pregame');
    var app = document.getElementById('ce-app');
    if (pregame) pregame.style.display = 'flex';
    if (app) app.classList.add('ce-app--hidden');

    // P5.2 — wire the Load Game button (pre-game, below promo grid).
    wireLoadButton();

    // Load promotion list
    var grid = document.getElementById('pregame-promo-grid');
    if (!grid) return;

    window.CE.bridge.getPromotionList().then(function (promos) {
      // Handle pywebview returning undefined or a non-array
      if (!promos || !Array.isArray(promos)) {
        grid.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Could not load promotions</div><div>Check the console for errors.</div></div>';
        return;
      }

      var html = '';
      promos.forEach(function (p) {
        var logo = p.logo_b64
          ? '<img src="data:image/png;base64,' + p.logo_b64 + '" class="ce-promo-card__logo" alt="' + escapeHtml(p.name) + '" />'
          : '<div class="ce-promo-card__logo ce-promo-card__logo--placeholder">' + escapeHtml(p.name.charAt(0)) + '</div>';
        html += '<div class="ce-promo-card" data-promo-id="' + p.promotion_id + '" role="button" tabindex="0">' +
          logo +
          '<div class="ce-promo-card__name">' + escapeHtml(p.name) + '</div>' +
          '<div class="ce-promo-card__cash">' + formatCash(p.current_cash) + '</div>' +
          '<div class="ce-promo-card__meta">' +
            '<span class="ce-chip ce-chip-default">' + escapeHtml((p.size_tier || '').toUpperCase()) + '</span>' +
            '<span class="ce-chip ce-chip-default">' + escapeHtml((p.broadcast_tier || '').toUpperCase()) + '</span>' +
          '</div>' +
        '</div>';
      });
      grid.innerHTML = html;

      // Wire up clicks
      grid.querySelectorAll('.ce-promo-card').forEach(function (card) {
        card.addEventListener('click', function () {
          var pid = parseInt(card.getAttribute('data-promo-id'), 10);
          onPromotionSelected(pid);
        });
        card.addEventListener('keydown', function (evt) {
          if (evt.key === 'Enter' || evt.key === ' ') {
            evt.preventDefault();
            var pid = parseInt(card.getAttribute('data-promo-id'), 10);
            onPromotionSelected(pid);
          }
        });
      });
    }).catch(function (err) {
      grid.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Could not load promotions</div><div>' + escapeHtml(String(err)) + '</div></div>';
    });
  }

  function onPromotionSelected(promoId) {
    // Get the player name from the input field
    var nameInput = document.getElementById('pregame-name-input');
    var playerName = nameInput ? nameInput.value.trim() : '';

    // First save the player name (if entered)
    var namePromise = playerName
      ? window.CE.bridge.setPlayerName(playerName)
      : Promise.resolve();

    namePromise.then(function () {
      return window.CE.bridge.selectPromotion(promoId);
    }).then(function () {
      state.promoId = promoId;
      state.playerName = playerName || 'Promoter';
      // Hide pre-game, show app shell
      var pregame = document.getElementById('ce-pregame');
      var app = document.getElementById('ce-app');
      if (pregame) pregame.style.display = 'none';
      if (app) app.classList.remove('ce-app--hidden');
      // Build shell + navigate to dashboard
      buildSidebar();
      wireAdvanceDay();
      updateTopBar();
      navigate('dashboard');
    }).catch(function (err) {
      console.error('[app] selection failed:', err);
    });
  }

  // ============================================================
  // APP SHELL
  // ============================================================
  function buildSidebar() {
    var sidebar = document.getElementById('ce-sidebar');
    if (!sidebar) return;
    var html = '';
    NAV_GROUPS.forEach(function (group) {
      html += '<div class="ce-nav-group"><div class="ce-nav-group__label">' + group.label + '</div>';
      group.items.forEach(function (item) {
        html += '<div class="ce-nav-item" data-screen="' + item.id + '" role="button" tabindex="0">' +
          '<span class="ce-nav-item__icon">' + item.icon + '</span>' +
          '<span class="ce-nav-item__name">' + item.name + '</span>' +
        '</div>';
      });
      html += '</div>';
    });
    sidebar.innerHTML = html;
    // Wire up clicks
    sidebar.querySelectorAll('.ce-nav-item').forEach(function (item) {
      item.addEventListener('click', function () {
        var screenId = item.getAttribute('data-screen');
        navigate(screenId);
      });
    });
  }

  function wireAdvanceDay() {
    var btn = document.getElementById('advance-day-btn');
    if (btn && !btn._wired) {
      btn._wired = true;
      btn.addEventListener('click', function () {
        btn.disabled = true;
        window.CE.bridge.advanceDay().then(function () {
          updateTopBar();
          // Mark all OTHER screens as stale (will refresh on next visit)
          var allScreens = ['dashboard', 'roster', 'free_agents', 'fighter_profile', 'event_builder'];
          allScreens.forEach(function (sid) {
            if (sid !== state.activeScreen) state._staleScreens.add(sid);
          });
          if (state.activeScreen === 'dashboard') {
            return window.CE.dashboard.loadAndRender(state.promoId);
          }
          // Other screens: player is reading, don't disrupt their view.
          // Stale flag will refresh on next navigation.
        }).catch(function (err) {
          console.error('[app] advanceDay failed:', err);
        }).then(function () {
          btn.disabled = false;
        });
      });
      btn.disabled = false;
    }
    // Phase F2.2 — wire Sim Week + Skip to Show buttons.
    wireSimWeek();
    wireSkipToShow();
    // P5.2 — wire the Save Game button (top bar, next to Advance Day).
    wireSaveButton();
  }

  // ============================================================
  // P5.2 — SAVE GAME (top-bar button → save-name modal)
  // ============================================================
  // On click: opens a modal asking for a save name (default:
  // "Empire YYYY-MM-DD" pre-filled from the sim clock). On submit:
  // calls bridge.saveGame(name) → toast "Game saved as [name]". On
  // cancel: closes the modal, no DB write. The auto_save on close
  // still fires (so even without clicking Save, the player's session
  // is preserved in 'exit_save').
  function wireSaveButton() {
    var btn = document.getElementById('save-game-btn');
    if (!btn || btn._wired) return;
    btn._wired = true;
    btn.addEventListener('click', function () {
      openSaveModal();
    });
  }

  function _defaultSaveName() {
    // Pre-fill with "Empire YYYY-MM-DD" so the player has a sensible
    // default if they don't type one.
    var dateEl = document.getElementById('top-bar-date');
    var dateStr = dateEl ? (dateEl.textContent || '').trim() : '';
    // The top-bar-date renders like "August 27, 2026" — extract the
    // YYYY-MM-DD by parsing the components. Fall back to today's
    // locale date if parsing fails.
    var m = dateStr.match(/(\w+)\s+(\d+),?\s+(\d+)/);
    if (m) {
      var months = ['January','February','March','April','May','June',
                    'July','August','September','October','November','December'];
      var mi = months.indexOf(m[1]) + 1;
      if (mi > 0) {
        var day = String(m[2]).padStart(2, '0');
        var mon = String(mi).padStart(2, '0');
        return 'Empire_' + m[3] + '-' + mon + '-' + day;
      }
    }
    return 'Empire';
  }

  function openSaveModal() {
    closeModal();  // defensive — close any existing modal first
    var overlay = document.createElement('div');
    overlay.className = 'ce-modal-overlay ce-save-modal-overlay';
    overlay.id = 'ce-save-modal';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'ce-save-modal-title');
    var defaultName = _defaultSaveName();
    overlay.innerHTML = '<div class="ce-modal-dialog ce-save-modal">' +
      '<div class="ce-modal-header">' +
        '<div class="ce-modal-title" id="ce-save-modal-title">SAVE EMPIRE</div>' +
        '<button class="ce-modal-close" id="ce-save-modal-close" type="button" aria-label="Cancel">×</button>' +
      '</div>' +
      '<div class="ce-modal-body">' +
        '<label class="ce-save-modal__label" for="ce-save-modal-input">Save name</label>' +
        '<input type="text" id="ce-save-modal-input" class="ce-save-modal__input" ' +
          'maxlength="40" placeholder="Empire_2026-08-27" value="' + escapeHtml(defaultName) + '" />' +
        '<div class="ce-save-modal__hint">Only letters, numbers, underscores, and hyphens. ' +
          'Other characters will be replaced with underscores.</div>' +
        '<div class="ce-save-modal__actions">' +
          '<button class="ce-btn ce-btn-ghost" id="ce-save-modal-cancel" type="button">Cancel</button>' +
          '<button class="ce-btn ce-btn-primary" id="ce-save-modal-submit" type="button">💾 Save</button>' +
        '</div>' +
        '<div class="ce-save-modal__status" id="ce-save-modal-status"></div>' +
      '</div>' +
    '</div>';
    document.body.appendChild(overlay);

    var input = document.getElementById('ce-save-modal-input');
    if (input) {
      // Select-all so the player can immediately type a new name.
      setTimeout(function () { input.focus(); input.select(); }, 30);
      input.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter') {
          evt.preventDefault();
          submitSave();
        } else if (evt.key === 'Escape') {
          evt.preventDefault();
          closeModal();
        }
      });
    }
    var closeBtn = document.getElementById('ce-save-modal-close');
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    var cancelBtn = document.getElementById('ce-save-modal-cancel');
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
    var submitBtn = document.getElementById('ce-save-modal-submit');
    if (submitBtn) submitBtn.addEventListener('click', submitSave);
    overlay.addEventListener('click', function (evt) {
      if (evt.target === overlay) closeModal();
    });

    function submitSave() {
      var rawName = (input && input.value || '').trim();
      if (!rawName) {
        showSaveStatus('Please enter a save name.', 'error');
        return;
      }
      if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Saving…'; }
      window.CE.bridge.saveGame(rawName).then(function (result) {
        if (result && result.ok) {
          var savedName = result.name || rawName;
          closeModal();
          showToast('Game saved as ' + savedName + '.');
        } else {
          showSaveStatus('Save failed: ' + (result && result.error ? result.error : 'unknown'), 'error');
          if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '💾 Save'; }
        }
      }).catch(function (err) {
        showSaveStatus('Save failed: ' + String(err), 'error');
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '💾 Save'; }
      });
    }
    function showSaveStatus(msg, kind) {
      var s = document.getElementById('ce-save-modal-status');
      if (s) {
        s.textContent = msg;
        s.className = 'ce-save-modal__status' + (kind === 'error' ? ' ce-save-modal__status--error' : '');
      }
    }
  }

  // ============================================================
  // P5.2 — LOAD GAME (pre-game button → save-slots modal)
  // ============================================================
  // On click: calls bridge.listSaves() → opens a modal listing every
  // save with name, sim_date, promotion, cash, fighter count, age
  // (timestamp). Player clicks a row → bridge.loadGame(name) → on
  // success: location.reload() so init() runs against the freshly
  // loaded DB.
  function wireLoadButton() {
    var btn = document.getElementById('pregame-load-btn');
    if (!btn || btn._wired) return;
    btn._wired = true;
    btn.addEventListener('click', function () {
      openLoadModal();
    });
  }

  function openLoadModal() {
    closeModal();
    var overlay = document.createElement('div');
    overlay.className = 'ce-modal-overlay ce-load-modal-overlay';
    overlay.id = 'ce-load-modal';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'ce-load-modal-title');
    overlay.innerHTML = '<div class="ce-modal-dialog ce-load-modal">' +
      '<div class="ce-modal-header">' +
        '<div class="ce-modal-title" id="ce-load-modal-title">LOAD EMPIRE</div>' +
        '<button class="ce-modal-close" id="ce-load-modal-close" type="button" aria-label="Close">×</button>' +
      '</div>' +
      '<div class="ce-modal-body">' +
        '<div class="ce-load-modal__loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Reading saves…</div></div>' +
      '</div>' +
    '</div>';
    document.body.appendChild(overlay);
    var closeBtn = document.getElementById('ce-load-modal-close');
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    overlay.addEventListener('click', function (evt) {
      if (evt.target === overlay) closeModal();
    });
    document.addEventListener('keydown', _loadModalEscClose);

    window.CE.bridge.listSaves().then(function (result) {
      var saves = (result && result.saves) || [];
      renderLoadModalBody(saves);
    }).catch(function (err) {
      renderLoadModalError(String(err));
    });
  }

  function _loadModalEscClose(evt) {
    if (evt.key === 'Escape') {
      closeModal();
      document.removeEventListener('keydown', _loadModalEscClose);
    }
  }

  function renderLoadModalBody(saves) {
    var body = document.querySelector('#ce-load-modal .ce-modal-body');
    if (!body) return;
    if (!saves.length) {
      body.innerHTML = '<div class="ce-load-modal__empty">' +
        '<div class="ce-load-modal__empty-icon">📂</div>' +
        '<div class="ce-load-modal__empty-title">No saved empires found.</div>' +
        '<div class="ce-load-modal__empty-body">Start a new game — pick a promotion above. ' +
          'Your progress is auto-saved as "exit_save" when you close the app.</div>' +
      '</div>';
      return;
    }
    var html = '<div class="ce-load-modal__list">';
    saves.forEach(function (s) {
      var ts = s.timestamp ? _formatSaveDate(s.timestamp) : '';
      var simDate = s.sim_date || '—';
      var promo = s.promotion || 'Unknown promotion';
      var cash = (s.cash != null) ? _formatCashShort(s.cash) : '—';
      var fighters = (s.fighters != null) ? s.fighters + ' fighters' : '';
      var events = (s.events != null) ? s.events + ' events' : '';
      var autosaveBadge = s.is_autosave ? '<span class="ce-load-modal__autosave">AUTO</span>' : '';
      html += '<div class="ce-load-modal__row" data-load-name="' + escapeHtml(s.name) + '" role="button" tabindex="0">' +
        '<div class="ce-load-modal__row-main">' +
          '<div class="ce-load-modal__row-name">' + escapeHtml(s.name) + autosaveBadge + '</div>' +
          '<div class="ce-load-modal__row-meta">' +
            '<span class="ce-load-modal__row-promo">' + escapeHtml(promo) + '</span>' +
            '<span class="ce-load-modal__row-sep">·</span>' +
            '<span>' + escapeHtml(simDate) + '</span>' +
            (cash !== '—' ? '<span class="ce-load-modal__row-sep">·</span>' +
              '<span class="ce-load-modal__row-cash">' + escapeHtml(cash) + '</span>' : '') +
            (fighters ? '<span class="ce-load-modal__row-sep">·</span><span>' + escapeHtml(fighters) + '</span>' : '') +
            (events ? '<span class="ce-load-modal__row-sep">·</span><span>' + escapeHtml(events) + '</span>' : '') +
          '</div>' +
        '</div>' +
        '<div class="ce-load-modal__row-ts">' + escapeHtml(ts) + '</div>' +
      '</div>';
    });
    html += '</div>';
    body.innerHTML = html;

    body.querySelectorAll('[data-load-name]').forEach(function (row) {
      row.addEventListener('click', function () {
        var name = row.getAttribute('data-load-name');
        onLoadSaveClick(name, row);
      });
      row.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault();
          var name = row.getAttribute('data-load-name');
          onLoadSaveClick(name, row);
        }
      });
    });
  }

  function onLoadSaveClick(name, row) {
    if (!name) return;
    if (!confirm('Load "' + name + '"? Any unsaved progress in the current session will be lost.')) return;
    // Mark the row as loading.
    if (row) {
      row.classList.add('ce-load-modal__row--loading');
      var allRows = document.querySelectorAll('[data-load-name]');
      allRows.forEach(function (r) {
        if (r !== row) r.classList.add('ce-load-modal__row--disabled');
      });
    }
    window.CE.bridge.loadGame(name).then(function (result) {
      if (result && result.ok) {
        // The DB file has been replaced + self.conn swapped. Reload
        // so init() runs against the loaded state.
        if (window && window.location && window.location.reload) {
          window.location.reload();
        }
      } else {
        if (row) row.classList.remove('ce-load-modal__row--loading');
        var body = document.querySelector('#ce-load-modal .ce-modal-body');
        if (body) {
          var errDiv = document.createElement('div');
          errDiv.className = 'ce-error-banner';
          errDiv.innerHTML = '<div class="ce-error-banner__title">Load failed</div>' +
            '<div>' + escapeHtml(result && result.error ? result.error : 'unknown') + '</div>';
          body.prepend(errDiv);
        }
      }
    }).catch(function (err) {
      if (row) row.classList.remove('ce-load-modal__row--loading');
      console.error('[app.loadGame] failed:', err);
    });
  }

  function renderLoadModalError(msg) {
    var body = document.querySelector('#ce-load-modal .ce-modal-body');
    if (!body) return;
    body.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Could not list saves</div>' +
      '<div>' + escapeHtml(msg) + '</div></div>';
  }

  function _formatSaveDate(isoTs) {
    // isoTs looks like "2026-08-27T14:32:11" — format as
    // "Aug 27, 14:32". Defensive — fall back to the raw string.
    if (!isoTs) return '';
    try {
      var parts = isoTs.split('T');
      var dParts = parts[0].split('-');
      var tParts = (parts[1] || '').split(':');
      var months = ['Jan','Feb','Mar','Apr','May','Jun',
                    'Jul','Aug','Sep','Oct','Nov','Dec'];
      var mi = parseInt(dParts[1], 10) - 1;
      var day = parseInt(dParts[2], 10);
      var hh = tParts[0] || '00';
      var mm = tParts[1] || '00';
      if (mi >= 0 && mi < 12 && day) {
        return months[mi] + ' ' + day + ', ' + hh + ':' + mm;
      }
    } catch (e) {}
    return isoTs;
  }

  function _formatCashShort(n) {
    n = Number(n || 0);
    var neg = n < 0;
    var abs = Math.abs(n);
    var s;
    if (abs >= 1e6) s = '$' + (abs / 1e6).toFixed(1) + 'M';
    else if (abs >= 1e3) s = '$' + (abs / 1e3).toFixed(0) + 'K';
    else s = '$' + Math.round(abs);
    return (neg ? '-' : '') + s;
  }

  // ============================================================
  // P5.2 — modal helpers (shared by Save + Load modals)
  // ============================================================
  function closeModal() {
    var ids = ['ce-save-modal', 'ce-load-modal'];
    ids.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.remove();
    });
    document.removeEventListener('keydown', _loadModalEscClose);
  }

  // ============================================================
  // Phase F2.2 — PROCESSING OVERLAY (Sim Week + Skip to Show)
  // ============================================================
  // Both buttons open a full-screen overlay that:
  //   1. Tells the player the sim is processing (so they don't think
  //      the app froze — run_tick can take 1-2s for 7 days on a 4000-
  //      fighter world DB).
  //   2. Cycles a random fighter profile snapshot every ~3s for
  //      visual interest (per the spec: "snapshot a random fighter
  //      profile every minute" — 3s is more responsive for a 7-day
  //      sim that completes in ~2s).
  // The overlay hides when the Python call returns; the top bar
  // refreshes with the new sim date + the current screen re-renders.

  function showProcessingOverlay(progressText) {
    var overlay = document.getElementById('ce-processing-overlay');
    if (!overlay) return;
    var progressEl = document.getElementById('ce-processing-overlay__progress');
    if (progressEl && progressText) progressEl.textContent = progressText;
    overlay.classList.add('ce-processing-overlay--visible');
    overlay.setAttribute('aria-hidden', 'false');
    // Start the random-fighter-snapshot cycle.
    startFighterSnapshotCycle();
  }

  function hideProcessingOverlay() {
    var overlay = document.getElementById('ce-processing-overlay');
    if (!overlay) return;
    overlay.classList.remove('ce-processing-overlay--visible');
    overlay.setAttribute('aria-hidden', 'true');
    stopFighterSnapshotCycle();
  }

  function updateProcessingProgress(text) {
    var progressEl = document.getElementById('ce-processing-overlay__progress');
    if (progressEl && text) progressEl.textContent = text;
  }

  // ---- Random fighter snapshot cycle ------------------------------
  // Every ~3s, fetch a random fighter_id from the player's promo +
  // render a small profile card in the overlay. Keeps the overlay
  // visually alive while the sim ticks (otherwise it would just be
  // a static spinner). The cycle stops when the overlay hides.
  var _fighterSnapshotTimer = null;
  var _fighterSnapshotInFlight = false;

  function startFighterSnapshotCycle() {
    stopFighterSnapshotCycle();  // defensive — clear any prior timer
    // Fire one immediately so the overlay doesn't show the placeholder
    // for 10 seconds (not 3 — that was way too fast).
    fetchFighterSnapshot();
    _fighterSnapshotTimer = setInterval(fetchFighterSnapshot, 10000);
  }

  function stopFighterSnapshotCycle() {
    if (_fighterSnapshotTimer) {
      clearInterval(_fighterSnapshotTimer);
      _fighterSnapshotTimer = null;
    }
    _fighterSnapshotInFlight = false;
  }

  function fetchFighterSnapshot() {
    if (_fighterSnapshotInFlight) return;
    _fighterSnapshotInFlight = true;
    window.CE.bridge.getRandomFighterId().then(function (resp) {
      if (!resp || !resp.fighter_id) {
        renderFighterSnapshotEmpty();
        return;
      }
      return window.CE.bridge.getFighterProfileData(resp.fighter_id);
    }).then(function (profile) {
      if (profile) renderFighterSnapshot(profile);
    }).catch(function (err) {
      // Silent fail — the overlay's primary job is to tell the player
      // the sim is processing. A failed snapshot fetch is a minor
      // cosmetic issue, not worth surfacing.
      console.warn('[app] fighter snapshot failed:', err);
    }).then(function () {
      _fighterSnapshotInFlight = false;
    });
  }

  function renderFighterSnapshot(profile) {
    var host = document.getElementById('ce-processing-overlay__fighter');
    if (!host) return;
    var h = (profile && profile.header) || {};
    var cs = (profile && profile.career_stats) || {};
    var bio = (profile && profile.bio) || {};
    var identity = h.identity_strip || {};
    var name = h.name || 'Unknown fighter';
    var nickname = h.nickname ? ' "' + h.nickname + '"' : '';
    // P-FIX: richer fighter bio — weight class, height, country, record, style, bio excerpt
    var meta = [];
    if (h.wc_name) meta.push(h.wc_name);
    if (h.age) meta.push(h.age + 'y');
    if (h.style_name && h.style_name !== '—') meta.push(h.style_name);
    if (cs.record_str) meta.push(cs.record_str);
    if (h.nat_code && h.nat_code !== '—') meta.push(h.nat_code);
    var momentum = identity.momentum || {};
    var phrase = momentum.short || momentum.long ||
                 h.overall_desc || '';
    var bioText = bio.bio_text || '';
    if (bioText.length > 120) bioText = bioText.substring(0, 117) + '…';
    host.innerHTML =
      '<div style="flex:1;min-width:0">' +
        '<div class="ce-processing-overlay__fighter-name">' +
          escapeHtml(name) + '<span style="color:var(--text-secondary);font-weight:400">' + escapeHtml(nickname) + '</span>' +
        '</div>' +
        (meta.length
          ? '<div class="ce-processing-overlay__fighter-meta">' + escapeHtml(meta.join(' · ')) + '</div>'
          : '') +
        (phrase
          ? '<div class="ce-processing-overlay__fighter-phrase">' + escapeHtml(phrase) + '</div>'
          : '') +
        (bioText
          ? '<div class="ce-processing-overlay__fighter-bio">' + escapeHtml(bioText) + '</div>'
          : '') +
      '</div>';
  }

  function renderFighterSnapshotEmpty() {
    var host = document.getElementById('ce-processing-overlay__fighter');
    if (!host) return;
    host.innerHTML = '<div class="ce-processing-overlay__fighter-placeholder">No fighters on the roster yet.</div>';
  }

  function wireSimWeek() {
    var btn = document.getElementById('sim-week-btn');
    if (btn && !btn._wired) {
      btn._wired = true;
      btn.addEventListener('click', function () {
        if (btn.disabled) return;
        setAdvanceButtonsDisabled(true);
        showProcessingOverlay('Simulating 7 days…');
        // P-FIX: process one day at a time so the Cancel button works.
        // The Python advance_days is synchronous + blocking — we can't
        // interrupt it mid-call. But by calling advance_days(1) seven
        // times, the Cancel button can take effect between calls.
        var day = 0;
        var totalDays = 7;
        var cancelled = false;
        var cancelBtn = document.getElementById('ce-processing-overlay__cancel');
        if (cancelBtn) {
          cancelBtn.onclick = function () {
            cancelled = true;
            updateProcessingProgress('Cancelling after day ' + day + '…');
          };
        }

        function processNextDay() {
          if (cancelled || day >= totalDays) {
            // Done (or cancelled) — refresh + hide overlay.
            updateProcessingProgress(cancelled ? 'Cancelled after ' + day + ' days.' : 'Done — refreshing…');
            updateTopBar();
            refreshActiveScreenAfterSim().then(function () {
              hideProcessingOverlay();
              setAdvanceButtonsDisabled(false);
              if (cancelled) showToast('Sim cancelled after ' + day + ' days.');
            }).catch(function () {
              hideProcessingOverlay();
              setAdvanceButtonsDisabled(false);
            });
            return;
          }
          day++;
          updateProcessingProgress('Day ' + day + ' of ' + totalDays + '…');
          window.CE.bridge.advanceDays(1).then(function (resp) {
            if (!resp || !resp.ok) {
              showToast('Sim failed on day ' + day + ': ' + (resp && resp.error ? resp.error : 'unknown'));
              hideProcessingOverlay();
              setAdvanceButtonsDisabled(false);
              return;
            }
            // Update the top bar date so the player sees it changing.
            if (resp.new_date) {
              var dateEl = document.getElementById('top-bar-date');
              if (dateEl && resp.clock) {
                // P-FIX: extract day-of-month from current_date, not current_day (which is day-of-year)
                var dayOfMonth = '';
                if (resp.clock.current_date) {
                  var parts = resp.clock.current_date.split('-');
                  if (parts.length >= 3) dayOfMonth = parseInt(parts[2], 10);
                }
                var dayStr = dayOfMonth ? (dayOfMonth + ', ') : '';
                dateEl.textContent = (resp.clock.month_name || '') + ' ' + dayStr + (resp.clock.current_year || '');
              }
            }
            // Schedule the next day on a microtask so the UI can repaint.
            setTimeout(processNextDay, 10);
          }).catch(function (err) {
            console.error('[app] sim day failed:', err);
            showToast('Sim failed: ' + (err && err.message ? err.message : String(err)));
            hideProcessingOverlay();
            setAdvanceButtonsDisabled(false);
          });
        }
        processNextDay();
      });
      btn.disabled = false;
    }
  }

  function wireSkipToShow() {
    var btn = document.getElementById('skip-to-show-btn');
    if (btn && !btn._wired) {
      btn._wired = true;
      btn.addEventListener('click', function () {
        if (btn.disabled) return;
        setAdvanceButtonsDisabled(true);
        showProcessingOverlay('Finding your next show…');
        // P-FIX: first call advanceToNextShow to get the target date +
        // day count, then advance one day at a time so the date
        // changes are visible + Cancel works.
        window.CE.bridge.advanceToNextShow().then(function (resp) {
          if (!resp || !resp.ok) {
            var errMsg = (resp && resp.error) || 'unknown error';
            showToast('Skip to Show failed: ' + errMsg);
            hideProcessingOverlay();
            setAdvanceButtonsDisabled(false);
            return;
          }
          if (resp.days_advanced === 0) {
            if (resp.message) {
              showToast(resp.message + ' Schedule an event first via Stack a Card.');
            } else {
              showToast('No scheduled events. Use Stack a Card to create one.');
            }
            hideProcessingOverlay();
            setAdvanceButtonsDisabled(false);
            return;
          }
          // The Python call already advanced all days. Just update
          // the UI + show the result.
          updateProcessingProgress('Arrived at show day — refreshing…');
          updateTopBar();
          return refreshActiveScreenAfterSim().then(function () {
            if (resp.event_id) {
              showToast("It's show day! Click 'Watch the Show' on the Dashboard.");
            }
          });
        }).catch(function (err) {
          console.error('[app] skip to show failed:', err);
          showToast('Skip to Show failed: ' + (err && err.message ? err.message : String(err)));
        }).then(function () {
          hideProcessingOverlay();
          setAdvanceButtonsDisabled(false);
        });
      });
      btn.disabled = false;
    }
  }

  function setAdvanceButtonsDisabled(disabled) {
    var ids = ['advance-day-btn', 'sim-week-btn', 'skip-to-show-btn'];
    ids.forEach(function (id) {
      var b = document.getElementById(id);
      if (b) b.disabled = disabled;
    });
  }

  function refreshActiveScreenAfterSim() {
    // After a multi-day sim, the current screen's data is stale.
    // Re-render it. The dashboard + matchmaking have explicit
    // reload functions; other screens just re-navigate.
    var active = state.activeScreen;
    if (active === 'dashboard' && window.CE.dashboard) {
      return window.CE.dashboard.loadAndRender(state.promoId);
    }
    if (active === 'matchmaking' && window.CE.matchmaking && state.activeParams.event_id) {
      return window.CE.matchmaking.loadAndRender(state.activeParams.event_id);
    }
    // Default: re-trigger navigate() to the current screen (forces
    // a fresh data fetch + render). The nav stack is preserved (we
    // don't push the current screen onto it twice — see navigate()).
    if (active) {
      navigate(active, state.activeParams);
    }
    return Promise.resolve();
  }

  function showToast(msg) {
    // Simple toast — reuses the matchmaking.js pattern. Falls back
    // to console.warn if no host element exists.
    var host = document.getElementById('screen-content') || document.body;
    if (!host) { console.warn('[toast]', msg); return; }
    var toast = document.createElement('div');
    toast.className = 'ce-toast ce-toast--info';
    toast.style.cssText = 'position:fixed;bottom:24px;right:24px;background:var(--bg-surface);' +
      'border:1px solid var(--gold);border-left:3px solid var(--gold);' +
      'padding:12px 16px;border-radius:var(--r-md);box-shadow:0 6px 20px rgba(0,0,0,0.3);' +
      'font-family:var(--font-serif);font-style:italic;font-size:13px;color:var(--text-primary);' +
      'max-width:360px;z-index:10000;';
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 5000);
  }

  function updateSidebarActive() {
    var items = document.querySelectorAll('.ce-nav-item');
    items.forEach(function (item) {
      if (item.getAttribute('data-screen') === state.activeScreen) {
        item.classList.add('ce-nav-item--active');
      } else {
        item.classList.remove('ce-nav-item--active');
      }
    });
  }

  function updateTopBar() {
    window.CE.bridge.getClock().then(function (clock) {
      if (!clock) return;
      var dateEl = document.getElementById('top-bar-date');
      if (dateEl) {
        // P-FIX: current_day is day-of-YEAR (1-365), NOT day-of-month.
        // Extract day-of-month from current_date string (YYYY-MM-DD).
        var dayOfMonth = '';
        if (clock.current_date) {
          var parts = clock.current_date.split('-');
          if (parts.length >= 3) dayOfMonth = parseInt(parts[2], 10);
        }
        var dayStr = dayOfMonth ? (dayOfMonth + ', ') : '';
        dateEl.textContent = (clock.month_name || '') + ' ' + dayStr + (clock.current_year || '');
      }
    }).catch(function () {});

    window.CE.bridge.getPlayerCash().then(function (cash) {
      if (!cash) return;
      var cashEl = document.getElementById('top-bar-cash');
      if (cashEl) {
        cashEl.textContent = cash.cash_display || '';
        cashEl.classList.toggle('ce-top-bar__cash--negative', cash.is_negative);
      }
    }).catch(function () {});
  }

  // ============================================================
  // NAVIGATION
  // ============================================================

  /**
   * Navigate to a screen, pushing the current screen onto the back
   * stack. Accepts a params object (e.g. {fighter_id: 48}) so screens
   * like Fighter Profile can be opened for a specific fighter.
   *
   * Per NAV_BUTTONS_AUDIT §5.4: ported from ui_legacy/state.py:92 —
   * stack caps at 10 entries, FIFO overflow.
   */
  function navigate(screenId, params) {
    params = params || {};
    // Push current screen onto back stack (only if different)
    if (state.activeScreen && state.activeScreen !== screenId) {
      state._navStack.push({
        screen: state.activeScreen,
        params: state.activeParams || {},
      });
      if (state._navStack.length > 10) state._navStack.shift();
    }
    state.activeScreen = screenId;
    state.activeParams = params;
    updateSidebarActive();
    window.CE.bridge.clearErrors();

    // Clear stale-screen flag (we're refreshing it now)
    state._staleScreens.delete(screenId);

    if (screenId === 'dashboard') {
      window.CE.dashboard.loadAndRender(state.promoId).catch(function () {});
      return;
    }
    // MM2 — Calendar screen (was a placeholder before this phase).
    if (screenId === 'schedule') {
      if (window.CE.calendar) {
        window.CE.calendar.loadAndRender().catch(function () {});
        return;
      }
    }
    // INFO-SCREENS-BATCH-1 — The Wire (news feed).
    if (screenId === 'news') {
      if (window.CE.wire) {
        window.CE.wire.loadAndRender().catch(function () {});
        return;
      }
    }
    // INFO-SCREENS-BATCH-1 — The Archive (past events).
    if (screenId === 'past_events') {
      if (window.CE.archive) {
        window.CE.archive.loadAndRender().catch(function () {});
        return;
      }
    }
    // INFO-SCREENS-BATCH-1 — The Rankings.
    if (screenId === 'rankings') {
      if (window.CE.rankings) {
        window.CE.rankings.loadAndRender().catch(function () {});
        return;
      }
    }
    // INFO-SCREENS-BATCH-1 — Belts (titles).
    if (screenId === 'titles') {
      if (window.CE.titles) {
        window.CE.titles.loadAndRender().catch(function () {});
        return;
      }
    }
    // Task FIGHT-NIGHT-SHOWCASE — Fight Night (live play-by-play).
    // Supports params: {event_id: X} (live mode — opens Fight Night
    // with the player's scheduled event, resolves on Start Fight) or
    // {fight_id: Y} (replay mode — reads existing beats) or no params
    // (shows the next unresolved fight on the player's promo).
    if (screenId === 'fight_resolution') {
      if (window.CE.fightNight) {
        window.CE.fightNight.loadAndRender();
        return;
      }
    }
    if (screenId === 'roster') {
      if (window.CE.roster) {
        window.CE.roster.loadAndRender(state.promoId).catch(function () {});
        return;
      }
    }
    if (screenId === 'free_agents') {
      if (window.CE.freeAgents) {
        // Phase M3.2 — pass navigation params so the Free Agents
        // screen can pre-select a fighter + flag the bidding-alert
        // flow (uses counterOffer instead of signFreeAgent).
        if (params && params.fighter_id) {
          window.CE.freeAgents.loadAndRenderWithBiddingAlert(
            params.fighter_id
          ).catch(function () {});
        } else {
          window.CE.freeAgents.loadAndRender().catch(function () {});
        }
        return;
      }
    }
    if (screenId === 'rival_promotions') {
      if (window.CE.rivalPromotions) {
        window.CE.rivalPromotions.loadAndRender().catch(function () {});
        return;
      }
    }
    if (screenId === 'event_builder') {
      if (window.CE.eventBuilder) {
        window.CE.eventBuilder.loadAndRender().catch(function () {});
        return;
      }
    }
    // Phase M4 — Matchmaking screen.
    if (screenId === 'matchmaking') {
      if (window.CE.matchmaking) {
        var mmEventId = params.event_id || params.eventId || null;
        window.CE.matchmaking.loadAndRender(mmEventId).catch(function () {});
        return;
      }
    }
    // Phase E4 — Staff Market screen.
    if (screenId === 'staff_market') {
      if (window.CE.staffMarket) {
        window.CE.staffMarket.loadAndRender().catch(function () {});
        return;
      }
    }
    // P1-WIRE-4-SCREENS — Bad Blood (Rivalries).
    if (screenId === 'rivalries') {
      if (window.CE.rivalries) {
        window.CE.rivalries.loadAndRender().catch(function () {});
        return;
      }
    }
    // P1-WIRE-4-SCREENS — Legends (Hall of Fame).
    if (screenId === 'hall_of_fame') {
      if (window.CE.hof) {
        window.CE.hof.loadAndRender().catch(function () {});
        return;
      }
    }
    // P1-WIRE-4-SCREENS — Scouting.
    if (screenId === 'scouting') {
      if (window.CE.scouting) {
        window.CE.scouting.loadAndRender().catch(function () {});
        return;
      }
    }
    // P3-AGENT-OFFERS — Agent Offers (mystery-box talent signing).
    if (screenId === 'agent_offers') {
      if (window.CE.agentOffers) {
        window.CE.agentOffers.loadAndRender().catch(function () {});
        return;
      }
    }
    // P1-WIRE-4-SCREENS — Training Camps (Gyms).
    if (screenId === 'gyms') {
      if (window.CE.gyms) {
        window.CE.gyms.loadAndRender().catch(function () {});
        return;
      }
    }
    // P2-FINANCE-CONTRACTS — The Books (finance screen).
    if (screenId === 'finance') {
      if (window.CE.finance) {
        window.CE.finance.loadAndRender().catch(function () {});
        return;
      }
    }
    // P2-FINANCE-CONTRACTS — Deals (contracts screen).
    if (screenId === 'contracts') {
      if (window.CE.contracts) {
        window.CE.contracts.loadAndRender().catch(function () {});
        return;
      }
    }
    // P4-RECORD-BOOK — The Record Book (all-time leaders).
    if (screenId === 'records') {
      if (window.CE.records) {
        window.CE.records.loadAndRender().catch(function () {});
        return;
      }
    }
    if (screenId === 'fighter_profile') {
      if (window.CE.fighterProfile) {
        var fid = params.fighter_id || params.fighterId;
        if (fid) {
          window.CE.fighterProfile.loadAndRender(fid).catch(function () {});
          return;
        }
      }
    }

    // Placeholder for not-yet-implemented screens
    var meta = null;
    for (var i = 0; i < NAV_GROUPS.length; i++) {
      for (var j = 0; j < NAV_GROUPS[i].items.length; j++) {
        if (NAV_GROUPS[i].items[j].id === screenId) {
          meta = NAV_GROUPS[i].items[j];
          break;
        }
      }
    }
    var phrase = PLACEHOLDER_PHRASES[screenId] || { title: (meta ? meta.name : screenId) + ' is coming soon.', body: 'This screen will be implemented in a future phase.' };
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-placeholder">' +
        '<div class="ce-placeholder__icon">' + (meta ? meta.icon : '•') + '</div>' +
        '<div class="ce-placeholder__title">' + escapeHtml(phrase.title) + '</div>' +
        '<div class="ce-placeholder__body">' + escapeHtml(phrase.body) + '</div>' +
      '</div>';
    }
  }

  /**
   * Navigate back to the previous screen. Pops the back stack.
   * If the stack is empty, falls back to the Dashboard.
   */
  function navigateBack() {
    if (!state._navStack.length) {
      return navigate('dashboard');
    }
    var prev = state._navStack.pop();
    // Render directly without pushing the current screen back onto the stack.
    state.activeScreen = prev.screen;
    state.activeParams = prev.params;
    updateSidebarActive();
    window.CE.bridge.clearErrors();
    state._staleScreens.delete(prev.screen);

    if (prev.screen === 'dashboard') {
      window.CE.dashboard.loadAndRender(state.promoId).catch(function () {});
      return;
    }
    // MM2 — Calendar screen back-navigation.
    if (prev.screen === 'schedule' && window.CE.calendar) {
      window.CE.calendar.loadAndRender().catch(function () {});
      return;
    }
    // INFO-SCREENS-BATCH-1 — The Wire back-navigation.
    if (prev.screen === 'news' && window.CE.wire) {
      window.CE.wire.loadAndRender().catch(function () {});
      return;
    }
    // INFO-SCREENS-BATCH-1 — The Archive back-navigation.
    if (prev.screen === 'past_events' && window.CE.archive) {
      window.CE.archive.loadAndRender().catch(function () {});
      return;
    }
    // INFO-SCREENS-BATCH-1 — The Rankings back-navigation.
    if (prev.screen === 'rankings' && window.CE.rankings) {
      window.CE.rankings.loadAndRender().catch(function () {});
      return;
    }
    // INFO-SCREENS-BATCH-1 — Belts back-navigation.
    if (prev.screen === 'titles' && window.CE.titles) {
      window.CE.titles.loadAndRender().catch(function () {});
      return;
    }
    // Task FIGHT-NIGHT-SHOWCASE — Fight Night back-navigation.
    if (prev.screen === 'fight_resolution' && window.CE.fightNight) {
      window.CE.fightNight.loadAndRender();
      return;
    }
    if (prev.screen === 'roster' && window.CE.roster) {
      window.CE.roster.loadAndRender(state.promoId).catch(function () {});
      return;
    }
    if (prev.screen === 'free_agents' && window.CE.freeAgents) {
      window.CE.freeAgents.loadAndRender().catch(function () {});
      return;
    }
    if (prev.screen === 'rival_promotions' && window.CE.rivalPromotions) {
      window.CE.rivalPromotions.loadAndRender().catch(function () {});
      return;
    }
    if (prev.screen === 'event_builder' && window.CE.eventBuilder) {
      window.CE.eventBuilder.loadAndRender().catch(function () {});
      return;
    }
    // Phase M4 — Matchmaking back-navigation.
    if (prev.screen === 'matchmaking' && window.CE.matchmaking) {
      var mmEventId = prev.params.event_id || prev.params.eventId || null;
      window.CE.matchmaking.loadAndRender(mmEventId).catch(function () {});
      return;
    }
    // Phase E4 — Staff Market screen.
    if (prev.screen === 'staff_market' && window.CE.staffMarket) {
      window.CE.staffMarket.loadAndRender().catch(function () {});
      return;
    }
    // P1-WIRE-4-SCREENS — Bad Blood (Rivalries) back-navigation.
    if (prev.screen === 'rivalries' && window.CE.rivalries) {
      window.CE.rivalries.loadAndRender().catch(function () {});
      return;
    }
    // P1-WIRE-4-SCREENS — Legends (Hall of Fame) back-navigation.
    if (prev.screen === 'hall_of_fame' && window.CE.hof) {
      window.CE.hof.loadAndRender().catch(function () {});
      return;
    }
    // P1-WIRE-4-SCREENS — Scouting back-navigation.
    if (prev.screen === 'scouting' && window.CE.scouting) {
      window.CE.scouting.loadAndRender().catch(function () {});
      return;
    }
    // P3-AGENT-OFFERS — Agent Offers back-navigation.
    if (prev.screen === 'agent_offers' && window.CE.agentOffers) {
      window.CE.agentOffers.loadAndRender().catch(function () {});
      return;
    }
    // P1-WIRE-4-SCREENS — Training Camps (Gyms) back-navigation.
    if (prev.screen === 'gyms' && window.CE.gyms) {
      window.CE.gyms.loadAndRender().catch(function () {});
      return;
    }
    // P2-FINANCE-CONTRACTS — The Books (finance screen) back-navigation.
    if (prev.screen === 'finance' && window.CE.finance) {
      window.CE.finance.loadAndRender().catch(function () {});
      return;
    }
    // P2-FINANCE-CONTRACTS — Deals (contracts screen) back-navigation.
    if (prev.screen === 'contracts' && window.CE.contracts) {
      window.CE.contracts.loadAndRender().catch(function () {});
      return;
    }
    // P4-RECORD-BOOK — The Record Book back-navigation.
    if (prev.screen === 'records' && window.CE.records) {
      window.CE.records.loadAndRender().catch(function () {});
      return;
    }
    if (prev.screen === 'fighter_profile' && window.CE.fighterProfile) {
      var fid = prev.params.fighter_id || prev.params.fighterId;
      if (fid) {
        window.CE.fighterProfile.loadAndRender(fid).catch(function () {});
        return;
      }
    }
    // Fallback
    navigate('dashboard');
  }

  /**
   * Returns the current navigation params (for screens that need to
   * read them after load).
   */
  function getActiveParams() {
    return state.activeParams || {};
  }

  // ============================================================
  // HELPERS
  // ============================================================
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function formatCash(n) {
    if (n === null || n === undefined) return '$0';
    n = Number(n);
    if (Math.abs(n) >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
    if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return '$' + (n / 1e3).toFixed(0) + 'K';
    return '$' + Math.round(n).toLocaleString();
  }

  // ============================================================
  // INIT
  // ============================================================
  function init() {
    // Wait for pywebview API, then check if a promo is already selected
    window.CE.bridge.ready().then(function () {
      return window.CE.bridge.getPlayerPromotion();
    }).then(function (promoId) {
      if (promoId && promoId > 0) {
        // Already selected — skip pre-game, go straight to dashboard
        state.promoId = promoId;
        var pregame = document.getElementById('ce-pregame');
        var app = document.getElementById('ce-app');
        if (pregame) pregame.style.display = 'none';
        if (app) app.classList.remove('ce-app--hidden');
        buildSidebar();
        wireAdvanceDay();
        updateTopBar();
        navigate('dashboard');
      } else {
        // No promo selected — show pre-game screen
        showPregame();
      }
    }).catch(function (err) {
      // If anything fails, show pre-game (safest fallback)
      console.warn('[app] init failed, showing pre-game:', err);
      showPregame();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  return { navigate: navigate, navigateBack: navigateBack, getActiveParams: getActiveParams, state: state };
})();
