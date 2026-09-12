"""Event generator for Super Mario Bros.

Covers both ports:

* ``mario``      - the NES original (``SuperMarioBros-Nes``)
* ``mariostars`` - the Super Mario All-Stars remake (``SuperMarioAllStars-Snes``)

They share the object id table (verified empirically: SMAS ``sprite_number_*`` values are
the SMB1 ids verbatim), so the two differ only in which RAM variables carry each signal.
That difference is isolated in :class:`Port`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .. import ram, screens, tracking
from ..emit import EventAccumulator, TASK_FRAME_RATES
from ..spans import clip, constant_runs, nonzero_runs

#: Enemy_State / sprite_state values that mark a defeat, and how it was achieved.
KILL_STATES = {4: "Stomp", 34: "Projectile", 132: "Shell"}

#: PlayerStatus values and the Player_state form row each gets.
FORM_NAMES = {0: "Small", 1: "Super", 2: "Fire"}

#: GameEngineSubroutine ($000E) values, from SMBDIS.ASM's dispatch table. This is the
#: game's own statement of what the player is doing, so it is preferred over inferring
#: events from counters that only move after an animation finishes.
#:
#: Super Mario All-Stars reuses the same enumeration in `player_action_state` ($7E000F):
#: the values observed in mariostars replays are exactly {0,4,5,6,7,8,9,10,11}, and the
#: shipped mariostars generator already keys the flagpole on 4 and death on 11.
ENGINE_ENTRANCE_TIMER = 0
ENGINE_VINE_AUTOCLIMB = 1
ENGINE_SIDE_PIPE_ENTRY = 2
ENGINE_VERTICAL_PIPE_ENTRY = 3
ENGINE_FLAGPOLE_SLIDE = 4
ENGINE_END_LEVEL = 5
ENGINE_LOSE_LIFE = 6
ENGINE_ENTRANCE = 7
ENGINE_NORMAL_PLAY = 8
ENGINE_CHANGE_SIZE = 9
ENGINE_INJURY_BLINK = 10
ENGINE_DEATH = 11
ENGINE_FIRE_FLOWER = 12

#: Entering a pipe (either orientation).
PIPE_STATES = (ENGINE_SIDE_PIPE_ENTRY, ENGINE_VERTICAL_PIPE_ENTRY)

#: Growing / shrinking or turning into Fire Mario -- the power-up pickup animation.
POWERUP_STATES = (ENGINE_CHANGE_SIZE, ENGINE_FIRE_FLOWER)

#: Engine states during which the game, not the player, moves things along: the area
#: entrance timer and black loading screen (0), the automatic vine climb (1), pipe entry
#: (2, 3) and the walk / drop into a new area (7). Verified on rendered frames: 0 is the
#: black screen (the "WORLD x-y" title card at a level start or after a life loss, ~24
#: frames of black between areas otherwise), 2 is Mario sinking into the pipe, 7 is Mario
#: emerging from it.
TRANSITION_STATES = (ENGINE_ENTRANCE_TIMER, ENGINE_VINE_AUTOCLIMB, ENGINE_SIDE_PIPE_ENTRY,
                     ENGINE_VERTICAL_PIPE_ENTRY, ENGINE_ENTRANCE)

#: The flagpole slide and the walk into the castle with the time bonus and fireworks.
LEVEL_END_STATES = (ENGINE_FLAGPOLE_SLIDE, ENGINE_END_LEVEL)

#: OperMode_Task value while the game engine runs; the other values (0 InitializeArea,
#: 1 ScreenRoutines, 2 SecondaryGameSetup) are the title card and area loading.
TASK_GAME_ROUTINES = 3

#: EventMusicQueue bits (NES only).
MUSIC_DEATH = 0x01
MUSIC_END_OF_LEVEL = 0x20
MUSIC_TIME_RUNNING_OUT = 0x40

#: Game timer value at which the "hurry up" warning fires.
TIMER_WARNING_VALUE = 100


@dataclass
class Port:
    """Which RAM variables carry each signal on this port of SMB1."""

    task: str
    n_slots: int
    #: variable name templates, formatted with the slot index
    type_var: str
    state_var: str
    flag_var: str
    #: per-slot visibility; None means "derive from the flag alone"
    offscreen_var: Optional[str] = None
    onscreen_flag_var: Optional[str] = None
    #: per-slot position, used only for the cross-slot merge
    page_var: Optional[str] = None
    x_var: Optional[str] = None
    #: scalar signals. The three player-state variables carry the same names on both
    #: ports: the SNES entries were added by ``ram.SMAS_CANDIDATES`` because the shipped
    #: ``player_powerup`` / ``star_power_timer`` addresses hold unrelated bytes.
    powerup_var: str = "player_status"
    star_timer_var: str = "star_timer"
    injury_timer_var: str = "injury_timer"
    coins_var: str = "coins"
    lives_var: str = "lives"
    timer_var: str = "time"
    engine_var: str = "player_state"
    flagpole_var: str = "jump_airborne"
    flagpole_value: int = 3
    checkpoint_var: Optional[str] = None
    music_var: Optional[str] = None
    #: Player_Y_HighPos: >1 means the player is below the bottom of the screen. When
    #: present this dates a fall exactly; when absent the timer-freeze proxy is used.
    player_y_high_var: Optional[str] = None
    #: per-slot screen Y, used to tell an emerged Piranha Plant from a hidden one
    enemy_y_var: Optional[str] = None
    #: Score increment produced by breaking one brick. The NES score field is BCD in
    #: units of 10 points, so a 50-point brick reads as 5; the SNES field holds actual
    #: points, so the same brick reads as 50.
    brick_score_delta: int = 5
    #: Variable carrying OperMode_Task ($0772) and how to read it out. Needed on the
    #: SNES, where the engine variable idles at 8 while the title card is up, so the
    #: intro screen is invisible to it; on the NES the engine reads 0 there.
    task_var: Optional[str] = None
    task_decode: Optional[Callable[[int], int]] = None


def _smas_oper_mode_task(value: int) -> int:
    """OperMode_Task from the shipped mariostars ``reset`` variable.

    ``reset`` is declared as a 4-byte little-endian BCD read at $0771, so its decimal
    digits are the bytes $0771..$0774 two at a time: byte 1 is OperMode_Task ($0772). The
    values observed are exactly 100 / 1000100 / 1060100 (task 1, the title card),
    1000200 (task 2, one frame), 300 / 60300 (task 3, gameplay) and 0 / 1000000 (task 0,
    area initialisation), verified on rendered frames. Anything that does not decode to
    0-3 is treated as gameplay rather than guessed at.
    """
    task = (int(value) // 100) % 100
    return task if task <= TASK_GAME_ROUTINES else TASK_GAME_ROUTINES


NES = Port(
    task="mario", n_slots=6,
    type_var="enemy_id_{}", state_var="enemy_kill3{}", flag_var="enemy_drawn1{}",
    offscreen_var="enemy_offscr_masked_{}",
    page_var="enemy_pageloc_{}", x_var="enemy_x_{}",
    music_var="event_music_queue",
    player_y_high_var="player_y_screen", enemy_y_var="enemy_y_{}",
)

SNES = Port(
    task="mariostars", n_slots=8,
    type_var="sprite_number_{}", state_var="sprite_state_{}",
    flag_var="sprite_onscreen_flag_{}", onscreen_flag_var="sprite_onscreen_flag_{}",
    coins_var="player_coins", lives_var="lives", timer_var="time_units",
    engine_var="player_action_state", flagpole_var="player_action_state",
    flagpole_value=4, brick_score_delta=50,
    task_var="reset", task_decode=_smas_oper_mode_task,
)

PORTS = {"mario": NES, "mariostars": SNES}


def _flag_name(port: Port, slot: int) -> str:
    """The NES Enemy_Flag slots are named enemy_drawn15..19 plus enemy_drawn20."""
    if port is NES:
        return f"enemy_drawn{15 + slot}"
    return port.flag_var.format(slot)


class _Vars:
    """Per-slot and scalar accessors over one repetition's variables dict."""

    def __init__(self, repvars: dict, port: Port):
        self.v = repvars
        self.port = port
        self.n = len(repvars[port.coins_var])
        self.types = [repvars.get(port.type_var.format(i), [0] * self.n)
                      for i in range(port.n_slots)]
        self.states = [repvars.get(port.state_var.format(i), [0] * self.n)
                       for i in range(port.n_slots)]
        self.flags = [repvars.get(_flag_name(port, i), [0] * self.n)
                      for i in range(port.n_slots)]
        if port.offscreen_var:
            self.offscreen = [repvars.get(port.offscreen_var.format(i), [0] * self.n)
                              for i in range(port.n_slots)]
        else:
            self.offscreen = None
        if port.enemy_y_var:
            self.eys = [repvars.get(port.enemy_y_var.format(i), [0] * self.n)
                        for i in range(port.n_slots)]
            self.emerged = _piranha_emerged(self)
        else:
            self.eys = None
            self.emerged = None
        if port.page_var and port.x_var:
            self.pages = [repvars.get(port.page_var.format(i), [0] * self.n)
                          for i in range(port.n_slots)]
            self.xs = [repvars.get(port.x_var.format(i), [0] * self.n)
                       for i in range(port.n_slots)]
        else:
            self.pages = self.xs = None

    def scalar(self, name: str) -> List:
        return self.v.get(name, [0] * self.n)

    def visible(self, slot: int, frame: int) -> bool:
        """Is this slot showing an object the player can see?

        NES: the slot is active (Enemy_Flag) and not marked offscreen
        (EnemyOffscrBitsMasked == 0, verified to put the object inside the visible band
        97.5-98.9% of frames). SNES: bit 0 of the sprite onscreen flag.
        """
        if self.emerged is not None and not self.emerged[slot][frame]:
            return False          # a Piranha Plant withdrawn into its pipe
        if self.offscreen is not None:
            return bool(self.flags[slot][frame]) and self.offscreen[slot][frame] == 0
        return bool(self.flags[slot][frame] & 1)

    def position(self, slot: int, frame: int) -> Optional[int]:
        if self.pages is None:
            return None
        return self.pages[slot][frame] * 256 + self.xs[slot][frame]


