"""Event generator for Shinobi III: Return of the Ninja Master (``shinobi``).

Shinobi is the weakest of the four datasets and this module is deliberately conservative
about it. There is **no public RAM map** for Shinobi III (searched romhacking.net, TCRF
and SMW Central), and the integration's ``data.json`` was built by hand: roughly half its
entries are background/palette scratch (``backTree``, ``backbrush``, ...) with no
gameplay meaning.

What that costs, explicitly:

* ``Enemy_defeated`` is inferred from score increments and is **untyped**. Only the
  documented enemy values are counted; see :data:`KILL_SCORE_VALUES`.
* There are no ``Enemy_appeared`` / ``Enemy_disappeared`` / ``Enemy_counter`` events,
  because nothing in the current RAM map locates enemy objects.
* ``Level_completed`` is read from the end-of-level fade that closes the recording, so
  it is missed in the few cleared repetitions whose recording stopped before the fade.
  See :func:`_screen_labels`.

Everything this module does emit is derived from a counter whose meaning is unambiguous
(``lives``, ``health``, ``shurikens``), so those events are as solid as the Mario ones.
"""

from __future__ import annotations

from typing import List, Optional

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

#: Frames to search back from a life loss for the moment health reached zero.
DEATH_SEARCH_FRAMES = 400

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
    death_frames = _player_events(acc, col, n)
    labels = _screen_labels(col, n, death_frames)
    screens.emit(acc, labels)
    for start, stop, label in constant_runs(labels):
        if label == screens.LEVEL_END:
            acc.add("Level_completed", start)
            break
    # Shinobi's single form: one row per stretch of frames on which the player is alive.
    for start, stop, _ in constant_runs([0] * n, keep=screens.alive_mask(labels)):
        acc.add("Player_state/Normal", start, stop)
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


def _death_onset(health, frame: int) -> int:
    """The frame health reached zero before the life loss at ``frame``."""
    onset = frame
    while onset > 0 and health[onset - 1] == 0 and frame - onset < DEATH_SEARCH_FRAMES:
        onset -= 1
    return onset


def _screen_labels(col, n: int, death_frames: List[int]) -> List[str]:
    """One screen label per frame; see :mod:`..screens` and :data:`SCREEN_SCROLL_LOCK`.

    Every non-zero stretch of ``blackScreen`` other than the scroll lock is a stretch the
    player does not control, Transition by default. Inside it: from the frame health
    reached zero to the frame the life is lost is the death sequence; the frames on which
    ``lives`` is negative are the GAME OVER screen; and a fade of value 22 or 62 that runs
    to the end of the recording is the end of a completed level.
    """
    mode = col("blackScreen")
    health = col("health")
    lives = col("lives")
    labels = [screens.GAMEPLAY] * n
    for start, stop, value in constant_runs([bool(v) and v != SCREEN_SCROLL_LOCK
                                             for v in mode]):
        if value:
            screens.fill(labels, start, stop, screens.TRANSITION)

    for frame in death_frames:
        screens.fill(labels, _death_onset(health, frame), frame, screens.DEATH)
    for frame in range(n):
        if lives[frame] < 0 and labels[frame] == screens.TRANSITION:
            labels[frame] = screens.GAME_OVER

    runs = constant_runs(labels)
    if runs and runs[-1][2] == screens.TRANSITION and mode[runs[-1][0]] in SCREEN_LEVEL_END_VALUES:
        screens.fill(labels, runs[-1][0], runs[-1][1], screens.LEVEL_END)
    return labels


def _player_events(acc: EventAccumulator, col, n: int) -> List[int]:
    """Player_damaged, Health_gained, Player_died, Life_gained, Player_state/Hit_recovery.

    Returns:
        The frames on which a life was lost.
    """
    health = col("health")
    lives = col("lives")

    death_frames = [f for f in range(1, n) if lives[f] < lives[f - 1]]

    damaged = []
    for frame in range(1, n):
        delta = health[frame] - health[frame - 1]
        if delta < 0:
            # A death drains the health bar; that drain is the death, not a separate hit.
            if any(-60 <= frame - df <= 180 for df in death_frames):
                continue
            acc.add("Player_damaged", frame)
            damaged.append(frame)
        elif delta > 0:
            acc.add("Health_gained", frame)

    # Post-hit recovery. `hit_timer` (added in this release, see ram.SHINOBI_CANDIDATES)
    # is set to 80 or 64 on the frame health drops and counts down once per frame while
    # the player flashes. The same byte also runs from 48 after knock-backs that cost no
    # health and idles at 1 for ~25 frames at other moments, so only stretches that begin
    # on a Player_damaged are used. A stretch is cut where health reaches 0, since the
    # counter keeps running through the death animation.
    hit_timer = col("hit_timer")
    for start, stop, _ in nonzero_runs(hit_timer, split_on_value_change=False):
        if not any(abs(start - f) <= 3 for f in damaged):
            continue
        zero = [f for f in range(start, stop + 1) if health[f] == 0]
        acc.add("Player_state/Hit_recovery", start, clip(start, stop, zero[:1]))

    # The shipped pipeline has no player-death event at all -- this is a real gap, since
    # `lives` records it unambiguously. `lives` only drops once the death animation has
    # played, 2-6 s after the fact, so the onset is walked back to the frame health
    # reached zero and `duration` runs to the life loss (the same treatment as the SMB1
    # fall death).
    for frame in death_frames:
        acc.add("Player_died", _death_onset(health, frame), frame)

    for frame in range(1, n):
        if lives[frame] > lives[frame - 1]:
            acc.add("Life_gained", frame)
    return death_frames


def _combat_events(acc: EventAccumulator, col, n: int) -> None:
    """Enemy_defeated, Projectile_appeared/Shuriken, Item_collected/Shurikens."""
    score = col("instantScore")
    for frame in range(1, n):
        if score[frame] - score[frame - 1] in KILL_SCORE_VALUES:
            acc.add("Enemy_defeated", frame)

    shurikens = col("shurikens")
    for frame in range(1, n):
        delta = shurikens[frame] - shurikens[frame - 1]
        if delta == -1:
            acc.add("Projectile_appeared/Shuriken", frame)
        elif delta > 0:
            # The amount picked up is not carried on the row; it is recoverable from
            # `shurikens` in the repetition's _variables.json.
            acc.add("Item_collected/Shurikens", frame)

    # Ninjutsu consumes several shurikens at once and decrements the magic counter.
    ninjutsu = col("ninjitsu")
    kind = col("typeOfNinjitsu")
    for frame in range(1, n):
        if ninjutsu[frame] < ninjutsu[frame - 1]:
            acc.add(f"Weapon_powerup_started/Ninjutsu{kind[frame] or ''}", frame)


def _level_events(acc: EventAccumulator, n: int) -> None:
    """Level_started. ``Level_completed`` is emitted from the screen labels in
    :func:`generate`, at the start of the end-of-level fade.

    The shipped generator fabricated ``Level_completed`` five seconds before the end of
    any repetition in which no life was lost -- a property of the whole repetition dressed
    up as a timed event -- and an earlier release of this module dropped it, having found
    that ``blackScreen`` is set in every repetition. It is: the value 40 is the scroll lock
    of an enemy wave. But its *trailing* value discriminates perfectly over the corpus: a
    fade of 22 or 62 running to the end of the recording occurs in 519 of 536 cleared
    repetitions and in none of the 130 failed ones (which end in the death value 21 or in
    play). The 17 misses are cleared repetitions whose recording stopped before the fade.
    """
    acc.add("Level_started", 0)
