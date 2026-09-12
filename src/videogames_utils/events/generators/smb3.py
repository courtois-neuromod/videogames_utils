"""Event generator for Super Mario Bros. 3 (``mario3``).

Uses the RAM addresses verified by ``videogames_utils.events.ram`` against
captainsouthbird's disassembly, most importantly:

* ``object_id_*`` (``Level_ObjectID``) decoded through the 170-entry ``OBJ_*`` table
* ``object_state_*`` (``Objects_State``) with its documented ``OBJSTATE_*`` constants,
  which distinguish a stomp from a shell kill from a projectile kill
* ``player_is_dying`` (``Player_IsDying``), which states the cause of death directly and
  replaces the timer-freeze / y-position heuristic the shipped generator uses

Structural note: in this dataset a single level *attempt* can span up to three one-life
``.bk2`` files grouped by ``IndexLevel``. The caller passes ``index_level`` so only the
first gets ``Level_started`` and the rest get ``Level_restarted``.
"""

from __future__ import annotations

import re
from typing import List, Optional

from .. import screens, tracking
from ..emit import EventAccumulator, TASK_FRAME_RATES
from ..spans import clip, constant_runs, nonzero_runs
from ..smb3_ids import SMB3_OBJECT_IDS, SMB3_SPECIAL_OBJECT_IDS

TASK = "mario3"
N_SLOTS = 8

#: Player_Suit values, from smb3.asm's PLAYERSUIT_* constants.
SUIT_NAMES = {
    0: "Small", 1: "Super", 2: "Fire", 3: "Raccoon",
    4: "Frog", 5: "Tanooki", 6: "Hammer",
}

#: Player_IsDying values.
DEATH_CAUSES = {1: "Enemy", 2: "Fall", 3: "Timeout"}

#: Objects_State values that mean the object was defeated, and by what.
DEFEAT_STATES = {
    6: "Projectile",   # OBJSTATE_KILLED   - flipped over and falling off screen
    7: "Stomp",        # OBJSTATE_SQUASHED - generally a stomped Goomba
    8: "Projectile",   # OBJSTATE_POOFDEATH - e.g. a Piranha death
}

#: Objects_State value meaning a shelled enemy has been kicked.
STATE_SHELLED = 3
STATE_KICKED = 5

#: Player_HaltGame values at or above this hold the game while the next area loads
#: after a pipe or door: 128 / 130 are the black screen, 129 / 131 the fade into the new
#: area with the player emerging from the pipe (verified on rendered frames). The values
#: below it are frame countdowns: the pipe-entry animation holds one value for its whole
#: length (14 for 60 frames, say), while the grow / shrink animations count 46 -> 1 or
#: 24 -> 1 one frame at a time, and 1 / 2 / 3 mirror Player_IsDying during a death.
HALT_AREA_LOAD = 128

#: Goal card ids, from smb3.asm's CARD_* constants.
CARD_NAMES = {0: "Mushroom", 1: "Flower", 2: "Star", 3: "1Up",
              4: "10Coin", 5: "20Coin", 8: "Wild"}

#: Object ids that are the end-of-level goal cards.
GOAL_CARD_OBJECTS = {0x21: "Mushroom", 0x22: "Flower", 0x23: "Star"}

#: Object ids that are items rather than enemies.
ITEM_OBJECT_IDS = {0x0B: "1Up", 0x0C: "Starman", 0x0D: "Mushroom",
                   0x19: "FireFlower", 0x1E: "SuperLeaf"}