#: A Piranha Plant rises exactly 24 px out of its pipe. A run has to show most of that
#: travel before the resting position can be identified.
PIRANHA_TRAVEL = 24
PIRANHA_MIN_OBSERVED = 20


def _piranha_emerged(d: "_Vars") -> List[List[bool]]:
    """Per slot and frame: False while a Piranha Plant is withdrawn into its pipe.

    The plant holds an enemy slot for its whole cycle -- rising, waiting, retracting,
    then sitting inside the pipe -- and the game's offscreen bits only describe the
    horizontal edges, so the slot reads as "visible" even while the plant is hidden and
    cannot touch the player. Its screen Y traces the cycle exactly: measured over 60
    mario replays the plant moves through 25 distinct Y values spanning 24 px, resting
    at the maximum.

    So within each run of the slot holding a plant, the resting position is the maximum
    Y observed, and the plant is out whenever it sits above that. A run that never shows
    the full travel cannot identify its own resting position, and is left visible
    throughout rather than guessed at. `Enemy_State` was checked first and is 0 for the
    entire cycle, so it cannot serve; this is also why the SNES port, which exposes no
    per-sprite Y, keeps the old behaviour.
    """
    mask = [[True] * d.n for _ in range(d.port.n_slots)]
    for slot in range(d.port.n_slots):
        types, flags, ys = d.types[slot], d.flags[slot], d.eys[slot]
        frame = 0
        while frame < d.n:
            if not flags[frame] or types[frame] != ram.SMB1_PIRANHA_ID:
                frame += 1
                continue
            stop = frame
            while (stop < d.n and flags[stop]
                   and types[stop] == ram.SMB1_PIRANHA_ID):
                stop += 1
            run = ys[frame:stop]
            if max(run) - min(run) >= PIRANHA_MIN_OBSERVED:
                down = max(run)
                for k in range(frame, stop):
                    mask[slot][k] = ys[k] < down - 1
            frame = stop
    return mask


