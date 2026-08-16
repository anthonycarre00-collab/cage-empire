"""CAGE EMPIRE Headline Engine (Phase 2 Task 2.6 + VOICE-P2).

Generates 4 MVP daily headlines from interpreted state, written to the
`daily_headlines` table at the end of the daily interpretation pass.

Per spec §8 (Headline Generation) + PHASE_2_PLAN §5 Task 2.6: each day,
generate:
  1. Top Story         — the biggest narrative of the day
  2. Upset of the Week — biggest upset in the last 7 days (if any)
  3. Fastest Rising    — fighter with the best momentum improvement
  4. Biggest Fall      — fighter with the worst momentum decline

The spec lists 8 headline types; we ship 4 in MVP (per §4 MVP Cut —
~40% content volume, ~80% player-perceived value). The 4 deferred
types (contract_drama, gym_of_month, veteran_watch, prospect_watch)
are tracked by the daily_headlines CHECK constraint (added in v3.11.0)
so adding them in Phase 3+ requires only engine code — no schema change.

Per CONVENTIONS §17.1: this module is the ONLY writer to the
`daily_headlines` cache table (alongside snapshot_cache, which is the
orchestrator). It NEVER writes to simulation tables (fighters, fight_
history, rankings, etc.). It READS from fighter_descriptors + fight_
history + rankings — those reads are safe (the interpretation layer
is allowed to read anything; it just can't WRITE to simulation tables).

Per CONVENTIONS §14: every headline_text + body_text is VOICE-LAYERED
— no raw numbers. "The fallen champion's reign crumbles" not
"record_wins went from 18 to 18-3". The voice layer (§14.3) is applied
via free-form voice phrases (NOT the "label||phrase" cache-column
format used by the other interpretation engines — the daily_headlines
table stores the text directly, not a label).

Per CONVENTIONS §17.5: the engine runs at the end of the daily pass
(after context_engine + career_phase + narrative_families + legacy
have all populated fighter_descriptors). MUST complete in <100ms for
the 4 headlines (4 small SELECTs against indexed columns — well under
the daily-pass budget).

Idempotency: each headline is written with INSERT OR REPLACE against
the UNIQUE (headline_date, headline_type) constraint. Re-running the
engine for the same date overwrites the 4 rows. This means the daily
pass is safe to re-run on the same day (e.g., during testing) without
producing duplicate headlines. The template + subject selection MUST
be deterministic given (current_date, headline_type) so the overwrite
produces the SAME row (no UI flickering between re-runs).

DESIGN DECISIONS (D-numbers — referenced from the worklog):
  D1  4 MVP headline types cut from the spec's 8 (per PHASE_2_PLAN
      §5, Task 2.6 + §4 MVP Cut). The 4 deferred types
      (contract_drama, gym_of_month, veteran_watch, prospect_watch)
      are CHECK'd in the daily_headlines schema (added in v3.11.0) so
      Phase 3+ can add them without a schema change.
  D2  Top Story priority order (first match wins):
        1. fallen_champion    — career_phase=declining + title_reigns>0
                                + momentum in (falling, collapsing)
        2. prodigy             — career_phase=prospect + momentum in
                                (very_high, high)
        3. cinderella_story    — career_phase=rising_contender +
                                momentum=very_high + age>=28
        4. veteran             — career_phase=veteran + momentum in
                                (stable, falling)
      The priority reflects narrative weight: a fallen champion IS
      the top story (the king is dead), a prodigy is next (the future
      is now), a cinderella story is third (the underdog is rising),
      a veteran is fourth (the old guard holds on). If NO fighter
      matches any family, the headline is skipped (NULL fighter_id,
      body_text="A quiet day across the promotions.").
  D3  Upset of the Week uses the rankings.rating column as the
      "expected winner" proxy. The fight_history table records
      (fighter_id, opponent_id, outcome) — we look for fights in the
      last 7 days where the WINNER had a LOWER rating than the LOSER
      (the upset). The "biggest" upset = the largest rating gap
      favoring the loser. If no fights in the last 7 days, this
      headline is skipped. The rating is rendered as a voice band
      ("underdog" / "heavy underdog" / "shocking upset") per §14.
  D4  Fastest Rising: query fighter_descriptors for momentum='very_
      high' AND career_phase='prospect' (the canonical prodigy
      criteria — a young fighter on a hot streak). If none match,
      fall back to momentum='high' AND career_phase='prospect' (a
      prospect on a smaller streak). If still none, fall back to
      momentum='very_high' (any fighter on a 5+ win streak). The
      fallback chain ensures the headline almost always has a
      subject.
  D5  Biggest Fall: query fighter_descriptors for momentum='collapsing'
      (3+ loss streak). If none match, fall back to momentum='falling'
      (2 loss streak). If still none, skip the headline (a day with
      no falling fighters is a quiet day).
  D6  Each headline is written with INSERT OR REPLACE against the
      UNIQUE (headline_date, headline_type) constraint. This makes
      the engine IDEMPOTENT — re-running for the same date replaces
      the 4 rows, doesn't duplicate them. Important for testing + for
      the daily pass (which may run multiple times on the same day
      during bulk-tick).
  D7  Voice phrases only (CONVENTIONS §14). The headline_text is
      short + punchy (think newspaper headline — verb-driven, no
      digits). The body_text is 1-2 sentences expanding on the
      headline. Both use voice bands, not raw numbers.
  D8  The engine NEVER raises — a failed headline write is caught +
      logged. The daily pass must not crash because one headline
      failed. Same defensive pattern as the memory_engine + the other
      interpretation engines.
  D9  The engine reads the canonical-label prefix from fighter_
      descriptors columns via the `decode_label` helper (reused from
      context_engine — single source of truth for the "label||phrase"
      format). This is the SAME pattern as narrative_families + legacy
      _engine — the bulk-load writes "label||phrase", readers parse
      out the label for rule logic.
  D10 The engine is called by snapshot_cache._generate_headlines at
      the END of the daily pass (after fighter_descriptors is fully
      populated). If the daily pass is skipped (e.g., bulk-tick mode),
      headlines are also skipped — they're derived from fighter_
      descriptors, so they're only as fresh as the last daily pass.

VOICE-P2 (Claude VOICE_ENFORCEMENT §2.3 + §3 + §5.2):
  P2-A  SUBJECT ROTATION. The prior version picked the same fighter
        every day for fastest_rising/biggest_fall (always the lowest
        fighter_id matching the criteria) + the same fallen_champion
        / prodigy every day for top_story. Result: the SAME headline
        appeared for 91 consecutive sim-days (verified live: "Daniel
        Gonzalez is sliding fast" × 91). The fix: collect ALL
        qualifying candidates (up to N=12), then pick one via a
        deterministic hash of (current_date, headline_type). This
        rotates subjects day-to-day without flickering (same date →
        same pick; different date → different pick).
  P2-B  TEMPLATE EXPANSION. The prior version had 1 template per
        (headline_type, narrative_family) pair — Claude's §3 bar is
        ≥8. Added 5 banks (top_story × 5 families + fastest_rising ×
        5 + biggest_fall × 5 + upset_of_week × 5) with 8 templates
        each. Templates follow Claude §1 voice: promoter-flavored,
        past-tense narrative, specific imagery, hedged uncertainty
        for scouting, elegiac for decline. No sports-page filler
        ("is rising fast" alone), no tabloid clickbait.
  P2-C  NO-REPEAT PATTERN. A given fighter can only "win" a given
        headline type once per sim-week — if the deterministic hash
        would pick a fighter who already won that type within the
        last 7 sim-days, the engine moves to the next candidate.
        This eliminates the "same headline 31 consecutive days"
        failure even when only one fighter qualifies.
  P2-D  DETERMINISTIC TEMPLATE PICKER. The template is selected via
        a deterministic hash of (current_date, headline_type,
        fighter_id) so re-running for the same date produces the
        SAME template (idempotent INSERT OR REPLACE, no UI flicker).
        Different fighter or different date → different template.
"""
import hashlib
import sqlite3
from datetime import datetime, timedelta


