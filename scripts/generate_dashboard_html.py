"""Generate a wired Dashboard HTML prototype from the live DB.

Usage:
    cd /home/z/my-project/cage_empire
    python3 scripts/generate_dashboard_html.py [promotion_id]

Default promotion_id=1. Output: dashboard_prototype.html in project root.
Double-click the HTML file to view in browser.
"""
import sqlite3
import base64
import calendar
import sys
import os
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cage_empire.db"
LOGO_DIR = PROJECT_ROOT / "src" / "ui" / "assets" / "promo_logos"
OUTPUT = PROJECT_ROOT / "dashboard_prototype.html"


def decode_phrase(stored):
    """Extract the voice phrase from 'label||phrase' format."""
    if not stored or "||" not in stored:
        return stored or ""
    return stored.split("||", 1)[1]


def decode_label(stored):
    """Extract the label from 'label||phrase' format."""
    if not stored or "||" not in stored:
        return stored or ""
    return stored.split("||", 1)[0]


def format_cash(cash):
    if abs(cash) >= 1_000_000:
        return f"${cash / 1_000_000:.1f}M"
    if abs(cash) >= 1_000:
        return f"${cash / 1_000:.0f}K"
    return f"${cash:,.0f}"


def reign_length(since_date, sim_date):
    """Calculate reign length from champion_since_date to sim_date."""
    try:
        since = datetime.strptime(since_date, "%Y-%m-%d")
        sim = datetime.strptime(sim_date, "%Y-%m-%d")
        months = (sim.year - since.year) * 12 + (sim.month - since.month)
        if months >= 12:
            return f"{months // 12}y {months % 12}m"
        return f"{months}m"
    except Exception:
        return "—"


def reputation_phrase(rep):
    if rep >= 80: return "Highly Respected"
    if rep >= 60: return "Respected"
    if rep >= 40: return "Established"
    if rep >= 20: return "Emerging"
    return "Unknown"


def fan_trust_phrase(trust):
    if trust >= 70: return "Strong"
    if trust >= 50: return "Moderate"
    if trust >= 30: return "Strained"
    return "Weak"


def topic_badge(topic):
    badges = {
        "weight_cut": "WEIGH-IN", "news_engine": "WIRE", "injury": "INJURY",
        "signing": "SIGNING", "fight": "FIGHT", "retirement": "RETIREMENT",
        "event_hype": "HYPE", "training": "TRAINING", "suspension": "SUSPENSION",
        "show_rating": "RATING", "career_arc": "CAREER", "finance": "FINANCE",
        "prospect": "PROSPECT", "cross_promo": "CROSS-PROMO", "inter_promo_callout": "CALLOUT",
    }
    return badges.get(topic, topic.upper())


def rating_tier(rating):
    """Convert numeric rating to voice tier + color."""
    if not rating: return ("unrated", "#6b7280")
    if rating >= 80: return ("a spectacular night of fights", "#4ade80")
    if rating >= 70: return ("a highly entertaining show", "#4ade80")
    if rating >= 60: return ("a solid night of fights", "#e0a957")
    if rating >= 50: return ("a decent show that failed to deliver", "#fbbf24")
    return ("a forgettable night for the fans", "#d63a3f")