def _is_flying_bullet(d: "_Vars", track) -> bool:
    """True if a Bullet Bill track is a bullet in flight rather than its cannon.

    Ids 0x08 and 0x33 are shared with the stationary cannon that fires them. A bullet
    moves in X on essentially every frame (measured median 1.5 px/frame); the cannon
    does not move at all. Where the port exposes no per-slot X -- mariostars -- the test
    cannot run and every track is kept, so roughly 10% of that dataset's Bullet Bill
    tracks are expected to be the cannon.
    """
    if d.pages is None:
        return True
    xs = [d.position(track.slot, f)
          for f in range(track.frame_start, track.frame_stop + 1)]
    steps = [abs(b - a) for a, b in zip(xs, xs[1:])]
    if not steps:
        return True
    return sum(1 for x in steps if x) / len(steps) >= 0.5


def _name(type_id: int) -> str:
    """The event-name suffix for an object id.

    Ids 0x08 and 0x33 both hold a Bullet Bill -- the disassembly names them after the
    two spawners (frenzy and cannon) rather than after the object -- so both report
    ``BulletBill``. Everything else uses the disassembly's own name.
    """
    if type_id in ram.SMB1_BULLET_IDS:
        return "BulletBill"
    return ram.SMB1_ENEMY_IDS.get(type_id, f"Unknown_0x{type_id:02X}")