#: Object ids that are scenery, platforms, items or engine control objects, never
#: enemies. SMB3 keeps all of these in the same object table as enemies, so they must be
#: filtered out or they become spurious Enemy_on_screen events (verified: a "Twirlingplat"
#: and a "Fallingplatform" both showed up as enemies before this filter existed).
#: Derived from the disassembly's own OBJ_* names rather than hand-listed, so the filter
#: stays correct if the table is regenerated.
_NON_ENEMY_NAME_PATTERN = re.compile(
    r"platform|plat|lift|cloud|block|bounce|door|anchor|controller|vine|debris|coin|"
    r"card|powerup|treasure|arrow|log|wood|oscillat|invisible|warphide|pipeway|spawn|"
    r"empty|unused|generator|toad|king|princess|bonus|hidden|switch|note|scroll|"
    r"watercurrent|autoscroll|bolt",
    re.IGNORECASE)

NON_ENEMY_OBJECT_IDS = (
    set(GOAL_CARD_OBJECTS)
    | set(ITEM_OBJECT_IDS)
    | {oid for oid, name in SMB3_OBJECT_IDS.items()
       if _NON_ENEMY_NAME_PATTERN.search(name)}
)

#: NES controller mapping (same as SMB1).
BUTTON_ACTIONS = {
    "LEFT": "Action/Left", "RIGHT": "Action/Right", "UP": "Action/Up",
    "DOWN": "Action/Down", "A": "Action/Jump", "B": "Action/Run",
    "START": "Action/Start", "SELECT": "Action/Select",
}


def _name(object_id: int) -> str:
    return SMB3_OBJECT_IDS.get(object_id, f"Unknown_0x{object_id:02X}")


def _transitions(series, predicate) -> List[int]:
    out, prev = [], False
    for frame, value in enumerate(series):
        now = bool(predicate(value))
        if now and not prev:
            out.append(frame)
        prev = now
    return out


class _Vars:
    def __init__(self, repvars: dict):
        self.v = repvars
        self.n = len(repvars["score"])
        self.ids = [self.col(f"object_id_{i}") for i in range(N_SLOTS)]
        self.states = [self.col(f"object_state_{i}") for i in range(N_SLOTS)]
        self.sobj = [self.col(f"special_obj_id_{i}") for i in range(N_SLOTS)]
        self.hvis = [self.col(f"object_sprhvis_{i}") for i in range(N_SLOTS)]
        self.vvis = [self.col(f"object_sprvvis_{i}") for i in range(N_SLOTS)]
        self.has_hvis = any(any(col) for col in self.hvis)
        self.has_vvis = any(any(col) for col in self.vvis)

    def col(self, name: str) -> List:
        return self.v.get(name, [0] * self.n)

    def visible(self, slot: int, frame: int) -> bool:
        """Is this slot holding an object the player can see?

        The slot must be occupied (``Objects_State != 0``) and *both* of the game's own
        visibility flags must be clear: ``Objects_SprHVis == 0`` (no 8x16 sprite of the
        object is off the left or right edge) and ``Objects_SprVVis == 0`` (none off the
        top or bottom edge). Occupancy alone means only "loaded in RAM": SMB3 keeps
        objects live well outside the camera, and in vertically scrolling levels a slot
        can be horizontally on-screen while sitting entirely above or below it.

        Validated against an independent geometric reference -- the object's level X
        (``Objects_X`` + ``Objects_XHi``) minus the screen scroll (``Horz_Scroll`` +
        ``Horz_Scroll_Hi``): over four replays, ``SprHVis == 0`` puts the object inside
        the visible 256px band on **99.9%** of frames (n=9571) and ``SprHVis != 0`` on
        only 11.7% (n=3394).

        An earlier attempt to validate this used ``Objects_SpriteX/Y``, which hold stale
        values whenever an object is not being drawn and therefore cannot adjudicate;
        that is why the scroll variables were added.

        ``SprVVis`` was validated the same way against ``Objects_Y`` + ``Objects_YHi``
        minus ``Vert_Scroll`` + ``Vert_Scroll_Hi``: among slot-frames already passing the
        horizontal test, ``SprVVis == 0`` sits inside the visible 240px band on
        **100.0%** of frames (n=37436) and ``SprVVis != 0`` on **5.1%** (n=9722).

        Falls back to slot occupancy alone when the flags are absent, so that
        ``_variables.json`` produced before those addresses were added still work.
        """
        if not self.states[slot][frame]:
            return False
        if self.has_hvis and self.hvis[slot][frame] != 0:
            return False
        if self.has_vvis and self.vvis[slot][frame] != 0:
            return False
        return True