def generate(promo_id=1):
    conn = sqlite3.connect(str(DB_PATH))

    # 1. Sim clock + promo info
    clock = conn.execute("SELECT current_date, current_month, current_year FROM simulation_clock WHERE clock_id=1").fetchone()
    sim_date = clock[0]
    month_name = calendar.month_name[clock[1]] if 1 <= clock[1] <= 12 else ""
    promo = conn.execute("SELECT name, current_cash, reputation, fan_trust, size_tier, broadcast_tier FROM promotions WHERE promotion_id=?", (promo_id,)).fetchone()
    promo_name = promo[0]
    cash = promo[1]
    rep = promo[2]
    fan_trust = promo[3]
    size_tier = promo[4].upper() if promo[4] else ""
    broadcast = promo[5].upper() if promo[5] else ""

    # 2. Logo (base64 embed)
    logo_file = LOGO_DIR / f"{promo_id}_alpha_combat_federation.png"
    # Try to find the right logo file
    for f in LOGO_DIR.glob("*.png"):
        if f.name.startswith(f"{promo_id}_"):
            logo_file = f
            break
    logo_b64 = ""
    if logo_file.exists():
        with open(logo_file, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()

    # 3. Top story
    ts = conn.execute("SELECT headline_text, body_text, fighter_id FROM daily_headlines WHERE headline_type='top_story' ORDER BY headline_date DESC LIMIT 1").fetchone()
    ts_headline = ts[0] if ts else "The newswire is quiet."
    ts_body = ts[1] if ts and ts[1] else "No stories have broken in the last 24 hours. Advance a day to see what develops."
    ts_fighter_name = ""
    if ts and ts[2]:
        f = conn.execute("SELECT first_name, last_name FROM fighters WHERE fighter_id=?", (ts[2],)).fetchone()
        if f:
            ts_fighter_name = f"{f[0]} {f[1]}"

    # 4. Fighter watch
    watch = []
    for htype, label, accent in [("fastest_rising", "TOP PROSPECT", "gold"), ("fastest_rising", "HOTTEST STREAK", "gold"), ("biggest_fall", "BIGGEST FALL", "crimson")]:
        h = conn.execute("SELECT fighter_id FROM daily_headlines WHERE headline_type=? ORDER BY headline_date DESC LIMIT 1", (htype,)).fetchone()
        if h and h[0]:
            fid = h[0]
            # For hottest_streak, try to find a different fighter
            if label == "HOTTEST STREAK":
                existing_ids = [w["fighter_id"] for w in watch]
                hot = conn.execute("""SELECT f.fighter_id FROM fighters f
                    JOIN fighter_descriptors fd ON fd.fighter_id=f.fighter_id
                    WHERE fd.momentum LIKE 'very_high||%' AND f.is_active=1
                    AND f.fighter_id NOT IN ({}) ORDER BY f.fighter_id LIMIT 1""".format(
                    ",".join(str(x) for x in existing_ids) if existing_ids else "0"), ).fetchone()
                if hot:
                    fid = hot[0]
            f = conn.execute("""SELECT f.first_name, f.last_name, fd.momentum, fd.career_phase, fd.narrative_family, fd.pressure, fd.legacy_state
                FROM fighters f LEFT JOIN fighter_descriptors fd ON fd.fighter_id=f.fighter_id WHERE f.fighter_id=?""", (fid,)).fetchone()
            if f:
                fights = conn.execute("SELECT outcome FROM fight_history WHERE fighter_id=? ORDER BY event_date DESC LIMIT 5", (fid,)).fetchall()
                last5 = [r[0][0].upper() if r[0] else "N" for r in fights]
                momentum_label = decode_label(f[2])
                momentum_phrase = decode_phrase(f[2])
                watch.append({
                    "label": label, "accent": accent, "fighter_id": fid,
                    "name": f"{f[0]} {f[1]}",
                    "momentum_label": momentum_label,
                    "momentum_phrase": momentum_phrase,
                    "career_phase": decode_phrase(f[3]),
                    "narrative": decode_phrase(f[4]) if f[4] else None,
                    "pressure": decode_phrase(f[5]) if f[5] else None,
                    "last5": last5,
                })

    # 5. Champions
    champs = conn.execute("""SELECT wc.name, f.fighter_id, f.first_name, f.last_name, t.champion_since_date, t.title_reigns_count, t.title_defenses_count
        FROM titles t JOIN weight_classes wc ON wc.weight_class_id=t.weight_class_id
        LEFT JOIN fighters f ON f.fighter_id=t.current_champion_fighter_id
        WHERE t.promotion_id=? AND t.is_vacant=0 AND t.current_champion_fighter_id IS NOT NULL
        ORDER BY COALESCE(wc.display_order, wc.weight_class_id)""", (promo_id,)).fetchall()

    # 6. News
    news = conn.execute("SELECT headline, body, topic, fighter_id, published_at FROM news_items ORDER BY published_at DESC LIMIT 5").fetchall()

    # 7. Recent results
    recent = conn.execute("""SELECT p.name, e.event_date, e.event_name, sr.overall_rating, sr.rating_description
        FROM events e JOIN promotions p ON p.promotion_id=e.promotion_id
        LEFT JOIN show_ratings sr ON sr.event_id=e.event_id
        WHERE e.status='completed' ORDER BY e.event_date DESC LIMIT 4""").fetchall()

    # 8. Scheduled events
    scheduled = conn.execute("""SELECT p.name, e.event_date, e.event_name
        FROM events e JOIN promotions p ON p.promotion_id=e.promotion_id
        WHERE e.status='scheduled' ORDER BY e.event_date LIMIT 3""").fetchall()

    # 9. Roster count
    roster_count = conn.execute("SELECT COUNT(*) FROM fighters WHERE current_promotion_id=? AND is_active=1", (promo_id,)).fetchone()[0]
    champ_count = len(champs)

    conn.close()

    # === GENERATE HTML ===
    rep_phr = reputation_phrase(rep)
    ft_phr = fan_trust_phrase(fan_trust)
    rep_pct = rep
    ft_pct = fan_trust

    # Build fighter watch cards
    watch_cards_html = ""
    for w in watch:
        ring_color = {"very_high": "#4ade80", "high": "#e0a957", "stable": "#6b7280", "falling": "#d63a3f", "collapsing": "#ef4444"}.get(w["momentum_label"], "#6b7280")
        ring_pct = {"very_high": 100, "high": 75, "stable": 50, "falling": 25, "collapsing": 10}.get(w["momentum_label"], 50)
        first_letter = w["last5"][0] if w["last5"] else "N"
        form_blocks = "".join(f'<div class="ce-form-block ce-form-{r.lower()}">{r}</div>' for r in w["last5"])
        accent_class = "ce-watch-card-crimson" if w["accent"] == "crimson" else ""
        icon = "★" if w["label"] == "TOP PROSPECT" else "🔥" if w["label"] == "HOTTEST STREAK" else "▼"
        pressure_chip = f'<span class="ce-chip ce-chip-danger">{w["pressure"]}</span>' if w["pressure"] else ""
        watch_cards_html += f"""
        <div class="ce-watch-card {accent_class}">
          <div class="ce-watch-header"><span class="ce-watch-label">{w['label']}</span><span class="ce-watch-icon">{icon}</span></div>
          <div class="ce-watch-body">
            <div class="ce-watch-portrait"><div class="ce-mom-ring" style="background:conic-gradient({ring_color} {ring_pct*3.6}deg, #2a2f38 0deg)"><div class="ce-mom-ring-inner"><span class="ce-mom-ring-label">{first_letter}</span></div></div></div>
            <div class="ce-watch-info">
              <a class="ce-link ce-watch-name" href="#">{w['name']}</a>
              <p class="ce-watch-phrase">"{w['momentum_phrase']}"</p>
              <div class="ce-watch-chips"><span class="ce-chip ce-chip-default">{w['career_phase'].split(' ')[0].capitalize()}</span>{pressure_chip}</div>
            </div>
          </div>
          <div class="ce-form-meter">{form_blocks}</div>
        </div>"""

    # Build champion cards
    champ_cards_html = ""
    for c in champs:
        rl = reign_length(c[4], sim_date)
        defenses = c[6]
        reigns = c[5]
        reigns_chip = f'<span class="ce-chip ce-chip-default">{reigns}ND REIGN</span>' if reigns > 1 else ""
        champ_cards_html += f"""
        <div class="ce-champ-card">
          <div class="ce-champ-wc">{c[0]}</div>
          <a class="ce-link ce-champ-name" href="#">{c[2]} {c[3]}</a>
          <div class="ce-champ-meta"><span class="ce-chip ce-chip-gold">{rl}</span><span class="ce-chip ce-chip-default">{defenses} DEF</span>{reigns_chip}</div>
        </div>"""

    # Build news cards
    news_cards_html = ""
    for n in news:
        badge = topic_badge(n[2])
        body_html = f'<p class="ce-news-body">{n[1]}</p>' if n[1] else ""
        link_class = "ce-link" if n[3] else "ce-news-headline-plain"
        news_cards_html += f"""
        <div class="ce-news-card">
          <div class="ce-news-top"><span class="ce-chip ce-chip-gold">{badge}</span><span class="ce-news-date">{n[4]}</span></div>
          <a class="ce-news-headline {link_class}" href="#">{n[0]}</a>
          {body_html}
        </div>"""

    # Build recent results
    results_html = ""
    for r in recent:
        rating_voice, rating_color = rating_tier(r[3])
        rating_desc = r[4] if r[4] else rating_voice
        results_html += f"""
        <div class="ce-result-card">
          <div class="ce-result-top"><span class="ce-result-promo">{r[0][:20]}</span><span class="ce-result-rating" style="color:{rating_color}">{rating_voice}</span></div>
          <div class="ce-result-name">{r[2][:35]}</div>
          <div class="ce-result-desc">"{rating_desc}"</div>
          <div class="ce-result-date">{r[1]}</div>
        </div>"""

    # Build next event
    next_event_html = ""
    if scheduled:
        next_event_html = f"""
        <div class="ce-next-event-card">
          <div class="ce-next-event-date ce-mono">{scheduled[0][1]}</div>
          <div class="ce-next-event-name">{scheduled[0][0]}</div>
          <div class="ce-next-event-detail">{scheduled[0][2][:50]}</div>
        </div>"""
    else:
        next_event_html = '<div class="ce-empty-state">No events scheduled. Time to build a card.</div>'

    # Top story fighter link
    ts_link = f'<a class="ce-link" href="#">View {ts_fighter_name} →</a>' if ts_fighter_name else ""

    # Logo HTML
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" class="ce-promo-logo" alt="{promo_name}" />' if logo_b64 else ""

    # Generate full HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>CAGE EMPIRE — {promo_name}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Oswald:wght@400;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
:root {{
  --bg-base:#0a0c10;--bg-surface:#15181f;--bg-card:#1c2028;--bg-card-elevated:#252a33;
  --border-subtle:#2a2f38;--border-strong:#3a4049;
  --text-primary:#e8eaed;--text-secondary:#aab0b8;--text-tertiary:#6b7280;--text-on-gold:#1a1410;
  --crimson:#d63a3f;--gold:#e0a957;--gold-bright:#f5c878;--green:#4ade80;
  --gold-tint:rgba(224,169,87,0.10);--crimson-tint:rgba(214,58,63,0.10);--green-tint:rgba(74,222,128,0.10);
}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background-color:var(--bg-base);color:var(--text-primary);font-family:'Inter',sans-serif;font-size:14px;overflow-x:hidden;
  background-image:radial-gradient(circle at 1px 1px,rgba(255,255,255,0.04) 1px,transparent 0);background-size:3px 3px;}}
