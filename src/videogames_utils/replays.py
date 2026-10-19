"""Generate the replay outputs of a videogame dataset from its ``.bk2`` files.

For every repetition listed in the plain ``func/*_events.tsv`` files, the ``.bk2`` is
replayed in the emulator and its ``gamelogs/`` outputs are written:

    *_variables.json   game variables, one value per frame
    *_recording.mp4    the replay, with its audio, at the game's frame rate
    *_lowlevel.npy     luminance, optical flow and audio envelope per frame
    *_summary.json     one record per repetition (see below)

The game-specific parts come from the dataset's :class:`~.events.game.Game`: the
scenario, the variables' corrections, the outcome, the protocol phases and the game's own
summary fields. Each dataset's ``code/replays/generate_replays.py`` only calls
:func:`main` with its game.

Every ``_summary.json`` holds the same common fields, followed by the game's own:

    Subject, Session, Run, Level   BIDS labels (``sub-01``, ``ses-002``, ``run-01``) and
                                   the ``level-`` entity of the ``.bk2``
    Bk2File                        the ``.bk2``, relative to the dataset root
    IndexInRun                     position among the run's repetitions with a ``.bk2``
    IndexGlobal, IndexLevel        position among the subject's repetitions, overall and
                                   at this level, in the order they were played
    Phase                          the protocol phase, or null
    Outcome                        how the repetition ended
    Duration, FrameCount           length of the replay, in seconds and frames
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import multiprocessing
import os
import os.path as op
import re
import sys
from typing import List, Optional

import numpy as np
import pandas as pd
import stable_retro as retro
from tqdm import tqdm

from .events.emit import RAW_REPETITION
from .events.game import Game, load_game
from .events.run import n_frames_of
from .low_level_features import (audio_envelope_per_frame, compute_luminance,
                                 compute_optical_flow)
from .replay import done_problem, get_variables_from_replay
from .video import make_mp4

_ENTITY_RE = re.compile(r"(sub|ses|run|level)-([^_]+)")


def _entities(name: str) -> dict:
    return dict(_ENTITY_RE.findall(op.basename(name)))


def collect_repetitions(dataset_dir: str) -> pd.DataFrame:
    """Every repetition with a ``.bk2``, from the plain events.tsv files of a dataset.

    Returns a DataFrame with one row per repetition, sorted by subject and order of
    play: ``bk2_file``, ``subject``, ``session``, ``run``, ``level`` (the ``.bk2``'s
    ``level-`` entity), ``events_level`` (the ``level`` of its events.tsv row),
    ``run_levels`` (distinct levels in the run), ``idx_in_run``, ``global_idx`` and
    ``level_idx``.
    """
    rows = []
    for root, _, files in sorted(os.walk(dataset_dir)):
        if "sourcedata" in root:
            continue
        for name in sorted(files):
            if not name.endswith("_events.tsv") or "annotated" in name:
                continue
            path = op.join(root, name)
            try:
                events = pd.read_table(path)
            except Exception as error:
                logging.error(f"Cannot read {path}: {error}")
                continue
            if "trial_type" not in events or "stim_file" not in events:
                continue
            run = "run-" + _entities(name).get("run", "")
            run_levels = events["level"].dropna().nunique() if "level" in events else 0
            reps = events[events["trial_type"] == RAW_REPETITION]
            reps = reps[reps["stim_file"].apply(
                lambda s: isinstance(s, str) and s.endswith(".bk2"))]
            for idx_in_run, (_, rep) in enumerate(reps.iterrows()):
                bk2 = _entities(rep["stim_file"])
                rows.append({
                    "bk2_file": rep["stim_file"],
                    "subject": "sub-" + bk2.get("sub", ""),
                    "session": "ses-" + bk2.get("ses", ""),
                    "run": run,
                    "level": bk2.get("level"),
                    "events_level": rep.get("level"),
                    "run_levels": run_levels,
                    "idx_in_run": idx_in_run,
                })
    columns = ["bk2_file", "subject", "session", "run", "level", "events_level",
               "run_levels", "idx_in_run"]
    reps = pd.DataFrame(rows, columns=columns)
    reps = reps.sort_values(["subject", "session", "run", "idx_in_run"])
    reps["global_idx"] = reps.groupby("subject").cumcount()
    reps = reps.sort_values(["subject", "level", "session", "run", "idx_in_run"])
    reps["level_idx"] = reps.groupby(["subject", "level"]).cumcount()
    return reps.sort_values(["subject", "global_idx"]).reset_index(drop=True)


def output_paths(output_dir: str, bk2_file: str) -> dict:
    """The ``gamelogs/`` outputs of a repetition."""
    base = op.join(output_dir, op.dirname(bk2_file), op.basename(bk2_file)[:-len(".bk2")])
    return {"json": base + "_summary.json", "mp4": base + "_recording.mp4",
            "variables": base + "_variables.json", "lowlevel": base + "_lowlevel.npy"}


def _missing_outputs(paths: dict, settings: dict) -> List[str]:
    missing = [] if op.exists(paths["json"]) else ["json"]
    for key, skip in (("mp4", "skip_videos"), ("variables", "skip_variables"),
                      ("lowlevel", "skip_lowlevel")):
        if not settings[skip] and not op.exists(paths[key]):
            missing.append(key)
    return missing


def summarize(game: Game, rep: dict, repvars: dict) -> dict:
    """The ``_summary.json`` of a repetition: the common fields, then the game's."""
    n_frames = n_frames_of(repvars)
    outcome = game.outcome(repvars)
    summary = {
        "Subject": rep["subject"], "Session": rep["session"], "Run": rep["run"],
        "Level": rep["level"], "Bk2File": rep["bk2_file"],
        "IndexInRun": int(rep["idx_in_run"]), "IndexGlobal": int(rep["global_idx"]),
        "IndexLevel": int(rep["level_idx"]), "Phase": rep.get("phase"),
        "Outcome": outcome,
        "Duration": n_frames / game.frame_rate, "FrameCount": n_frames,
    }
    if game.summary is not None:
        events = game.generate(repvars, outcome=outcome, stim_file=rep["bk2_file"])
        summary.update(game.summary(repvars, events))
    return summary


