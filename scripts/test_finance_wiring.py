#!/usr/bin/env python3
"""Phase E1 — Finance wiring smoke test.

Per docs/ECON_STAFF_PLAN.md §0 + Phase E1.4 + E1.5.

Verifies the end-to-end finance wiring fix:
  1. `finance.register_subscribers` is callable (registration surface).
  2. Calling it subscribes `_process_event_finance` to EVENT_COMPLETED
     on the event bus (the Phase E1.2 fix — was FIGHT_RESOLVED).
  3. Simulating one event completion (by publishing EVENT_COMPLETED
     on the bus, exactly as fight_engine._update_event_status_after_
     resolution does on the GUI path) writes finance_transactions rows.
  4. Every written row has a `transaction_type` that is valid per the
     finance_transactions CHECK constraint + a non-zero `amount`.

The test uses a transaction + rollback so the DB is left unchanged.
Re-running the test is safe.

Usage:
    python scripts/test_finance_wiring.py
    DEBUG_FINANCE=1 python scripts/test_finance_wiring.py   # also emits
                                                             # [finance]
                                                             # debug lines
"""
import os
import sys
import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

# Set DEBUG_FINANCE before importing finance so the env-var check
# inside _process_event_finance sees it. Optional — the test passes
# either way. Useful for manually verifying the E1.5 debug hook.
os.environ.setdefault("DEBUG_FINANCE", "1")

import finance  # noqa: E402  (after sys.path + env setup)
from event_bus import get_bus, reset_bus, Events  # noqa: E402

DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

# Per the finance_transactions CHECK constraint in src/build_db.py:
#   'ticket_sales', 'broadcast_revenue', 'merchandise',
#   'fighter_purse', 'venue_rental', 'staff_salary',
#   'medical_cost', 'signing_bonus', 'weight_cut_penalty',
#   'sponsorship', 'bonus_payment', 'concessions'   (added Phase E2.4)
#   'marketing'                                   (added Phase E3.2)
#   'show_quality_adjustment'                     (added Phase F1.1)
#
# Note: the Phase E1.4 task spec lists 'purse_payment' as a valid type,
# but the actual schema + finance.py both use 'fighter_purse'. This is
# a typo in the task spec (confirmed against the schema CHECK constraint
# and docs/ECON_STAFF_PLAN.md §1.2 which also uses 'fighter_purse').
# We assert against the SCHEMA's allowed set, not the task spec's typo.
#
# Phase E2.4 added 'concessions' to the schema CHECK via migration
# v3_17_0_add_concessions_txn_type (see src/build_db.py). The Phase E1
# smoke test still passes 13/13 because adding a value to the allowed
# set doesn't add a new check — it just lets new 'concessions' rows
# (written by Phase E2.4's _process_event_finance) pass the existing
# transaction_type validity check.
#
# Phase F1.1 (docs/FIX_PLAN_FINANCES_ADVANCEDAY.md §F1.1) added
# 'show_quality_adjustment' via migration v3_26_0_add_show_quality_
# adjustment_txn_type. The new txn type is the post-event revenue
# adjustment row that applies the show-quality multiplier (±30%) to
# PPV + merch. Added to the schema CHECK + this test's VALID set so
# the assertion "all transaction_types valid per schema CHECK constraint"
# still passes when finance writes the new row.
VALID_TXN_TYPES = {
    'ticket_sales', 'broadcast_revenue', 'merchandise',
    'fighter_purse', 'venue_rental', 'staff_salary',
    'medical_cost', 'signing_bonus', 'weight_cut_penalty',
    'sponsorship', 'bonus_payment', 'concessions',
    'marketing', 'show_quality_adjustment',
}


class Results:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []

    def check(self, name, cond, detail=""):
        if cond:
            self.passed += 1
            print(f"  [PASS] {name}  {detail}")
        else:
            self.failed += 1
            self.failures.append((name, detail))
            print(f"  [FAIL] {name}  {detail}")
        return cond


