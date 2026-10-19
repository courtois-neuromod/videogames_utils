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

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class EventType:
    """One entry in the controlled vocabulary.

    Attributes:
        name: The ``trial_type`` value, or a template containing ``{...}``.
        description: Prose definition, reused verbatim in the BIDS sidecar.
        former: Previous ``trial_type`` values that map onto this one. Kept for reference
            only: they are not published in the sidecar or the README.
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


#: The event families shared by the games: a description, and the name of each qualifier
#: that follows the family in an event name (``EnemyDefeated/<method>/<enemy_type>``).
#: A qualifier written as a ``{placeholder}`` in the vocabulary is named after it. A game
#: can add or override families with ``Game.families``.
FAMILIES: Dict[str, dict] = {
    "Action": {"Description": "The player holds a controller button. `duration` spans the "
                              "hold and the raw button is in the `button` column.",
               "Qualifiers": ("role",)},
    "EnemyAttack": {"Description": "An enemy begins an attack.",
                    "Qualifiers": ("enemy_type",)},
    "EnemyDefeated": {"Description": "The player defeats an enemy.",
                      "Qualifiers": ("method", "enemy_type")},
    "EnemyOnScreen": {"Description": "An enemy is visible on screen. `duration` runs until "
                                     "it leaves the screen or is defeated.",
                      "Qualifiers": ("enemy_type",)},
    "ItemCollected": {"Description": "The player collects an item.",
                      "Qualifiers": ("item_type",)},
    "ItemOnScreen": {"Description": "An item is visible on screen. `duration` spans the "
                                    "time it is visible.",
                     "Qualifiers": ("item_type",)},
    "LevelExited": {"Description": "The player leaves the level without finishing it.",
                    "Qualifiers": ("exit",)},
    "PlayerDied": {"Description": "The player loses a life.",
                   "Qualifiers": ("cause",)},
    "PlayerState": {"Description": "What the player is, one row per continuous stretch. The "
                                   "forms are mutually exclusive and together cover every "
                                   "frame on which the player is alive in the level; the "
                                   "other states are overlays that can co-occur with a "
                                   "form.",
                    "Qualifiers": ("state",)},
    "ProjectileAppeared": {"Description": "A projectile appears.",
                           "Qualifiers": ("projectile_type",)},
    "ProjectileOnScreen": {"Description": "A projectile is visible on screen. `duration` "
                                          "spans the time it is visible.",
                           "Qualifiers": ("projectile_type",)},
    "Screen": {"Description": "What the game is showing, as opposed to what the player is "
                              "doing. The Screen/* rows of a repetition partition it: "
                              "exactly one is active at any frame.",
               "Qualifiers": ("screen",)},
}


def humanize(name: str) -> str:
    """``GreenKoopa`` -> ``Green Koopa``: the default description of a decoded type."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)


def wildcard_name(name: str) -> str:
    """A vocabulary entry's name with its ``{...}`` placeholders written ``*``."""
    return "/".join("*" if part.startswith("{") else part for part in name.split("/"))


#: Descriptions for the columns carried by the annotated events files.
COLUMN_DESCRIPTIONS: Dict[str, dict] = {
    "onset": {"Description": "Onset of the event, in seconds from the start of the run.",
              "Units": "s"},
    "duration": {"Description": "Duration of the event in seconds. Zero for point events.",
                 "Units": "s"},
    "trial_type": {"Description": "Event type: a family, optionally followed by qualifiers "
                                  "separated by `/`, e.g. `EnemyDefeated/Stomp/Goomba`. "
                                  "`Levels` lists every value; `EventTypes` describes "
                                  "them hierarchically, one entry per family with the "
                                  "format of its names and the values each qualifier "
                                  "takes."},
    "frame_start": {"Description": "Index of the first emulator frame of the event, "
                                   "relative to the start of its repetition."},
    "frame_stop": {"Description": "Index of the last emulator frame of the event, "
                                  "relative to the start of its repetition."},
    "button": {"Description": "Raw controller button underlying an Action/* event. "
                              "n/a for all other events."},
    "stim_file": {"Description": "Path to the .bk2 replay of the repetition. Set on the "
                                 "Repetition row only; every other event falls inside "
                                 "exactly one of those windows. Per-repetition metadata "
                                 "(phase, IndexInRun, IndexGlobal, IndexLevel, Outcome) "
                                 "lives in the matching gamelogs/*_summary.json. "
                                 "'Missing file' marks a repetition whose .bk2 was "
                                 "lost; its row is kept, with no events inside it."},
}


