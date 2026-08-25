/* ============================================================
   CAGE EMPIRE — Scouting Screen
   ============================================================
   P1-WIRE-4-SCREENS — Screen 3 of 4.
   Per docs/P1_PLAN_WIRE_SCREENS.md §3 + docs/REVIEW_P1_SCREEN_BACKENDS.md
   §1 + CONVENTIONS §14 (Interpretation Layer).

   Renders the player's scouting operation into #screen-content
   via window.CE.bridge.getScoutingData(). The backend (src/scouting.py
   — 752 LOC) is fully coded; this screen finally gives the player a
   UI to drive scout assignments.

   What the player sees:
     - Section header: "SCOUTING" (gold accent — Talent Hunter
       pillar) + subtitle showing the scout count.
     - Summary strip: scouts on staff, free-agent scouts
       available (CTA → Staff Market), reports filed.
     - Two tabs: "My Scouts" (default) + "Reports".
     - My Scouts tab:
       * Scout cards: name + skill phrase, 3 attribute phrases
         (eye / tech / character) as gold chips, reliability
         phrase, bias tags (style / nationality / aggression),
         current assignment status.
       * If scout is on assignment: "Scouting {fighter} — ETA
         {date} ({days}d)" + Cancel button.
       * If scout is idle: "Assign to Fighter" button → opens
         the Assign modal.
     - Reports tab:
       * Report cards (last 20): target fighter name (clickable
         → Fighter Profile), ceiling phrase, top 2 strengths as
         chips, confidence chip, stale badge.
       * Click a card → expand to show the full report_text
         (multi-line prose) + all 8 estimated fields.
     - Assign modal:
       * Two sub-sections: "Free Agents" + "Rival Promo Fighters".
       * Each section: search input + paginated list of fighters
         (clickable to confirm assignment).
       * Confirm → bridge.assignScout(scout_id, target_fighter_id)
         → toast + modal closes + scout card refreshes.

   Voice compliance (CONVENTIONS §14 + §17.4 "Rich Not Thin"):
     - All estimated_* fields are voice descriptors (already in DB).
     - Phase 7 / Task A5 + B3: the raw `scout_confidence` (0-100)
       int has been DROPPED from the JSON payload. The UI shows
       the voice phrase ONLY ('HIGHLY CONFIDENT' / 'MODERATELY
       CONFIDENT' / 'UNCERTAIN' / 'WILD GUESS') — no "· 87" raw
       int suffix anymore. Per §17.4, only the voice phrase crosses
       the API boundary; the previous "scout's own rating, not a
       fighter attribute" carve-out was a §14 violation (it's a
       raw 0-100 int shown as text, regardless of semantics).
     - Scout attributes (eye_for_talent / technical_analysis /
       character_reading / mistake_rate) are NEVER shown raw —
       only voice phrases.
     - contract_cost_estimate is a dollar value (carve-out OK).
   ============================================================ */

window.CE = window.CE || {};

