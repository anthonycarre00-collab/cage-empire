#!/usr/bin/env python3
"""Capture post-1yr-sim metrics + full analysis."""
import sqlite3, json
from pathlib import Path
from collections import Counter

DB = Path(__file__).parent.parent / "data" / "cage_empire.db"
c = sqlite3.connect(str(DB))

# Load baseline
with open('data/baseline_1yr_sim.json') as f:
    baseline = json.load(f)

sim_date = c.execute('SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1').fetchone()[0]
tick = c.execute('SELECT tick_counter FROM simulation_clock WHERE clock_id=1').fetchone()[0]

print(f'=== 1-YEAR SIM ANALYSIS ===')
print(f'sim_date: {baseline["sim_date"]} → {sim_date} ({tick} ticks)')
print()

# 1. Population
print('=== 1. POPULATION ===')
n_fighters = c.execute('SELECT COUNT(*) FROM fighters').fetchone()[0]
n_active = c.execute('SELECT COUNT(*) FROM fighters WHERE is_active=1 AND is_retired=0').fetchone()[0]
n_retired = c.execute('SELECT COUNT(*) FROM fighters WHERE is_retired=1').fetchone()[0]
n_regen = c.execute('SELECT COUNT(*) FROM regen_lineage').fetchone()[0]
print(f'Fighters: {baseline["counts"]["fighters"]} → {n_fighters} (+{n_fighters - baseline["counts"]["fighters"]})')
print(f'Active: {baseline["counts"]["active"]} → {n_active} ({n_active - baseline["counts"]["active"]:+d})')
print(f'Retired: {baseline["counts"]["retired"]} → {n_retired} (+{n_retired - baseline["counts"]["retired"]})')
print(f'Regen lineage: {baseline["counts"]["regen_lineage"]} → {n_regen} (+{n_regen - baseline["counts"]["regen_lineage"]})')
print(f'Free agents: {baseline["counts"]["free_agents"]} → {c.execute("SELECT COUNT(*) FROM fighters WHERE is_active=1 AND is_retired=0 AND current_promotion_id IS NULL").fetchone()[0]}')
print()

# 2. Top fighters (did they change?)
print('=== 2. TOP FIGHTERS (by ELO) ===')
top_now = list(c.execute('''
SELECT r.fighter_id, f.first_name || ' ' || f.last_name, r.rating,
       fc.record_wins, fc.record_losses, fc.potential, fc.title_reigns
FROM rankings r JOIN fighters f ON f.fighter_id=r.fighter_id
JOIN fighter_career fc ON fc.fighter_id=r.fighter_id
WHERE f.is_active=1 AND f.is_retired=0
ORDER BY r.rating DESC LIMIT 15
'''))
for r in top_now:
    print(f'  {r[1]:25s} ELO={r[2]:.0f}  {r[3]}-{r[4]}  pot={r[5]}  reigns={r[6]}')
print()

# 3. Retirees + regen
print('=== 3. RETIREES + REGEN ===')
retirees = list(c.execute('''
SELECT rl.retiring_fighter_id, fa.first_name || ' ' || fa.last_name, rl.regen_date,
       rl.replacement_fighter_id, fb.first_name || ' ' || fb.last_name
FROM regen_lineage rl
JOIN fighters fa ON fa.fighter_id=rl.retiring_fighter_id
JOIN fighters fb ON fb.fighter_id=rl.replacement_fighter_id
ORDER BY rl.regen_date DESC LIMIT 15
'''))
print(f'Total retired+regen: {n_regen}')
for r in retirees[:10]:
    print(f'  {r[1]:25s} retired {r[2]} → replaced by {r[4]}')
print()

# 4. Champions + title changes
print('=== 4. CHAMPIONS + TITLE CHANGES ===')
n_champs = c.execute('SELECT COUNT(*) FROM titles WHERE current_champion_fighter_id IS NOT NULL').fetchone()[0]
n_vacant = c.execute('SELECT COUNT(*) FROM titles WHERE current_champion_fighter_id IS NULL').fetchone()[0]
print(f'Champions: {baseline["counts"]["champions"]} → {n_champs} (vacant: {n_vacant})')
print()
print('Current champions by promotion:')
for r in c.execute('''
SELECT p.name, wc.name, f.first_name || ' ' || f.last_name, t.champion_since_date, t.title_defenses_count
FROM titles t JOIN promotions p ON p.promotion_id=t.promotion_id
JOIN weight_classes wc ON wc.weight_class_id=t.weight_class_id
LEFT JOIN fighters f ON f.fighter_id=t.current_champion_fighter_id
WHERE t.current_champion_fighter_id IS NOT NULL
ORDER BY p.name, wc.name LIMIT 30
'''):
    print(f'  {r[0]:30s} {r[1]:20s} {r[2]:25s} since={r[3]} defenses={r[4]}')