.ce-noise{{position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;opacity:0.5;
  background-image:radial-gradient(circle at 1px 1px,rgba(255,255,255,0.04) 1px,transparent 0);background-size:3px 3px;}}
.ce-watermark{{position:fixed;bottom:20px;right:20px;font-family:'Oswald',sans-serif;font-size:120px;font-weight:700;color:var(--gold);opacity:0.04;pointer-events:none;z-index:0;letter-spacing:-0.05em;}}
.ce-dash{{position:relative;z-index:1;max-width:1400px;margin:0 auto;padding:24px;display:flex;flex-direction:column;gap:28px;}}
.ce-welcome-section{{display:flex;align-items:center;gap:20px;}}
.ce-promo-logo{{width:56px;height:56px;border-radius:8px;border:2px solid var(--gold);object-fit:cover;flex-shrink:0;}}
.ce-welcome-text{{flex:1;}}
.ce-welcome-title{{font-family:'Oswald',sans-serif;font-size:28px;font-weight:600;color:var(--gold);letter-spacing:0.01em;}}
.ce-welcome-sub{{font-size:14px;color:var(--text-secondary);margin-top:4px;}}
.ce-welcome-sub strong{{color:var(--text-primary);font-weight:600;}}
.ce-welcome-sub .ce-green{{color:var(--green);}}
.ce-grad-header{{position:relative;height:64px;border-radius:6px;overflow:hidden;
  background:linear-gradient(90deg,var(--gold) 0%,rgba(224,169,87,0.7) 30%,rgba(224,169,87,0.3) 60%,transparent 100%);}}