def _transitions(series, predicate) -> List[int]:
    """Frames where ``predicate`` becomes true, having been false the frame before."""
    out = []
    prev = False
    for frame, value in enumerate(series):
        now = bool(predicate(value))
        if now and not prev:
            out.append(frame)
        prev = now
    return out


def generate(repvars: dict, task: str, level=None, outcome: Optional[str] = None,
             **defaults) -> "object":
    """Build the events DataFrame for one SMB1 repetition.

    Args:
        repvars: The repetition's ``_variables.json`` contents.
        task: ``"mario"`` or ``"mariostars"``.
        level: Level label to stamp on every row; defaults to ``repvars["level"]``.
        outcome: The summary ``Outcome``, used to gate the warp event.
        **defaults: Extra columns copied onto every row (phase, Index*, stim_file).

    Returns:
        A pandas DataFrame of events, with onsets relative to the repetition start.
    """
    port = PORTS[task]
    fs = TASK_FRAME_RATES[task]
    d = _Vars(repvars, port)
    acc = EventAccumulator(level if level is not None else repvars.get("level"), fs,
                           **defaults)

    _actions(acc, repvars, task)
    _level_events(acc, d, port, outcome)
    _enemy_events(acc, d, port)
    _player_events(acc, d, port)
    _item_events(acc, d, port)
    _environment_events(acc, d, port)

    return acc.to_frame()


# --------------------------------------------------------------------------- actions

#: Raw button -> Action/* event. The jump and run buttons differ between the ports: the
#: NES uses A/B, while Super Mario All-Stars uses B/Y (as the shipped mariostars
#: generator already does). Directions and START/SELECT are common to both.
_COMMON_BUTTONS = {
    "LEFT": "Action/Left", "RIGHT": "Action/Right", "UP": "Action/Up",
    "DOWN": "Action/Down", "START": "Action/Start", "SELECT": "Action/Select",
}
BUTTON_ACTIONS = {
    "mario": {**_COMMON_BUTTONS, "A": "Action/Jump", "B": "Action/Run"},
    # A and X are alternate bindings for jump and run on the SNES pad; L and R have no
    # documented function in SMAS's SMB1, so they are reported as Action/Other with the
    # raw button preserved rather than being assigned a meaning we cannot justify.
    "mariostars": {**_COMMON_BUTTONS, "B": "Action/Jump", "Y": "Action/Run",
                   "A": "Action/Jump", "X": "Action/Run",
                   "L": "Action/Other", "R": "Action/Other"},
}


def _actions(acc: EventAccumulator, repvars: dict, task: str) -> None:
    """Button holds, as Action/* events carrying the raw button."""
    for button, trial_type in BUTTON_ACTIONS[task].items():
        series = repvars.get(button)
        if not series:
            continue
        held = False
        start = 0
        for frame, value in enumerate(series):
            if value and not held:
                held, start = True, frame
            elif not value and held:
                acc.add(trial_type, start, frame - 1, button=button)
                held = False
        if held:
            acc.add(trial_type, start, len(series) - 1, button=button)


# ---------------------------------------------------------------------- enemy events


#: Frames to search back from the life-loss for the moment the player left the screen.
#: The observed lag is 244-259 frames on both ports; 400 leaves ample margin.
FALL_SEARCH_FRAMES = 400

#: Half of the SMB1 timer tick, in frames. The timer-freeze proxy can only place the
#: fall at the last tick before the freeze, which lands a median 12 frames early on the
#: NES when checked against the true Player_Y_HighPos crossing; adding this back removes
#: that bias, leaving roughly +/-12 frames (0.2 s).
TIMER_TICK_HALF = 12


