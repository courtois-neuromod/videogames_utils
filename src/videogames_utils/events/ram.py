"""Candidate RAM addresses for a game integration, and the harness that verifies them
before they are added to a dataset's ``stimuli/<Game>/data.json``.

Each dataset lists its own candidates (``Game.ram_candidates``), sourced from a public
disassembly where one exists, and checks them against an independent truth signal before
they ship. Nothing in this module writes to a dataset; the harness builds a throwaway
*shadow* integration in a temporary directory instead.
"""

from __future__ import annotations

import json
import os
import os.path as op
import shutil
import tempfile
import warnings
from dataclasses import dataclass

import stable_retro as retro

from ..replay import get_variables_from_replay


# --------------------------------------------------------------------------- specs


@dataclass
class Candidate:
    """One RAM variable proposed for addition to an integration's ``data.json``.

    Attributes:
        name: Key to write into ``data.json`` (and hence into ``_variables.json``).
        address: Decimal address, as ``data.json`` expects.
        dtype: stable-retro type string, e.g. ``"|u1"``.
        symbol: The disassembly label this address corresponds to.
        note: Why we want it / what it decodes to.
    """

    name: str
    address: int
    dtype: str
    symbol: str
    note: str = ""

    def as_json_entry(self) -> dict:
        return {"address": self.address, "type": self.dtype}


def candidate_array(prefix: str, base: int, count: int, dtype: str, symbol: str,
                    note: str = ""):
    """Expand a contiguous RAM array into one Candidate per slot."""
    return [
        Candidate(f"{prefix}_{i}", base + i, dtype, f"{symbol}[{i}]", note)
        for i in range(count)
    ]


# ------------------------------------------------------------------------- harness


def build_shadow_integration(dataset_dir: str, game: str, candidates, dest: str) -> str:
    """Copy an integration into ``dest`` with ``candidates`` merged into its data.json.

    Large files (ROMs, save states) are symlinked rather than copied so this stays cheap
    for the SNES and Genesis integrations.

    Returns:
        The directory to hand to ``retro.data.Integrations.add_custom_path``.
    """
    src = op.join(dataset_dir, "stimuli", game)
    if not op.isdir(src):
        raise FileNotFoundError(f"no integration at {src}")
    out_game = op.join(dest, game)
    os.makedirs(out_game, exist_ok=True)

    for entry in os.listdir(src):
        if entry == "data.json":
            continue
        source, target = op.join(src, entry), op.join(out_game, entry)
        if op.exists(target) or op.islink(target):
            continue
        if not op.isfile(source):
            continue
        if os.path.getsize(source) > 64 * 1024:
            os.symlink(op.realpath(source), target)
        else:
            shutil.copy2(source, target)

    with open(op.join(src, "data.json")) as f:
        data = json.load(f)
    info = data.setdefault("info", {})
    for cand in candidates:
        info[cand.name] = cand.as_json_entry()
    with open(op.join(out_game, "data.json"), "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)

    return dest


def replay_with_candidates(dataset_dir, game, bk2_path, candidates,
                           workdir=None) -> dict:
    """Replay ``bk2_path`` against a shadow integration carrying ``candidates``.

    Returns the usual ``repetition_variables`` dict, with the candidate keys added.
    """
    tmp = workdir or tempfile.mkdtemp(prefix="vg_shadow_")
    build_shadow_integration(dataset_dir, game, candidates, tmp)
    retro.data.Integrations.add_custom_path(op.abspath(tmp))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        repvars, _, frames, _, _ = get_variables_from_replay(
            bk2_path, game=game,
            inttype=retro.data.Integrations.CUSTOM_ONLY)
    del frames
    return repvars
