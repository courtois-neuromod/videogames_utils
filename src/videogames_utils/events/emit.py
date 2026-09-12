"""Helpers for building BIDS events DataFrames.

Replaces the ~40 lines of identical ``onset``/``duration``/``trial_type``/``level``/
``frame_start``/``frame_stop`` list-building that were copy-pasted into every generator
function of all four datasets' ``generate_annotations.py``.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

import pandas as pd

#: Authoritative frame rates, read from the emulator cores via
#: ``retro.make(game).em.get_screen_rate()``. The pipelines previously hardcoded 60.0,
#: which drifts by ~0.16% on NES/SNES and ~0.13% on Genesis -- up to ~0.6 s over the
#: longest repetitions, comparable to a TR.
FRAME_RATES = {
    "SuperMarioBros-Nes": 60.099826520671,
    "SuperMarioBros3-Nes": 60.099826520671,
    "SuperMarioAllStars-Snes": 60.098811862348,
    "ShinobiIIIReturnOfTheNinjaMaster-Genesis": 59.922743404312,
}

#: task name -> frame rate, for callers that only know the BIDS task label.
TASK_FRAME_RATES = {
    "mario": FRAME_RATES["SuperMarioBros-Nes"],
    "mario3": FRAME_RATES["SuperMarioBros3-Nes"],
    "mariostars": FRAME_RATES["SuperMarioAllStars-Snes"],
    "shinobi": FRAME_RATES["ShinobiIIIReturnOfTheNinjaMaster-Genesis"],
}

#: Canonical column order for the annotated events files.
#:
#: Deliberately minimal. Dropped in favour of the per-repetition sidecar or the event
#: name itself:
#:   phase, IndexInRun, IndexGlobal, IndexLevel -> already in gamelogs/*_summary.json
#:   enemy_type                                 -> now the last segment of trial_type
#:   value                                      -> only carried Enemy_counter, removed
#: `stim_file` is set on the gym-retro_game container row only; every other event sits
#: inside exactly one container window, so repeating the path on every row was noise.
COLUMNS = [
    "trial_type", "level", "onset", "duration", "frame_start", "frame_stop",
    "button", "stim_file",
]

#: Columns stored as nullable integers.
INT_COLUMNS = ["frame_start", "frame_stop"]


def empty_events() -> pd.DataFrame:
    """An empty events frame with the standard event columns."""
    return pd.DataFrame(columns=["onset", "duration", "trial_type", "level",
                                 "frame_start", "frame_stop"])


class EventAccumulator:
    """Collect events for one repetition, then emit them as a DataFrame.

    Onsets and durations are computed from ``fs``, so callers pass frame indices and
    never divide by a frame rate themselves.

    Example:
        acc = EventAccumulator(level="w1l1", fs=60.0998)
        acc.add("Item_collected/Coin", frame)
        acc.add("Enemy_appeared/Goomba", start, stop)
        df = acc.to_frame()
    """

    def __init__(self, level, fs: float, **defaults):
        self.level = level
        self.fs = fs
        self.defaults = defaults
        self._rows: List[dict] = []

    def add(self, trial_type: str, frame_start: int,
            frame_stop: Optional[int] = None, **extra) -> None:
        """Record one event spanning ``frame_start``..``frame_stop`` (inclusive).

        A point event omits ``frame_stop`` and gets duration 0.
        """
        stop = frame_start if frame_stop is None else frame_stop
        self._rows.append({
            "onset": frame_start / self.fs,
            "duration": (stop - frame_start) / self.fs,
            "trial_type": trial_type,
            "level": self.level,
            "frame_start": int(frame_start),
            "frame_stop": int(stop),
            **self.defaults,
            **extra,
        })

    def extend(self, rows: Iterable[dict]) -> None:
        self._rows.extend(rows)

    def __len__(self) -> int:
        return len(self._rows)

    def to_frame(self) -> pd.DataFrame:
        if not self._rows:
            return empty_events()
        return pd.DataFrame(self._rows)


def finalize(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate per-repetition frames into the final run-level events table.

    Sorts by onset, rounds the time columns, coerces the integer columns and applies the
    canonical column order.
    """
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame()

    # Sort by onset, but keep the gym-retro_game container first among rows that share
    # one. Level_started sits at frame 0 of a repetition and therefore ties with its own
    # container; if it sorted ahead, consumers that slice between container rows (the
    # videogames_utils GUI does exactly this) would file it under the previous repetition.
    events = pd.concat(frames)
    events["_container_first"] = (events["trial_type"] != "gym-retro_game").astype(int)
    events = (events.sort_values(by=["onset", "_container_first"], kind="stable")
                    .drop(columns="_container_first")
                    .reset_index(drop=True))
    events["onset"] = events["onset"].round(3)
    events["duration"] = events["duration"].round(3)

    for col in INT_COLUMNS:
        if col in events.columns:
            events[col] = events[col].astype("Int64")

    ordered = [c for c in COLUMNS if c in events.columns]
    rest = [c for c in events.columns if c not in ordered]
    return events[ordered + rest]
