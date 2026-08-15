#!/usr/bin/env python3
"""Capture pre-sim baseline metrics for 1-year analysis."""
import sqlite3, json, sys
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "cage_empire.db"
c = sqlite3.connect(str(DB))

baseline = {}

# Top fighters
baseline['top_fighters'] = [dict(zip(['fighter_id','name','elo','wins','losses','potential'], r)) for r in c.execute('''
SELECT r.fighter_id, f.first_name || ' ' || f.last_name, r.rating,
       fc.record_wins, fc.record_losses, fc.potential
FROM rankings r JOIN fighters f ON f.fighter_id=r.fighter_id
JOIN fighter_career fc ON fc.fighter_id=r.fighter_id
ORDER BY r.rating DESC LIMIT 20
''')]

# Champions
baseline['champions'] = [dict(zip(['title_id','promo','wc','champ','since'], r)) for r in c.execute('''
SELECT t.title_id, p.name, wc.name,
       f.first_name || ' ' || f.last_name, t.champion_since_date
FROM titles t JOIN promotions p ON p.promotion_id=t.promotion_id
JOIN weight_classes wc ON wc.weight_class_id=t.weight_class_id
LEFT JOIN fighters f ON f.fighter_id=t.current_champion_fighter_id
WHERE t.current_champion_fighter_id IS NOT NULL ORDER BY p.name
''')]

# Promotions
baseline['promotions'] = [dict(zip(['pid','name','tier','cash','state','roster'], r)) for r in c.execute('''
SELECT p.promotion_id, p.name, p.size_tier, p.current_cash, p.financial_state,
       COUNT(f.fighter_id) FROM promotions p
LEFT JOIN fighters f ON f.current_promotion_id=p.promotion_id AND f.is_active=1 AND f.is_retired=0
GROUP BY p.promotion_id ORDER BY p.promotion_id
''')]

# Counts
baseline['counts'] = {
    'fighters': c.execute('SELECT COUNT(*) FROM fighters').fetchone()[0],
    'active': c.execute('SELECT COUNT(*) FROM fighters WHERE is_active=1 AND is_retired=0').fetchone()[0],
    'retired': c.execute('SELECT COUNT(*) FROM fighters WHERE is_retired=1').fetchone()[0],
    'events': c.execute('SELECT COUNT(*) FROM events').fetchone()[0],
    'fights': c.execute('SELECT COUNT(*) FROM fights').fetchone()[0],
    'titles': c.execute('SELECT COUNT(*) FROM titles').fetchone()[0],
    'champions': c.execute('SELECT COUNT(*) FROM titles WHERE current_champion_fighter_id IS NOT NULL').fetchone()[0],
    'rivalries': c.execute('SELECT COUNT(*) FROM rivalries').fetchone()[0],
    'news': c.execute('SELECT COUNT(*) FROM news_items').fetchone()[0],
    'staff': c.execute('SELECT COUNT(*) FROM staff').fetchone()[0],
    'finance_txns': c.execute('SELECT COUNT(*) FROM finance_transactions').fetchone()[0],
    'free_agents': c.execute('SELECT COUNT(*) FROM fighters WHERE is_active=1 AND is_retired=0 AND current_promotion_id IS NULL').fetchone()[0],
    'fight_history': c.execute('SELECT COUNT(*) FROM fight_history').fetchone()[0],
    'rankings': c.execute('SELECT COUNT(*) FROM rankings').fetchone()[0],
    'memory_links': c.execute('SELECT COUNT(*) FROM fighter_memory_links').fetchone()[0],
    'regen_lineage': c.execute('SELECT COUNT(*) FROM regen_lineage').fetchone()[0],
    'injuries': c.execute('SELECT COUNT(*) FROM injuries').fetchone()[0],
}

# Sim state
baseline['sim_date'] = c.execute('SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1').fetchone()[0]
baseline['tick_counter'] = c.execute('SELECT tick_counter FROM simulation_clock WHERE clock_id=1').fetchone()[0]

# Rivalries
baseline['rivalries'] = [dict(zip(['rid','type','heat','active','a','b'], r)) for r in c.execute('''
SELECT r.rivalry_id, r.rivalry_type, r.rivalry_heat, r.is_active,
       fa.first_name || ' ' || fa.last_name, fb.first_name || ' ' || fb.last_name
FROM rivalries r
JOIN fighters fa ON fa.fighter_id=r.fighter_a_id
JOIN fighters fb ON fb.fighter_id=r.fighter_b_id
WHERE r.is_active=1 ORDER BY r.rivalry_heat DESC LIMIT 20
''')]

# Age distribution
baseline['age_dist'] = {}
for r in c.execute('''
SELECT CASE
  WHEN CAST(strftime('%Y','2026-07-20') AS INT) - CAST(strftime('%Y',date_of_birth) AS INT) < 25 THEN '18-24'
  WHEN CAST(strftime('%Y','2026-07-20') AS INT) - CAST(strftime('%Y',date_of_birth) AS INT) < 30 THEN '25-29'
  WHEN CAST(strftime('%Y','2026-07-20') AS INT) - CAST(strftime('%Y',date_of_birth) AS INT) < 35 THEN '30-34'
  WHEN CAST(strftime('%Y','2026-07-20') AS INT) - CAST(strftime('%Y',date_of_birth) AS INT) < 40 THEN '35-39'
  ELSE '40+' END, COUNT(*)
FROM fighters WHERE is_active=1 GROUP BY 1
'''):
    baseline['age_dist'][r[0]] = r[1]

# Potential distribution
baseline['potential_dist'] = {}
for r in c.execute('''
SELECT CASE
  WHEN potential >= 80 THEN 'Elite(80+)'
  WHEN potential >= 70 THEN 'Contender(70-79)'
  WHEN potential >= 60 THEN 'Above(60-69)'
  WHEN potential >= 50 THEN 'Average(50-59)'
  WHEN potential >= 40 THEN 'Below(40-49)'
  ELSE 'Low(<40)' END, COUNT(*)
FROM fighter_career GROUP BY 1
'''):
    baseline['potential_dist'][r[0]] = r[1]

with open('data/baseline_1yr_sim.json', 'w') as f:
    json.dump(baseline, f, indent=2, default=str)

print('Baseline saved to data/baseline_1yr_sim.json')
print(f'sim_date={baseline["sim_date"]} tick={baseline["tick_counter"]}')
print(f'fighters={baseline["counts"]["fighters"]} active={baseline["counts"]["active"]} retired={baseline["counts"]["retired"]}')
print(f'champions={baseline["counts"]["champions"]} rivalries={baseline["counts"]["rivalries"]} free_agents={baseline["counts"]["free_agents"]}')
c.close()
