"""Render a dataset's ``code/annotations/README.md`` from the vocabulary and the dataset.

The event table is built from :mod:`vocabulary`, so it cannot fall behind the code, and
every entry carries the number of rows it actually has in the dataset, so an entry that
is defined but never produced is stated as such rather than silently listed. Prose that
is specific to one game (how each signal was verified, what is known to be missing)
lives in :data:`NOTES` below and is reviewed by hand.

    python -m videogames_utils.events.docs /path/to/mario mario
    python -m videogames_utils.events.docs /path/to/mario mario -o /tmp/README.md

The full cross-game reference (RAM addresses, values, validation figures for every
event) is ``docs/EVENT_REFERENCE.md`` in the videogames_utils repository.
"""

from __future__ import annotations

import argparse
import collections
import os.path as op
import sys
from glob import glob
from typing import Dict, Optional

import pandas as pd

from . import vocabulary
from .emit import TASK_FRAME_RATES

REFERENCE_URL = ("https://github.com/courtois-neuromod/videogames_utils/blob/main/docs/"
                 "EVENT_REFERENCE.md")

GAME_NAMES = {
    "mario": "Super Mario Bros. (NES)",
    "mariostars": "Super Mario All-Stars: Super Mario Bros. (SNES)",
    "mario3": "Super Mario Bros. 3 (NES)",
    "shinobi": "Shinobi III: Return of the Ninja Master (Genesis)",
}

#: Why a vocabulary entry allowed for the task produces no row in the dataset. Entries
#: absent from here that have zero rows are reported as "never occurred". Keep this
#: honest: "not implemented" means the pipeline has no detector for it.
NOT_EMITTED: Dict[str, Dict[str, str]] = {
    "mario": {
        "Player_died/Timeout": "implemented (death routine with the timer at 0); no "
                               "subject ever ran out of time",
        "Item_collected/Powerup": "not implemented; the pickup is the first frame of the "
                                  "`Player_state/Super`, `Fire` or `Star` row it starts "
                                  "(a 1-up is `Life_gained`)",
        "Enemy_attack/{enemy_type}": "not implemented (no verified RAM signal)",
        "Projectile_on_screen/{projectile_type}": "implemented for Bowser's flames (id "
                                                  "0x15) but the flame never passes the "
                                                  "visibility test; not yet resolved",
        "Shell_started_moving": "not implemented for SMB1",
        "Checkpoint_reached": "deliberately not emitted: `HalfwayPage` is written at a "
                              "death past the midpoint, not at the crossing",
        "Level_restarted": "not applicable: an SMB1 repetition spans all its lives, and "
                           "each restart is a `Screen/Level_intro` row",
        "Action/Other": "the NES pad has no extra buttons",
        "Action/Start": "never pressed",
        "Action/Select": "never pressed",
    },
    "mario3": {
        "Player_state/Hammer": "never obtained",
        "Item_collected/Powerup": "not implemented; the pickup is the first frame of the "
                                  "`Player_state/*` row it starts",
        "Enemy_attack/{enemy_type}": "not implemented (no verified RAM signal)",
        "Enemy_defeated/Shell/{enemy_type}": "the object state table does not attribute "
                                             "a shell kill to the shell; kicks are "
                                             "reported as `Shell_started_moving`",
        "Pipe_entered": "not implemented; pipe and door travel is the `Screen/Transition` "
                        "row",
        "Timer_warning_started": "not implemented for SMB3",
        "Action/Other": "the NES pad has no extra buttons",
        "Action/Start": "never pressed",
        "Action/Select": "never pressed",
    },
    "shinobi": {
        "Player_state/Hit_recovery": "requires the `hit_timer` variable, present only in "
                                     "sidecars replayed with the current `data.json`",
        "Weapon_powerup_expired/{powerup_type}": "not implemented (no RAM signal for the "
                                                 "weapon upgrade)",
        "Action/Other": "never pressed",
        "Action/Start": "never pressed",
        "Action/Select": "never pressed",
    },
}
NOT_EMITTED["mariostars"] = {
    **{k: v for k, v in NOT_EMITTED["mario"].items() if k != "Action/Other"},
}

