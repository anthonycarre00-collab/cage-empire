#!/usr/bin/env bash
# ============================================================
#  CAGE EMPIRE - macOS / Linux launcher
#  Run from project root:  ./run.sh
# ============================================================
set -e
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

echo
echo "[CAGE EMPIRE] Step 1/3 - Rebuild database..."
"$PYTHON" src/build_db.py

echo
echo "[CAGE EMPIRE] Step 2/3 - Seed minimal world..."
"$PYTHON" src/seed_data.py

echo
echo "[CAGE EMPIRE] Step 3/3 - Launch app..."
"$PYTHON" src/app.py
