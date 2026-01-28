# Video Game Replay Visualizer GUI

Interactive tool for exploring CNeuroMod videogame datasets with synchronized visualization of gameplay, brain activity, and physiological signals.

## Features

1. **Replay Browser**: Browse datasets (mario, shinobi, mario3, mariostars) and select replays
2. **Video Playback**: Play, pause, forward, backward controls with frame slider
3. **Controller Display**: Visual representation of button presses in real-time
4. **Game Variables**: Display variables as scrolling timeseries
   - Select which variables to display
   - Toggle between raw values and z-scored values
   - Overlay or stacked plot modes
5. **Annotated Events**: Show events aligned to the current replay
   - Events with zero duration display for minimum 0.5 seconds
6. **Brain Activity Visualization**: Glass brain plots showing parcellated brain activity
   - 2x2 layout with Left Sagittal, Right Sagittal, Coronal, and Axial views
   - Automatically loads when `{dataset}.timeseries` folder is available
   - Background precomputation with configurable number of workers
   - Smooth interpolation between TRs for fluid visualization
   - Synchronized with replay timing using onset information from events
7. **Physiological Data Visualization**: Scrolling physio timeseries display
   - PPG (photoplethysmography), ECG, RSP (respiration), and EDA channels
   - Scrolling display like an ECG monitor (data enters from right, scrolls left)
   - Event markers for r-peaks, systolic peaks, and other physio events
   - Automatically loads when `{dataset}.physprep` folder is available
   - Synchronized with replay timing

## Installation

```bash
pip install -e .
```

This will install all dependencies including:
- PyQt6 (GUI framework)
- pyqtgraph (fast plotting)
- pandas (data loading)
- scipy (z-score computation)
- h5py (HDF5 file reading)
- nibabel (NIfTI file reading)
- nilearn (brain visualization)
- matplotlib (plotting backend)
- And existing dependencies (stable-retro, opencv, etc.)

## Usage

### Command-line tool

```bash
vg-visualizer
```

### Command-line options

```bash
vg-visualizer --n_jobs 8    # Use 8 workers for brain plot precomputation
vg-visualizer -j -1         # Use all available CPU cores
vg-visualizer               # Default: 1 worker (minimal CPU impact)
```

The `--n_jobs` (or `-j`) option controls how many parallel workers are used for precomputing brain plots in the background. Using more workers speeds up precomputation but uses more CPU.

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
   - Toggle between "Stacked" and "Overlay" plot modes
   - All plots are synchronized with video playback
6. **View Events**: Active events are shown in the "Active Events" panel
7. **View Controller**: Button presses are visualized in real-time
8. **View Brain Activity** (if available):
   - Brain visualization appears automatically when `{dataset}.timeseries` folder exists
   - Glass brain plots show parcellated activity in a 2x2 grid (L/R sagittal, coronal, axial)
   - Progress bar shows precomputation status
   - Smooth transitions between TRs for continuous visualization
9. **View Physiological Data** (if available):
   - Physio panel appears automatically when `{dataset}.physprep` folder exists
   - Toggle channels (PPG, ECG, RSP, EDA) with checkboxes
   - Toggle event markers (r-peaks, systolic peaks) with "Show Events" checkbox
   - Green line marks current time; data scrolls from right to left

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
├── stimuli/
│   └── GameName-System/          (e.g., SuperMarioBros-Nes)
│       ├── rom.nes               (ROM file - REQUIRED for playback)
│       ├── data.json             (variable definitions)
│       ├── *.state               (savestate files)
│       └── metadata.json         (game metadata)

dataset_name.timeseries/    (e.g., mario.timeseries - for brain visualization)
└── sub-XX/
    └── func/
        ├── *_timeseries.h5       (parcellated brain timeseries)
        └── *_dseg.nii.gz         (atlas segmentation)

dataset_name.physprep/      (e.g., mario.physprep - for physio visualization)
└── sub-XX/
    └── ses-YYY/
        └── func/
            ├── *_desc-preproc_physio.tsv.gz  (preprocessed physio signals)
            └── *_events.tsv                   (physio events: r-peaks, etc.)
```

**Important**: ROM files are **REQUIRED**. The .bk2 files contain input recordings and savestates, but the actual game ROM must be present in the `stimuli/` folder for the emulator to run.

## Known Limitations

- Loading large replays may take a few moments (all frames are loaded into memory for smooth playback)
- Very long replays (>10,000 frames) may use significant RAM
- Brain plot precomputation runs in the background; first few seconds may show "loading" until plots are ready

## Technical Details

- **Video Player**:
  - Uses `videogames_utils.replay.replay_bk2()` to generate frames on-the-fly
  - Automatically finds ROM files in `dataset/stimuli/` folder
  - Configures stable_retro to use the dataset's custom integration paths
  - .bk2 files contain input recordings; ROMs provide the game code for emulation
- **Controller Display**: Shows NES controller with real-time button state visualization
- **Timeseries**: PyQtGraph for fast, interactive plotting with synchronized scrolling
- **Events**: Automatically maps events from BOLD runs to individual replays using onset timing from desc-annotated_events.tsv
- **Brain Visualization**:
  - Detects `{dataset}.timeseries` folder automatically
  - Loads HDF5 parcellated timeseries and corresponding atlas NIfTI files
  - **Background precomputation**: Brain plots are generated in parallel using configurable workers (`--n_jobs`)
  - **Caching**: All TRs for the current replay are cached in memory
  - Extracts run number and onset time from `desc-annotated_events.tsv`
  - Syncs brain activity to replay timing (converts frame → replay time → run time → TR)
  - Smoothly interpolates between consecutive TRs for fluid visualization
  - TR hardcoded to 1.49 seconds
  - Uses Nilearn for glass brain plotting with 2x2 view layout
- **Physio Visualization**:
  - Detects `{dataset}.physprep` folder automatically
  - Loads preprocessed physio signals (PPG, ECG, RSP, EDA) at 1000 Hz
  - Scrolling display with 5-second visible window
  - Event markers overlay (r-peaks, systolic peaks, respiration events)
  - Data synchronized to replay timing using onset from events file
- **Supported Games**: mario, mario3, mariostars, shinobi (auto-detected from filenames)
