"""One key scheme for the per-repetition ``gamelogs/*_summary.json`` files.

Each of the four ``code/replays/generate_replays.py`` scripts wrote its own keys
(``Duration`` / ``Duration_seconds`` / ``duration``, ``ScoreGained`` / ``Score`` /
``end_score``, ...). This module holds the single shared set, in UpperCamelCase like the
``trial_type`` vocabulary, plus the game-specific extras, so the scripts can build their
summaries through :func:`make_summary` and cannot drift apart again.

Existing files are converted without emulation:

    python -m videogames_utils.summary /path/to/shinobi shinobi

:func:`harmonize` keeps the old keys next to the new ones by default, so code reading the
old names (``cleared``, ``end_score``, ...) keeps working for one release; pass
``--drop-legacy`` once downstream code reads the new names. :func:`get` reads a value
from a file in either scheme.

Values are left as they are: ``Outcome`` keeps the lowercase labels of
:mod:`videogames_utils.events.outcome` (``cleared``, ``failed/killed``, ...) and
``PlayerFormFinal`` its lowercase form names, unlike the UpperCamelCase ``trial_type``
values. Keys missing from a dataset are written as null rather than guessed.
"""

from __future__ import annotations

import argparse
import json
import os.path as op
import sys
from glob import glob
from typing import Dict, Optional, Sequence

#: Keys every summary carries, in this order, for all four games.
SHARED_KEYS = (
    "Subject", "Session", "Run", "Level", "Bk2File", "Duration", "FrameCount",
    "Outcome", "Score", "LivesLost", "HitsTaken", "EnemiesDefeated", "IndexInRun",
    "IndexGlobal", "IndexLevel", "Phase",
)

_SMB1_EXTRAS = ("XTraveled", "AverageSpeed", "CoinsCollected", "PowerupsCollected",
                "BricksSmashed")
_SNES_NES3_EXTRAS = ("TimerFinal", "XTraveled", "AverageSpeed", "CoinsCollected",
                     "PowerupsCollected", "StarsCollected", "BricksSmashed",
                     "PlayerFormFinal")

#: Game-specific keys, after the shared ones, in this order.
EXTRA_KEYS: Dict[str, Sequence[str]] = {
    "mario": ("World",) + _SMB1_EXTRAS,
    "mariostars": _SNES_NES3_EXTRAS,
    "mario3": _SNES_NES3_EXTRAS + ("MaxPMeter", "EnemiesStomped", "FlightsActivated",
                                   "KuriboShoeAcquired"),
    "shinobi": ("HealthLost", "ShurikensThrown"),
}

KEY_DESCRIPTIONS: Dict[str, str] = {
    "Subject": "Subject label, without the 'sub-' prefix, e.g. '01'.",
    "Session": "Session label, without the 'ses-' prefix, e.g. '004'.",
    "Run": "fMRI run of the repetition, e.g. 'run-01'.",
    "Level": "Level label, as in the BIDS 'level-' entity of the filename (e.g. 'w5l2', "
             "'1').",
    "Bk2File": "Basename of the repetition's .bk2 replay, without the extension.",
    "Duration": "Length of the repetition, in seconds at the console's native frame rate.",
    "FrameCount": "Number of emulator frames in the repetition.",
    "Outcome": "How the repetition ended, from videogames_utils.events.outcome: "
               "'cleared', 'failed/killed', 'failed/fall', 'failed/timeout', 'failed' "
               "(shinobi), 'incomplete/warp', 'incomplete/interrupted' or 'unknown'.",
    "Score": "Points scored during the repetition (shinobi's score starts at 0 in every "
             "repetition, so its final score is the same quantity).",
    "LivesLost": "Lives lost during the repetition.",
    "HitsTaken": "Times the player was hit.",
    "EnemiesDefeated": "Enemies the player defeated.",
    "IndexInRun": "0-based position of the repetition within its run.",
    "IndexGlobal": "0-based position of the repetition across all of the subject's "
                   "sessions.",
    "IndexLevel": "0-based count of the subject's earlier repetitions of the same level.",
    "Phase": "Phase of the protocol the repetition belongs to, e.g. 'discovery', "
             "'practice'.",
    "World": "World number, for Super Mario Bros. (NES).",
    "XTraveled": "Horizontal distance traveled in the level.",
    "AverageSpeed": "XTraveled divided by Duration.",
    "CoinsCollected": "Coins collected.",
    "PowerupsCollected": "Power-ups collected.",
    "StarsCollected": "Stars (Starman) collected.",
    "BricksSmashed": "Bricks smashed.",
    "TimerFinal": "Value of the in-game level timer on the last frame.",
    "PlayerFormFinal": "Player form on the last frame, lowercase, e.g. 'small'.",
    "MaxPMeter": "Highest value reached by the P-meter.",
    "EnemiesStomped": "Enemies defeated by stomping.",
    "FlightsActivated": "Times the player took off flying.",
    "KuriboShoeAcquired": "Whether the player got Kuribo's shoe.",
    "HealthLost": "Health points lost.",
    "ShurikensThrown": "Shurikens thrown.",
}

