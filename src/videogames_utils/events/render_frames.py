"""Render selected frames of a ``.bk2`` replay to PNG, using the dataset's own integration.

The quickest way to check what an event boundary actually looks like on screen: pick the
frame indices from a ``_variables.json`` or an annotated events file (``frame_start`` /
``frame_stop``, relative to the repetition) and look at the images.

    python -m videogames_utils.events.render_frames /path/to/mario \\
        sub-01/ses-015/gamelogs/sub-01_ses-015_task-mario_level-w1l1_rep-000.bk2 \\
        0,118,124,1888 --check player_state,time --out /tmp/frames

Frame indices follow the ``_variables.json`` convention: the first repetition of a run
(``IndexInRun`` 0 in its ``_summary.json``) skips the movie's first step, as
``generate_replays.py`` does. ``--check`` prints the emulator's value of each named
variable next to the stored one at every rendered frame, which confirms the alignment.
"""

from __future__ import annotations

import argparse
import json
import os
import os.path as op
import sys
import warnings

import stable_retro as retro
from PIL import Image

from ..replay import replay_bk2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset_dir")
    ap.add_argument("bk2", help="path of the .bk2, relative to the dataset")
    ap.add_argument("frames", help="comma-separated frame indices")
    ap.add_argument("--check", default="", help="comma-separated variables to print")
    ap.add_argument("--out", default="frames", help="output directory")
    args = ap.parse_args(argv)

    frames = sorted(int(x) for x in args.frames.split(","))
    check = [c for c in args.check.split(",") if c]
    bk2 = op.join(args.dataset_dir, args.bk2)
    with open(bk2.replace(".bk2", "_summary.json")) as f:
        summary = json.load(f)
    with open(bk2.replace(".bk2", "_variables.json")) as f:
        stored = json.load(f)
    skip = summary.get("IndexInRun", 0) == 0
    stimuli = op.abspath(op.join(args.dataset_dir, "stimuli"))
    game = [g for g in os.listdir(stimuli) if op.isfile(op.join(stimuli, g, "data.json"))][0]
    retro.data.Integrations.add_custom_path(stimuli)
    os.makedirs(args.out, exist_ok=True)
    base = op.basename(bk2).replace(".bk2", "")
    print(f"{base}: skip_first_step={skip} game={game} "
          f"n_stored={len(stored.get('score') or stored.get('health'))}")

    want, last = set(frames), max(frames)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for i, (frame, _keys, ann, *_rest) in enumerate(
                replay_bk2(bk2, skip_first_step=skip, game=game, check_done=False)):
            if i in want:
                Image.fromarray(frame).save(op.join(args.out, f"{base}_f{i:05d}.png"))
                if check:
                    pairs = [f"{k}={ann['info'].get(k)}/"
                             f"{stored[k][i] if k in stored else None}" for k in check]
                    print(f"  f{i}: " + " ".join(pairs))
            if i >= last:
                break
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
