"""The controlled ``trial_type`` vocabulary of the CNeuroMod videogame datasets, and the
BIDS ``task-<task>_events.json`` sidecar generated from it.

Each game declares the entries it may emit (``Game.vocabulary``, see :mod:`.game`); this
module holds what they share. The vocabulary follows ``Event-Types.pdf``. Event names are hierarchical, with ``/``
separating a category from its qualifier, e.g. ``EnemyDefeated/Stomp`` or
``EnemyOnScreen/Goomba``. Placeholders written ``{...}`` in the specification are filled
at generation time with a decoded object name.

Nothing here reads or writes a dataset; :func:`write_bids_sidecar` returns a dict that
the caller may dump wherever it wants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Sequence


@dataclass(frozen=True)
class EventType:
    """One entry in the controlled vocabulary.

    Attributes:
        name: The ``trial_type`` value, or a template containing ``{...}``.
        description: Prose definition, reused verbatim in the BIDS sidecar.
        former: Previous ``trial_type`` values that map onto this one.
        parametric: True if the event carries a ``value`` column.
        durational: True if ``duration`` is meaningful (not a point event).
    """

    name: str
    description: str
    former: Sequence[str] = field(default_factory=tuple)
    parametric: bool = False
    durational: bool = False

    @property
    def is_template(self) -> bool:
        return "{" in self.name

    @property
    def prefix(self) -> str:
        """The part before the first ``/``, e.g. ``EnemyDefeated``."""
        return self.name.split("/", 1)[0]


#: Events removed from the vocabulary, and why. Kept here so the change is documented
#: rather than silently absent, and so a reader of an older file can look the name up.
RETIRED: Dict[str, str] = {
    "Enemy_disappeared/{enemy_type}":
        "Redundant. It was a point event on the last visible frame of an "
        "EnemyOnScreen track that was not claimed by a defeat, so it is exactly "
        "`onset + duration` of that row -- verified on 6620 of 6620 rows, matching on "
        "integer frames. Read it as an EnemyOnScreen row with no EnemyDefeated at "
        "its end.",
}

def former_to_new(vocabulary: Sequence[EventType]) -> Dict[str, str]:
    """Former trial_type -> new trial_type.

    Templated targets keep their placeholder, since the qualifier is only known at
    generation time.
    """
    mapping: Dict[str, str] = {}
    for entry in vocabulary:
        for former in entry.former:
            mapping.setdefault(former, entry.name)
    return mapping


def _matches(template: str, candidate: str) -> bool:
    """True if ``candidate`` fits ``template``, treating ``{...}`` as one free segment.

    Segment-aware rather than prefix-based, because names now go three deep:
    ``EnemyDefeated/Stomp/Goomba`` has to match
    ``EnemyDefeated/Stomp/{enemy_type}`` but not ``EnemyDefeated/Shell/{enemy_type}``.
    """
    want, got = template.split("/"), candidate.split("/")
    if len(want) != len(got):
        return False
    return all(w.startswith("{") or w == g for w, g in zip(want, got))


def is_valid(trial_type: str, vocabulary: Sequence[EventType]) -> bool:
    """True if ``trial_type`` is one of the ``vocabulary`` entries, or fits a template."""
    return any(entry.name == trial_type
               or (entry.is_template and _matches(entry.name, trial_type))
               for entry in vocabulary)


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
                                 "lives in the matching gamelogs/*_summary.json. "
                                 "'Missing file' marks a repetition whose .bk2 was "
                                 "lost; its row is kept, with no events inside it."},
}


def write_bids_sidecar(vocabulary: Sequence[EventType]) -> dict:
    """Build the ``task-<task>_events.json`` contents for a game's vocabulary."""
    levels = {}
    for entry in vocabulary:
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
