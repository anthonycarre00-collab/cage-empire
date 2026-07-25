#!/usr/bin/env bash
# ============================================================
#  CAGE EMPIRE - macOS / Linux launcher + build tool
#
#  Usage:
#    ./run.sh                Launch the game (uses existing DB)
#    ./run.sh build-world    Full world rebuild (phase 1-5, ~10s, 4900+ fighters)
#    ./run.sh build-dev      Minimal dev rebuild (5 fighters for testing)
#    ./run.sh migrate        Apply schema migrations to existing DB (preserves world)
#    ./run.sh check          Forensic DB integrity check
#    ./run.sh test           Run all 38 acceptance tests
#    ./run.sh backfill       Backfill retired legends' attributes
#
#  Run from project root:  ./run.sh <mode>
# ============================================================
set -e
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

mode="${1:-run}"

case "$mode" in
    run)
        echo "[CAGE EMPIRE] Launching game..."
        "$PYTHON" src/app.py
        ;;
    build-world)
        echo "[CAGE EMPIRE] Full world rebuild (DESTROYS existing DB)..."
        echo ""
        echo "Step 1/8: Fresh build (schema only)..."
        "$PYTHON" src/build_db.py --fresh
        echo ""
        echo "Step 2/8: World seed phase 1 (nations, regions, cities, venues, weight classes, names)..."
        "$PYTHON" scripts/seed_world_phase1.py
        echo ""
        echo "Step 3/8: World seed phase 2 (gyms, promotions, staff)..."
        "$PYTHON" scripts/seed_world_phase2.py
        echo ""
        echo "Step 4/8: Parse fighter profiles from download/fighter_image_prompts.txt..."
        "$PYTHON" scripts/parse_fighter_profiles.py
        echo ""
        echo "Step 5/8: Assign attributes from bio keywords..."
        "$PYTHON" scripts/assign_attributes_from_bios.py
        echo ""
        echo "Step 6/8: World seed phase 3 (4000 fighters FROM PROFILES)..."
        "$PYTHON" scripts/seed_world_phase3_from_profiles.py
        echo ""
        echo "Step 7/8: World seed phase 4 (career histories, fights, titles, contracts)..."
        "$PYTHON" scripts/seed_world_phase4.py
        echo ""
        echo "Step 7.5/8: World seed phase 5 (bios, gym histories, retired legends, news)..."
        "$PYTHON" scripts/seed_world_phase5.py
        echo ""
        echo "Step 8/8: Backfill retired legends' attributes..."
        "$PYTHON" scripts/backfill_legends.py
        echo ""
        echo "[CAGE EMPIRE] World rebuild complete."
        echo "Run './run.sh check' to verify DB integrity."
        ;;
    build-dev)
        echo "[CAGE EMPIRE] Minimal dev rebuild (5 fighters)..."
        "$PYTHON" src/build_db.py --fresh
        "$PYTHON" src/seed_data.py
        echo "[CAGE EMPIRE] Dev rebuild complete."
        ;;
    migrate)
        echo "[CAGE EMPIRE] Applying schema migrations (preserves world data)..."
        echo "Backing up DB first..."
        cp data/cage_empire.db "data/cage_empire.db.backup-$(date +%Y%m%d%H%M%S)"
        "$PYTHON" src/build_db.py --migrate
        echo "[CAGE EMPIRE] Migration complete."
        echo "Run './run.sh check' to verify DB integrity."
        ;;
    check)
        echo "[CAGE EMPIRE] Forensic DB integrity check..."
        "$PYTHON" scripts/forensic_db_check.py --verbose
        ;;
    test)
        echo "[CAGE EMPIRE] Running all acceptance tests..."
        PASS=0; FAIL=0; FAILED=""
        for f in scripts/test_*.py; do
            out=$("$PYTHON" "$f" 2>&1)
            real_fails=$(echo "$out" | grep -cE "\[FAIL\]|  FAIL  ")
            if [ "$real_fails" -gt 0 ]; then
                FAIL=$((FAIL+1))
                FAILED="$FAILED $(basename $f)"
            else
                PASS=$((PASS+1))
            fi
            basename=$(basename "$f")
            if [ "$real_fails" -gt 0 ]; then
                echo "  FAIL  $basename"
            else
                echo "  PASS  $basename"
            fi
        done
        echo ""
        echo "Results: $PASS pass / $FAIL fail out of $((PASS+FAIL)) tests"
        if [ "$FAIL" -gt 0 ]; then
            echo "Failed tests:$FAILED"
            exit 1
        fi
        ;;
    backfill)
        echo "[CAGE EMPIRE] Backfilling retired legends' attributes..."
        "$PYTHON" scripts/backfill_legends.py
        echo "[CAGE EMPIRE] Backfill complete."
        ;;
    *)
        echo "Usage: ./run.sh [run|build-world|build-dev|migrate|check|test|backfill]"
        echo ""
        echo "  run          Launch the game (default)"
        echo "  build-world  Full world rebuild (4900+ fighters, ~10s)"
        echo "  build-dev    Minimal dev rebuild (5 fighters for testing)"
        echo "  migrate      Apply schema migrations (preserves world data)"
        echo "  check        Forensic DB integrity check"
        echo "  test         Run all 38 acceptance tests"
        echo "  backfill     Backfill retired legends' attributes"
        exit 1
        ;;
esac