print()

# 5. News feed quality
print('=== 5. NEWS FEED ===')
n_news = c.execute('SELECT COUNT(*) FROM news_items').fetchone()[0]
print(f'News items: {baseline["counts"]["news"]} → {n_news} (+{n_news - baseline["counts"]["news"]})')
print('By importance:')
for r in c.execute('SELECT importance, COUNT(*) FROM news_items GROUP BY importance ORDER BY 2 DESC'):
    print(f'  {r[0]:15s} {r[1]}')
print('By topic (top 15):')
for r in c.execute('SELECT topic, COUNT(*) FROM news_items GROUP BY topic ORDER BY 2 DESC LIMIT 15'):
    print(f'  {r[0]:25s} {r[1]}')
print('Sample headlines (recent):')
for r in c.execute('SELECT headline FROM news_items ORDER BY news_item_id DESC LIMIT 10'):
    print(f'  "{r[0]}"')
print()

# 6. Memory resurfacing
print('=== 6. MEMORY RESURFACING ===')
n_mem_news = c.execute("SELECT COUNT(*) FROM news_items WHERE topic='memory_resurfacing'").fetchone()[0]
n_mem_links = c.execute('SELECT COUNT(*) FROM fighter_memory_links').fetchone()[0]
print(f'Memory resurfacing news: {n_mem_news}')
print(f'Fighter memory links: {baseline["counts"]["memory_links"]} → {n_mem_links} (+{n_mem_links - baseline["counts"]["memory_links"]})')
print('Memory link types:')
for r in c.execute('SELECT link_type, COUNT(*) FROM fighter_memory_links GROUP BY link_type ORDER BY 2 DESC'):
    print(f'  {r[0]:25s} {r[1]}')
print()

# 7. Rivalries
print('=== 7. RIVALRIES ===')
n_riv = c.execute('SELECT COUNT(*) FROM rivalries').fetchone()[0]
n_riv_active = c.execute('SELECT COUNT(*) FROM rivalries WHERE is_active=1').fetchone()[0]
print(f'Rivalries: {baseline["counts"]["rivalries"]} → {n_riv} (+{n_riv - baseline["counts"]["rivalries"]})')
print(f'Active: {n_riv_active}')
print('By type:')
for r in c.execute('SELECT rivalry_type, COUNT(*) FROM rivalries GROUP BY rivalry_type ORDER BY 2 DESC'):
    print(f'  {r[0]:25s} {r[1]}')
print('Top rivalries (by heat):')
for r in c.execute('''
SELECT r.rivalry_type, r.rivalry_heat, r.fights_count,
       fa.first_name || ' ' || fa.last_name, fb.first_name || ' ' || fb.last_name
FROM rivalries r
JOIN fighters fa ON fa.fighter_id=r.fighter_a_id
JOIN fighters fb ON fb.fighter_id=r.fighter_b_id
WHERE r.is_active=1 ORDER BY r.rivalry_heat DESC LIMIT 10
'''):
    print(f'  {r[3]:20s} vs {r[4]:20s} {r[0]:20s} heat={r[1]} fights={r[2]}')
print()

# 8. Promotions + finances
print('=== 8. PROMOTIONS + FINANCES ===')
print(f'{"Promo":40s} {"Tier":8s} {"Cash":>15s} {"State":12s} {"Roster":>7s} {"Txns":>6s}')
print('-' * 95)
for r in c.execute('''
SELECT p.promotion_id, p.name, p.size_tier, p.current_cash, p.financial_state,
       COUNT(DISTINCT f.fighter_id) as roster,
       (SELECT COUNT(*) FROM finance_transactions ft WHERE ft.promotion_id=p.promotion_id) as txns
FROM promotions p
LEFT JOIN fighters f ON f.current_promotion_id=p.promotion_id AND f.is_active=1 AND f.is_retired=0
GROUP BY p.promotion_id ORDER BY p.promotion_id
'''):
    print(f'{r[1]:40s} {r[2]:8s} ${r[3] or 0:>13,.0f} {r[4]:12s} {r[5]:>7d} {r[6]:>6d}')
print()

