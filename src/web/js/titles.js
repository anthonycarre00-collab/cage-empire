/* ============================================================
   CAGE EMPIRE — Belts Screen ("THE BELTS")
   ============================================================
   Phase INFO-SCREENS-BATCH-1 §4. Replaces the placeholder
   Belts nav item. Renders every title across every promo so
   the player can see who holds the gold — the Discovery +
   Kingmaker reward ("I want that belt too").

   What the player sees:
     - Section header: "THE BELTS" (gold accent) + subtitle
       "Who holds the gold".
     - Grouped by promo: each promo gets a section block with
       its logo + name + champion/vacant count.
     - Player's promo block has a gold border highlight.
     - Title grid: each title is a card showing weight class,
       current champion (portrait + name + clickable →
       Fighter Profile), champion since date, defense count,
       reign voice phrase, OR a "VACANT" state.
     - Voice phrases for reign length: "just won the belt" /
       "long-reigning champion" / "era-defining reign".
     - Voice empty state: "No titles have been contested yet."

   Voice compliance (CONVENTIONS §14):
     - Reign length is a voice phrase, not just a number.
     - No raw fighter attribute numbers — only name + reign
       metadata.
     - Player's promo's titles get a gold border highlight
       (Ownership language).
   ============================================================ */

window.CE = window.CE || {};

