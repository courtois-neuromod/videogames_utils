"""Metadata utilities for creating BIDS-compliant sidecars from replay variables."""

from typing import Any, Dict


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