# Reuse the decode_label helper from context_engine (D9) — single
# source of truth for the "label||phrase" storage format.
from interpretation.context_engine import decode_label


# ============================================================
# HEADLINE TYPE CONSTANTS
# ============================================================
# These match the CHECK'd enum on daily_headlines.headline_type (added
# in v3.11.0). Tests read these; the engine writes them.

HEADLINE_TOP_STORY = "top_story"
HEADLINE_UPSET_OF_WEEK = "upset_of_week"
HEADLINE_FASTEST_RISING = "fastest_rising"
HEADLINE_BIGGEST_FALL = "biggest_fall"

ALL_HEADLINE_TYPES = (
    HEADLINE_TOP_STORY,
    HEADLINE_UPSET_OF_WEEK,
    HEADLINE_FASTEST_RISING,
    HEADLINE_BIGGEST_FALL,
)


# ============================================================
# VOICE-P2 (Claude §3): HEADLINE TEMPLATE BANKS
# ============================================================
# 5 banks per headline type, keyed by narrative_family (or "default"
# for fighters with no family). 8 templates per (type, family) pair
# per Claude's §3 minimum variety bar.
#
# Voice follows Claude §1: promoter-flavored, past-tense narrative,
# specific imagery, hedged uncertainty for scouting, elegiac for
# decline. NO sports-page filler standing alone ("is rising fast"),
# NO tabloid clickbait ("SCANDAL:", "in stunning development").
#
# Each template is a format string with named slots:
#   - {name}        : the featured fighter's full name
#   - {last}        : the featured fighter's last name (punchier)
#   - {winner}      : (upset_of_week only) the winner's full name
#   - {loser}       : (upset_of_week only) the loser's full name
#   - {result_phrase}: (upset_of_week only) the finish type phrase
#   - {upset_band}  : (upset_of_week only) the magnitude phrase
# The template picker fills these via str.format(**headline).

# ---- Top Story (4 narrative families + default) × 8 templates = 40 ----
_TOP_STORY_TEMPLATES = {
    "fallen_champion": [
        {"headline_text": "Once the king, now the question",
         "body_text": "{name}'s decline has gone from a slow fade to a real conversation. The matchmakers are watching."},
        {"headline_text": "The crown slips, the throne empties",
         "body_text": "{name} can't buy a win these days. The version the division remembers is gone."},
        {"headline_text": "The fallen champion's reign crumbles",
         "body_text": "{name} — once the king of the division — slides further from glory. The crown is fading fast."},
        {"headline_text": "The long goodbye continues for {last}",
         "body_text": "{name} keeps searching for the version that held the belt. Father time is winning."},
        {"headline_text": "The throne is empty, the courtroom is loud",
         "body_text": "{name} — the belt long gone — fights on, but the division has already moved on."},
        {"headline_text": "The once-king wanders the undercard",
         "body_text": "{name} is no longer the main event. The slide that started quietly is getting louder."},
        {"headline_text": "A champion's echo, fading",
         "body_text": "{name} still fights with the name, but not the form. The crown has slipped, the throne emptied."},
        {"headline_text": "{last} — the legend looking for an exit",
         "body_text": "{name} keeps showing up. The results don't match the resume anymore. The end is in sight."},
    ],
    "prodigy": [
        {"headline_text": "The can't-miss kid isn't missing",
         "body_text": "{name} keeps delivering on the promise. The hype train has left the station and the division is chasing."},
        {"headline_text": "The wunderkind everyone's talking about",
         "body_text": "{name} is the can't-miss kid — and right now, nobody's missing him. The matchmakers can't ignore him anymore."},
        {"headline_text": "The future arrives early",
         "body_text": "{name} is fighting like a man who's been here for years. He hasn't. The division is on notice."},
        {"headline_text": "Scorching the earth on the way up",
         "body_text": "{name} is running through opponents like the clock is wrong about his age. The title shot is coming."},
        {"headline_text": "The prodigy turns heads again",
         "body_text": "{name} keeps proving the hype is real. The division's brightest young talent continues to surge."},
        {"headline_text": "{last} makes the old hands look slow",
         "body_text": "{name} is the prospect the veterans don't want on their card. The gap is widening, not closing."},
        {"headline_text": "A star is being written in real time",
         "body_text": "{name} adds another chapter to the early-career story. The ceiling isn't in sight yet."},
        {"headline_text": "The division's next name is here",
         "body_text": "{name} is no longer a prospect to watch — he's the prospect to fear. The title conversation starts now."},
    ],
    "cinderella_story": [
        {"headline_text": "Nobody saw this rise coming",
         "body_text": "{name} — once an afterthought — is now the division's most improbable contender. The Cinderella story rolls on."},
        {"headline_text": "The ultimate underdog story, unfolding",
         "body_text": "{name} keeps defying the odds. The late-blooming run that nobody predicted has legs."},
        {"headline_text": "Out of nowhere, into the conversation",
         "body_text": "{name} was an afterthought a year ago. Now the division has to take him seriously. The rise is real."},
        {"headline_text": "The Cinderella story keeps writing itself",
         "body_text": "{name} adds another improbable win to the run. The matchmakers are running out of reasons to keep him off the card."},
        {"headline_text": "Late bloomer, fast riser",
         "body_text": "{name} is the fighter nobody wanted, the contender nobody saw coming. The story picks up speed."},
        {"headline_text": "The division's quietest roar",
         "body_text": "{name} was supposed to be a footnote. The footnote is becoming a chapter."},
        {"headline_text": "{last} refuses to be a footnote",
         "body_text": "{name} keeps crashing the contender party. The invite list keeps getting rewritten."},
        {"headline_text": "From the shadows, into the spotlight",
         "body_text": "{name} spent years on the undercard. Those days are over. The Cinderella run is the division's best story."},
    ],
    "veteran": [
        {"headline_text": "The veteran refuses to fade",
         "body_text": "{name} — grizzled, battle-tested, still going — proves there's life in the old warhorse yet."},
        {"headline_text": "The old soul still has chapters left",
         "body_text": "{name} keeps showing up. The division's old soul isn't ready for the exit yet."},
        {"headline_text": "Seen it all, done it all, still standing",
         "body_text": "{name} has been on this card for years. The new wave keeps coming. He keeps answering."},
        {"headline_text": "The grizzled hand holds the line",
         "body_text": "{name} — the kind of veteran you build a card around — won't go quietly. The division still has to deal with him."},
        {"headline_text": "{last} won't write the final chapter yet",
         "body_text": "{name} is past his peak, sure. But the peak was high enough that what's left is still trouble."},
        {"headline_text": "The division's old guard holds",
         "body_text": "{name} is the kind of fighter the prospects study on tape. He's still here, still teaching lessons."},
        {"headline_text": "A career that won't close",
         "body_text": "{name} keeps finding the next fight. The farewell tour keeps getting postponed."},
        {"headline_text": "{last} — still the fighter the room respects",
         "body_text": "{name} may not be the main event anymore. But the main event still asks about him."},
    ],
    "default": [
        {"headline_text": "The division has a new story to tell",
         "body_text": "{name} is the name on everyone's lips today. The narrative is shifting."},
        {"headline_text": "The matchup math just changed",
         "body_text": "{name} is the fighter the matchmakers are talking about. The conversation is moving."},
        {"headline_text": "{last} forces the division to take notice",
         "body_text": "{name} is the story today — not because of a single win, but because of what's building."},
        {"headline_text": "A quiet shift, a loud signal",
         "body_text": "{name} is the fighter the scouts are whispering about. The floor is moving."},
        {"headline_text": "The kind of day that shifts a division",
         "body_text": "{name} isn't a headline name yet — but the headline is coming. The momentum is his."},
        {"headline_text": "{last} makes the division adjust",
         "body_text": "{name} forces the rest of the weight class to recalibrate. The pecking order has movement."},
        {"headline_text": "A name to circle on the card",
         "body_text": "{name} isn't the main event today. But the main event is paying attention."},
        {"headline_text": "{last} — the story the room is telling",
         "body_text": "{name} is the fighter the gyms are talking about this week. The whisper is getting louder."},
    ],
}

