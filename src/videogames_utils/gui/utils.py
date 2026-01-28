"""
Utility functions for the GUI
"""

from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json
import pandas as pd
import numpy as np
from scipy import stats


# Game configurations from the original script
GAME_CONFIGS = {
    'mario': {
        'top_stats': ['score', 'coins', 'lives', 'time', 'world'],
        'state_vars': {
            'Power': 'powerstate',
            'Star': 'star_timer',
            'Fireballs': 'fireball_counter',
            'Jump': 'jump_airborne',
        },
        'position': ['player_x_posHi', 'player_y_pos'],
        'buttons': ['B', 'A', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'START', 'SELECT'],
        'event_vars': [
            'powerup_appear', 'powerup_yes_no', 'enemy_kill30', 'enemy_kill31',
            'enemy_kill32', 'enemy_kill33', 'enemy_kill34', 'enemy_kill35',
        ]
    },
    'mario3': {
        'top_stats': ['score', 'coins', 'lives', 'time', 'world'],
        'state_vars': {
            'Form': 'mario_form',
            'Power': 'powerup',
            'Invincible': 'invincibility_timer',
            'Flight': 'flight_timer',
            'P-Meter': 'p_meter',
            'Boss HP': 'boss_hp',
            'In Air': 'in_air',
        },
        'position': ['player_x_level', 'player_y_level'],
        'buttons': ['B', 'A', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'START', 'SELECT'],
        'event_vars': [
            'killed', 'stomp_counter', 'boss_hp', 'kuribo_shoe', 'p_switch_timer',
            'statue_timer', 'in_water', 'complete_level', 'goal_cards_p1_1',
            'goal_cards_p1_2', 'goal_cards_p1_3',
        ]
    },
    'mariostars': {
        'top_stats': ['score', 'coins', 'lives', 'time_hundreds', 'current_world'],
        'state_vars': {
            'Power': 'player_powerup',
            'Star': 'star_power_timer',
            'Action': 'player_action_state',
        },
        'position': ['player_x_high', 'player_y_low'],
        'buttons': ['B', 'A', 'X', 'Y', 'L', 'R', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'START', 'SELECT'],
        'event_vars': []
    },
    'shinobi': {
        'top_stats': ['score', 'lives', 'health', 'shurikens', 'section'],
        'state_vars': {
            'Ninjitsu': 'ninjitsu',
            'Type': 'typeOfNinjitsu',
            'Status': 'status',
            'Ride': 'ride',
        },
        'position': ['X_player', 'Y_player'],
        'buttons': ['B', 'A', 'C', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'START', 'MODE'],
        'event_vars': []
    }
}


def detect_game_from_filename(filename: str) -> str:
    """Detect game type from filename"""
    filename_lower = filename.lower()
    if 'mariostars' in filename_lower:
        return 'mariostars'
    elif 'mario3' in filename_lower:
        return 'mario3'
    elif 'mario' in filename_lower:
        return 'mario'
    elif 'shinobi' in filename_lower:
        return 'shinobi'
    else:
        raise ValueError(f"Cannot detect game type from filename: {filename}")


def find_rom_integration_path(dataset_path: Path, game_type: str) -> Optional[Path]:
    """
    Find the stable_retro integration directory for a game in the stimuli folder

    Returns the directory containing rom.nes, data.json, etc.
    """
    stimuli_path = dataset_path / "stimuli"
    if not stimuli_path.exists():
        return None

    # First try specific patterns for known games
    integration_patterns = {
        'mario': ['SuperMarioBros-Nes', 'Mario-Nes'],
        'mario3': ['SuperMarioBros3-Nes', 'Mario3-Nes'],
        'mariostars': ['SuperMarioAllStars-Snes', 'SuperMario64-n64', 'Mario64-n64'],
        'shinobi': ['Shinobi3-Genesis', 'RevengeOfShinobi-Genesis',
                    'ShinobiIIIReturnOfTheNinjaMaster-Genesis', 'Shinobi-Genesis']
    }

    patterns = integration_patterns.get(game_type, [])

    # Look for the integration directory using patterns
    for pattern in patterns:
        integration_dir = stimuli_path / pattern
        if integration_dir.exists() and integration_dir.is_dir():
            # Verify it has the required files
            if (integration_dir / "rom.nes").exists() or \
               (integration_dir / "rom.md").exists() or \
               (integration_dir / "rom.sfc").exists() or \
               (integration_dir / "rom.n64").exists():
                return integration_dir

    # Fallback: search all subdirectories for any with ROM files
    # This handles cases where the directory name doesn't match our patterns
    try:
        for item in stimuli_path.iterdir():
            if item.is_dir():
                # Check if this directory contains a ROM file
                if (item / "rom.nes").exists() or \
                   (item / "rom.md").exists() or \
                   (item / "rom.sfc").exists() or \
                   (item / "rom.n64").exists():
                    # Found a ROM directory, return it
                    return item
    except Exception as e:
        print(f"Error scanning stimuli directory: {e}")

    return None


def load_variables_json(json_path: Path) -> Dict:
    """Load variables from JSON file"""
    with open(json_path, 'r') as f:
        return json.load(f)


def get_replays_from_events_files(dataset_path: Path) -> List[Dict]:
    """
    Get all replays by parsing events files in func/ directories

    This is more reliable than globbing for bk2 files, and also determines
    which replays are first in their run.

    Args:
        dataset_path: Path to dataset root

    Returns:
        List of replay info dicts with added 'skip_first_step' field
    """
    replays = []

    # Find all events files
    events_files = list(dataset_path.rglob("func/*desc-annotated_events.tsv"))

    for events_file in events_files:
        try:
            df = pd.read_csv(events_file, sep='\t')

            # Get all gym-retro_game rows
            game_rows = df[df['trial_type'] == 'gym-retro_game']

            for idx, (row_idx, row) in enumerate(game_rows.iterrows()):
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
                # Add flag for skip_first_step (first replay in this run)
                info['skip_first_step'] = (idx == 0)
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


def is_first_replay_in_run(events_path: Path, bk2_filename: str) -> bool:
    """
    Check if this replay is the first in its run

    The first replay in a run is the first gym-retro_game entry in the events file
    for that specific run.

    Args:
        events_path: Path to desc-annotated_events.tsv file
        bk2_filename: Filename of the .bk2 replay

    Returns:
        True if this is the first replay in the run, False otherwise
    """
    if not events_path or not events_path.exists():
        return False

    try:
        df = pd.read_csv(events_path, sep='\t')

        # Find the gym-retro_game row that references this .bk2 file
        game_row_mask = (df['trial_type'] == 'gym-retro_game') & (df['stim_file'].str.contains(bk2_filename, na=False))

        if not game_row_mask.any():
            return False

        game_row_idx = df[game_row_mask].index[0]

        # Check if there are any previous gym-retro_game rows in the same run
        # (i.e., in this events file)
        previous_game_rows = df[df.index < game_row_idx]['trial_type'] == 'gym-retro_game'

        # If no previous game rows, this is the first
        return not previous_game_rows.any()
    except Exception:
        return False


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

    # Find the gym-retro_game row that references this .bk2 file
    game_row_mask = (df['trial_type'] == 'gym-retro_game') & (df['stim_file'].str.contains(bk2_filename, na=False))

    if not game_row_mask.any():
        return pd.DataFrame()  # No events found for this replay

    game_row_idx = df[game_row_mask].index[0]
    replay_onset = df.loc[game_row_idx, 'onset']

    # Get the index of the next gym-retro_game row (or end of dataframe)
    next_game_rows = df[df.index > game_row_idx]['trial_type'] == 'gym-retro_game'
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