def event_types(vocabulary: Sequence[EventType], trial_types: Iterable[str] = (),
                families: Optional[Mapping[str, dict]] = None,
                type_descriptions: Optional[Mapping[str, str]] = None) -> Dict[str, dict]:
    """The game's events, described hierarchically, one entry per family.

    An event with no qualifier (``LevelStarted``) is just described. A family with
    qualifiers gets its description, the ``Format`` of its names, and one list per
    qualifier of the values it takes::

        "EnemyDefeated": {
            "Description": "The player defeats an enemy.",
            "Format": "EnemyDefeated/<method>/<enemy_type>",
            "method": {"Stomp": "...", "Projectile": "...", "Shell": "..."},
            "enemy_type": {"Goomba": "Goomba.", ...},
        }

    A qualifier filled at generation time with a decoded name lists the values present in
    ``trial_types``. Families, and the values within each list, are in alphabetical order.
    """
    families = {**FAMILIES, **(families or {})}
    type_descriptions = type_descriptions or {}
    present = sorted(set(map(str, trial_types)))
    by_family: Dict[str, list] = {}
    for entry in vocabulary:
        by_family.setdefault(entry.name.split("/", 1)[0], []).append(entry)

    tree: Dict[str, dict] = {}
    for family in sorted(by_family):
        entries = by_family[family]
        bare = [e for e in entries if "/" not in e.name]
        qualified = [e for e in entries if "/" in e.name]
        if not qualified:
            tree[family] = {"Description": bare[0].description}
            continue
        spec = families.get(family, {})
        if spec.get("Description"):
            description = spec["Description"]
        elif len(qualified) == 1:
            description = qualified[0].description
        else:
            raise KeyError(f"no description for the event family {family!r}; add it to "
                           "the game's families")
        node: Dict[str, object] = {"Description": description}
        formats: list = []
        lists: Dict[str, Dict[str, str]] = {}
        for entry in qualified:
            parts = entry.name.split("/")[1:]
            names = []
            for index, part in enumerate(parts):
                if part.startswith("{"):
                    name = part.strip("{}")
                    values = lists.setdefault(name, {})
                    for value in present:
                        if _matches(entry.name, value):
                            seg = value.split("/")[index + 1]
                            values[seg] = type_descriptions.get(seg, humanize(seg) + ".")
                else:
                    qualifiers = spec.get("Qualifiers", ())
                    if index >= len(qualifiers):
                        raise KeyError(f"no qualifier name for {entry.name!r}; add the "
                                       "family to the game's families")
                    name = qualifiers[index]
                    lists.setdefault(name, {})[part] = entry.description
                names.append(name)
            fmt = "/".join([family] + [f"<{n}>" for n in names])
            if fmt not in formats:
                formats.append(fmt)
        node["Format"] = formats[0] if len(formats) == 1 else formats
        for name, values in lists.items():
            node[name] = dict(sorted(values.items()))
        tree[family] = node
    return tree


def levels(vocabulary: Sequence[EventType], trial_types: Iterable[str] = (),
           type_descriptions: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """The BIDS ``Levels`` of ``trial_type``: every value, with its description.

    The vocabulary's fixed names, plus the values of its templates present in
    ``trial_types``, whose description ends with the decoded types they name. In
    alphabetical order.
    """
    type_descriptions = type_descriptions or {}
    out = {e.name: e.description for e in vocabulary if not e.is_template}
    templates = [e for e in vocabulary if e.is_template]
    for value in set(map(str, trial_types)) - set(out):
        for entry in templates:
            if _matches(entry.name, value):
                named = [f"{part.strip('{}')}: "
                         + type_descriptions.get(seg, humanize(seg) + ".")
                         for part, seg in zip(entry.name.split("/"), value.split("/"))
                         if part.startswith("{")]
                out[value] = " ".join([entry.description] + named)
                break
    return dict(sorted(out.items()))


def write_bids_sidecar(vocabulary: Sequence[EventType], trial_types: Iterable[str] = (),
                       families: Optional[Mapping[str, dict]] = None,
                       type_descriptions: Optional[Mapping[str, str]] = None) -> dict:
    """Build the ``task-<task>_events.json`` contents for a game's vocabulary.

    ``trial_type`` is described twice: under the BIDS ``Levels``, one entry per value
    present (:func:`levels`), and under ``EventTypes``, hierarchically, one entry per
    family with a list of values per qualifier (:func:`event_types`). The second is the
    readable one: a family's qualifiers combine freely
    (``EnemyDefeated/<method>/<enemy_type>``), so the first repeats each type many times.
    """
    sidecar = {k: dict(v) for k, v in COLUMN_DESCRIPTIONS.items()}
    sidecar["trial_type"]["Levels"] = levels(vocabulary, trial_types, type_descriptions)
    sidecar["trial_type"]["EventTypes"] = event_types(vocabulary, trial_types, families,
                                                      type_descriptions)
    return sidecar


def is_described(tree: Mapping[str, dict], trial_type: str) -> bool:
    """True if ``trial_type`` is covered by an :func:`event_types` tree."""
    family, *qualifiers = str(trial_type).split("/")
    node = tree.get(family)
    if node is None:
        return False
    formats = node.get("Format")
    if not qualifiers:
        return formats is None
    for fmt in [formats] if isinstance(formats, str) else formats or []:
        names = [part.strip("<>") for part in fmt.split("/")[1:]]
        if len(names) == len(qualifiers) and all(
                value in node.get(name, {}) for name, value in zip(names, qualifiers)):
            return True
    return False