# ---- Fastest Rising (4 families + default) × 8 templates = 40 ----
_FASTEST_RISING_TEMPLATES = {
    "prodigy": [
        {"headline_text": "{name} is the division's hottest hand",
         "body_text": "The surge continues for {name}. The prospects don't want the call. The veterans are watching the tape."},
        {"headline_text": "White-hot and nobody's got the answer",
         "body_text": "{name} keeps finding the win column. The title shot is no longer a question of if, but when."},
        {"headline_text": "The hottest hand in the sport right now",
         "body_text": "{name} is scorching the earth on the way to a title shot. Opponents take notice."},
        {"headline_text": "{last} can't put a foot wrong",
         "body_text": "The run {name} is on is the kind that defines a career. The division is on notice."},
        {"headline_text": "The matchmakers can't ignore him anymore",
         "body_text": "{name} keeps delivering. The contender math keeps moving in his favor."},
        {"headline_text": "The kind of run that turns a prospect into a name",
         "body_text": "{name} is stringing together wins the way future champions do. The future is now."},
        {"headline_text": "{last} is the name on the matchmaker's desk",
         "body_text": "The surge continues for {name}. The phone keeps ringing for the next fight."},
        {"headline_text": "The division's brightest young talent, surging",
         "body_text": "{name} adds another win to the streak. The ceiling isn't in sight yet."},
    ],
    "cinderella_story": [
        {"headline_text": "{name} keeps defying the odds",
         "body_text": "The improbable rise continues for {name}. The doubters are running out of arguments."},
        {"headline_text": "Late bloomer, fast riser, real contender",
         "body_text": "{name} is the division's most unlikely hot hand. The Cinderella story has legs."},
        {"headline_text": "{last} — the rise nobody scripted",
         "body_text": "{name} keeps winning fights nobody thought he'd win. The division is recalibrating."},
        {"headline_text": "Out of nowhere, into the contender conversation",
         "body_text": "{name} is the late-blooming run the division didn't see coming. The matchmakers can't ignore it."},
        {"headline_text": "The Cinderella story picks up speed",
         "body_text": "{name} adds another chapter to the improbable rise. The title shot is no longer unthinkable."},
        {"headline_text": "{last} forces the contender math to move",
         "body_text": "{name} keeps climbing. The pecking order has movement at the top."},
        {"headline_text": "The quietest roar in the division",
         "body_text": "{name} was an afterthought. The afterthought is becoming the storyline."},
        {"headline_text": "{last} — the rise the room can't stop talking about",
         "body_text": "{name} is the name on everyone's lips. The Cinderella run keeps writing itself."},
    ],
    "veteran": [
        {"headline_text": "{name} finds a second wind",
         "body_text": "The old warhorse is surging. {name} is the veteran the division forgot to write off."},
        {"headline_text": "Late-career run, real momentum",
         "body_text": "{name} is fighting like a man ten years younger. The veteran has found another gear."},
        {"headline_text": "{last} refuses to fade quietly",
         "body_text": "The grizzled hand is on a run. {name} is making the case for one more title conversation."},
        {"headline_text": "The old soul's late surge",
         "body_text": "{name} is the veteran who won't go away. The win streak has the division recalibrating."},
        {"headline_text": "{last} — the second act no one saw coming",
         "body_text": "The late-career run is real. {name} is back in the contender conversation."},
        {"headline_text": "The division's old guard, surging",
         "body_text": "{name} keeps finding wins. The prospects studying his tape have to take notes."},
        {"headline_text": "{last} still has the magic",
         "body_text": "The veteran surge continues for {name}. The farewell tour is on hold."},
        {"headline_text": "A late chapter, written in wins",
         "body_text": "{name} adds another to the streak. The late-career run is the division's quietest good story."},
    ],
    "fallen_champion": [
        {"headline_text": "{name} claws back toward relevance",
         "body_text": "The fallen champion is on a run. {name} is climbing again — slower than the fall, but climbing."},
        {"headline_text": "{last} finds a flicker of the old form",
         "body_text": "The slide is over, for now. {name} is stringing wins together and the division notices."},
        {"headline_text": "The comeback trail opens for {last}",
         "body_text": "{name} is back in the win column. The road back to the title is long, but the first step is taken."},
        {"headline_text": "{last} — the once-king, climbing again",
         "body_text": "The fallen champion is rebuilding. {name} is on a streak and the matchmakers are watching."},
        {"headline_text": "A champion's echo, finding new life",
         "body_text": "{name} adds another win. The crown is gone, but the contender conversation isn't."},
        {"headline_text": "{last} writes the next chapter",
         "body_text": "The comeback is real. {name} keeps winning and the division has to take the call."},
        {"headline_text": "From the canvas, back into the conversation",
         "body_text": "{name} is climbing the rankings again. The fall was loud; the rise is quiet."},
        {"headline_text": "{last} won't let the story end here",
         "body_text": "The fallen champion keeps showing up. {name} is on a run and the title picture is shifting."},
    ],
    "default": [
        {"headline_text": "{name} is trending upward fast",
         "body_text": "The hottest hand in the division belongs to {name}. The surge continues — opponents take notice."},
        {"headline_text": "The wind at his back, the division taking notice",
         "body_text": "{name} is stringing together the kind of run that turns heads. The matchup math favors him."},
        {"headline_text": "{last} is rolling right now",
         "body_text": "{name} has found his rhythm at the right time. The contender math is moving."},
        {"headline_text": "Trending the way a contender should",
         "body_text": "{name} keeps climbing. The pecking order has movement at the top."},
        {"headline_text": "{last} forces the matchmakers to call",
         "body_text": "The surge continues for {name}. The next fight is going to be a bigger one."},
        {"headline_text": "A fighter who's found his rhythm",
         "body_text": "{name} is on the kind of run that defines a year. The division is recalibrating."},
        {"headline_text": "{last} is the division's quiet surge",
         "body_text": "{name} keeps winning and the whispers are getting louder. The title picture shifts."},
        {"headline_text": "The arrow's pointing up, the division feels it",
         "body_text": "{name} is the ascent the division can't ignore. The matchups are getting bigger."},
    ],
}

