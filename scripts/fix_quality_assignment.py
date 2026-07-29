#!/usr/bin/env python3
"""Fix fighter-to-promotion assignment to be QUALITY-BASED, not random.

Real MMA promotion rosters:
  - Major (UFC-level): the BEST fighters — high potential, good records,
    champions. ~60 fighters
  - Mid (Bellator/ONE-level): solid veterans + rising prospects. ~40 each
  - Small (regional): mostly rookies, prospects, lower-potential fighters. ~15 each
  - Free agents: everyone else — the largest pool

Current problem: fighters were assigned by INDEX (first 60 to major,
next 120 to mid, etc.) — completely random quality distribution.
Alpha Combat has fighters with potential=26 alongside potential=89.

This script:
  1. Clears ALL current promotion assignments (everyone becomes a free agent)
  2. Computes a quality score for each fighter (potential + record + age factor)
  3. Sorts fighters by quality score DESC
  4. Assigns the top 60 to major (best fighters)
  5. Assigns next 120 to mid (3 promos × 40)
  6. Assigns next 90 to small (6 promos × 15)
  7. Everyone else stays as free agent
  8. Ensures current champions are on the roster of their title's promotion
  9. Rebuilds interpretation layer
  10. Commits to DB
"""
import sqlite3
import random
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cage_empire.db"


def compute_quality_score(conn, fighter_id):
    """Compute a quality score for assignment purposes.

    Factors:
      - Potential (0-100, weight: 40%)
      - Win rate (wins / total fights, weight: 30%)
      - Title reigns (weight: 20%)
      - Age factor (prime fighters 28-32 get bonus, weight: 10%)
    """
    row = conn.execute("""
        SELECT fc.potential, fc.record_wins, fc.record_losses, fc.record_draws,
               fc.title_reigns, f.date_of_birth
        FROM fighters f
        JOIN fighter_career fc ON f.fighter_id = fc.fighter_id
        WHERE f.fighter_id = ?
    """, (fighter_id,)).fetchone()

    if not row:
        return 0

    potential, wins, losses, draws, title_reigns, dob = row
    potential = potential or 50
    wins = wins or 0
    losses = losses or 0
    draws = draws or 0
    title_reigns = title_reigns or 0
    total = wins + losses + draws

    # Win rate (default 0.5 for 0-0 fighters)
    win_rate = wins / total if total > 0 else 0.5

    # Age factor (prime 28-32 = 1.0, young <24 = 0.8, old >35 = 0.7)
    age = 28
    if dob:
        try:
            age = 2026 - int(dob[:4])
        except (ValueError, TypeError):
            age = 28
    if age < 24:
        age_factor = 0.8
    elif age <= 32:
        age_factor = 1.0
    elif age <= 37:
        age_factor = 0.9
    else:
        age_factor = 0.7

    # Quality score (0-100)
    score = (
        potential * 0.40 +
        win_rate * 100 * 0.30 +
        min(title_reigns * 15, 30) * 0.20 +
        age_factor * 100 * 0.10
    )
    return score


