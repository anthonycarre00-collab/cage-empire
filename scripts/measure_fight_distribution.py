#!/usr/bin/env python3
"""TIER3-MISSING §T3.1 (W12) — Fight engine distribution MEASUREMENT.

This script MEASURES the result_type distribution of resolved fights
in the world DB and compares it to real-world UFC distributions. It
is MEASUREMENT ONLY — it does NOT tune any fight engine constants
(per the brief: "The user will rebalance fighter attribute
allocations separately later").

Real-world UFC distributions (approximate, per the brief):
  - KO/TKO              ~35%  (knockouts + technical knockouts)
  - Submission          ~20%  (tap-outs)
  - Decision           ~45%  (unanimous + split decisions)
  - Draw               ~1%   (rare)
  - DQ                 ~0.5% (rare)
  - Doctor Stoppage    ~1%   (rare)
  - No Contest         ~0.5% (rare)

The script:
  1. Queries the fights table for the result_type distribution
     (WHERE result_type IS NOT NULL — only resolved fights).
  2. Computes percentages for each category.
  3. Compares to the real-world UFC distributions above.
  4. Reports the gap (absolute + percentage-point difference).
  5. Saves the report to docs/fight_distribution_report.md.

Run from the project root:
    python3 scripts/measure_fight_distribution.py
    python3 scripts/measure_fight_distribution.py --db-path PATH

Exit codes:
    0 = report generated successfully
    2 = script error (couldn't run)

CONVENTIONS compliance:
  §6  — Smoke test protocol. This is a diagnostic, not a test.
        Does NOT modify the DB. Does NOT tune any constants.
  §13 — Design Law: Sport realism pillar — fight outcomes should
        mirror real-world MMA distributions for the simulation to
        feel authentic.
  §14 — Voice Layer: N/A — raw numbers ARE allowed in this report
        (it's a measurement / diagnostic, not player-facing text).
"""
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db"),
))
REPORT_PATH = PROJECT_DIR / "docs" / "fight_distribution_report.md"

# Real-world UFC distributions (approximate, per the brief).
# These are the TARGET distributions the fight engine should
# approximate after the user rebalances fighter attributes.
UFC_TARGET_DISTRIBUTION = {
    "ko_tko":             0.35,   # ~35% (knockouts + technical KOs)
    "submission":         0.20,   # ~20% (tap-outs)
    "unanimous_decision": 0.40,   # ~40% (the bulk of decisions)
    "split_decision":     0.05,   # ~5%  (close decisions)
    "draw":               0.01,   # ~1%
    "dq":                 0.005,  # ~0.5%
    "doctor_stoppage":    0.01,   # ~1%
    "no_contest":         0.005,  # ~0.5%
}

# Composite categories (per the brief):
#   KO%   = ko_tko
#   Sub%  = submission
#   Dec%  = unanimous_decision + split_decision
#   Draw% = draw
#   DQ%   = dq
#   Doctor% = doctor_stoppage
#   NC%   = no_contest
COMPOSITE_CATEGORIES = [
    ("KO/TKO",       ["ko_tko"]),
    ("Submission",   ["submission"]),
    ("Decision",     ["unanimous_decision", "split_decision"]),
    ("Draw",         ["draw"]),
    ("DQ",           ["dq"]),
    ("Doctor Stoppage", ["doctor_stoppage"]),
    ("No Contest",   ["no_contest"]),
]

# Target composite percentages (per the brief):
#   KO ~35%, Sub ~20%, Decision ~45%, Draw/DQ/Doctor/NC ~1%.
UFC_TARGET_COMPOSITE = {
    "KO/TKO":            0.35,
    "Submission":        0.20,
    "Decision":          0.45,   # UD + split
    "Draw":              0.01,
    "DQ":                0.005,
    "Doctor Stoppage":   0.01,
    "No Contest":        0.005,
}


