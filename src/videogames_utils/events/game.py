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
        generate: ``generate(repvars, outcome=..., stim_file=...)`` returns the events of
            one repetition, with onsets relative to its start.
        outcome: ``outcome(repvars)`` returns how a repetition ended (``cleared``,
            ``failed/...``, ...), stored as ``Outcome`` in its ``_summary.json``.
        summary: ``summary(repvars, events)`` returns the game's own fields of a
            repetition's ``_summary.json`` (UpperCamelCase), from its variables and the
            events ``generate`` makes of them. The common fields are added by
            :mod:`videogames_utils.replays`.
        phases: ``phases(repetitions)`` returns the protocol phase of each repetition of
            the dataset, given the DataFrame built by
            :func:`videogames_utils.replays.collect_repetitions`. None if the protocol
            has no phases.
        scenario: ``scenario(level)`` returns the scenario file, in the game's
            integration directory, to replay a repetition with, from the ``level`` of
            its events.tsv row. None to use the integration's ``scenario.json``.
        process_variables: ``process_variables(repvars)`` corrects a replay's variables
            before they are saved, e.g. a position that wraps around.
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
        reference: Markdown reference for this game: how each event is read from the RAM
            and how it was validated. Embedded in the dataset README and in the common
            event reference, under a heading per game; use ``###`` and lower.
        not_emitted: trial_type -> why the dataset has no row for it.
        families: Event families added to or overriding the standard ones
            (:data:`~.vocabulary.FAMILIES`), for the BIDS sidecar:
            ``{"Family": {"Description": ..., "Qualifiers": ("name", ...)}}``.
        type_descriptions: Decoded type name (``"Goomba"``) -> description, for the BIDS
            sidecar. Types not listed are described by their name.
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
    summary: Optional[Callable] = None
    phases: Optional[Callable] = None
    scenario: Optional[Callable] = None
    process_variables: Optional[Callable] = None
    form_states: frozenset = frozenset()
    form_var: Optional[str] = None
    state_timers: Sequence[Tuple[str, str]] = ()
    coin_var: Optional[str] = None
    check_repetition: Optional[Callable] = None
    completion_miss: Optional[Tuple[str, str]] = None
    reference: str = ""
    not_emitted: Mapping[str, str] = field(default_factory=dict)
    families: Mapping[str, dict] = field(default_factory=dict)
    type_descriptions: Mapping[str, str] = field(default_factory=dict)
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
