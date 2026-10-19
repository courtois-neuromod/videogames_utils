"""Run-level orchestration: turn one run's ``_events.tsv`` into an annotated events file.

This is the shared body of what used to be four near-duplicate
``code/annotations/generate_annotations.py`` scripts. Each dataset now keeps only a thin
CLI that calls :func:`annotate_dataset` with its :class:`~.game.Game`.
"""

from __future__ import annotations

import collections
import json
import os
import os.path as op
from glob import glob
from typing import Dict, List, Optional

import pandas as pd

from . import vocabulary
from .emit import RAW_REPETITION, REPETITION, finalize
from .game import Game


#: stim_file value of a repetition whose .bk2 was lost.
MISSING_FILE = "Missing file"


def n_frames_of(repvars: dict) -> int:
    """Number of frames of a replay, from its per-frame button presses."""
    actions = repvars.get("actions") or []
    return len(repvars.get(actions[0]) or []) if actions else 0


def annotate_run(events_path: str, dataset_dir: str, game: Game) -> pd.DataFrame:
    """Build the annotated events table for one run.

    Args:
        events_path: The run's plain ``*_events.tsv``.
        dataset_dir: Dataset root, used to resolve ``stim_file`` paths.
        game: The dataset's game.

    Returns:
        The annotated events DataFrame, or an empty one when no replay is available.
    """
    raw = pd.read_table(events_path)
    reps = raw[raw["trial_type"] == RAW_REPETITION].reset_index(drop=True)
    if reps.empty:
        return pd.DataFrame()
    missing: List[str] = []

    frames: List[pd.DataFrame] = []

    for _, rep in reps.iterrows():
        stim = rep.get("stim_file")
        # The datasets use a "Missing file" sentinel with inconsistent capitalisation
        # ("Missing File" appears in shinobi), so compare case-insensitively. The
        # repetition was played but its .bk2 was lost: keep its container row, with the
        # timing the task logged, so the run's timeline stays complete.
        if not isinstance(stim, str) or stim.strip().lower() == "missing file":
            frames.append(pd.DataFrame([{
                "onset": float(rep["onset"]),
                "duration": pd.to_numeric(rep.get("duration"), errors="coerce"),
                "trial_type": REPETITION,
                "frame_start": pd.NA, "frame_stop": pd.NA,
                "stim_file": MISSING_FILE,
            }]))
            continue
        var_path = op.join(dataset_dir, stim).replace(".bk2", "_variables.json")
        if not op.exists(var_path):
            # Skip this repetition rather than abandoning the whole run: a handful of
            # .bk2 have no sidecars (1 in mario3, 9 in mariostars, 18 in shinobi), and
            # the shipped script aborts the entire events file when it meets one.
            missing.append(stim)
            continue
        with open(var_path) as handle:
            repvars = json.load(handle)

        summary = {}
        sum_path = var_path.replace("_variables.json", "_summary.json")
        if op.exists(sum_path):
            with open(sum_path) as handle:
                summary = json.load(handle)

        rep_onset = float(rep["onset"])
        n_frames = n_frames_of(repvars)
        duration = n_frames / game.frame_rate

        # Only the container row carries stim_file; the repetition's phase and indices
        # live in its _summary.json rather than being repeated on every event row.
        defaults = {}

        rep_events = game.generate(repvars, outcome=summary.get("Outcome"), stim_file=stim,
                                   **defaults)
        if not rep_events.empty:
            rep_events["onset"] = rep_events["onset"] + rep_onset
            frames.append(rep_events)

        # The container row anchors stim_file and stays in the vocabulary as-is.
        container = pd.DataFrame([{
            "onset": rep_onset, "duration": duration,
            "trial_type": REPETITION,
            "frame_start": 0, "frame_stop": n_frames,
            "stim_file": stim,
        }])
        frames.append(container)

    if missing:
        print(f"  warning: {len(missing)} repetition(s) without _variables.json, "
              f"skipped: {[op.basename(m) for m in missing[:3]]}")
    if not frames:
        return pd.DataFrame()
    return finalize(frames)


def annotate_dataset(dataset_dir: str, game: Game, output_dir: Optional[str] = None,
                     subjects: Optional[List[str]] = None,
                     sessions: Optional[List[str]] = None,
                     overwrite: bool = False, verbose: bool = True) -> Dict[str, int]:
    """Annotate every run of a dataset.

    Returns:
        ``{"written": n, "skipped": n, "empty": n}``
    """
    stats = {"written": 0, "skipped": 0, "empty": 0}

    for root, _, files in sorted(os.walk(dataset_dir)):
        if "sourcedata" in root:
            continue
        if subjects and not any(s in root for s in subjects):
            continue
        if sessions and not any(s in root for s in sessions):
            continue
        for name in sorted(files):
            if "events.tsv" not in name or "annotated" in name:
                continue
            events_path = op.join(root, name)
            out_name = name.replace("_events.", "_desc-annotated_events.")
            if output_dir:
                sub, ses = name.split("_")[0], name.split("_")[1]
                out_path = op.join(output_dir, sub, ses, "func", out_name)
            else:
                out_path = op.join(root, out_name)
            if op.exists(out_path) and not overwrite:
                stats["skipped"] += 1
                continue

            annotated = annotate_run(events_path, dataset_dir, game)
            if annotated.empty:
                stats["empty"] += 1
                if verbose:
                    print(f"  no replays available: {name}")
                continue
            os.makedirs(op.dirname(out_path), exist_ok=True)
            annotated.to_csv(out_path, sep="\t", index=False, na_rep="n/a")
            stats["written"] += 1
            if verbose:
                print(f"  wrote {out_path} ({len(annotated)} events)")

    return stats


def census(dataset_dir: str) -> collections.Counter:
    """trial_type counts over every annotated events file of the dataset."""
    counts: collections.Counter = collections.Counter()
    for path in glob(op.join(dataset_dir, "sub-*", "ses-*", "func",
                             "*_desc-annotated_events.tsv")):
        counts.update(pd.read_csv(path, sep="\t", usecols=["trial_type"])["trial_type"])
    return counts


def write_events_sidecar(dataset_dir: str, game: Game) -> str:
    """Write the BIDS ``task-<task>_events.json`` describing the game's vocabulary.

    The decoded types listed are those present in the dataset's annotated events files.
    """
    path = op.join(dataset_dir, f"task-{game.task}_events.json")
    sidecar = vocabulary.write_bids_sidecar(
        game.vocabulary, trial_types=census(dataset_dir), families=game.families,
        type_descriptions=game.type_descriptions)
    with open(path, "w") as handle:
        json.dump(sidecar, handle, indent=2)
        handle.write("\n")
    return path
