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


@pytest.mark.parametrize("task,old,name", [
    ("mario", MARIO, MARIO_NAME), ("mariostars", MARIOSTARS, MARIO_NAME),
    ("mario3", MARIO3, MARIO_NAME), ("shinobi", SHINOBI, SHINOBI_NAME)])
def test_all_four_datasets_get_the_same_shared_keys(task, old, name):
    new = summary.harmonize(old, task, name, keep_legacy=False)
    assert list(new) == list(summary.SHARED_KEYS) + list(summary.EXTRA_KEYS[task])


def test_mario_values():
    new = summary.harmonize(MARIO, "mario", MARIO_NAME, keep_legacy=False)
    assert (new["Subject"], new["Session"], new["Run"]) == ("01", "004", "run-01")
    assert new["Level"] == "w5l2"  # the BIDS level entity, not the old "2"
    assert new["World"] == "5"
    assert (new["Score"], new["EnemiesDefeated"], new["CoinsCollected"]) == (420, 2, 8)
    assert new["Bk2File"] == MARIO["Bk2File"]
    assert new["FrameCount"] is None  # mario never recorded it


def test_shinobi_values():
    new = summary.harmonize(SHINOBI, "shinobi", SHINOBI_NAME, keep_legacy=False)
    assert (new["Subject"], new["Session"], new["Run"], new["Level"]) == (
        "01", "010", "run-01", "1")
    assert new["Bk2File"] == "sub-01_ses-010_task-shinobi_run-01_level-1_rep-01"
    assert (new["Duration"], new["Score"], new["EnemiesDefeated"]) == (166.95, 28430, 29)
    assert (new["HealthLost"], new["ShurikensThrown"]) == (1, 1)
    # No source for these in shinobi: null rather than a guess.
    for key in ("IndexInRun", "IndexGlobal", "IndexLevel", "Phase", "HitsTaken",
                "LivesLost", "FrameCount"):
        assert new[key] is None, key


def test_frame_count_comes_from_the_variables():
    new = summary.harmonize(SHINOBI, "shinobi", SHINOBI_NAME,
                            variables={"score": [0] * 10017})
    assert new["FrameCount"] == 10017


def test_values_are_not_recased():
    new = summary.harmonize(MARIOSTARS, "mariostars", MARIO_NAME)
    assert (new["Outcome"], new["PlayerFormFinal"]) == ("cleared", "small")


def test_old_keys_are_kept_by_default():
    new = summary.harmonize(SHINOBI, "shinobi", SHINOBI_NAME)
    assert {k: new[k] for k in SHINOBI} == SHINOBI
    new = summary.harmonize(MARIO, "mario", MARIO_NAME)
    assert new["Level"] == "w5l2"  # the one old key whose value changes
    assert new["LevelFullName"] == "w5l2"


@pytest.mark.parametrize("keep_legacy", [True, False])
def test_converting_twice_changes_nothing(keep_legacy):
    for task, old, name in (("mario", MARIO, MARIO_NAME), ("shinobi", SHINOBI, SHINOBI_NAME)):
        once = summary.harmonize(old, task, name, keep_legacy=keep_legacy)
        assert summary.harmonize(once, task, name, keep_legacy=keep_legacy) == once


def test_unknown_key_is_an_error():
    with pytest.raises(ValueError, match="Mystery"):
        summary.harmonize(dict(SHINOBI, Mystery=1), "shinobi", SHINOBI_NAME)


def test_make_summary_checks_the_keys():
    fields = dict.fromkeys(summary.SHARED_KEYS)
    made = summary.make_summary("shinobi", ShurikensThrown=3, **fields)
    assert list(made) == list(summary.SHARED_KEYS) + ["HealthLost", "ShurikensThrown"]

    with pytest.raises(ValueError, match="missing.*Session"):
        summary.make_summary("shinobi", **{k: None for k in fields if k != "Session"})
    with pytest.raises(ValueError, match="not allowed.*StarsCollected"):
        summary.make_summary("shinobi", StarsCollected=1, **fields)


def test_cli_rewrites_a_dataset_in_place(tmp_path):
    gamelogs = tmp_path / "sub-01" / "ses-010" / "gamelogs"
    gamelogs.mkdir(parents=True)
    (gamelogs / SHINOBI_NAME).write_text(json.dumps(SHINOBI))
    (gamelogs / SHINOBI_NAME.replace("_summary", "_variables")).write_text(
        json.dumps({"score": [0] * 5}))

    assert summary.main([str(tmp_path), "shinobi", "--drop-legacy"]) == 0
    data = json.loads((gamelogs / SHINOBI_NAME).read_text())
    assert (data["Score"], data["FrameCount"], data["Level"]) == (28430, 5, "1")
    assert "end_score" not in data
