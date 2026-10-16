"""Record how each step's outputs were produced, in the dataset's ``code/provenance.json``.

The file is rewritten in place, so every commit of the dataset holds exactly one and git
history keeps the earlier ones. It has one section per step of :data:`STEPS`, and a step
rewrites only its own section::

    with provenance.step(".", "replays", "code/replays/generate_replays.py",
                         parameters=vars(args), input_submodules=["stimuli"]) as prov:
        prov.add_inputs(bk2_files + [rom_path] + state_files)
        ...
        prov.add_outputs(written_files)

Entering the block refuses to run, with no override, if videogames_utils (which must be
a git checkout) or the dataset has uncommitted changes, or if an input submodule is at a
commit that is on none of its remote branches. If the block raises, nothing is written.
"""

from __future__ import annotations

import datetime
import hashlib
import importlib.metadata
import json
import os
import os.path as op
import platform
import socket
import subprocess
from contextlib import contextmanager
from typing import Iterable, Optional, Sequence

STEPS = ("replays", "videos", "lowlevel", "annotations", "sidecars")
PROVENANCE_PATH = op.join("code", "provenance.json")
KEY_PACKAGES = ("videogames_utils", "stable-retro", "numpy", "opencv-python",
                "imageio-ffmpeg", "Pillow", "pandas", "scipy")
CODE_URL = "https://github.com/courtois-neuromod/videogames_utils/tree/"
PACKAGE_DIR = op.dirname(op.abspath(__file__))


class ProvenanceError(RuntimeError):
    """A step may not run: what it would record could not be retrieved later."""


def _git(repo: str, *args: str) -> Optional[str]:
    """Output of a git command, or None if it fails."""
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def _package_repo() -> Optional[str]:
    """The git checkout videogames_utils runs from, if its files are tracked there."""
    if _git(PACKAGE_DIR, "ls-files", "--", "."):
        return _git(PACKAGE_DIR, "rev-parse", "--show-toplevel")
    return None


def _dirty(repo: str) -> bool:
    """True if tracked files or submodules differ from HEAD."""
    return _git(repo, "status", "--porcelain", "--untracked-files=no") != ""


def _submodule_commit(dataset_dir: str, path: str) -> Optional[str]:
    """Commit recorded in the dataset's HEAD for submodule ``path``."""
    line = _git(dataset_dir, "ls-tree", "HEAD", "--", path)
    return line.split()[2] if line and " commit " in line else None


def require_clean(dataset_dir: str, input_submodules: Sequence[str] = ()) -> None:
    """Raise :class:`ProvenanceError` listing every reason the step may not run."""
    problems = []
    repo = _package_repo()
    if repo is None:
        problems.append("videogames_utils is not installed from a git checkout")
    elif _dirty(repo):
        problems.append(f"videogames_utils has uncommitted changes ({repo})")
    if _git(dataset_dir, "rev-parse", "HEAD") is None:
        problems.append(f"{dataset_dir} is not a git repository with a commit")
    elif _dirty(dataset_dir):
        problems.append(f"the dataset has uncommitted changes ({op.abspath(dataset_dir)})")

    for path in input_submodules:
        commit = _submodule_commit(dataset_dir, path)
        sub = op.join(dataset_dir, path)
        if commit is None:
            problems.append(f"{path} is not a submodule of the dataset")
        elif not op.exists(op.join(sub, ".git")):
            problems.append(f"submodule {path} is not installed, so its commit "
                            f"{commit[:8]} cannot be checked against its remotes")
        elif not _git(sub, "branch", "-r", "--contains", commit):
            problems.append(f"submodule {path} is at {commit[:8]}, which is not on any "
                            "remote branch (push it, or fetch if it already is)")
    if problems:
        raise ProvenanceError("refusing to run:\n  - " + "\n  - ".join(problems))