def generate(repvars: dict, level=None, outcome: Optional[str] = None,
             rep_index: Optional[int] = None, **defaults):
    """Build the events DataFrame for one SMB3 repetition.

    Args:
        rep_index: Position of this .bk2 among the repetitions of its level within the
            run (the ``rep-NNN`` entity). In SMB3 a level attempt spans up to three
            one-life .bk2 files, so rep 0 starts the level and the rest are restarts
            after a death. Do NOT pass ``IndexLevel`` here -- that is a dataset-wide
            counter of attempts at the level (values in the hundreds), not a position.
    """
    fs = TASK_FRAME_RATES[TASK]
    d = _Vars(repvars)
    acc = EventAccumulator(level if level is not None else repvars.get("level"), fs,
                           **defaults)

    _actions(acc, repvars)
    completed = _level_events(acc, d, rep_index)
    _object_events(acc, d)
    labels = _screen_labels(d, completed)
    screens.emit(acc, labels)
    _player_events(acc, d, screens.alive_mask(labels))
    _state_timers(acc, d)
    _item_events(acc, d)
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


def _object_events(acc: EventAccumulator, d: _Vars) -> None:
    """Enemy_*, Projectile_on_screen, Goal_card_visible, Item_on_screen."""
    tracks = tracking.find_tracks(
        d.n, N_SLOTS, d.visible, lambda s, f: d.ids[s][f],
        keep=lambda oid: oid not in NON_ENEMY_OBJECT_IDS)

    # Attribute each defeat to the track it belongs to, at most one per track, so a
    # single enemy cycling through several defeat states cannot emit several rows.
    defeats = _defeat_frames(d)
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

    # Defeats belonging to no track are enemies killed while off screen; still real.
    for index, (slot, frame, method) in enumerate(defeats):
        if index in claimed:
            continue
        oid = d.ids[slot][frame]
        if oid in NON_ENEMY_OBJECT_IDS:
            continue
        acc.add(f"Enemy_defeated/{method}/{_name(oid)}", frame)

    # A shell being kicked.
    for slot in range(N_SLOTS):
        state = d.states[slot]
        for frame in range(1, d.n):
            if state[frame] == STATE_KICKED and state[frame - 1] != STATE_KICKED:
                acc.add("Shell_started_moving", frame)

    # Projectiles live in their own SpecialObj table.
    for track in tracking.find_tracks(
            d.n, N_SLOTS, lambda s, f: bool(d.sobj[s][f]),
            lambda s, f: d.sobj[s][f], min_frames=2):
        name = SMB3_SPECIAL_OBJECT_IDS.get(track.type_id, f"Unknown_0x{track.type_id:02X}")
        acc.add(f"Projectile_on_screen/{name}", track.frame_start, track.frame_stop)

    # Goal cards and items occupy ordinary object slots.
    for track in tracking.find_tracks(
            d.n, N_SLOTS, d.visible, lambda s, f: d.ids[s][f], min_frames=2,
            keep=lambda oid: oid in GOAL_CARD_OBJECTS):
        acc.add(f"Goal_card_visible/{GOAL_CARD_OBJECTS[track.type_id]}", track.frame_start)

    for track in tracking.find_tracks(
            d.n, N_SLOTS, d.visible, lambda s, f: d.ids[s][f], min_frames=2,
            keep=lambda oid: oid in ITEM_OBJECT_IDS):
        acc.add(f"Item_on_screen/{ITEM_OBJECT_IDS[track.type_id]}",
                track.frame_start, track.frame_stop)


