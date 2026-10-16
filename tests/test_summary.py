"""One shared _summary.json key scheme for the four datasets (issue #6)."""

import json

import pytest

from videogames_utils import summary

# Verbatim from the datasets (mario sub-01 ses-004 w5l2 rep-000, shinobi sub-01 ses-010
# run-01 level-1 rep-01).
MARIO = {"Subject": "01", "World": "5", "Level": "2", "Duration": 59.26805793316009,
         "Outcome": "failed/killed", "ScoreGained": 420, "X_Traveled": 641,
         "Average_speed": 10.815269174550846, "Lives_lost": 3, "Hits_taken": 3,
         "Enemies_killed": 2, "Powerups_collected": 0, "Bricks_smashed": 0,
         "CoinsGained": 8, "IndexInRun": 0, "Run": "run-01", "IndexGlobal": 118,
         "IndexLevel": 0, "Phase": "discovery", "LevelFullName": "w5l2",
         "Bk2File": "sub-01_ses-004_task-mario_level-w5l2_rep-000"}
MARIO_NAME = "sub-01_ses-004_task-mario_level-w5l2_rep-000_summary.json"

SHINOBI = {"duration": 166.95, "cleared": True, "Outcome": "cleared", "end_score": 28430,
           "total health lost": 1, "shurikens used": 1, "enemies killed": 29}
SHINOBI_NAME = "sub-01_ses-010_task-shinobi_run-01_level-1_rep-01_summary.json"

# Key lists from the table in issue #6.
MARIOSTARS = {"Duration_seconds": 10.0, "Frame_count": 601, "Timer_final": 390,
              "Outcome": "cleared", "Score": 100, "X_traveled": 50, "Average_speed": 5.0,
              "Lives_lost": 0, "Hits_taken": 0, "Enemies_killed": 1, "Coins": 2,
              "Powerups_collected": 0, "Stars_collected": 0, "Bricks_smashed": 0,
              "Player_form_final": "small", "IndexInRun": 1, "Run": "run-02",
              "IndexGlobal": 7, "IndexLevel": 3, "Phase": "practice"}
MARIO3 = {k: v for k, v in MARIOSTARS.items() if k not in ("Lives_lost", "Enemies_killed")}
MARIO3.update({"Max_p_meter": 6, "Enemies_stomped": 1, "Flights_activated": 0,
               "Kuribo_shoe_acquired": False})


def test_every_key_is_upper_camel_case():
    keys = list(summary.SHARED_KEYS) + [k for ks in summary.EXTRA_KEYS.values() for k in ks]
    for key in keys:
        assert key[0].isupper() and "_" not in key and " " not in key, key
    assert set(summary.KEY_DESCRIPTIONS) == set(keys)


def test_shared_keys_are_the_ones_proposed_in_the_issue():
    assert summary.SHARED_KEYS == (
        "Subject", "Session", "Run", "Level", "Bk2File", "Duration", "FrameCount",
        "Outcome", "Score", "LivesLost", "HitsTaken", "EnemiesDefeated", "IndexInRun",
        "IndexGlobal", "IndexLevel", "Phase")


@pytest.mark.parametrize("task,old", [("mario", MARIO), ("mariostars", MARIOSTARS),
                                      ("mario3", MARIO3), ("shinobi", SHINOBI)])
def test_harmonize_gives_all_four_datasets_the_same_shared_keys(task, old):
    new = summary.harmonize(old, task, keep_legacy=False)
    assert list(new) == list(summary.SHARED_KEYS) + list(summary.EXTRA_KEYS[task])


def test_harmonize_mario_values():
    new = summary.harmonize(MARIO, "mario", filename=MARIO_NAME, keep_legacy=False)
    assert new["Subject"] == "01"
    assert new["Session"] == "004"
    assert new["Run"] == "run-01"
    assert new["Level"] == "w5l2"  # the BIDS level entity, as in the filename
    assert new["World"] == "5"
    assert new["Score"] == 420
    assert new["Duration"] == MARIO["Duration"]
    assert new["EnemiesDefeated"] == 2
    assert new["CoinsCollected"] == 8
    assert new["XTraveled"] == 641
    assert new["Bk2File"] == MARIO["Bk2File"]
    assert new["FrameCount"] is None  # mario never recorded it


