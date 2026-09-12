"""Validation for the generated BIDS events files.

Three automatic layers, all with full coverage of whatever they are pointed at:

V0  schema and controlled vocabulary -- structural correctness of the TSVs
V1  invariants re-derived from the raw RAM by a *different* route than the generator
V2  cross-port agreement between mario (NES SMB1) and mariostars (SNES SMB1), which are
    the same levels on two consoles

The point of V1 is that it must not reuse the generator's own logic: a check that calls
the same helper the generator called proves nothing. Each invariant here recomputes its
quantity straight from ``_variables.json``.

Findings are returned as :class:`Finding` records rather than raised, so a run reports
every problem at once instead of stopping at the first.
"""

from __future__ import annotations

import collections
import json
import os.path as op
from dataclasses import dataclass, field
from glob import glob
from typing import Dict, Iterable, List, Optional

import pandas as pd

from . import vocabulary
from .emit import COLUMNS, TASK_FRAME_RATES

#: Columns every annotated events file must have.
REQUIRED_COLUMNS = ["trial_type", "onset", "duration", "level", "frame_start",
                    "frame_stop", "stim_file"]

#: Events other than the container row must leave stim_file empty.
CONTAINER = "gym-retro_game"

#: Tolerance when comparing an onset recomputed from frame_start, in seconds.
ONSET_TOLERANCE = 0.002

#: The mutually exclusive Player_state forms. Together they tile the frames on which the
#: player is alive in the level.
FORM_STATES = frozenset({"Player_state/Small", "Player_state/Super", "Player_state/Fire",
                         "Player_state/Raccoon", "Player_state/Frog",
                         "Player_state/Tanooki", "Player_state/Hammer",
                         "Player_state/Normal"})

#: Screen/* rows during which no form row may exist.
NOT_ALIVE_SCREENS = frozenset({"Screen/Death", "Screen/Level_intro", "Screen/Game_over",
                               "Screen/Map"})

#: Shortest title card observed (86 frames on the NES, 79 on the SNES); the black screen
#: between areas is 24 frames on the NES and the task-1 stretch of a pipe 35-42 frames on
#: the SNES, so a length threshold separates the two by a different route than the
#: generator's "at the start or after a death" rule.
INTRO_MIN_FRAMES = 60

#: RAM variable holding the form, per task.
FORM_VARS = {"mario": "player_status", "mariostars": "player_status", "mario3": "powerup"}

#: (timer variable, trial_type) pairs whose non-zero runs are the overlay states.
_SMB1_TIMERS = (("star_timer", "Player_state/Star"),
                ("injury_timer", "Player_state/Hit_recovery"))
STATE_TIMERS = {
    "mario": _SMB1_TIMERS,
    "mariostars": _SMB1_TIMERS,
    "mario3": (("invincibility_timer", "Player_state/Star"),
               ("invisibility_timer", "Player_state/Hit_recovery"),
               ("flight_timer", "Player_state/Flying"),
               ("statue_timer", "Player_state/Statue"),
               ("kuribo_shoe", "Player_state/Kuribo_shoe")),
}


@dataclass
class Finding:
    """One validation problem."""

    layer: str
    check: str
    path: str
    detail: str
    severity: str = "error"

    def __str__(self) -> str:
        return f"[{self.severity.upper()} {self.layer}] {self.check}\n    {self.path}\n    {self.detail}"


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    checked: collections.Counter = field(default_factory=collections.Counter)

    def add(self, *args, **kwargs) -> None:
        self.findings.append(Finding(*args, **kwargs))

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    def summary(self) -> str:
        lines = [f"checked: {dict(self.checked)}"]
        by_check = collections.Counter((f.layer, f.check) for f in self.findings)
        if not by_check:
            lines.append("no findings")
        for (layer, check), count in by_check.most_common():
            lines.append(f"  {layer} {check}: {count}")
        return "\n".join(lines)


# ------------------------------------------------------------------------------- V0


#: Frames a defeat may sit past the end of its track, matching the generator.
DEFEAT_SLACK = 4


