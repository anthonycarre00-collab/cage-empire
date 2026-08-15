#!/usr/bin/env python3
"""Assign fighter portrait images to fighters in the DB.

DB-REVIEW-IMAGE-ASSIGNMENT E.2: walks ``data/portraits/`` recursively,
finds all ``.webp`` files, parses each filename with the regex
``^(\\d+)_(.+?)(?:_(.+))?\\.webp$`` to extract the fighter_id (group 1,
zero-padded 4-digit prefix), the camelCase name string (group 2), and
the optional nickname (group 3).

For each image:
  1. Look up fighter_id in the ``fighters`` table. Skip if missing
     (the supervisor already verified all 415 IDs exist; this is a
     belt-and-braces guard).
  2. Verify the camelCase name aligns with the DB's
     ``first_name + last_name``. The split is performed by scanning
     for Word boundaries in the camelCase name (regex
     ``[A-Z][a-z\\-]+``). First word = first_name, rest joined = last_name.
     On mismatch (case-insensitive), print a WARNING but still assign
     (fighter_id is the primary key — the filename is the source of
     truth, not the name string).
  3. UPDATE ``fighters.portrait_path`` with the relative path (relative
     to ``data/``). E.g. ``portraits/batch_001-020/batch_001-020/
     0001_HirokiNakamura_Mist.webp``.

Per user directive: the image never changes once assigned — regens get
a fresh fighter_id (see regen_lineage), so the cached base64 stays
valid for the lifetime of the fighter_id.

Idempotent: re-running updates existing paths + assigns any new images.
The 1 stray ``4.png`` legacy file is skipped (not a .webp).

Usage:
    python scripts/assign_fighter_portraits.py
"""
import os
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
PORTRAITS_DIR = PROJECT_DIR / "data" / "portraits"

# Filename pattern: NNNN_FirstNameLastName[_Nickname].(png|webp)
#   group 1 = fighter_id (zero-padded 4 digits)
#   group 2 = camelCase name string
#   group 3 = optional nickname (everything after the 2nd underscore)
#   group 4 = file extension (png or webp) — .png preferred over .webp
FILENAME_RE = re.compile(r"^(\d+)_(.+?)(?:_(.+))?\.(png|webp)$", re.IGNORECASE)

# CamelCase word splitter. Captures each Word starting with an
# uppercase letter, allowing lowercase letters + hyphens within
# (handles "Beom-seok", "Seo-joon"). The first word is the first
# name; the remaining words concatenated are the last name.
CAMEL_WORD_RE = re.compile(r"[A-Z][a-z\-]+")


def split_camel_name(name_str):
    """Split a camelCase name string into (first_name, last_name).

    Examples:
        "HirokiNakamura"      → ("Hiroki", "Nakamura")
        "PauloMoraes"         → ("Paulo", "Moraes")
        "Beom-seokHwang"      → ("Beom-seok", "Hwang")
        "TulioGonalves"       → ("Tulio", "Gonalves")
        "PatrciaRezende"      → ("Patrcia", "Rezende")

    Falls back to (name_str, "") if no camelCase boundary is found
    (defensive — should never happen for our 415 files).
    """
    words = CAMEL_WORD_RE.findall(name_str)
    if not words:
        return (name_str, "")
    if len(words) == 1:
        return (words[0], "")
    return (words[0], "".join(words[1:]))


def names_match(file_first, file_last, db_first, db_last):
    """Return True if the file-derived names match the DB names
    (case-insensitive, whitespace-trimmed).

    The DB stores ASCII-transliterated names (e.g. "Gonalves" for
    "Gonçalves", "Patrcia" for "Patrícia") so we do an exact
    case-insensitive match — no Unicode normalization. The fighter_id
    is the source of truth; a name mismatch just prints a warning.
    """
    return (file_first.strip().lower() == (db_first or "").strip().lower()
            and file_last.strip().lower() == (db_last or "").strip().lower())