# 9. Events + fight results
print('=== 9. EVENTS + FIGHT RESULTS ===')
n_events = c.execute('SELECT COUNT(*) FROM events').fetchone()[0]
n_completed = c.execute("SELECT COUNT(*) FROM events WHERE status='completed'").fetchone()[0]
n_fights = c.execute('SELECT COUNT(*) FROM fights').fetchone()[0]
print(f'Events: {baseline["counts"]["events"]} → {n_events} (+{n_events - baseline["counts"]["events"]})')
print(f'Completed: {n_completed}')
print(f'Fights: {baseline["counts"]["fights"]} → {n_fights} (+{n_fights - baseline["counts"]["fights"]})')
print('Result distribution (this year):')
for r in c.execute('''
SELECT result_type, COUNT(*) FROM fights 
WHERE created_at > datetime('now', '-5 minutes')
GROUP BY result_type ORDER BY 2 DESC
'''):
    print(f'  {r[0]:25s} {r[1]}')
print()

# 10. Show ratings
print('=== 10. SHOW RATINGS ===')
for r in c.execute('''
SELECT p.name, AVG(sr.overall_rating), COUNT(*), MIN(sr.overall_rating), MAX(sr.overall_rating)
FROM show_ratings sr JOIN events e ON e.event_id=sr.event_id
JOIN promotions p ON p.promotion_id=e.promotion_id
GROUP BY p.promotion_id ORDER BY AVG(sr.overall_rating) DESC
'''):
    print(f'  {r[0]:40s} avg={r[1]:.1f} n={r[2]} min={r[3]} max={r[4]}')
print()

# 11. Tick health
print('=== 11. TICK HEALTH ===')
for r in c.execute('''
SELECT health_status, COUNT(*), ROUND(AVG(tick_duration_ms),1), MAX(tick_duration_ms)
FROM simulation_tick_health GROUP BY health_status
'''):
    print(f'  {r[0]:10s} count={r[1]} avg_ms={r[2]} max_ms={r[3]}')
print()

# 12. Rival AI behavior
print('=== 12. RIVAL AI BEHAVIOR ===')
n_rival_mem = c.execute('SELECT COUNT(*) FROM rival_ai_memory').fetchone()[0]
print(f'Rival AI memories: {n_rival_mem}')
if n_rival_mem > 0:
    print('By type:')
    for r in c.execute('SELECT memory_type, COUNT(*) FROM rival_ai_memory GROUP BY memory_type ORDER BY 2 DESC'):
        print(f'  {r[0]:25s} {r[1]}')
print()

# 13. Gym movements
print('=== 13. GYM MOVEMENTS ===')
# Check if any fighters changed gyms (compare current_gym_id to original)
# We don't have the original stored, but we can check if any memory links of type 'old_gyms' exist
n_gym_links = c.execute("SELECT COUNT(*) FROM fighter_memory_links WHERE link_type='old_gyms' OR link_type='former_teammates'").fetchone()[0]
print(f'Gym change memory links: {n_gym_links} (writers exist but may not fire without gym-transfer flow)')
print()

# 14. Injuries
print('=== 14. INJURIES ===')
n_inj = c.execute('SELECT COUNT(*) FROM injuries').fetchone()[0]
n_active_inj = c.execute('SELECT COUNT(*) FROM injuries WHERE is_active=1').fetchone()[0]
print(f'Injuries: {baseline["counts"]["injuries"]} → {n_inj} (+{n_inj - baseline["counts"]["injuries"]})')
print(f'Active: {n_active_inj}')
print()

# 15. Staff
print('=== 15. STAFF ===')
n_staff = c.execute('SELECT COUNT(*) FROM staff').fetchone()[0]
print(f'Staff: {baseline["counts"]["staff"]} → {n_staff} (+{n_staff - baseline["counts"]["staff"]})')
print()

# Save analysis
analysis = {
    'sim_date_start': baseline['sim_date'],
    'sim_date_end': sim_date,
    'ticks': tick,
    'population': {'fighters': n_fighters, 'active': n_active, 'retired': n_retired, 'regen': n_regen},
    'events': n_events,
    'fights': n_fights,
    'champions': n_champs,
    'rivalries': n_riv,
    'news': n_news,
    'memory_resurfacing_news': n_mem_news,
    'memory_links': n_mem_links,
    'rival_ai_memories': n_rival_mem,
    'injuries': n_inj,
}
with open('data/post_1yr_sim.json', 'w') as f:
    json.dump(analysis, f, indent=2, default=str)

c.close()
print('Analysis saved to data/post_1yr_sim.json')