def _defeat_frames(d: _Vars) -> List[tuple]:
    """(slot, frame, method) for every object defeat.

    A stomp that only shells an enemy (Normal -> Shelled) is a defeat by stomp; a shelled
    enemy later kicked into others is a Shell kill for those it hits, which the state
    table does not attribute, so kicks are reported via Shell_started_moving instead.
    """
    out = []
    for slot in range(N_SLOTS):
        state = d.states[slot]
        for frame in range(1, d.n):
            now, before = state[frame], state[frame - 1]
            if now == before:
                continue
            if now in DEFEAT_STATES:
                out.append((slot, frame, DEFEAT_STATES[now]))
            elif now == STATE_SHELLED and before not in (STATE_SHELLED, STATE_KICKED):
                out.append((slot, frame, "Stomp"))
    return out


def _screen_labels(d: _Vars, completed: Optional[int]) -> List[str]:
    """One screen label per frame; see :mod:`..screens`.

    SMB3 shows no title card: a repetition opens in the level with a short palette
    fade-in. What it does have:

    * the death sequence, ``Player_IsDying`` non-zero (~200 frames);
    * area transitions after a pipe or door, ``Player_HaltGame`` >= 128 while the next
      area loads, extended back over the constant halt value of the pipe-entry animation
      that immediately precedes it;
    * the end-of-level sequence, from the frame the goal card is taken to the end of the
      recording (the card animation and the COURSE CLEAR screen, ~340 frames);
    * and, in the recordings that ran on past a death instead of stopping (148 of 4063,
      all but one of them game overs), the world map: ``level_music`` is 0 only outside a
      level, and the map carries the GAME OVER dialog when ``lives`` is negative.
    """
    dying = d.col("player_is_dying")
    halt = d.col("player_halt_game")
    music = d.col("level_music")
    lives = d.col("lives")
    labels = [screens.GAMEPLAY] * d.n

    runs = constant_runs(halt)
    for index, (start, stop, value) in enumerate(runs):
        if value < HALT_AREA_LOAD:
            continue
        screens.fill(labels, start, stop, screens.TRANSITION)
        if index and 0 < runs[index - 1][2] < HALT_AREA_LOAD:
            screens.fill(labels, runs[index - 1][0], runs[index - 1][1],
                         screens.TRANSITION)

    last_death = -1
    for start, stop, value in constant_runs(dying):
        if value:
            screens.fill(labels, start, stop, screens.DEATH)
            last_death = stop
    for frame in range(last_death + 1, d.n):
        if music[frame] == 0:
            labels[frame] = screens.GAME_OVER if lives[frame] < 0 else screens.MAP

    if completed is not None:
        screens.fill(labels, completed, d.n - 1, screens.LEVEL_END)
    return labels


def _player_events(acc: EventAccumulator, d: _Vars, alive: List[bool]) -> None:
    """Player_damaged, Player_died/*, Life_gained, Player_state/{suit}."""
    dying = d.col("player_is_dying")
    suit = d.col("powerup")           # Player_Suit ($00ED)
    lives = d.col("lives")
    flash = d.col("invisibility_timer")   # Player_FlashInv: post-hit blinking
    suit_lost = d.col("player_suit_lost")

    # Death, with the cause stated by the game itself.
    death_frames = _transitions(dying, bool)
    for frame in death_frames:
        acc.add(f"Player_died/{DEATH_CAUSES.get(dying[frame], 'Enemy')}", frame)

    # Damage: the suit-lost poof counter, falling back to the post-hit blink timer.
    hit_frames = _transitions(suit_lost, bool) or _transitions(flash, bool)
    for frame in hit_frames:
        if any(-120 <= frame - df <= 120 for df in death_frames):
            continue
        acc.add("Player_damaged", frame)

    # The suit the player wears, one row per continuous stretch, Small included, so the
    # form rows tile the frames where the player is alive in the level (``alive``, from
    # the screen labels: a row is cut at a death and none exists on the map). Player_Suit
    # changes on the frame the item is collected or the hit lands. A hit as Fire or with
    # a suit drops the player to Super in this game (verified: every 2 -> 1 transition
    # coincides with player_suit_lost), so a hit typically ends one row and starts
    # another on the same frame.
    if "powerup" in d.v:
        for start, stop, value in constant_runs(suit, keep=alive):
            name = SUIT_NAMES.get(value)
            if name is None:
                continue
            acc.add(f"Player_state/{name}", start, stop)

    for frame in range(1, d.n):
        if lives[frame] > lives[frame - 1]:
            acc.add("Life_gained", frame)


