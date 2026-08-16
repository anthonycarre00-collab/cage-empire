/* ============================================================
   CAGE EMPIRE — Agent Offers Screen ("AGENT OFFERS")
   ============================================================
   Phase P3 (docs/P3_P4_PLAN.md §P3). Replaces the placeholder
   `agent_offers` nav item (added in this commit). The Talent Hunter
   fantasy's highest-dopamine moment: an agent calls with a mystery
   fighter. The player sees a vague scouting report — NEVER the name,
   NEVER the raw attributes — and has 14 days to decide whether to
   sign the gamble.

   What the player sees:
     - Section header: "AGENT OFFERS" (gold accent) + subtitle
       "N active offer(s)".
     - Cash strip: shows current player cash (so the player knows if
       they can afford the asking price before clicking Sign).
     - Offer cards (one per active offer):
       * offer_type chip ("Mystery Prospect" / "Established Fighter"
         / "Comeback Veteran") — gold/warning color-coded.
       * fighter_description — italic voice-layer scouting report.
         The agent's pitch. NO name. NO record. NO raw attributes.
       * asking_price — large, gold. The dollar figure is the only
         number the player sees (currency, not a fighter attribute).
       * expires_date + countdown ("Expires in N days" — red if ≤1
         day, warning yellow if ≤3 days, neutral otherwise).
       * "Sign for $X" button (green, prominent) — disabled when
         cash < asking_price (hover tooltip explains why).
       * "Pass" button (ghost).
     - When accepted: success toast "It's... [Fighter Name]!" →
       navigate to Fighter Profile (the reveal).
     - When declined: info toast "Passed on the offer." → card
       removed from the list.
     - Empty state: "No agents have come knocking. They will when
       the market moves."

   Voice compliance (CONVENTIONS §14 + REVENTIONS §13):
     - fighter_description: voice layer (no name, no attributes, no
       record numbers, no age as int).
     - asking_price: dollar figure (currency, not a fighter attribute).
     - days_until_expiry: integer countdown (countdown, not a rating).
     - On accept, the fighter's identity is REVEALED — this is the
       reveal moment, the dopamine hit.
   ============================================================ */

window.CE = window.CE || {};

