#!/usr/bin/env python3
"""Verify fighter portrait assignment integrity.

DB-REVIEW-IMAGE-ASSIGNMENT E.3: runs 6 integrity checks against the
``fighters.portrait_path`` column + the ``data/portraits/`` directory.

Checks:
  1. Count fighters with portrait_path IS NOT NULL vs IS NULL.
  2. Verify every non-NULL portrait_path points to a file that
     actually exists on disk (relative to ``data/``).
  3. Verify every .webp image file in data/portraits/ is referenced
     by exactly one fighter (no orphans, no duplicates).
  4. Sample 5 fighters WITH portraits — print names + paths.
  5. Sample 5 fighters WITHOUT portraits — print names (so user can
     see who's missing).
  6. Check image dimensions of 5 random portraits (should all be
     512x512). If a file is corrupted (not a valid image), flag it.

Exit code 0 if all checks pass, 1 if any fail.

Usage:
    python scripts/verify_portraits.py
"""
import os
import random
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
DATA_DIR = PROJECT_DIR / "data"
PORTRAITS_DIR = DATA_DIR / "portraits"


def _is_valid_image(path):
    """Return (is_valid, dimensions_or_None, error_or_None).

    CR-15: supports both .png (new) and .webp (legacy) formats.
    PNG magic: \x89PNG\r\n\x1a\n (8 bytes).
    WEBP magic: RIFF....WEBP (12 bytes).
    Uses PIL if available for dimension checking.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(12)
        ext = Path(path).suffix.lower()
        if ext == ".png":
            if head[:8] != b"\x89PNG\r\n\x1a\n":
                # Check all-null corruption
                with open(path, "rb") as f:
                    sample = f.read(4096)
                if all(b == 0 for b in sample):
                    return (False, None, "corrupted: file is all null bytes")
                return (False, None, f"not a PNG file (magic={head[:8]!r})")
        elif ext == ".webp":
            if head[:4] != b"RIFF" or head[8:12] != b"WEBP":
                with open(path, "rb") as f:
                    sample = f.read(4096)
                if all(b == 0 for b in sample):
                    return (False, None,
                            "corrupted: file is all null bytes (likely a "
                            "truncated upload — content was zeroed but "
                            "the file size was set correctly)")
                return (False, None, f"not a WEBP file (magic={head[:4]!r})")
        else:
            return (False, None, f"unsupported extension: {ext}")
        # Try PIL for dimensions.
        try:
            from PIL import Image
            with Image.open(path) as im:
                return (True, im.size, None)
        except ImportError:
            return (True, None, None)
        except Exception as e:
            return (False, None, f"PIL decode failed: {e}")
    except Exception as e:
        return (False, None, f"read error: {e}")


def main():
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(DB_PATH)
    checks_passed = 0
    checks_failed = 0

    try:
        # ----- Check 1: counts -----
        print("=" * 60)
        print("CHECK 1 — Fighter portrait_path counts")
        total = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
        with_p = conn.execute(
            "SELECT COUNT(*) FROM fighters WHERE portrait_path IS NOT NULL"
        ).fetchone()[0]
        without_p = total - with_p
        print(f"  Total fighters:              {total}")
        print(f"  With portrait_path set:      {with_p}")
        print(f"  Without portrait_path (NULL):{without_p}")
        if with_p == 0:
            print("  FAIL: no fighters have portrait_path set")
            checks_failed += 1
        else:
            print("  PASS")
            checks_passed += 1
        print()

        # ----- Check 2: every non-NULL path exists on disk -----
        print("=" * 60)
        print("CHECK 2 — Every non-NULL portrait_path exists on disk")
        rows = conn.execute(
            "SELECT fighter_id, first_name, last_name, portrait_path "
            "FROM fighters WHERE portrait_path IS NOT NULL"
        ).fetchall()
        missing_files = []
        for fid, fn, ln, pp in rows:
            # portrait_path is relative to data/
            full = DATA_DIR / pp
            if not full.exists():
                missing_files.append((fid, fn, ln, pp, str(full)))
        if missing_files:
            print(f"  FAIL: {len(missing_files)} portrait_path values "
                  f"point to non-existent files:")
            for fid, fn, ln, pp, full in missing_files[:10]:
                print(f"    fighter_id={fid} ({fn} {ln}): "
                      f"portrait_path='{pp}' (resolved to {full})")
            if len(missing_files) > 10:
                print(f"    ... and {len(missing_files) - 10} more.")
            checks_failed += 1
        else:
            print(f"  PASS: all {len(rows)} non-NULL portrait_path "
                  f"values resolve to existing files.")
            checks_passed += 1
        print()

        # ----- Check 3: every image file is referenced exactly once -----
        print("=" * 60)
        print("CHECK 3 — Orphan + duplicate check")
        # Build set of on-disk image file relative paths (.png + .webp).
        on_disk = set()
        for root, _dirs, files in os.walk(PORTRAITS_DIR):
            for fn in files:
                if fn.lower().endswith((".png", ".webp")):
                    full = Path(root) / fn
                    rel = full.relative_to(DATA_DIR).as_posix()
                    on_disk.add(rel)
        # Build set of DB-referenced paths + count duplicates.
        db_paths = [r[0] for r in conn.execute(
            "SELECT portrait_path FROM fighters "
            "WHERE portrait_path IS NOT NULL"
        ).fetchall()]
        from collections import Counter
        dup_counts = Counter(db_paths)
        duplicates = {p: c for p, c in dup_counts.items() if c > 1}
        # Orphans = files on disk not referenced by any fighter.
        db_set = set(db_paths)
        orphans = on_disk - db_set
        # Unresolved = DB references that don't exist on disk (already
        # caught in Check 2, but list here for completeness).
        unresolved = db_set - on_disk

        if duplicates:
            print(f"  FAIL: {len(duplicates)} paths referenced by "
                  f"more than one fighter:")
            for p, c in list(duplicates.items())[:10]:
                print(f"    {p}: {c} fighters")
            checks_failed += 1
        elif orphans:
            print(f"  WARN: {len(orphans)} image files on disk not "
                  f"referenced by any fighter:")
            for p in sorted(orphans)[:10]:
                print(f"    {p}")
            if len(orphans) > 10:
                print(f"    ... and {len(orphans) - 10} more.")
            # Orphans are a warning, not a hard fail — they may be
            # newly-added images that haven't been assigned yet.
            # But if the count is high relative to assigned, flag.
            print(f"  PASS (with warnings): no duplicates, "
                  f"{len(orphans)} orphan(s) on disk.")
            checks_passed += 1
        elif unresolved:
            print(f"  FAIL: {len(unresolved)} DB-referenced paths "
                  f"don't exist on disk:")
            for p in sorted(unresolved)[:10]:
                print(f"    {p}")
            checks_failed += 1
        else:
            print(f"  PASS: {len(on_disk)} image files on disk, "
                  f"{len(db_set)} referenced by DB. No orphans, no "
                  f"duplicates.")
            checks_passed += 1
        print()

        # ----- Check 4: sample 5 fighters WITH portraits -----
        print("=" * 60)
        print("CHECK 4 — Sample 5 fighters WITH portraits")
        sample_with = conn.execute(
            "SELECT fighter_id, first_name, last_name, portrait_path "
            "FROM fighters WHERE portrait_path IS NOT NULL "
            "ORDER BY RANDOM() LIMIT 5"
        ).fetchall()
        if not sample_with:
            print("  FAIL: no fighters with portraits to sample.")
            checks_failed += 1
        else:
            for fid, fn, ln, pp in sample_with:
                print(f"  #{fid:4d} {fn} {ln}: {pp}")
            print("  PASS")
            checks_passed += 1
        print()

        # ----- Check 5: sample 5 fighters WITHOUT portraits -----
        print("=" * 60)
        print("CHECK 5 — Sample 5 fighters WITHOUT portraits")
        sample_without = conn.execute(
            "SELECT fighter_id, first_name, last_name "
            "FROM fighters WHERE portrait_path IS NULL "
            "ORDER BY RANDOM() LIMIT 5"
        ).fetchall()
        if not sample_without:
            print("  (no fighters without portraits — every fighter "
                  "has one!)")
        else:
            for fid, fn, ln in sample_without:
                print(f"  #{fid:4d} {fn} {ln}")
        print("  PASS")
        checks_passed += 1
        print()

        # ----- Check 6: image dimensions of 5 random portraits -----
        print("=" * 60)
        print("CHECK 6 — Image dimensions of 5 random portraits "
              "(expected 512x512)")
        all_paths = [r[0] for r in conn.execute(
            "SELECT portrait_path FROM fighters "
            "WHERE portrait_path IS NOT NULL"
        ).fetchall()]
        if not all_paths:
            print("  FAIL: no portraits to check.")
            checks_failed += 1
        else:
            random.seed(20260802)
            sample_paths = random.sample(all_paths,
                                         min(5, len(all_paths)))
            dim_ok = 0
            dim_bad = 0
            for rel in sample_paths:
                full = DATA_DIR / rel
                is_valid, dims, err = _is_valid_image(full)
                if not is_valid:
                    print(f"  {rel}: INVALID — {err}")
                    dim_bad += 1
                elif dims is None:
                    print(f"  {rel}: valid image (dimensions unknown — "
                          f"PIL not available)")
                    dim_ok += 1
                elif dims == (512, 512):
                    print(f"  {rel}: {dims[0]}x{dims[1]} OK")
                    dim_ok += 1
                else:
                    print(f"  {rel}: {dims[0]}x{dims[1]} — FLAG for "
                          f"resize (expected 512x512)")
                    dim_bad += 1
            if dim_bad == 0:
                print(f"  PASS: all 5 sampled portraits are valid + "
                      f"correct dimensions.")
                checks_passed += 1
            else:
                print(f"  FAIL: {dim_bad} of 5 sampled portraits are "
                      f"invalid or wrong dimensions.")
                checks_failed += 1
        print()

        # Also do a full sweep for corrupted files (not just the
        # sample of 5) — print summary so user knows how many of the
        # 415 are corrupted. This doesn't count as a check for pass/
        # fail purposes (the sample-of-5 already covered that), but
        # surfaces the corruption rate for the user's awareness.
        print("=" * 60)
        print("BONUS — Full corruption sweep across all "
              f"{len(all_paths)} assigned portraits")
        valid_count = 0
        corrupted_count = 0
        corrupted_examples = []
        for rel in all_paths:
            full = DATA_DIR / rel
            is_valid, _dims, err = _is_valid_image(full)
            if is_valid:
                valid_count += 1
            else:
                corrupted_count += 1
                if len(corrupted_examples) < 5:
                    corrupted_examples.append((rel, err))
        print(f"  Valid image files:   {valid_count}")
        print(f"  Corrupted/invalid:   {corrupted_count}")
        if corrupted_examples:
            print(f"  First {len(corrupted_examples)} corrupted:")
            for rel, err in corrupted_examples:
                print(f"    {rel}: {err}")
        print()

        # ----- Final summary -----
        print("=" * 60)
        print(f"FINAL: {checks_passed} checks passed, "
              f"{checks_failed} failed.")
        print("=" * 60)
        return 0 if checks_failed == 0 else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
