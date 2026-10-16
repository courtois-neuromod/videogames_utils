"""One key scheme for the per-repetition ``gamelogs/*_summary.json`` files.

The four ``generate_replays.py`` scripts build their summaries with :func:`make_summary`,
so their keys cannot drift apart. Existing files are converted in place, without
emulation:

    python -m videogames_utils.summary /path/to/shinobi shinobi [--drop-legacy]

The old keys are kept next to the new ones unless ``--drop-legacy`` is given. Values are
not changed. Keys and migration: ``docs/SUMMARY_KEYS.md``.
"""

from __future__ import annotations

import argparse
import json
import os.path as op
import sys
from glob import glob

SHARED_KEYS = (
    "Subject", "Session", "Run", "Level", "Bk2File", "Duration", "FrameCount",
    "Outcome", "Score", "LivesLost", "HitsTaken", "EnemiesDefeated", "IndexInRun",
    "IndexGlobal", "IndexLevel", "Phase",
)

_SMB1_EXTRAS = ("XTraveled", "AverageSpeed", "CoinsCollected", "PowerupsCollected",
                "BricksSmashed")
_SNES_SMB3_EXTRAS = ("TimerFinal", "XTraveled", "AverageSpeed", "CoinsCollected",
                     "PowerupsCollected", "StarsCollected", "BricksSmashed",
                     "PlayerFormFinal")

EXTRA_KEYS = {
    "mario": ("World",) + _SMB1_EXTRAS,
    "mariostars": _SNES_SMB3_EXTRAS,
    "mario3": _SNES_SMB3_EXTRAS + ("MaxPMeter", "EnemiesStomped", "FlightsActivated",
                                   "KuriboShoeAcquired"),
    "shinobi": ("HealthLost", "ShurikensThrown"),
}

#: Old key -> new key, per dataset. None: no new counterpart (mario's old ``Level`` is
#: the number within the world, shinobi's ``cleared`` is ``Outcome == "cleared"``).
LEGACY_KEYS = {
    "mario": {
        "Level": None, "LevelFullName": "Level", "ScoreGained": "Score",
        "X_Traveled": "XTraveled", "Average_speed": "AverageSpeed",
        "Lives_lost": "LivesLost", "Hits_taken": "HitsTaken",
        "Enemies_killed": "EnemiesDefeated", "Powerups_collected": "PowerupsCollected",
        "Bricks_smashed": "BricksSmashed", "CoinsGained": "CoinsCollected",
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
        "duration": "Duration", "cleared": None, "end_score": "Score",
        "total health lost": "HealthLost", "shurikens used": "ShurikensThrown",
        "enemies killed": "EnemiesDefeated",
    },
}


def make_summary(task: str, **fields) -> dict:
    """Summary dict for ``task``: every shared key is required (None if unknown), the
    task's extras are optional, anything else raises ``ValueError``."""
    missing = [k for k in SHARED_KEYS if k not in fields]
    if missing:
        raise ValueError(f"{task} summary is missing shared keys: {', '.join(missing)}")
    keys = SHARED_KEYS + EXTRA_KEYS[task]
    unknown = [k for k in fields if k not in keys]
    if unknown:
        raise ValueError(f"keys not allowed for {task}: {', '.join(unknown)}")
    return {k: fields.get(k) for k in keys}


def harmonize(old: dict, task: str, filename: str, variables: dict = None,
              keep_legacy: bool = True) -> dict:
    """Convert an old summary to the shared keys.

    ``Subject``, ``Session``, ``Run``, ``Level`` and ``Bk2File`` missing from the summary
    are taken from the BIDS entities of ``filename``; ``FrameCount`` from the length of
    ``score`` in ``variables`` (the repetition's ``_variables.json``).
    """
    legacy = LEGACY_KEYS[task]
    unknown = [k for k in old if k not in legacy and k not in SHARED_KEYS + EXTRA_KEYS[task]]
    if unknown:
        raise ValueError(f"unknown {task} summary keys: {', '.join(unknown)}")

    fields = {legacy.get(k, k): v for k, v in old.items()}
    fields.pop(None, None)

    stem = op.basename(filename).replace("_summary.json", "")
    entities = dict(part.split("-", 1) for part in stem.split("_") if "-" in part)
    from_name = {"Subject": entities.get("sub"), "Session": entities.get("ses"),
                 "Run": "run-" + entities["run"] if "run" in entities else None,
                 "Level": entities.get("level"), "Bk2File": stem}
    for key in SHARED_KEYS:
        if fields.get(key) is None:
            fields[key] = from_name.get(key)
    if fields["FrameCount"] is None and variables and "score" in variables:
        fields["FrameCount"] = len(variables["score"])

    new = make_summary(task, **fields)
    if keep_legacy:
        new.update({k: v for k, v in old.items() if k not in new})
    return new


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset_dir")
    ap.add_argument("task", choices=tuple(EXTRA_KEYS))
    ap.add_argument("--drop-legacy", action="store_true",
                    help="write the new keys only")
    args = ap.parse_args(argv)
    paths = sorted(glob(op.join(args.dataset_dir, "sub-*", "ses-*", "gamelogs",
                                "*_summary.json")))
    for path in paths:
        with open(path) as handle:
            old = json.load(handle)
        variables = None
        var_path = path.replace("_summary.json", "_variables.json")
        if op.exists(var_path):
            with open(var_path) as handle:
                variables = json.load(handle)
        new = harmonize(old, args.task, path, variables, keep_legacy=not args.drop_legacy)
        with open(path, "w") as handle:
            json.dump(new, handle)
    print(f"harmonized {len(paths)} summaries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