def _fall_onset(d: "_Vars", port: Port, reset_frame: int) -> int:
    """The frame the player dropped off the bottom of the screen, before `reset_frame`.

    The engine only reaches `PlayerLoseLife` about 4 s after a fall -- the game lets the
    player drop out of the level, then resets. Recording the death at the reset puts it
    seconds after anything the player saw, so the onset is walked back to the fall.

    NES: exact, from `Player_Y_HighPos` (`player_y_screen`), which is 1 while the player
    is on screen and >1 once below it. Checked over 150 replays: 69 of 69 fall deaths
    have such a crossing, at a lag of 244-257 frames.

    SNES: no player-Y address is exposed by this port, so the proxy is the frame the
    level timer stops ticking -- the game freezes gameplay the moment the player drops
    out. Validated by running the same proxy on the NES, where the true crossing is
    known: median error -12 frames, 100% within 24 frames, hence the tick correction.
    Returns `reset_frame` unchanged if neither signal is available.
    """
    lo = max(reset_frame - FALL_SEARCH_FRAMES, 1)
    if port.player_y_high_var:
        y = d.scalar(port.player_y_high_var)
        if any(y):
            frame = reset_frame
            while frame > lo and y[frame] > 1:
                frame -= 1
            if lo < frame < reset_frame:
                return frame + 1
    timer = d.scalar(port.timer_var)
    for frame in range(reset_frame - 1, lo, -1):
        if timer[frame] != timer[frame - 1]:
            return min(frame + TIMER_TICK_HALF, reset_frame)
    return reset_frame


def _enemy_events(acc: EventAccumulator, d: _Vars, port: Port) -> None:
    """Enemy_on_screen / Enemy_defeated / Enemy_counter."""
    tracks = tracking.find_tracks(
        d.n, port.n_slots, d.visible, lambda s, f: d.types[s][f],
        keep=lambda tid: tid not in ram.SMB1_NON_ENEMY_IDS)
    if d.pages is not None:
        tracks = tracking.merge_across_slots(tracks, d.position)
    # Bullet Bills share their ids with the cannon that fires them; keep only the ones
    # actually in flight.
    tracks = [t for t in tracks
              if t.type_id not in ram.SMB1_BULLET_IDS or _is_flying_bullet(d, t)]

    # Attribute each defeat to the visible track it belongs to, at most one per track.
    # Without this a single enemy whose kill state is re-entered (a shell struck twice,
    # say) produced several Enemy_defeated rows, which is how "more endings than
    # appearances" showed up in validation.
    defeats = _defeat_frames(d, port)
    claimed = set()
    for track in tracks:
        for index, (slot, frame, method) in enumerate(defeats):
            if index in claimed or slot != track.slot:
                continue
            if track.frame_start <= frame <= track.frame_stop + 4:
                track.ended_defeated = True
                track.defeat = (frame, method)
                claimed.add(index)
                break

    for track in tracks:
        name = _name(track.type_id)
        acc.add(f"Enemy_on_screen/{name}", track.frame_start, track.frame_stop)
        if track.ended_defeated:
            frame, method = track.defeat
            acc.add(f"Enemy_defeated/{method}/{name}", frame)

    # Defeats that belong to no visible track are enemies killed off screen -- typically
    # a kicked shell rolling on out of view. They are real (the score goes up), so they
    # are kept, but they have no Enemy_on_screen partner.
    for index, (slot, frame, method) in enumerate(defeats):
        if index in claimed:
            continue
        type_id = d.types[slot][frame]
        if type_id in ram.SMB1_NON_ENEMY_IDS:
            continue
        acc.add(f"Enemy_defeated/{method}/{_name(type_id)}", frame)

    # Projectiles occupying enemy slots (Bowser flames; Bullet Bills are enemies).
    proj = tracking.find_tracks(
        d.n, port.n_slots, d.visible, lambda s, f: d.types[s][f],
        min_frames=2, keep=lambda tid: tid in ram.SMB1_PROJECTILE_IDS)
    for track in proj:
        acc.add(f"Projectile_on_screen/{_name(track.type_id)}",
                track.frame_start, track.frame_stop)