def check_schema(df: pd.DataFrame, task: str, path: str, report: Report) -> None:
    """V0: structure, controlled vocabulary, ordering and frame/onset consistency."""
    report.checked["files"] += 1
    report.checked["rows"] += len(df)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        report.add("V0", "missing required columns", path, f"missing {missing}")
        return

    unknown = [c for c in df.columns if c not in COLUMNS]
    if unknown:
        report.add("V0", "unexpected columns", path, f"unexpected {unknown}", "warning")

    ordered = [c for c in COLUMNS if c in df.columns]
    if list(df.columns)[:len(ordered)] != ordered:
        report.add("V0", "column order", path,
                   f"expected {ordered}, got {list(df.columns)}", "warning")

    bad_types = sorted({t for t in df["trial_type"].dropna().unique()
                        if not vocabulary.is_valid(str(t), task)})
    if bad_types:
        report.add("V0", "trial_type outside the vocabulary", path,
                   f"{bad_types[:10]}")

    onsets = df["onset"].astype(float)
    if not onsets.is_monotonic_increasing:
        n_bad = int((onsets.diff() < 0).sum())
        report.add("V0", "onsets not sorted", path, f"{n_bad} descending steps")
    if (onsets < 0).any():
        report.add("V0", "negative onset", path, f"{int((onsets < 0).sum())} rows")
    if (df["duration"].astype(float) < 0).any():
        report.add("V0", "negative duration", path,
                   f"{int((df['duration'].astype(float) < 0).sum())} rows")

    frames = df["frame_stop"].astype("Float64") - df["frame_start"].astype("Float64")
    if (frames < 0).any():
        report.add("V0", "frame_stop before frame_start", path,
                   f"{int((frames < 0).sum())} rows")

    # stim_file belongs to the container row alone.
    others = df[df["trial_type"] != CONTAINER]
    stray = others["stim_file"].notna().sum() if "stim_file" in others else 0
    if stray:
        report.add("V0", "stim_file set on a non-container row", path,
                   f"{stray} rows outside gym-retro_game carry a stim_file")

    # Every non-container event must fall inside exactly one repetition window.
    reps = df[df["trial_type"] == CONTAINER]
    if reps.empty:
        report.add("V0", "no repetition rows", path, "no gym-retro_game rows")
        return
    windows = [(float(r.onset), float(r.onset) + float(r.duration))
               for r in reps.itertuples()]

    # Repetition windows must not overlap: with stim_file carried only by the container
    # row, an overlap makes it impossible to say which repetition an event belongs to.
    ordered = sorted(windows)
    overlaps = sum(1 for i in range(1, len(ordered))
                   if ordered[i][0] < ordered[i - 1][1] - 0.01)
    if overlaps:
        report.add("V0", "overlapping repetition windows", path,
                   f"{overlaps} repetition(s) start before the previous one ends -- the "
                   "run's plain _events.tsv has bad onsets, so events in the overlap "
                   "cannot be attributed to a repetition")
    outside = 0
    for onset in others["onset"].astype(float):
        if not any(start - 0.05 <= onset <= stop + 0.05 for start, stop in windows):
            outside += 1
    if outside:
        report.add("V0", "events outside every repetition window", path,
                   f"{outside}/{len(others)} rows")


# ------------------------------------------------------------------------------- V1


def _nonzero_runs(series) -> int:
    return sum(1 for i, v in enumerate(series) if v and (i == 0 or not series[i - 1]))


def _constant_nonzero_runs(series) -> int:
    return sum(1 for i, v in enumerate(series) if v and (i == 0 or series[i - 1] != v))


def _diff_increases(series) -> int:
    return sum(1 for i in range(1, len(series)) if series[i] > series[i - 1])


def _diff_decreases(series) -> int:
    return sum(1 for i in range(1, len(series)) if series[i] < series[i - 1])


def _coin_collections(series) -> int:
    """Coin pickups, counting the wrap at 100 (which also awards a life)."""
    total = 0
    for i in range(1, len(series)):
        delta = series[i] - series[i - 1]
        if delta > 0 or delta <= -99:
            total += 1
    return total


