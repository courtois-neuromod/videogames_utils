"""Record how each step's outputs were produced, in the dataset's ``code/provenance.json``.

One file per dataset, rewritten in place: every commit of the dataset holds exactly one,
and git history keeps the earlier ones. It has one section per generation step (see
:data:`STEPS`); a step rewrites only its own section. Each section records the code
(videogames_utils version and commit, dataset commit, script), the inputs (git-annex key
or checksum of every input file, commit of every input submodule), the environment, the
parameters and the outputs.

A generator wraps its work in :func:`step`::

    from videogames_utils import provenance

    with provenance.step(".", "replays", "code/replays/generate_replays.py",
                         parameters=vars(args), input_submodules=["stimuli"]) as prov:
        prov.add_inputs(bk2_files + [rom_path] + state_files)
        ...
        prov.add_outputs(written_files)

Entering the block refuses to run, with no override, when videogames_utils or the dataset
has uncommitted changes to tracked files, when the installed videogames_utils commit
cannot be identified, or when an input submodule is at a commit that is on none of its
remote-tracking branches (as of the last fetch). If the block raises, nothing is written.

:func:`update_generated_by` copies a summary into ``GeneratedBy`` of the BIDS
``dataset_description.json``.
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
import sys
from contextlib import contextmanager
from typing import Dict, Iterable, Iterator, List, Optional, Sequence

#: Generation steps, each with its own section.
STEPS = ("replays", "videos", "lowlevel", "annotations", "sidecars")

#: Where the file lives, relative to the dataset root.
PROVENANCE_PATH = op.join("code", "provenance.json")

#: Packages whose versions are recorded individually.
KEY_PACKAGES = ("videogames_utils", "stable-retro", "numpy", "opencv-python",
                "imageio-ffmpeg", "Pillow", "pandas", "scipy")

CODE_URL = "https://github.com/courtois-neuromod/videogames_utils/tree/"

#: Directory of the installed package, used to find its git checkout.
PACKAGE_DIR = op.dirname(op.abspath(__file__))


class ProvenanceError(RuntimeError):
    """A generator may not run: what it would record could not be retrieved later."""


def _git(repo: str, *args: str) -> Optional[str]:
    """Output of a git command, or None if it fails."""
    try:
        result = subprocess.run(["git", "-C", repo, *args], capture_output=True,
                                text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _package_repo() -> Optional[str]:
    """Root of the git checkout videogames_utils is installed from, if any.

    Only when the package's files are tracked there, so a regular install inside a venv
    that happens to sit in some other repository is not mistaken for a checkout.
    """
    top = _git(PACKAGE_DIR, "rev-parse", "--show-toplevel")
    if top and _git(PACKAGE_DIR, "ls-files", "--", "."):
        return top
    return None


def _package_commit() -> Optional[str]:
    """videogames_utils commit: from its checkout, else from pip's direct_url.json."""
    repo = _package_repo()
    if repo:
        return _git(repo, "rev-parse", "HEAD")
    try:
        direct_url = importlib.metadata.distribution("videogames_utils").read_text(
            "direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return None
    if direct_url:
        return json.loads(direct_url).get("vcs_info", {}).get("commit_id")
    return None


def _version(name: str) -> Optional[str]:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _dirty(repo: str) -> bool:
    """True if tracked files (or submodules) differ from HEAD. Untracked files are ignored."""
    status = _git(repo, "status", "--porcelain", "--untracked-files=no")
    return status is None or status != ""


def _submodule_commit(dataset_dir: str, path: str) -> Optional[str]:
    """Commit the dataset's HEAD records for submodule ``path``."""
    line = _git(dataset_dir, "ls-tree", "HEAD", "--", path)
    if not line or " commit " not in line:
        return None
    return line.split()[2]


def require_clean(dataset_dir: str, input_submodules: Sequence[str] = ()) -> None:
    """Raise :class:`ProvenanceError` listing every reason the step may not run."""
    problems = []

    repo = _package_repo()
    if repo is not None and _dirty(repo):
        problems.append(f"videogames_utils has uncommitted changes ({repo})")
    if _package_commit() is None:
        problems.append("cannot tell which videogames_utils commit is installed; install "
                        "it from a git checkout or a git URL")

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
    if op.islink(path):
        target = os.readlink(path)
        if "annex/objects/" in target.replace(os.sep, "/"):
            return op.basename(target)
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _ffmpeg() -> Optional[str]:
    try:
        import imageio_ffmpeg
        out = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-version"],
                             capture_output=True, text=True, check=True).stdout
    except Exception:  # noqa: BLE001 - recorded as unknown rather than failing the run
        return None
    return out.splitlines()[0] if out else None