def _defeat_frames(d: _Vars, port: Port) -> List[tuple]:
    """(slot, frame, method) for every enemy defeat, at the frame the kill happens.

    The event is emitted on the *first* frame of a kill state, i.e. the transition into
    it, not the last. Two reasons:

    1. Semantics: the enemy is defeated when it is hit, not when its corpse finishes
       falling off the screen (state 34 persists for the whole death animation).
    2. Correctness: on a projectile kill the game deliberately shoves the dying enemy's
       bounding box off screen (``MoveBoundBoxOffscreen``, right after it writes
       ``EnemyOffscrBitsMasked``). Reading the defeat at the end of the animation
       therefore placed it long after the enemy stopped being visible, so it could not be
       matched to its own Enemy_on_screen track -- which is how validation reported 17 of
       20 defeats in a w3-1 replay as "off screen".

    The number of defeats is unchanged; only their onsets move earlier.
    """
    out = []
    for slot in range(port.n_slots):
        state = d.states[slot]
        for frame in range(1, d.n):
            value = state[frame]
            if value in KILL_STATES and state[frame - 1] not in KILL_STATES:
                out.append((slot, frame, KILL_STATES[value]))
    return out


# --------------------------------------------------------------------- player events


def _player_events(acc: EventAccumulator, d: _Vars, port: Port) -> None:
    """Player_damaged, Player_died/*, Life_gained, Player_state/*.

    Driven by GameEngineSubroutine rather than by counters: the engine states the player
    action on the frame it begins, whereas `lives` only drops once the death animation
    has finished (several seconds later).
    """
    engine = d.scalar(port.engine_var)
    lives = d.scalar(port.lives_var)
    timer = d.scalar(port.timer_var)

    # Damage: the engine runs the injury-blink routine.
    for frame in _transitions(engine, lambda v: v == ENGINE_INJURY_BLINK):
        acc.add("Player_damaged", frame)

    # Deaths: the engine runs the death routine. Classified by cause below.
    death_frames = _transitions(engine, lambda v: v == ENGINE_DEATH)
    death_onsets = list(death_frames)
    for frame in death_frames:
        acc.add(f"Player_died/{_death_cause(d, port, frame, timer, engine)}", frame)

    # Falls do not run the death routine -- the player simply drops off the screen and
    # the engine goes straight to losing a life. Catch those separately, ignoring the
    # ones already accounted for by a death routine.
    falls = []
    for frame in _transitions(engine, lambda v: v == ENGINE_LOSE_LIFE):
        if any(0 <= frame - df <= 400 for df in death_frames):
            continue
        onset = _fall_onset(d, port, frame)
        acc.add("Player_died/Fall", onset, frame)
        death_onsets.append(onset)
        falls.append((onset, frame))

    labels = _screen_labels(d, port, falls)
    screens.emit(acc, labels)
    _state_events(acc, d, port, sorted(death_onsets), screens.alive_mask(labels))

    # Extra lives. The counter can also wrap when coins hit 100, which is a 1-up too.
    for frame in range(1, d.n):
        if lives[frame] > lives[frame - 1]:
            acc.add("Life_gained", frame)


def _screen_labels(d: _Vars, port: Port, falls: List[tuple]) -> List[str]:
    """One screen label per frame; see :mod:`..screens`.

    The engine state says what the game is doing on each frame: the flagpole slide and
    walk into the castle (4, 5) are the end-of-level sequence, the death routine and the
    life loss (11, 6) the death sequence, and the entrance timer, vine climb, pipe entry
    and area entrance (0, 1, 2, 3, 7) are transitions during which the player has no
    control. Everything else is gameplay, including the brief grow / shrink / fire-flower
    freezes (9, 12) and the post-hit blink (10).

    Two things the engine cannot see. A fall leaves it at 8 while the player drops out
    of the level, so the interval from the fall to the life loss is relabelled from the
    ``Player_died/Fall`` timing. And on the SNES the engine idles at 8 while the title
    card is up (the NES resets it to 0 there), so any frame on which OperMode_Task is not
    running the game routines is a transition too.

    Finally, a transition block at the start of the repetition or directly after a death
    is the level's title card -- the black "WORLD x-y / Mario x n" screen, ~2 s -- and is
    labelled Level_intro. The 24-frame black screen between areas and the pipe / vine
    animations around it stay Transition.
    """
    engine = d.scalar(port.engine_var)
    labels = []
    for value in engine:
        if value in LEVEL_END_STATES:
            labels.append(screens.LEVEL_END)
        elif value in (ENGINE_DEATH, ENGINE_LOSE_LIFE):
            labels.append(screens.DEATH)
        elif value in TRANSITION_STATES:
            labels.append(screens.TRANSITION)
        else:
            labels.append(screens.GAMEPLAY)

    if port.task_var and port.task_var in d.v:
        for frame, value in enumerate(d.v[port.task_var]):
            if (labels[frame] == screens.GAMEPLAY
                    and port.task_decode(value) != TASK_GAME_ROUTINES):
                labels[frame] = screens.TRANSITION

    for onset, stop in falls:
        screens.fill(labels, onset, stop, screens.DEATH)

    for start, stop, label in constant_runs(labels):
        if label == screens.TRANSITION and (start == 0
                                            or labels[start - 1] == screens.DEATH):
            screens.fill(labels, start, stop, screens.LEVEL_INTRO)
    return labels