window.CE.scouting = (function () {
  'use strict';

  // ============================================================
  // STATE
  // ============================================================
  var state = {
    data: null,           // last getScoutingData payload
    activeTab: 'scouts',  // 'scouts' | 'reports'
    _expandedReportId: null,
    _searchTimer: null,
    // Assign-modal state.
    _assign: {
      scoutId: null,
      scoutName: '',
      section: 'fa',      // 'fa' | 'rival'
      search: '',
      rivalPromoId: null,
      rivalPromos: [],
      faPage: 1,
      rivalPage: 1,
      faData: null,
      rivalData: null,
      loading: false,
    },
  };

  // ============================================================
  // HELPERS
  // ============================================================
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function fighterInitial(name) {
    if (!name) return '?';
    var parts = String(name).trim().split(/\s+/);
    if (parts.length < 2) return parts[0].charAt(0).toUpperCase();
    return parts[parts.length - 1].charAt(0).toUpperCase();
  }

  function confidenceChipClass(phrase) {
    if (!phrase) return 'ce-chip ce-chip-default';
    if (phrase.indexOf('highly') === 0) return 'ce-chip ce-chip-gold';
    if (phrase.indexOf('moderately') === 0) return 'ce-chip ce-chip-default';
    if (phrase.indexOf('uncertain') === 0) return 'ce-chip ce-chip-warning';
    return 'ce-chip ce-chip-crimson';  // wild guess
  }

  // ============================================================
  // RENDERERS — SUMMARY
  // ============================================================
  function renderSummary(data) {
    var scouts = (data.player_scouts || []).length;
    var faCount = data.free_agent_scouts_count || 0;
    var reports = (data.recent_reports || []).length;
    return '' +
      '<div class="ce-sct__summary">' +
        '<div class="ce-sct__stat ce-sct__stat--gold">' +
          '<span class="ce-sct__stat-label">SCOUTS ON STAFF</span>' +
          '<span class="ce-sct__stat-val">' + scouts + '</span>' +
        '</div>' +
        '<div class="ce-sct__stat">' +
          '<span class="ce-sct__stat-label">FREE-AGENT SCOUTS</span>' +
          '<span class="ce-sct__stat-val">' + faCount + '</span>' +
          '<span class="ce-sct__stat-hint">Hire from Staff Market</span>' +
        '</div>' +
        '<div class="ce-sct__stat">' +
          '<span class="ce-sct__stat-label">REPORTS FILED</span>' +
          '<span class="ce-sct__stat-val">' + reports + '</span>' +
        '</div>' +
      '</div>';
  }

  // ============================================================
  // RENDERERS — TABS
  // ============================================================
  function renderTabs() {
    var scoutsActive = state.activeTab === 'scouts' ? ' ce-sct__tab--active' : '';
    var reportsActive = state.activeTab === 'reports' ? ' ce-sct__tab--active' : '';
    return '' +
      '<div class="ce-sct__tabs">' +
        '<button class="ce-sct__tab' + scoutsActive + '" data-tab="scouts" type="button">My Scouts</button>' +
        '<button class="ce-sct__tab' + reportsActive + '" data-tab="reports" type="button">Reports</button>' +
      '</div>';
  }

  // ============================================================
  // RENDERERS — SCOUT CARD
  // ============================================================
  function renderScoutCard(scout) {
    var assign = scout.current_assignment;
    var statusHtml = '';
    var actionHtml = '';
    if (assign) {
      var daysLabel = (assign.days_remaining != null)
        ? ' · ' + assign.days_remaining + 'd left'
        : '';
      statusHtml = '' +
        '<div class="ce-sct__scout-status ce-sct__scout-status--busy">' +
          '<span class="ce-sct__scout-status-label">SCOUTING</span>' +
          '<a class="ce-sct__scout-target ce-link" href="#" data-fighter-id="' + assign.fighter_id + '">' +
            escapeHtml(assign.fighter_name) + '</a>' +
          '<span class="ce-sct__scout-eta ce-mono">ETA ' + escapeHtml(assign.eta_date || '—') + daysLabel + '</span>' +
        '</div>';
      actionHtml = '<button class="ce-btn ce-btn-ghost ce-sct__cancel-btn" data-scout-id="' + scout.staff_id + '" type="button">Cancel</button>';
    } else {
      statusHtml = '<div class="ce-sct__scout-status ce-sct__scout-status--idle">Idle — ready to scout</div>';
      actionHtml = '<button class="ce-btn ce-btn-primary ce-sct__assign-btn" data-scout-id="' + scout.staff_id + '" data-scout-name="' + escapeHtml(scout.name) + '" type="button">Assign to Fighter</button>';
    }

    // Bias tags
    var biasParts = [];
    if (scout.bias_style) biasParts.push('Style: ' + scout.bias_style);
    if (scout.bias_nationality) biasParts.push('Nat: ' + scout.bias_nationality);
    if (scout.bias_aggression != null && scout.bias_aggression !== 0) {
      var ag = Number(scout.bias_aggression);
      var agLabel = (ag > 0 ? '+' : '') + ag + ' agg';
      biasParts.push(agLabel);
    }
    var biasHtml = biasParts.length
      ? '<div class="ce-sct__scout-biases">' +
          biasParts.map(function (b) {
            return '<span class="ce-chip ce-chip-default ce-sct__bias-chip">' + escapeHtml(b) + '</span>';
          }).join('') +
        '</div>'
      : '';

    return '' +
      '<article class="ce-sct__scout-card" data-scout-id="' + scout.staff_id + '">' +
        '<div class="ce-sct__scout-header">' +
          '<div class="ce-sct__scout-portrait">' + escapeHtml(fighterInitial(scout.name)) + '</div>' +
          '<div class="ce-sct__scout-info">' +
            '<div class="ce-sct__scout-name">' + escapeHtml(scout.name) + '</div>' +
            '<div class="ce-sct__scout-meta ce-mono">' +
              escapeHtml(scout.skill_phrase) + ' · ' + escapeHtml(scout.salary_display) +
            '</div>' +
          '</div>' +
          actionHtml +
        '</div>' +
        '<div class="ce-sct__scout-attrs">' +
          '<span class="ce-chip ce-chip-gold ce-sct__attr-chip">' + escapeHtml(scout.eye_for_talent_phrase) + '</span>' +
          '<span class="ce-chip ce-chip-gold ce-sct__attr-chip">' + escapeHtml(scout.tech_phrase) + '</span>' +
          '<span class="ce-chip ce-chip-gold ce-sct__attr-chip">' + escapeHtml(scout.character_phrase) + '</span>' +
          '<span class="ce-chip ce-chip-default ce-sct__attr-chip">Reliability: ' + escapeHtml(scout.mistake_phrase) + '</span>' +
        '</div>' +
        biasHtml +
        statusHtml +
      '</article>';
  }

  function renderScoutsTab(data) {
    var scouts = data.player_scouts || [];
    if (!scouts.length) {
      return '<div class="ce-sct__empty">' +
        '<div class="ce-sct__empty-icon">🔍</div>' +
        '<div class="ce-sct__empty-title">No scouts on your staff.</div>' +
        '<div class="ce-sct__empty-body">Head to the Staff Market to hire a scout. They will fan out and find the next great one before anyone else does.</div>' +
        '<button class="ce-btn ce-btn-primary ce-sct__empty-cta" id="ce-sct-goto-staff" type="button">Browse Staff Market</button>' +
      '</div>';
    }
    return '<div class="ce-sct__scout-list">' +
      scouts.map(renderScoutCard).join('') +
    '</div>';
  }

  // ============================================================
  // RENDERERS — REPORT CARD
  // ============================================================
  function renderReportCard(report) {
    var isExpanded = state._expandedReportId === report.scouting_report_id;
    var staleChip = report.is_stale
      ? '<span class="ce-chip ce-chip-warning ce-sct__stale-chip">STALE</span>'
      : '';
    var strengthsHtml = (report.estimated_strengths || []).slice(0, 3).map(function (s) {
      return '<span class="ce-chip ce-chip-green ce-sct__strength-chip">' + escapeHtml(s) + '</span>';
    }).join('');
    var weaknessesHtml = (report.estimated_weaknesses || []).slice(0, 2).map(function (s) {
      return '<span class="ce-chip ce-chip-crimson ce-sct__weakness-chip">' + escapeHtml(s) + '</span>';
    }).join('');

    var nickHtml = report.target_nickname
      ? '<span class="ce-sct__report-nick"> \'' + escapeHtml(report.target_nickname) + '\'</span>'
      : '';

    var detailHtml = '';
    if (isExpanded) {
      detailHtml = '' +
        '<div class="ce-sct__report-detail">' +
          '<div class="ce-sct__report-grid">' +
            '<div class="ce-sct__report-row"><span class="ce-sct__report-label">FLOOR</span><span class="ce-sct__report-val">' + escapeHtml(report.estimated_floor || '—') + '</span></div>' +
            '<div class="ce-sct__report-row"><span class="ce-sct__report-label">MARKETABILITY</span><span class="ce-sct__report-val">' + escapeHtml(report.marketability_assessment || '—') + '</span></div>' +
            '<div class="ce-sct__report-row"><span class="ce-sct__report-label">INJURY RISK</span><span class="ce-sct__report-val">' + escapeHtml(report.injury_risk_assessment || '—') + '</span></div>' +
            '<div class="ce-sct__report-row"><span class="ce-sct__report-label">CONTRACT COST</span><span class="ce-sct__report-val ce-mono">' + escapeHtml(report.contract_cost_display || '—') + '</span></div>' +
          '</div>' +
          (weaknessesHtml
            ? '<div class="ce-sct__report-weaknesses"><span class="ce-sct__report-label">WEAKNESSES</span> ' + weaknessesHtml + '</div>'
            : '') +
          '<div class="ce-sct__report-prose">' + escapeHtml(report.report_text || '') + '</div>' +
        '</div>';
    }

    return '' +
      '<article class="ce-sct__report-card' + (isExpanded ? ' ce-sct__report-card--expanded' : '') + '" data-report-id="' + report.scouting_report_id + '">' +
        '<div class="ce-sct__report-header">' +
          '<div class="ce-sct__report-portrait">' + escapeHtml(fighterInitial(report.target_name)) + '</div>' +
          '<div class="ce-sct__report-info">' +
            '<a class="ce-sct__report-name ce-link" href="#" data-fighter-id="' + report.target_fighter_id + '">' +
              escapeHtml(report.target_name) + '</a>' + nickHtml +
            '<div class="ce-sct__report-meta ce-mono">By ' + escapeHtml(report.scout_name) + ' · ' + escapeHtml(report.report_date_display) + '</div>' +
          '</div>' +
          '<div class="ce-sct__report-chips">' +
            staleChip +
            '<span class="' + confidenceChipClass(report.confidence_phrase) + '">' +
              escapeHtml((report.confidence_phrase || '').toUpperCase()) +
            '</span>' +
          '</div>' +
        '</div>' +
        '<div class="ce-sct__report-ceiling">' +
          '<span class="ce-sct__report-ceiling-label">CEILING</span>' +
          '<span class="ce-sct__report-ceiling-val">' + escapeHtml(report.estimated_ceiling || '—') + '</span>' +
        '</div>' +
        (strengthsHtml
          ? '<div class="ce-sct__report-strengths">' + strengthsHtml + '</div>'
          : '') +
        detailHtml +
        '<div class="ce-sct__report-footer">' +
          '<span class="ce-sct__expand-hint">' + (isExpanded ? '▲ Collapse' : '▼ Full report') + '</span>' +
        '</div>' +
      '</article>';
  }

  function renderReportsTab(data) {
    var reports = data.recent_reports || [];
    if (!reports.length) {
      return '<div class="ce-sct__empty">' +
        '<div class="ce-sct__empty-icon">📝</div>' +
        '<div class="ce-sct__empty-title">No scouting reports yet.</div>' +
        '<div class="ce-sct__empty-body">Assign a scout to a fighter from the My Scouts tab. They will observe for 7 sim days, then deliver a full report — ceiling, strengths, weaknesses, marketability, the lot.</div>' +
      '</div>';
    }
    return '<div class="ce-sct__report-list">' +
      reports.map(renderReportCard).join('') +
    '</div>';
  }

  // ============================================================
  // RENDERERS — ASSIGN MODAL
  // ============================================================
  function renderAssignModal() {
    var a = state._assign;
    if (!a.scoutId) return '';
    var faActive = a.section === 'fa' ? ' ce-sct__modal-tab--active' : '';
    var rivalActive = a.section === 'rival' ? ' ce-sct__modal-tab--active' : '';

    var rivalPromoOptions = '<option value="">Pick a promotion…</option>' +
      a.rivalPromos.map(function (p) {
        var sel = a.rivalPromoId === p.promotion_id ? ' selected' : '';
        return '<option value="' + p.promotion_id + '"' + sel + '>' +
          escapeHtml(p.name) + '</option>';
      }).join('');

    var faSectionHtml = a.section === 'fa'
      ? renderAssignFighterList(a.faData, 'fa', a.loading)
      : '';
    var rivalSectionHtml = a.section === 'rival'
      ? (a.rivalPromoId
          ? renderAssignFighterList(a.rivalData, 'rival', a.loading)
          : '<div class="ce-sct__modal-empty">Pick a rival promotion above to browse their roster.</div>')
      : '';

    return '' +
      '<div class="ce-modal-overlay ce-sct__modal-overlay" id="ce-sct-assign-modal" style="display:flex">' +
        '<div class="ce-modal-dialog ce-fa-modal-dialog--wide">' +
          '<div class="ce-modal-header">' +
            '<div class="ce-modal-title">ASSIGN ' + escapeHtml(a.scoutName.toUpperCase()) + '</div>' +
            '<button class="ce-modal-close" id="ce-sct-assign-close" type="button">×</button>' +
          '</div>' +
          '<div class="ce-modal-body">' +
            '<p class="ce-modal-line">Pick a target for ' + escapeHtml(a.scoutName) + '. The report lands in 7 sim days.</p>' +
            '<div class="ce-sct__modal-tabs">' +
              '<button class="ce-sct__modal-tab' + faActive + '" data-modal-tab="fa" type="button">Free Agents</button>' +
              '<button class="ce-sct__modal-tab' + rivalActive + '" data-modal-tab="rival" type="button">Rival Promos</button>' +
            '</div>' +
            (a.section === 'fa'
              ? '<div class="ce-sct__modal-search-row">' +
                  '<input type="text" id="ce-sct-assign-search" class="ce-filter-input" placeholder="Search free agents…" value="' + escapeHtml(a.search) + '" />' +
                '</div>'
              : '<div class="ce-sct__modal-search-row">' +
                  '<select id="ce-sct-assign-rival-promo" class="ce-filter-select">' + rivalPromoOptions + '</select>' +
                  '<input type="text" id="ce-sct-assign-search" class="ce-filter-input" placeholder="Search roster…" value="' + escapeHtml(a.search) + '" />' +
                '</div>') +
            '<div class="ce-sct__modal-list-host">' +
              faSectionHtml +
              rivalSectionHtml +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';
  }

  function renderAssignFighterList(data, sectionKind, loading) {
    if (loading) {
      return '<div class="ce-sct__modal-loading"><div class="ce-loading__spinner"></div><div>Loading fighters…</div></div>';
    }
    if (!data) return '';
    var fighters = data.fighters || [];
    if (!fighters.length) {
      return '<div class="ce-sct__modal-empty">No fighters match your search.</div>';
    }
    var list = fighters.map(function (f) {
      var name = f.name || (f.first_name ? (f.first_name + ' ' + (f.last_name || '')) : 'Unknown');
      var meta = [];
      if (f.wc_name || f.weight_class_name) meta.push(f.wc_name || f.weight_class_name);
      if (f.record_str) meta.push(f.record_str);
      else if (f.record_wins != null) {
        var rec = f.record_wins + '-' + f.record_losses;
        if (f.record_draws > 0) rec += '-' + f.record_draws;
        meta.push(rec);
      }
      var metaHtml = meta.length ? '<div class="ce-sct__pick-meta ce-mono">' + escapeHtml(meta.join(' · ')) + '</div>' : '';
      var stageHtml = (f.stage_short || f.form_short)
        ? '<div class="ce-sct__pick-stage">' + escapeHtml((f.stage_short || '') + (f.form_short ? (' · ' + f.form_short) : '')) + '</div>'
        : '';
      return '' +
        '<div class="ce-sct__pick-row" data-fighter-id="' + f.fighter_id + '" data-fighter-name="' + escapeHtml(name) + '" role="button" tabindex="0">' +
          '<div class="ce-sct__pick-portrait">' + escapeHtml(fighterInitial(name)) + '</div>' +
          '<div class="ce-sct__pick-info">' +
            '<div class="ce-sct__pick-name">' + escapeHtml(name) + '</div>' +
            metaHtml +
            stageHtml +
          '</div>' +
          '<div class="ce-sct__pick-action">Scout ▶</div>' +
        '</div>';
    }).join('');

    // Pagination footer
    var total = data.total || 0;
    var perPage = data.per_page || 20;
    var page = data.page || 1;
    var totalPages = data.total_pages || 1;
    var paginationHtml = '';
    if (total > perPage) {
      paginationHtml = '<div class="ce-sct__modal-pagination">' +
        '<button class="ce-page-btn" data-modal-page="' + (page - 1) + '" type="button"' + (page <= 1 ? ' disabled' : '') + '>◀</button>' +
        '<span class="ce-page-indicator ce-mono">Page ' + page + ' of ' + totalPages + ' (' + total + ')</span>' +
        '<button class="ce-page-btn" data-modal-page="' + (page + 1) + '" type="button"' + (page >= totalPages ? ' disabled' : '') + '>▶</button>' +
      '</div>';
    }
    return '<div class="ce-sct__modal-list">' + list + '</div>' + paginationHtml;
  }

  // ============================================================
  // MAIN RENDER
  // ============================================================
  function render() {
    var host = document.getElementById('screen-content');
    if (!host || !state.data) return;
    var data = state.data;

    var tabBody = state.activeTab === 'scouts'
      ? renderScoutsTab(data)
      : renderReportsTab(data);

    var html = '' +
      '<div class="ce-sct">' +
        '<div class="ce-section">' +
          '<div class="ce-sec-header">' +
            '<div class="ce-accent-bar ce-accent-gold"></div>' +
            '<span class="ce-sec-icon">🔍</span>' +
            '<span class="ce-sec-title ce-sec-title-gold">SCOUTING</span>' +
            '<span class="ce-sec-sub ce-mono">' + (data.player_scouts || []).length + ' scouts on staff</span>' +
          '</div>' +
        '</div>' +
        renderSummary(data) +
        renderTabs() +
        tabBody +
      '</div>' +
      renderAssignModal();

    host.innerHTML = html;
    wireEvents();
  }

  // ============================================================
  // EVENT WIRING
  // ============================================================
  function wireEvents() {
    // Tab switcher
    document.querySelectorAll('.ce-sct__tab').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.activeTab = btn.getAttribute('data-tab') || 'scouts';
        state._expandedReportId = null;
        render();
      });
    });

    // Empty-state CTA → Staff Market
    var gotoStaffBtn = document.getElementById('ce-sct-goto-staff');
    if (gotoStaffBtn) gotoStaffBtn.addEventListener('click', function () {
      window.CE.app.navigate('staff_market');
    });

    // Assign buttons — open modal
    document.querySelectorAll('.ce-sct__assign-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var sid = parseInt(btn.getAttribute('data-scout-id'), 10);
        var sname = btn.getAttribute('data-scout-name') || 'Scout';
        openAssignModal(sid, sname);
      });
    });

    // Cancel-assignment buttons
    document.querySelectorAll('.ce-sct__cancel-btn').forEach(function (btn) {
      btn.addEventListener('click', function (evt) {
        evt.stopPropagation();
        var sid = parseInt(btn.getAttribute('data-scout-id'), 10);
        if (!sid) return;
        btn.disabled = true;
        btn.textContent = 'Cancelling…';
        window.CE.bridge.cancelScoutAssignment(sid).then(function (res) {
          if (res && res.ok) {
            showToast('Assignment cancelled.', 'success');
            loadAndRender();
          } else {
            showToast('Cancel failed: ' + (res && res.error ? res.error : 'unknown'), 'error');
            btn.disabled = false;
            btn.textContent = 'Cancel';
          }
        }).catch(function (err) {
          showToast('Cancel failed: ' + err, 'error');
          btn.disabled = false;
          btn.textContent = 'Cancel';
        });
      });
    });

    // Fighter-name hyperlinks → Fighter Profile
    document.querySelectorAll('.ce-sct__scout-target[data-fighter-id], .ce-sct__report-name[data-fighter-id]').forEach(function (link) {
      link.addEventListener('click', function (evt) {
        evt.preventDefault();
        evt.stopPropagation();
        var fid = link.getAttribute('data-fighter-id');
        if (fid) window.CE.app.navigate('fighter_profile', { fighter_id: Number(fid) });
      });
    });

    // Report card expand/collapse
    document.querySelectorAll('.ce-sct__report-card').forEach(function (card) {
      card.addEventListener('click', function (evt) {
        if (evt.target.closest('.ce-sct__report-name')) return;
        if (evt.target.closest('button')) return;
        var rid = parseInt(card.getAttribute('data-report-id'), 10);
        if (!rid) return;
        state._expandedReportId = (state._expandedReportId === rid) ? null : rid;
        render();
      });
    });

    wireAssignModalEvents();
  }

  function wireAssignModalEvents() {
    var closeBtn = document.getElementById('ce-sct-assign-close');
    if (closeBtn) closeBtn.addEventListener('click', closeAssignModal);

    var overlay = document.getElementById('ce-sct-assign-modal');
    if (overlay) overlay.addEventListener('click', function (evt) {
      if (evt.target === overlay) closeAssignModal();
    });

    // Modal tab switcher
    document.querySelectorAll('.ce-sct__modal-tab').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state._assign.section = btn.getAttribute('data-modal-tab') || 'fa';
        state._assign.search = '';
        state._assign.faPage = 1;
        state._assign.rivalPage = 1;
        state._assign.faData = null;
        state._assign.rivalData = null;
        render();
        loadAssignSection();
      });
    });

    // Search input
    var searchInput = document.getElementById('ce-sct-assign-search');
    if (searchInput) searchInput.addEventListener('input', function () {
      if (state._searchTimer) clearTimeout(state._searchTimer);
      state._searchTimer = setTimeout(function () {
        state._assign.search = searchInput.value;
        state._assign.faPage = 1;
        state._assign.rivalPage = 1;
        loadAssignSection();
      }, 250);
    });

    // Rival promo dropdown
    var rivalSel = document.getElementById('ce-sct-assign-rival-promo');
    if (rivalSel) rivalSel.addEventListener('change', function () {
      state._assign.rivalPromoId = parseInt(rivalSel.value, 10) || null;
      state._assign.rivalPage = 1;
      state._assign.rivalData = null;
      render();
      loadAssignSection();
    });

    // Pagination
    document.querySelectorAll('.ce-sct__modal-pagination .ce-page-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.disabled) return;
        var p = parseInt(btn.getAttribute('data-modal-page'), 10);
        if (!p || p < 1) return;
        if (state._assign.section === 'fa') state._assign.faPage = p;
        else state._assign.rivalPage = p;
        loadAssignSection();
      });
    });

    // Fighter pick rows
    document.querySelectorAll('.ce-sct__pick-row').forEach(function (row) {
      var handler = function (evt) {
        if (evt.type === 'keydown' && evt.key !== 'Enter' && evt.key !== ' ') return;
        if (evt.type === 'keydown') evt.preventDefault();
        var fid = parseInt(row.getAttribute('data-fighter-id'), 10);
        var fname = row.getAttribute('data-fighter-name') || 'fighter';
        if (!fid) return;
        confirmAssign(fid, fname);
      };
      row.addEventListener('click', handler);
      row.addEventListener('keydown', handler);
    });
  }

  // ============================================================
  // ASSIGN-MODAL FLOW
  // ============================================================
  function openAssignModal(scoutId, scoutName) {
    state._assign = {
      scoutId: scoutId,
      scoutName: scoutName,
      section: 'fa',
      search: '',
      rivalPromoId: null,
      rivalPromos: [],
      faPage: 1,
      rivalPage: 1,
      faData: null,
      rivalData: null,
      loading: false,
    };
    render();
    // Kick off the data fetches in parallel.
    loadAssignSection();
    // Also pre-fetch the rival promo list so the dropdown populates
    // immediately when the player switches to the Rival Promos tab.
    window.CE.bridge.getRivalPromotions().then(function (promos) {
      if (promos && promos.promotions) {
        state._assign.rivalPromos = promos.promotions;
      } else if (Array.isArray(promos)) {
        state._assign.rivalPromos = promos;
      }
    }).catch(function () { /* swallow */ });
  }

  function closeAssignModal() {
    state._assign.scoutId = null;
    state._assign.scoutName = '';
    render();
  }

  function loadAssignSection() {
    var a = state._assign;
    if (!a.scoutId) return;
    a.loading = true;
    // Re-render just the list area to show loading.
    var host = document.querySelector('.ce-sct__modal-list-host');
    if (host) host.innerHTML = renderAssignFighterList(null, a.section, true);

    if (a.section === 'fa') {
      window.CE.bridge.getFreeAgents(a.faPage, { search: a.search }).then(function (data) {
        a.loading = false;
        a.faData = data;
        if (host) host.innerHTML = renderAssignFighterList(data, 'fa', false);
        wireAssignModalEvents();
      }).catch(function (err) {
        a.loading = false;
        if (host) host.innerHTML = '<div class="ce-sct__modal-empty">Failed to load: ' + escapeHtml(String(err)) + '</div>';
      });
    } else if (a.section === 'rival' && a.rivalPromoId) {
      window.CE.bridge.getRivalRoster(a.rivalPromoId, a.rivalPage, { search: a.search }).then(function (data) {
        a.loading = false;
        a.rivalData = data;
        if (host) host.innerHTML = renderAssignFighterList(data, 'rival', false);
        wireAssignModalEvents();
      }).catch(function (err) {
        a.loading = false;
        if (host) host.innerHTML = '<div class="ce-sct__modal-empty">Failed to load: ' + escapeHtml(String(err)) + '</div>';
      });
    } else {
      a.loading = false;
      if (host) host.innerHTML = '<div class="ce-sct__modal-empty">Pick a rival promotion above to browse their roster.</div>';
    }
  }

  function confirmAssign(fighterId, fighterName) {
    var a = state._assign;
    if (!a.scoutId) return;
    window.CE.bridge.assignScout(a.scoutId, fighterId).then(function (res) {
      if (res && res.ok) {
        var eta = res.eta_date ? (' · ETA ' + res.eta_date) : '';
        showToast(a.scoutName + ' is scouting ' + fighterName + eta, 'success');
        closeAssignModal();
        loadAndRender();
      } else {
        showToast('Assign failed: ' + (res && res.error ? res.error : 'unknown'), 'error');
      }
    }).catch(function (err) {
      showToast('Assign failed: ' + err, 'error');
    });
  }

  // ============================================================
  // TOAST
  // ============================================================
  function showToast(msg, kind) {
    var host = document.getElementById('screen-content');
    if (!host) return;
    var existing = host.querySelector('.ce-toast');
    if (existing) existing.remove();
    var toast = document.createElement('div');
    toast.className = 'ce-toast ce-toast--' + (kind || 'info');
    toast.textContent = msg;
    host.appendChild(toast);
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 4000);
  }

  // ============================================================
  // LOAD + RENDER
  // ============================================================
  function loadAndRender() {
    var host = document.getElementById('screen-content');
    if (host) {
      host.innerHTML = '<div class="ce-loading"><div class="ce-loading__spinner"></div><div class="ce-loading__text">Fanning out the scouts…</div></div>';
    }
    return window.CE.bridge.getScoutingData().then(function (data) {
      if (!data || data.error) {
        if (host) {
          host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load scouting</div><div>' +
            escapeHtml(data ? data.error : 'unknown error') + '</div></div>';
        }
        return;
      }
      state.data = data;
      render();
    }).catch(function (err) {
      console.error('[scouting] load failed:', err);
      if (host) {
        host.innerHTML = '<div class="ce-error-banner"><div class="ce-error-banner__title">Failed to load scouting</div><div>' +
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