def main():
    print("=" * 60)
    print("CAGE EMPIRE — Quality-Based Promotion Assignment")
    print("=" * 60)

    # Back up
    import shutil
    backup = DB_PATH.parent / "cage_empire.db.backup-quality-assign"
    shutil.copy2(DB_PATH, backup)
    print(f"Backed up to {backup}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Get sim date
    sim_date = conn.execute(
        "SELECT simulation_clock.current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]

    # Step 1: Get all champions and their title's promotion
    # Champions MUST stay on their title's promotion
    champions = conn.execute("""
        SELECT t.current_champion_fighter_id, t.promotion_id, t.weight_class_id
        FROM titles t
        WHERE t.is_vacant = 0 AND t.current_champion_fighter_id IS NOT NULL
    """).fetchall()
    champion_map = {}  # fighter_id → promotion_id
    for fighter_id, promo_id, wc_id in champions:
        champion_map[fighter_id] = promo_id
    print(f"\nFound {len(champions)} champions to preserve")

    # Step 2: Clear ALL promotion assignments (everyone becomes free agent)
    conn.execute("UPDATE fighters SET current_promotion_id=NULL WHERE is_active=1")
    # Terminate all contracts
    conn.execute("UPDATE contracts SET status='terminated' WHERE status='active'")
    conn.commit()
    print("Cleared all promotion assignments")

    # Step 3: Get all active fighters with their quality scores
    all_fighters = conn.execute("""
        SELECT f.fighter_id, f.gender, f.weight_class_id
        FROM fighters f
        WHERE f.is_active = 1
        ORDER BY f.fighter_id
    """).fetchall()

    print(f"\nComputing quality scores for {len(all_fighters)} fighters...")
    scored = []
    for fighter_id, gender, wc_id in all_fighters:
        score = compute_quality_score(conn, fighter_id)
        scored.append((fighter_id, gender, wc_id, score))

    # Sort by quality score DESC (best fighters first)
    scored.sort(key=lambda x: x[3], reverse=True)

    # Step 4: Get promotions by tier
    major_promos = conn.execute(
        "SELECT promotion_id FROM promotions WHERE size_tier='major' ORDER BY promotion_id"
    ).fetchall()
    mid_promos = conn.execute(
        "SELECT promotion_id FROM promotions WHERE size_tier='mid' ORDER BY promotion_id"
    ).fetchall()
    small_promos = conn.execute(
        "SELECT promotion_id FROM promotions WHERE size_tier='small' ORDER BY promotion_id"
    ).fetchall()

    # Step 5: Assign fighters to promotions
    # Targets: major=60, mid=40 each, small=15 each
    targets = {
        'major': 60,
        'mid': 40,
        'small': 15,
    }

    # Track which fighters have been assigned
    assigned = set()

    # First: assign champions to their title's promotion (must happen first)
    for fighter_id, promo_id in champion_map.items():
        conn.execute(
            "UPDATE fighters SET current_promotion_id=? WHERE fighter_id=?",
            (promo_id, fighter_id)
        )
        assigned.add(fighter_id)

    print(f"Assigned {len(assigned)} champions to their title promotions")

    # Create a new contract for each assigned champion
    for fighter_id, promo_id in champion_map.items():
        # Create contract
        end_date = datetime.strptime(sim_date[:10], "%Y-%m-%d") + timedelta(days=365)
        conn.execute(
            "INSERT INTO contracts (promotion_id, contract_target_type, start_date, end_date, "
            "salary, status) VALUES (?, 'fighter', ?, ?, 50000, 'active')",
            (promo_id, sim_date[:10], end_date.strftime("%Y-%m-%d"))
        )
        contract_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO fighter_contracts (contract_id, fighter_id, contract_type) "
            "VALUES (?, ?, 'standard')",
            (contract_id, fighter_id)
        )

    # Now assign remaining fighters by quality
    # Remove already-assigned (champions) from the scored list
    remaining = [(fid, gender, wc, score) for fid, gender, wc, score in scored
                 if fid not in assigned]

    # Major promotion: top 60 (minus champions already there)
    major_target = targets['major']
    major_already = len(champion_map)
    # Count how many champions are in each major promo
    major_champ_count = sum(1 for fid, pid in champion_map.items()
                           if any(p[0] == pid for p in major_promos))
    major_to_assign = max(0, major_target - major_champ_count)

    # Assign by quality, respecting gender/weight class diversity
    # For major: take the best fighters regardless of WC (but try to spread across WCs)
    major_fighters = remaining[:major_to_assign]
    for fighter_id, gender, wc, score in major_fighters:
        promo_id = major_promos[0][0]  # Alpha Combat
        conn.execute(
            "UPDATE fighters SET current_promotion_id=? WHERE fighter_id=?",
            (promo_id, fighter_id)
        )
        assigned.add(fighter_id)
        # Create contract
        end_date = datetime.strptime(sim_date[:10], "%Y-%m-%d") + timedelta(days=365)
        conn.execute(
            "INSERT INTO contracts (promotion_id, contract_target_type, start_date, end_date, "
            "salary, status) VALUES (?, 'fighter', ?, ?, 50000, 'active')",
            (promo_id, sim_date[:10], end_date.strftime("%Y-%m-%d"))
        )
        contract_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO fighter_contracts (contract_id, fighter_id, contract_type) "
            "VALUES (?, ?, 'standard')",
            (contract_id, fighter_id)
        )

    print(f"Assigned {major_to_assign} fighters to major (total: {major_champ_count + major_to_assign})")

    # Remove assigned from remaining
    remaining = [(fid, gender, wc, score) for fid, gender, wc, score in remaining
                 if fid not in assigned]

    # Mid promotions: next best 120 fighters (40 per promo)
    # Try to assign fighters to promos that match their region/nation for realism
    mid_per_promo = targets['mid']
    mid_assigned = 0
    for promo_idx, (promo_id,) in enumerate(mid_promos):
        # Take the next batch of best fighters
        batch = remaining[:mid_per_promo]
        remaining = remaining[mid_per_promo:]
        for fighter_id, gender, wc, score in batch:
            conn.execute(
                "UPDATE fighters SET current_promotion_id=? WHERE fighter_id=?",
                (promo_id, fighter_id)
            )
            assigned.add(fighter_id)
            # Create contract
            end_date = datetime.strptime(sim_date[:10], "%Y-%m-%d") + timedelta(days=365)
            conn.execute(
                "INSERT INTO contracts (promotion_id, contract_target_type, start_date, end_date, "
                "salary, status) VALUES (?, 'fighter', ?, ?, 30000, 'active')",
                (promo_id, sim_date[:10], end_date.strftime("%Y-%m-%d"))
            )
            contract_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO fighter_contracts (contract_id, fighter_id, contract_type) "
                "VALUES (?, ?, 'standard')",
                (contract_id, fighter_id)
            )
            mid_assigned += 1

    print(f"Assigned {mid_assigned} fighters to mid promotions")

    # Small promotions: next 90 fighters (15 per promo)
    # These should be the lower-quality fighters (rookies, prospects)
    small_per_promo = targets['small']
    small_assigned = 0
    for promo_idx, (promo_id,) in enumerate(small_promos):
        batch = remaining[:small_per_promo]
        remaining = remaining[small_per_promo:]
        for fighter_id, gender, wc, score in batch:
            conn.execute(
                "UPDATE fighters SET current_promotion_id=? WHERE fighter_id=?",
                (promo_id, fighter_id)
            )
            assigned.add(fighter_id)
            # Create contract
            end_date = datetime.strptime(sim_date[:10], "%Y-%m-%d") + timedelta(days=365)
            conn.execute(
                "INSERT INTO contracts (promotion_id, contract_target_type, start_date, end_date, "
                "salary, status) VALUES (?, 'fighter', ?, ?, 15000, 'active')",
                (promo_id, sim_date[:10], end_date.strftime("%Y-%m-%d"))
            )
            contract_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO fighter_contracts (contract_id, fighter_id, contract_type) "
                "VALUES (?, ?, 'standard')",
                (contract_id, fighter_id)
            )
            small_assigned += 1

    print(f"Assigned {small_assigned} fighters to small promotions")

    # Everyone else stays as free agent (no contract, no promotion)
    free_agent_count = len(remaining)
    print(f"Free agents: {free_agent_count}")
    print(f"Total assigned: {len(assigned)}")
    print(f"Total active: {len(all_fighters)}")

    conn.commit()

    # Step 6: Verify quality distribution
    print("\n" + "=" * 60)
    print("QUALITY VERIFICATION")
    print("=" * 60)

    for p_name, p_tier in conn.execute(
        "SELECT name, size_tier FROM promotions ORDER BY "
        "CASE size_tier WHEN 'major' THEN 1 WHEN 'mid' THEN 2 ELSE 3 END, promotion_id"
    ).fetchall():
        stats = conn.execute("""
            SELECT AVG(fc.potential), MIN(fc.potential), MAX(fc.potential),
                   AVG(fc.record_wins), COUNT(*)
            FROM fighters f
            JOIN fighter_career fc ON f.fighter_id = fc.fighter_id
            WHERE f.current_promotion_id = (SELECT promotion_id FROM promotions WHERE name = ?)
            AND f.is_active = 1
        """, (p_name,)).fetchone()
        print(f"  {p_name:40s} ({p_tier:6s}): "
              f"avg_pot={stats[0]:.1f} min={stats[1]} max={stats[2]} "
              f"avg_wins={stats[3]:.1f} count={stats[4]}")

    # Free agents
    fa_stats = conn.execute("""
        SELECT AVG(fc.potential), MIN(fc.potential), MAX(fc.potential), COUNT(*)
        FROM fighters f JOIN fighter_career fc ON f.fighter_id = fc.fighter_id
        WHERE f.current_promotion_id IS NULL AND f.is_active = 1
    """).fetchone()
    print(f"  {'Free Agents':40s} {'FA':6s}): "
          f"avg_pot={fa_stats[0]:.1f} min={fa_stats[1]} max={fa_stats[2]} "
          f"count={fa_stats[3]}")

    # Step 7: Rebuild interpretation layer
    print("\nRebuilding interpretation layer...")
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from interpretation.context_engine import compute_all_fighters
    from interpretation.career_phase_engine import compute_all_career_phases
    from interpretation.narrative_families import compute_all_families
    from interpretation.legacy_engine import compute_all_legacies

    compute_all_fighters(conn)
    compute_all_career_phases(conn)
    compute_all_families(conn)
    compute_all_legacies(conn)

    # Regenerate headlines
    from interpretation.headline_engine import generate_daily_headlines
    generate_daily_headlines(conn, sim_date)

    conn.commit()
    conn.close()

    print("\nDone! Fighters are now assigned by quality.")


if __name__ == "__main__":
    main()
