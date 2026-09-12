"""The controlled ``trial_type`` vocabulary shared by the four CNeuroMod videogame
datasets, and the BIDS ``task-<task>_events.json`` sidecar generated from it.

The vocabulary follows ``Event-Types.pdf``. Event names are hierarchical, with ``/``
separating a category from its qualifier, e.g. ``Enemy_defeated/Stomp`` or
``Enemy_on_screen/Goomba``. Placeholders written ``{...}`` in the specification are filled
at generation time with a decoded object name.

Nothing here reads or writes a dataset; :func:`write_bids_sidecar` returns a dict that
the caller may dump wherever it wants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

#: The four task names, in the order used throughout the datasets.
TASKS = ("mario", "mariostars", "mario3", "shinobi")


@dataclass(frozen=True)
class EventType:
    """One entry in the controlled vocabulary.

    Attributes:
        name: The ``trial_type`` value, or a template containing ``{...}``.
        description: Prose definition, reused verbatim in the BIDS sidecar.
        tasks: Which tasks may emit it.
        former: Previous ``trial_type`` values that map onto this one.
        parametric: True if the event carries a ``value`` column.
        durational: True if ``duration`` is meaningful (not a point event).
    """

    name: str
    description: str
    tasks: Sequence[str]
    former: Sequence[str] = field(default_factory=tuple)
    parametric: bool = False
    durational: bool = False

    @property
    def is_template(self) -> bool:
        return "{" in self.name

    @property
    def prefix(self) -> str:
        """The part before the first ``/``, e.g. ``Enemy_defeated``."""
        return self.name.split("/", 1)[0]


ALL = ("mario", "mariostars", "mario3", "shinobi")
MARIOS = ("mario", "mariostars", "mario3")
SMB1S = ("mario", "mariostars")

VOCABULARY: List[EventType] = [
    # ---------------------------------------------------------------- player events
    EventType("Player_damaged",
              "The player is hit and loses the current power-up state (Mario games) or "
              "health (Shinobi).",
              ALL, former=("Hit/powerup_lost", "HealthLoss")),
    EventType("Player_died/Enemy",
              "The player dies after being hit by an enemy or another damaging object.",
              MARIOS, former=("Hit/life_lost", "Hit/killed")),
    EventType("Player_died/Fall",
              "The player falls into a pit and dies. `onset` is the frame the player "
              "drops below the bottom of the screen and `duration` runs to the frame "
              "the life is actually lost, about 4 s later -- the game lets the player "
              "fall out of the level before resetting.",
              MARIOS, former=("Hit/fall",), durational=True),
    EventType("Player_died/Timeout",
              "The player dies because the level timer ran out.",
              MARIOS, former=("Hit/timeout",)),
    EventType("Player_died",
              "The player loses all health or dies from an environmental hazard. "
              "`onset` is the frame health reaches zero and `duration` runs to the frame "
              "the life is actually lost, 2-6 s later, once the death animation and the "
              "fade have played.",
              ("shinobi",), durational=True),
    EventType("Life_gained", "The player collects or earns an extra life.", ALL),
    EventType("Health_gained",
              "The player collects a health item and the health bar increases.",
              ("shinobi",), former=("HealthGain",)),

    # ---------------------------------------------------------- player state events
    # One row per continuous stretch of a state, with `duration` spanning the whole
    # stretch: these describe what the player *is*, not the moment it changed. Forms
    # (Small, Super, Fire and the mario3 suits; Normal in Shinobi) are mutually exclusive
    # and together tile every frame on which the player is alive in the level -- i.e.
    # outside the Screen/Death, Screen/Level_intro, Screen/Game_over and Screen/Map
    # stretches. The other states are overlays that can co-occur with a form and with
    # each other. A row ends when the state is lost, when the player dies, or when the
    # repetition ends. They replace the Powerup_started/expired and Flight_started/expired
    # pairs.
    EventType("Player_state/Small",
              "The player is small Mario: no power-up. Together with the other form rows "
              "this covers every frame on which the player is alive in the level.",
              MARIOS, durational=True),
    EventType("Player_state/Normal",
              "The player is in Shinobi's single form. Joe Musashi has no power-up forms, "
              "so this row simply covers every frame on which the player is alive in the "
              "level (the temporary weapon upgrade is not tracked; see the README). "
              "Present for uniformity with the Mario datasets.",
              ("shinobi",), durational=True),
    EventType("Player_state/Super",
              "The player is Super (big) Mario, from the frame the mushroom is collected "
              "until hit, death or the end of the repetition.",
              MARIOS, former=("Powerup_started/Super",), durational=True),
    EventType("Player_state/Fire",
              "The player is Fire Mario (can throw fireballs).",
              MARIOS, former=("Powerup_started/Fire",), durational=True),
    EventType("Player_state/Raccoon", "The player is Raccoon Mario.",
              ("mario3",), former=("Powerup_started/Raccoon",), durational=True),
    EventType("Player_state/Frog", "The player wears the Frog suit.",
              ("mario3",), former=("Powerup_started/Frog",), durational=True),
    EventType("Player_state/Tanooki", "The player wears the Tanooki suit.",
              ("mario3",), former=("Powerup_started/Tanooki",), durational=True),
    EventType("Player_state/Hammer", "The player wears the Hammer Brothers suit.",
              ("mario3",), former=("Powerup_started/Hammer",), durational=True),
    EventType("Player_state/Star",
              "Star invincibility is active.",
              MARIOS, former=("Powerup_started/Star", "Powerup_expired/Star",
                              "Star_activated"), durational=True),
    EventType("Player_state/Hit_recovery",
              "Post-hit recovery: the player has just been damaged and blinks. In the "
              "Mario games nothing can hurt the player until it ends; in Shinobi it is "
              "the game's post-hit counter.",
              ALL, durational=True),
    EventType("Player_state/Flying",
              "The player is flying with a flight-capable suit.",
              ("mario3",), former=("Flight_started", "Flight_expired",
                                   "Flight_activated"), durational=True),
    EventType("Player_state/Statue", "Tanooki Mario is in statue form.",
              ("mario3",), durational=True),
    EventType("Player_state/Kuribo_shoe", "The player rides Kuribo's Shoe.",
              ("mario3",), durational=True),

    # ------------------------------------------------------------ item/block events
    EventType("Item_on_screen/{item_type}",
              "A coin, mushroom, flower, star or extra life is visible on screen. "
              "`duration` spans the time it is visible.",
              MARIOS, former=("Item_appeared/{item_type}",), durational=True),
    EventType("Item_collected/Coin",
              "The player collects a coin.", MARIOS, former=("Coin_collected",)),
    EventType("Item_collected/Powerup",
              "The player collects a mushroom, flower, star or other power-up item.",
              MARIOS, former=("Powerup_collected",)),
    EventType("Item_collected/{item_type}",
              "The player collects a health item, weapon upgrade, extra life or other "
              "collectible.", ("shinobi",)),
    EventType("Block_smashed",
              "The player destroys a breakable brick block from below.",
              MARIOS, former=("Brick_smashed",)),

    # ----------------------------------------------------------------- enemy events
    EventType("Enemy_on_screen/{enemy_type}",
              "A specific enemy type is visible on screen. `duration` runs from the "
              "frame it becomes visible until it leaves the screen or is defeated; an "
              "enemy that leaves and returns produces two separate events.",
              MARIOS, former=("Enemy_appeared/{enemy_type}",), durational=True),
    EventType("Enemy_attack/{enemy_type}",
              "An enemy begins an attack, such as firing a projectile or emerging from "
              "a pipe.", MARIOS),
    EventType("Enemy_defeated/Stomp/{enemy_type}",
              "The player defeats an enemy by jumping on it.",
              MARIOS, former=("Kill/stomp",)),
    EventType("Enemy_defeated/Projectile/{enemy_type}",
              "The player defeats an enemy with a fireball or other projectile.",
              MARIOS, former=("Kill/impact",)),
    EventType("Enemy_defeated/Shell/{enemy_type}",
              "The player defeats an enemy using a moving shell.",
              MARIOS, former=("Kill/kick",)),
    EventType("Enemy_defeated",
              "The player defeats an enemy. Shinobi has no RAM map for enemy types, so "
              "this event is untyped and is inferred from score increments.",
              ("shinobi",), former=("Kill",)),

    # ----------------------------------------------------- projectile / shell events
    EventType("Projectile_on_screen/{projectile_type}",
              "A fireball, Bullet Bill, hammer or other moving projectile is visible on "
              "screen. `duration` spans the time it is visible.",
              MARIOS, former=("Projectile_appeared/{projectile_type}",), durational=True),
    EventType("Projectile_appeared/Shuriken",
              "The player throws a shuriken. A point event: Shinobi has no RAM map for "
              "object positions, so the projectile cannot be tracked on screen.",
              ("shinobi",)),
    EventType("Shell_started_moving",
              "A shell begins moving after being kicked or otherwise activated.", MARIOS),

    # ---------------------------------------------------------- environment events
    EventType("Pipe_entered", "The player enters a pipe.", MARIOS),
    EventType("Checkpoint_reached",
              "The player passes the level checkpoint that changes the restart position.",
              SMB1S),
    EventType("Flagpole_visible",
              "The flagpole at the end of the level becomes visible on screen.", SMB1S),
    EventType("Castle_visible",
              "The end-of-level castle becomes visible on screen.", SMB1S),
    EventType("Timer_warning_started",
              "The game begins warning the player that little time remains.", MARIOS),

    # ---------------------------------------------------------- mario3-only events
    EventType("P-Switch_started",
              "The player activates a P-Switch, temporarily changing nearby bricks and "
              "coins.", ("mario3",), former=("P-Switch_activated",), durational=True),
    EventType("P-Switch_expired", "The temporary P-Switch effect ends.", ("mario3",)),
    EventType("Goal_card_visible",
              "The end-of-level roulette card comes on screen. Its face cycles mushroom / "
              "flower / star until it is touched, so it is untyped here; the type taken is "
              "in Goal_card_collected.", ("mario3",),
              former=("Goal_card_visible/{card_type}",)),
    EventType("Goal_card_collected/{card_type}",
              "The player touches and collects the end-of-level goal card.", ("mario3",)),
    EventType("Auto_scroll_started",
              "The level begins scrolling independently of the player.", ("mario3",)),

    # --------------------------------------------------------------- shinobi events
    EventType("Weapon_powerup_started/{powerup_type}",
              "The player receives a temporary or persistent weapon upgrade.",
              ("shinobi",), durational=True),
    EventType("Weapon_powerup_expired/{powerup_type}",
              "A temporary weapon upgrade ends or is lost.", ("shinobi",)),

    # ----------------------------------------------------------------- level events
    EventType("Level_started", "A new level or gameplay attempt begins.", ALL),
    EventType("Level_restarted", "The level restarts after the player dies.", MARIOS),
    EventType("Level_completed",
              "The player successfully finishes the level. In Shinobi this is the start "
              "of the end-of-level fade that closes the recording; it is missed in the "
              "few cleared repetitions whose recording stopped before the fade.",
              ALL, former=("Level_complete",)),
    EventType("Level_exited/Warp",
              "The player left the level through a warp-zone pipe rather than finishing "
              "it. Not part of Event-Types.pdf; retained from the previous vocabulary.",
              SMB1S, former=("Warp",)),

    # ---------------------------------------------------------------- action events
    # Not covered by Event-Types.pdf. Normalized across games at the user's request, with
    # the raw button preserved in the `button` column.
    EventType("Action/Left", "The player holds the left direction.", ALL,
              former=("LEFT",), durational=True),
    EventType("Action/Right", "The player holds the right direction.", ALL,
              former=("RIGHT",), durational=True),
    EventType("Action/Up", "The player holds the up direction.", ALL,
              former=("UP",), durational=True),
    EventType("Action/Down", "The player holds the down direction (duck / crouch).", ALL,
              former=("DOWN",), durational=True),
    EventType("Action/Jump", "The player presses the jump button.", ALL,
              former=("JUMP",), durational=True),
    EventType("Action/Run", "The player presses the run / throw button (Mario games).",
              MARIOS, former=("RUN/THROW",), durational=True),
    EventType("Action/Attack", "The player presses the attack button (Shinobi).",
              ("shinobi",), former=("HIT",), durational=True),
    EventType("Action/Ninjutsu", "The player presses the ninjutsu button (Shinobi).",
              ("shinobi",), former=("NINJUTSU",), durational=True),
    EventType("Action/Other",
              "The player presses a button with no documented function in this game "
              "(e.g. L/R on the SNES pad in Super Mario All-Stars). The raw button is in "
              "the `button` column.", ALL, durational=True),
    EventType("Action/Start", "The player presses START (pauses the game).", ALL,
              former=("START",), durational=True),
    EventType("Action/Select", "The player presses SELECT / MODE.", ALL,
              former=("SELECT", "MODE"), durational=True),

    # ---------------------------------------------------------------- screen events
    # What the game is showing, as opposed to what the player is doing. One durational
    # row per continuous stretch; the Screen/* rows of a repetition partition it, so
    # exactly one is active at any frame. Gameplay is the complement of the others.
    EventType("Screen/Gameplay",
              "The player controls the character in the level. The Screen/* rows of a "
              "repetition partition it: exactly one is active at any frame, and this is "
              "the complement of all the others.",
              ALL, durational=True),
    EventType("Screen/Level_intro",
              "The level's title card: Super Mario Bros.' black 'WORLD x-y / Mario x n' "
              "screen, shown when the level starts and again after each death before "
              "play resumes. mario3 and shinobi have no intro screen.",
              SMB1S, durational=True),
    EventType("Screen/Death",
              "The death sequence: from the frame the player dies, or drops off the "
              "bottom of the screen, to the end of the death animation and the freeze "
              "that follows it. The player has no control.",
              ALL, durational=True),
    EventType("Screen/Level_end",
              "The end-of-level sequence after the level is completed: the flagpole "
              "slide, walk into the castle and time bonus (SMB1); the goal card and "
              "COURSE CLEAR screen (mario3); the ROUND CLEAR bonus tally (shinobi). The "
              "player has no control.",
              ALL, durational=True),
    EventType("Screen/Transition",
              "A transition inside a level with no player control: pipe, vine or door "
              "travel and the black or fading screen while the next area loads (SMB1 "
              "pipes, vines and the exit from a bonus area; mario3 pipes and doors; "
              "shinobi section fades), and the fade back into play after a shinobi "
              "death.",
              ALL, durational=True),
    EventType("Screen/Game_over",
              "The GAME OVER screen after the last life is lost: mario3's world map with "
              "the GAME OVER dialog, shinobi's GAME OVER / CONTINUE screen. Recordings "
              "were meant to stop at the death, so this only appears where one ran on.",
              ("mario3", "shinobi"), durational=True),
    EventType("Screen/Map",
              "The SMB3 world map, in the rare recording that ran on past the level and "
              "back to the map with lives remaining.",
              ("mario3",), durational=True),

    # -------------------------------------------------------------- container event
    EventType("gym-retro_game",
              "One repetition of gameplay (one .bk2 file). This is the container row "
              "that carries `stim_file`; all other events fall inside its window.", ALL,
              durational=True),
]

BY_NAME: Dict[str, EventType] = {e.name: e for e in VOCABULARY}

#: Events removed from the vocabulary, and why. Kept here so the change is documented
#: rather than silently absent, and so a reader of an older file can look the name up.
RETIRED: Dict[str, str] = {
    "Enemy_disappeared/{enemy_type}":
        "Redundant. It was a point event on the last visible frame of an "
        "Enemy_on_screen track that was not claimed by a defeat, so it is exactly "
        "`onset + duration` of that row -- verified on 6620 of 6620 rows, matching on "
        "integer frames. Read it as an Enemy_on_screen row with no Enemy_defeated at "
        "its end.",
}

#: Former trial_type -> new trial_type. Templated targets keep their placeholder, since
#: the qualifier is only known at generation time.
FORMER_TO_NEW: Dict[str, str] = {}
for _e in VOCABULARY:
    for _f in _e.former:
        FORMER_TO_NEW.setdefault(_f, _e.name)


def _matches(template: str, candidate: str) -> bool:
    """True if ``candidate`` fits ``template``, treating ``{...}`` as one free segment.

    Segment-aware rather than prefix-based, because names now go three deep:
    ``Enemy_defeated/Stomp/Goomba`` has to match
    ``Enemy_defeated/Stomp/{enemy_type}`` but not ``Enemy_defeated/Shell/{enemy_type}``.
    """
    want, got = template.split("/"), candidate.split("/")
    if len(want) != len(got):
        return False
    return all(w.startswith("{") or w == g for w, g in zip(want, got))


def is_valid(trial_type: str, task: Optional[str] = None) -> bool:
    """True if ``trial_type`` is in the vocabulary (and allowed for ``task``)."""
    entry = BY_NAME.get(trial_type)
    if entry is None:
        for cand in VOCABULARY:
            if cand.is_template and _matches(cand.name, trial_type):
                entry = cand
                break
    if entry is None:
        return False
    return task is None or task in entry.tasks


def for_task(task: str) -> List[EventType]:
    """Vocabulary entries a given task may emit."""
    return [e for e in VOCABULARY if task in e.tasks]


#: Descriptions for the columns carried by the annotated events files.
COLUMN_DESCRIPTIONS: Dict[str, dict] = {
    "onset": {"Description": "Onset of the event, in seconds from the start of the run.",
              "Units": "s"},
    "duration": {"Description": "Duration of the event in seconds. Zero for point events.",
                 "Units": "s"},
    "trial_type": {"Description": "Event type, from a controlled vocabulary shared by the "
                                  "CNeuroMod videogame datasets."},
    "level": {"Description": "Level identifier of the repetition the event belongs to."},
    "frame_start": {"Description": "Index of the first emulator frame of the event, "
                                   "relative to the start of its repetition."},
    "frame_stop": {"Description": "Index of the last emulator frame of the event, "
                                  "relative to the start of its repetition."},
    "button": {"Description": "Raw controller button underlying an Action/* event. "
                              "n/a for all other events."},
    "stim_file": {"Description": "Path to the .bk2 replay of the repetition. Set on the "
                                 "gym-retro_game row only; every other event falls inside "
                                 "exactly one of those windows. Per-repetition metadata "
                                 "(phase, IndexInRun, IndexGlobal, IndexLevel, Outcome) "
                                 "lives in the matching gamelogs/*_summary.json."},
}


def write_bids_sidecar(task: str) -> dict:
    """Build the ``task-<task>_events.json`` contents for one task."""
    levels = {}
    for entry in for_task(task):
        name = entry.name
        if entry.is_template:
            parts = name.split("/")
            placeholders = [p for p in parts if p.startswith("{")]
            name = "/".join("*" if p.startswith("{") else p for p in parts)
            desc = (f"{entry.description} The * stands for "
                    + " then ".join(p.strip("{}") for p in placeholders) + ".")
        else:
            desc = entry.description
        if entry.former:
            desc += " Formerly: " + ", ".join(repr(f) for f in entry.former) + "."
        levels[name] = desc

    sidecar = {k: dict(v) for k, v in COLUMN_DESCRIPTIONS.items()}
    sidecar["trial_type"]["Levels"] = levels
    return sidecar
