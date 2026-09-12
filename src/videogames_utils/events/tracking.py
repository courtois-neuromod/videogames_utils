"""On-screen object tracking for the ``Enemy_*`` events.

Semantics, as specified for these datasets:

* An object's event starts when it becomes **visible on screen** and ends when it leaves
  the screen (or is defeated).
* An object that moves between RAM slots without leaving the screen is **one** event.
* An object that leaves the screen and comes back is **two** events.

The slot-migration diagnostic over 10 mario replays found 2 candidate migrations in 274
visible appearances (0.73%), both in a water level where same-type enemies spawn
continuously and are more likely detector false positives than real migrations. The
tracker is therefore built per-slot, with an optional position-based merge for the games
where per-slot coordinates exist (mario, mario3). mariostars has no per-slot coordinates
and does not need them.

A short debounce merges runs separated by a few frames, because a one-frame flicker of
the slot bookkeeping is not a disappearance the player perceives.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

#: Frames of invisibility tolerated inside a single track (~67 ms at 60 fps).
DEFAULT_DEBOUNCE = 4

#: Tracks shorter than this are dropped as slot churn rather than perceived objects.
#: Spawner objects (e.g. SMB1's BulletBillCannon) produce runs of a single frame.
DEFAULT_MIN_FRAMES = 5


@dataclass
class Track:
    """One object's continuous visible presence on screen.

    Attributes:
        slot: RAM slot the object occupied when it appeared.
        type_id: Object id at appearance.
        frame_start: First visible frame.
        frame_stop: Last visible frame.
        type_ids: Every id the slot held during the track, in order of first appearance.
            A Green Paratroopa stomped into a Green Koopa changes id mid-track without
            leaving the screen, so this is not always a single value.
        ended_defeated: Set by the caller when the track ended in a defeat rather than
            the object leaving the screen.
    """

    slot: int
    type_id: int
    frame_start: int
    frame_stop: int
    type_ids: List[int]
    ended_defeated: bool = False
    #: ``(frame, method)`` of the defeat that ended this track, when it ended in one.
    defeat: Optional[tuple] = None

    @property
    def n_frames(self) -> int:
        return self.frame_stop - self.frame_start + 1

    @property
    def changed_type(self) -> bool:
        return len(self.type_ids) > 1


def find_tracks(
    n_frames: int,
    n_slots: int,
    visible: Callable[[int, int], bool],
    type_id: Callable[[int, int], int],
    debounce: int = DEFAULT_DEBOUNCE,
    min_frames: int = DEFAULT_MIN_FRAMES,
    keep: Optional[Callable[[int], bool]] = None,
) -> List[Track]:
    """Build tracks from per-frame, per-slot visibility.

    Args:
        n_frames: Number of frames in the repetition.
        n_slots: Number of object slots.
        visible: ``visible(slot, frame)`` -> is this slot showing an object on screen?
        type_id: ``type_id(slot, frame)`` -> the object id in this slot on this frame.
        debounce: Merge two runs in the same slot separated by at most this many
            invisible frames, provided the type is unchanged.
        min_frames: Drop tracks shorter than this.
        keep: Optional filter on the track's type id; tracks whose id fails it are
            dropped (used to exclude spawners, platforms and scenery).

    Returns:
        Tracks sorted by onset frame.
    """
    tracks: List[Track] = []

    for slot in range(n_slots):
        current: Optional[Track] = None
        gap = 0
        for frame in range(n_frames):
            if visible(slot, frame):
                tid = type_id(slot, frame)
                if current is None:
                    current = Track(slot, tid, frame, frame, [tid])
                else:
                    current.frame_stop = frame
                    if tid != current.type_ids[-1]:
                        current.type_ids.append(tid)
                gap = 0
            elif current is not None:
                gap += 1
                if gap > debounce:
                    tracks.append(current)
                    current = None
                    gap = 0
        if current is not None:
            tracks.append(current)

    if keep is not None:
        tracks = [t for t in tracks if keep(t.type_id)]
    tracks = [t for t in tracks if t.n_frames >= min_frames]
    tracks.sort(key=lambda t: (t.frame_start, t.slot))
    return tracks


def counter_series(
    n_frames: int,
    n_slots: int,
    visible: Callable[[int, int], bool],
    keep: Optional[Callable[[int, int], bool]] = None,
) -> List[tuple]:
    """Number of visible objects per frame, as change points.

    Args:
        keep: Optional ``keep(slot, frame)`` filter applied on top of ``visible``.

    Returns:
        A list of ``(frame_start, frame_stop, count)`` spans covering every frame, where
        the count is constant within each span. Spans are contiguous and non-empty.
    """
    spans: List[tuple] = []
    prev_count = None
    start = 0
    for frame in range(n_frames):
        count = 0
        for slot in range(n_slots):
            if visible(slot, frame) and (keep is None or keep(slot, frame)):
                count += 1
        if prev_count is None:
            prev_count = count
        elif count != prev_count:
            spans.append((start, frame - 1, prev_count))
            start = frame
            prev_count = count
    if prev_count is not None and n_frames:
        spans.append((start, n_frames - 1, prev_count))
    return spans


def merge_across_slots(tracks: Sequence[Track],
                       position: Callable[[int, int], Optional[int]],
                       max_gap: int = 3,
                       max_distance: int = 8) -> List[Track]:
    """Merge tracks that are the same object handed between RAM slots.

    Two tracks merge when the later one starts within ``max_gap`` frames of the earlier
    one ending, they carry the same type id, and their world positions at the handover
    are within ``max_distance`` pixels.

    Only meaningful for games with per-slot coordinates (mario, mario3). Measured at
    ~0.7% of appearances in mario, so this is a refinement rather than a load-bearing
    step; mariostars omits it entirely.
    """
    remaining = sorted(tracks, key=lambda t: (t.frame_start, t.slot))
    merged: List[Track] = []
    consumed = set()

    for i, track in enumerate(remaining):
        if i in consumed:
            continue
        current = track
        changed = True
        while changed:
            changed = False
            for j in range(i + 1, len(remaining)):
                if j in consumed:
                    continue
                other = remaining[j]
                if other.slot == current.slot:
                    continue
                if not (0 <= other.frame_start - current.frame_stop <= max_gap):
                    continue
                if other.type_id != current.type_ids[-1]:
                    continue
                a = position(current.slot, current.frame_stop)
                b = position(other.slot, other.frame_start)
                if a is None or b is None or abs(a - b) > max_distance:
                    continue
                current.frame_stop = other.frame_stop
                for tid in other.type_ids:
                    if tid != current.type_ids[-1]:
                        current.type_ids.append(tid)
                current.ended_defeated = other.ended_defeated
                consumed.add(j)
                changed = True
        merged.append(current)

    merged.sort(key=lambda t: (t.frame_start, t.slot))
    return merged