def check_invariants(events: pd.DataFrame, repvars: dict, task: str, summary: dict,
                     path: str, report: Report) -> None:
    """V1: recompute quantities straight from the RAM and compare with the events.

    Every check here derives its truth value from ``repvars`` without calling any
    generator helper, so it is an independent test rather than a restatement.
    """
    report.checked["repetitions"] += 1
    counts = collections.Counter(events["trial_type"])

    def prefix_count(prefix: str) -> int:
        return sum(n for t, n in counts.items()
                   if t == prefix or t.startswith(prefix + "/"))

    # --- coins -------------------------------------------------------------------
    coin_var = {"mario": "coins", "mariostars": "player_coins",
                "mario3": "coins_p1"}.get(task)
    if coin_var and coin_var in repvars:
        expected = _coin_collections(repvars[coin_var])
        got = counts.get("Item_collected/Coin", 0)
        if expected != got:
            report.add("V1", "coin count disagrees with the coin counter", path,
                       f"counter says {expected}, events say {got}")

    # --- lives -------------------------------------------------------------------
    if "lives" in repvars:
        gained = _diff_increases(repvars["lives"])
        got = counts.get("Life_gained", 0)
        if gained != got:
            report.add("V1", "Life_gained disagrees with the lives counter", path,
                       f"counter says {gained}, events say {got}", "warning")

    # --- deaths ------------------------------------------------------------------
    deaths = prefix_count("Player_died")
    if task == "shinobi" and "lives" in repvars:
        expected = _diff_decreases(repvars["lives"])
        if expected != deaths:
            report.add("V1", "death count disagrees with the lives counter", path,
                       f"counter says {expected}, events say {deaths}")
    elif task == "mario3":
        # One .bk2 is one life, so a failed repetition has exactly one death.
        outcome = (summary or {}).get("Outcome", "")
        if outcome.startswith("failed") and deaths != 1:
            report.add("V1", "failed repetition without exactly one death", path,
                       f"outcome={outcome}, {deaths} Player_died events")
        if outcome == "cleared" and deaths:
            report.add("V1", "cleared repetition with a death", path,
                       f"{deaths} Player_died events")

    # --- level completion --------------------------------------------------------
    completed = counts.get("Level_completed", 0)
    if completed > 1:
        report.add("V1", "more than one Level_completed", path, f"{completed} events")
    outcome = (summary or {}).get("Outcome")
    warped = counts.get("Level_exited/Warp", 0)
    if outcome and task == "shinobi":
        # Completion is read from the end-of-level fade, which the recording sometimes
        # stops short of (17 of 536 cleared repetitions), so a miss is only a warning.
        if outcome == "cleared" and not completed:
            report.add("V1", "cleared repetition without Level_completed", path,
                       "recording stopped before the end-of-level fade", "warning")
        if outcome == "failed" and completed:
            report.add("V1", "failed repetition with Level_completed", path,
                       f"outcome={outcome}, {completed} events")
    elif outcome:
        if outcome == "cleared" and completed != 1:
            if warped:
                # The shipped Outcome is derived from `jump_airborne == 3`, which is the
                # flagpole slide AND the vine climb, so a warp taken up a vine is
                # mislabelled "cleared". The events are right; the summary is not.
                report.add("V1", "summary says cleared but the repetition warped out",
                           path,
                           f"outcome={outcome}, Level_exited/Warp present, "
                           "no flagpole -- the shipped Outcome is unreliable here",
                           "warning")
            else:
                report.add("V1", "cleared repetition without Level_completed", path,
                           f"outcome={outcome}, {completed} events")
        if outcome.startswith("failed") and completed:
            report.add("V1", "failed repetition with Level_completed", path,
                       f"outcome={outcome}, {completed} events")

    # --- enemies -----------------------------------------------------------------
    # A defeat that belongs to a visible track sits somewhere inside it -- it is emitted
    # at the first frame of the kill state, not at the track's end -- so a defeat is
    # matched to a track of the same species whose window contains it, mirroring the
    # generator's own rule. Defeats matching no track are enemies killed while off
    # screen (a kicked shell rolling on out of view); those are real, since the score
    # rises, but they have no Enemy_on_screen partner. Each track claims at most one.
    appeared = prefix_count("Enemy_on_screen")
    defeated = prefix_count("Enemy_defeated")
    if appeared:
        tt = events["trial_type"].astype(str)
        tracks = events[tt.str.startswith("Enemy_on_screen/")]
        kills = events[tt.str.startswith("Enemy_defeated/")]
        by_species = collections.defaultdict(list)
        for _, t in tracks.iterrows():
            by_species[str(t["trial_type"]).split("/", 1)[1]].append(
                [t["frame_start"], t["frame_stop"], False])
        on_track = unmatched = 0
        for _, k in kills.iterrows():
            parts = str(k["trial_type"]).split("/")
            frame = k["frame_start"]
            hit = None
            if len(parts) >= 3:
                for window in by_species.get(parts[2], ()):
                    if not window[2] and window[0] <= frame <= window[1] + DEFEAT_SLACK:
                        hit = window
                        break
            if hit is None:
                unmatched += 1
            else:
                hit[2] = True
                on_track += 1
        offscreen = unmatched
        if defeated >= 5 and offscreen / defeated > 0.5:
            report.add("V1", "most enemy defeats happen off screen", path,
                       f"{offscreen}/{defeated} defeats had no visible track -- "
                       "suggests the visibility predicate is too strict", "warning")
    # Note on the semantics: visibility uses the game's own EnemyOffscrBitsMasked, which
    # is set when an enemy is offscreen *by any amount*, so an enemy killed while
    # straddling the screen edge legitimately has no fully-visible track. A handful of
    # such defeats per repetition is expected; a majority of them is not.

    # --- screens -----------------------------------------------------------------
    tt = events["trial_type"].astype(str)
    n_frames = len(repvars.get("score") or repvars.get("health") or [])
    alive = _check_screens(events, repvars, task, n_frames, path, report)

    # --- player states -----------------------------------------------------------
    # Recounted straight from the RAM series: one form row per maximal run of a constant
    # form value over the frames on which the player is alive (outside the Death /
    # Level_intro / Game_over / Map screens), one overlay row per non-zero run of its
    # timer. The form rows must also tile the alive frames exactly.
    form_var = FORM_VARS.get(task)
    forms = events[tt.isin(FORM_STATES)]
    if task == "shinobi":
        form_var, series = "alive", [0] * n_frames
    else:
        series = repvars.get(form_var) if form_var else None
    if series is not None and alive is not None:
        expected = sum(1 for i, v in enumerate(series)
                       if alive[i] and (i == 0 or not alive[i - 1] or series[i - 1] != v))
        if expected != len(forms):
            report.add("V1", "Player_state form rows disagree with the form variable",
                       path, f"{form_var} has {expected} runs over alive frames, "
                             f"events have {len(forms)}")
        covered = int((forms["frame_stop"].astype(int)
                       - forms["frame_start"].astype(int) + 1).sum())
        n_alive = sum(alive)
        if covered != n_alive:
            report.add("V1", "Player_state form rows do not tile the alive frames", path,
                       f"form rows cover {covered} frames, {n_alive} are alive")
        ordered = forms.sort_values("frame_start")
        stops = ordered["frame_stop"].astype(int).tolist()
        starts = ordered["frame_start"].astype(int).tolist()
        overlapping = sum(1 for i in range(1, len(starts)) if starts[i] <= stops[i - 1])
        if overlapping:
            report.add("V1", "overlapping Player_state form rows", path,
                       f"{overlapping} row(s) start before the previous form ends")
    for var, trial_type in STATE_TIMERS.get(task, ()):
        if var not in repvars:
            continue
        expected = _nonzero_runs(repvars[var])
        got = counts.get(trial_type, 0)
        if expected != got:
            report.add("V1", f"{trial_type} rows disagree with {var}", path,
                       f"{var} has {expected} non-zero runs, events have {got}")
    if task == "shinobi":
        recovery = events[tt == "Player_state/Hit_recovery"]
        hits = events[tt == "Player_damaged"]["frame_start"].astype(int).tolist()
        if len(recovery) > len(hits):
            report.add("V1", "more Hit_recovery rows than Player_damaged", path,
                       f"{len(recovery)} recoveries, {len(hits)} hits")
        stray = sum(1 for f in recovery["frame_start"].astype(int)
                    if not any(abs(f - h) <= 3 for h in hits))
        if stray:
            report.add("V1", "Hit_recovery not anchored on a Player_damaged", path,
                       f"{stray} row(s) start more than 3 frames from any hit")

    # --- frame/onset consistency -------------------------------------------------
    if n_frames:
        over = events[events["frame_stop"].astype("Float64") > n_frames + 1]
        if len(over):
            report.add("V1", "frame index beyond the end of the repetition", path,
                       f"{len(over)} rows, replay has {n_frames} frames")