#: Old key -> shared key, per dataset. mario's old ``Level`` (the level number within
#: the world, e.g. '2') is not here: the shared ``Level`` is the full label, which mario
#: kept as ``LevelFullName``; the old number is the digit after 'l' in it.
LEGACY_KEYS: Dict[str, Dict[str, str]] = {
    "mario": {
        "LevelFullName": "Level", "ScoreGained": "Score", "X_Traveled": "XTraveled",
        "Average_speed": "AverageSpeed", "Lives_lost": "LivesLost",
        "Hits_taken": "HitsTaken", "Enemies_killed": "EnemiesDefeated",
        "Powerups_collected": "PowerupsCollected", "Bricks_smashed": "BricksSmashed",
        "CoinsGained": "CoinsCollected",
    },
    "mariostars": {
        "Duration_seconds": "Duration", "Frame_count": "FrameCount",
        "Timer_final": "TimerFinal", "X_traveled": "XTraveled",
        "Average_speed": "AverageSpeed", "Lives_lost": "LivesLost",
        "Hits_taken": "HitsTaken", "Enemies_killed": "EnemiesDefeated",
        "Coins": "CoinsCollected", "Powerups_collected": "PowerupsCollected",
        "Stars_collected": "StarsCollected", "Bricks_smashed": "BricksSmashed",
        "Player_form_final": "PlayerFormFinal",
    },
    "mario3": {
        "Duration_seconds": "Duration", "Frame_count": "FrameCount",
        "Timer_final": "TimerFinal", "X_traveled": "XTraveled",
        "Average_speed": "AverageSpeed", "Hits_taken": "HitsTaken",
        "Coins": "CoinsCollected", "Powerups_collected": "PowerupsCollected",
        "Stars_collected": "StarsCollected", "Bricks_smashed": "BricksSmashed",
        "Player_form_final": "PlayerFormFinal", "Max_p_meter": "MaxPMeter",
        "Enemies_stomped": "EnemiesStomped", "Flights_activated": "FlightsActivated",
        "Kuribo_shoe_acquired": "KuriboShoeAcquired",
    },
    "shinobi": {
        "duration": "Duration", "end_score": "Score", "total health lost": "HealthLost",
        "shurikens used": "ShurikensThrown", "enemies killed": "EnemiesDefeated",
    },
}

#: Old keys with no shared counterpart: dropped by --drop-legacy, kept otherwise.
#: shinobi's ``cleared`` is ``Outcome == "cleared"``.
DERIVED_LEGACY_KEYS: Dict[str, Sequence[str]] = {
    "mario": ("Level",),
    "mariostars": (),
    "mario3": (),
    "shinobi": ("cleared",),
}


def make_summary(task: str, **fields) -> dict:
    """Build a summary dict for ``task`` with the shared key order.

    Every shared key must be given (None where the dataset has no value). Extras for the
    task are optional and default to None; any other key raises ``ValueError``.
    """
    missing = [k for k in SHARED_KEYS if k not in fields]
    if missing:
        raise ValueError(f"{task} summary is missing shared keys: {', '.join(missing)}")
    extras = EXTRA_KEYS[task]
    unknown = [k for k in fields if k not in SHARED_KEYS and k not in extras]
    if unknown:
        raise ValueError(f"keys not allowed for {task}: {', '.join(unknown)}")
    return {k: fields.get(k) for k in tuple(SHARED_KEYS) + tuple(extras)}


