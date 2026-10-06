"""Event generator for Shinobi III: Return of the Ninja Master (``shinobi``).

Shinobi is the weakest of the four datasets and this module is deliberately conservative
about it. There is **no public RAM map** for Shinobi III (searched romhacking.net, TCRF
and SMW Central), and the integration's ``data.json`` was built by hand: roughly half its
entries are background/palette scratch (``backTree``, ``backbrush``, ...) with no
gameplay meaning.

What that costs, explicitly:

* ``EnemyDefeated`` is inferred from score increments and is **untyped**. Only the
  documented enemy values are counted; see :data:`KILL_SCORE_VALUES`.
* There are no ``Enemy_appeared`` / ``Enemy_disappeared`` / ``Enemy_counter`` events,
  because nothing in the current RAM map locates enemy objects.
* ``PlayerDied`` distinguishes only ``Enemy`` and ``Fall``, the two death states of the
  player's animation byte; see :data:`DEATH_CAUSES`.
* ``LevelCompleted`` is read from the end-of-level fade that closes the recording, so
  it is missed in the few cleared repetitions whose recording stopped before the fade.
  See :func:`_screen_labels`.

Everything this module does emit is derived from a counter whose meaning is unambiguous
(``lives``, ``health``, ``shurikens``), so those events are as solid as the Mario ones.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .. import screens
from ..emit import EventAccumulator, TASK_FRAME_RATES
from ..spans import clip, constant_runs, nonzero_runs

TASK = "shinobi"

#: Score increments that correspond to defeating an enemy, from the value table in the
#: shipped generator's own docstring:
#:   200 basic enemies (all levels)
#:   300 mortars and machineguns (level 5)
#:   400 cauldron-heads (level 1)
#:   500 anti-riot cop (level 5), hovering ninja (level 4)
#: The shipped code only counted 200 and 300, silently dropping the 400 and 500 kills its
#: own docstring documents (verified: one sampled repetition contains 7 uncounted
#: 500-point kills).
#:
#: Other increments do occur -- 1000 is common, and 250/350/700/3000/5000 appear -- but
#: nothing in the available RAM map attributes them, so they are deliberately NOT counted
#: as kills rather than guessed at. Roughly a third of scoring events are therefore not
#: represented; this is stated in the dataset README.
KILL_SCORE_VALUES = frozenset({200, 300, 400, 500})

#: Values of the (misnamed) ``blackScreen`` variable at $FF0024. It is a screen-mode
#: byte, non-zero whenever the game rather than the player drives the screen. Read off
#: rendered frames and the full corpus (666 replays):
#:
#:   40  scroll lock while an enemy wave attacks -- ordinary gameplay, the screen is NOT
#:       black; 105-231 frames, ~3 per level at fixed positions
#:   22 / 62 then 20  a section transition: fade out (27 frames), fade in (41-58 frames)
#:   20  from the frame health reaches 0: the death animation (127-344 frames), followed
#:       by 21 on the frame the life is lost, then 21 + 20 (~85 frames) fading back in at
#:       the checkpoint
#:   21  with lives negative: the GAME OVER / CONTINUE screen, until the recording stops
#:   22 / 62 running to the end of the recording: the level was completed -- the fade
#:       into the ROUND CLEAR bonus tally (level 1, ~380 frames of it recorded) or the
#:       15-16 frames of fade before the recording stops (levels 4 and 5)
SCREEN_SCROLL_LOCK = 40
SCREEN_LEVEL_END_VALUES = (22, 62)

#: Values the player's animation state (``status``, $FF415A) takes for the death
#: sequence, and the cause each one means. ``status`` switches to one of them on the very
#: frame ``health`` reaches 0 and holds it until the life is lost, and it takes neither
#: value at any other time. Over the corpus (666 replays, 144 deaths), confirmed on the
#: rendered frames:
#:
#:   41  health drained by enemy hits: the player collapses in the play area (97-208 px
#:       from the top of the screen), 1-3 health left before the last hit. 18 deaths.
#:   43  fell into a pit or into water: the player is at the bottom edge of the screen
#:       (369-381 px) and the health bar is wiped in one frame, usually from full. 126
#:       deaths.
#:
#: No other death occurs in levels 1, 4 and 5, and the game has no level timer.
DEATH_CAUSES = {41: "Enemy", 43: "Fall"}

#: Genesis controller mapping for Shinobi III. B attacks, C jumps, A casts ninjutsu --
#: the same assignment the shipped generator uses.
BUTTON_ACTIONS = {
    "LEFT": "Action/Left", "RIGHT": "Action/Right", "UP": "Action/Up",
    "DOWN": "Action/Down", "B": "Action/Attack", "C": "Action/Jump",
    "A": "Action/Ninjutsu", "START": "Action/Start", "MODE": "Action/Select",
    "X": "Action/Other", "Y": "Action/Other", "Z": "Action/Other",
}


def _transitions(series, predicate) -> List[int]:
    out, prev = [], False
    for frame, value in enumerate(series):
        now = bool(predicate(value))
        if now and not prev:
            out.append(frame)
        prev = now
    return out


def generate(repvars: dict, level=None, outcome: Optional[str] = None, **defaults):
    """Build the events DataFrame for one Shinobi repetition."""
    fs = TASK_FRAME_RATES[TASK]
    n = len(repvars["health"])
    acc = EventAccumulator(level if level is not None else repvars.get("level"), fs,
                           **defaults)

    def col(name):
        return repvars.get(name, [0] * n)

    _actions(acc, repvars)
    _level_events(acc, n)
    deaths = _deaths(col, n)
    _player_events(acc, col, n, deaths)
    labels = _screen_labels(col, n, deaths)
    screens.emit(acc, labels)
    for start, stop, label in constant_runs(labels):
        if label == screens.LEVEL_END:
            acc.add("LevelCompleted", start)
            break
    # Shinobi's single form: one row per stretch of frames on which the player is alive.
    for start, stop, _ in constant_runs([0] * n, keep=screens.alive_mask(labels)):
        acc.add("PlayerState/Normal", start, stop)
    _combat_events(acc, col, n)
    return acc.to_frame()


def _actions(acc: EventAccumulator, repvars: dict) -> None:
    for button, trial_type in BUTTON_ACTIONS.items():
        series = repvars.get(button)
        if not series:
            continue
        held, start = False, 0
        for frame, value in enumerate(series):
            if value and not held:
                held, start = True, frame
            elif not value and held:
                acc.add(trial_type, start, frame - 1, button=button)
                held = False
        if held:
            acc.add(trial_type, start, len(series) - 1, button=button)


def _deaths(col, n: int) -> List[Tuple[int, int, str]]:
    """``(onset, stop, cause)`` for each death; see :data:`DEATH_CAUSES`.

    ``onset`` is the frame ``status`` enters a death state, which is the frame health
    reaches 0. ``stop`` is the frame the life is lost -- ``lives`` only drops once the
    death animation and fade have played, 2-6 s later -- or the last frame when the
    recording stops before that (4 deaths in the corpus, all falls), which a death keyed
    on ``lives`` alone would miss.
    """
    status = col("status")
    lives = col("lives")
    out = []
    for onset in _transitions(status, lambda v: v in DEATH_CAUSES):
        stop = next((f for f in range(onset + 1, n) if lives[f] < lives[f - 1]), n - 1)
        out.append((onset, stop, DEATH_CAUSES[status[onset]]))
    return out


def _screen_labels(col, n: int, deaths: List[Tuple[int, int, str]]) -> List[str]:
    """One screen label per frame; see :mod:`..screens` and :data:`SCREEN_SCROLL_LOCK`.

    Every non-zero stretch of ``blackScreen`` other than the scroll lock is a stretch the
    player does not control, Transition by default. Inside it: from the frame health
    reached zero to the frame the life is lost (or the recording stops) is the death
    sequence; the frames on which
    ``lives`` is negative are the GAME OVER screen; and a fade of value 22 or 62 that runs
    to the end of the recording is the end of a completed level.
    """
    mode = col("blackScreen")
    lives = col("lives")
    labels = [screens.GAMEPLAY] * n
    for start, stop, value in constant_runs([bool(v) and v != SCREEN_SCROLL_LOCK
                                             for v in mode]):
        if value:
            screens.fill(labels, start, stop, screens.TRANSITION)

    for onset, stop, _ in deaths:
        screens.fill(labels, onset, stop, screens.DEATH)
    for frame in range(n):
        if lives[frame] < 0 and labels[frame] == screens.TRANSITION:
            labels[frame] = screens.GAME_OVER

    runs = constant_runs(labels)
    if runs and runs[-1][2] == screens.TRANSITION and mode[runs[-1][0]] in SCREEN_LEVEL_END_VALUES:
        screens.fill(labels, runs[-1][0], runs[-1][1], screens.LEVEL_END)
    return labels


def _player_events(acc: EventAccumulator, col, n: int,
                   deaths: List[Tuple[int, int, str]]) -> None:
    """PlayerDamaged, HealthGained, PlayerDied/*, LifeGained, PlayerState/HitRecovery."""
    health = col("health")
    lives = col("lives")

    damaged = []
    for frame in range(1, n):
        delta = health[frame] - health[frame - 1]
        if delta < 0:
            # The drop to 0 that starts a death is the death, not a separate hit. (An
            # earlier release suppressed drops within 180 frames before the life loss,
            # which misses most falls, whose sequence runs ~350 frames: 118 of 140
            # deaths also carried a PlayerDamaged.)
            if any(onset <= frame <= stop for onset, stop, _ in deaths):
                continue
            acc.add("PlayerDamaged", frame)
            damaged.append(frame)
        elif delta > 0:
            acc.add("HealthGained", frame)

    # Post-hit recovery. `hit_timer` (added in this release, see ram.SHINOBI_CANDIDATES)
    # is set to 80 or 64 on the frame health drops and counts down once per frame while
    # the player flashes. The same byte also runs from 48 after knock-backs that cost no
    # health and idles at 1 for ~25 frames at other moments, so only stretches that begin
    # on a PlayerDamaged are used. A stretch is cut where health reaches 0, since the
    # counter keeps running through the death animation.
    hit_timer = col("hit_timer")
    for start, stop, _ in nonzero_runs(hit_timer, split_on_value_change=False):
        if not any(abs(start - f) <= 3 for f in damaged):
            continue
        zero = [f for f in range(start, stop + 1) if health[f] == 0]
        acc.add("PlayerState/HitRecovery", start, clip(start, stop, zero[:1]))

    # The shipped pipeline has no player-death event at all. The cause comes from the
    # death state `status` enters (see DEATH_CAUSES). As in the Mario games, an enemy
    # death is a point event (the sequence that follows is the Screen/Death row) and a
    # fall runs from the frame the player hits the bottom of the screen to the life loss.
    for onset, stop, cause in deaths:
        acc.add(f"PlayerDied/{cause}", onset, stop if cause == "Fall" else None)

    for frame in range(1, n):
        if lives[frame] > lives[frame - 1]:
            acc.add("LifeGained", frame)


def _combat_events(acc: EventAccumulator, col, n: int) -> None:
    """EnemyDefeated, ProjectileAppeared/Shuriken, ItemCollected/Shurikens."""
    score = col("instantScore")
    for frame in range(1, n):
        if score[frame] - score[frame - 1] in KILL_SCORE_VALUES:
            acc.add("EnemyDefeated", frame)

    shurikens = col("shurikens")
    for frame in range(1, n):
        delta = shurikens[frame] - shurikens[frame - 1]
        if delta == -1:
            acc.add("ProjectileAppeared/Shuriken", frame)
        elif delta > 0:
            # The amount picked up is not carried on the row; it is recoverable from
            # `shurikens` in the repetition's _variables.json.
            acc.add("ItemCollected/Shurikens", frame)

    # Ninjutsu consumes several shurikens at once and decrements the magic counter.
    ninjutsu = col("ninjitsu")
    kind = col("typeOfNinjitsu")
    for frame in range(1, n):
        if ninjutsu[frame] < ninjutsu[frame - 1]:
            acc.add(f"WeaponPowerupStarted/Ninjutsu{kind[frame] or ''}", frame)


def _level_events(acc: EventAccumulator, n: int) -> None:
    """LevelStarted. ``LevelCompleted`` is emitted from the screen labels in
    :func:`generate`, at the start of the end-of-level fade.

    The shipped generator fabricated ``LevelCompleted`` five seconds before the end of
    any repetition in which no life was lost -- a property of the whole repetition dressed
    up as a timed event -- and an earlier release of this module dropped it, having found
    that ``blackScreen`` is set in every repetition. It is: the value 40 is the scroll lock
    of an enemy wave. But its *trailing* value discriminates perfectly over the corpus: a
    fade of 22 or 62 running to the end of the recording occurs in 519 of 532 cleared
    repetitions and in none of the 134 failed ones (which end in the death value 21 or in
    play). The 13 misses are cleared repetitions whose recording stopped before the fade.
    """
    acc.add("LevelStarted", 0)
