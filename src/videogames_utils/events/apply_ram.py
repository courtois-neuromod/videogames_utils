"""Merge verified RAM candidates into a dataset's ``stimuli/<Game>/data.json``.

Only candidates that have passed the verification harness belong here. Run with
``--dry-run`` first; the script prints a diff of what it would add and never removes or
rewrites an existing entry.

    python -m videogames_utils.events.apply_ram /path/to/mario --dry-run
    python -m videogames_utils.events.apply_ram /path/to/mario
"""

from __future__ import annotations

import argparse
import json
import os.path as op
import sys

from . import ram

#: dataset directory basename -> (game, verified candidate list)
VERIFIED = {
    "mario": ("SuperMarioBros-Nes", ram.SMB1_CANDIDATES),
    "mario3": ("SuperMarioBros3-Nes", ram.SMB3_CANDIDATES + ram.SMB3_UNVERIFIED),
    "mariostars": ("SuperMarioAllStars-Snes", ram.SMAS_CANDIDATES),
    "shinobi": ("ShinobiIIIReturnOfTheNinjaMaster-Genesis", ram.SHINOBI_CANDIDATES),
}

#: Existing data.json keys whose names are wrong, with the disassembly's actual symbol.
#: The addresses are correct, so the keys are kept as aliases (renaming them would break
#: the shipped generate_annotations.py); this only records the truth for documentation.
MISLABELLED = {
    "mariostars": {
        "player_powerup": "($0578) NOT the power-up state -- holds unrelated values such "
                          "as 82 and 107; use player_status ($0756)",
        "star_power_timer": "($0553) NOT the star timer -- holds constants, never counts "
                            "down; use star_timer ($07AF)",
    },
    "mario3": {
        "killed": "Map_ReturnStatus ($0713) - NOT a kill flag; unused by the generators",
        "mario_form": "Player_QueueSuit ($0578) - queued suit change, not the current form",
        "invisibility_timer": "Player_FlashInv ($0552) - post-hit flashing, not invisibility",
        "invincibility_timer": "Player_StarInv ($0553) - correct meaning, star invincibility",
        "stomp_counter": "Kill_Tally ($05F4)",
        "timer_subframe": "Level_TimerTick ($05F1)",
        "object_set": "Level_Tileset ($070A)",
        "p_meter": "Player_Power ($03DD)",
        "powerup": "Player_Suit ($00ED) - the actual current form",
    },
}


def apply(dataset_dir: str, dry_run: bool = False) -> int:
    name = op.basename(op.abspath(dataset_dir.rstrip("/")))
    if name not in VERIFIED:
        print(f"nothing to apply for {name!r} (verified games: {sorted(VERIFIED)})")
        return 0
    game, candidates = VERIFIED[name]
    path = op.join(dataset_dir, "stimuli", game, "data.json")
    if not op.exists(path):
        print(f"ERROR: {path} does not exist")
        return 1

    with open(path) as f:
        data = json.load(f)
    info = data.setdefault("info", {})

    added, conflicts, already = [], [], []
    for cand in candidates:
        entry = cand.as_json_entry()
        if cand.name in info:
            if info[cand.name] == entry:
                already.append(cand.name)
            else:
                conflicts.append((cand.name, info[cand.name], entry))
            continue
        info[cand.name] = entry
        added.append(cand)

    print(f"{name}/{game}: {len(info) - len(added)} existing keys, {len(added)} to add")
    for cand in added:
        print(f"  + {cand.name:<26} {cand.address:>6} ({cand.dtype})  {cand.symbol}")
    for key in already:
        print(f"  = {key} already present and identical")
    for key, old, new in conflicts:
        print(f"  ! {key} EXISTS with a different value: {old} vs {new} - left untouched")

    if dry_run:
        print("\n(dry run, nothing written)")
        return 0
    if not added:
        print("\nnothing to write")
        return 0

    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"\nwrote {path} ({len(info)} variables total)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dataset_dir")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    return apply(args.dataset_dir, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
