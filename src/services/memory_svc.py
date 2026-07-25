"""CAGE EMPIRE memory service (Stage 6 — Task 6.0).

Per docs/TASK_6_0_PLAN.md §3.5, this module ships in Task 6.0 with
ONLY the 2 populate_* functions. All other memory_svc work (queue,
mark_surfaced, pruning) defers to Task 6.7 (Fight Resolution screen).

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables.
  §13 — Design Law: Legacy pillar — memory links tell torch-passing stories.
  §15 — Event Bus: the populate_* functions are called inline from
        existing code paths (_check_retirements, _build_main_event),
        NOT via the event bus. This matches how _check_retirements
        already publishes FIGHTER_RETIRED inline.
"""
import sqlite3


def populate_style_echo(conn, replacement_fighter_id, retiring_fighter_id):
    """Write a 'style_echo' memory link if the regen replacement
    inherited the retiring fighter's style archetype.

    Called from tick_processor._check_retirements after the existing
    'successor' link INSERT. Idempotent (INSERT OR IGNORE against the
    UNIQUE constraint on fighter_id + linked_fighter_id + link_type).

    link_strength = 70 if the archetype is inherited (else skip the
    insert — no style echo if there's no style match).
    """
    # Look up both fighters' style archetype
    row = conn.execute(
        "SELECT f1.fight_style_archetype_id, f2.fight_style_archetype_id "
        "FROM fighters f1, fighters f2 "
        "WHERE f1.fighter_id=? AND f2.fighter_id=?",
        (replacement_fighter_id, retiring_fighter_id),
    ).fetchone()
    if not row:
        return
    replacement_archetype, retiring_archetype = row
    if replacement_archetype is None or retiring_archetype is None:
        return
    if replacement_archetype != retiring_archetype:
        return  # no style echo — different archetypes

    # Idempotent insert
    conn.execute(
        "INSERT OR IGNORE INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'style_echo', 70)",
        (replacement_fighter_id, retiring_fighter_id),
    )


def populate_regional_rival(conn, fighter_a_id, fighter_b_id):
    """Write a 'regional_rival' memory link if both fighters share
    a birth nation or region.

    Called from services.matchmaking._build_main_event and
    _build_co_main after fighter selection. Idempotent.

    link_strength = 50 + 10 * common_region_count (nation + region
    matches). Two fighters from the same nation AND region get 70;
    same nation only gets 60; different nations gets 50 (still linked
    — they're fighting each other, which is itself a regional story
    if they're from the same broader area).
    """
    row = conn.execute(
        "SELECT f1.birth_nation_id, f1.birth_city_id, "
        "       f2.birth_nation_id, f2.birth_city_id "
        "FROM fighters f1, fighters f2 "
        "WHERE f1.fighter_id=? AND f2.fighter_id=?",
        (fighter_a_id, fighter_b_id),
    ).fetchone()
    if not row:
        return
    a_nation, a_city, b_nation, b_city = row

    common = 0
    if a_nation is not None and a_nation == b_nation:
        common += 1
    # Check if same region (cities share a region)
    if a_city is not None and b_city is not None and a_city == b_city:
        common += 1

    link_strength = min(50 + 10 * common, 100)

    # Idempotent insert — note: regional_rival is bidirectional, so
    # we insert both directions (A→B and B→A). The UNIQUE constraint
    # on (fighter_id, linked_fighter_id, link_type) allows both.
    conn.execute(
        "INSERT OR IGNORE INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'regional_rival', ?)",
        (fighter_a_id, fighter_b_id, link_strength),
    )
    conn.execute(
        "INSERT OR IGNORE INTO fighter_memory_links "
        "(fighter_id, linked_fighter_id, link_type, link_strength) "
        "VALUES (?, ?, 'regional_rival', ?)",
        (fighter_b_id, fighter_a_id, link_strength),
    )