def _entities(filename: str) -> Dict[str, str]:
    stem = op.basename(filename).replace("_summary.json", "").replace(".bk2", "")
    entities = {"stem": stem}
    for part in stem.split("_"):
        if "-" in part:
            key, value = part.split("-", 1)
            entities[key] = value
    return entities


def harmonize(old: dict, task: str, filename: Optional[str] = None,
              variables: Optional[dict] = None, keep_legacy: bool = True) -> dict:
    """Convert a summary in any dataset's old scheme to the shared one.

    Args:
        old: The summary as read from disk (old or already harmonized).
        task: The BIDS task label.
        filename: The summary's (or .bk2's) path, to fill ``Subject``, ``Session``,
            ``Run``, ``Level`` and ``Bk2File`` from the BIDS entities when the summary
            lacks them.
        variables: The repetition's ``_variables.json``, to fill ``FrameCount`` from the
            length of its ``score`` series when the summary lacks it.
        keep_legacy: Also keep the old keys, after the new ones, with their values.
    """
    legacy = LEGACY_KEYS[task]
    derived = DERIVED_LEGACY_KEYS[task]
    known = set(SHARED_KEYS) | set(EXTRA_KEYS[task]) | set(legacy) | set(derived)
    unknown = [k for k in old if k not in known]
    if unknown:
        raise ValueError(f"unknown {task} summary keys: {', '.join(unknown)}")

    fields = {k: v for k, v in old.items()
              if (k in SHARED_KEYS or k in EXTRA_KEYS[task]) and k not in derived}
    for old_key, new_key in legacy.items():
        if old_key in old:
            fields[new_key] = old[old_key]

    if filename is not None:
        entities = _entities(filename)
        from_name = {"Subject": entities.get("sub"), "Session": entities.get("ses"),
                     "Run": f"run-{entities['run']}" if "run" in entities else None,
                     "Level": entities.get("level"), "Bk2File": entities["stem"]}
        for key, value in from_name.items():
            if fields.get(key) is None:
                fields[key] = value
    if fields.get("FrameCount") is None and variables and variables.get("score"):
        fields["FrameCount"] = len(variables["score"])

    for key in SHARED_KEYS:
        fields.setdefault(key, None)
    new = make_summary(task, **fields)
    if keep_legacy:
        for key, value in old.items():
            if key not in new:
                new[key] = value
    return new


def get(data: dict, key: str, default=None):
    """Read shared or extra ``key`` from a summary in the new or any old scheme."""
    if key == "Level" and "LevelFullName" in data:
        return data["LevelFullName"]  # an old mario file, whose "Level" meant the number
    if key in data:
        return data[key]
    for mapping in LEGACY_KEYS.values():
        for old_key, new_key in mapping.items():
            if new_key == key and old_key in data:
                return data[old_key]
    return default


def harmonize_file(path: str, task: str, keep_legacy: bool = True) -> dict:
    """Rewrite one ``_summary.json`` in place in the shared scheme; returns the result."""
    with open(path) as handle:
        old = json.load(handle)
    variables = None
    var_path = path.replace("_summary.json", "_variables.json")
    if op.exists(var_path):
        with open(var_path) as handle:
            variables = json.load(handle)
    new = harmonize(old, task, filename=path, variables=variables,
                    keep_legacy=keep_legacy)
    with open(path, "w") as handle:
        json.dump(new, handle)
    return new


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset_dir")
    ap.add_argument("task", choices=tuple(EXTRA_KEYS))
    ap.add_argument("--drop-legacy", action="store_true",
                    help="write the new keys only, without the old ones")
    args = ap.parse_args(argv)
    paths = sorted(
        glob(op.join(args.dataset_dir, "sub-*", "ses-*", "gamelogs", "*_summary.json"))
        + glob(op.join(args.dataset_dir, "sub-*", "ses-*", "beh", "*_summary.json")))
    for path in paths:
        harmonize_file(path, args.task, keep_legacy=not args.drop_legacy)
    print(f"harmonized {len(paths)} summaries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