def _state_events(acc: EventAccumulator, d: _Vars, port: Port,
                  death_onsets: List[int], alive: List[bool]) -> None:
    """Player_state/{Small,Super,Fire,Star,Hit_recovery}: one row per continuous stretch.

    The form is read straight from PlayerStatus, which the game writes on the very frame
    the mushroom or flower is collected (the same frame the engine enters 9 / 12) and on
    the frame of a hit (engine 10), so no look-ahead is needed. Form rows exist only on
    the frames where the player is alive in the level (``alive``, from the screen
    labels): they are cut at a death, since the game leaves the status set through the
    death animation and only resets it on the restart, but Mario is not Super while dead;
    and Small resumes only once the title card has gone and play restarts. Star and
    Hit_recovery are the non-zero stretches of StarInvincibleTimer and InjuryTimer, cut
    at a death that falls inside them.
    """
    # A _variables.json predating the variable has no form information at all; a
    # zero-filled default would otherwise read as Small throughout.
    if port.powerup_var in d.v:
        for start, stop, value in constant_runs(d.v[port.powerup_var], keep=alive):
            name = FORM_NAMES.get(value)
            if name is None:
                continue
            acc.add(f"Player_state/{name}", start, stop)

    for var, name in ((port.star_timer_var, "Star"),
                      (port.injury_timer_var, "Hit_recovery")):
        series = d.v.get(var)
        if not series:
            continue  # _variables.json predating the variable
        for start, stop, _ in nonzero_runs(series, split_on_value_change=False):
            acc.add(f"Player_state/{name}", start, clip(start, stop, death_onsets))


def _death_cause(d: _Vars, port: Port, frame: int, timer, engine) -> str:
    """Classify a death that ran the engine's death routine.

    A timeout is unambiguous (the timer is exhausted). Everything else that reaches the
    death routine did so through contact, since falling off the screen bypasses it.
    """
    if timer:
        window = timer[max(0, frame - 120):frame + 1]
        if window and all(t == 0 for t in window):
            return "Timeout"
    return "Enemy"


# ----------------------------------------------------------------------- item events


def _item_events(acc: EventAccumulator, d: _Vars, port: Port) -> None:
    """Item_collected/Coin, Item_on_screen/*, Block_smashed."""
    # Block_smashed. Breaking a brick scores 50 points, which the BCD score field holds
    # as 5. The same +5 increment also appears once the level is over, when the remaining
    # time is converted to score at 50 points per unit, so scoring stops at the end of
    # the level. Requiring the player to be airborne removes the rest: a brick can only
    # be broken from below.
    score = d.scalar("score")
    engine = d.scalar(port.engine_var)
    ends = _transitions(engine, lambda v: v in (ENGINE_FLAGPOLE_SLIDE, ENGINE_END_LEVEL))
    cutoff = ends[0] if ends else d.n
    airborne = d.scalar("jump_airborne") if port is NES else None
    for frame in range(1, min(cutoff, d.n)):
        if score[frame] - score[frame - 1] != port.brick_score_delta:
            continue
        if airborne is not None and airborne[frame - 1] not in (1, 2):
            continue
        acc.add("Block_smashed", frame)

    coins = d.scalar(port.coins_var)
    for frame in range(1, d.n):
        delta = coins[frame] - coins[frame - 1]
        # The counter wraps at 100 (and awards a life), so a wrap is still a collection.
        if delta > 0 or delta <= -99:
            acc.add("Item_collected/Coin", frame)

    # Power-up items live in the last enemy slot on the NES; on the SNES they have their
    # own entity type variable.
    item_tracks = tracking.find_tracks(
        d.n, port.n_slots, d.visible, lambda s, f: d.types[s][f],
        min_frames=2, keep=lambda tid: tid in ram.SMB1_ITEM_SCENERY_IDS)
    for track in item_tracks:
        name = _name(track.type_id)
        if track.type_id == 0x2E:  # PowerUpObject
            acc.add("Item_on_screen/Powerup", track.frame_start, track.frame_stop)
        elif track.type_id in (0x30, 0x31):
            continue  # handled as Flagpole_visible / Castle_visible
        else:
            acc.add(f"Item_on_screen/{name}", track.frame_start, track.frame_stop)


