#!/usr/bin/env python3
"""CR-14: Verify regenerated fighter bios match actual DB records.

CAGE EMPIRE — Fix Plan for DB Audit Issue #5 (CR-14).
Reference: docs/CR10_14_FIX_PLAN.md §5 (CR-14 — Bio regeneration).

PURPOSE:
- After running scripts/regenerate_fighter_bios.py, run this script to
  verify the regenerated bios actually match the DB records.
- Samples 20 random fighters (mix of career phases + potential tiers),
  fetches their bio + their actual fighter_career record, and confirms
  the bio mentions the correct record.
- Also verifies the bio mentions the correct weight class, nationality,
  and gym (if the fighter has one).

WHAT IT CHECKS PER FIGHTER:
- Extract the "X-Y" or "X-Y-D" record pattern from the bio text (regex).
- Compare to fighter_career.record_wins-losses[-draws].
- Verify bio mentions the weight_class.name.
- Verify bio mentions the nations.name (nationality).
- Verify bio mentions the gyms.name (if fighter has a current_gym_id).
- Flag mismatches.

EXIT CODES:
- 0 if ≥18/20 bios match DB records (90% target).
- 1 if below 90%.

USAGE:
    python scripts/verify_bios.py
"""
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

# Sample size + pass threshold.
SAMPLE_SIZE = 20
PASS_THRESHOLD = 18  # 90% of 20


# ============================================================
# RECORD EXTRACTION + VERIFICATION
# ============================================================

# Match an "X-Y" or "X-Y-D" record pattern. We require a digit on
# both sides of the dash (and an optional third segment) so we don't
# accidentally match date fragments like "2026-08-02" — well, that
# would actually match. So we add a word-boundary + lookahead/lookbehind
# to avoid matching within larger numbers (4-digit years etc.).
#
# Concretely: we look for a pattern preceded by start-of-string or a
# space, followed by 1-2 digits, a dash, 1-2 digits, optionally a dash
# and 1-2 digits, followed by a non-digit. This matches "3-1-1" or
# "16-11" but skips "2026-08-02" (which has 4-digit segments).
RECORD_PATTERN = re.compile(
    r"(?:^|\s)(\d{1,3})-(\d{1,3})(?:-(\d{1,3}))?(?=\D|$)"
)


def _format_record(wins, losses, draws):
    """Format a fighter's record as 'W-L' or 'W-L-D' (D only if >0)."""
    record = f"{wins}-{losses}"
    if draws and draws > 0:
        record += f"-{draws}"
    return record


def extract_records_from_bio(bio_text):
    """Extract all X-Y[-D] record patterns from the bio text.

    Returns:
        List of (wins, losses, draws) tuples. draws may be None if
        the pattern only had two segments.
    """
    matches = []
    for m in RECORD_PATTERN.finditer(bio_text):
        w = int(m.group(1))
        l = int(m.group(2))
        d = int(m.group(3)) if m.group(3) is not None else None
        matches.append((w, l, d))
    return matches


def record_matches(bio_records, db_wins, db_losses, db_draws):
    """Return True if any extracted bio record matches the DB record.

    A match is: bio_wins == db_wins AND bio_losses == db_losses AND
    (bio_draws == db_draws OR (db_draws == 0 AND bio_draws is None)).

    The db_draws==0 + bio_draws is None case is OK because the bio
    format omits draws when draws == 0 ("3-1" rather than "3-1-0").
    """
    db_draws = db_draws or 0
    for (bw, bl, bd) in bio_records:
        if bw != db_wins or bl != db_losses:
            continue
        if bd is None:
            # Bio omitted draws — accept only if DB has 0 draws.
            if db_draws == 0:
                return True
        else:
            if bd == db_draws:
                return True
    return False


def bio_mentions(bio_text, needle):
    """Case-insensitive substring check.

    Returns True if needle (case-insensitive) appears in bio_text.
    None/empty needles return True (vacuous mention check — e.g., a
    fighter with no gym should not fail the gym check).
    """
    if not needle:
        return True
    return needle.lower() in bio_text.lower()