def test_harmonize_shinobi_fills_what_the_filename_gives():
    new = summary.harmonize(SHINOBI, "shinobi", filename=SHINOBI_NAME, keep_legacy=False)
    assert (new["Subject"], new["Session"], new["Run"], new["Level"]) == (
        "01", "010", "run-01", "1")
    assert new["Bk2File"] == "sub-01_ses-010_task-shinobi_run-01_level-1_rep-01"
    assert (new["Duration"], new["Score"], new["EnemiesDefeated"]) == (166.95, 28430, 29)
    assert (new["HealthLost"], new["ShurikensThrown"]) == (1, 1)
    # No source for these in shinobi; null rather than a guess.
    for key in ("IndexInRun", "IndexGlobal", "IndexLevel", "Phase", "HitsTaken",
                "LivesLost", "FrameCount"):
        assert new[key] is None, key


def test_frame_count_comes_from_the_variables():
    new = summary.harmonize(SHINOBI, "shinobi", filename=SHINOBI_NAME,
                            variables={"score": [0] * 10017}, keep_legacy=False)
    assert new["FrameCount"] == 10017


def test_values_are_not_recased():
    new = summary.harmonize(MARIOSTARS, "mariostars", keep_legacy=False)
    assert new["Outcome"] == "cleared"
    assert new["PlayerFormFinal"] == "small"


def test_legacy_keys_are_kept_by_default():
    new = summary.harmonize(SHINOBI, "shinobi", filename=SHINOBI_NAME)
    for key, value in SHINOBI.items():
        assert new[key] == value, key
    assert new["Duration"] == 166.95


def test_mario_legacy_level_does_not_overwrite_the_shared_level():
    # mario's old "Level" was the level number within the world ("2"); the shared
    # "Level" is the full level label. The old meaning stays readable as LevelFullName.
    new = summary.harmonize(MARIO, "mario", filename=MARIO_NAME)
    assert new["Level"] == "w5l2"
    assert new["LevelFullName"] == "w5l2"
    assert new["World"] == "5"


def test_harmonize_is_idempotent():
    once = summary.harmonize(SHINOBI, "shinobi", filename=SHINOBI_NAME)
    assert summary.harmonize(once, "shinobi", filename=SHINOBI_NAME) == once


def test_unknown_key_is_an_error():
    with pytest.raises(ValueError, match="Mystery"):
        summary.harmonize(dict(SHINOBI, Mystery=1), "shinobi")


def test_get_reads_old_and_new_files():
    old_file = SHINOBI
    new_file = summary.harmonize(SHINOBI, "shinobi", keep_legacy=False)
    for data in (old_file, new_file):
        assert summary.get(data, "Duration") == 166.95
        assert summary.get(data, "Score") == 28430
    assert summary.get(MARIO, "Score") == 420
    assert summary.get(MARIOSTARS, "Duration") == 10.0
    assert summary.get(MARIO, "FrameCount", default="n/a") == "n/a"


def test_make_summary_checks_the_keys():
    fields = {k: None for k in summary.SHARED_KEYS}
    fields.update(Outcome="cleared", ShurikensThrown=3)
    made = summary.make_summary("shinobi", **fields)
    assert list(made)[:len(summary.SHARED_KEYS)] == list(summary.SHARED_KEYS)

    with pytest.raises(ValueError, match="missing.*Session"):
        summary.make_summary("shinobi", **{k: v for k, v in fields.items()
                                           if k != "Session"})
    with pytest.raises(ValueError, match="not allowed.*StarsCollected"):
        summary.make_summary("shinobi", StarsCollected=1, **fields)


def test_harmonize_file_rewrites_in_place(tmp_path):
    path = tmp_path / SHINOBI_NAME
    path.write_text(json.dumps(SHINOBI))
    (tmp_path / SHINOBI_NAME.replace("_summary", "_variables")).write_text(
        json.dumps({"score": [0] * 5}))

    summary.harmonize_file(str(path), "shinobi")
    data = json.loads(path.read_text())
    assert data["FrameCount"] == 5
    assert data["Level"] == "1"
    assert data["cleared"] is True


def test_cli_harmonizes_every_summary_of_a_dataset(tmp_path):
    gamelogs = tmp_path / "sub-01" / "ses-010" / "gamelogs"
    gamelogs.mkdir(parents=True)
    (gamelogs / SHINOBI_NAME).write_text(json.dumps(SHINOBI))

    assert summary.main([str(tmp_path), "shinobi", "--drop-legacy"]) == 0
    data = json.loads((gamelogs / SHINOBI_NAME).read_text())
    assert "end_score" not in data and data["Score"] == 28430