#: Per-game accuracy notes, in Markdown. Reviewed by hand when the generator changes.
NOTES: Dict[str, str] = {
    "mario": """\
- `Player_state/*` rows are read straight from the RAM: `PlayerStatus` ($0756,
  `player_status`) for the form, which the game writes on the very frame a mushroom or
  flower is collected or a hit lands; `StarInvincibleTimer` ($079F, `star_timer`) for
  `Star`; and `InjuryTimer` ($079E, `injury_timer`) for `Hit_recovery`, the ~3.7 s after
  a hit during which enemy contact is ignored. Form rows (Small included) exist only on
  the frames where the player is alive in the level, so they are cut at a death and
  resume once the title card has gone. Validation recounts every row from the same
  series by a different route.
- `Screen/*` rows come from the engine state (`GameEngineSubroutine`, $000E,
  `player_state`): 0/1/2/3/7 are transitions, 4/5 the end-of-level sequence, 11/6 the
  death, everything else play. A transition block at the start of the repetition or
  right after a death is the title card (`Screen/Level_intro`). Every boundary was
  checked on rendered emulator frames; a fall death is dated from `Player_Y_HighPos`
  leaving 1 (exact).
- Enemy visibility uses the game's own `EnemyOffscrBitsMasked` ($03D8). Validated against
  independently computed screen-relative positions: when it is zero the enemy is inside
  the visible band on 97.5-98.9% of frames, when non-zero on 0.0-1.5%. Piranha Plants
  count only while out of their pipe (from the per-slot Y), Bullet Bills only while in
  flight (the cannon shares their id and does not move).
- Enemy types come from `Enemy_ID` ($0016) decoded through the object table in
  1wErt3r's SMB disassembly. Cross-checked against mariostars on the levels played on
  both consoles.
- `Level_completed` uses the engine's `PlayerEndLevel` routine, so it also fires on
  castle levels where there is no flagpole. `Level_exited/Warp` is detected from the
  world/area index changing while the level never ended.
- Recordings end at the life loss on the last life, so there is no game-over screen in
  this dataset. START is never pressed, so there is no pause.
""",
    "mariostars": """\
- Super Mario All-Stars reuses Super Mario Bros.' object id table verbatim, verified
  empirically (`sprite_number_*` values decode to PiranhaPlant / Goomba / BuzzyBeetle /
  GreenKoopa / Paratroopa / FlagpoleFlag on the levels where those appear), and the same
  engine enumeration in `player_action_state`. The same generator therefore serves both
  `mario` and `mariostars`; see the mario README for the shared logic.
- Visibility uses bit 0 of `sprite_onscreen_flag_*`. This port exposes no per-sprite
  coordinates, so the Piranha Plant and Bullet Bill refinements of the NES do not apply:
  a plant counts for its whole cycle and roughly 10% of Bullet Bill tracks are cannons.
- **Three RAM variables were added** for the `Player_state/*` rows: `player_status`
  ($0756), `injury_timer` ($07AE) and `star_timer` ($07AF). The shipped `player_powerup`
  ($0578) and `star_power_timer` ($0553) do **not** hold what their names say (values
  such as 82 and 107, constants rather than a countdown) and are no longer read.
- The title card (`Screen/Level_intro`) is invisible to the engine variable on this port,
  which idles at 8 while the card is up. It is read from `OperMode_Task` ($0772), decoded
  out of the shipped `reset` variable (a 4-byte BCD read at $0771 whose second byte pair
  is that task; 1 = card, 3 = game routines). The port fades in and out around the card,
  so those boundaries are within ~30 frames (0.5 s).
- A fall death is dated from the frame the level timer stops ticking, plus half a tick;
  validated on the NES against the exact crossing: 100% within 24 frames (0.4 s).
- The SNES pad maps B to jump and Y to run. `L` and `R` are recorded as `Action/Other`
  with the raw button preserved.
""",
    "mario3": """\
- `Player_state/*` rows are read straight from the RAM: `Player_Suit` ($00ED,
  `powerup`) for the form, `Player_StarInv` (`invincibility_timer`) for `Star`,
  `Player_FlashInv` (`invisibility_timer`) for `Hit_recovery`, `Player_FlyTime`
  (`flight_timer`) for `Flying`, plus `statue_timer` and `kuribo_shoe`. A hit as Fire or
  in a suit drops the player to Super (verified: every 2 -> 1 transition coincides with
  `player_suit_lost`), so one form row ends and the next starts on the same frame.
- `Screen/*`: there is no title card (a repetition opens in the level with a short
  fade-in). The death is `Player_IsDying` != 0; area transitions are `Player_HaltGame`
  >= 128 while the next area loads, plus the pipe-entry hold before it; the end of a
  level runs from the goal card to the end of the recording (card animation and COURSE
  CLEAR). All checked on rendered frames.
- **148 of 4063 recordings run on past a game-over death** into the world map with the
  GAME OVER dialog (median 18 s, up to 4 min), and one (sub-06 ses-010 w6l4 rep-000)
  returns to the map and records a second attempt. These are `Screen/Game_over` and
  `Screen/Map` rows, excluded from the alive frames, so they are easy to find and drop.
  They are recording overruns, not gameplay.
- Object ids come from `Level_ObjectID` ($0671), decoded through the 170-entry `OBJ_*`
  table generated from captainsouthbird's SMB3 disassembly. Visibility uses the game's
  own `Objects_SprHVis` / `Objects_SprVVis` flags, validated against the object's level
  position minus the scroll: horizontally inside the band on 99.9% of accepted frames,
  vertically on 100.0%.
- Cause of death comes from `Player_IsDying` ($00F1), which states it directly
  (1 = enemy, 2 = dropped off screen, 3 = time up).
- `Goal_card_visible` is the roulette card object (`OBJ_ENDLEVELCARD`, 0x41), which is
  on screen 0.5-4 s before it is taken. It is untyped because its face cycles; the type
  taken is in `Goal_card_collected`.
- A level attempt spans up to three one-life `.bk2` files. The first gets
  `Level_started`, the rest `Level_restarted`.
""",
    "shinobi": """\
Shinobi is the least well characterised of the four datasets. There is **no public RAM
map** for Shinobi III, and roughly half the entries in its `data.json` are
background/palette scratch with no gameplay meaning.

- `Enemy_defeated` is inferred from score increments and is **untyped**. Only the
  documented enemy values (200, 300, 400, 500) are counted. Other increments occur (1000
  is common, as are 250/350/700/3000/5000) but nothing available attributes them, so they
  are deliberately not counted rather than guessed at -- roughly a third of scoring events
  are therefore not represented.
- There are **no** `Enemy_on_screen` events: nothing in the current RAM map locates
  enemy objects.
- `Screen/*` and `Level_completed` come from the (misnamed) `blackScreen` byte at
  $FF0024, a screen-mode value: 40 is the scroll lock of an enemy wave (ordinary play,
  not a black screen); 22 or 62 then 20 is a section fade; 20 from the frame health
  reaches 0 is the death animation, 21 the life loss and the fade back in; 21 with lives
  negative is the GAME OVER screen; and a fade of 22 or 62 running to the end of the
  recording is the end of a completed level (the ROUND CLEAR tally on level 1). That
  trailing fade is present in 519 of 536 cleared repetitions and in none of the 130
  failed ones; the 17 misses are recordings that stopped inside the last enemy wave. All
  checked on rendered frames.
- `Player_died` is durational: `lives` only drops 2-6 s after the fact, once the death
  animation and fade have played, so `onset` is the frame health reached 0 and
  `duration` runs to the life loss.
- `Player_state/Normal` exists so that every dataset has a form for every frame of play;
  Shinobi has no forms. The temporary weapon upgrade is not tracked, and
  `Weapon_powerup_started/Ninjutsu` marks a ninjutsu cast (8 repetitions), not a weapon
  upgrade.
- `Player_state/Hit_recovery` uses `hit_timer`, a RAM variable added to `data.json`
  ($FF4165; the Genesis core exposes work RAM word-swapped, so the byte seen at raw
  offset $FF4164 is declared one higher). It is set to 80 or 64 on the frame health drops
  and counts down once per frame while the player flashes; only stretches that begin on
  a `Player_damaged` are emitted. Rows appear once the sidecars have been replayed with
  that variable.
""",
}