def environment() -> dict:
    """Python, key package versions, a hash of all installed packages, ffmpeg, host."""
    installed = sorted({f"{d.metadata['Name']}=={d.version}".lower()
                        for d in importlib.metadata.distributions()
                        if d.metadata["Name"]})
    return {
        "python": platform.python_version(),
        "executable": sys.executable,
        "packages": {name: _version(name) for name in KEY_PACKAGES},
        "installed_packages_sha256": hashlib.sha256(
            "\n".join(installed).encode()).hexdigest(),
        "ffmpeg": _ffmpeg(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
    }


def load(dataset_dir: str) -> dict:
    """The dataset's provenance record, or an empty dict."""
    path = op.join(dataset_dir, PROVENANCE_PATH)
    if not op.exists(path):
        return {}
    with open(path) as handle:
        return json.load(handle)


class Step:
    """Collects the inputs and outputs of one step; see :func:`step`."""

    def __init__(self, dataset_dir: str):
        self.dataset_dir = dataset_dir
        self.inputs: Dict[str, str] = {}
        self.outputs: List[str] = []

    def _rel(self, path: str) -> str:
        return op.relpath(op.abspath(path), op.abspath(self.dataset_dir))

    def add_inputs(self, paths: Iterable[str]) -> None:
        """Record the annex key or checksum of each input file now."""
        for path in paths:
            self.inputs[self._rel(path)] = file_id(path)

    def add_outputs(self, paths: Iterable[str]) -> None:
        """Mark files as written by this step; they are checksummed when the step ends."""
        self.outputs.extend(self._rel(p) for p in paths)


@contextmanager
def step(dataset_dir: str, name: str, script: str, parameters: Optional[dict] = None,
         input_submodules: Sequence[str] = ()) -> Iterator[Step]:
    """Check the repositories, run the block, then write the step's section.

    Args:
        dataset_dir: Root of the dataset repository.
        name: One of :data:`STEPS`.
        script: Path of the generator script, relative to the dataset root.
        parameters: The full CLI arguments with defaults resolved, e.g. ``vars(args)``.
        input_submodules: Submodules the step reads, e.g. ``["stimuli"]``.
    """
    if name not in STEPS:
        raise ValueError(f"unknown step {name!r}; expected one of {', '.join(STEPS)}")
    require_clean(dataset_dir, input_submodules)

    code = {
        "videogames_utils_version": _version("videogames_utils"),
        "videogames_utils_commit": _package_commit(),
        "dataset_commit": _git(dataset_dir, "rev-parse", "HEAD"),
        "script": script,
    }
    submodules = {p: _submodule_commit(dataset_dir, p) for p in input_submodules}
    env = environment()
    # JSON round trip so Paths and other argparse values are stored as strings.
    params = json.loads(json.dumps(dict(parameters or {}), default=str))

    collector = Step(dataset_dir)
    yield collector

    outputs = sorted(set(collector.outputs))
    listing = "".join(f"{p}\t{file_id(op.join(dataset_dir, p))}\n" for p in outputs)
    section = {
        "code": code,
        "inputs": {"files": dict(sorted(collector.inputs.items())),
                   "submodules": submodules},
        "environment": env,
        "parameters": params,
        "outputs": {"files": outputs,
                    "checksum": "sha256:" + hashlib.sha256(listing.encode()).hexdigest()},
        "timestamp": datetime.datetime.now(datetime.timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    record = load(dataset_dir)
    record[name] = section
    path = op.join(dataset_dir, PROVENANCE_PATH)
    os.makedirs(op.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump({k: record[k] for k in sorted(record, key=_step_order)}, handle, indent=2)
        handle.write("\n")


def _step_order(name: str):
    return (STEPS.index(name), name) if name in STEPS else (len(STEPS), name)


def update_generated_by(dataset_dir: str) -> None:
    """Write the videogames_utils entry of ``GeneratedBy`` in dataset_description.json.

    Other entries are kept. ``CodeURL`` points at the commit of the most recent step and
    ``Description`` lists every step with its commit and date.
    """
    record = load(dataset_dir)
    if not record:
        raise ProvenanceError(f"no {PROVENANCE_PATH} in {dataset_dir}")
    latest = max(record.values(), key=lambda s: s["timestamp"])
    steps = "; ".join(
        f"{name}: {s['code']['script']} at videogames_utils "
        f"{(s['code']['videogames_utils_commit'] or '?')[:8]}, {s['timestamp']}"
        for name, s in record.items())
    entry = {
        "Name": "videogames_utils",
        "Version": latest["code"]["videogames_utils_version"],
        "CodeURL": CODE_URL + (latest["code"]["videogames_utils_commit"] or ""),
        "Description": f"Generated outputs; details in {PROVENANCE_PATH}. Steps: {steps}.",
    }

    path = op.join(dataset_dir, "dataset_description.json")
    with open(path) as handle:
        description = json.load(handle)
    others = [e for e in description.get("GeneratedBy", [])
              if e.get("Name") != "videogames_utils"]
    description["GeneratedBy"] = others + [entry]
    with open(path, "w") as handle:
        json.dump(description, handle, indent=4)
        handle.write("\n")
