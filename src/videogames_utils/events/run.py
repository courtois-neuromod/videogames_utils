"""Run-level orchestration: turn one run's ``_events.tsv`` into an annotated events file.

This is the shared body of what used to be four near-duplicate
``code/annotations/generate_annotations.py`` scripts. Each dataset now keeps only a thin
CLI that calls :func:`annotate_dataset` with its task name.
"""

from __future__ import annotations

import json
import os
import os.path as op
import re
from typing import Dict, List, Optional

import pandas as pd

from . import vocabulary
from .emit import TASK_FRAME_RATES, finalize
from .generators import shinobi3, smb1, smb3

#: Which generator handles which task.
GENERATORS = {
    "mario": lambda v, **kw: smb1.generate(v, "mario", **kw),
    "mariostars": lambda v, **kw: smb1.generate(v, "mariostars", **kw),
    "mario3": lambda v, **kw: smb3.generate(v, **kw),
    "shinobi": lambda v, **kw: shinobi3.generate(v, **kw),
}

_REP_RE = re.compile(r"rep-(\d+)")


def _rep_index(stim_file: str) -> Optional[int]:
    match = _REP_RE.search(op.basename(stim_file))
    return int(match.group(1)) if match else None


def annotate_run(events_path: str, dataset_dir: str, task: str) -> pd.DataFrame:
    """Build the annotated events table for one run.

    Args:
        events_path: The run's plain ``*_events.tsv``.
        dataset_dir: Dataset root, used to resolve ``stim_file`` paths.
        task: One of ``mario``, ``mariostars``, ``mario3``, ``shinobi``.

    Returns:
        The annotated events DataFrame, or an empty one when no replay is available.
    """
    raw = pd.read_table(events_path)
    reps = raw[raw["trial_type"] == "gym-retro_game"].reset_index(drop=True)
    if reps.empty:
        return pd.DataFrame()
    missing: List[str] = []

    frames: List[pd.DataFrame] = []

    for _, rep in reps.iterrows():
        stim = rep.get("stim_file")
        # The datasets use a "Missing file" sentinel with inconsistent capitalisation
        # ("Missing File" appears in shinobi), so compare case-insensitively.
        if not isinstance(stim, str) or stim.strip().lower() == "missing file":
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
        n_frames = len(repvars.get("score") or repvars.get("health") or [])
        duration = n_frames / TASK_FRAME_RATES[task]

        # Only the container row carries stim_file; the repetition's phase and indices
        # live in its _summary.json rather than being repeated on every event row.
        defaults = {}

        kwargs = {"level": repvars.get("level", rep.get("level")),
                  "outcome": summary.get("Outcome")}
        if task == "mario3":
            kwargs["rep_index"] = _rep_index(stim)

        rep_events = GENERATORS[task](repvars, **kwargs, **defaults)
        if not rep_events.empty:
            rep_events["onset"] = rep_events["onset"] + rep_onset
            frames.append(rep_events)

        # The container row anchors stim_file and stays in the vocabulary as-is.
        container = pd.DataFrame([{
            "onset": rep_onset, "duration": duration,
            "trial_type": "gym-retro_game",
            "level": repvars.get("level", rep.get("level")),
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


def _determine_phase(reps: pd.DataFrame) -> str:
    """discovery = the same level repeated; practice = different levels in sequence.

    Matches the shipped behaviour (comparing the first two repetitions) so the column
    keeps its established meaning.
    """
    levels = reps["level"].tolist()
    if len(levels) > 1 and levels[0] == levels[1]:
        return "discovery"
    return "practice"


def annotate_dataset(dataset_dir: str, task: str, output_dir: Optional[str] = None,
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

            annotated = annotate_run(events_path, dataset_dir, task)
            if annotated.empty:
                stats["empty"] += 1
                if verbose:
                    print(f"  no replays available: {name}")
                continue
            os.makedirs(op.dirname(out_path), exist_ok=True)
            annotated.to_csv(out_path, sep="\t", index=False)
            stats["written"] += 1
            if verbose:
                print(f"  wrote {out_path} ({len(annotated)} events)")

    return stats


def write_events_sidecar(dataset_dir: str, task: str) -> str:
    """Write the BIDS ``task-<task>_events.json`` describing the vocabulary."""
    path = op.join(dataset_dir, f"task-{task}_events.json")
    with open(path, "w") as handle:
        json.dump(vocabulary.write_bids_sidecar(task), handle, indent=2)
        handle.write("\n")
    return path