def census(dataset_dir: str) -> collections.Counter:
    """trial_type counts over every annotated events file of the dataset."""
    counts: collections.Counter = collections.Counter()
    for path in glob(op.join(dataset_dir, "sub-*", "ses-*", "func",
                             "*_desc-annotated_events.tsv")):
        counts.update(pd.read_csv(path, sep="\t", usecols=["trial_type"])["trial_type"])
    return counts


def _rows_for(entry: vocabulary.EventType, counts: collections.Counter) -> int:
    if entry.is_template:
        return sum(n for t, n in counts.items() if vocabulary._matches(entry.name, str(t)))
    return counts.get(entry.name, 0)


def _event_table(task: str, counts: collections.Counter) -> str:
    lines = ["| Event | Rows | Description |", "|---|---|---|"]
    for entry in vocabulary.for_task(task):
        n = _rows_for(entry, counts)
        if n:
            rows = f"{n:,}"
        else:
            reason = NOT_EMITTED.get(task, {}).get(entry.name, "never occurred in this dataset")
            rows = f"*none: {reason}*"
        kind = " (durational)" if entry.durational else ""
        lines.append(f"| `{entry.name}`{kind} | {rows} | {entry.description} |")
    return "\n".join(lines)


def _renamed_table(task: str) -> str:
    lines = ["| Former | Now |", "|---|---|"]
    for old, new in sorted(vocabulary.FORMER_TO_NEW.items()):
        if task in vocabulary.BY_NAME[new].tasks:
            lines.append(f"| `{old}` | `{new}` |")
    for old, why in vocabulary.RETIRED.items():
        lines.append(f"| `{old}` | *(dropped)* |")
    return "\n".join(lines)


