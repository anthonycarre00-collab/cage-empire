#!/usr/bin/env python3
"""Deep forensic audit of the seeded world DB.

Goes beyond audit_world.py — checks:
  1. Archetype attribute realism (do wrestlers actually have high wrestling?)
  2. Gym specialization matching region style preferences
  3. Champion quality (are champions actually the best in their WC?)
  4. Free agent count + quality (enough for scouting?)
  5. Stance/handedness distribution
  6. National tendencies (do Brazilian fighters use BJJ archetypes?)
  7. Contract salary realism
  8. Injury type vs fighter activity
  9. HoF legend quality
  10. News item quality
  11. Regen function gaps (static analysis)
"""
import sqlite3
import sys
from pathlib import Path
from collections import Counter, defaultdict

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    print("=" * 70)
    print("CAGE EMPIRE Deep Forensic Audit")
    print("=" * 70)

    # ----------------------------------------------------------------
    # 1. Archetype attribute realism
    # ----------------------------------------------------------------
    print("\n--- 1. Archetype Attribute Realism ---")
    print("\n  Do wrestlers have high takedown_offense? Do strikers have high punch_power?")
    for arch_name, key_attr in [
        ("Wrestler", "takedown_offense"),
        ("Striker", "punch_power"),
        ("Grappler", "submission_offense"),
        ("Submission Specialist", "submission_offense"),
        ("Brawler", "punch_power"),
        ("Counter-Striker", "head_movement"),
        ("Balanced", "fight_iq"),
    ]:
        row = conn.execute(
            f"SELECT AVG(fa.{key_attr}), MIN(fa.{key_attr}), MAX(fa.{key_attr}), COUNT(*) "
            f"FROM fighters f "
            f"JOIN fighter_attributes fa ON fa.fighter_id=f.fighter_id "
            f"JOIN style_archetypes sa ON sa.style_archetype_id=f.fight_style_archetype_id "
            f"WHERE sa.name=?",
            (arch_name,),
        ).fetchone()
        # Compare to overall average
        overall = conn.execute(f"SELECT AVG(fa.{key_attr}) FROM fighter_attributes fa").fetchone()[0]
        flag = "✓" if row[0] > overall + 3 else ("⚠️" if row[0] < overall else "✓")
        print(f"  {flag} {arch_name:<25} {key_attr:<20} avg={row[0]:.1f} (overall={overall:.1f}) min={row[1]} max={row[2]} n={row[3]}")

    # ----------------------------------------------------------------
    # 2. Gym specialization vs region style
    # ----------------------------------------------------------------
    print("\n--- 2. Gym Specialization vs Region Style ---")
    # Check if gyms in wrestling-heavy regions have higher development_focus
    print("\n  Do gyms in wrestling regions have different specs than BJJ regions?")
    for style_keyword, label in [("wrestling", "Wrestling regions"), ("bjj", "BJJ regions"), ("striking", "Striking regions")]:
        row = conn.execute(
            "SELECT AVG(g.facility_quality), AVG(g.development_focus), AVG(g.sparring_depth), COUNT(*) "
            "FROM gyms g JOIN regions r ON g.region_id=r.region_id "
            "WHERE r.style_preferences LIKE ?",
            (f"%{style_keyword}%",),
        ).fetchone()
        print(f"  {label:<25} facility={row[0]:.1f} dev_focus={row[1]:.1f} sparring={row[2]:.1f} n={row[3]}")

    # ----------------------------------------------------------------
    # 3. Champion quality
    # ----------------------------------------------------------------
    print("\n--- 3. Champion Quality (are champions the best in their WC?) ---")
    champions = conn.execute(
        "SELECT t.current_champion_fighter_id, t.weight_class_id, t.promotion_id, "
        "t.title_defenses_count, r.rating "
        "FROM titles t "
        "JOIN rankings r ON r.fighter_id=t.current_champion_fighter_id AND r.weight_class_id=t.weight_class_id "
        "WHERE t.current_champion_fighter_id IS NOT NULL"
    ).fetchall()
    n_champ_top = 0
    n_champ_top3 = 0
    for champ_id, wc_id, promo_id, defenses, champ_rating in champions:
        # Get top 3 fighters by rating in this WC + promo
        top3 = conn.execute(
            "SELECT f.fighter_id, r.rating FROM fighters f "
            "JOIN rankings r ON r.fighter_id=f.fighter_id "
            "WHERE r.weight_class_id=? AND r.promotion_id=? "
            "ORDER BY r.rating DESC LIMIT 3",
            (wc_id, promo_id),
        ).fetchall()
        if top3 and top3[0][0] == champ_id:
            n_champ_top += 1
        if any(t[0] == champ_id for t in top3):
            n_champ_top3 += 1
    print(f"  Champions who are #1 in their WC+promo: {n_champ_top}/{len(champions)} ({100*n_champ_top/len(champions):.1f}%)")
    print(f"  Champions in top 3 of their WC+promo:   {n_champ_top3}/{len(champions)} ({100*n_champ_top3/len(champions):.1f}%)")
    if n_champ_top < len(champions) * 0.7:
        print("  ⚠️  Less than 70% of champions are the top-ranked fighter — title assignment may not reflect rankings")

    # ----------------------------------------------------------------
    # 4. Free agent count + quality
    # ----------------------------------------------------------------
    print("\n--- 4. Free Agent Count + Quality (for scouting) ---")
    fa_stats = conn.execute(
        "SELECT COUNT(*), "
        "  SUM(CASE WHEN fc.potential >= 70 THEN 1 ELSE 0 END), "
        "  SUM(CASE WHEN fc.potential >= 50 AND fc.potential < 70 THEN 1 ELSE 0 END), "
        "  SUM(CASE WHEN fc.potential < 50 THEN 1 ELSE 0 END), "
        "  AVG(fc.potential) "
        "FROM fighters f "
        "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
        "WHERE f.current_promotion_id IS NULL AND f.is_active=1 AND f.is_retired=0"
    ).fetchone()
    print(f"  Total free agents: {fa_stats[0]}")
    print(f"  Elite potential (70+): {fa_stats[1]} ({100*fa_stats[1]/fa_stats[0]:.1f}%)")
    print(f"  Solid potential (50-69): {fa_stats[2]} ({100*fa_stats[2]/fa_stats[0]:.1f}%)")
    print(f"  Limited potential (<50): {fa_stats[3]} ({100*fa_stats[3]/fa_stats[0]:.1f}%)")
    print(f"  Average potential: {fa_stats[4]:.1f}")
    # By career stage
    print("\n  Free agents by age group:")
    for r in conn.execute(
        "SELECT "
        "  CASE "
        "    WHEN date_of_birth >= '2004-01-01' THEN '18-22 (prospect)' "
        "    WHEN date_of_birth >= '1999-01-01' THEN '23-27 (developing)' "
        "    WHEN date_of_birth >= '1994-01-01' THEN '28-32 (prime)' "
        "    WHEN date_of_birth >= '1989-01-01' THEN '33-37 (declining)' "
        "    ELSE '38+ (veteran)' "
        "  END AS stage, COUNT(*) "
        "FROM fighters WHERE current_promotion_id IS NULL AND is_retired=0 "
        "GROUP BY stage ORDER BY stage"
    ).fetchall():
        print(f"    {r[0]}: {r[1]}")

    # ----------------------------------------------------------------
    # 5. Stance/handedness distribution
    # ----------------------------------------------------------------
    print("\n--- 5. Stance/Handedness Distribution ---")
    print("\n  Stance (target ~80% orthodox, 15% southpaw, 5% switch):")
    for r in conn.execute(
        "SELECT stance, COUNT(*) FROM fighters GROUP BY stance ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"    {r[0]}: {r[1]}")
    print("\n  Handedness (target ~85% right, 10% left, 5% ambidextrous):")
    for r in conn.execute(
        "SELECT handedness, COUNT(*) FROM fighters GROUP BY handedness ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"    {r[0]}: {r[1]}")

    # ----------------------------------------------------------------
    # 6. National tendencies
    # ----------------------------------------------------------------
    print("\n--- 6. National Tendencies (archetype distribution by nation) ---")
    # Do Brazilian fighters use more Grappler/Submission archetypes?
    for nation, expected_arch in [
        ("Brazil", "Grappler"),
        ("Dagestan", "Wrestler"),
        ("United States", "Wrestler"),
        ("Japan", "Balanced"),
        ("Netherlands", "Striker"),
    ]:
        row = conn.execute(
            "SELECT sa.name, COUNT(*) FROM fighters f "
            "JOIN style_archetypes sa ON sa.style_archetype_id=f.fight_style_archetype_id "
            "WHERE f.birth_nation_id=(SELECT nation_id FROM nations WHERE name=?) "
            "GROUP BY sa.name ORDER BY COUNT(*) DESC LIMIT 1",
            (nation,),
        ).fetchone()
        total = conn.execute(
            "SELECT COUNT(*) FROM fighters WHERE birth_nation_id="
            "(SELECT nation_id FROM nations WHERE name=?)",
            (nation,),
        ).fetchone()[0]
        pct = 100 * row[1] / total if total > 0 else 0
        print(f"  {nation:<20} top archetype: {row[0]} ({row[1]}/{total} = {pct:.0f}%)")

    # ----------------------------------------------------------------
    # 7. Contract salary realism
    # ----------------------------------------------------------------
    print("\n--- 7. Contract Salary Realism ---")
    salary_stats = conn.execute(
        "SELECT MIN(salary), MAX(salary), AVG(salary), "
        "  SUM(CASE WHEN salary < 20000 THEN 1 ELSE 0 END), "
        "  SUM(CASE WHEN salary >= 20000 AND salary < 100000 THEN 1 ELSE 0 END), "
        "  SUM(CASE WHEN salary >= 100000 AND salary < 300000 THEN 1 ELSE 0 END), "
        "  SUM(CASE WHEN salary >= 300000 THEN 1 ELSE 0 END) "
        "FROM contracts WHERE status='active'"
    ).fetchone()
    print(f"  Min: ${salary_stats[0]:,}  Max: ${salary_stats[1]:,}  Avg: ${salary_stats[2]:,.0f}")
    print(f"  <$20k (entry):       {salary_stats[3]}")
    print(f"  $20k-$100k (mid):    {salary_stats[4]}")
    print(f"  $100k-$300k (star):  {salary_stats[5]}")
    print(f"  $300k+ (elite):      {salary_stats[6]}")

    # ----------------------------------------------------------------
    # 8. Injury type vs fighter activity
    # ----------------------------------------------------------------
    print("\n--- 8. Injury Distribution ---")
    print("\n  Injury types:")
    for r in conn.execute(
        "SELECT injury_type, COUNT(*), AVG(severity) FROM injuries GROUP BY injury_type ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"    {r[0]:<30} count={r[1]} avg_severity={r[2]:.1f}")
    print("\n  Active vs healed:")
    for r in conn.execute(
        "SELECT is_active, COUNT(*) FROM injuries GROUP BY is_active"
    ).fetchall():
        print(f"    is_active={r[0]}: {r[1]}")

    # ----------------------------------------------------------------
    # 9. HoF legend quality
    # ----------------------------------------------------------------
    print("\n--- 9. Hall of Fame Legend Quality ---")
    hof_stats = conn.execute(
        "SELECT AVG(fc.record_wins), AVG(fc.record_losses), AVG(fc.title_reigns), "
        "  AVG(fc.potential), COUNT(*) "
        "FROM hall_of_fame hof "
        "JOIN fighter_career fc ON fc.fighter_id=hof.fighter_id"
    ).fetchone()
    print(f"  Count: {hof_stats[4]}")
    print(f"  Avg wins: {hof_stats[0]:.1f}  Avg losses: {hof_stats[1]:.1f}  Avg title reigns: {hof_stats[2]:.1f}")
    print(f"  Avg potential: {hof_stats[3]:.1f}")
    print("\n  Sample HoF entries:")
    for r in conn.execute(
        "SELECT f.first_name, f.last_name, fc.record_wins, fc.record_losses, "
        "fc.title_reigns, hof.inducted_date, substr(hof.career_summary, 1, 120) "
        "FROM hall_of_fame hof "
        "JOIN fighters f ON f.fighter_id=hof.fighter_id "
        "JOIN fighter_career fc ON fc.fighter_id=hof.fighter_id "
        "ORDER BY fc.title_reigns DESC LIMIT 5"
    ).fetchall():
        print(f"    {r[0]} {r[1]}: {r[2]}-{r[3]}, {r[4]} reigns, inducted {r[5]}")
        print(f"      {r[6]}...")

    # ----------------------------------------------------------------
    # 10. News item quality
    # ----------------------------------------------------------------
    print("\n--- 10. News Item Quality ---")
    print("\n  News by topic:")
    for r in conn.execute(
        "SELECT topic, COUNT(*) FROM news_items GROUP BY topic ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"    {r[0]}: {r[1]}")
    print("\n  Sample headlines:")
    for r in conn.execute(
        "SELECT headline FROM news_items ORDER BY RANDOM() LIMIT 8"
    ).fetchall():
        print(f"    {r[0]}")

    # ----------------------------------------------------------------
    # 11. Regen function gaps (static analysis)
    # ----------------------------------------------------------------
    print("\n--- 11. Regen Function Gaps (static analysis) ---")
    print("""
  The generate_fighter() function in app.py has these gaps:

  ⚠️  GAP 1: No bio generation. Regen fighters don't get a fighter_bio
     row. The top 200 seeded fighters have bios, but new regen fighters
     (who could become champions) won't have one. The UI will show "no
     bio available" for them.

  ⚠️  GAP 2: Name pool not region-aware. The regen function picks from
     ALL name pool entries without region filtering. A retiring Brazilian
     fighter could spawn a replacement with a Japanese name. Should
     inherit the retiring fighter's birth_nation_id and use region-
     appropriate names.

  ⚠️  GAP 3: No gym assignment. Regen fighters enter with
     current_gym_id=NULL. Task 16 (training camps) requires a gym —
     regen fighters can't participate in camps until signed + assigned
     a gym. Should assign a gym in the retiring fighter's nation.

  ⚠️  GAP 4: No birth location. birth_city_id and birth_nation_id are
     NULL. Should inherit from retiring fighter or pick from name pool
     region.

  ⚠️  GAP 5: Personality not widened. Regen uses fighter_gen directly,
     which produces the narrow 32-68 range. The Phase 3 widening step
     isn't applied. Regen fighters will have bland personalities.

  ⚠️  GAP 6: No meta-columns. injury_proneness, weight_cut_difficulty,
     consistency, clutch_factor, marketability, fan_friendliness,
     promo_boost all use schema defaults (50). Should randomize for
     variety.
""")

    # ----------------------------------------------------------------
    # 12. Sample fighters (for the doc)
    # ----------------------------------------------------------------
    print("\n--- 12. Sample Fighters (for documentation) ---")
    # Pick one of each: champion, top prospect, journeyman, veteran, free agent
    samples = {
        "Current Champion": conn.execute(
            "SELECT f.fighter_id FROM fighters f "
            "JOIN titles t ON t.current_champion_fighter_id=f.fighter_id "
            "WHERE t.title_defenses_count >= 3 "
            "ORDER BY t.title_defenses_count DESC LIMIT 1"
        ).fetchone(),
        "Top Prospect (elite potential, young)": conn.execute(
            "SELECT f.fighter_id FROM fighters f "
            "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
            "WHERE fc.potential >= 80 AND f.date_of_birth >= '2001-01-01' "
            "ORDER BY fc.potential DESC, f.date_of_birth DESC LIMIT 1"
        ).fetchone(),
        "Prime Contender": conn.execute(
            "SELECT f.fighter_id FROM fighters f "
            "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
            "JOIN rankings r ON r.fighter_id=f.fighter_id "
            "WHERE f.date_of_birth BETWEEN '1994-01-01' AND '1998-01-01' "
            "AND fc.record_wins >= 15 "
            "ORDER BY r.rating DESC LIMIT 1"
        ).fetchone(),
        "Journeyman Veteran": conn.execute(
            "SELECT f.fighter_id FROM fighters f "
            "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
            "WHERE f.date_of_birth BETWEEN '1986-01-01' AND '1990-01-01' "
            "AND fc.record_wins + fc.record_losses >= 30 "
            "ORDER BY fc.record_losses DESC LIMIT 1"
        ).fetchone(),
        "Free Agent (unsigned)": conn.execute(
            "SELECT f.fighter_id FROM fighters f "
            "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
            "WHERE f.current_promotion_id IS NULL AND fc.potential >= 60 "
            "AND f.date_of_birth >= '1999-01-01' "
            "ORDER BY fc.potential DESC LIMIT 1"
        ).fetchone(),
    }
    for label, row in samples.items():
        if row:
            print(f"\n  [{label}]")
            fid = row[0]
            f = conn.execute(
                "SELECT f.first_name, f.last_name, f.nickname, f.gender, f.date_of_birth, "
                "f.height_cm, f.reach_cm, f.stance, f.handedness, "
                "sa.name, pa.name, wc.name, wc.gender, "
                "n.name as nation, g.name as gym, p.name as promo, "
                "fc.record_wins, fc.record_losses, fc.record_draws, "
                "fc.win_streak, fc.loss_streak, fc.career_health, fc.potential, "
                "fc.title_reigns, r.rating "
                "FROM fighters f "
                "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
                "LEFT JOIN style_archetypes sa ON sa.style_archetype_id=f.fight_style_archetype_id "
                "LEFT JOIN personality_archetypes pa ON pa.personality_archetype_id=f.personality_archetype_id "
                "LEFT JOIN weight_classes wc ON wc.weight_class_id=f.weight_class_id "
                "LEFT JOIN nations n ON n.nation_id=f.birth_nation_id "
                "LEFT JOIN gyms g ON g.gym_id=f.current_gym_id "
                "LEFT JOIN promotions p ON p.promotion_id=f.current_promotion_id "
                "LEFT JOIN rankings r ON r.fighter_id=f.fighter_id "
                "WHERE f.fighter_id=?",
                (fid,),
            ).fetchone()
            if f:
                print(f"    Name: {f[0]} {f[1]}{f' \"{f[2]}\"' if f[2] else ''}")
                print(f"    Gender: {f[3]}  DOB: {f[4]}  Age: {2026 - int(f[4][:4])}")
                print(f"    Physical: {f[5]}cm / {f[6]}cm reach / {f[7]} / {f[8]}")
                print(f"    Style: {f[9]}  Personality: {f[10]}")
                print(f"    WC: {f[11]} ({f[12]})  Nation: {f[13]}")
                print(f"    Gym: {f[14]}  Promotion: {f[15]}")
                print(f"    Record: {f[16]}-{f[17]}-{f[18]}  Streak: W{f[19]} L{f[20]}")
                rating_str = f"{f[24]:.0f}" if f[24] is not None else "N/A (free agent)"
                print(f"    Health: {f[21]}  Potential: {f[22]}  Title reigns: {f[23]}  Rating: {rating_str}")
            # Bio if exists
            bio = conn.execute(
                "SELECT bio_text, bio_tone FROM fighter_bios WHERE fighter_id=?", (fid,)
            ).fetchone()
            if bio:
                print(f"    Bio [{bio[1]}]: {bio[0][:150]}...")

    print("\n" + "=" * 70)
    conn.close()


if __name__ == "__main__":
    main()