.ce-grad-header-content{{position:relative;z-index:2;height:100%;display:flex;align-items:center;justify-content:space-between;padding:0 24px;}}
.ce-grad-header-title{{font-family:'Oswald',sans-serif;font-size:28px;font-weight:700;color:var(--text-on-gold);letter-spacing:0.02em;text-transform:uppercase;text-shadow:0 1px 2px rgba(0,0,0,0.3);}}
.ce-grad-header-sub{{font-size:11px;font-weight:500;color:rgba(26,20,16,0.7);text-transform:uppercase;letter-spacing:0.04em;}}
.ce-chain-link{{position:absolute;top:0;right:0;width:50%;height:100%;z-index:1;opacity:0.12;
  background-image:repeating-linear-gradient(45deg,transparent 0,transparent 8px,rgba(0,0,0,0.3) 8px,rgba(0,0,0,0.3) 10px),repeating-linear-gradient(-45deg,transparent 0,transparent 8px,rgba(0,0,0,0.3) 8px,rgba(0,0,0,0.3) 10px);}}
.ce-section{{display:flex;flex-direction:column;gap:8px;}}
.ce-sec-header{{display:flex;align-items:center;gap:12px;padding-bottom:4px;}}
.ce-accent-bar{{width:3px;height:24px;border-radius:2px;}}
.ce-accent-gold{{background:var(--gold);}}
.ce-accent-green{{background:var(--green);}}
.ce-accent-crimson{{background:var(--crimson);}}
.ce-sec-title{{font-family:'Oswald',sans-serif;font-size:20px;font-weight:600;text-transform:uppercase;letter-spacing:0.02em;}}
.ce-sec-title-gold{{color:var(--gold);}}
.ce-sec-title-green{{color:var(--green);}}
.ce-sec-title-crimson{{color:var(--crimson);}}
.ce-sec-title-white{{color:var(--text-primary);}}
.ce-sec-icon{{font-size:16px;margin-left:4px;}}
.ce-top-story{{background:var(--bg-card);border:2px solid var(--gold);border-radius:8px;padding:20px 24px;box-shadow:0 4px 16px rgba(0,0,0,0.4);}}
.ce-ts-eyebrow{{font-size:11px;font-weight:600;color:var(--gold);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;}}
.ce-ts-headline{{font-family:'Oswald',sans-serif;font-size:22px;font-weight:600;color:var(--text-primary);margin-bottom:8px;line-height:1.3;}}
.ce-ts-body{{font-size:14px;color:var(--text-secondary);line-height:1.6;margin-bottom:12px;}}
.ce-ts-footer{{display:flex;align-items:center;gap:8px;}}
.ce-chip{{display:inline-flex;align-items:center;padding:3px 10px;border-radius:4px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em;white-space:nowrap;}}
.ce-chip-gold{{background:rgba(224,169,87,0.15);color:var(--gold);border:1px solid var(--gold);}}
.ce-chip-green{{background:rgba(74,222,128,0.15);color:var(--green);border:1px solid var(--green);}}
.ce-chip-default{{background:var(--bg-card-elevated);color:var(--text-secondary);border:1px solid var(--border-subtle);}}
.ce-chip-danger{{background:rgba(214,58,63,0.15);color:var(--crimson);border:1px solid var(--crimson);}}
.ce-link{{color:var(--gold);text-decoration:none;cursor:pointer;transition:color 0.15s;font-weight:500;}}
.ce-link:hover{{color:var(--gold-bright);text-decoration:underline;}}
.ce-stat-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;}}
.ce-stat-tile{{background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:6px;padding:16px;display:flex;flex-direction:column;gap:6px;}}
.ce-stat-label{{font-size:10px;font-weight:600;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:0.04em;}}
.ce-stat-value{{font-size:20px;font-weight:700;color:var(--text-primary);}}
.ce-stat-value-green{{color:var(--green);}}
.ce-mono{{font-family:'JetBrains Mono',monospace;}}
.ce-descriptor{{font-style:italic;color:var(--text-primary);}}
.ce-trend{{display:flex;align-items:center;gap:4px;font-size:12px;}}
.ce-trend-up{{color:var(--green);}}
.ce-trend-down{{color:var(--crimson);}}
.ce-trend-val{{color:var(--text-secondary);}}
.ce-sparkline svg{{width:100%;height:32px;}}
.ce-stat-bar{{height:8px;background:var(--border-subtle);border-radius:4px;overflow:hidden;margin-top:4px;}}
.ce-stat-bar-fill{{height:100%;border-radius:4px;}}
.ce-stat-bar-green{{background:var(--green);}}
.ce-stat-bar-gold{{background:var(--gold);}}
.ce-stat-chips{{display:flex;gap:4px;margin-top:4px;}}
.ce-watch-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}}
.ce-watch-card{{background:var(--bg-card);border:2px solid var(--gold);border-radius:8px;padding:16px;display:flex;flex-direction:column;gap:12px;}}
.ce-watch-card-crimson{{border-color:var(--crimson);}}
.ce-watch-header{{display:flex;justify-content:space-between;align-items:center;}}
.ce-watch-label{{font-family:'Oswald',sans-serif;font-size:12px;font-weight:600;color:var(--gold);text-transform:uppercase;letter-spacing:0.04em;}}
.ce-watch-card-crimson .ce-watch-label{{color:var(--crimson);}}
.ce-watch-icon{{font-size:14px;}}
.ce-watch-body{{display:flex;gap:12px;}}
.ce-watch-portrait{{flex-shrink:0;}}
.ce-mom-ring{{width:56px;height:56px;border-radius:50%;display:flex;align-items:center;justify-content:center;}}
.ce-mom-ring-inner{{width:44px;height:44px;border-radius:50%;background:var(--bg-card);display:flex;align-items:center;justify-content:center;}}
.ce-mom-ring-label{{font-family:'Oswald',sans-serif;font-size:18px;font-weight:700;}}
.ce-watch-info{{flex:1;min-width:0;}}
.ce-watch-name{{font-size:16px;font-weight:600;display:block;margin-bottom:4px;}}
.ce-watch-phrase{{font-size:13px;color:var(--text-secondary);line-height:1.4;margin-bottom:6px;font-style:italic;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}}
.ce-watch-chips{{display:flex;gap:4px;flex-wrap:wrap;}}
.ce-form-meter{{display:flex;gap:4px;}}
.ce-form-block{{width:28px;height:28px;border-radius:4px;display:flex;align-items:center;justify-content:center;font-family:'Oswald',sans-serif;font-size:14px;font-weight:700;color:var(--bg-base);}}
.ce-form-w{{background:var(--green);}}
.ce-form-l{{background:var(--crimson);}}
.ce-form-d{{background:var(--text-tertiary);}}
.ce-champ-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;}}
.ce-champ-card{{background:var(--bg-card);border:1px solid var(--border-subtle);border-left:3px solid var(--green);border-radius:6px;padding:12px 16px;display:flex;flex-direction:column;gap:4px;}}
.ce-champ-wc{{font-size:11px;font-weight:600;color:var(--green);text-transform:uppercase;letter-spacing:0.04em;}}
.ce-champ-name{{font-size:15px;font-weight:600;}}
.ce-champ-meta{{display:flex;gap:4px;flex-wrap:wrap;}}
.ce-results-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}}
.ce-result-card{{background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:6px;padding:12px 16px;display:flex;flex-direction:column;gap:4px;}}
.ce-result-top{{display:flex;justify-content:space-between;align-items:center;}}
.ce-result-promo{{font-size:11px;color:var(--text-tertiary);text-transform:uppercase;}}
.ce-result-rating{{font-size:12px;font-weight:600;font-style:italic;}}
.ce-result-name{{font-size:13px;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.ce-result-desc{{font-size:12px;color:var(--text-secondary);font-style:italic;}}
.ce-result-date{{font-size:11px;color:var(--text-tertiary);font-family:'JetBrains Mono',monospace;}}
.ce-news-list{{display:flex;flex-direction:column;gap:8px;}}
.ce-news-card{{background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:6px;padding:12px 16px;transition:background 0.15s,border-color 0.15s;}}
.ce-news-card:hover{{background:var(--bg-card-elevated);border-color:var(--border-strong);}}
.ce-news-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;}}
.ce-news-date{{font-size:11px;color:var(--text-tertiary);font-family:'JetBrains Mono',monospace;}}
.ce-news-headline{{font-size:14px;font-weight:600;color:var(--text-primary);display:block;margin-bottom:4px;}}
.ce-news-headline-plain{{text-decoration:none;cursor:default;}}
.ce-news-body{{font-size:13px;color:var(--text-secondary);line-height:1.5;}}
.ce-next-event-card{{background:var(--bg-card);border:1px solid var(--gold);border-radius:6px;padding:16px;display:flex;flex-direction:column;gap:4px;}}
.ce-next-event-date{{font-size:14px;font-weight:700;color:var(--gold);}}
.ce-next-event-name{{font-size:16px;font-weight:600;}}
.ce-next-event-detail{{font-size:13px;color:var(--text-secondary);}}
.ce-empty-state{{background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:6px;padding:20px;text-align:center;color:var(--text-tertiary);font-style:italic;}}
</style>
</head>
<body>
<div class="ce-noise"></div>
<div class="ce-watermark">CE</div>
<div class="ce-dash">

  <!-- Welcome + Logo -->
  <div class="ce-welcome-section">
    {logo_html}
    <div class="ce-welcome-text">
      <h2 class="ce-welcome-title">Welcome back, Promoter.</h2>
      <p class="ce-welcome-sub">It's <strong>{month_name} {clock[2]}</strong>. <strong>{promo_name}</strong> has <strong>{roster_count}</strong> fighters, <span class="ce-green"><strong>{champ_count}</strong> champions</span>, and <strong>{format_cash(cash)}</strong> in the bank.</p>
    </div>
  </div>

  <!-- Gradient Header -->
  <div class="ce-grad-header">
    <div class="ce-grad-header-content">
      <span class="ce-grad-header-title">THE EMPIRE</span>
      <span class="ce-grad-header-sub">{month_name} {clock[2]} · {promo_name}</span>
    </div>
    <div class="ce-chain-link"></div>
  </div>

  <!-- Top Story -->
  <div class="ce-section">
    <div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">TOP STORY</span></div>
    <div class="ce-top-story">
      <div class="ce-ts-eyebrow">BREAKING</div>
      <h3 class="ce-ts-headline">{ts_headline}</h3>
      <p class="ce-ts-body">{ts_body}</p>
      <div class="ce-ts-footer">
        <span class="ce-chip ce-chip-gold">PROSPECT</span>
        <span class="ce-chip ce-chip-default">LW</span>
        {ts_link}
      </div>
    </div>
  </div>

  <!-- Promotion Status -->
  <div class="ce-section">
    <div class="ce-sec-header"><div class="ce-accent-bar ce-accent-green"></div><span class="ce-sec-title ce-sec-title-green">PROMOTION STATUS</span></div>
    <div class="ce-stat-grid">
      <div class="ce-stat-tile">
        <div class="ce-stat-label">CASH</div>
        <div class="ce-stat-value ce-mono ce-stat-value-green">{format_cash(cash)}</div>
        <div class="ce-trend"><span class="ce-trend-up">▲</span><span class="ce-trend-val ce-mono">stable</span></div>
        <div class="ce-sparkline"><svg viewBox="0 0 120 32"><polyline points="0,20 20,18 40,16 60,14 80,12 100,10 120,8" fill="none" stroke="#4ade80" stroke-width="2"/><polygon points="0,20 20,18 40,16 60,14 80,12 100,10 120,8 120,32 0,32" fill="rgba(74,222,128,0.1)"/></svg></div>
      </div>
      <div class="ce-stat-tile">
        <div class="ce-stat-label">REPUTATION</div>
        <div class="ce-stat-value ce-descriptor">{rep_phr}</div>
        <div class="ce-stat-bar"><div class="ce-stat-bar-fill ce-stat-bar-green" style="width:{rep_pct}%"></div></div>
      </div>
      <div class="ce-stat-tile">
        <div class="ce-stat-label">FAN TRUST</div>
        <div class="ce-stat-value ce-descriptor">{ft_phr}</div>
        <div class="ce-stat-bar"><div class="ce-stat-bar-fill ce-stat-bar-green" style="width:{ft_pct}%"></div></div>
      </div>
      <div class="ce-stat-tile">
        <div class="ce-stat-label">ROSTER</div>
        <div class="ce-stat-value ce-mono">{roster_count}</div>
        <div class="ce-stat-chips"><span class="ce-chip ce-chip-default">{size_tier}</span><span class="ce-chip ce-chip-default">{broadcast}</span></div>
      </div>
      <div class="ce-stat-tile">
        <div class="ce-stat-label">CHAMPIONS</div>
        <div class="ce-stat-value ce-mono ce-stat-value-green">{champ_count} of 8</div>
        <div class="ce-stat-bar"><div class="ce-stat-bar-fill ce-stat-bar-green" style="width:{champ_count * 100 // 8}%"></div></div>
      </div>
    </div>
  </div>

  <!-- Next Event -->
  <div class="ce-section">
    <div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">NEXT EVENT</span></div>
    {next_event_html}
  </div>

  <!-- Fighter Watch -->
  <div class="ce-section">
    <div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-gold">FIGHTER WATCH</span><span class="ce-sec-icon">🥊</span></div>
    <div class="ce-watch-grid">
      {watch_cards_html}
    </div>
  </div>

  <!-- Champions -->
  <div class="ce-section">
    <div class="ce-sec-header"><div class="ce-accent-bar ce-accent-green"></div><span class="ce-sec-title ce-sec-title-green">YOUR CHAMPIONS</span><span class="ce-sec-icon">🏆</span></div>
    <div class="ce-champ-grid">
      {champ_cards_html}
    </div>
  </div>

  <!-- Recent Results -->
  <div class="ce-section">
    <div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-white">RECENT RESULTS</span></div>
    <div class="ce-results-grid">
      {results_html}
    </div>
  </div>

  <!-- Recent News -->
  <div class="ce-section">
    <div class="ce-sec-header"><div class="ce-accent-bar ce-accent-gold"></div><span class="ce-sec-title ce-sec-title-white">RECENT NEWS</span></div>
    <div class="ce-news-list">
      {news_cards_html}
    </div>
  </div>

</div>
</body>
</html>"""

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Generated {OUTPUT} ({len(html)} bytes)")
    print(f"Promotion: {promo_name} | Cash: {format_cash(cash)} | Roster: {roster_count} | Champions: {champ_count}")
    print(f"Fighter Watch: {len(watch)} fighters | News: {len(news)} | Results: {len(recent)}")
    print(f"Logo embedded: {'yes' if logo_b64 else 'no'}")


if __name__ == "__main__":
    promo_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    generate(promo_id)