def render(task: str, counts: collections.Counter) -> str:
    n_reps = counts.get("gym-retro_game", 0)
    n_rows = sum(counts.values())
    n_types = len(counts)
    fs = TASK_FRAME_RATES[task]
    return f"""# Annotated event files - {task}

`generate_annotations.py` turns the per-frame RAM dumps written by
`code/replays/generate_replays.py` (`gamelogs/*_variables.json`) into BIDS event files at
`sub-*/ses-*/func/*_desc-annotated_events.tsv` for {GAME_NAMES[task]}.

The event logic is shared by all four CNeuroMod videogame datasets and lives in
[`videogames_utils.events`](https://github.com/courtois-neuromod/videogames_utils); this
directory only holds the command-line front end. The machine-readable vocabulary is
published as `task-{task}_events.json` at the dataset root, and the cross-game reference
with every RAM address, value and validation figure is
[`docs/EVENT_REFERENCE.md`]({REFERENCE_URL}) in that repository.

This dataset: **{n_reps:,} repetitions**, **{n_rows:,} event rows**, **{n_types}
distinct `trial_type` values**. This file is generated by
`python -m videogames_utils.events.docs . {task}`; the row counts are a census of the
files as they stand.

## Usage

```bash
python code/annotations/generate_annotations.py -d . --overwrite --validate
```

`--validate` runs the schema checks and the RAM-derived invariants afterwards and exits
non-zero on any error. The replay sidecars must exist first
(`code/replays/generate_replays.py`).

## Columns

| Column | Description |
|---|---|
| `trial_type` | Event type, from the controlled vocabulary below. |
| `level` | Level of the repetition the event belongs to. |
| `onset` | Seconds from the start of the fMRI run. |
| `duration` | Seconds. 0 for point events. |
| `frame_start` | First emulator frame of the event, relative to its repetition. |
| `frame_stop` | Last emulator frame of the event, relative to its repetition. |
| `button` | Raw controller button behind an `Action/*` event; empty otherwise. |
| `stim_file` | Path to the repetition's `.bk2` replay. Set on the `gym-retro_game` row only. |

Onsets are computed at the console's true frame rate ({fs:.6f} Hz, read from the
emulator core), not 60.0 Hz. Per-repetition metadata (`phase`, `IndexInRun`,
`IndexGlobal`, `IndexLevel`, `Outcome`) is not repeated on event rows; it lives in the
repetition's `gamelogs/*_summary.json`, keyed by the `stim_file` of the container row.

## How to read the rows

- **Point events** have `duration` 0 and mark a moment (a coin, a death, a completion).
- **Durational events** span a stretch of frames: object visibility, button holds,
  player states and screens.
- **`gym-retro_game`** is the container: one row per repetition (one `.bk2`), carrying
  `stim_file`. Every other row falls inside exactly one container window.
- **`Screen/*`** rows partition every repetition: they are contiguous, do not overlap and
  cover it from its first frame to its last, so exactly one is active at any frame.
  `Screen/Gameplay` is the complement of the non-play screens (title card, death
  sequence, end-of-level sequence, transitions, game over).
- **`Player_state/*` form rows** (Small, Super, Fire and the SMB3 suits; Normal in
  Shinobi) are mutually exclusive and tile the frames on which the player is alive in the
  level, i.e. outside `Screen/Death`, `Screen/Level_intro`, `Screen/Game_over` and
  `Screen/Map`. The other `Player_state/*` rows (Star, Hit_recovery, Flying, ...) are
  overlays that can co-occur with a form.
- Names are hierarchical: the part before the first `/` is the family. `{{...}}` in the
  table below is filled at generation time with a decoded object name, e.g.
  `Enemy_on_screen/Goomba`.

## Event types

Every entry of the vocabulary this game may emit, with the number of rows it has in the
dataset. An entry with no rows says why.

{_event_table(task, counts)}

## Accuracy notes

{NOTES[task]}
## Renamed from the previous vocabulary

Earlier releases used different `trial_type` names. Analyses filtering on the former
names need updating; the mapping for this game is:

{_renamed_table(task)}

The former `Powerup_started/*` and `Powerup_expired/*` point events became the
durational `Player_state/*` rows (the onset of `Player_state/Super` is the old
`Powerup_started/Super`, the end of `Player_state/Star` the old `Powerup_expired/Star`),
and `Powerup_started/Small`, emitted on a hit, is the start of a `Player_state/Small`
row.

## Validation

```bash
python -m videogames_utils.events.validate_cli check . {task}
```

`check` runs two layers: the schema and controlled-vocabulary checks (V0), and invariants
recomputed straight from `_variables.json` by a different route than the generator used
(V1): coin counts against the coin counter, deaths against the lives counter, level
completion against the summary outcome, enemy track bookkeeping, `Screen/*` rows
partitioning each repetition and agreeing with the deaths and completions, form rows
tiling the alive frames, and frame-range bounds. `mario` and `mariostars` can also be
compared level by level (`cross-port`), since they are the same game on two consoles.

A human video review measures precision and recall per event type:

```python
from videogames_utils.events import review
review.build_review_set('.', '{task}', out_dir='/tmp/review', per_type=50)
# rate the clips in /tmp/review/review.html, then:
review.score_reviews('/tmp/review/ratings.json', '/tmp/review/manifest.json')
```
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset_dir")
    ap.add_argument("task", choices=vocabulary.TASKS)
    ap.add_argument("-o", "--output", default=None,
                    help="where to write; default code/annotations/README.md in the dataset")
    args = ap.parse_args(argv)
    counts = census(args.dataset_dir)
    text = render(args.task, counts)
    out = args.output or op.join(args.dataset_dir, "code", "annotations", "README.md")
    with open(out, "w") as handle:
        handle.write(text)
    print(f"wrote {out} ({sum(counts.values()):,} rows counted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
