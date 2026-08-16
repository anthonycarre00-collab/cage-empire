"""VOICE-P2 (Claude VOICE_ENFORCEMENT §5.4) — purge existing tabloid
cliché rows from news_items.headline.

The code fix in src/news.py prevents NEW tabloid-pattern headlines
from being generated. But existing rows in the live DB still contain
those patterns (377 rows at last count). This script rewrites the
existing rows in-place so the §5.4 query returns 0 rows.

Patterns purged:
  - "SCANDAL: " prefix        → replaced with "BREAKING: "
  - "BOMBSHELL: " prefix      → replaced with "BREAKING: "
  - "EXCLUSIVE: " prefix      → replaced with "WIRE FLASH: "
  - "Social Storm: " prefix   → replaced with "The Feed: "
  - "Feeds Lit: " prefix      → replaced with "The Feed: "
  - " in stunning development" suffix → replaced with " after the incident"
  - "Scandal rocks the division — " prefix → replaced with "The commission comes down on "

Idempotent: re-running this script on already-purged rows is a no-op
(the patterns it targets are gone after the first run).

Usage:
    cd /home/z/my-project/cage_empire
    python3 scripts/voice_p2_purge_tabloid_rows.py
"""
import sqlite3
import re
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cage_empire.db"


# (regex, replacement) pairs — applied in order. Each regex matches
# the literal pattern; the replacement is voice-appropriate per
# Claude §1 (promoter-flavored, specific imagery, no stock phrases).
PURGE_RULES = [
    # Tabloid prefixes — rewrite to neutral wire-service prefixes
    # that the new _SOURCE_TONE_PREFIX uses.
    (re.compile(r"^SCANDAL:\s*"),              "BREAKING: "),
    (re.compile(r"^BOMBSHELL:\s*"),            "BREAKING: "),
    (re.compile(r"^EXCLUSIVE:\s*"),            "WIRE FLASH: "),
    (re.compile(r"^Social Storm:\s*"),         "The Feed: "),
    (re.compile(r"^Feeds Lit:\s*"),            "The Feed: "),
    # Mid-phrase / suffix clichés — match anywhere in the headline.
    (re.compile(r"\s+in stunning development\s*$"), " after the incident"),
    (re.compile(r"Scandal rocks the division\s*—\s*"),
     "The commission comes down on "),
    # Any residual SCANDAL / BOMBSHELL / EXCLUSIVE / Social Storm
    # tokens that survived the prefix pass (e.g. they were already
    # mid-headline). Replace with voice-appropriate fallbacks.
    (re.compile(r"\bSCANDAL\b"),    "the incident"),
    (re.compile(r"\bBOMBSHELL\b"),  "the latest"),
    (re.compile(r"\bEXCLUSIVE\b"),  "the wire"),
    (re.compile(r"\bSocial Storm\b"), "the feed"),
]


def purge_headline(h):
    """Apply all PURGE_RULES in order. Returns the rewritten headline."""
    if not h:
        return h
    for pattern, replacement in PURGE_RULES:
        h = pattern.sub(replacement, h)
    return h


def main():
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}")
        return 1

    conn = sqlite3.connect(str(DB_PATH))

    # Count rows matching §5.4 patterns BEFORE the purge.
    before = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE headline LIKE '%SCANDAL%' "
        "   OR headline LIKE '%stunning development%' "
        "   OR headline LIKE '%Storm:%' "
        "   OR headline LIKE '%BOMBSHELL%' "
        "   OR headline LIKE '%EXCLUSIVE%' "
        "   OR headline LIKE '%Feeds Lit%'"
    ).fetchone()[0]
    print(f"  BEFORE: {before} tabloid-cliché rows in news_items.headline")

    # Pull every matching row + rewrite in-place.
    rows = conn.execute(
        "SELECT news_item_id, headline FROM news_items "
        "WHERE headline LIKE '%SCANDAL%' "
        "   OR headline LIKE '%stunning development%' "
        "   OR headline LIKE '%Storm:%' "
        "   OR headline LIKE '%BOMBSHELL%' "
        "   OR headline LIKE '%EXCLUSIVE%' "
        "   OR headline LIKE '%Feeds Lit%'"
    ).fetchall()

    rewritten = 0
    for news_id, headline in rows:
        new_h = purge_headline(headline)
        if new_h != headline:
            conn.execute(
                "UPDATE news_items SET headline=? WHERE news_item_id=?",
                (new_h, news_id),
            )
            rewritten += 1
    conn.commit()
    print(f"  REWROTE: {rewritten} rows")

    # Verify §5.4 returns 0 rows AFTER the purge.
    after = conn.execute(
        "SELECT COUNT(*) FROM news_items "
        "WHERE headline LIKE '%SCANDAL%' "
        "   OR headline LIKE '%stunning development%' "
        "   OR headline LIKE '%Storm:%' "
        "   OR headline LIKE '%BOMBSHELL%' "
        "   OR headline LIKE '%EXCLUSIVE%'"
    ).fetchone()[0]
    print(f"  AFTER: {after} tabloid-cliché rows remain")
    if after == 0:
        print("  ✓ §5.4 SWEEP PASS — 0 rows match tabloid patterns")
    else:
        print(f"  ⚠ §5.4 SWEEP PARTIAL — {after} rows still match (inspecting):")
        for r in conn.execute(
            "SELECT headline FROM news_items "
            "WHERE headline LIKE '%SCANDAL%' "
            "   OR headline LIKE '%stunning development%' "
            "   OR headline LIKE '%Storm:%' "
            "   OR headline LIKE '%BOMBSHELL%' "
            "   OR headline LIKE '%EXCLUSIVE%' LIMIT 10"
        ):
            print(f"    {r[0]!r}")

    conn.close()
    return 0 if after == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
