#!/usr/bin/env python3
"""Audit the seeded world DB for believability + balance.

Checks:
  1. Geographic realism (nations/regions/cities consistent)
  2. Fighter potential distribution (not everyone maxed)
  3. Attribute + archetype realism (balanced, not all 50)
  4. Personality/mental attribute balance
  5. Title belt coverage (every active WC×promo has a title)
  6. Bio uniqueness + cliché check
  7. Career record realism (records match career stage)
  8. Name uniqueness (no duplicate fighter names)
  9. Missing data audit
"""
import sqlite3
import sys
from pathlib import Path
from collections import Counter

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    print("=" * 70)
    print("CAGE EMPIRE World Audit")
    print("=" * 70)

    # ----------------------------------------------------------------
    # 1. Geographic realism
    # ----------------------------------------------------------------
    print("\n--- 1. Geographic Realism ---")
    print("\nNations (with region/city/gym counts):")
    for r in conn.execute(
        "SELECT n.name, n.language, "
        "  (SELECT COUNT(*) FROM regions WHERE nation_id=n.nation_id), "
        "  (SELECT COUNT(*) FROM cities WHERE nation_id=n.nation_id), "
        "  (SELECT COUNT(*) FROM gyms WHERE nation_id=n.nation_id), "
        "  (SELECT COUNT(*) FROM fighters WHERE birth_nation_id=n.nation_id) "
        "FROM nations n ORDER BY (SELECT COUNT(*) FROM fighters WHERE birth_nation_id=n.nation_id) DESC"
    ).fetchall():
        print(f"  {r[0]:<25} lang={r[1]:<12} regions={r[2]} cities={r[3]} gyms={r[4]} fighters={r[5]}")

    # Check: every region has a nation_id
    orphan_regions = conn.execute(
        "SELECT COUNT(*) FROM regions WHERE nation_id IS NULL"
    ).fetchone()[0]
    print(f"\nOrphan regions (no nation_id): {orphan_regions}")

    # Check: every city's nation matches its region's nation
    mismatches = conn.execute(
        "SELECT COUNT(*) FROM cities c JOIN regions r ON c.region_id=r.region_id "
        "WHERE c.nation_id != r.nation_id"
    ).fetchone()[0]
    print(f"City/region nation mismatches: {mismatches}")

    # ----------------------------------------------------------------
    # 2. Fighter potential distribution
    # ----------------------------------------------------------------
    print("\n--- 2. Fighter Potential Distribution ---")
    pot_dist = conn.execute(
        "SELECT "
        "  CASE "
        "    WHEN potential >= 70 THEN 'elite (70-90)' "
        "    WHEN potential >= 50 THEN 'solid (50-69)' "
        "    WHEN potential >= 25 THEN 'limited (25-49)' "
        "    ELSE 'very low (<25)' "
        "  END AS tier, "
        "  COUNT(*) "
        "FROM fighter_career GROUP BY tier ORDER BY MIN(potential)"
    ).fetchall()
    total = sum(r[1] for r in pot_dist)
    print(f"\nTotal fighters: {total}")
    for tier, n in pot_dist:
        pct = 100 * n / total
        print(f"  {tier}: {n} ({pct:.1f}%)")
    print("  Target: ~10% elite, ~30% solid, ~60% limited")

    # Potential stats
    stats = conn.execute(
        "SELECT MIN(potential), MAX(potential), AVG(potential), "
        "COUNT(DISTINCT potential) FROM fighter_career"
    ).fetchone()
    print(f"\n  Min: {stats[0]}, Max: {stats[1]}, Avg: {stats[2]:.1f}, Distinct values: {stats[3]}")

    # ----------------------------------------------------------------
    # 3. Attribute + archetype realism
    # ----------------------------------------------------------------
    print("\n--- 3. Attribute + Archetype Realism ---")
    # Average attribute values across all fighters (should be ~50 with variation)
    print("\nAttribute averages (should be ~45-55, not all 50):")
    attr_cols = [r[1] for r in conn.execute("PRAGMA table_info(fighter_attributes)").fetchall()
                 if r[1] not in ("fighter_attribute_id", "fighter_id", "created_at", "updated_at")]
    for col in attr_cols[:10]:  # sample first 10
        s = conn.execute(f"SELECT AVG({col}), MIN({col}), MAX({col}) FROM fighter_attributes").fetchone()
        print(f"  {col:<25} avg={s[0]:.1f} min={s[1]} max={s[2]}")

    # Archetype distribution
    print("\nStyle archetype distribution:")
    for r in conn.execute(
        "SELECT sa.name, COUNT(*) FROM fighters f "
        "JOIN style_archetypes sa ON sa.style_archetype_id=f.fight_style_archetype_id "
        "GROUP BY sa.name ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"  {r[0]:<25} {r[1]}")

    # Personality archetype distribution
    print("\nPersonality archetype distribution:")
    for r in conn.execute(
        "SELECT pa.name, COUNT(*) FROM fighters f "
        "JOIN personality_archetypes pa ON pa.personality_archetype_id=f.personality_archetype_id "
        "GROUP BY pa.name ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"  {r[0]:<25} {r[1]}")

    # ----------------------------------------------------------------
    # 4. Personality/mental attribute balance
    # ----------------------------------------------------------------
    print("\n--- 4. Personality/Mental Attribute Balance ---")
    print("\nPersonality averages (should vary, not all 50):")
    pers_cols = [r[1] for r in conn.execute("PRAGMA table_info(fighter_personality)").fetchall()
                 if r[1] not in ("fighter_personality_id", "fighter_id", "created_at", "updated_at")]
    for col in pers_cols[:10]:  # sample first 10
        s = conn.execute(f"SELECT AVG({col}), MIN({col}), MAX({col}) FROM fighter_personality").fetchone()
        print(f"  {col:<25} avg={s[0]:.1f} min={s[1]} max={s[2]}")

    # ----------------------------------------------------------------
    # 5. Title belt coverage
    # ----------------------------------------------------------------
    print("\n--- 5. Title Belt Coverage ---")
    # For every (promo, wc) combo that has fighters, is there a title?
    combos_with_fighters = conn.execute(
        "SELECT DISTINCT p.promotion_id, p.name, f.weight_class_id, wc.name, wc.gender "
        "FROM fighters f "
        "JOIN promotions p ON p.promotion_id=f.current_promotion_id "
        "JOIN weight_classes wc ON wc.weight_class_id=f.weight_class_id "
        "WHERE f.current_promotion_id IS NOT NULL"
    ).fetchall()
    titles = conn.execute(
        "SELECT promotion_id, weight_class_id, is_vacant, current_champion_fighter_id "
        "FROM titles"
    ).fetchall()
    title_map = {(t[0], t[1]): t for t in titles}
    missing = []
    for pid, pname, wid, wcname, wcgender in combos_with_fighters:
        if (pid, wid) not in title_map:
            missing.append((pname, wcname, wcgender))
    print(f"\n  (promo, wc) combos with fighters: {len(combos_with_fighters)}")
    print(f"  Titles created: {len(titles)}")
    print(f"  Missing titles: {len(missing)}")
    if missing:
        for m in missing[:10]:
            print(f"    MISSING: {m[0]} / {m[1]} ({m[2]})")
    # Vacancy rate
    n_vacant = sum(1 for t in titles if t[2])
    print(f"  Vacant titles: {n_vacant}/{len(titles)} ({100*n_vacant/len(titles):.1f}%)")

    # ----------------------------------------------------------------
    # 6. Bio uniqueness + cliché check
    # ----------------------------------------------------------------
    print("\n--- 6. Bio Uniqueness + Cliché Check ---")
    bios = conn.execute("SELECT fighter_id, bio_text, bio_tone FROM fighter_bios").fetchall()
    print(f"\n  Total bios: {len(bios)}")
    # Check for duplicates
    bio_texts = [b[1] for b in bios]
    dupes = [t for t, c in Counter(bio_texts).items() if c > 1]
    print(f"  Duplicate bios: {len(dupes)}")
    if dupes:
        for d in dupes[:3]:
            print(f"    DUP: {d[:100]}...")
    # Cliché phrases to check
    cliches = [
        "the real deal", "the next big thing", "force to be reckoned with",
        "household name", "seen it all", "been around the block",
        "what could have been", "winding down", "the tank",
        "comes to entertain", "must-watch", "shockwaves",
    ]
    print("\n  Cliché phrase usage:")
    for cliche in cliches:
        n = sum(1 for b in bios if cliche.lower() in b[1].lower())
        if n > 0:
            print(f"    '{cliche}': {n} bios")
    # Bio tone distribution
    print("\n  Bio tone distribution:")
    for r in conn.execute(
        "SELECT bio_tone, COUNT(*) FROM fighter_bios GROUP BY bio_tone ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"    {r[0]:<25} {r[1]}")
    # Sample 5 bios
    print("\n  Sample bios:")
    for b in bios[:5]:
        f_row = conn.execute(
            "SELECT first_name, last_name FROM fighters WHERE fighter_id=?", (b[0],)
        ).fetchone()
        print(f"    [{b[2]}] {f_row[0]} {f_row[1]}:")
        print(f"      {b[1][:200]}...")

    # ----------------------------------------------------------------
    # 7. Career record realism
    # ----------------------------------------------------------------
    print("\n--- 7. Career Record Realism ---")
    # Check: do records match career stage (inferred from age)?
    print("\n  Age vs total fights (should increase with age):")
    for r in conn.execute(
        "SELECT "
        "  CASE "
        "    WHEN date_of_birth >= '2004-01-01' THEN '18-22 (prospect)' "
        "    WHEN date_of_birth >= '1999-01-01' THEN '23-27 (developing)' "
        "    WHEN date_of_birth >= '1994-01-01' THEN '28-32 (prime)' "
        "    WHEN date_of_birth >= '1989-01-01' THEN '33-37 (declining)' "
        "    ELSE '38-43 (veteran)' "
        "  END AS stage, "
        "  AVG(fc.record_wins + fc.record_losses + fc.record_draws) AS avg_fights, "
        "  AVG(fc.record_wins) AS avg_wins, "
        "  AVG(fc.record_losses) AS avg_losses, "
        "  COUNT(*) "
        "FROM fighters f JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
        "WHERE f.is_retired=0 "
        "GROUP BY stage ORDER BY stage"
    ).fetchall():
        print(f"    {r[0]:<25} avg_fights={r[1]:.1f} wins={r[2]:.1f} losses={r[3]:.1f} n={r[4]}")

    # Win rate by potential (higher potential = higher win rate)
    print("\n  Win rate by potential tier (should increase with potential):")
    for r in conn.execute(
        "SELECT "
        "  CASE "
        "    WHEN potential >= 70 THEN 'elite' "
        "    WHEN potential >= 50 THEN 'solid' "
        "    ELSE 'limited' "
        "  END AS tier, "
        "  AVG(record_wins * 1.0 / (record_wins + record_losses + 0.01)) AS win_rate, "
        "  COUNT(*) "
        "FROM fighter_career WHERE record_wins + record_losses > 0 "
        "GROUP BY tier ORDER BY MIN(potential)"
    ).fetchall():
        print(f"    {r[0]:<15} win_rate={r[1]:.3f} n={r[2]}")

    # ----------------------------------------------------------------
    # 8. Name uniqueness
    # ----------------------------------------------------------------
    print("\n--- 8. Name Uniqueness ---")
    names = conn.execute(
        "SELECT first_name, last_name, nickname FROM fighters WHERE is_retired=0"
    ).fetchall()
    full_names = [f"{n[0]} {n[1]}" for n in names]
    name_dupes = [t for t, c in Counter(full_names).items() if c > 1]
    print(f"  Total active fighters: {len(names)}")
    print(f"  Duplicate full names: {len(name_dupes)}")
    if name_dupes:
        for d in name_dupes[:5]:
            print(f"    DUP: {d}")

    # ----------------------------------------------------------------
    # 9. Missing data audit
    # ----------------------------------------------------------------
    print("\n--- 9. Missing Data Audit ---")
    checks = [
        ("Fighters without fighter_attributes", "SELECT COUNT(*) FROM fighters f LEFT JOIN fighter_attributes fa ON fa.fighter_id=f.fighter_id WHERE fa.fighter_id IS NULL AND f.is_retired=0"),
        ("Fighters without fighter_personality", "SELECT COUNT(*) FROM fighters f LEFT JOIN fighter_personality fp ON fp.fighter_id=f.fighter_id WHERE fp.fighter_id IS NULL AND f.is_retired=0"),
        ("Fighters without fighter_career", "SELECT COUNT(*) FROM fighters f LEFT JOIN fighter_career fc ON fc.fighter_id=f.fighter_id WHERE fc.fighter_id IS NULL"),
        ("Fighters without rankings", "SELECT COUNT(*) FROM fighters f LEFT JOIN rankings r ON r.fighter_id=f.fighter_id WHERE r.fighter_id IS NULL AND f.is_retired=0"),
        ("Fighters without gym", "SELECT COUNT(*) FROM fighters WHERE current_gym_id IS NULL AND is_retired=0"),
        ("Fighters without weight_class", "SELECT COUNT(*) FROM fighters WHERE weight_class_id IS NULL"),
        ("Fighters without DOB", "SELECT COUNT(*) FROM fighters WHERE date_of_birth IS NULL"),
        ("Fighters without birth_nation", "SELECT COUNT(*) FROM fighters WHERE birth_nation_id IS NULL"),
        ("Champions without contracts", "SELECT COUNT(*) FROM titles t JOIN fighters f ON f.fighter_id=t.current_champion_fighter_id LEFT JOIN fighter_contracts fc ON fc.fighter_id=f.fighter_id WHERE fc.fighter_id IS NULL AND t.current_champion_fighter_id IS NOT NULL"),
        ("Gyms without staff (coaches)", "SELECT COUNT(*) FROM gyms g WHERE NOT EXISTS (SELECT 1 FROM staff s WHERE s.role_type='coach' AND s.nation_id=g.nation_id)"),
        ("Events without venue", "SELECT COUNT(*) FROM events WHERE venue_id IS NULL"),
        ("Events without market", "SELECT COUNT(*) FROM events WHERE market_id IS NULL"),
        ("Fights without winner", "SELECT COUNT(*) FROM fights WHERE winner_fighter_id IS NULL AND result_type != 'draw'"),
        ("Free agents with contracts", "SELECT COUNT(*) FROM fighters f JOIN fighter_contracts fc ON fc.fighter_id=f.fighter_id WHERE f.current_promotion_id IS NULL"),
    ]
    for label, q in checks:
        n = conn.execute(q).fetchone()[0]
        flag = "  ⚠️" if n > 0 else "  ✓"
        print(f"{flag} {label}: {n}")

    # ----------------------------------------------------------------
    # 10. Overall stats
    # ----------------------------------------------------------------
    print("\n--- 10. Overall World Stats ---")
    stats = [
        ("nations", "Nations"),
        ("regions", "Regions"),
        ("cities", "Cities"),
        ("venues", "Venues"),
        ("markets", "Markets"),
        ("weight_classes", "Weight classes"),
        ("name_pools", "Name pool entries"),
        ("gyms", "Gyms"),
        ("promotions", "Promotions"),
        ("staff", "Staff"),
        ("fighters", "Fighters (active)"),
        ("fighter_bios", "Fighter bios"),
        ("hall_of_fame", "Hall of Fame"),
        ("events", "Events"),
        ("fights", "Fights"),
        ("fight_history", "Fight history rows"),
        ("titles", "Titles"),
        ("contracts", "Contracts"),
        ("injuries", "Injuries"),
        ("news_items", "News items"),
    ]
    for table, label in stats:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {label}: {n}")

    print("\n" + "=" * 70)
    conn.close()


if __name__ == "__main__":
    main()
