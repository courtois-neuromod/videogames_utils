"""Command line entry point for the events validation layers.

    # V0 + V1 over one dataset
    python -m videogames_utils.events.validate_cli check /path/to/mario

    # V2: two datasets of the same game, e.g. mario vs mariostars (two SMB1 ports)
    python -m videogames_utils.events.validate_cli cross-port /path/to/mario /path/to/mariostars

    # V4: write or check a dataset's golden regression fixtures (Game.golden_sessions)
    python -m videogames_utils.events.validate_cli golden-write /path/to/mario /path/to/fixtures
    python -m videogames_utils.events.validate_cli golden-check /path/to/mario /path/to/fixtures
"""

from __future__ import annotations

import argparse
import collections
import os
import os.path as op
import re
import sys
from glob import glob

import pandas as pd

from . import validation
from .game import load_game


def _level_rosters(events_dir: str) -> dict:
    """level -> Counter of enemy types seen, aggregated over a dataset.

    The level is the ``level-`` entity of each repetition's ``.bk2``.
    """
    rosters = collections.defaultdict(collections.Counter)
    for path in sorted(glob(op.join(events_dir, "sub-*", "ses-*", "func",
                                    "*_desc-annotated_events.tsv"))):
        events = pd.read_csv(path, sep="\t")
        for stim, rows in validation._repetition_windows(events):
            match = re.search(r"_level-([^_]+)_", str(stim))
            if not match:
                continue
            rows = rows[rows["trial_type"].astype(str).str.startswith("EnemyOnScreen/")]
            rosters[match.group(1)].update(rows["trial_type"].str.split("/").str[1])
    return rosters


def cmd_check(args) -> int:
    report = validation.validate_dataset(args.dataset_dir, load_game(args.dataset_dir),
                                         limit=args.limit,
                                         with_invariants=not args.no_invariants)
    print(report.summary())
    for finding in report.findings[:args.max_findings]:
        print("\n" + str(finding))
    extra = len(report.findings) - args.max_findings
    if extra > 0:
        print(f"\n... and {extra} more")
    return 1 if report.errors else 0


def cmd_cross_port(args) -> int:
    """V2: two datasets of the same game should meet the same enemies on the same levels."""
    report = validation.Report()
    a_name = load_game(args.a_dir).task
    b_name = load_game(args.b_dir).task
    a_rosters = _level_rosters(args.a_dir)
    b_rosters = _level_rosters(args.b_dir)
    validation.check_cross_port(a_name, a_rosters, b_name, b_rosters, report)

    shared = sorted(set(a_rosters) & set(b_rosters))
    print(f"levels in {a_name}: {len(a_rosters)}, {b_name}: {len(b_rosters)}, "
          f"shared: {len(shared)}")
    for level in shared:
        a, b = set(a_rosters[level]), set(b_rosters[level])
        mark = "ok " if a == b else "DIFF"
        print(f"  [{mark}] {level:<8} {a_name}={sorted(a)}")
        if a != b:
            print(f"           {'':<8} {b_name}={sorted(b)}")
    print("\n" + report.summary())
    return 0


def _fixture_name(task, sub, ses):
    return f"{task}_{sub}_{ses}_desc-annotated_events.tsv"


def _golden_paths(dataset_dir: str):
    """(task, annotated events file) for each of the dataset's golden sessions."""
    game = load_game(dataset_dir)
    for sub, ses in game.golden_sessions:
        for path in sorted(glob(op.join(dataset_dir, sub, ses, "func",
                                        "*_desc-annotated_events.tsv"))):
            yield game.task, path


def cmd_golden_write(args) -> int:
    os.makedirs(args.fixtures_dir, exist_ok=True)
    written = 0
    for task, path in _golden_paths(args.dataset_dir):
        dest = op.join(args.fixtures_dir,
                       f"{task}_{op.basename(path)}")
        pd.read_csv(path, sep="\t").to_csv(dest, sep="\t", index=False)
        written += 1
        print(f"  froze {dest}")
    print(f"{written} fixture(s) written")
    return 0


def cmd_golden_check(args) -> int:
    bad = 0
    checked = 0
    for task, path in _golden_paths(args.dataset_dir):
        golden = op.join(args.fixtures_dir, f"{task}_{op.basename(path)}")
        if not op.exists(golden):
            continue
        checked += 1
        current = pd.read_csv(path, sep="\t")
        expected = pd.read_csv(golden, sep="\t")
        if current.equals(expected):
            continue
        bad += 1
        print(f"\nDIFF {op.basename(path)}")
        if len(current) != len(expected):
            print(f"  row count {len(expected)} -> {len(current)}")
        cur_counts = collections.Counter(current["trial_type"])
        exp_counts = collections.Counter(expected["trial_type"])
        for key in sorted(set(cur_counts) | set(exp_counts)):
            if cur_counts[key] != exp_counts[key]:
                print(f"  {key:<34} {exp_counts[key]} -> {cur_counts[key]}")
    print(f"\n{checked} fixture(s) checked, {bad} changed")
    return 1 if bad else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="V0 + V1 over one dataset")
    p.add_argument("dataset_dir")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-invariants", action="store_true")
    p.add_argument("--max-findings", type=int, default=40)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("cross-port", help="V2: two datasets of the same game")
    p.add_argument("a_dir")
    p.add_argument("b_dir")
    p.set_defaults(func=cmd_cross_port)

    p = sub.add_parser("golden-write", help="freeze regression fixtures")
    p.add_argument("dataset_dir")
    p.add_argument("fixtures_dir")
    p.set_defaults(func=cmd_golden_write)

    p = sub.add_parser("golden-check", help="diff against the frozen fixtures")
    p.add_argument("dataset_dir")
    p.add_argument("fixtures_dir")
    p.set_defaults(func=cmd_golden_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
