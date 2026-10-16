# `_summary.json` keys

Every repetition has a `gamelogs/*_summary.json` next to its `.bk2`. The four datasets
share one key scheme, defined in `videogames_utils.summary` (`SHARED_KEYS`,
`EXTRA_KEYS`). Keys are UpperCamelCase, like the `trial_type` vocabulary in
[`EVENT_REFERENCE.md`](EVENT_REFERENCE.md).

The per-game columns give the key each dataset used before (`same`: unchanged; `—`: the
dataset had no such key, so it is null until the generator writes it).

## Shared keys

Every summary has all of these, in this order. A value the dataset does not record is
`null`.

| Key | Description | mario | mariostars | mario3 | shinobi |
|---|---|---|---|---|---|
| `Subject` | Subject label, without the 'sub-' prefix, e.g. '01'. | same | — | — | — |
| `Session` | Session label, without the 'ses-' prefix, e.g. '004'. | — | — | — | — |
| `Run` | fMRI run of the repetition, e.g. 'run-01'. | same | same | same | — |
| `Level` | Level label, as in the BIDS 'level-' entity of the filename (e.g. 'w5l2', '1'). | `LevelFullName` | — | — | — |
| `Bk2File` | Basename of the repetition's .bk2 replay, without the extension. | same | — | — | — |
| `Duration` | Length of the repetition, in seconds at the console's native frame rate. | same | `Duration_seconds` | `Duration_seconds` | `duration` |
| `FrameCount` | Number of emulator frames in the repetition. | — | `Frame_count` | `Frame_count` | — |
| `Outcome` | How the repetition ended, from videogames_utils.events.outcome: 'cleared', 'failed/killed', 'failed/fall', 'failed/timeout', 'failed' (shinobi), 'incomplete/warp', 'incomplete/interrupted' or 'unknown'. | same | same | same | same |
| `Score` | Points scored during the repetition (shinobi's score starts at 0 in every repetition, so its final score is the same quantity). | `ScoreGained` | same | same | `end_score` |
| `LivesLost` | Lives lost during the repetition. | `Lives_lost` | `Lives_lost` | — | — |
| `HitsTaken` | Times the player was hit. | `Hits_taken` | `Hits_taken` | `Hits_taken` | — |
| `EnemiesDefeated` | Enemies the player defeated. | `Enemies_killed` | `Enemies_killed` | — | `enemies killed` |
| `IndexInRun` | 0-based position of the repetition within its run. | same | same | same | — |
| `IndexGlobal` | 0-based position of the repetition across all of the subject's sessions. | same | same | same | — |
| `IndexLevel` | 0-based count of the subject's earlier repetitions of the same level. | same | same | same | — |
| `Phase` | Phase of the protocol the repetition belongs to, e.g. 'discovery', 'practice'. | same | same | same | — |

## Game-specific keys

Written after the shared keys, in this order.

| Key | Description | mario | mariostars | mario3 | shinobi |
|---|---|---|---|---|---|
| `World` | World number, for Super Mario Bros. (NES). | same |  |  |  |
| `XTraveled` | Horizontal distance traveled in the level. | `X_Traveled` | `X_traveled` | `X_traveled` |  |
| `AverageSpeed` | XTraveled divided by Duration. | `Average_speed` | `Average_speed` | `Average_speed` |  |
| `CoinsCollected` | Coins collected. | `CoinsGained` | `Coins` | `Coins` |  |
| `PowerupsCollected` | Power-ups collected. | `Powerups_collected` | `Powerups_collected` | `Powerups_collected` |  |
| `BricksSmashed` | Bricks smashed. | `Bricks_smashed` | `Bricks_smashed` | `Bricks_smashed` |  |
| `TimerFinal` | Value of the in-game level timer on the last frame. |  | `Timer_final` | `Timer_final` |  |
| `StarsCollected` | Stars (Starman) collected. |  | `Stars_collected` | `Stars_collected` |  |
| `PlayerFormFinal` | Player form on the last frame, lowercase, e.g. 'small'. |  | `Player_form_final` | `Player_form_final` |  |
| `MaxPMeter` | Highest value reached by the P-meter. |  |  | `Max_p_meter` |  |
| `EnemiesStomped` | Enemies defeated by stomping. |  |  | `Enemies_stomped` |  |
| `FlightsActivated` | Times the player took off flying. |  |  | `Flights_activated` |  |
| `KuriboShoeAcquired` | Whether the player got Kuribo's shoe. |  |  | `Kuribo_shoe_acquired` |  |
| `HealthLost` | Health points lost. |  |  |  | `total health lost` |
| `ShurikensThrown` | Shurikens thrown. |  |  |  | `shurikens used` |

## Values

Values are unchanged. `Outcome` keeps the lowercase labels of
`videogames_utils.events.outcome` (`cleared`, `failed/killed`, ...) and `PlayerFormFinal`
its lowercase form names (`small`), unlike the UpperCamelCase `trial_type` values.

## Migration

Existing summaries are converted from the files already in the dataset, with no
emulation:

```bash
python -m videogames_utils.summary . shinobi                 # new keys + old keys
python -m videogames_utils.summary . shinobi --drop-legacy   # new keys only
```

`Subject`, `Session`, `Run`, `Level` and `Bk2File` are filled from the BIDS filename when
the summary lacks them, and `FrameCount` from the length of the `score` series in the
repetition's `_variables.json`. Everything else is a rename.

By default the old keys stay in the file after the new ones, with the same values, so
code reading `cleared`, `end_score`, `Duration_seconds`, ... keeps working for one
release. Run with `--drop-legacy` once downstream code reads the new names.

Two old keys have no new counterpart:

- **shinobi `cleared`** is `Outcome == "cleared"`.
- **mario `Level`** was the level number within the world (`"2"` for `w5l2`). `Level` now
  holds the full label, as in every other dataset and in the filename; the old number is
  the digit after `l`. Because the name is reused, this is the one key whose value changes
  in place, even when the old keys are kept.

New summaries should be built with `videogames_utils.summary.make_summary(task, ...)`,
which requires every shared key and rejects keys that are not listed for the game.
