"""Run-length helpers for the durational ``Player_state/*`` events.

A state row covers one continuous stretch of a RAM signal. Two operations are needed
everywhere: finding those stretches, and cutting a stretch short at the player's death,
since a form or timer that the game leaves set through the death animation is not a
state the player is in.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple


def nonzero_runs(series: Sequence, split_on_value_change: bool = True
                 ) -> List[Tuple[int, int, int]]:
    """Maximal runs of non-zero values as ``(first_frame, last_frame, value)``.

    With ``split_on_value_change`` a run ends when the value changes, so a form variable
    going 0 -> 1 -> 2 -> 0 yields one run per form. Without it (timers, whose value
    changes every frame) a run ends only when the series returns to zero, and ``value``
    is the run's first value.
    """
    out = []
    start = None
    for frame, value in enumerate(series):
        if value:
            if start is None:
                start = frame
            elif split_on_value_change and value != series[frame - 1]:
                out.append((start, frame - 1, series[start]))
                start = frame
        elif start is not None:
            out.append((start, frame - 1, series[start]))
            start = None
    if start is not None:
        out.append((start, len(series) - 1, series[start]))
    return out


def clip(start: int, stop: int, cuts: Iterable[int]) -> int:
    """``stop``, brought forward to the frame before the first cut inside ``(start, stop]``.

    A run that begins at or after a cut is left alone: only a death that falls inside a
    stretch ends it, so a row is never dropped and the number of rows always equals the
    number of runs in the RAM series.
    """
    inside = [c for c in cuts if start < c <= stop]
    return min(inside) - 1 if inside else stop


def constant_runs(series: Sequence, keep: Optional[Sequence[bool]] = None
                  ) -> List[Tuple[int, int, object]]:
    """Maximal runs of a constant value as ``(first_frame, last_frame, value)``.

    Unlike :func:`nonzero_runs`, zero is a value like any other, so the runs tile the
    whole series. With ``keep`` (one boolean per frame) frames where it is False belong
    to no run, and a run is cut there: this is how the form rows are restricted to the
    frames where the player is alive in the level.
    """
    out = []
    start = None
    for frame, value in enumerate(series):
        kept = keep is None or keep[frame]
        if start is not None and (not kept or value != series[start]):
            out.append((start, frame - 1, series[start]))
            start = None
        if kept and start is None:
            start = frame
    if start is not None:
        out.append((start, len(series) - 1, series[start]))
    return out