# ============================================================
# SAMPLE SELECTION (DETERMINISTIC — career_phase + potential mix)
# ============================================================

def _select_sample(conn, n=SAMPLE_SIZE):
    """Select a deterministic mix of fighters for verification.

    Selection strategy (deterministic, no RNG — same sample every run):
      - ~5 from each career_phase bucket (champion, prospect, veteran,
        gatekeeper, declining, rising_contender) — take 3-4 each.
      - Top up with rising_contender if some buckets are empty.

    The mix ensures we test bios across career phases (which drive
    bio_tone) and potential tiers (which we don't use directly but
    correlate with career_phase).

    Returns:
        List of fighter_ids (length ~= n).
    """
    cur = conn.cursor()
    # Get current champion fighter_ids.
    champion_ids = {r[0] for r in cur.execute(
        "SELECT DISTINCT current_champion_fighter_id FROM titles "
        "WHERE is_vacant = 0 AND current_champion_fighter_id IS NOT NULL"
    )}

    # Sample per career_phase bucket. Use ROW_NUMBER() to get a
    # deterministic sample (lowest fighter_ids per bucket).
    sample_ids = []
    seen = set()

    # 1. Champions first (the rare bucket — get up to 5).
    for fid in list(champion_ids)[:5]:
        if fid not in seen:
            sample_ids.append(fid)
            seen.add(fid)

    # 2. Per-bucket samples for the other 5 phases.
    BUCKETS = ["prospect", "rising_contender", "veteran",
               "gatekeeper", "declining"]
    PER_BUCKET = 3  # 5 buckets × 3 = 15, plus up to 5 champions = 20.

    for label in BUCKETS:
        # career_phase is stored as "label||phrase" — match the prefix.
        rows = cur.execute(
            "SELECT fighter_id FROM fighter_descriptors "
            "WHERE career_phase LIKE ? || '||%' "
            "ORDER BY fighter_id LIMIT ?",
            (label, PER_BUCKET),
        ).fetchall()
        for r in rows:
            fid = r[0]
            if fid not in seen:
                sample_ids.append(fid)
                seen.add(fid)

    # 3. Top up to SAMPLE_SIZE with rising_contender if short.
    if len(sample_ids) < n:
        rows = cur.execute(
            "SELECT fighter_id FROM fighter_descriptors "
            "WHERE career_phase LIKE 'rising_contender||%' "
            "  AND fighter_id NOT IN (%s) "
            "ORDER BY fighter_id LIMIT ?" % ",".join("?" * len(sample_ids)),
            (*sample_ids, n - len(sample_ids)),
        ).fetchall()
        for r in rows:
            sample_ids.append(r[0])

    return sample_ids[:n]


# ============================================================
# VERIFICATION MAIN
# ============================================================