def main():
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        return 2
    if not PORTRAITS_DIR.exists():
        print(f"ERROR: portraits dir not found at {PORTRAITS_DIR}",
              file=sys.stderr)
        return 2

    # Walk portraits dir recursively, find portrait image files.
    # CR-15: support both .png (new) and .webp (legacy). Prefer .png
    # when both exist for the same fighter_id.
    image_files = []
    for root, _dirs, files in os.walk(PORTRAITS_DIR):
        for fn in files:
            if fn.lower().endswith((".png", ".webp")):
                image_files.append(Path(root) / fn)
    image_files.sort()

    # Deduplicate by fighter_id: if both .png and .webp exist, keep .png
    by_id = {}
    for p in image_files:
        m = FILENAME_RE.match(p.name)
        if not m:
            continue
        fid = int(m.group(1))
        ext = m.group(4).lower()
        if fid not in by_id:
            by_id[fid] = p
        elif ext == "png" and by_id[fid].suffix.lower() == ".webp":
            by_id[fid] = p  # .png wins over .webp
    image_files = sorted(by_id.values(), key=lambda p: int(FILENAME_RE.match(p.name).group(1)))

    print(f"Found {len(image_files)} portrait image files under {PORTRAITS_DIR}")
    ext_counts = {}
    for p in image_files:
        ext = p.suffix.lower()
        ext_counts[ext] = ext_counts.get(ext, 0) + 1
    print(f"  by extension: {ext_counts}")

    conn = sqlite3.connect(DB_PATH)
    try:
        # Pre-fetch fighter_id → (first_name, last_name) for verification.
        fighter_rows = conn.execute(
            "SELECT fighter_id, first_name, last_name FROM fighters"
        ).fetchall()
        fighter_map = {r[0]: (r[1], r[2]) for r in fighter_rows}
        total_fighters = len(fighter_map)
        print(f"DB has {total_fighters} fighters total.")

        assigned = 0
        skipped_no_match = 0
        skipped_bad_filename = 0
        warnings = 0
        warnings_list = []

        for img_path in image_files:
            fn = img_path.name
            m = FILENAME_RE.match(fn)
            if not m:
                print(f"  SKIP (bad filename): {fn}")
                skipped_bad_filename += 1
                continue
            fid_str, name_str, _nickname = m.group(1), m.group(2), m.group(3)
            _ext = m.group(4)
            try:
                fid = int(fid_str)
            except ValueError:
                print(f"  SKIP (bad fighter_id): {fn}")
                skipped_bad_filename += 1
                continue

            if fid not in fighter_map:
                print(f"  SKIP (fighter_id {fid} not in DB): {fn}")
                skipped_no_match += 1
                continue

            db_first, db_last = fighter_map[fid]
            file_first, file_last = split_camel_name(name_str)
            if not names_match(file_first, file_last, db_first, db_last):
                warnings += 1
                warnings_list.append(
                    f"  WARN (name mismatch): {fn} → "
                    f"file='{file_first} {file_last}' vs "
                    f"db='{db_first} {db_last}' (assigning anyway — "
                    f"fighter_id is the primary key)"
                )

            # Compute relative path (relative to data/).
            # img_path is data/portraits/batch_XXX/batch_XXX/NNNN_*.webp
            # We want portraits/batch_XXX/batch_XXX/NNNN_*.webp
            rel = img_path.relative_to(PROJECT_DIR / "data")
            rel_str = rel.as_posix()  # forward-slash for cross-platform

            conn.execute(
                "UPDATE fighters SET portrait_path=? WHERE fighter_id=?",
                (rel_str, fid),
            )
            assigned += 1

        conn.commit()

        # Final counts.
        with_portrait = conn.execute(
            "SELECT COUNT(*) FROM fighters WHERE portrait_path IS NOT NULL"
        ).fetchone()[0]
        without_portrait = total_fighters - with_portrait

        # Print warnings (limit to first 30 for readability).
        print()
        if warnings_list:
            print(f"--- {len(warnings_list)} name-mismatch warnings "
                  f"(showing first 30) ---")
            for w in warnings_list[:30]:
                print(w)
            if len(warnings_list) > 30:
                print(f"  ... and {len(warnings_list) - 30} more.")
        print()
        print("=" * 60)
        print(f"SUMMARY")
        print(f"  image files scanned:        {len(image_files)}")
        print(f"  Portraits assigned:         {assigned}")
        print(f"  Skipped (bad filename):     {skipped_bad_filename}")
        print(f"  Skipped (no DB match):      {skipped_no_match}")
        print(f"  Name-mismatch warnings:     {warnings}")
        print(f"  Fighters with portrait:     {with_portrait}")
        print(f"  Fighters without portrait:  {without_portrait}")
        print(f"  Total fighters in DB:       {total_fighters}")
        print("=" * 60)

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