def measure_distribution(conn):
    """Query fights table for the result_type distribution.

    Returns: dict mapping result_type → (count, percentage).
    """
    rows = conn.execute(
        """
        SELECT result_type, COUNT(*)
        FROM fights
        WHERE result_type IS NOT NULL
        GROUP BY result_type
        ORDER BY COUNT(*) DESC
        """
    ).fetchall()
    total = sum(count for _rt, count in rows)
    distribution = {}
    for result_type, count in rows:
        pct = (count / total) if total > 0 else 0.0
        distribution[result_type] = (count, pct)
    return distribution, total


def build_report(distribution, total, db_path):
    """Build the markdown report.

    Args:
        distribution: dict result_type → (count, pct).
        total: total resolved fights.
        db_path: path to the DB (for the report header).

    Returns: markdown string.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    lines.append("# Fight Engine Distribution Report (T3.1 / W12)")
    lines.append("")
    lines.append(f"**Generated:** {now}")
    lines.append(f"**DB:** `{db_path}`")
    lines.append(f"**Total resolved fights:** {total}")
    lines.append("")
    lines.append("## Purpose")
    lines.append("")
    lines.append("This report MEASURES the result_type distribution of resolved")
    lines.append("fights in the world DB and compares it to real-world UFC")
    lines.append("distributions. It is **MEASUREMENT ONLY** — it does NOT tune")
    lines.append("any fight engine constants. Per the T3.1 brief, the user will")
    lines.append("rebalance fighter attribute allocations separately later.")
    lines.append("")
    lines.append("## Raw result_type distribution")
    lines.append("")
    lines.append("| result_type           | count | percentage |")
    lines.append("|-----------------------|-------|------------|")
    for result_type in sorted(distribution.keys()):
        count, pct = distribution[result_type]
        lines.append(
            f"| {result_type:<21s} | {count:5d} | {pct*100:8.2f}% |"
        )
    lines.append(f"| {'TOTAL':<21s} | {total:5d} | {100.0:8.2f}% |")
    lines.append("")
    lines.append("## Composite categories (per the brief)")
    lines.append("")
    lines.append("The brief specifies the comparison in composite categories:")
    lines.append("KO%, sub%, decision% (UD+split), draw%, DQ%, doctor_stoppage%,")
    lines.append("no_contest%.")
    lines.append("")
    lines.append("| Category          | result_types                          | count | actual % | target % | gap (pp) |")
    lines.append("|-------------------|---------------------------------------|-------|----------|----------|----------|")
    for cat_name, cat_types in COMPOSITE_CATEGORIES:
        cat_count = sum(distribution.get(rt, (0, 0.0))[0] for rt in cat_types)
        cat_pct = (cat_count / total) if total > 0 else 0.0
        target_pct = UFC_TARGET_COMPOSITE.get(cat_name, 0.0)
        gap_pp = (cat_pct - target_pct) * 100  # percentage points
        types_str = "+".join(cat_types)
        lines.append(
            f"| {cat_name:<17s} | {types_str:<37s} | {cat_count:5d} | "
            f"{cat_pct*100:7.2f}% | {target_pct*100:7.2f}% | "
            f"{gap_pp:+7.2f} |"
        )
    lines.append("")
    lines.append("## Comparison to real-world UFC distributions")
    lines.append("")
    lines.append("Real-world UFC distributions (approximate, per the brief):")
    lines.append("")
    lines.append("- KO ~35% (knockouts + technical knockouts)")
    lines.append("- Submission ~20% (tap-outs)")
    lines.append("- Decision ~45% (unanimous + split decisions combined)")
    lines.append("- Draw ~1%")
    lines.append("- DQ ~0.5%")
    lines.append("- Doctor Stoppage ~1%")
    lines.append("- No Contest ~0.5%")
    lines.append("")
    lines.append("## Gap analysis")
    lines.append("")
    lines.append("The gap column (above) shows the difference between the actual")
    lines.append("distribution and the target UFC distribution, in percentage")
    lines.append("points (pp). A positive gap means the actual is HIGHER than")
    lines.append("the target; a negative gap means the actual is LOWER.")
    lines.append("")
    # Compute the largest gaps for a summary.
    gaps = []
    for cat_name, cat_types in COMPOSITE_CATEGORIES:
        cat_count = sum(distribution.get(rt, (0, 0.0))[0] for rt in cat_types)
        cat_pct = (cat_count / total) if total > 0 else 0.0
        target_pct = UFC_TARGET_COMPOSITE.get(cat_name, 0.0)
        gap_pp = (cat_pct - target_pct) * 100
        gaps.append((cat_name, cat_pct, target_pct, gap_pp))
    # Sort by absolute gap (largest first).
    gaps_sorted = sorted(gaps, key=lambda x: abs(x[3]), reverse=True)
    lines.append("Largest gaps (sorted by absolute gap):")
    lines.append("")
    for cat_name, cat_pct, target_pct, gap_pp in gaps_sorted:
        direction = "HIGHER" if gap_pp > 0 else "LOWER"
        if abs(gap_pp) < 0.5:
            direction = "ON TARGET"
        lines.append(
            f"- **{cat_name}**: actual {cat_pct*100:.2f}% vs target "
            f"{target_pct*100:.2f}% → gap {gap_pp:+.2f}pp ({direction})"
        )
    lines.append("")
    lines.append("## Tuning guidance (for the user's separate fighter-attribute rebalance)")
    lines.append("")
    lines.append("This script does NOT tune any fight engine constants. The gaps")
    lines.append("above identify where the actual distribution diverges from the")
    lines.append("target. Common fighter-attribute adjustments that affect each")
    lines.append("category:")
    lines.append("")
    lines.append("- **KO/TKO too high** → reduce average striking_power /")
    lines.append("  increase average durability / reduce aggression (fewer")
    lines.append("  wild exchanges).")
    lines.append("- **KO/TKO too low** → increase average striking_power /")
    lines.append("  decrease average durability / increase aggression.")
    lines.append("- **Submission too high** → reduce average submission_skill /")
    lines.append("  increase average submission_defense.")
    lines.append("- **Submission too low** → increase average submission_skill /")
    lines.append("  decrease average submission_defense.")
    lines.append("- **Decision too high** → increase average striking_power /")
    lines.append("  aggression (more finishes, fewer decisions).")
    lines.append("- **Decision too low** → decrease average striking_power /")
    lines.append("  increase average durability / cardio (fights go longer).")
    lines.append("")
    lines.append("## Conclusion")
    lines.append("")
    lines.append("This report is a SNAPSHOT of the current distribution. After")
    lines.append("the user rebalances fighter attributes, re-run this script to")
    lines.append("verify the distribution has shifted toward the target.")
    lines.append("")
    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db-path", default=str(DB_PATH),
                    help="Path to the cage_empire DB.")
    ap.add_argument("--report-path", default=str(REPORT_PATH),
                    help="Path to write the markdown report.")
    args = ap.parse_args()

    db = Path(args.db_path)
    if not db.exists():
        print(f"ERROR: DB not found at {db}", file=sys.stderr)
        return 2

    print(f"  TIER3-MISSING measure_fight_distribution")
    print(f"  DB: {db}")

    conn = sqlite3.connect(str(db))
    distribution, total = measure_distribution(conn)
    conn.close()

    print(f"\n  Total resolved fights: {total}")
    print(f"\n  Raw result_type distribution:")
    for result_type in sorted(distribution.keys()):
        count, pct = distribution[result_type]
        print(f"    {result_type:<22s} {count:5d}  {pct*100:6.2f}%")
    print(f"\n  Composite categories (actual vs target):")
    for cat_name, cat_types in COMPOSITE_CATEGORIES:
        cat_count = sum(distribution.get(rt, (0, 0.0))[0] for rt in cat_types)
        cat_pct = (cat_count / total) if total > 0 else 0.0
        target_pct = UFC_TARGET_COMPOSITE.get(cat_name, 0.0)
        gap_pp = (cat_pct - target_pct) * 100
        print(f"    {cat_name:<17s} actual {cat_pct*100:6.2f}%  "
              f"target {target_pct*100:6.2f}%  gap {gap_pp:+6.2f}pp")

    # Write the markdown report.
    report = build_report(distribution, total, db)
    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n  Report written to: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