def verify_fighter(conn, fighter_id):
    """Verify a single fighter's bio against their DB record.

    Returns:
        dict with keys:
            fighter_id, name, db_record (str), bio_record_strs (list),
            record_match (bool), wc_match (bool), nat_match (bool),
            gym_match (bool), all_match (bool), bio_text (str),
            wc_name, nat_name, gym_name
    """
    cur = conn.cursor()
    # Fetch bio + fighter + career + wc + nation + gym.
    row = cur.execute(
        """
        SELECT
            f.fighter_id, f.first_name, f.last_name, f.nickname,
            f.gender,
            b.bio_text,
            c.record_wins, c.record_losses, c.record_draws,
            wc.name AS wc_name,
            n.name  AS nat_name,
            g.name  AS gym_name
        FROM fighters f
        LEFT JOIN fighter_bios    b  ON f.fighter_id = b.fighter_id
        LEFT JOIN fighter_career  c  ON f.fighter_id = c.fighter_id
        LEFT JOIN weight_classes  wc ON f.weight_class_id = wc.weight_class_id
        LEFT JOIN nations         n  ON f.birth_nation_id = n.nation_id
        LEFT JOIN gyms            g  ON f.current_gym_id  = g.gym_id
        WHERE f.fighter_id = ?
        """,
        (fighter_id,),
    ).fetchone()

    if row is None:
        return None

    bio_text = row[5] or ""
    db_w = row[6] or 0
    db_l = row[7] or 0
    db_d = row[8] or 0
    db_record_str = _format_record(db_w, db_l, db_d)
    wc_name = row[9]
    nat_name = row[10]
    gym_name = row[11]

    name = f"{row[1]} {row[2]}"
    if row[3]:
        name += f" '{row[3]}'"

    # Extract record patterns from bio.
    bio_records = extract_records_from_bio(bio_text)
    bio_record_strs = []
    for (bw, bl, bd) in bio_records:
        if bd is None:
            bio_record_strs.append(f"{bw}-{bl}")
        else:
            bio_record_strs.append(f"{bw}-{bl}-{bd}")

    rec_match = record_matches(bio_records, db_w, db_l, db_d)
    wc_match = bio_mentions(bio_text, wc_name)
    nat_match = bio_mentions(bio_text, nat_name)
    gym_match = bio_mentions(bio_text, gym_name)  # True if no gym

    return {
        "fighter_id":        fighter_id,
        "name":              name,
        "db_record":         db_record_str,
        "bio_records":       bio_record_strs,
        "record_match":      rec_match,
        "wc_match":          wc_match,
        "nat_match":         nat_match,
        "gym_match":         gym_match,
        "all_match":         rec_match and wc_match and nat_match and gym_match,
        "bio_text":          bio_text,
        "wc_name":           wc_name,
        "nat_name":          nat_name,
        "gym_name":          gym_name,
    }


def main():
    """Entry point — sample 20 fighters, verify, print report."""
    print("=" * 70)
    print("CR-14: Verify regenerated bios match DB records")
    print("Reference: docs/CR10_14_FIX_PLAN.md §5")
    print("=" * 70)

    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(2)

    conn = sqlite3.connect(str(DB_PATH))
    sample_ids = _select_sample(conn, SAMPLE_SIZE)
    print(f"\nSample {len(sample_ids)} fighters (deterministic mix of career phases):")
    print()

    results = []
    for fid in sample_ids:
        r = verify_fighter(conn, fid)
        if r is None:
            continue
        results.append(r)
        mark = "MATCH ✓" if r["all_match"] else "MISMATCH ✗"
        bio_recs = ", ".join(r["bio_records"]) if r["bio_records"] else "(none)"
        print(f"  [{r['fighter_id']:>4}] {r['name']:<35} "
              f"bio: {bio_recs:<15} | db: {r['db_record']:<8} | {mark}")
        if not r["all_match"]:
            details = []
            if not r["record_match"]:
                details.append(f"record")
            if not r["wc_match"]:
                details.append(f"wc='{r['wc_name']}'")
            if not r["nat_match"]:
                details.append(f"nat='{r['nat_name']}'")
            if not r["gym_match"]:
                details.append(f"gym='{r['gym_name']}'")
            print(f"        flags: {', '.join(details)}")

    conn.close()

    # ----- Summary -----
    n = len(results)
    matches = sum(1 for r in results if r["all_match"])
    record_only_matches = sum(1 for r in results if r["record_match"])

    print()
    print("=" * 70)
    print(f"SUMMARY")
    print("=" * 70)
    print(f"  All-fields match (record + wc + nat + gym): "
          f"{matches}/{n}")
    print(f"  Record-only match:                          "
          f"{record_only_matches}/{n}")
    print(f"  (Was 3/14 before CR-14 — DB_REVIEW_AUDIT.md §3)")
    print(f"  Target: ≥{PASS_THRESHOLD}/{SAMPLE_SIZE} (90%)")
    print()

    if matches >= PASS_THRESHOLD:
        print(f"  PASS — {matches}/{n} bios match DB records "
              f"(≥{PASS_THRESHOLD} threshold met).")
        sys.exit(0)
    else:
        print(f"  FAIL — only {matches}/{n} bios match DB records "
              f"(below {PASS_THRESHOLD} threshold).")
        sys.exit(1)


if __name__ == "__main__":
    main()
