"""Metadata utilities for processing BK2 replay files and creating BIDS-compliant sidecars."""

import csv
import os
import os.path as op
import glob
import warnings
from functools import lru_cache
from typing import List, Dict, Optional, Any, Tuple


@lru_cache(maxsize=None)
def _positions_in_runs(session_dir: str) -> Dict[str, Tuple[str, int]]:
    """Map each replay of a session to (run, position in run) from its events.tsv files.

    The position counts the ``gym-retro_game`` rows of the run's raw
    ``func/*_events.tsv`` from 0, in acquisition order. Keys are the ``stim_file``
    values: paths relative to the dataset root.
    """
    positions = {}
    pattern = op.join(session_dir, "func", "*_run-*_events.tsv")
    for events_file in sorted(glob.glob(pattern)):
        name = op.basename(events_file)
        if "_desc-" in name or not op.exists(events_file):
            continue
        run = name.split("_run-")[1].split("_")[0]
        with open(events_file, newline="") as fh:
            rows = [r for r in csv.DictReader(fh, delimiter="\t")
                    if r.get("trial_type") == "gym-retro_game"]
        for idx, row in enumerate(rows):
            stim_file = (row.get("stim_file") or "").strip()
            if stim_file.endswith(".bk2"):
                positions[op.normpath(stim_file)] = (run, idx)
    return positions


