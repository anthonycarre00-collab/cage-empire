"""CAGE EMPIRE — Voice display helpers (Task UI-POLISH, Fix 5).

Centralizes the "make voice phrases look good in the UI" logic so
every Office Mode screen applies the SAME capitalisation rules.
Without this, phrases from `voice.py` (e.g., "carries real knockout
power", "an up-and-comer knocking on the door of title contention",
"experienced hand") would appear in lowercase — which the user
flagged as ugly ("Ugly text/fonts with no capital letters").

CONVENTIONS compliance:
  §14 — Voice Layer: this module NEVER reveals raw attribute values.
        It only transforms the PHRASE STRINGS produced by voice.py +
        the interpretation layer. The capitalisation is purely a
        display concern — no semantic content is added or removed.
  §17 — UI Snapshot Rule: this module reads NOTHING from the DB. It
        is a pure string-transformation utility. Callers feed it
        decoded phrases from `fighter_descriptors` cache columns.

Why a separate module (not inline in each screen):
  - Single source of truth — every screen applies the same rules.
  - Testable in isolation — `python -c "from ui.voice_display import
    title_case_phrase; print(title_case_phrase('an up-and-comer'))"`.
  - Future-proof — when the brief adds more display rules (e.g.,
    "expand abbreviations", "strip trailing punctuation"), they go
    here, not scattered across 6 screen files.

Usage:
  from ui.voice_display import title_case_phrase, display_phrase

  # title_case_phrase: capitalise first letter of each significant
  # word. Skips small words (a, an, the, and, or, but, of, in, on,
  # to, for, with, by) unless they're the first word.
  title_case_phrase("riding a hot streak")  # → "Riding a Hot Streak"
  title_case_phrase("an up-and-comer")      # → "An Up-and-Comer"
  title_case_phrase("carries real knockout power")  # → "Carries Real Knockout Power"

  # display_phrase: decode a "label||phrase" cache value + apply
  # title_case. Returns the fallback if the cache value is NULL or
  # doesn't contain "||".
  display_phrase("very_high||on fire and unstoppable right now",
                 fallback="(uncached)")
  # → "On Fire and Unstoppable Right Now"
"""

# Small words that should NOT be capitalised in title case (unless
# they're the first word of the phrase). Standard journalistic title
# case convention. Hyphenated compounds are split + each part is
# capitalised (so "up-and-comer" → "Up-and-Comer").
_SMALL_WORDS = frozenset({
    "a", "an", "the",
    "and", "or", "but", "nor", "so", "yet",
    "of", "in", "on", "at", "to", "for", "with", "by", "from",
    "as", "into", "onto", "over", "under", "via",
    "vs", "vs.",
})


def _capitalise_word(word):
    """Capitalise a single word for title case.

    Handles hyphenated compounds ("up-and-comer" → "Up-and-Comer")
    by splitting on hyphens, capitalising each non-small part, and
    rejoining. Preserves digits + punctuation (e.g., "R2" stays "R2",
    "T.K.O." stays "T.K.O."). Handles leading punctuation like
    "(uncached)" → "(Uncached)" by finding the first alphabetic
    character and capitalising it.

    Args:
        word: a single word (no internal spaces), possibly with
            hyphens.

    Returns:
        The title-cased word.
    """
    if not word:
        return word
    # Split on hyphens to handle "up-and-comer" style compounds.
    parts = word.split("-")
    out = []
    for i, part in enumerate(parts):
        if not part:
            out.append(part)
            continue
        lower = part.lower()
        # Small words inside a hyphenated compound stay lowercase
        # ("up-and-comer" → "Up-and-Comer" — "and" stays lowercase,
        # but "up" + "comer" are capitalised because they're the
        # first/last parts of the compound).
        if i > 0 and lower in _SMALL_WORDS:
            out.append(lower)
            continue
        # Find the first alphabetic character + capitalise it. This
        # handles leading punctuation like "(uncached)" → "(Uncached)"
        # without disturbing the rest of the word.
        idx = -1
        for j, ch in enumerate(part):
            if ch.isalpha():
                idx = j
                break
        if idx < 0:
            # No alphabetic chars — preserve as-is (e.g., "R2" has
            # alphabetic 'R' so this branch isn't hit; pure digit
            # strings like "2" have no letters to capitalise).
            out.append(part)
        elif idx == 0:
            out.append(part[0].upper() + part[1:])
        else:
            out.append(part[:idx] + part[idx].upper() + part[idx+1:])
    return "-".join(out)


def title_case_phrase(phrase):
    """Convert a voice phrase to Title Case for display.

    The voice.py module returns lowercase phrases (e.g., "carries
    real knockout power"). This helper capitalises the first letter
    of each significant word while preserving small words (a, the,
    of, in, etc.) in lowercase — standard journalistic title case.

    Examples:
        "riding a hot streak"           → "Riding a Hot Streak"
        "an up-and-comer"               → "An Up-and-Comer"
        "carries real knockout power"   → "Carries Real Knockout Power"
        "can't be knocked out"          → "Can't Be Knocked Out"
        "experienced hand"              → "Experienced Hand"
        "iron chin"                     → "Iron Chin"

    Args:
        phrase: the raw voice phrase string (may be None or empty).

    Returns:
        The title-cased phrase, or "" if input is None/empty.
    """
    if not phrase:
        return ""
    s = str(phrase).strip()
    if not s:
        return ""
    words = s.split()
    out = []
    for i, word in enumerate(words):
        if not word:
            out.append(word)
            continue
        lower = word.lower()
        # Small words after the first stay lowercase.
        if i > 0 and lower in _SMALL_WORDS:
            out.append(lower)
        else:
            out.append(_capitalise_word(word))
    return " ".join(out)


def display_phrase(stored_value, fallback=""):
    """Decode a "label||phrase" cache value + title-case it for display.

    Single source of truth for the cache-column decode + display
    pattern used by every Office Mode screen. Mirrors the
    `decode_phrase` helper in interpretation.context_engine but
    applies title-case on top so the UI shows properly capitalised
    text.

    Per §17.4: the UI displays the voice PHRASE (after ||), never
    the canonical label (before ||). If the stored value is NULL or
    doesn't contain "||", return the caller-provided fallback
    (also title-cased, since fallbacks are usually short phrases
    like "(uncached)" or "(none)").

    Args:
        stored_value: the raw cache column value (e.g.,
            "rising_contender||an up-and-comer knocking on the door
            of title contention").
        fallback: the string to return if decode fails. Title-cased
            so it reads consistently with decoded phrases.

    Returns:
        The title-cased voice phrase, or the title-cased fallback.
    """
    if not stored_value or "||" not in str(stored_value):
        return title_case_phrase(fallback) if fallback else ""
    phrase = str(stored_value).split("||", 1)[1]
    return title_case_phrase(phrase)


def display_attr_descriptor(descriptor_str):
    """Title-case an attribute descriptor from the JSON cache.

    The `fighter_descriptors.attribute_descriptors` JSON column
    stores descriptors DIRECTLY (no "||" prefix) — voice.py already
    applied describe_attribute when building the snapshot. This
    helper just title-cases the stored phrase for display.

    Args:
        descriptor_str: the descriptor string from the JSON (e.g.,
            "carries real knockout power"). May be None.

    Returns:
        The title-cased descriptor, or "(Uncached)" if input is
        None/empty (uses the standard fallback convention).
    """
    if not descriptor_str:
        return "(Uncached)"
    return title_case_phrase(descriptor_str)