#: Timer / flag variables that each define an overlay state, and the state's name.
STATE_TIMERS = (
    ("invincibility_timer", "Star"),        # Player_StarInv
    ("invisibility_timer", "Hit_recovery"),  # Player_FlashInv (post-hit blink)
    ("flight_timer", "Flying"),             # Player_FlyTime
    ("statue_timer", "Statue"),             # Tanooki statue
    ("kuribo_shoe", "Kuribo_shoe"),         # riding Kuribo's Shoe
)


def _state_timers(acc: EventAccumulator, d: _Vars) -> None:
    """Player_state/{Star,Hit_recovery,Flying,Statue,Kuribo_shoe}, P-Switch, auto-scroll.

    Each overlay state is the non-zero stretch of its timer or flag, cut at a death that
    falls inside it. The P-Switch is a level state rather than a player state and keeps
    its started/expired pair.
    """
    death_frames = _transitions(d.col("player_is_dying"), bool)
    for var, name in STATE_TIMERS:
        for start, stop, _ in nonzero_runs(d.col(var), split_on_value_change=False):
            acc.add(f"Player_state/{name}", start, clip(start, stop, death_frames))

    for start, stop, _ in nonzero_runs(d.col("p_switch_timer"),
                                       split_on_value_change=False):
        acc.add("P-Switch_started", start, stop)
        if stop < d.n - 1:
            acc.add("P-Switch_expired", stop)

    autoscroll = d.col("level_hautoscroll")
    for frame in _transitions(autoscroll, bool):
        acc.add("Auto_scroll_started", frame)


def _item_events(acc: EventAccumulator, d: _Vars) -> None:
    """Item_collected/Coin and Block_smashed."""
    # Breaking a brick scores 10 points, held as 1 in the score field. Restricted to
    # frames where the player is airborne, since a brick is broken from below.
    score = d.col("score")
    in_air = d.col("in_air")
    for frame in range(1, d.n):
        if score[frame] - score[frame - 1] == 1 and in_air[frame - 1]:
            acc.add("Block_smashed", frame)

    coins = d.col("coins_p1")
    for frame in range(1, d.n):
        delta = coins[frame] - coins[frame - 1]
        if delta > 0 or delta <= -99:   # the counter wraps at 100 and awards a life
            acc.add("Item_collected/Coin", frame)


def _level_events(acc: EventAccumulator, d: _Vars, rep_index: Optional[int]
                  ) -> Optional[int]:
    """Level_started / Level_restarted / Level_completed / Goal_card_collected.

    A level attempt can span several one-life .bk2 files, so only the first repetition at
    a given level starts it; the rest are restarts after a death.

    Returns:
        The frame of Level_completed, or None if the level was not completed.
    """
    if rep_index in (None, 0):
        acc.add("Level_started", 0)
    else:
        acc.add("Level_restarted", 0)

    # Clearing the level is signalled by a goal card being added to the inventory.
    for card_var in ("goal_cards_p1_1", "goal_cards_p1_2", "goal_cards_p1_3"):
        cards = d.col(card_var)
        for frame in range(1, d.n):
            if cards[frame] > cards[frame - 1]:
                acc.add("Level_completed", frame)
                acc.add(f"Goal_card_collected/{CARD_NAMES.get(cards[frame], cards[frame])}",
                        frame)
                return frame
    return None