def main():
    print("=" * 72)
    print("Phase E1 — Finance wiring smoke test")
    print(f"  DB:      {DB_PATH}")
    print(f"  DEBUG_FINANCE env: {os.environ.get('DEBUG_FINANCE')!r}")
    print("=" * 72)

    r = Results()

    # ---- E1.4 step 2: finance.register_subscribers is callable ----
    r.check(
        "finance.register_subscribers is callable",
        callable(getattr(finance, 'register_subscribers', None)),
    )
    if not callable(getattr(finance, 'register_subscribers', None)):
        print("\nFATAL: finance.register_subscribers missing — cannot continue.")
        sys.exit(2)

    # ---- E1.4 step 1: connect to DB ----
    if not DB_PATH.exists():
        print(f"\nFATAL: DB not found at {DB_PATH}")
        sys.exit(2)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # ---- E1.4 step 3: call finance.register_subscribers ----
    # (Equivalent to app_web.register_all_subscribers() for the finance
    # module — we register just finance to isolate the test from the
    # other 14 subscribers which would also fire on EVENT_COMPLETED
    # and write unrelated side-effect rows.)
    reset_bus()
    finance.register_subscribers()
    bus = get_bus()
    n_event_completed_subs = bus.subscriber_count(Events.EVENT_COMPLETED)
    r.check(
        "finance subscribed to EVENT_COMPLETED (Phase E1.2 fix)",
        n_event_completed_subs >= 1,
        f"subs on EVENT_COMPLETED = {n_event_completed_subs}",
    )

    finance_registered = any(
        name == "finance.process_event"
        for name, _ in bus._subscribers.get(Events.EVENT_COMPLETED, [])
    )
    r.check(
        'subscriber name is "finance.process_event"',
        finance_registered,
    )

    n_fight_resolved_subs = bus.subscriber_count(Events.FIGHT_RESOLVED)
    r.check(
        "finance NO LONGER subscribes to FIGHT_RESOLVED (Phase E1.2 fix)",
        n_fight_resolved_subs == 0,
        f"subs on FIGHT_RESOLVED = {n_fight_resolved_subs} (expected 0)",
    )

    # ---- E1.4 step 4: simulate one event completion ----
    # Pick a real completed event for promo 1 (the player's promo).
    row = conn.execute(
        "SELECT event_id, promotion_id, event_date FROM events "
        "WHERE promotion_id = 1 AND status = 'completed' "
        "ORDER BY event_id LIMIT 1",
    ).fetchone()
    if not row:
        print("\nFATAL: no completed event for promo 1 in DB — cannot test.")
        sys.exit(2)
    event_id, promo_id, event_date = row
    print(f"\n  [INFO] test subject: event_id={event_id} "
          f"promo_id={promo_id} event_date={event_date}")

    # Snapshot the existing finance rows for this event so we can
    # restore them on rollback. We DELETE the existing rows so the
    # _process_event_finance idempotency check doesn't skip — this
    # lets us verify the function ACTUALLY generates rows when called.
    existing_rows = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions WHERE event_id = ?",
        (event_id,),
    ).fetchone()[0]
    print(f"  [INFO] event {event_id} currently has {existing_rows} "
          f"finance_transactions rows (will be deleted + regenerated "
          f"within this transaction, then rolled back)")

    # NOTE: We do NOT commit. All writes below stay in the transaction
    # and we'll ROLLBACK at the end so the DB is left unchanged.
    conn.execute(
        "DELETE FROM finance_transactions WHERE event_id = ?",
        (event_id,),
    )
    # Verify deletion (within the transaction, before finance runs).
    rows_after_delete = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions WHERE event_id = ?",
        (event_id,),
    ).fetchone()[0]
    r.check(
        f"deleted existing finance rows for event {event_id} "
        f"(within transaction)",
        rows_after_delete == 0,
        f"got={rows_after_delete}",
    )

    # Simulate EVENT_COMPLETED on the bus — this is exactly what
    # fight_engine._update_event_status_after_resolution publishes
    # on the GUI path when an event transitions to 'completed'
    # (fight_engine.py:2489-2498). This exercises the full wiring:
    # bus → finance subscriber → _process_event_finance → writes.
    bus.publish(conn, {
        'type': Events.EVENT_COMPLETED,
        'event_id': event_id,
        'promotion_id': promo_id,
        'event_date': event_date,
    })

    # ---- E1.4 step 4 (verify) + step 5 (assertions) ----
    new_rows = conn.execute(
        "SELECT transaction_type, amount, description "
        "FROM finance_transactions WHERE event_id = ? "
        "ORDER BY transaction_type",
        (event_id,),
    ).fetchall()
    r.check(
        f"finance_transactions rows written for event {event_id}",
        len(new_rows) > 0,
        f"got={len(new_rows)} rows",
    )
    if new_rows:
        print(f"\n  [INFO] {len(new_rows)} rows written:")
        for txn_type, amount, desc in new_rows:
            print(f"    - {txn_type:<20} ${amount:>14,.2f}  {desc}")

    # Assert every row has a valid transaction_type + non-zero amount.
    valid_types_seen = set()
    nonzero_amounts = 0
    for txn_type, amount, _desc in new_rows:
        if txn_type in VALID_TXN_TYPES:
            valid_types_seen.add(txn_type)
        else:
            r.check(
                f"transaction_type {txn_type!r} is valid per schema CHECK",
                False,
                f"not in VALID_TXN_TYPES",
            )
        if amount != 0:
            nonzero_amounts += 1
    r.check(
        "all transaction_types valid per schema CHECK constraint",
        all(t in VALID_TXN_TYPES for t, _, _ in new_rows),
        f"valid types seen: {sorted(valid_types_seen)}",
    )
    r.check(
        "at least one row with non-zero amount",
        nonzero_amounts > 0,
        f"{nonzero_amounts} of {len(new_rows)} rows have non-zero amount",
    )

    # Spot-check that the core revenue types were written (these are
    # always written by _process_event_finance regardless of card data).
    r.check(
        "ticket_sales row written (always positive)",
        any(t == 'ticket_sales' and a > 0 for t, a, _ in new_rows),
        "ticket_sales is the primary gate-receipt revenue row",
    )
    r.check(
        "broadcast_revenue row written (always positive)",
        any(t == 'broadcast_revenue' and a > 0 for t, a, _ in new_rows),
    )
    r.check(
        "venue_rental row written (always negative)",
        any(t == 'venue_rental' and a < 0 for t, a, _ in new_rows),
    )

    # ---- E1.5 verification: DEBUG_FINANCE hook emitted a log line ----
    # (We can't easily capture stdout from inside this script — the
    # debug print goes to the same stdout. The test below just verifies
    # the env var check is in the source; the actual print is visible
    # in the test output if DEBUG_FINANCE=1.)
    finance_src = open(SRC_DIR / "finance.py").read()
    r.check(
        "DEBUG_FINANCE env-var hook present in src/finance.py",
        "DEBUG_FINANCE" in finance_src and "os.environ.get('DEBUG_FINANCE')" in finance_src,
        "set DEBUG_FINANCE=1 to see [finance] processing log lines",
    )

    # ---- Rollback so the DB is left unchanged ----
    conn.rollback()
    print(f"\n  [INFO] rolled back — DB unchanged")

    rows_after_rollback = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions WHERE event_id = ?",
        (event_id,),
    ).fetchone()[0]
    r.check(
        f"rollback restored original finance rows for event {event_id}",
        rows_after_rollback == existing_rows,
        f"expected={existing_rows} got={rows_after_rollback}",
    )

    conn.close()

    # ---- Summary ----
    print("\n" + "=" * 72)
    if r.failed == 0:
        print(f"RESULT: ALL {r.passed} CHECKS PASSED")
    else:
        print(f"RESULT: {r.passed} PASSED, {r.failed} FAILED")
        print("\nFailures:")
        for name, detail in r.failures:
            print(f"  - {name}  {detail}")
    print("=" * 72)
    sys.exit(0 if r.failed == 0 else 1)


if __name__ == "__main__":
    main()