# ---- Biggest Fall (4 families + default) × 8 templates = 40 ----
_BIGGEST_FALL_TEMPLATES = {
    "fallen_champion": [
        {"headline_text": "{name} — the slide that won't stop",
         "body_text": "The fall continues for {name}. Once a name to fear — now a fighter searching for answers."},
        {"headline_text": "The crown is gone, the losses keep coming",
         "body_text": "{name} can't find the win column. The once-king is sliding fast and the division notices."},
        {"headline_text": "{last} searches for the version that held the belt",
         "body_text": "The fallen champion's decline has legs. {name} keeps losing, the end is in sight."},
        {"headline_text": "The throne empties, the losses stack",
         "body_text": "{name} adds another loss to the skid. The matchmakers are running out of favorable matchups."},
        {"headline_text": "{last} — the long goodbye gets longer",
         "body_text": "The slide is real for {name}. Father time is winning, and the division knows it."},
        {"headline_text": "Once the king, now the question",
         "body_text": "{name} can't buy a win these days. The crown has slipped and the throne is empty."},
        {"headline_text": "{last} keeps searching for the exit",
         "body_text": "The fallen champion keeps showing up. The losses keep stacking. The end is in sight."},
        {"headline_text": "A champion's echo, fading fast",
         "body_text": "{name} is in freefall. The version of him the division remembers is gone."},
    ],
    "veteran": [
        {"headline_text": "{name} — the old warhorse slows",
         "body_text": "The decline continues for {name}. The grizzled veteran is searching for answers."},
        {"headline_text": "Father time is winning, {last} knows it",
         "body_text": "{name} keeps losing. The farewell tour is being written, game by game."},
        {"headline_text": "{last} — the late-career slide is on",
         "body_text": "The veteran is fading. {name} can't find the version that built the reputation."},
        {"headline_text": "The division's old guard, slipping",
         "body_text": "{name} adds another loss. The prospects are no longer scared of the name."},
        {"headline_text": "{last} — the end is in sight",
         "body_text": "The slide is real. {name} is fighting to stay relevant and the losses keep coming."},
        {"headline_text": "A career finding its way to the exit",
         "body_text": "{name} is on the kind of skid that ends careers. The veteran won't go quietly, but he is going."},
        {"headline_text": "{last} keeps searching for the old form",
         "body_text": "The decline has legs. {name} is no longer the fighter the division remembers."},
        {"headline_text": "The long goodbye, picking up speed",
         "body_text": "{name} is sliding. The farewell tour is no longer hypothetical."},
    ],
    "prodigy": [
        {"headline_text": "The wunderkind hits a wall",
         "body_text": "The hype train slows for {name}. The first real rough patch of the prospect's career."},
        {"headline_text": "{last} — the can't-miss kid, missing",
         "body_text": "The slide is on for {name}. The division's brightest young talent is searching for answers."},
        {"headline_text": "The future arrives, then stalls",
         "body_text": "{name} can't find the win column. The prospect's rough patch has legs."},
        {"headline_text": "{last} learns what a skid feels like",
         "body_text": "The first real adversity for {name}. The hype has gone quiet. The matchmakers are patient."},
        {"headline_text": "The ceiling moves, the floor drops",
         "body_text": "{name} is sliding. The prospect's learning curve just got steep."},
        {"headline_text": "{last} — the prospect's cold streak",
         "body_text": "The slide continues for {name}. The division's brightest young talent needs a win."},
        {"headline_text": "A bump in the road, getting longer",
         "body_text": "{name} keeps losing. The rough patch is becoming a story."},
        {"headline_text": "{last} — the hype has gone quiet",
         "body_text": "The prospect is searching. {name} needs to find the version that turned heads."},
    ],
    "cinderella_story": [
        {"headline_text": "The Cinderella run loses a step",
         "body_text": "{name} can't find the win column. The improbable rise has hit its first real wall."},
        {"headline_text": "{last} — the underdog's cold streak",
         "body_text": "The slide is on for {name}. The Cinderella story is on hold."},
        {"headline_text": "The clock strikes on the improbable rise",
         "body_text": "{name} keeps losing. The late-bloomer story needs another chapter."},
        {"headline_text": "{last} — the run that won't extend",
         "body_text": "The Cinderella story has stalled. {name} is searching for the next win."},
        {"headline_text": "The underdog, back on the canvas",
         "body_text": "{name} adds another loss. The improbable rise is becoming the improbable stall."},
        {"headline_text": "{last} — the story pauses",
         "body_text": "The Cinderella run has hit adversity. {name} needs to find another gear."},
        {"headline_text": "The fairy tale hits a rough chapter",
         "body_text": "{name} is sliding. The underdog story is on hold, not over."},
        {"headline_text": "{last} — the rise, interrupted",
         "body_text": "The Cinderella story loses momentum. {name} is still searching for the next win."},
    ],
    "default": [
        {"headline_text": "{name} is sliding in the wrong direction",
         "body_text": "The fall continues for {name}. Once a name to fear — now a fighter searching for answers."},
        {"headline_text": "The slide is on, the camp knows it",
         "body_text": "{name} can't find the win column. The rough patch is starting to stick."},
        {"headline_text": "{last} — form has slipped, the doubters are loud",
         "body_text": "The losses are stacking into a story. {name} is searching for the version he used to be."},
        {"headline_text": "A rough patch that's getting longer",
         "body_text": "{name} adds another loss. The slide is real and the division notices."},
        {"headline_text": "{last} — searching for the version he used to be",
         "body_text": "The skid continues for {name}. The matchmakers are running out of patient matchups."},
        {"headline_text": "The kind of skid careers don't always recover from",
         "body_text": "{name} is in freefall. The spiral has started and the camp knows it."},
        {"headline_text": "{last} — one more loss from a real conversation",
         "body_text": "The slide is on for {name}. The next fight is going to define the next year."},
        {"headline_text": "The bottom has dropped out, and fast",
         "body_text": "{name} can't find the win. The fall is loud and the division is whispering."},
    ],
}

