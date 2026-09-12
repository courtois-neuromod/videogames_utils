"""Per-game event generators.

Each module turns one repetition's ``_variables.json`` into a BIDS events DataFrame using
the shared vocabulary, emit helpers and tracker. The datasets' own
``code/annotations/generate_annotations.py`` are thin CLIs over these.

    smb1     - Super Mario Bros, covering both the NES original (mario) and the Super
               Mario All-Stars remake (mariostars), which share the object id tables.
    smb3     - Super Mario Bros 3 (mario3).
    shinobi3 - Shinobi III (shinobi).
"""
