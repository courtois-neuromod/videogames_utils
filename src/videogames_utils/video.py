import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

import numpy as np
from moviepy.editor import ImageSequenceClip, AudioFileClip
from PIL import Image

from .replay import write_wav


def make_gif(selected_frames, movie_fname):
    """Create a GIF file from a list of frames."""
    frame_list = [Image.fromarray(np.uint8(img), "RGB") for img in selected_frames]

    if not frame_list:
        logging.warning(f"No frames to save in {movie_fname}")
        return

    frame_list[0].save(
        movie_fname,
        save_all=True,
        append_images=frame_list[1:],
        optimize=False,
        duration=16,
        loop=0,
    )


def make_mp4(
    selected_frames: Iterable[np.ndarray],
    movie_fname: str,
    *,
    audio: np.ndarray | None = None,
    sample_rate: int | None = None,
    fps: int = 60,
) -> None:
    """Create an MP4 file from a list of frames, with optional audio multiplexing using moviepy."""

    # Convert frames to list if not already (moviepy needs list)
    frame_list = list(selected_frames)

    # Convert frames to RGB format expected by moviepy
    processed_frames = []
    for frame in frame_list:
        im = Image.new("RGB", (frame.shape[1], frame.shape[0]), color="white")
        im.paste(Image.fromarray(frame), (0, 0))
        processed_frames.append(np.array(im))

    # Create video clip from frames
    clip = ImageSequenceClip(processed_frames, fps=fps)

    final_path = Path(movie_fname)

    if audio is None or sample_rate is None:
        # Write video without audio
        clip.write_videofile(str(final_path), codec='libx264', audio=False, logger=None)
        clip.close()
        return

    # Handle audio
    temp_dir = tempfile.mkdtemp(prefix="videogames_utils_")
    temp_audio = Path(temp_dir) / "audio.wav"

    try:
        if audio.dtype != np.int16:
            logging.info("Casting audio to int16 before saving")
            audio = audio.astype(np.int16)

        write_wav(audio, sample_rate, str(temp_audio))

        # Add audio to video clip
        audio_clip = AudioFileClip(str(temp_audio))
        clip = clip.set_audio(audio_clip)

        # Write final video with audio
        clip.write_videofile(str(final_path), codec='libx264', audio_codec='aac', logger=None)

    finally:
        clip.close()
        try:
            temp_audio.unlink(missing_ok=True)
            os.rmdir(temp_dir)
        except OSError:
            pass


def make_webp(selected_frames, movie_fname):
    """Create a WebP file from a list of frames."""
    frame_list = [Image.fromarray(np.uint8(img), "RGB") for img in selected_frames]

    if not frame_list:
        logging.warning(f"No frames to save in {movie_fname}")
        return

    frame_list[0].save(
        movie_fname,
        "WEBP",
        quality=50,
        lossless=False,
        save_all=True,
        append_images=frame_list[1:],
        duration=16,
        loop=0,
    )