# ---- Upset of the Week (4 families + default) × 8 templates = 40 ----
# Keyed by the WINNER's narrative_family (the fighter who pulled off
# the upset). {winner}, {loser}, {result_phrase}, {upset_band} are
# the format slots.
_UPSET_OF_WEEK_TEMPLATES = {
    "prodigy": [
        {"headline_text": "{winner} announces himself at {loser}'s expense",
         "body_text": "{winner} pulled off {upset_band} this week, finishing {loser} by {result_phrase}. The prodigy is here."},
        {"headline_text": "The wunderkind shocks {loser}",
         "body_text": "{winner} stunned {loser} by {result_phrase}. The division's brightest young talent just got brighter."},
        {"headline_text": "{winner} — the can't-miss kid delivers",
         "body_text": "{winner} pulled off {upset_band}, finishing {loser} by {result_phrase}. The hype is real."},
        {"headline_text": "The future arrives, {loser} pays the price",
         "body_text": "{winner} upset {loser} by {result_phrase}. The prospect era starts now."},
        {"headline_text": "{winner} turns heads, finishes {loser}",
         "body_text": "{winner} pulled off {upset_band} — {loser} by {result_phrase}. The division takes notice."},
        {"headline_text": "The prospect makes a name off {loser}",
         "body_text": "{winner} upset {loser} by {result_phrase}. The matchup math just changed."},
        {"headline_text": "{winner} — the prospect's coming-out party",
         "body_text": "{winner} stunned {loser} by {result_phrase}. The contender conversation starts now."},
        {"headline_text": "The division's next name just arrived",
         "body_text": "{winner} pulled off {upset_band}, finishing {loser} by {result_phrase}. The future is now."},
    ],
    "cinderella_story": [
        {"headline_text": "{winner} — the underdog wins again",
         "body_text": "{winner} pulled off {upset_band}, finishing {loser} by {result_phrase}. The Cinderella story rolls on."},
        {"headline_text": "Nobody saw {winner} coming",
         "body_text": "{winner} upset {loser} by {result_phrase}. The improbable rise has another chapter."},
        {"headline_text": "{winner} — the late bloomer shocks again",
         "body_text": "{winner} stunned {loser} by {result_phrase}. The Cinderella story has legs."},
        {"headline_text": "The underdog strikes, {loser} pays",
         "body_text": "{winner} pulled off {upset_band} — {loser} by {result_phrase}. The matchup math moved."},
        {"headline_text": "{winner} — the rise nobody scripted",
         "body_text": "{winner} upset {loser} by {result_phrase}. The division's most improbable contender strikes again."},
        {"headline_text": "Out of nowhere, into the win column",
         "body_text": "{winner} pulled off {upset_band}, finishing {loser} by {result_phrase}. The Cinderella run continues."},
        {"headline_text": "{winner} — the story the room is telling",
         "body_text": "{winner} stunned {loser} by {result_phrase}. The whispers are getting louder."},
        {"headline_text": "The Cinderella story, picking up speed",
         "body_text": "{winner} upset {loser} by {result_phrase}. The title conversation is no longer unthinkable."},
    ],
    "veteran": [
        {"headline_text": "{winner} — the old warhorse still has it",
         "body_text": "{winner} pulled off {upset_band}, finishing {loser} by {result_phrase}. The veteran won't go quietly."},
        {"headline_text": "The grizzled hand strikes again",
         "body_text": "{winner} stunned {loser} by {result_phrase}. The division's old guard holds the line."},
        {"headline_text": "{winner} — the veteran schools {loser}",
         "body_text": "{winner} pulled off {upset_band} — {loser} by {result_phrase}. The old soul still has chapters."},
        {"headline_text": "Seen it all, beat {loser} anyway",
         "body_text": "{winner} upset {loser} by {result_phrase}. The veteran's experience tells."},
        {"headline_text": "{winner} — the late-career upset",
         "body_text": "{winner} pulled off {upset_band}, finishing {loser} by {result_phrase}. The farewell tour is on hold."},
        {"headline_text": "The old guard, answering the new wave",
         "body_text": "{winner} stunned {loser} by {result_phrase}. The veteran still has lessons to teach."},
        {"headline_text": "{winner} won't write the final chapter yet",
         "body_text": "{winner} pulled off {upset_band} — {loser} by {result_phrase}. The veteran's not done."},
        {"headline_text": "The second act, alive and well",
         "body_text": "{winner} upset {loser} by {result_phrase}. The late-career run picks up another win."},
    ],
    "fallen_champion": [
        {"headline_text": "{winner} — the once-king strikes back",
         "body_text": "{winner} pulled off {upset_band}, finishing {loser} by {result_phrase}. The fallen champion has a pulse."},
        {"headline_text": "The crown is gone, the pride remains",
         "body_text": "{winner} stunned {loser} by {result_phrase}. The comeback trail opens for the once-king."},
        {"headline_text": "{winner} — the fallen champion climbs",
         "body_text": "{winner} pulled off {upset_band} — {loser} by {result_phrase}. The road back starts here."},
        {"headline_text": "The once-king, back in the win column",
         "body_text": "{winner} upset {loser} by {result_phrase}. The fallen champion isn't done yet."},
        {"headline_text": "{winner} — a flicker of the old form",
         "body_text": "{winner} pulled off {upset_band}, finishing {loser} by {result_phrase}. The version the division remembers surfaces."},
        {"headline_text": "The throne is empty, the fighter is not",
         "body_text": "{winner} stunned {loser} by {result_phrase}. The fallen champion still has fights in him."},
        {"headline_text": "{winner} — the comeback has legs",
         "body_text": "{winner} pulled off {upset_band} — {loser} by {result_phrase}. The climb back to relevance starts here."},
        {"headline_text": "A champion's echo, finding new life",
         "body_text": "{winner} upset {loser} by {result_phrase}. The fallen champion has another chapter."},
    ],
    "default": [
        {"headline_text": "{winner} stuns {loser}",
         "body_text": "{winner} pulled off {upset_band} this week, finishing {loser} by {result_phrase}. The division takes notice."},
        {"headline_text": "{winner} pulls off the upset",
         "body_text": "{winner} stunned {loser} by {result_phrase} — {upset_band} that nobody saw coming."},
        {"headline_text": "{winner} — the night belongs to him",
         "body_text": "{winner} upset {loser} by {result_phrase}. {upset_band}, and the division is recalibrating."},
        {"headline_text": "{loser} sent packing by {winner}",
         "body_text": "{winner} pulled off {upset_band}, finishing {loser} by {result_phrase}. The matchup math moved."},
        {"headline_text": "{winner} — the night nobody predicted",
         "body_text": "{winner} stunned {loser} by {result_phrase}. The upset has the division talking."},
        {"headline_text": "An upset that reshuffles the card",
         "body_text": "{winner} pulled off {upset_band} — {loser} by {result_phrase}. The pecking order has movement."},
        {"headline_text": "{winner} — the win that turns a year",
         "body_text": "{winner} upset {loser} by {result_phrase}. {upset_band}, and the contender conversation shifts."},
        {"headline_text": "The kind of upset that defines a week",
         "body_text": "{winner} pulled off {upset_band}, finishing {loser} by {result_phrase}. The division is whispering."},
    ],
}

# Map headline_type → template bank for easy lookup.
_HEADLINE_TEMPLATES = {
    HEADLINE_TOP_STORY: _TOP_STORY_TEMPLATES,
    HEADLINE_FASTEST_RISING: _FASTEST_RISING_TEMPLATES,
    HEADLINE_BIGGEST_FALL: _BIGGEST_FALL_TEMPLATES,
    HEADLINE_UPSET_OF_WEEK: _UPSET_OF_WEEK_TEMPLATES,
}


# ============================================================
# MAIN ENTRY POINT — generate_daily_headlines
# ============================================================