def collect_bk2_files(
    data_path: str,
    subjects: Optional[List[str]] = None,
    sessions: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Collect BK2 replay files from a BIDS-formatted dataset.

    Scans the data directory for .bk2 files and extracts metadata from
    their BIDS-compliant filenames.

    Parameters
    ----------
    data_path : str
        Root path to the dataset containing subject folders.
    subjects : list of str, optional
        List of subject IDs to filter (e.g., ['sub-01', 'sub-02']).
        If None, all subjects are included.
    sessions : list of str, optional
        List of session IDs to filter (e.g., ['ses-001', 'ses-002']).
        If None, all sessions are included.

    Returns
    -------
    list of dict
        List of dictionaries containing BK2 file metadata:
        - 'bk2_file': Relative path to BK2 file from data_path
        - 'sub': Subject ID (e.g., '01')
        - 'ses': Session ID (e.g., '001')
        - 'run': Run number (e.g., '01'), or None if unknown
        - 'bk2_idx': Index of BK2 file within run (0-based), or None if unknown

    When the file name has no ``bk2-`` entity (mario: ``level-w1l1_rep-000``,
    shinobi: ``run-01_level-1_rep-01``), run and index are read from the session's
    ``func/*_events.tsv``: the replay's position among the run's ``gym-retro_game``
    rows. ``rep`` numbers repetitions of a level and is not used for either.

    Examples
    --------
    >>> bk2_files = collect_bk2_files('/data/mario', subjects=['sub-01'])
    >>> print(bk2_files[1])
    {'bk2_file': 'sub-01/ses-001/gamelogs/sub-01_ses-001_task-mario_level-w1l1_rep-001.bk2',
     'sub': '01', 'ses': '001', 'run': '01', 'bk2_idx': 1}
    """
    # Search in both 'beh' and 'gamelogs' subdirectories
    pattern_beh = op.join(data_path, "sub-*", "ses-*", "beh", "*.bk2")
    pattern_gamelogs = op.join(data_path, "sub-*", "ses-*", "gamelogs", "*.bk2")
    all_bk2_paths = sorted(glob.glob(pattern_beh) + glob.glob(pattern_gamelogs))

    bk2_files = []
    for bk2_path in all_bk2_paths:
        # Get relative path from data_path
        rel_path = op.relpath(bk2_path, data_path)

        # Extract entities from filename
        filename = op.basename(bk2_path)
        parts = filename.replace(".bk2", "").split("_")

        entities = {}
        for part in parts:
            if "-" in part:
                key, value = part.split("-", 1)
                entities[key] = value

        # Extract subject and session from path
        path_parts = rel_path.split(os.sep)
        sub_folder = [p for p in path_parts if p.startswith("sub-")]
        ses_folder = [p for p in path_parts if p.startswith("ses-")]

        if not sub_folder or not ses_folder:
            continue

        sub_id = sub_folder[0].replace("sub-", "")
        ses_id = ses_folder[0].replace("ses-", "")

        # Apply filters
        if subjects is not None and f"sub-{sub_id}" not in subjects:
            continue
        if sessions is not None and f"ses-{ses_id}" not in sessions:
            continue

        # Handle different naming conventions:
        # - run-XX_bk2-YY: run and position are both in the file name
        # - otherwise (mario: level-w1l1_rep-000, shinobi: run-01_level-1_rep-01)
        #   `rep` counts repetitions of a level, not runs or positions in a run, so
        #   run and position come from the run's events.tsv, where the
        #   gym-retro_game rows list the replays in the order they were played.
        position = _positions_in_runs(op.dirname(op.dirname(op.abspath(bk2_path))))
        if "bk2" in entities:
            run = entities.get("run")
            bk2_idx = int(entities["bk2"])
        elif rel_path in position:
            run, bk2_idx = position[rel_path]
            if "run" in entities and entities["run"] != run:
                warnings.warn(
                    f"{filename} is listed in the events.tsv of run-{run}",
                    stacklevel=2,
                )
        else:
            # Not listed in any events.tsv: leave both unset rather than guess, so
            # that `bk2_idx == 0` (first replay of a run) cannot be true by mistake.
            run = entities.get("run")
            bk2_idx = None

        bk2_info = {
            "bk2_file": rel_path,
            "sub": sub_id,
            "ses": ses_id,
            "run": run,
            "bk2_idx": bk2_idx,
        }

        bk2_files.append(bk2_info)

    return bk2_files


def create_sidecar_dict(variables: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a BIDS-compliant sidecar dictionary from game variables.

    Extracts metadata and scalar statistics from replay variables for
    inclusion in JSON sidecar files.

    Parameters
    ----------
    variables : dict
        Dictionary of game variables from replay. May contain:
        - Lists/arrays (per-frame values)
        - Scalars (constant values)
        - Special keys like 'metadata', 'filename', 'actions'

    Returns
    -------
    dict
        Sidecar metadata dictionary with scalar summaries:
        - Scalar variables are copied directly
        - List/array variables are summarized with statistics
        - Special keys like 'metadata' and 'actions' are preserved

    Examples
    --------
    >>> variables = {
    ...     'score': [0, 100, 200, 300],
    ...     'lives': [3, 3, 3, 2],
    ...     'level': 'w1l1',
    ...     'metadata': 'sub-01_ses-001...'
    ... }
    >>> sidecar = create_sidecar_dict(variables)
    >>> print(sidecar)
    {'score_mean': 150.0, 'score_max': 300, 'score_min': 0,
     'lives_mean': 2.75, 'lives_max': 3, 'lives_min': 2,
     'level': 'w1l1', 'metadata': 'sub-01_ses-001...'}
    """
    import numpy as np

    sidecar = {}

    # Keys to exclude from statistical summaries
    exclude_keys = {'metadata', 'filename', 'actions', 'subject', 'session'}

    for key, value in variables.items():
        # Skip excluded keys but preserve them
        if key in exclude_keys:
            sidecar[key] = value
            continue

        # Handle list/array variables with statistics
        if isinstance(value, (list, np.ndarray)):
            try:
                arr = np.array(value)
                # Only compute stats for numeric arrays
                if np.issubdtype(arr.dtype, np.number) and arr.size > 0:
                    sidecar[f"{key}_mean"] = float(np.mean(arr))
                    sidecar[f"{key}_max"] = float(np.max(arr))
                    sidecar[f"{key}_min"] = float(np.min(arr))
                    sidecar[f"{key}_std"] = float(np.std(arr))
            except (TypeError, ValueError):
                # Skip non-numeric or problematic arrays
                pass
        # Copy scalar values directly
        elif isinstance(value, (int, float, str, bool)):
            sidecar[key] = value

    return sidecar
