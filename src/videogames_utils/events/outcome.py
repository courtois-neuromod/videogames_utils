"""How a repetition ended, decided from the game engine rather than from heuristics.

One implementation for all four datasets, replacing four divergent copies of
``_determine_outcome`` in ``code/replays/generate_replays.py``. The label vocabulary is
unchanged, so existing consumers of ``_summary.json`` keep working:

    cleared
    failed/killed, failed/fall, failed/timeout
    incomplete/warp, incomplete/interrupted
    unknown

What changes is how the labels are decided.

**mario / mariostars.** The shipped logic tested ``jump_airborne == 3``. That value is
Player_State $001D, which is the flagpole slide *and* the vine climb, so a W4-2 warp
taken up the vine was labelled ``cleared``. It also never fires on castle levels, where
the level ends at an axe rather than a flagpole. Both are replaced by the engine's own
``PlayerEndLevel`` routine (``GameEngineSubroutine`` == 5), which fires on every kind of
level ending and on nothing else.

**mario3.** The shipped logic inferred death from a timer freeze plus the player's X
position, and fell through to ``failed/killed`` as a catch-all -- which is why 91% of
mario3 repetitions carry that label. ``Player_IsDying`` ($00F1) states the cause outright.

**shinobi.** Unchanged in substance: with no RAM map there is still no signal beyond
"did the player lose a life", which is what the shipped code used.
"""

from __future__ import annotations

from typing import Optional, Sequence

#: GameEngineSubroutine / player_action_state values (shared by SMB1 on NES and SNES).
ENGINE_FLAGPOLE_SLIDE = 4
ENGINE_END_LEVEL = 5
ENGINE_LOSE_LIFE = 6
ENGINE_DEATH = 11

#: Player_IsDying values in SMB3.
SMB3_DEATH_CAUSE = {1: "failed/killed", 2: "failed/fall", 3: "failed/timeout"}


def _first_transition(series: Sequence, value) -> Optional[int]:
    for index in range(1, len(series)):
        if series[index] == value and series[index - 1] != value:
            return index
    return None


def _changed(series) -> bool:
    return bool(series) and len(series) > 1 and any(
        series[i] != series[i - 1] for i in range(1, len(series)))


def _last_change(series) -> Optional[int]:
    """Frame of the last change in a series, or None."""
    for index in range(len(series) - 1, 0, -1):
        if series[index] != series[index - 1]:
            return index
    return None


def smb1_outcome(repvars: dict, engine_var: str = "player_state",
                 timer_var: str = "time") -> str:
    """Outcome for Super Mario Bros, on either port.

    The label describes how the repetition *ended*, so the three possible terminal
    events -- reaching the end of the level, warping out, and dying -- are all located
    and the **latest** one wins. Ordering them by time rather than by precedence matters
    in both directions:

    * a player can climb a vine (which the shipped logic mistook for a flagpole slide)
      and then lose their last life, which is a failure, not a clear;
    * a player can lose a life early and then take the W4-2 warp pipe, which is a warp
      exit, not a death.

    Each death is attributed by looking at the engine between the previous death and this
    one: if the death routine (``GameEngineSubroutine`` == 11) ran, the player was killed
    by something; if the engine went straight to losing a life (== 6) without it, the
    player dropped off the bottom of the screen.

    Args:
        engine_var: ``player_state`` on the NES, ``player_action_state`` on the SNES.
            Both hold the same GameEngineSubroutine enumeration.
    """
    try:
        engine = repvars.get(engine_var) or []
        lives = repvars["lives"]
        n = len(engine)

        # --- candidate terminal events, each with the frame it happened on ------------

        # The engine's own end-of-level routine. Fires on flagpole and castle levels
        # alike, unlike the flagpole-slide test, which also fires on a vine climb.
        end_frame = _first_transition(engine, ENGINE_END_LEVEL)

        # A warp-zone exit moves the player to another world or area.
        world = repvars.get("world") or repvars.get("current_world") or []
        area = repvars.get("area") or repvars.get("current_level") or []
        warp_frame = max(
            (f for f in (_last_change(world), _last_change(area)) if f is not None),
            default=None)

        deaths = [i for i in range(1, len(lives)) if lives[i] < lives[i - 1]]
        if not deaths:
            deaths = [i for i in range(1, n)
                      if engine[i] == ENGINE_LOSE_LIFE and engine[i - 1] != ENGINE_LOSE_LIFE]
        death_frame = deaths[-1] if deaths else None

        # --- decide -----------------------------------------------------------------
        # Completing a level also advances the world index, so a world change is only a
        # warp when the level never ended: `end_frame` takes precedence over it. Among
        # the remaining two, order matters -- a player can lose a life early and then
        # take the W4-2 warp pipe, which is a warp exit rather than a death.
        if end_frame is not None:
            return "cleared"

        if warp_frame is not None and (death_frame is None or warp_frame > death_frame):
            return "incomplete/warp"

        if death_frame is None:
            return "incomplete/interrupted"
        frame = death_frame

        # A death: attribute it from the engine between the previous death and this one.
        previous = deaths[-2] if len(deaths) > 1 else -1
        span = engine[previous + 1:frame + 1]
        routine_frame = None
        for offset, value in enumerate(span):
            if value == ENGINE_DEATH:
                routine_frame = previous + 1 + offset
                break
        if routine_frame is None:
            return "failed/fall"

        timer = repvars.get(timer_var) or []
        if timer:
            window = timer[max(0, routine_frame - 120):routine_frame + 1]
            if window and all(t == 0 for t in window):
                return "failed/timeout"
        return "failed/killed"
    except (KeyError, IndexError, TypeError):
        return "unknown"