def generate_daily_headlines(conn, current_date=None):
    """Generate 4 daily headlines from interpreted state.

    Per spec §8 + PHASE_2_PLAN §5 Task 2.6: runs at the end of the
    daily interpretation pass (after fighter_descriptors is fully
    populated by context_engine + career_phase + narrative_families +
    legacy). Writes 4 headlines to the daily_headlines table.

    Per D6: IDEMPOTENT — each headline is written with INSERT OR
    REPLACE against UNIQUE (headline_date, headline_type). Re-running
    for the same date replaces, doesn't duplicate.

    Per D8: NEVER raises — a failed headline write is caught + logged.

    Per VOICE-P2 P2-A/P2-C: subject selection rotates across sim-days
    via a deterministic hash of (current_date, headline_type). A
    fighter who already won a given headline type within the last 7
    sim-days is skipped, so the same headline can't appear 31
    consecutive days even when only one fighter qualifies.

    Args:
        conn: sqlite3.Connection.
        current_date: optional ISO date string. If None, read from
            simulation_clock (the normal case — caller is the daily
            pass).

    Returns:
        int — number of headlines written (0-4). 4 = all headlines
        generated; fewer = some were skipped (e.g., no upsets in the
        last 7 days → upset_of_week skipped).
    """
    # 1. Resolve current_date from simulation_clock if not provided.
    if current_date is None:
        try:
            row = conn.execute(
                "SELECT simulation_clock.current_date "
                "FROM simulation_clock WHERE clock_id=1"
            ).fetchone()
            current_date = row[0] if row else None
        except sqlite3.Error:
            current_date = None
    if not current_date:
        from datetime import date as _date
        current_date = _date.today().isoformat()

    written = 0

    # Each headline is a separate try/except (D8) — a single failed
    # headline must not abort the others. The engine writes what it
    # can + logs the failures.
    for headline_type, generator in (
        (HEADLINE_TOP_STORY, _generate_top_story),
        (HEADLINE_UPSET_OF_WEEK, _generate_upset_of_week),
        (HEADLINE_FASTEST_RISING, _generate_fastest_rising),
        (HEADLINE_BIGGEST_FALL, _generate_biggest_fall),
    ):
        try:
            headline = generator(conn, current_date)
            if headline is None:
                # No subject for this headline type today — skip
                # (don't write a row). This is a valid outcome per
                # D2/D3/D5 — e.g., no upsets in the last 7 days.
                continue
            _write_headline(conn, current_date, headline_type,
                            headline)
            written += 1
        except Exception as e:
            import sys
            print(f"WARNING: headline_engine {headline_type} failed: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)

    conn.commit()
    return written


# ============================================================
# HEADLINE 1 — Top Story
# ============================================================

def _generate_top_story(conn, current_date):
    """Generate the Top Story headline.

    Per D2: query fighter_descriptors for narrative_family != NULL,
    pick the most interesting (fallen_champion > prodigy > cinderella
    > veteran). The priority reflects narrative weight.

    Per VOICE-P2 P2-B: 8 templates per (top_story, family) pair — the
    template rotates day-to-day via a deterministic hash of
    (current_date, "top_story", fighter_id) so the same fighter
    getting the top-story nod produces different headline_text across
    days (eliminates the "same headline 31 consecutive days" failure
    even when only one fighter qualifies at the top priority rank).

    Per VOICE-P2 P2-A: when multiple candidates share the top priority
    rank (e.g., two fallen_champions), rotate the subject day-to-day
    via a deterministic hash of (current_date, "top_story"). When only
    one candidate exists at the top rank, that fighter gets the
    headline every day (priority order is the contract — see test K
    in test_memory_headlines.py) and template rotation provides the
    variety.

    Returns the headline dict (headline_text, body_text, fighter_id)
    or None if no fighter matches any family.
    """
    # Bulk-load all fighters with a non-NULL narrative_family. We
    # decode the canonical label from the "label||phrase" storage
    # format (D9) to apply the priority order.
    rows = conn.execute(
        """
        SELECT fd.fighter_id, fd.narrative_family,
               f.first_name, f.last_name
        FROM fighter_descriptors fd
        JOIN fighters f ON f.fighter_id = fd.fighter_id
        WHERE fd.narrative_family IS NOT NULL
          AND f.is_active = 1 AND f.is_retired = 0
        """
    ).fetchall()

    if not rows:
        # No narrative families today — skip the top story.
        return None

    # Priority order (D2): fallen_champion > prodigy > cinderella >
    # veteran. We assign a priority rank to each label + sort by
    # (rank ASC, fighter_id ASC) so the candidates are stable.
    priority = {
        "fallen_champion": 1,
        "prodigy": 2,
        "cinderella_story": 3,
        "veteran": 4,
    }

    candidates = []  # list of (rank, fighter_id, label, name)
    for fighter_id, narrative_family, first_name, last_name in rows:
        label = decode_label(narrative_family)
        rank = priority.get(label)
        if rank is None:
            continue  # unrecognized family — skip (defensive)
        name = f"{first_name} {last_name}".strip() or "The fighter"
        candidates.append((rank, fighter_id, label, name))

    if not candidates:
        return None

    # Sort by (rank, fighter_id) for a stable candidate list.
    candidates.sort(key=lambda c: (c[0], c[1]))

    # Always pick from the TOP priority rank (the contract per test K:
    # fallen_champion > prodigy > cinderella > veteran — when a
    # fallen_champion exists, top_story IS that fallen_champion). If
    # multiple candidates share the top rank, rotate via hash (P2-A).
    top_rank = candidates[0][0]
    top_rank_candidates = [c for c in candidates if c[0] == top_rank]
    if len(top_rank_candidates) == 1:
        # Only one candidate at the top rank — that's the subject.
        # Template rotation provides the headline variety.
        _rank, fighter_id, label, name = top_rank_candidates[0]
    else:
        # Multiple candidates at the top rank — rotate day-to-day
        # via hash + the no-repeat-within-7-days guard.
        fighter_id, label, name = _pick_candidate(
            conn, current_date, HEADLINE_TOP_STORY, top_rank_candidates,
        )

    # VOICE-P2 P2-D: pick the template via a deterministic hash of
    # (current_date, "top_story", fighter_id) so re-running for the
    # same date produces the SAME template (idempotent INSERT OR
    # REPLACE, no UI flicker).
    templates = _HEADLINE_TEMPLATES[HEADLINE_TOP_STORY].get(
        label, _HEADLINE_TEMPLATES[HEADLINE_TOP_STORY]["default"])
    template = _pick_template(templates, current_date,
                              HEADLINE_TOP_STORY, fighter_id)

    return _format_template(template, name=name,
                            last=name.split()[-1] if name else "the fighter",
                            fighter_id=fighter_id)


# ============================================================
# HEADLINE 2 — Upset of the Week
# ============================================================

def _generate_upset_of_week(conn, current_date):
    """Generate the Upset of the Week headline.

    Per D3: query fight_history for fights in the last 7 days where
    the winner had a LOWER rankings.rating than the loser. The
    "biggest" upset = the largest rating gap favoring the loser. If
    no fights in the last 7 days, skip.

    Per VOICE-P2 P2-A: collect the top N upsets (not just the single
    biggest), pick the day's subject via a deterministic hash. This
    rotates upsets across days when multiple qualifying fights exist.

    The rating is rendered as a voice band ("underdog" / "heavy
    underdog" / "shocking upset") per §14.
    """
    # Compute the date 7 days ago.
    try:
        today = datetime.fromisoformat(current_date).date()
    except (ValueError, TypeError):
        return None
    week_ago = today - timedelta(days=7)
    week_ago_str = week_ago.isoformat()

    # Look up fights in the last 7 days where the winner had a lower
    # rating than the loser. We join fight_history (twice — once for
    # the winner, once for the loser) to rankings to get both ratings.
    # The upset = winner.rating < loser.rating; the magnitude =
    # loser.rating - winner.rating (positive — the bigger, the bigger
    # the upset).
    rows = conn.execute(
        """
        SELECT win.fighter_id AS winner_id,
               win.opponent_id AS loser_id,
               win.event_date,
               win.result_type,
               wf.first_name AS winner_first,
               wf.last_name AS winner_last,
               lf.first_name AS loser_first,
               lf.last_name AS loser_last,
               wr.rating AS winner_rating,
               lr.rating AS loser_rating
        FROM fight_history win
        JOIN fighters wf ON wf.fighter_id = win.fighter_id
        JOIN fighters lf ON lf.fighter_id = win.opponent_id
        LEFT JOIN rankings wr ON wr.fighter_id = win.fighter_id
        LEFT JOIN rankings lr ON lr.fighter_id = win.opponent_id
        WHERE win.outcome = 'win'
          AND win.event_date > ?
          AND win.event_date <= ?
          AND wr.rating IS NOT NULL
          AND lr.rating IS NOT NULL
          AND wr.rating < lr.rating
        ORDER BY (lr.rating - wr.rating) DESC, win.fighter_id ASC
        LIMIT 12
        """,
        (week_ago_str, current_date),
    ).fetchall()

    if not rows:
        return None

    # VOICE-P2 P2-A: build a stable candidate list + hash-pick.
    candidates = []
    for (winner_id, loser_id, _event_date, result_type,
         winner_first, winner_last, loser_first, loser_last,
         winner_rating, loser_rating) in rows:
        rating_gap = (loser_rating or 0) - (winner_rating or 0)
        winner_name = (f"{winner_first} {winner_last}".strip()
                       or "The winner")
        loser_name = (f"{loser_first} {loser_last}".strip()
                      or "The loser")
        result_phrase = _result_type_phrase(result_type)
        # Voice band for the upset magnitude (D3 — no raw rating
        # numbers per §14).
        if rating_gap >= 50:
            upset_band = "a shocking upset"
        elif rating_gap >= 25:
            upset_band = "a heavy underdog"
        else:
            upset_band = "an underdog"
        candidates.append((
            winner_id, winner_name, loser_name, result_phrase, upset_band,
        ))

    # Pick a candidate via deterministic hash. Note: we use the
    # candidate index as the hash key (not fighter_id), because the
    # upset_of_week subject is the FIGHT, not the fighter.
    idx = _hash_index(current_date, HEADLINE_UPSET_OF_WEEK,
                      len(candidates))
    (winner_id, winner_name, loser_name, result_phrase,
     upset_band) = candidates[idx]

    # Look up the winner's narrative_family so we can pick a
    # family-keyed template (VOICE-P2 P2-B).
    family = _get_fighter_family(conn, winner_id)
    templates = _HEADLINE_TEMPLATES[HEADLINE_UPSET_OF_WEEK].get(
        family, _HEADLINE_TEMPLATES[HEADLINE_UPSET_OF_WEEK]["default"])
    template = _pick_template(templates, current_date,
                              HEADLINE_UPSET_OF_WEEK, winner_id)

    return _format_template(template,
                            name=winner_name,
                            last=winner_name.split()[-1],
                            winner=winner_name, loser=loser_name,
                            result_phrase=result_phrase,
                            upset_band=upset_band,
                            fighter_id=winner_id)


# ============================================================
# HEADLINE 3 — Fastest Rising
# ============================================================

def _generate_fastest_rising(conn, current_date):
    """Generate the Fastest Rising headline.

    Per D4: query fighter_descriptors for momentum='very_high' AND
    career_phase='prospect' (the canonical prodigy criteria). If
    none match, fall back to momentum='high' AND career_phase=
    'prospect'. If still none, fall back to momentum='very_high'
    (any fighter on a 5+ win streak).

    Per VOICE-P2 P2-A: rotate subject day-to-day via a deterministic
    hash of (current_date, "fastest_rising").
    """
    # Fallback chain (D4). Each query uses the bulk-load pattern
    # (single SELECT) — we collect up to 12 candidates per chain
    # link, then hash-pick across whatever the first non-empty link
    # returned.
    for momentum_filter, career_filter in (
        ("very_high", "prospect"),
        ("high", "prospect"),
        ("very_high", None),  # any career_phase
    ):
        candidates = _find_fighters_by_labels(
            conn, momentum_filter, career_filter, limit=12)
        if candidates:
            fighter_id, first_name, last_name, family = _pick_candidate(
                conn, current_date, HEADLINE_FASTEST_RISING, candidates,
            )
            name = (f"{first_name} {last_name}".strip()
                    or "The fighter")
            templates = _HEADLINE_TEMPLATES[HEADLINE_FASTEST_RISING].get(
                family,
                _HEADLINE_TEMPLATES[HEADLINE_FASTEST_RISING]["default"])
            template = _pick_template(
                templates, current_date, HEADLINE_FASTEST_RISING, fighter_id)
            return _format_template(
                template, name=name, last=last_name or name,
                fighter_id=fighter_id)
    return None


# ============================================================
# HEADLINE 4 — Biggest Fall
# ============================================================

def _generate_biggest_fall(conn, current_date):
    """Generate the Biggest Fall headline.

    Per D5: query fighter_descriptors for momentum='collapsing' (3+
    loss streak). If none match, fall back to momentum='falling' (2
    loss streak). If still none, skip the headline.

    Per VOICE-P2 P2-A: rotate subject day-to-day via a deterministic
    hash of (current_date, "biggest_fall").
    """
    for momentum_filter in ("collapsing", "falling"):
        candidates = _find_fighters_by_labels(
            conn, momentum_filter, None, limit=12)
        if candidates:
            fighter_id, first_name, last_name, family = _pick_candidate(
                conn, current_date, HEADLINE_BIGGEST_FALL, candidates,
            )
            name = (f"{first_name} {last_name}".strip()
                    or "The fighter")
            templates = _HEADLINE_TEMPLATES[HEADLINE_BIGGEST_FALL].get(
                family,
                _HEADLINE_TEMPLATES[HEADLINE_BIGGEST_FALL]["default"])
            template = _pick_template(
                templates, current_date, HEADLINE_BIGGEST_FALL, fighter_id)
            return _format_template(
                template, name=name, last=last_name or name,
                fighter_id=fighter_id)
    return None


# ============================================================
# VOICE-P2 P2-A: SUBJECT ROTATION HELPERS
# ============================================================

def _hash_index(current_date, headline_type, n):
    """Deterministic hash of (current_date, headline_type) → index in [0, n).

    Used by _pick_candidate to rotate the headline subject day-to-day
    without flickering (same date → same pick; different date →
    different pick). Uses MD5 for hash stability across Python
    processes (Python's built-in hash() is randomized per-process).

    Args:
        current_date: ISO date string (e.g., "2026-08-19").
        headline_type: one of HEADLINE_* constants.
        n: the number of candidates (n >= 1).

    Returns:
        int in [0, n). 0 if n <= 1.
    """
    if n <= 1:
        return 0
    key = f"{current_date}|{headline_type}"
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    return int(h, 16) % n


def _pick_template(templates, current_date, headline_type, fighter_id):
    """Deterministic hash of (current_date, headline_type, fighter_id) →
    template index.

    Same fighter + same date → same template (idempotent INSERT OR
    REPLACE — re-running for the same date produces the SAME row,
    no UI flicker). Different fighter or different date → different
    template (variety).

    Args:
        templates: list of template dicts (≥8 per Claude §3).
        current_date: ISO date string.
        headline_type: one of HEADLINE_* constants.
        fighter_id: int — the featured fighter's ID.

    Returns:
        A template dict with keys 'headline_text' + 'body_text'.
    """
    n = len(templates)
    if n <= 1:
        return templates[0]
    key = f"{current_date}|{headline_type}|{fighter_id}"
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    return templates[int(h, 16) % n]


def _pick_candidate(conn, current_date, headline_type, candidates):
    """Pick a candidate from the list, rotating day-to-day.

    VOICE-P2 P2-A + P2-C: the candidate is selected via a deterministic
    hash of (current_date, headline_type). The hash rotates the subject
    day-to-day. P2-C adds a no-repeat-within-7-days guard: if the
    hash-selected candidate already won this headline type within the
    last 7 sim-days, the engine moves to the next candidate in the
    list. This prevents the same fighter winning 31 consecutive days
    even when only one fighter dominates the candidate pool — the
    engine simply defers to the next day's hash, which picks a
    different fighter.

    Args:
        conn: sqlite3.Connection (used for the no-repeat guard query).
        current_date: ISO date string.
        headline_type: one of HEADLINE_* constants.
        candidates: list of (rank, fighter_id, label, name) tuples
            (top_story) OR (fighter_id, first_name, last_name, family)
            tuples (fastest_rising/biggest_fall). The signature is
            flexible — the candidate's fighter_id is always at index 0
            or 1 depending on the call site. We unpack defensively.

    Returns:
        Tuple matching the candidate's structure (caller knows the
        shape — top_story returns (fighter_id, label, name); the
        rising/fall generators return (fighter_id, first, last, family)).
    """
    n = len(candidates)
    if n == 0:
        return None
    # VOICE-P2 P2-C: build the set of fighter_ids who already won
    # this headline type within the last 7 sim-days. Skip them when
    # picking today's subject.
    recent_winner_ids = _recent_headline_fighter_ids(
        conn, headline_type, current_date, days=7)

    # The hash gives us a starting index; iterate from there and
    # return the first candidate whose fighter_id isn't in the
    # recent-winner set. If ALL candidates are recent winners (rare
    # — only happens when the candidate pool is smaller than 7),
    # fall back to the hash-selected one (better to repeat than to
    # skip the headline entirely).
    start_idx = _hash_index(current_date, headline_type, n)
    # Identify the fighter_id field in the candidate tuple. Top-story
    # candidates are (rank:int, fighter_id:int, label:str, name:str);
    # rising/fall candidates are (fighter_id:int, first:str, last:str,
    # family:str|None). The distinguishing rule: top-story has BOTH
    # cand[0] AND cand[1] as ints; rising/fall has cand[0] int + cand[1]
    # str.
    def _fighter_id_of(cand):
        if len(cand) >= 2 and isinstance(cand[0], int) and isinstance(cand[1], int):
            # Top-story tuple: (rank, fighter_id, label, name)
            return cand[1]
        # Rising/fall tuple: (fighter_id, first, last, family)
        return cand[0]

    for offset in range(n):
        idx = (start_idx + offset) % n
        cand = candidates[idx]
        if _fighter_id_of(cand) not in recent_winner_ids:
            return _unpack_candidate(cand)
    # All candidates are recent winners — fall back to hash-selected.
    return _unpack_candidate(candidates[start_idx])


def _unpack_candidate(cand):
    """Unpack a candidate tuple into the call-site's expected shape.

    Top-story candidates are (rank, fighter_id, label, name) — caller
    wants (fighter_id, label, name).

    Rising/fall candidates are (fighter_id, first_name, last_name,
    family) — caller wants (fighter_id, first_name, last_name, family)
    (unchanged).

    This helper inspects the tuple shape + returns the right unpacking.
    """
    if len(cand) >= 2 and isinstance(cand[0], int) and isinstance(cand[1], int):
        # Top-story tuple: (rank:int, fighter_id:int, label:str, name:str)
        rank, fighter_id, label, name = cand
        return (fighter_id, label, name)
    # Rising/fall tuple: (fighter_id:int, first:str, last:str, family:str|None)
    return cand


def _recent_headline_fighter_ids(conn, headline_type, current_date,
                                 days=7):
    """Return the set of fighter_ids who won the given headline type
    within the last `days` sim-days (inclusive of `current_date` -
    days, exclusive of `current_date`).

    VOICE-P2 P2-C: used by _pick_candidate to skip fighters who
    already won this headline type this week, eliminating the
    "same headline 31 consecutive days" failure.
    """
    try:
        today = datetime.fromisoformat(current_date).date()
    except (ValueError, TypeError):
        return set()
    cutoff = (today - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT fighter_id FROM daily_headlines "
        "WHERE headline_type = ? "
        "  AND headline_date >= ? "
        "  AND headline_date < ? "
        "  AND fighter_id IS NOT NULL",
        (headline_type, cutoff, current_date),
    ).fetchall()
    return {r[0] for r in rows}


# ============================================================
# HELPER — find candidates by decoded momentum + career_phase labels
# ============================================================

def _find_fighters_by_labels(conn, momentum_label, career_phase_label,
                             limit=12):
    """Find active fighters matching the given decoded momentum +
    career_phase labels. Returns up to `limit` candidates ordered
    by fighter_id ASC (stable across daily passes — no UI flicker).

    Per D9: the fighter_descriptors columns store "label||voice phrase"
    — we filter on the LABEL (before the "||"), not the phrase.
    SQLite's SUBSTR + INSTR does the parsing inline:

        SUBSTR(momentum, 1, INSTR(momentum || '||', '||') - 1)

    VOICE-P2 P2-A: returns a LIST of candidates (not just one) so
    the picker can rotate day-to-day.

    Args:
        conn: sqlite3.Connection.
        momentum_label: canonical momentum label (e.g. "very_high").
        career_phase_label: canonical career_phase label, or None to
            skip the career_phase filter.
        limit: max candidates to return (default 12).

    Returns:
        List of (fighter_id, first_name, last_name, narrative_family)
        tuples, where narrative_family is the decoded label (or None).
        Empty list if no matches.
    """
    sql = """
        SELECT fd.fighter_id, f.first_name, f.last_name, fd.narrative_family
        FROM fighter_descriptors fd
        JOIN fighters f ON f.fighter_id = fd.fighter_id
        WHERE f.is_active = 1 AND f.is_retired = 0
          AND SUBSTR(fd.momentum, 1,
                     INSTR(fd.momentum || '||', '||') - 1) = ?
    """
    params = [momentum_label]
    if career_phase_label is not None:
        sql += ("  AND SUBSTR(fd.career_phase, 1, "
                "INSTR(fd.career_phase || '||', '||') - 1) = ?\n")
        params.append(career_phase_label)
    sql += "        ORDER BY fd.fighter_id ASC LIMIT ?\n"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [(fid, fn, ln, decode_label(nf)) for (fid, fn, ln, nf) in rows]


def _get_fighter_family(conn, fighter_id):
    """Look up a fighter's decoded narrative_family label (or None)."""
    row = conn.execute(
        "SELECT narrative_family FROM fighter_descriptors "
        "WHERE fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    if not row or not row[0]:
        return None
    return decode_label(row[0])


# ============================================================
# HELPER — voice phrase for fight_history.result_type
# ============================================================
# Reused by the Upset of the Week headline. Same translation as the
# memory_engine uses (kept here as a local copy so this module is
# self-contained — no risk of a future refactor to memory_engine
# silently breaking headline generation).

_RESULT_TYPE_PHRASES = {
    "unanimous_decision": "unanimous decision",
    "split_decision": "split decision",
    "ko_tko": "knockout",
    "submission": "submission",
    "doctor_stoppage": "doctor stoppage",
    "dq": "disqualification",
    "draw": "draw",
}


def _result_type_phrase(result_type):
    """Render a fight_history.result_type as a voice phrase (§14)."""
    if not result_type:
        return "a finish"
    return _RESULT_TYPE_PHRASES.get(result_type, "a finish")


# ============================================================
# HELPER — format a template dict with the call-site's slots
# ============================================================

def _format_template(template, fighter_id=None, **slots):
    """Apply str.format to a template's headline_text + body_text.

    Per D7: the template's slots are filled from the call-site's
    keyword arguments (e.g., name=, last=, winner=, loser=,
    result_phrase=, upset_band=). Missing slots would raise
    KeyError — we let it propagate so the engine's try/except logs
    the failure (D8) and moves to the next headline.

    Args:
        template: dict with keys 'headline_text' + 'body_text'.
        fighter_id: optional int — included in the returned dict.
        **slots: format-string slot values.

    Returns:
        dict with keys 'headline_text', 'body_text', 'fighter_id'.
    """
    return {
        "headline_text": template["headline_text"].format(**slots),
        "body_text": template["body_text"].format(**slots),
        "fighter_id": fighter_id,
    }


# ============================================================
# HELPER — write a headline row (INSERT OR REPLACE for idempotency)
# ============================================================

def _write_headline(conn, current_date, headline_type, headline):
    """Write a single headline row to daily_headlines.

    Per D6: uses INSERT OR REPLACE against UNIQUE (headline_date,
    headline_type) for idempotency. Re-running for the same date
    overwrites the row — doesn't duplicate.

    Args:
        conn: sqlite3.Connection.
        current_date: ISO date string.
        headline_type: one of HEADLINE_*.
        headline: dict with keys 'headline_text', 'body_text',
            'fighter_id'.
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_headlines
            (headline_date, headline_type, headline_text,
             body_text, fighter_id, snapshot_version, created_at)
        VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
        """,
        (current_date, headline_type,
         headline["headline_text"],
         headline.get("body_text"),
         headline.get("fighter_id")),
    )