# ------------------------------------------------------------------- one repetition

#: The game being processed. Set before the worker processes are forked, which inherit it.
_GAME: Optional[Game] = None


def _init_worker(stimuli_dir: str) -> None:
    retro.data.Integrations.add_custom_path(stimuli_dir)


def process_repetition(rep: dict, settings: dict) -> Optional[str]:
    """Replay one repetition and write its outputs.

    Returns:
        A description of what is wrong with its ``done`` flags, or None.
    """
    game = _GAME
    paths = output_paths(settings["output_dir"], rep["bk2_file"])
    missing = _missing_outputs(paths, settings)
    if not missing and not settings["force"]:
        logging.info(f"Skipping (all outputs exist): {rep['bk2_file']}")
        return None
    logging.info(f"Processing {rep['bk2_file']} (missing: {', '.join(missing)})")
    bk2_path = op.join(settings["dataset_dir"], rep["bk2_file"])
    if not op.exists(bk2_path):
        logging.error(f"File not found: {bk2_path}")
        return None

    scenario = None
    if game.scenario is not None and isinstance(rep["events_level"], str):
        name = game.scenario(rep["events_level"])
        if name:
            scenario = op.join(settings["stimuli_dir"], game.game_id, name)
    repvars, replay_info, frames, audio, audio_rate = get_variables_from_replay(
        bk2_path, game=game.game_id, scenario=scenario,
        inttype=retro.data.Integrations.CUSTOM_ONLY)
    problem = done_problem([info["done"] for info in replay_info], rep["bk2_file"])
    del replay_info
    if game.process_variables is not None:
        repvars = game.process_variables(repvars)

    os.makedirs(op.dirname(paths["json"]), exist_ok=True)
    if not settings["skip_videos"]:
        make_mp4(frames, paths["mp4"], audio=audio, sample_rate=audio_rate,
                 fps=game.frame_rate)
    if not settings["skip_variables"]:
        with open(paths["variables"], "w") as handle:
            json.dump(repvars, handle)
    if not settings["skip_lowlevel"]:
        np.save(paths["lowlevel"], {
            "luminance": compute_luminance(frames),
            "optical_flow": compute_optical_flow(frames),
            "audio_envelope": audio_envelope_per_frame(
                audio, sample_rate=audio_rate, frame_rate=game.frame_rate,
                frame_count=len(frames)),
        })
    with open(paths["json"], "w") as handle:
        json.dump(summarize(game, rep, repvars), handle)

    del frames, audio, repvars
    gc.collect()
    return problem