def _check_screens(events: pd.DataFrame, repvars: dict, task: str, n_frames: int,
                   path: str, report: Report) -> Optional[List[bool]]:
    """The Screen/* rows partition the repetition and agree with the point events.

    Returns the per-frame alive mask implied by the Screen rows (None if the rows are
    unusable), for the form-row checks.
    """
    tt = events["trial_type"].astype(str)
    counts = collections.Counter(tt)
    rows = events[tt.str.startswith("Screen/")].sort_values("frame_start")
    if rows.empty:
        report.add("V1", "no Screen rows", path, "a repetition must carry Screen/* rows")
        return None
    starts = rows["frame_start"].astype(int).tolist()
    stops = rows["frame_stop"].astype(int).tolist()
    gaps = sum(1 for i in range(1, len(starts)) if starts[i] != stops[i - 1] + 1)
    if starts[0] != 0 or gaps or (n_frames and stops[-1] != n_frames - 1):
        report.add("V1", "Screen rows do not partition the repetition", path,
                   f"start {starts[0]}, {gaps} gap(s)/overlap(s), end {stops[-1]} of "
                   f"{n_frames} frames")
        return None
    alive = [True] * n_frames
    for start, stop, label in zip(starts, stops, rows["trial_type"]):
        if label in NOT_ALIVE_SCREENS:
            for frame in range(start, stop + 1):
                alive[frame] = False

    # Deaths: one Death screen per Player_died, starting on its frame.
    died = events[tt.str.startswith("Player_died")]["frame_start"].astype(int).tolist()
    death_starts = rows[rows["trial_type"] == "Screen/Death"]["frame_start"].astype(int)
    if len(died) != len(death_starts):
        report.add("V1", "Screen/Death rows disagree with Player_died", path,
                   f"{len(died)} deaths, {len(death_starts)} Death screens")
    elif sorted(died) != sorted(death_starts.tolist()):
        report.add("V1", "Screen/Death does not start on the Player_died frame", path,
                   f"deaths at {sorted(died)[:4]}, screens at "
                   f"{sorted(death_starts.tolist())[:4]}")

    # Level end: at most one, present exactly when the level was completed, containing
    # the Level_completed frame.
    ends = rows[rows["trial_type"] == "Screen/Level_end"]
    completed = events[tt == "Level_completed"]["frame_start"].astype(int).tolist()
    if len(ends) > 1:
        report.add("V1", "more than one Screen/Level_end", path, f"{len(ends)} rows")
    if bool(len(ends)) != bool(completed):
        report.add("V1", "Screen/Level_end and Level_completed disagree", path,
                   f"{len(ends)} Level_end screens, {len(completed)} Level_completed")
    elif ends is not None and len(ends) and completed:
        a, b = int(ends.iloc[0]["frame_start"]), int(ends.iloc[0]["frame_stop"])
        if not a <= completed[0] <= b:
            report.add("V1", "Level_completed outside its Screen/Level_end", path,
                       f"completed at {completed[0]}, screen {a}-{b}")

    # Pipes: entering a pipe starts a transition.
    pipes = events[tt == "Pipe_entered"]["frame_start"].astype(int).tolist()
    transitions = rows[rows["trial_type"] == "Screen/Transition"]
    spans = list(zip(transitions["frame_start"].astype(int),
                     transitions["frame_stop"].astype(int)))
    stray = sum(1 for f in pipes if not any(a <= f <= b for a, b in spans))
    if stray:
        report.add("V1", "Pipe_entered outside any Screen/Transition", path,
                   f"{stray} of {len(pipes)} pipe entries", "warning")

    # SMB1 title cards, recounted by length rather than by context: the engine-0 (NES)
    # or task-1 (SNES) stretches long enough to be the card.
    if task in ("mario", "mariostars"):
        if task == "mario":
            series = [v == 0 for v in repvars.get("player_state", [])]
        else:
            series = [(int(v) // 100) % 100 == 1 for v in repvars.get("reset", [])]
        long_runs = 0
        run = 0
        for v in series + [False]:
            if v:
                run += 1
            else:
                long_runs += run >= INTRO_MIN_FRAMES
                run = 0
        intros = counts.get("Screen/Level_intro", 0)
        if intros != long_runs:
            report.add("V1", "Screen/Level_intro count disagrees with the title-card "
                             "stretches", path,
                       f"{long_runs} stretch(es) >= {INTRO_MIN_FRAMES} frames, "
                       f"{intros} Level_intro rows", "warning")
    return alive


# ------------------------------------------------------------------------------- V2


def check_cross_port(mario_stats: Dict[str, collections.Counter],
                     stars_stats: Dict[str, collections.Counter],
                     report: Report, min_reps: int = 3,
                     tolerance: float = 0.5) -> None:
    """V2: mario and mariostars play the same SMB1 levels on two consoles.

    For each level present in both, the set of enemy types encountered should agree. A
    type seen consistently on one port and never on the other points at a decode error.
    """
    shared = sorted(set(mario_stats) & set(stars_stats))
    report.checked["levels compared"] = len(shared)
    for level in shared:
        a, b = mario_stats[level], stars_stats[level]
        if sum(a.values()) < min_reps or sum(b.values()) < min_reps:
            continue
        only_a = sorted(set(a) - set(b))
        only_b = sorted(set(b) - set(a))
        if only_a or only_b:
            report.add("V2", "enemy roster differs between the two SMB1 ports",
                       f"level {level}",
                       f"mario only: {only_a[:6]}; mariostars only: {only_b[:6]}",
                       "warning")


def enemy_roster(events: pd.DataFrame) -> collections.Counter:
    """Enemy types named by the Enemy_on_screen events of one events file."""
    rows = events[events["trial_type"].astype(str).str.startswith("Enemy_on_screen/")]
    return collections.Counter(rows["trial_type"].str.split("/").str[1])


# --------------------------------------------------------------------------- driver


def validate_dataset(dataset_dir: str, task: str, report: Optional[Report] = None,
                     limit: Optional[int] = None, with_invariants: bool = True) -> Report:
    """Run V0 (and optionally V1) over a dataset's annotated events files."""
    report = report or Report()
    pattern = op.join(dataset_dir, "sub-*", "ses-*", "func",
                      "*_desc-annotated_events.tsv")
    paths = sorted(glob(pattern))
    if limit:
        paths = paths[:limit]
    for path in paths:
        df = pd.read_csv(path, sep="\t")
        check_schema(df, task, path, report)
        if not with_invariants:
            continue
        if "stim_file" not in df.columns:
            continue
        for stim, window in _repetition_windows(df):
            if not isinstance(stim, str):
                continue
            var_path = op.join(dataset_dir, stim).replace(".bk2", "_variables.json")
            sum_path = var_path.replace("_variables.json", "_summary.json")
            if not op.exists(var_path):
                continue
            with open(var_path) as f:
                repvars = json.load(f)
            summary = {}
            if op.exists(sum_path):
                with open(sum_path) as f:
                    summary = json.load(f)
            check_invariants(window, repvars, task, summary, stim, report)
    return report


def _repetition_windows(df: pd.DataFrame):
    """Yield ``(stim_file, rows)`` for each repetition.

    ``stim_file`` is carried by the container row only, so a repetition is the set of
    rows whose onset falls inside that container's window.
    """
    reps = df[df["trial_type"] == CONTAINER]
    spans = [(float(r.onset), float(r.onset) + float(r.duration),
              getattr(r, "stim_file", None)) for r in reps.itertuples()]
    for index, (start, stop, stim) in enumerate(spans):
        # Skip repetitions whose window overlaps a neighbour: their events cannot be
        # attributed, so any invariant computed over them would be meaningless. The
        # overlap itself is reported by the V0 schema check.
        if any(i != index and s2 < stop - 0.01 and start < e2 - 0.01
               for i, (s2, e2, _) in enumerate(spans)):
            continue
        rows = df[(df["onset"] >= start - 0.05) & (df["onset"] <= stop + 0.05)]
        yield stim, rows


def slice_repetition(df: pd.DataFrame, stim_file: str) -> pd.DataFrame:
    """Rows belonging to the repetition whose container row names ``stim_file``."""
    for stim, rows in _repetition_windows(df):
        if stim == stim_file:
            return rows
    return df.iloc[0:0]


#: Backwards-compatible alias.
_slice_repetition = slice_repetition