window.CE.titles = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    data: null,
    collapsedPromos: {},  // {promo_id: bool} — collapsed by default false
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

  function formatDate(dateStr) {
    if (!dateStr) return '—';
    var parts = dateStr.split('-');
    if (parts.length !== 3) return dateStr;
    var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var m = parseInt(parts[1], 10);
    return (MONTHS[m - 1] || '?') + ' ' + parseInt(parts[2], 10) + ', ' + parts[0];
  }

  /** Short weight-class name (Heavyweight → HW, etc.). */
  function shortWc(name) {
    var map = {
      'Heavyweight': 'HW',
      'Light Heavyweight': 'LHW',
      'Middleweight': 'MW',
      'Welterweight': 'WW',
      'Lightweight': 'LW',
      'Featherweight': 'FW',
      'Bantamweight': 'BW',
      'Flyweight': 'FlyW',
      'Strawweight': 'SW',
      'Atomweight': 'AW',
    };
    return map[name] || (name || '—');
  }

  /** Get the first letter of the fighter's last name (placeholder
   *  portrait initial when no portrait_b64 is available). */
  function initial(name) {
    if (!name) return '?';
    var parts = name.trim().split(/\s+/);
    if (parts.length < 2) return parts[0].charAt(0).toUpperCase();
    return parts[parts.length - 1].charAt(0).toUpperCase();
  }

  // ============================================================
  // RENDER — HEADER STRIP (summary stats)
  // ============================================================
  function renderSummary() {
    var promos = (state.data && state.data.promos) || [];
    var totalTitles = 0;
    var totalHeld = 0;
    var playerHeld = 0;
    var playerTotal = 0;
    promos.forEach(function (p) {
      p.titles.forEach(function (t) {
        totalTitles++;
        if (t.champion) totalHeld++;
        if (p.is_player_promo) {
          playerTotal++;
          if (t.champion) playerHeld++;
        }
      });
    });
    var playerName = (state.data && state.data.player_promo_name) || 'Your Promotion';
    var playerSummary = playerHeld + ' of ' + playerTotal + ' — ' +
      (playerTotal - playerHeld) + ' to capture';

    return '' +
      '<div class="ce-titles__summary">' +
        '<div class="ce-titles__summary-stat">' +
          '<span class="ce-titles__summary-label">TITLES IN PLAY</span>' +
          '<span class="ce-titles__summary-val">' + totalTitles + '</span>' +
        '</div>' +
        '<div class="ce-titles__summary-stat">' +
          '<span class="ce-titles__summary-label">CURRENTLY HELD</span>' +
          '<span class="ce-titles__summary-val">' + totalHeld + '</span>' +
        '</div>' +
        '<div class="ce-titles__summary-stat ce-titles__summary-stat--player">' +
          '<span class="ce-titles__summary-label">' + escapeHtml(playerName.toUpperCase()) + '</span>' +
          '<span class="ce-titles__summary-val ce-titles__summary-val--gold">' + escapeHtml(playerSummary) + '</span>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — PROMO SECTION
  // ============================================================
  function renderPromo(promo) {
    var heldCount = promo.titles.filter(function (t) { return t.champion; }).length;
    var totalCount = promo.titles.length;
    var isCollapsed = !!state.collapsedPromos[promo.promo_id];

    var logo = promo.logo_b64
      ? '<img src="data:image/png;base64,' + promo.logo_b64 + '" class="ce-titles__promo-logo" alt="' + escapeHtml(promo.promo_name) + '" />'
      : '<div class="ce-titles__promo-logo ce-titles__promo-logo--placeholder">' + escapeHtml((promo.promo_name || '?').charAt(0)) + '</div>';

    var playerTag = promo.is_player_promo
      ? '<span class="ce-chip ce-chip-gold ce-titles__player-tag">YOUR PROMO</span>'
      : '';

    var headerClasses = ['ce-titles__promo-header'];
    if (promo.is_player_promo) headerClasses.push('ce-titles__promo-header--player');

    var caret = isCollapsed ? '▸' : '▾';

    var titleCardsHtml = isCollapsed ? '' : promo.titles.map(renderTitleCard).join('');

    return '' +
      '<section class="ce-titles__promo' + (promo.is_player_promo ? ' ce-titles__promo--player' : '') + '">' +
        '<div class="' + headerClasses.join(' ') + '" data-promo-id="' + promo.promo_id + '" role="button" tabindex="0">' +
          '<div class="ce-titles__promo-caret">' + caret + '</div>' +
          logo +
          '<div class="ce-titles__promo-info">' +
            '<div class="ce-titles__promo-name">' + escapeHtml(promo.promo_name) + '</div>' +
            '<div class="ce-titles__promo-meta">' +
              '<span>' + heldCount + ' of ' + totalCount + ' held</span>' +
              '<span class="ce-titles__sep">·</span>' +
              '<span>' + (totalCount - heldCount) + ' vacant</span>' +
            '</div>' +
          '</div>' +
          playerTag +
        '</div>' +
        (isCollapsed ? '' : '<div class="ce-titles__grid">' + titleCardsHtml + '</div>') +
      '</section>';
  }

  // ============================================================
  // RENDER — TITLE CARD
  // ============================================================
  function renderTitleCard(title) {
    var wcShort = shortWc(title.weight_class_name);
    var genderTag = title.weight_class_gender === 'female' ? " <span class='ce-titles__wc-women'>(W)</span>" : '';

    if (!title.champion) {
      // Vacant title.
      return '' +
        '<div class="ce-titles__card ce-titles__card--vacant">' +
          '<div class="ce-titles__card-wc">' +
            '<span class="ce-titles__wc-short">' + escapeHtml(wcShort) + '</span>' +
            '<span class="ce-titles__wc-full">' + escapeHtml(title.weight_class_name) + genderTag + '</span>' +
          '</div>' +
          '<div class="ce-titles__vacant-mark">VACANT</div>' +
          '<div class="ce-titles__vacant-body">The throne sits empty. Run a title fight to claim it.</div>' +
        '</div>';
    }

    var c = title.champion;
    var portrait = c.portrait_b64
      ? '<img src="' + c.portrait_b64 + '" class="ce-titles__portrait" alt="' + escapeHtml(c.name) + '" />'
      : '<div class="ce-titles__portrait ce-titles__portrait--placeholder">' + escapeHtml(initial(c.name)) + '</div>';
    var nickHtml = c.nickname
      ? '<span class="ce-titles__champ-nick"> \'' + escapeHtml(c.nickname) + '\'</span>'
      : '';
    var defensesLabel = c.title_defenses_count === 1 ? 'defense' : 'defenses';
    var reignsLabel = c.title_reigns_count === 1 ? 'reign' : 'reigns';

    return '' +
      '<div class="ce-titles__card">' +
        '<div class="ce-titles__card-wc">' +
          '<span class="ce-titles__wc-short">' + escapeHtml(wcShort) + '</span>' +
          '<span class="ce-titles__wc-full">' + escapeHtml(title.weight_class_name) + genderTag + '</span>' +
        '</div>' +
        '<div class="ce-titles__card-body">' +
          portrait +
          '<div class="ce-titles__champ-info">' +
            '<a class="ce-titles__champ-name ce-link" href="#" data-fighter-id="' +
              c.fighter_id + '">' + escapeHtml(c.name) + '</a>' + nickHtml +
            '<div class="ce-titles__champ-reign">' + escapeHtml(c.reign_voice) + '</div>' +
            '<div class="ce-titles__champ-meta">' +
              '<span class="ce-titles__champ-defs">' + c.title_defenses_count + ' ' + defensesLabel + '</span>' +
              '<span class="ce-titles__sep">·</span>' +
              '<span class="ce-titles__champ-reigns">' + c.title_reigns_count + ' ' + reignsLabel + '</span>' +
              '<span class="ce-titles__sep">·</span>' +
              '<span class="ce-titles__champ-since">since ' + escapeHtml(formatDate(c.champion_since_date)) + '</span>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // MAIN RENDER
  // ============================================================
  function render() {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var promos = (state.data && state.data.promos) || [];
    if (!promos.length) {
      host.innerHTML = '' +
        '<div class="ce-titles">' +
          '<div class="ce-section">' +
            '<div class="ce-sec-header">' +
              '<div class="ce-accent-bar ce-accent-gold"></div>' +
              '<span class="ce-sec-icon">🥇</span>' +
              '<span class="ce-sec-title ce-sec-title-gold">THE BELTS</span>' +
              '<span class="ce-sec-sub ce-mono">who holds the gold</span>' +
            '</div>' +
          '</div>' +
          '<div class="ce-titles__empty">' +
            '<div class="ce-titles__empty-title">No titles have been contested yet.</div>' +
            '<div class="ce-titles__empty-body">Run a title fight to crown your first champion.</div>' +
          '</div>' +
        '</div>';
      return;
    }
    // Sort promos: player's promo first, then by promo_id.
    promos = promos.slice().sort(function (a, b) {
      if (a.is_player_promo !== b.is_player_promo) {
        return a.is_player_promo ? -1 : 1;
      }
      return a.promo_id - b.promo_id;
    });

    var html = '' +
      '<div class="ce-titles">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">🥇</span>' +
            '<span class="ce-sec-title ce-sec-title-gold">THE BELTS</span>' +
            '<span class="ce-sec-sub ce-mono">who holds the gold</span>' +
          '</div>' +
        '</div>' +
        renderSummary() +
        promos.map(renderPromo).join('') +
      '</div>';
    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    // Promo section collapse/expand.
    document.querySelectorAll('.ce-titles__promo-header').forEach(function (hdr) {
      hdr.addEventListener('click', function () {
        var pid = parseInt(hdr.getAttribute('data-promo-id'), 10);
        if (!pid) return;
        state.collapsedPromos[pid] = !state.collapsedPromos[pid];
        render();
      });
      hdr.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault();
          hdr.click();
        }
      });
    });

    // Fighter-name hyperlinks → Fighter Profile.
    document.querySelectorAll('.ce-titles__champ-name[data-fighter-id]').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        evt.stopPropagation();
        var fid = link.getAttribute('data-fighter-id');
        if (fid) window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
      });
    });
  }

  // ============================================================
  // LOAD + RENDER
  // ============================================================
  function loadAndRender() {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Surveying the gold…</div></div>';
    }
    return window.CE.bridge.getTitlesData().then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load titles</div><div>' +
            escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      state.data = data;
      render();
    }).catch(function (err) {
      console.error('[titles] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load titles</div><div>' +
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
