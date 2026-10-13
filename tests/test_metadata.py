"""collect_bk2_files: run and position in run for each replay (issue #1)."""

import os.path as op

import pytest

from videogames_utils.metadata import _positions_in_runs, collect_bk2_files

EVENTS_HEADER = "trial_type\tonset\tlevel\tstim_file\n"


@pytest.fixture(autouse=True)
def _clear_cache():
    _positions_in_runs.cache_clear()
    yield
    _positions_in_runs.cache_clear()


def _write_session(root, sub, ses, runs, gamelogs="gamelogs"):
    """runs: {run: [bk2 basenames in play order]}. Creates the .bk2 files and events.tsv."""
    ses_dir = root / f"sub-{sub}" / f"ses-{ses}"
    (ses_dir / gamelogs).mkdir(parents=True)
    (ses_dir / "func").mkdir()
    for run, names in runs.items():
        lines = [EVENTS_HEADER]
        onset = 0.0
        for name in names:
            (ses_dir / gamelogs / name).write_bytes(b"")
            rel = f"sub-{sub}/ses-{ses}/{gamelogs}/{name}"
            lines.append(f"gym-retro_game\t{onset}\tx\t{rel}\n")
            lines.append(f"questionnaire-answer\t{onset + 1}\tx\t\n")
            onset += 100
        events = ses_dir / "func" / f"sub-{sub}_ses-{ses}_task-x_run-{run}_events.tsv"
        events.write_text("".join(lines))


def _by_name(files):
    return {op.basename(f["bk2_file"]): f for f in files}


def test_mario_names_take_run_and_position_from_events(tmp_path):
    p = "sub-01_ses-001_task-mario_level-"
    _write_session(tmp_path, "01", "001", {
        "01": [p + "w1l1_rep-000.bk2", p + "w1l1_rep-001.bk2", p + "w1l2_rep-000.bk2"],
        "02": [p + "w1l2_rep-001.bk2", p + "w1l1_rep-002.bk2"],
    })
    got = _by_name(collect_bk2_files(str(tmp_path)))

    assert {k: (v["run"], v["bk2_idx"]) for k, v in got.items()} == {
        p + "w1l1_rep-000.bk2": ("01", 0),
        p + "w1l1_rep-001.bk2": ("01", 1),
        p + "w1l2_rep-000.bk2": ("01", 2),
        p + "w1l2_rep-001.bk2": ("02", 0),
        p + "w1l1_rep-002.bk2": ("02", 1),
    }


def test_only_first_replay_of_each_run_has_index_zero(tmp_path):
    # The replay rule: skip_first_step applies to the first bk2 of each run only.
    p = "sub-01_ses-001_task-mario_level-"
    _write_session(tmp_path, "01", "001", {
        "01": [p + f"w1l1_rep-00{i}.bk2" for i in range(4)],
        "02": [p + f"w1l1_rep-00{i}.bk2" for i in range(4, 7)],
    })
    first = [f for f in collect_bk2_files(str(tmp_path)) if f["bk2_idx"] == 0]
    assert sorted(op.basename(f["bk2_file"]) for f in first) == [
        p + "w1l1_rep-000.bk2", p + "w1l1_rep-004.bk2"]


def test_shinobi_names_keep_their_run_and_get_a_position(tmp_path):
    p = "sub-01_ses-002_task-shinobi_run-01_level-"
    _write_session(tmp_path, "01", "002", {
        "01": [p + "1_rep-01.bk2", p + "4_rep-01.bk2", p + "5_rep-01.bk2"]})
    got = _by_name(collect_bk2_files(str(tmp_path)))
    assert [got[p + n]["bk2_idx"] for n in ("1_rep-01.bk2", "4_rep-01.bk2", "5_rep-01.bk2")] \
        == [0, 1, 2]
    assert {v["run"] for v in got.values()} == {"01"}


def test_bk2_entity_in_name_is_used_as_is(tmp_path):
    ses_dir = tmp_path / "sub-01" / "ses-001" / "beh"
    ses_dir.mkdir(parents=True)
    (ses_dir / "sub-01_ses-001_run-03_level-w1l1_bk2-02.bk2").write_bytes(b"")
    (f,) = collect_bk2_files(str(tmp_path))
    assert (f["run"], f["bk2_idx"]) == ("03", 2)


def test_replay_missing_from_events_gets_no_index(tmp_path):
    p = "sub-01_ses-001_task-mario_level-"
    _write_session(tmp_path, "01", "001", {"01": [p + "w1l1_rep-000.bk2"]})
    stray = tmp_path / "sub-01" / "ses-001" / "gamelogs" / (p + "w1l1_rep-001.bk2")
    stray.write_bytes(b"")
    got = _by_name(collect_bk2_files(str(tmp_path)))
    assert got[p + "w1l1_rep-001.bk2"]["bk2_idx"] is None
    assert got[p + "w1l1_rep-001.bk2"]["run"] is None


def test_annotated_events_are_ignored(tmp_path):
    p = "sub-01_ses-001_task-mario_level-"
    _write_session(tmp_path, "01", "001", {"01": [p + "w1l1_rep-000.bk2", p + "w1l1_rep-001.bk2"]})
    func = tmp_path / "sub-01" / "ses-001" / "func"
    # same replays in the opposite order, in a derived file that must not count
    (func / "sub-01_ses-001_task-x_run-01_desc-annotated_events.tsv").write_text(
        EVENTS_HEADER
        + f"gym-retro_game\t0\tx\tsub-01/ses-001/gamelogs/{p}w1l1_rep-001.bk2\n"
        + f"gym-retro_game\t9\tx\tsub-01/ses-001/gamelogs/{p}w1l1_rep-000.bk2\n")
    got = _by_name(collect_bk2_files(str(tmp_path)))
    assert got[p + "w1l1_rep-000.bk2"]["bk2_idx"] == 0
    assert got[p + "w1l1_rep-001.bk2"]["bk2_idx"] == 1


def test_subject_and_session_filters(tmp_path):
    p = "sub-0{}_ses-001_task-mario_level-w1l1_rep-000.bk2"
    _write_session(tmp_path, "01", "001", {"01": [p.format(1)]})
    _write_session(tmp_path, "02", "001", {"01": [p.format(2)]})
    got = collect_bk2_files(str(tmp_path), subjects=["sub-02"])
    assert [f["sub"] for f in got] == ["02"]