def file_id(path: str) -> str:
    """git-annex key of an annexed file (from its symlink), else ``sha256:<hex>``."""
    if op.islink(path) and "annex/objects/" in os.readlink(path):
        return op.basename(os.readlink(path))
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _version(name: str) -> Optional[str]:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def environment() -> dict:
    """Python, key package versions, a hash of all installed packages, ffmpeg, host."""
    import imageio_ffmpeg

    installed = sorted(f"{d.metadata['Name']}=={d.version}".lower()
                       for d in importlib.metadata.distributions())
    ffmpeg = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-version"],
                            capture_output=True, text=True).stdout
    return {
        "python": platform.python_version(),
        "packages": {name: _version(name) for name in KEY_PACKAGES},
        "installed_packages_sha256": hashlib.sha256("\n".join(installed).encode()).hexdigest(),
        "ffmpeg": ffmpeg.splitlines()[0] if ffmpeg else None,
        "host": socket.gethostname(),
    }


def load(dataset_dir: str) -> dict:
    """The dataset's provenance record, or an empty dict."""
    path = op.join(dataset_dir, PROVENANCE_PATH)
    if not op.exists(path):
        return {}
    with open(path) as handle:
        return json.load(handle)


class Step:
    """Inputs and outputs of one step; see :func:`step`."""

    def __init__(self, dataset_dir: str):
        self.dataset_dir = dataset_dir
        self.inputs = {}
        self.outputs = set()

    def _rel(self, path: str) -> str:
        return op.relpath(op.abspath(path), op.abspath(self.dataset_dir))

    def add_inputs(self, paths: Iterable[str]) -> None:
        for path in paths:
            self.inputs[self._rel(path)] = file_id(path)

    def add_outputs(self, paths: Iterable[str]) -> None:
        """Files written by the step; checksummed when it ends."""
        self.outputs.update(self._rel(p) for p in paths)


@contextmanager
def step(dataset_dir: str, name: str, script: str, parameters: Optional[dict] = None,
         input_submodules: Sequence[str] = ()):
    """Check the repositories, run the block, then write the step's section.

    ``parameters`` should be the full CLI arguments with defaults resolved, e.g.
    ``vars(args)``; ``script`` is relative to the dataset root.
    """
    if name not in STEPS:
        raise ValueError(f"unknown step {name!r}; expected one of {', '.join(STEPS)}")
    require_clean(dataset_dir, input_submodules)
    section = {
        "code": {"videogames_utils_version": _version("videogames_utils"),
                 "videogames_utils_commit": _git(_package_repo(), "rev-parse", "HEAD"),
                 "dataset_commit": _git(dataset_dir, "rev-parse", "HEAD"),
                 "script": script},
        "inputs": {"submodules": {p: _submodule_commit(dataset_dir, p)
                                  for p in input_submodules}},
        "environment": environment(),
        # JSON round trip so Paths and other argparse values are stored as strings.
        "parameters": json.loads(json.dumps(parameters or {}, default=str)),
    }

    prov = Step(dataset_dir)
    yield prov

    outputs = sorted(prov.outputs)
    listing = "".join(f"{p}\t{file_id(op.join(dataset_dir, p))}\n" for p in outputs)
    section["inputs"]["files"] = dict(sorted(prov.inputs.items()))
    section["outputs"] = {"files": outputs,
                          "checksum": "sha256:" + hashlib.sha256(listing.encode()).hexdigest()}
    section["timestamp"] = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")

    record = load(dataset_dir)
    record[name] = section
    path = op.join(dataset_dir, PROVENANCE_PATH)
    os.makedirs(op.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")


def update_generated_by(dataset_dir: str) -> None:
    """Set the videogames_utils entry of ``GeneratedBy`` in dataset_description.json,
    pointing at the commit of the most recent step. Other entries are kept."""
    latest = max(load(dataset_dir).values(), key=lambda s: s["timestamp"])
    entry = {"Name": "videogames_utils",
             "Version": latest["code"]["videogames_utils_version"],
             "CodeURL": CODE_URL + latest["code"]["videogames_utils_commit"],
             "Description": f"Per-step details in {PROVENANCE_PATH}."}

    path = op.join(dataset_dir, "dataset_description.json")
    with open(path) as handle:
        description = json.load(handle)
    description["GeneratedBy"] = [e for e in description.get("GeneratedBy", [])
                                  if e.get("Name") != "videogames_utils"] + [entry]
    with open(path, "w") as handle:
        json.dump(description, handle, indent=4)
        handle.write("\n")
