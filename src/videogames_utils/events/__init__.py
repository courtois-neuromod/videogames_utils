"""Event annotation tooling shared by the CNeuroMod videogame datasets.

Game-agnostic: each dataset describes its game in a :class:`~.game.Game`, exposed by its
``code/game_specific/`` package, and passes it to the pipeline.

Submodules:
    game        - the Game description a dataset provides, and :func:`~.game.load_game`
    run         - turn a run's events.tsv into an annotated events file
    validation  - schema checks and RAM-derived invariants
    docs        - render a dataset's code/annotations/README.md
    vocabulary  - the trial_type vocabulary entries and the BIDS sidecar
    emit        - helpers for building BIDS events DataFrames
    spans       - runs of frames in per-frame series
    screens     - the Screen/* labels and the alive mask
    tracking    - on-screen object tracking used for the Enemy* events
    ram         - candidate RAM address specs and the verification harness
    review      - human review clips for precision and recall
"""