window.CE.agentOffers = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    data: null,
    _busy: false,  // prevents double-clicks on Sign/Pass buttons
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

  function formatCash(n) {
    n = Number(n || 0);
    if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return '$' + Math.round(n / 1e3) + 'K';
    return '$' + Math.round(n).toLocaleString();
  }

  /** Days-until-expiry → voice phrase + CSS class. */
  function expiryVoice(daysLeft) {
    if (daysLeft === null || daysLeft === undefined) {
      return { phrase: 'expiry unknown', cls: 'ce-agent-offers__expiry--unknown' };
    }
    if (daysLeft < 0) {
      return { phrase: 'expired', cls: 'ce-agent-offers__expiry--expired' };
    }
    if (daysLeft === 0) {
      return { phrase: 'expires today', cls: 'ce-agent-offers__expiry--critical' };
    }
    if (daysLeft === 1) {
      return { phrase: 'expires in 1 day', cls: 'ce-agent-offers__expiry--critical' };
    }
    if (daysLeft <= 3) {
      return { phrase: 'expires in ' + daysLeft + ' days', cls: 'ce-agent-offers__expiry--soon' };
    }
    return { phrase: 'expires in ' + daysLeft + ' days', cls: 'ce-agent-offers__expiry--ok' };
  }

  // ============================================================
  // RENDER — CASH STRIP
  // ============================================================
  function renderCashStrip() {
    var d = state.data || {};
    var cash = Number(d.player_cash || 0);
    var isNeg = cash < 0;
    return '' +
      '<div class="ce-agent-offers__cash-strip">' +
        '<div class="ce-agent-offers__cash-label">YOUR WAR CHEST</div>' +
        '<div class="ce-agent-offers__cash-value' + (isNeg ? ' ce-agent-offers__cash-value--neg' : '') + '">' +
          escapeHtml(d.player_cash_display || formatCash(cash)) +
        '</div>' +
        '<div class="ce-agent-offers__cash-hint">' +
          (isNeg ? 'in the red — sign at your own peril' : 'available to gamble on the right talent') +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — OFFER CARD
  // ============================================================
  function renderOfferCard(o) {
    var exp = expiryVoice(o.days_until_expiry);
    var chipCls = 'ce-chip ce-chip-' + (o.offer_type_color || 'gold');
    var signDisabled = !o.can_afford || state._busy;
    var signBtnCls = 'ce-btn ce-btn-primary ce-agent-offers__sign-btn' +
      (signDisabled ? ' ce-agent-offers__sign-btn--disabled' : '');
    var signTitle = !o.can_afford
      ? 'You need ' + escapeHtml(o.asking_price_display) + ' but only have ' +
        escapeHtml(state.data.player_cash_display || '?') + '.'
      : (state._busy ? 'One moment…' : 'Sign this fighter for ' + escapeHtml(o.asking_price_display));

    return '' +
      '<div class="ce-agent-offers__card" data-offer-id="' + o.offer_id + '">' +
        '<div class="ce-agent-offers__card-top">' +
          '<span class="ce-agent-offers__chip ' + chipCls + '">' +
            escapeHtml(o.offer_type_label || 'Agent Offer') +
          '</span>' +
          '<span class="ce-agent-offers__expiry ' + exp.cls + '">' +
            '<span class="ce-agent-offers__expiry-icon" aria-hidden="true">⏳</span>' +
            '<span class="ce-agent-offers__expiry-phrase">' + escapeHtml(exp.phrase) + '</span>' +
            '<span class="ce-agent-offers__expiry-date"> · ' + escapeHtml(o.expires_date_display || '—') + '</span>' +
          '</span>' +
        '</div>' +
        '<div class="ce-agent-offers__description">' +
          '"' + escapeHtml(o.fighter_description || 'An agent has a fighter they want to shop around.') + '"' +
        '</div>' +
        '<div class="ce-agent-offers__card-bottom">' +
          '<div class="ce-agent-offers__price-block">' +
            '<div class="ce-agent-offers__price-label">ASKING PRICE</div>' +
            '<div class="ce-agent-offers__price-value">' +
              escapeHtml(o.asking_price_display || formatCash(o.asking_price)) +
            '</div>' +
          '</div>' +
          '<div class="ce-agent-offers__actions">' +
            '<button type="button" class="' + signBtnCls + '"' +
              (signDisabled ? ' disabled aria-disabled="true"' : '') +
              ' data-action="sign" data-offer-id="' + o.offer_id + '"' +
              ' title="' + signTitle + '">' +
              '<span class="ce-agent-offers__btn-icon" aria-hidden="true">✍</span>' +
              'Sign for ' + escapeHtml(o.asking_price_display || formatCash(o.asking_price)) +
            '</button>' +
            '<button type="button" class="ce-btn ce-btn-ghost ce-agent-offers__pass-btn"' +
              (state._busy ? ' disabled aria-disabled="true"' : '') +
              ' data-action="pass" data-offer-id="' + o.offer_id + '"' +
              ' title="Pass on this offer">' +
              'Pass' +
            '</button>' +
          '</div>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDER — OFFER LIST (with empty state)
  // ============================================================
  function renderOfferList() {
    var offers = (state.data && state.data.offers) || [];
    if (!offers.length) {
      return '' +
        '<div class="ce-agent-offers__empty">' +
          '<div class="ce-agent-offers__empty-icon" aria-hidden="true">🤝</div>' +
          '<div class="ce-agent-offers__empty-title">No agents have come knocking.</div>' +
          '<div class="ce-agent-offers__empty-body">' +
            'They will when the market moves. Sim a week forward — the calls come in roughly once a week, ' +
            'and each one is a gamble on a name you don\'t know yet.' +
          '</div>' +
        '</div>';
    }
    return '' +
      '<div class="ce-agent-offers__list">' +
        offers.map(renderOfferCard).join('') +
      '</div>';
  }

  // ============================================================
  // MAIN RENDER
  // ============================================================
  function render() {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var d = state.data || {};
    var count = d.active_count || 0;
    var subText = count === 0
      ? 'no active offers'
      : (count + ' active offer' + (count === 1 ? '' : 's'));
    var html = '' +
      '<div class="ce-agent-offers">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">🤝</span>' +
            '<span class="ce-sec-title ce-sec-title-gold">AGENT OFFERS</span>' +
            '<span class="ce-agent-offers__sub ce-mono">' + escapeHtml(subText) + '</span>' +
          '</div>' +
        '</div>' +
        renderCashStrip() +
        renderOfferList() +
      '</div>';
    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    // Sign + Pass buttons — both carry data-action + data-offer-id.
    var buttons = document.querySelectorAll(
      '.ce-agent-offers__sign-btn, .ce-agent-offers__pass-btn');
    buttons.forEach(function (btn) {
      btn.addEventListener('click', function (evt) {
        evt.preventDefault();
        if (state._busy) return;
        if (btn.disabled) return;
        var action = btn.getAttribute('data-action');
        var offerId = parseInt(btn.getAttribute('data-offer-id') || '0', 10);
        if (!offerId) return;
        if (action === 'sign') {
          handleSign(offerId);
        } else if (action === 'pass') {
          handlePass(offerId);
        }
      });
    });
  }

  // ============================================================
  // SIGN HANDLER — the reveal moment
  // ============================================================
  function handleSign(offerId) {
    state._busy = true;
    // Visually disable all buttons immediately so the player can't
    // double-click before the Promise resolves.
    document.querySelectorAll(
      '.ce-agent-offers__sign-btn, .ce-agent-offers__pass-btn').forEach(
      function (b) { b.disabled = true; });
    showToast('Closing the deal…', 'info');

    window.CE.bridge.resolveAgentOffer(offerId, true).then(function (res) {
      state._busy = false;
      if (!res || res.error) {
        showToast('Sign failed — ' + (res ? res.error : 'unknown error'),
                  'error');
        loadAndRender();
        return;
      }
      if (!res.accepted || !res.ok) {
        // Backend rejected the sign — surface the reason.
        var reason = res.reason || 'the deal fell through';
        showToast('Sign fell through — ' + reason, 'error');
        loadAndRender();
        return;
      }
      // SUCCESS — the reveal moment. Show the fighter's name in a
      // gold toast, then navigate to their profile after a short
      // pause so the player can savor the reveal.
      var name = res.fighter_name || 'Unknown Fighter';
      var nick = res.fighter_nickname;
      var reveal = nick
        ? ('It\'s... ' + name + ' "' + nick + '"!')
        : ('It\'s... ' + name + '!');
      showToast(reveal + ' Signed for ' +
        (res.asking_price_display || '?') + '.', 'success', 4500);

      // Refresh the top bar cash display in-place (the cash changed
      // by asking_price). We do this BEFORE navigating so the top bar
      // shows the new balance when the player lands on the fighter
      // profile screen. Defensive — if bridge.getPlayerCash isn't
      // available, the next Advance Day will refresh it anyway.
      try {
        window.CE.bridge.getPlayerCash().then(function (cash) {
          if (!cash) return;
          var cashEl = document.getElementById('top-bar-cash');
          if (cashEl) {
            cashEl.textContent = cash.cash_display || '';
            cashEl.classList.toggle('ce-top-bar__cash--negative',
                                   cash.is_negative);
          }
        }).catch(function () {});
      } catch (e) { /* defensive — top bar refresh is best-effort */ }

      // Navigate to the fighter profile after a short pause so the
      // player can savor the reveal.
      setTimeout(function () {
        if (window.CE.app && window.CE.app.navigate) {
          window.CE.app.navigate('fighter_profile', {
            fighter_id: Number(res.fighter_id),
          });
        } else {
          // Fallback — re-render the offers list.
          loadAndRender();
        }
      }, 1400);
    }).catch(function (err) {
      state._busy = false;
      console.error('[agent_offers] sign failed:', err);
      showToast('Sign failed — ' + String(err), 'error');
      loadAndRender();
    });
  }

  // ============================================================
  // PASS HANDLER — quiet rejection
  // ============================================================
  function handlePass(offerId) {
    state._busy = true;
    document.querySelectorAll(
      '.ce-agent-offers__sign-btn, .ce-agent-offers__pass-btn').forEach(
      function (b) { b.disabled = true; });

    window.CE.bridge.resolveAgentOffer(offerId, false).then(function (res) {
      state._busy = false;
      if (!res || res.error || !res.ok) {
        showToast('Pass failed — ' + (res ? (res.error || res.reason) : 'unknown'),
                  'error');
        loadAndRender();
        return;
      }
      showToast('Passed on the offer.', 'info');
      // Optimistically remove the card from the DOM (the next
      // loadAndRender will fetch the canonical list).
      var card = document.querySelector(
        '.ce-agent-offers__card[data-offer-id="' + offerId + '"]');
      if (card && card.parentNode) {
        card.classList.add('ce-agent-offers__card--removing');
        setTimeout(function () {
          if (card.parentNode) card.parentNode.removeChild(card);
          // If no more cards, re-render to show the empty state.
          var remaining = document.querySelectorAll(
            '.ce-agent-offers__card').length;
          if (remaining === 0) loadAndRender();
        }, 200);
      } else {
        loadAndRender();
      }
    }).catch(function (err) {
      state._busy = false;
      console.error('[agent_offers] pass failed:', err);
      showToast('Pass failed — ' + String(err), 'error');
      loadAndRender();
    });
  }

  // ============================================================
  // TOAST — success/info/error feedback
  // ============================================================
  function showToast(msg, kind, ttl) {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var existing = host.querySelector('.ce-toast');
    if (existing) existing.remove();
    var toast = document.createElement('div');
    toast.className = 'ce-toast ce-toast--' + (kind || 'info');
    toast.textContent = msg;
    host.appendChild(toast);
    var ms = ttl || 3500;
    setTimeout(function () {
      if (toast.parentNode) {
        toast.classList.add('ce-toast--fading');
        setTimeout(function () {
          if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 300);
      }
    }, ms);
  }

  // ============================================================
  // LOAD + RENDER
  // ============================================================
  function loadAndRender() {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Checking your messages…</div></div>';
    }
    return window.CE.bridge.getAgentOffers().then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load agent offers</div><div>' +
            escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      state.data = data;
      render();
    }).catch(function (err) {
      console.error('[agent_offers] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load agent offers</div><div>' +
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
