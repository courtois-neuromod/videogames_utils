"""Remove the extra first input line from the first .bk2 of each run.

Why: until task_stimuli 70cab45ba (2023-02-14, "fix overwrite of first rep"), the first
recording of a run was opened before the run's first ``emulator.reset()``, and that reset
wrote one extra, empty input line at the start of the file. Later repetitions of a run, and
every recording made after the fix, start clean.

Which file, per run. Only the plain ``*_events.tsv`` are read: ``desc-*`` files are derived
from the replays of these recordings, so they must not decide which recordings change.

* the ``stim_file`` of the run's first ``gym-retro_game`` row;
* nothing if that row is "Missing file" or empty: the extra line was in the lost recording,
  and the next repetition starts clean;
* nothing if the .bk2 was written on or after the fix date. A .bk2's zip entries carry the
  time it was written, so this also skips any file that was already rewritten (stripped);
* nothing if the task logged ``nframes`` and the .bk2 does not have exactly ``nframes + 1``
  input lines;
* an error if the line to remove presses a button: the reset's line is always empty.

Each file is stripped at most once, and running the script again changes nothing.

Usage, from the dataset root (e.g. through ``datalad run``):
    python code/videogames_utils/src/videogames_utils/strip_extra_step.py . [--dry-run]
"""
import argparse
import datetime
import glob
import os
import sys
import tempfile
import zipfile

import pandas as pd

#: Date of task_stimuli 70cab45ba; recordings written from that day on have no extra line.
FIX_DATE = datetime.date(2023, 2, 14)
GAME_ROW = "gym-retro_game"

env = None


def _frame_lines(bk2):
    with zipfile.ZipFile(bk2) as z:
        text = z.read("Input Log.txt").decode("utf-8", "replace")
    return [line for line in text.splitlines() if line.startswith("|")]


def written_on(bk2):
    """Date the .bk2 was written, from its zip entries."""
    with zipfile.ZipFile(bk2) as z:
        return datetime.date(*min(i.date_time for i in z.infolist())[:3])


def is_missing(stim):
    return not isinstance(stim, str) or stim.strip().lower() in ("", "missing file", "n/a", "nan")


def plan(root, fix_date=FIX_DATE):
    """One ``(events file, .bk2 or None, decision)`` per run; decision is "strip", "skip: ..." or "ERROR: ..."."""
    rows = []
    for evt in sorted(glob.glob(os.path.join(root, "sub-*", "ses-*", "func", "*_events.tsv"))):
        rel = os.path.relpath(evt, root)
        if "_desc-" in os.path.basename(evt):
            continue
        try:
            events = pd.read_csv(evt, sep="\t")
        except pd.errors.EmptyDataError:
            rows.append((rel, None, "skip: empty events file"))
            continue
        if not {"trial_type", "stim_file"} <= set(events.columns):
            rows.append((rel, None, "skip: no trial_type/stim_file columns"))
            continue
        games = events[events["trial_type"] == GAME_ROW]
        if games.empty:
            rows.append((rel, None, f"skip: no {GAME_ROW} row"))
            continue
        first = games.iloc[0]
        stim = first["stim_file"]
        if is_missing(stim):
            rows.append((rel, None, "skip: first repetition is missing (the extra line was in that file)"))
            continue
        path = os.path.join(root, stim)
        if not os.path.exists(path):
            rows.append((rel, stim, "ERROR: .bk2 content not available"))
            continue
        written = written_on(path)
        if written >= fix_date:
            rows.append((rel, stim, f"skip: written {written}, on or after {fix_date} "
                                    "(recorded after the fix, or already rewritten)"))
            continue
        lines = _frame_lines(path)
        nframes = pd.to_numeric(first.get("nframes"), errors="coerce")
        if pd.notna(nframes) and len(lines) != int(nframes) + 1:
            rows.append((rel, stim, f"skip: {len(lines)} input lines for nframes={int(nframes)}, no extra line"))
            continue
        if not lines or not set(lines[0]) <= set("|."):
            rows.append((rel, stim, "ERROR: first input line presses buttons, so it is not the reset's line"))
            continue
        rows.append((rel, stim, "strip"))
    return rows


def strip_first_step(bk2_in: str, bk2_out: str = None, strip_n_steps: int = 1):
    """Write ``bk2_in`` without its first ``strip_n_steps`` input lines to ``bk2_out`` (default: in place).

    The start state and the header are kept. The output is written to a temporary file next to
    ``bk2_out`` and moved over it at the end, so an interrupted run leaves the file untouched.
    """
    global env
    import stable_retro as retro

    bk2_out = bk2_out or bk2_in
    movie_in = retro.Movie(bk2_in)
    for _ in range(strip_n_steps):
        movie_in.step()
    if env is None or env.gamename != movie_in.get_game():
        if env is not None:
            env.close()
        # The environment only provides the game name, the core and the button count: no state needed.
        env = retro.make(movie_in.get_game(), state=retro.State.NONE, render_mode=None)

    fd, tmp = tempfile.mkstemp(suffix=".bk2", dir=os.path.dirname(os.path.abspath(bk2_out)))
    os.close(fd)
    try:
        movie_out = retro.Movie(tmp, True, movie_in.players)
        movie_out.configure(env.gamename, env.em)
        movie_out.set_state(movie_in.get_state())
        while movie_in.step():
            for player in range(movie_in.players):
                for button in range(env.num_buttons):
                    movie_out.set_key(button, movie_in.get_key(button, player), player)
            movie_out.step()
        movie_out.close()
        movie_in.close()
        os.replace(tmp, bk2_out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Remove the extra first input line from the first .bk2 of each run.")
    parser.add_argument("root", help="dataset root")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    parser.add_argument("--fix-date", type=datetime.date.fromisoformat, default=FIX_DATE,
                        help=f"recordings written on or after this date are left alone (default: {FIX_DATE})")
    args = parser.parse_args(argv)

    rows = plan(args.root, args.fix_date)
    targets = sorted({stim for _, stim, decision in rows if decision == "strip"})
    errors = [row for row in rows if row[2].startswith("ERROR")]
    print("events_file\tbk2\tdecision")
    for evt, stim, decision in rows:
        print(f"{evt}\t{stim or 'n/a'}\t{decision}")
    print(f"# {len(rows)} runs, {len(targets)} file(s) to strip, {len(errors)} error(s)", file=sys.stderr)
    if errors:
        return 1
    if args.dry_run or not targets:
        return 0

    import stable_retro as retro
    retro.data.add_custom_integration(os.path.abspath(os.path.join(args.root, "stimuli")))
    for stim in targets:
        path = os.path.join(args.root, stim)
        before = len(_frame_lines(path))
        strip_first_step(path)
        after = len(_frame_lines(path))
        if after != before - 1:
            print(f"ERROR: {stim}: {before} -> {after} input lines", file=sys.stderr)
            return 1
    print(f"# stripped {len(targets)} file(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
