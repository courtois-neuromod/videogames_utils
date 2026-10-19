"""
Utility functions for the GUI
"""

from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json
import pandas as pd
import numpy as np
import stable_retro as retro

from ..events.emit import REPETITION_TYPES
from scipy import stats


def find_integration_path(dataset_path: Path, bk2_path: Path) -> Optional[Path]:
    """
    Find the stable_retro integration directory of the game a .bk2 was recorded with

    The game name is read from the .bk2 itself and the integration is expected in
    the dataset's stimuli/ folder, under that name.

    Returns the integration directory (containing data.json), or None if not found.
    """
    movie = retro.Movie(str(bk2_path))
    try:
        game = movie.get_game()
    finally:
        movie.close()
    integration_dir = Path(dataset_path) / "stimuli" / game
    if (integration_dir / "data.json").exists():
        return integration_dir
    return None


def load_variables_json(json_path: Path) -> Dict:
    """Load variables from JSON file"""
    with open(json_path, 'r') as f:
        return json.load(f)


def get_replays_from_events_files(dataset_path: Path) -> List[Dict]:
    """
    Get all replays by parsing events files in func/ directories

    This is more reliable than globbing for bk2 files.

    Args:
        dataset_path: Path to dataset root

    Returns:
        List of replay info dicts
    """
    replays = []

    # Find all events files
    events_files = list(dataset_path.rglob("func/*desc-annotated_events.tsv"))

    for events_file in events_files:
        try:
            df = pd.read_csv(events_file, sep='\t')

            # Get all repetition rows
            game_rows = df[df['trial_type'].isin(REPETITION_TYPES)]

            for _, row in game_rows.iterrows():
                stim_file = row['stim_file']

                if pd.isna(stim_file):
                    continue

                # stim_file is like "sub-03/ses-015/gamelogs/sub-03_ses-015_task-mario_level-w7l3_rep-000.bk2"
                bk2_filename = Path(stim_file).name
                bk2_path = dataset_path / stim_file

                if not bk2_path.exists():
                    print(f"Warning: bk2 file not found: {bk2_path}")
                    continue

                info = get_replay_info(bk2_path)
                info['events_file'] = events_file

                replays.append(info)

        except Exception as e:
            print(f"Error parsing {events_file}: {e}")
            continue

    return replays


def find_annotated_events_for_replay(dataset_path: Path, subject: str, session: str, task: str) -> Optional[Path]:
    """
    Find the desc-annotated_events.tsv file for a replay

    Args:
        dataset_path: Path to dataset root
        subject: Subject ID (e.g., '03')
        session: Session ID (e.g., '015')
        task: Task name (e.g., 'mario')

    Returns:
        Path to events file, or None if not found
    """
    func_dir = dataset_path / f"sub-{subject}" / f"ses-{session}" / "func"

    if not func_dir.exists():
        return None

    # Find any run's annotated events (they should all contain references to this replay)
    events_files = list(func_dir.glob(f"*task-{task}*desc-annotated_events.tsv"))

    if events_files:
        return events_files[0]  # Return first match

    return None


def load_annotated_events(events_path: Path, bk2_filename: str) -> pd.DataFrame:
    """
    Load annotated events for a specific replay

    Args:
        events_path: Path to desc-annotated_events.tsv file
        bk2_filename: Filename of the .bk2 replay (e.g., 'sub-03_ses-015_task-mario_level-w1l1_rep-000.bk2')

    Returns:
        DataFrame with events adjusted to replay timing (onset relative to replay start)
    """
    df = pd.read_csv(events_path, sep='\t')

    # Find the repetition row that references this .bk2 file
    game_row_mask = (df['trial_type'].isin(REPETITION_TYPES)) & (df['stim_file'].str.contains(bk2_filename, na=False))

    if not game_row_mask.any():
        return pd.DataFrame()  # No events found for this replay

    game_row_idx = df[game_row_mask].index[0]
    replay_onset = df.loc[game_row_idx, 'onset']

    # Get the index of the next repetition row (or end of dataframe)
    next_game_rows = df[df.index > game_row_idx]['trial_type'].isin(REPETITION_TYPES)
    if next_game_rows.any():
        next_game_idx = next_game_rows.idxmax()
        replay_events = df.loc[game_row_idx:next_game_idx-1].copy()
    else:
        replay_events = df.loc[game_row_idx:].copy()

    # Adjust onset times relative to replay start
    replay_events['onset'] = replay_events['onset'] - replay_onset

    # Handle zero-duration events (minimum 0.5s display)
    replay_events['display_duration'] = replay_events['duration'].apply(lambda d: 0.5 if d == 0 else d)

    return replay_events


def compute_zscore(data: np.ndarray) -> np.ndarray:
    """Compute z-score normalization of data"""
    return stats.zscore(data, nan_policy='omit')


def find_datasets(root_path: Path) -> List[Path]:
    """
    Find all videogame dataset directories

    Looks for directories with BIDS-like structure (sub-*/ses-*/gamelogs/)
    """
    datasets = []

    # Look for directories one level up that contain subject folders
    for item in root_path.parent.iterdir():
        if item.is_dir() and (item / "sub-01").exists():
            # Check if it has gamelogs
            gamelogs = list(item.rglob("gamelogs"))
            if gamelogs:
                datasets.append(item)

    return sorted(datasets)


def parse_bk2_filename(filename: str) -> Dict[str, str]:
    """Parse BIDS entities from .bk2 filename"""
    entities = {}
    parts = Path(filename).stem.split('_')

    for part in parts:
        if '-' in part:
            key, value = part.split('-', 1)
            entities[key] = value

    return entities


def get_replay_info(bk2_path: Path) -> Dict:
    """Extract information from a .bk2 replay file path"""
    filename = bk2_path.name
    entities = parse_bk2_filename(filename)

    return {
        'path': bk2_path,
        'subject': entities.get('sub', 'unknown'),
        'session': entities.get('ses', 'unknown'),
        'task': entities.get('task', 'unknown'),
        'level': entities.get('level', 'unknown'),
        'rep': entities.get('rep', '000'),
        'filename': filename
    }
