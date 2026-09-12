"""The ``Screen/*`` events: what the game is showing, as opposed to what the player is.

Every repetition is partitioned into stretches labelled with one of the constants below,
and one durational ``Screen/<label>`` row is emitted per stretch, so exactly one is
active at any frame. Which RAM signals produce the labels is game-specific and lives in
each generator; this module only holds the labels, the row emission and the derived
"alive" mask that the ``Player_state`` form rows are restricted to.
"""

from __future__ import annotations

from typing import List, Sequence

from .emit import EventAccumulator
from .spans import constant_runs

#: The player controls the character in the level.
GAMEPLAY = "Gameplay"
#: The level's title card (SMB1's black "WORLD x-y / Mario x n" screen).
LEVEL_INTRO = "Level_intro"
#: The death sequence, from the death (or the drop off screen) to the end of the
#: animation and the freeze that follows it.
DEATH = "Death"
#: The end-of-level sequence after the level is completed.
LEVEL_END = "Level_end"
#: A transition inside a level with no player control: pipe / vine / door travel and the
#: black or fading screen while a new area loads.
TRANSITION = "Transition"
#: The GAME OVER screen after the last life is lost.
GAME_OVER = "Game_over"
#: The world map (SMB3), when a recording runs on past the level.
MAP = "Map"

#: Labels during which the player is not alive in the level, so no form row applies.
NOT_ALIVE = frozenset({LEVEL_INTRO, DEATH, GAME_OVER, MAP})


def fill(labels: List[str], start: int, stop: int, label: str) -> None:
    """Set ``labels[start..stop]`` (inclusive) to ``label``."""
    for frame in range(max(start, 0), min(stop, len(labels) - 1) + 1):
        labels[frame] = label


def emit(acc: EventAccumulator, labels: Sequence[str]) -> None:
    """One ``Screen/<label>`` row per maximal run of a label."""
    for start, stop, label in constant_runs(labels):
        acc.add(f"Screen/{label}", start, stop)


def alive_mask(labels: Sequence[str]) -> List[bool]:
    """True on frames where a ``Player_state`` form row may exist."""
    return [label not in NOT_ALIVE for label in labels]