def smb3_outcome(repvars: dict) -> str:
    """Outcome for Super Mario Bros 3.

    Clearing is a goal card entering the inventory; the cause of failure comes straight
    from ``Player_IsDying``. Falls back to the previous goal-card-only logic when the new
    variable is absent, so it still works on sidecars generated before the RAM addresses
    were added.
    """
    try:
        for card_var in ("goal_cards_p1_1", "goal_cards_p1_2", "goal_cards_p1_3"):
            cards = repvars.get(card_var) or []
            if len(cards) > 1 and any(cards[i] > cards[i - 1] for i in range(1, len(cards))):
                return "cleared"

        dying = repvars.get("player_is_dying")
        if dying:
            for value in dying:
                if value in SMB3_DEATH_CAUSE:
                    return SMB3_DEATH_CAUSE[value]
            return "incomplete/interrupted"

        # Legacy path: no Player_IsDying available.
        time_series = repvars.get("time") or []
        all_zero = all(
            (repvars.get(name) or [1])[-1] == 0
            for name in ("timer_100", "timer_10", "timer_1"))
        if (time_series and time_series[-1] == 0) or all_zero:
            return "failed/timeout"
        x_low = repvars.get("player_x_level_low") or []
        if x_low[-100:] and all(v == 0 for v in x_low[-100:]):
            return "failed/fall"
        return "failed/killed"
    except (KeyError, IndexError, TypeError):
        return "unknown"


def shinobi_outcome(repvars: dict) -> str:
    """Outcome for Shinobi III.

    Unchanged from the shipped behaviour: with no RAM map for this game the only
    available signal is whether a life was lost. Note this makes ``cleared`` a statement
    about survival, not about reaching the end of the stage.
    """
    try:
        lives = repvars["lives"]
        lost = any(lives[i] < lives[i - 1] for i in range(1, len(lives)))
        return "failed" if lost else "cleared"
    except (KeyError, IndexError, TypeError):
        return "unknown"


#: task -> callable, for callers that only know the BIDS task label.
BY_TASK = {
    "mario": lambda v: smb1_outcome(v, "player_state", "time"),
    "mariostars": lambda v: smb1_outcome(v, "player_action_state", "time_units"),
    "mario3": smb3_outcome,
    "shinobi": shinobi_outcome,
}


def determine(repvars: dict, task: str) -> str:
    """Outcome for one repetition of ``task``."""
    return BY_TASK[task](repvars)
