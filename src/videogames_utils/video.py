import itertools
import logging
import os
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Iterable

import numpy as np
import imageio_ffmpeg
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
    fps: float,
) -> None:
    """Create an MP4 file from a list of frames, with optional audio multiplexing.

    ``fps`` is required and should be the emulator's native frame rate (see
    ``videogames_utils.events.emit.FRAME_RATES``). The emulator's audio already plays at
    that rate, so writing the frames at a nominal 60 fps makes the video stream drift
    away from its own audio track and from the events timeline.

    Frames are piped to ffmpeg directly rather than through moviepy, which rounds the
    frame rate to two decimals and resamples frames by timestamp, silently dropping the
    last one. Here every frame is written once, at the exact (rational) rate.
    """
    frames = iter(selected_frames)
    first = next(frames, None)
    if first is None:
        logging.warning(f"No frames to save in {movie_fname}")
        return
    height, width = first.shape[:2]
    rate = Fraction(fps).limit_denominator(1_000_000)

    temp_dir = tempfile.mkdtemp(prefix="videogames_utils_")
    temp_audio = Path(temp_dir) / "audio.wav"
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
        "-framerate", f"{rate.numerator}/{rate.denominator}", "-i", "pipe:0",
    ]
    try:
        if audio is not None and sample_rate is not None:
            if audio.dtype != np.int16:
                logging.info("Casting audio to int16 before saving")
                audio = audio.astype(np.int16)
            write_wav(audio, sample_rate, str(temp_audio))
            cmd += ["-i", str(temp_audio), "-c:a", "aac", "-ar", "44100"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(movie_fname)]

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for frame in itertools.chain([first], frames):
                proc.stdin.write(np.ascontiguousarray(frame[..., :3], dtype=np.uint8).tobytes())
        except BrokenPipeError:
            pass  # ffmpeg exited early; its stderr is reported below
        finally:
            proc.stdin.close()
        stderr = proc.stderr.read()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed writing {movie_fname}: {stderr.decode(errors='replace')}")
    finally:
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
