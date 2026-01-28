# Video Game Replay Visualizer GUI

Interactive tool for exploring CNeuroMod videogame datasets.

## Features

1. **Replay Browser**: Browse datasets (mario, shinobi, mario3, mariostars) and select replays
2. **Video Playback**: Play, pause, forward, backward controls with frame slider
3. **Game Variables**: Display variables as scrolling timeseries (like EEG)
   - Select which variables to display
   - Toggle between raw values and z-scored values
4. **Annotated Events**: Show events aligned to the current replay
   - Events with zero duration display for minimum 0.5 seconds

## Installation

```bash
pip install -e .
```

This will install all dependencies including:
- PyQt6 (GUI framework)
- pyqtgraph (fast plotting)
- pandas (data loading)
- scipy (z-score computation)
- And existing dependencies (stable-retro, opencv, etc.)

## Usage

### Command-line tool

```bash
vg-visualizer
```

### As a Python module

```bash
python -m videogames_utils.gui
```

## How to Use

1. **Browse for Dataset**: Click "Browse for Dataset..." button and select a dataset folder (e.g., mario, shinobi, mario3)
2. **Filter**: Use subject/session/level filters to narrow down replays
3. **Load Replay**: Double-click a replay or select and click "Load Selected Replay"
4. **Control Playback**:
   - Play/Pause button
   - << and >> buttons for frame stepping
   - Slider for seeking to specific frames
5. **View Variables**:
   - Check/uncheck variables to display
   - Toggle between "Raw Values" and "Z-Scored"
   - All plots are synchronized with video playback
6. **View Events**: Active events are shown in the "Active Events" panel

## File Structure

The GUI expects datasets with this structure:

```
dataset_name/               (e.g., mario, shinobi, mario3, mariostars)
├── sub-XX/
│   └── ses-YYY/
│       ├── gamelogs/
│       │   ├── *.bk2                    (replay files - input recordings + savestate)
│       │   ├── *_variables.json         (game state variables per frame)
│       │   └── *_summary.json           (replay metadata)
│       └── func/
│           └── *desc-annotated_events.tsv (event annotations aligned to BOLD runs)
└── stimuli/
    └── GameName-System/          (e.g., SuperMarioBros-Nes)
        ├── rom.nes               (ROM file - REQUIRED for playback)
        ├── data.json             (variable definitions)
        ├── *.state               (savestate files)
        └── metadata.json         (game metadata)
```

**Important**: ROM files are **REQUIRED**. The .bk2 files contain input recordings and savestates, but the actual game ROM must be present in the `stimuli/` folder for the emulator to run.

## Known Limitations

- Loading large replays may take a few moments (all frames are loaded into memory for smooth playback)
- Very long replays (>10,000 frames) may use significant RAM

## Technical Details

- **Video Player**:
  - Uses `videogames_utils.replay.replay_bk2()` to generate frames on-the-fly
  - Automatically finds ROM files in `dataset/stimuli/` folder
  - Configures stable_retro to use the dataset's custom integration paths
  - .bk2 files contain input recordings; ROMs provide the game code for emulation
- **Timeseries**: PyQtGraph for fast, interactive plotting with synchronized scrolling
- **Events**: Automatically maps events from BOLD runs to individual replays using onset timing from desc-annotated_events.tsv
- **Supported Games**: mario, mario3, mariostars, shinobi (auto-detected from filenames)
