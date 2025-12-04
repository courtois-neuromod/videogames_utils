"""Metadata utilities for processing BK2 replay files and creating BIDS-compliant sidecars."""

import os
import os.path as op
import glob
from typing import List, Dict, Optional, Any


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
        - 'run': Run number (e.g., '01')
        - 'bk2_idx': Index of BK2 file within run (0-based)

    Examples
    --------
    >>> bk2_files = collect_bk2_files('/data/mario', subjects=['sub-01'])
    >>> print(bk2_files[0])
    {'bk2_file': 'sub-01/ses-001/beh/sub-01_ses-001_run-01_level-w1l1_bk2-00.bk2',
     'sub': '01', 'ses': '001', 'run': '01', 'bk2_idx': 0}
    """
    pattern = op.join(data_path, "sub-*", "ses-*", "beh", "*.bk2")
    all_bk2_paths = sorted(glob.glob(pattern))

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

        # Extract BK2 index (if present in filename)
        bk2_idx = int(entities.get("bk2", "0"))

        bk2_info = {
            "bk2_file": rel_path,
            "sub": sub_id,
            "ses": ses_id,
            "run": entities.get("run", "00"),
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
