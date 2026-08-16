/* ============================================================
   CAGE EMPIRE — The Record Book Screen ("THE RECORD BOOK")
   ============================================================
   Phase P4 (docs/P3_P4_PLAN.md §P4). Replaces the placeholder
   `records` nav item. The Historian fantasy (Legacy pillar) —
   all-time leaders across the entire sport. The names that echo.

   What the player sees:
     - Section header: "THE RECORD BOOK" (gold accent) + subtitle
       "All-time leaders".
     - Records grid (2-3 columns responsive): each card shows:
       * Record title (e.g. "MOST WINS") — uppercase gold
       * Icon (emoji)
       * Fighter name (clickable → Fighter Profile)
       * Value (big number, e.g. "32")
       * Context phrase (e.g. "32-20-4 career record") — voice
     - Current Champions section: a strip of champion chips (top
       12 by defenses) + the total count. Each chip shows fighter
       name, promo, weight class, reign length, defense count.
       Player's promo champions get a gold accent.
     - Empty state: "The record book is being written. Give it time."

   Voice compliance (CONVENTIONS §14):
     - Career record (W-L-D) is OK as numbers — public career stats,
       not hidden attributes.
     - Age is OK as a number for "oldest/youngest fighter" — age is
       observable public record.
     - Win % is OK as a number — derived career stat.
     - Title reigns + defenses are OK as counts — career achievements.
     - Each record carries a voice "context" phrase so the player
       gets narrative, not just a bare number.
     - No raw potential/attribute numbers ever shown.
   ============================================================ */

window.CE = window.CE || {};

window.CE.records = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    data: null,
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

  /** Tier → CSS accent color class for the card's left border. */
  function tierClass(tier) {
    return 'ce-records__card--' + (tier || 'gold');
  }

  // ============================================================
  // RENDER — RECORDS GRID
  // ============================================================
  function renderRecordCard(r) {
    var nameHtml = '<a class="ce-link ce-records__name" href="#" ' +
      'data-fighter-id="' + r.fighter_id + '">' +
      escapeHtml(r.fighter_name || '—') + '</a>';
    if (r.fighter_nickname) {
      nameHtml += '<span class="ce-records__nick"> \'' +
        escapeHtml(r.fighter_nickname) + '\'</span>';
    }
    return '' +
      '<div class="ce-records__card ' + tierClass(r.tier) + '">' +
        '<div class="ce-records__card-top">' +
          '<span class="ce-records__icon" aria-hidden="true">' +
            escapeHtml(r.icon || '•') +
          '</span>' +
          '<span class="ce-records__title">' +
            escapeHtml(r.title || '—') +
          '</span>' +
        '</div>' +
        '<div class="ce-records__value">' +
          escapeHtml(r.value_display || '—') +
        '</div>' +
        '<div class="ce-records__fighter">' + nameHtml + '</div>' +
        '<div class="ce-records__context">' +
          escapeHtml(r.context || '') +
        '</div>' +
      '</div>';
  }

  function renderRecordsGrid() {
    var records = (state.data && state.data.records) || [];
    if (!records.length) {
      return '' +
        '<div class="ce-records__empty">' +
          '<div class="ce-records__empty-icon" aria-hidden="true">📖</div>' +
          '<div class="ce-records__empty-title">The record book is being written.</div>' +
          '<div class="ce-records__empty-body">' +
            'Give it time. Once the world has seen a few cards, ' +
            'the names that echo will appear here.' +
          '</div>' +
        '</div>';
    }
    return '' +
      '<div class="ce-records__grid">' +
        records.map(renderRecordCard).join('') +
      '</div>';
  }

  // ============================================================
  // RENDER — CURRENT CHAMPIONS STRIP
  // ============================================================
  function renderChampionChip(c) {
    var cls = 'ce-records__champ' + (c.is_player_promo
      ? ' ce-records__champ--player' : '');
    var nickHtml = c.fighter_nickname
      ? '<span class="ce-records__champ-nick">\'' +
        escapeHtml(c.fighter_nickname) + '\'</span>'
      : '';
    var defsLabel = c.title_defenses_count === 1 ? 'defense' : 'defenses';
    return '' +
      '<div class="' + cls + '">' +
        '<div class="ce-records__champ-belt" aria-hidden="true">🥇</div>' +
        '<div class="ce-records__champ-body">' +
          '<a class="ce-link ce-records__champ-name" href="#" ' +
            'data-fighter-id="' + c.fighter_id + '">' +
            escapeHtml(c.fighter_name || '—') +
          '</a>' + nickHtml +
          '<div class="ce-records__champ-meta">' +
            '<span class="ce-records__champ-wc">' +
              escapeHtml(c.weight_class_name || '—') + '</span>' +
            '<span class="ce-records__champ-sep"> · </span>' +
            '<span class="ce-records__champ-promo">' +
              escapeHtml(c.promotion_name || '—') + '</span>' +
          '</div>' +
          '<div class="ce-records__champ-stats">' +
            '<span class="ce-records__champ-reign">' +
              escapeHtml(c.reign_length || '—') + ' reigning</span>' +
            '<span class="ce-records__champ-sep"> · </span>' +
            '<span class="ce-records__champ-defs">' +
              c.title_defenses_count + ' ' + defsLabel + '</span>' +
          '</div>' +
        '</div>' +
      '</div>';
  }

  function renderChampions() {
    var champs = state.data && state.data.champions;
    if (!champs || !champs.count) return '';
    var items = champs.items || [];
    var countText = champs.count + ' champion' +
      (champs.count === 1 ? '' : 's') + ' across the world';
    return '' +
      '<div class="ce-records__champions">' +
        '<div class="ce-records__champions-header">' +
          '<div class="ce-accent-bar ce-accent-gold"></div>' +
          '<span class="ce-records__champions-title">CURRENT CHAMPIONS</span>' +
          '<span class="ce-records__champions-count ce-mono">' +
            escapeHtml(countText) +
          '</span>' +
        '</div>' +
        '<div class="ce-records__champions-grid">' +
          items.map(renderChampionChip).join('') +
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
      '<div class="ce-records">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">📖</span>' +
            '<span class="ce-sec-title ce-sec-title-gold">THE RECORD BOOK</span>' +
            '<span class="ce-records__sub ce-mono">all-time leaders</span>' +
          '</div>' +
        '</div>' +
        renderRecordsGrid() +
        renderChampions() +
      '</div>';
    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    // Fighter-name hyperlinks → Fighter Profile (both record cards +
    // champion chips).
    document.querySelectorAll(
      '.ce-records__name[data-fighter-id], ' +
      '.ce-records__champ-name[data-fighter-id]'
    ).forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        var fid = link.getAttribute('data-fighter-id');
        if (fid && window.CE.app && window.CE.app.navigate) {
          window.CE.app.navigate('fighter_profile', {
            fighter_id: Number(fid),
          });
        }
      });
    });
  }

  // ============================================================
  // LOAD + RENDER
  // ============================================================
  function loadAndRender() {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Compiling the record book…</div></div>';
    }
    return window.CE.bridge.getRecordsData().then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load records</div><div>' +
            escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      state.data = data;
      render();
    }).catch(function (err) {
      console.error('[records] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load records</div><div>' +
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
