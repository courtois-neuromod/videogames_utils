"""What a dataset tells :mod:`videogames_utils.events` about its game.

The events pipeline is game-agnostic: everything that depends on the game (which events
it has, how they are read from the RAM, how a repetition's outcome is decided, what is
checked against the RAM, the documentation) is provided by the dataset, as one
:class:`Game` object exposed by its ``code/game_specific/`` package::

    # <dataset>/code/game_specific/__init__.py
    from videogames_utils.events.game import Game
    GAME = Game(task="mario", ...)

Scripts and command-line tools obtain it with :func:`load_game`.
"""

from __future__ import annotations

import importlib.util
import os.path as op
import sys
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Sequence, Tuple

#: Where a dataset keeps its game-specific code, relative to the dataset root.
GAME_SPECIFIC_DIR = op.join("code", "game_specific")


def _unchanged(level):
    return level


@dataclass(frozen=True)
class Game:
    """The game-specific half of the events pipeline, provided by a dataset.

    Attributes:
        task: BIDS task label, e.g. ``"mario"``.
        name: Display name of the game, e.g. ``"Super Mario Bros. (NES)"``.
        game_id: stable-retro integration name, e.g. ``"SuperMarioBros-Nes"``; the
            integration lives in the dataset's ``stimuli/<game_id>/``.
        frame_rate: Emulator frame rate, in frames per second.
        vocabulary: The :class:`~videogames_utils.events.vocabulary.EventType` entries
            the game may emit.
        generate: ``generate(repvars, level=..., outcome=..., stim_file=...)`` returns the
            events of one repetition, with onsets relative to its start.
        outcome: ``outcome(repvars)`` returns how a repetition ended (``cleared``,
            ``failed/...``, ...), stored as ``Outcome`` in its ``_summary.json``.
        level_from_events: Converts the ``level`` of a plain events.tsv row to the
            annotated form. Only used for "Missing file" repetitions.
        form_states: The mutually exclusive ``PlayerState/*`` forms, which together tile
            the frames on which the player is alive in the level.
        form_var: RAM variable holding the form, or None if the game has a single form.
        state_timers: ``(RAM variable, trial_type)`` pairs whose non-zero runs are the
            overlay ``PlayerState/*`` rows.
        coin_var: RAM variable counting coins, or None if the game has no coins.
        check_repetition: Extra game-specific RAM invariants, called as
            ``check_repetition(events, repvars, summary, path, report)``.
        completion_miss: Severity and explanation of a cleared repetition without
            ``LevelCompleted``, for games where it can legitimately happen.
        notes: Markdown accuracy notes for the dataset README.
        not_emitted: trial_type -> why the dataset has no row for it.
        golden_sessions: ``(subject, session)`` pairs frozen as regression fixtures.
        ram_candidates: Verified RAM variables to merge into ``data.json``.
        mislabelled: ``data.json`` keys whose names are wrong, with what they hold.
    """

    task: str
    name: str
    game_id: str
    frame_rate: float
    vocabulary: Sequence
    generate: Callable
    outcome: Callable
    level_from_events: Callable = _unchanged
    form_states: frozenset = frozenset()
    form_var: Optional[str] = None
    state_timers: Sequence[Tuple[str, str]] = ()
    coin_var: Optional[str] = None
    check_repetition: Optional[Callable] = None
    completion_miss: Optional[Tuple[str, str]] = None
    notes: str = ""
    not_emitted: Mapping[str, str] = field(default_factory=dict)
    golden_sessions: Sequence[Tuple[str, str]] = ()
    ram_candidates: Sequence = ()
    mislabelled: Mapping[str, str] = field(default_factory=dict)


def load_game(dataset_dir: str) -> Game:
    """Import ``<dataset_dir>/code/game_specific`` and return its ``GAME``.

    Each dataset is imported under its own module name, so several can be loaded in one
    process.
    """
    package_dir = op.join(op.abspath(dataset_dir), GAME_SPECIFIC_DIR)
    init = op.join(package_dir, "__init__.py")
    if not op.exists(init):
        raise FileNotFoundError(f"no game-specific package at {package_dir}")
    name = "game_specific_" + op.basename(op.abspath(dataset_dir)).replace("-", "_")
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, init, submodule_search_locations=[package_dir])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name].GAME
