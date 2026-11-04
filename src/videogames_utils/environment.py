"""Check that a dataset's outputs are made in the environment its repository pins.

A dataset's replays and annotations are reproducible when they are made from the data and
code of one commit of its repository, with the videogames_utils commit recorded as its
``code/videogames_utils`` submodule, the game integration of its ``stimuli`` subdataset,
and the Python packages of ``requirements.lock``. :func:`check` stops a pipeline that
would run in any other environment, unless it is explicitly allowed to.
"""

from __future__ import annotations

import importlib.metadata as metadata
import inspect
import os.path as op
import subprocess
import sys
from typing import List, Optional

from packaging.markers import Marker

import videogames_utils

#: The Python version the lock was made for.
PYTHON = (3, 12)
#: The exact package versions, at the root of the videogames_utils repository.
LOCK = op.join(op.dirname(op.dirname(op.dirname(op.abspath(__file__)))), "requirements.lock")
#: Where a dataset keeps videogames_utils and the game integration, relative to its root.
SUBMODULE = op.join("code", "videogames_utils")
STIMULI = "stimuli"


def code_dataset(game) -> str:
    """The root of the dataset whose ``code/game_specific/`` provides ``game``."""
    path = op.abspath(inspect.getsourcefile(game.generate))
    return op.dirname(op.dirname(op.dirname(path)))


def _git(*args: str, cwd: str) -> Optional[str]:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def _lock_problems() -> List[str]:
    if not op.exists(LOCK):
        return [f"no {LOCK}"]
    out = []
    with open(LOCK) as handle:
        for line in handle:
            requirement = line.split("#", 1)[0].strip()
            if "==" not in requirement:
                continue
            spec, _, marker = requirement.partition(";")
            if marker.strip() and not Marker(marker).evaluate():
                continue
            name, version = (part.strip() for part in spec.split("=="))
            try:
                installed = metadata.version(name)
            except metadata.PackageNotFoundError:
                out.append(f"{name} {version} is not installed")
                continue
            if installed != version:
                out.append(f"{name} is {installed}, requirements.lock pins {version}")
    return out


def problems(code_dir: str, data_dir: str, stimuli_dir: Optional[str] = None) -> List[str]:
    """Every way the running environment differs from the dataset's pinned one."""
    code_dir, data_dir = op.realpath(code_dir), op.realpath(data_dir)
    out = []
    if data_dir != code_dir:
        out.append(f"the data ({data_dir}) is not in the repository of the code ({code_dir})")
    if stimuli_dir and op.realpath(stimuli_dir) != op.join(code_dir, STIMULI):
        out.append(f"the game integration is read from {stimuli_dir}, not from the "
                   f"dataset's {STIMULI}")
    if sys.version_info[:2] != PYTHON:
        out.append(f"Python is {sys.version.split()[0]}, the lock is for "
                   f"{PYTHON[0]}.{PYTHON[1]}")

    submodule = op.join(code_dir, SUBMODULE)
    package = op.realpath(op.dirname(videogames_utils.__file__))
    if not package.startswith(op.realpath(submodule) + op.sep):
        out.append(f"videogames_utils is imported from {package}, not from the dataset's "
                   f"{SUBMODULE} (pip install -e ./{SUBMODULE})")
    else:
        recorded = (_git("ls-tree", "HEAD", SUBMODULE, cwd=code_dir) or "").split()
        head = _git("rev-parse", "HEAD", cwd=submodule)
        if len(recorded) > 2 and head != recorded[2]:
            out.append(f"{SUBMODULE} is at {str(head)[:7]}, the dataset records "
                       f"{recorded[2][:7]}")
        if _git("status", "--porcelain", cwd=submodule):
            out.append(f"{SUBMODULE} has local changes")
    out += _lock_problems()

    if _git("status", "--porcelain", "--", "code", f":(exclude){SUBMODULE}", cwd=code_dir):
        out.append("the dataset's code/ has uncommitted changes")
    stimuli = _git("submodule", "status", "--", STIMULI, cwd=code_dir)
    if stimuli is not None and stimuli[:1] in ("+", "-", "U"):
        out.append(f"{STIMULI} is not checked out at the commit the dataset records")
    return out


def check(code_dir: str, data_dir: str, stimuli_dir: Optional[str] = None,
          allow: bool = False) -> None:
    """Exit with the list of :func:`problems`, or only print it when ``allow`` is set."""
    found = problems(code_dir, data_dir, stimuli_dir)
    if not found:
        return
    message = ("This environment is not the one the dataset pins:\n"
               + "\n".join(f"  - {problem}" for problem in found))
    if allow:
        print(message + "\nRunning anyway (--allow-unpinned): the outputs are not "
              "reproducible.", file=sys.stderr)
        return
    sys.exit(message + "\nFix the environment, or pass --allow-unpinned to run anyway; the "
             "outputs will not be reproducible.")