# ---------------------------------------------------------------- environment events


def _environment_events(acc: EventAccumulator, d: _Vars, port: Port) -> None:
    """Pipe_entered, Checkpoint_reached, Flagpole_visible, Castle_visible,
    Timer_warning_started."""
    engine = d.scalar(port.engine_var)
    for frame in _transitions(engine, lambda v: v in PIPE_STATES):
        acc.add("Pipe_entered", frame)

    # Checkpoint_reached is deliberately NOT emitted for SMB1. Its only candidate
    # signal, HalfwayPage ($075B), is written when the player dies past the midpoint in
    # order to place the respawn -- not when the midpoint is crossed. Verified on a w1-1
    # replay where it is non-zero only during the two death/respawn sequences. Emitting
    # it would mislabel deaths as checkpoints.

    # The flagpole and end-of-level star flag occupy enemy slots, but the enemy
    # offscreen test never clears for the star flag (0 of 479 frames in a sampled
    # replay), so scenery visibility is judged by slot occupancy alone.
    def scenery_visible(slot, frame):
        return bool(d.flags[slot][frame])

    for track in tracking.find_tracks(
            d.n, port.n_slots, scenery_visible, lambda s, f: d.types[s][f], min_frames=2,
            keep=lambda tid: tid in (0x30, 0x31)):
        label = "Flagpole_visible" if track.type_id == 0x30 else "Castle_visible"
        acc.add(label, track.frame_start)

    # Timer warning. On the NES the game announces it itself via the music queue, which
    # is authoritative. Elsewhere fall back to the timer crossing 100 -- but only while
    # the player is actually playing: at level completion the timer drains to zero to pay
    # out the score bonus, and that downward crossing is not a hurry-up warning.
    if port.music_var:
        for frame in _transitions(d.scalar(port.music_var),
                                  lambda v: v & MUSIC_TIME_RUNNING_OUT):
            acc.add("Timer_warning_started", frame)
    else:
        timer = d.scalar(port.timer_var)
        for frame in range(1, d.n):
            if (timer[frame - 1] > TIMER_WARNING_VALUE >= timer[frame]
                    and engine[frame] == ENGINE_NORMAL_PLAY):
                acc.add("Timer_warning_started", frame)
                break


# ---------------------------------------------------------------------- level events


def _level_events(acc: EventAccumulator, d: _Vars, port: Port,
                  outcome: Optional[str]) -> None:
    """Level_started, Level_completed, Level_exited/Warp."""
    acc.add("Level_started", 0)

    # PlayerEndLevel is the game's own "level is over, walk to the castle" routine. It
    # fires on castle levels too, where there is no flagpole and the shipped
    # jump_airborne == 3 test never triggers.
    engine = d.scalar(port.engine_var)
    ends = _transitions(engine, lambda v: v == ENGINE_END_LEVEL)
    if not ends:
        ends = _transitions(engine, lambda v: v == ENGINE_FLAGPOLE_SLIDE)
    if ends:
        acc.add("Level_completed", ends[0])

    # Warp-zone exit. Finishing a level ALSO advances the world index, so a world change
    # is only a warp when the level never ended -- without this guard the event fired on
    # every completed level (2201 events against 148 warp outcomes in mario).
    #
    # Detected from the world index rather than from the summary Outcome because that
    # Outcome was unreliable: the previous _determine_outcome tested `jump_airborne == 3`,
    # which is the flagpole slide *and* the vine climb, so a W4-2 warp taken up the vine
    # was labelled "cleared".
    if ends:
        return

    # `_Vars.scalar` returns a zero-filled list for an absent key, which is truthy, so
    # `a or b` would never fall through -- pick the key that is actually present.
    world = d.v.get("world") or d.v.get("current_world") or []
    area = d.v.get("area") or d.v.get("current_level") or []
    warped = None
    for series in (world, area):
        if not series:
            continue
        for frame in range(1, len(series)):
            if series[frame] != series[frame - 1]:
                warped = frame if warped is None else min(warped, frame)
                break
    if warped is not None:
        acc.add("Level_exited/Warp", warped)