def _process(task) -> Optional[str]:
    return process_repetition(*task)


# ------------------------------------------------------------------------ dataset


def generate_replays(dataset_dir: str, game: Game, output_dir: Optional[str] = None,
                     stimuli_dir: Optional[str] = None, n_jobs: int = 1,
                     subjects: Optional[List[str]] = None,
                     sessions: Optional[List[str]] = None, skip_videos: bool = False,
                     skip_variables: bool = False, skip_lowlevel: bool = False,
                     force: bool = False) -> List[str]:
    """Replay every repetition of a dataset and write its outputs.

    Indices and phases are computed over the whole dataset, then the repetitions are
    filtered by ``subjects`` and ``sessions``. Each repetition is replayed in a fresh
    worker process, which is the only reliable way to release the emulator's memory.

    Returns:
        The repetitions whose ``done`` flags are wrong, described.
    """
    dataset_dir = op.abspath(dataset_dir)
    settings = {
        "dataset_dir": dataset_dir,
        "output_dir": op.abspath(output_dir or dataset_dir),
        "stimuli_dir": op.abspath(stimuli_dir or op.join(dataset_dir, "stimuli")),
        "skip_videos": skip_videos, "skip_variables": skip_variables,
        "skip_lowlevel": skip_lowlevel, "force": force,
    }
    reps = collect_repetitions(dataset_dir)
    reps["phase"] = list(game.phases(reps)) if game.phases is not None else None
    if subjects:
        reps = reps[reps["subject"].isin(subjects)]
    if sessions:
        reps = reps[reps["session"].isin(sessions)]
    tasks = [(rep, settings) for rep in reps.to_dict("records")]
    logging.info(f"{len(tasks)} repetitions to process")
    if not tasks:
        return []

    global _GAME
    _GAME = game
    n_jobs = os.cpu_count() if n_jobs == -1 else max(1, n_jobs)
    context = multiprocessing.get_context("fork")
    with context.Pool(n_jobs, initializer=_init_worker,
                      initargs=(settings["stimuli_dir"],), maxtasksperchild=1) as pool:
        problems = list(tqdm(pool.imap(_process, tasks), total=len(tasks),
                             desc="Processing files"))
    return [p for p in problems if p]


def report_done_problems(problems: List[str]) -> None:
    """Print every replay whose done flag is not set on its last frame only."""
    if problems:
        banner = "!" * 80
        logging.warning(f"\n{banner}\n{len(problems)} replay(s) do not end on done:\n"
                        + "\n".join(problems) + f"\n{banner}")


def main(argv=None, game: Optional[Game] = None) -> int:
    """Command line front end, called by each dataset's ``generate_replays.py``."""
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-d", "--datapath", default=".",
                        help="Root of the dataset, with the events.tsv and .bk2 files.")
    parser.add_argument("-s", "--stimuli", default=None,
                        help="Where the game integration is; default <datapath>/stimuli.")
    parser.add_argument("-o", "--output", default=None,
                        help="Where to write the outputs; default <datapath>.")
    parser.add_argument("-nj", "--n_jobs", default=1, type=int,
                        help="Parallel jobs; -1 for all cores.")
    parser.add_argument("--subjects", "-sub", nargs="+", default=None,
                        help="Subjects to process, e.g. sub-01 sub-02.")
    parser.add_argument("--sessions", "-ses", nargs="+", default=None,
                        help="Sessions to process, e.g. ses-001 ses-002.")
    parser.add_argument("--skip_videos", action="store_true",
                        help="Do not write the _recording.mp4 files.")
    parser.add_argument("--skip_variables", action="store_true",
                        help="Do not write the _variables.json files.")
    parser.add_argument("--skip_lowlevel", action="store_true",
                        help="Do not write the _lowlevel.npy files.")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate outputs that already exist. Needed when the "
                             "integration's data.json has gained variables.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Display verbose output.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(message)s", force=True)
    problems = generate_replays(
        args.datapath, game or load_game(args.datapath), output_dir=args.output,
        stimuli_dir=args.stimuli, n_jobs=args.n_jobs, subjects=args.subjects,
        sessions=args.sessions, skip_videos=args.skip_videos,
        skip_variables=args.skip_variables, skip_lowlevel=args.skip_lowlevel,
        force=args.force)
    report_done_problems(problems)
    return 0


if __name__ == "__main__":
    sys.exit(main())
