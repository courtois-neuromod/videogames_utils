"""Command line entry point for the events validation layers.

    # V0 + V1 over one dataset
    python -m videogames_utils.events.validate_cli check /path/to/mario mario

    # V2: mario vs mariostars, the same SMB1 levels on two consoles
    python -m videogames_utils.events.validate_cli cross-port /path/to/mario /path/to/mariostars

    # V4: write or check the golden regression fixtures
    python -m videogames_utils.events.validate_cli golden-write  /path/to/fixtures
    python -m videogames_utils.events.validate_cli golden-check  /path/to/fixtures
"""

from __future__ import annotations

import argparse
import collections
import os
import os.path as op
import sys
from glob import glob

import pandas as pd

from . import validation

#: The repetitions frozen as golden fixtures: broad coverage in a handful of files.
GOLDEN_SPEC = [
    ("mario", "sub-01", "ses-001"),
    ("mario3", "sub-03", "ses-013"),
    ("mariostars", "sub-03", "ses-006"),
    ("shinobi", "sub-01", "ses-002"),
]

ROOT = os.environ.get("VG_DATASETS_ROOT", "/home/hyruuk/DATA/neuromod")


def _level_rosters(events_dir: str) -> dict:
    """level -> Counter of enemy types seen, aggregated over a dataset."""
    rosters = collections.defaultdict(collections.Counter)
    for path in sorted(glob(op.join(events_dir, "sub-*", "ses-*", "func",
                                    "*_desc-annotated_events.tsv"))):
        events = pd.read_csv(path, sep="\t")
        rows = events[events["trial_type"].astype(str).str.startswith("Enemy_appeared/")]
        for level, group in rows.groupby("level"):
            rosters[str(level)].update(group["trial_type"].str.split("/").str[1])
    return rosters


def cmd_check(args) -> int:
    report = validation.validate_dataset(args.dataset_dir, args.task, limit=args.limit,
                                         with_invariants=not args.no_invariants)
    print(report.summary())
    for finding in report.findings[:args.max_findings]:
        print("\n" + str(finding))
    extra = len(report.findings) - args.max_findings
    if extra > 0:
        print(f"\n... and {extra} more")
    return 1 if report.errors else 0


def cmd_cross_port(args) -> int:
    """V2: the two SMB1 ports should meet the same enemies on the same levels."""
    report = validation.Report()
    mario = _level_rosters(args.mario_dir)
    stars = _level_rosters(args.mariostars_dir)
    validation.check_cross_port(mario, stars, report)

    shared = sorted(set(mario) & set(stars))
    print(f"levels in mario: {len(mario)}, mariostars: {len(stars)}, shared: {len(shared)}")
    for level in shared:
        a, b = set(mario[level]), set(stars[level])
        mark = "ok " if a == b else "DIFF"
        print(f"  [{mark}] {level:<8} mario={sorted(a)}")
        if a != b:
            print(f"           {'':<8} stars={sorted(b)}")
    print("\n" + report.summary())
    return 0


def _fixture_name(task, sub, ses):
    return f"{task}_{sub}_{ses}_desc-annotated_events.tsv"


def cmd_golden_write(args) -> int:
    os.makedirs(args.fixtures_dir, exist_ok=True)
    written = 0
    for task, sub, ses in GOLDEN_SPEC:
        for path in sorted(glob(op.join(ROOT, task, sub, ses, "func",
                                        "*_desc-annotated_events.tsv"))):
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
    for task, sub, ses in GOLDEN_SPEC:
        for path in sorted(glob(op.join(ROOT, task, sub, ses, "func",
                                        "*_desc-annotated_events.tsv"))):
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
    p.add_argument("task", choices=["mario", "mariostars", "mario3", "shinobi"])
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-invariants", action="store_true")
    p.add_argument("--max-findings", type=int, default=40)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("cross-port", help="V2 mario vs mariostars")
    p.add_argument("mario_dir")
    p.add_argument("mariostars_dir")
    p.set_defaults(func=cmd_cross_port)

    p = sub.add_parser("golden-write", help="freeze regression fixtures")
    p.add_argument("fixtures_dir")
    p.set_defaults(func=cmd_golden_write)

    p = sub.add_parser("golden-check", help="diff against the frozen fixtures")
    p.add_argument("fixtures_dir")
    p.set_defaults(func=cmd_golden_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
