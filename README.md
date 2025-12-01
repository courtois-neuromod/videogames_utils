# CNeuroMod Videogame Utils

Utilities for processing and analyzing CNeuroMod videogame data, including replay file processing, psychophysics measurements, and video generation.

## Installation

```bash
pip install git+https://github.com/cneuromod/videogames.utils.git
```

Or install from source:

```bash
git clone https://github.com/cneuromod/videogames.utils.git
cd videogames.utils
pip install -e .
```

## Requirements

- Python >= 3.9
- stable-retro
- numpy
- Pillow
- scikit-video
- opencv-python

## Features

### Replay Processing

Process and analyze BK2 replay files from retro game emulators:

```python
from cneuromod_vg_utils import replay_bk2

# Iterate through a replay file
for frame, keys, annotations, audio_chunk, audio_rate, truncate, actions, state in replay_bk2('replay.bk2'):
    # Process each frame
    print(f"Frame shape: {frame.shape}")
    print(f"Keys pressed: {keys}")
    print(f"Reward: {annotations['reward']}")
```

Extract complete replay data:

```python
from cneuromod_vg_utils.replay import get_variables_from_replay

# Get all replay data at once
rep_vars, info, frames, states, audio, audio_rate = get_variables_from_replay(
    'replay.bk2',
    skip_first_step=True,
    game='SuperMarioBros-Nes'
)
```

### Audio Processing

Export audio from replay files:

```python
from cneuromod_vg_utils.replay import write_wav

# Write audio to WAV file
write_wav(audio, audio_rate, 'output.wav')
```

### Psychophysics Analysis

Compute psychophysical measures from video and audio data:

```python
from cneuromod_vg_utils.psychophysics import (
    audio_envelope_per_frame,
    compute_luminance,
    compute_optical_flow
)

# Compute audio envelope synchronized to video frames
envelope = audio_envelope_per_frame(audio, sample_rate=32040, frame_rate=60.0)

# Compute luminance for each frame
luminance = compute_luminance(frames)

# Compute optical flow between consecutive frames
flow = compute_optical_flow(frames)
```

### Video Generation

Create video files from frame sequences:

```python
from cneuromod_vg_utils.video import make_mp4, make_gif, make_webp

# Create MP4 with audio
make_mp4(frames, 'output.mp4', audio=audio, sample_rate=32040, fps=60)

# Create GIF
make_gif(frames, 'output.gif')

# Create WebP animation
make_webp(frames, 'output.webp')
```

## Module Overview

### `replay.py`

Core replay functionality for processing BK2 files:

- `replay_bk2()` - Iterator for stepping through replay files
- `get_variables_from_replay()` - Extract complete replay data
- `reformat_info()` - Parse replay metadata from filenames
- `assemble_audio()` - Concatenate audio chunks
- `write_wav()` - Export audio to WAV format

### `psychophysics.py`

Psychophysical measurements for video game stimuli:

- `audio_envelope_per_frame()` - RMS-based audio envelope at frame rate
- `compute_luminance()` - Mean luminance per frame
- `compute_optical_flow()` - Frame-to-frame motion analysis

### `video.py`

Video file generation utilities:

- `make_mp4()` - Create MP4 files with optional audio
- `make_gif()` - Create GIF animations
- `make_webp()` - Create WebP animations

## CNeuroMod Integration

This package is designed for the CNeuroMod project's videogame data. Replay filenames are expected to follow the CNeuroMod naming convention:

```
sub-{subject}_ses-{session}_level-{level}_*.bk2
```

Metadata is automatically extracted from filenames using this convention.

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## Authors

CNeuroMod
