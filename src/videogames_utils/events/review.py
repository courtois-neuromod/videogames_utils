"""V3: build a human review set to measure how exact the generated events actually are.

The replay pipeline already writes a frame-aligned ``_recording.mp4`` for every
repetition, and every event row carries ``frame_start``. This module cuts a short clip
around a stratified sample of events, burns in the label and a frame counter, and writes
a self-contained HTML page on which a rater marks each clip correct / incorrect /
unclear. :func:`score_reviews` then turns the saved ratings into precision per event
type.

Recall needs the complementary sample: :func:`build_recall_windows` cuts unlabelled
windows of gameplay for a rater to annotate exhaustively, which is then compared against
what the generator emitted for the same windows.

Requires ffmpeg on PATH for the clip cutting.
"""

from __future__ import annotations

import collections
import json
import math
import os
import os.path as op
import random
import subprocess
from dataclasses import dataclass, asdict
from glob import glob
from typing import Dict, List, Optional

import pandas as pd

from .emit import TASK_FRAME_RATES

#: Seconds of context on either side of the event.
DEFAULT_PAD = 2.0

#: Event types whose correctness is a direct counter read and needs only a spot check.
LOW_RISK_PREFIXES = ("Action", "Item_collected/Coin", "gym-retro_game")


@dataclass
class Clip:
    """One clip presented to the rater."""

    clip_id: str
    task: str
    trial_type: str
    stim_file: str
    onset: float
    rep_onset: float
    frame_start: int
    filename: str


def _rep_onsets(events: pd.DataFrame) -> Dict[str, float]:
    reps = events[events["trial_type"] == "gym-retro_game"]
    return {r.stim_file: float(r.onset) for r in reps.itertuples()
            if isinstance(getattr(r, "stim_file", None), str)}


def sample_events(events_dir: str, task: str, per_type: int = 50,
                  seed: int = 0, include_low_risk: int = 5) -> List[dict]:
    """Pick a stratified sample of events, spread across subjects and levels.

    Deterministic given ``seed`` so a review set can be rebuilt exactly.
    """
    rng = random.Random(seed)
    by_type: Dict[str, List[dict]] = collections.defaultdict(list)

    for path in sorted(glob(op.join(events_dir, "sub-*", "ses-*", "func",
                                    "*_desc-annotated_events.tsv"))):
        events = pd.read_csv(path, sep="\t")
        if "stim_file" not in events.columns:
            continue
        onsets = _rep_onsets(events)
        for row in events.itertuples():
            trial_type = str(row.trial_type)
            stim = getattr(row, "stim_file", None)
            if trial_type == "gym-retro_game" or not isinstance(stim, str):
                continue
            by_type[trial_type].append({
                "task": task,
                "trial_type": trial_type,
                "stim_file": stim,
                "onset": float(row.onset),
                "rep_onset": onsets.get(stim, 0.0),
                "frame_start": int(row.frame_start) if not pd.isna(row.frame_start) else 0,
            })

    sample: List[dict] = []
    for trial_type, rows in sorted(by_type.items()):
        quota = per_type
        if any(trial_type.startswith(p) for p in LOW_RISK_PREFIXES):
            quota = min(per_type, include_low_risk)
        # spread over distinct repetitions before allowing repeats within one
        rng.shuffle(rows)
        seen_reps: collections.Counter = collections.Counter()
        rows.sort(key=lambda r: seen_reps.update([r["stim_file"]]) or seen_reps[r["stim_file"]])
        sample.extend(rows[:quota])
    return sample


def cut_clip(dataset_dir: str, item: dict, out_dir: str, pad: float = DEFAULT_PAD,
             fs: Optional[float] = None) -> Optional[str]:
    """Cut one labelled clip with ffmpeg. Returns the filename, or None on failure."""
    fs = fs or TASK_FRAME_RATES[item["task"]]
    video = op.join(dataset_dir, item["stim_file"]).replace(".bk2", "_recording.mp4")
    if not op.exists(video):
        return None

    # onset is run-relative; the video starts at the repetition.
    within = max(0.0, item["onset"] - item["rep_onset"])
    start = max(0.0, within - pad)
    marker = within - start

    name = (f"{item['task']}_{item['trial_type'].replace('/', '-')}_"
            f"{op.basename(item['stim_file']).replace('.bk2', '')}_"
            f"{item['frame_start']}.mp4")
    out_path = op.join(out_dir, name)
    if op.exists(out_path):
        return name

    label = item["trial_type"].replace(":", r"\:").replace("'", "")
    # A red band flashes for 0.2 s at the event, and the label is always on screen.
    draw = (
        f"drawtext=text='{label}':x=8:y=8:fontsize=16:fontcolor=yellow:"
        f"box=1:boxcolor=black@0.6,"
        f"drawbox=x=0:y=0:w=iw:h=ih:color=red@0.8:t=4:"
        f"enable='between(t,{marker:.3f},{marker + 0.2:.3f})'"
    )
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}",
           "-t", f"{2 * pad:.3f}", "-i", video, "-vf", draw,
           "-an", "-c:v", "libx264", "-preset", "veryfast", out_path]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return name


def build_review_set(dataset_dir: str, task: str, out_dir: str, per_type: int = 50,
                     pad: float = DEFAULT_PAD, seed: int = 0,
                     events_dir: Optional[str] = None) -> dict:
    """Build clips plus an HTML rating page. Returns a manifest dict.

    Args:
        dataset_dir: Dataset root, where the ``_recording.mp4`` files live.
        events_dir: Where the annotated events files are, if not in ``dataset_dir``
            (e.g. a scratch output directory from a trial run).
    """
    os.makedirs(out_dir, exist_ok=True)
    items = sample_events(events_dir or dataset_dir, task, per_type=per_type, seed=seed)

    clips: List[Clip] = []
    for index, item in enumerate(items):
        name = cut_clip(dataset_dir, item, out_dir, pad=pad)
        if name is None:
            continue
        clips.append(Clip(clip_id=f"{task}-{index:05d}", filename=name, **item))

    manifest = {"task": task, "dataset_dir": dataset_dir, "pad": pad, "seed": seed,
                "clips": [asdict(c) for c in clips]}
    with open(op.join(out_dir, "manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=2)
    with open(op.join(out_dir, "review.html"), "w") as handle:
        handle.write(_review_page(manifest))
    return manifest


def _review_page(manifest: dict) -> str:
    """A self-contained rating page: no server, ratings export as JSON."""
    clips_json = json.dumps(manifest["clips"])
    return """<!doctype html>
<meta charset="utf-8">
<title>Event review - %(task)s</title>
<style>
 body{font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px;background:#111;color:#eee}
 h1{font-size:18px;margin:0 0 4px} .sub{color:#999;margin-bottom:16px}
 .wrap{display:flex;gap:24px;align-items:flex-start}
 video{width:512px;background:#000;border:1px solid #333}
 .meta{font-family:ui-monospace,monospace;font-size:12px;color:#bbb;margin:8px 0}
 button{font:14px system-ui;padding:8px 14px;margin-right:8px;border:0;border-radius:6px;cursor:pointer}
 .yes{background:#1a7f37;color:#fff} .no{background:#a40e26;color:#fff}
 .maybe{background:#7a5c00;color:#fff} .skip{background:#333;color:#ccc}
 #prog{color:#999;margin-top:12px} pre{background:#000;padding:12px;max-height:200px;overflow:auto}
</style>
<h1>Event review &mdash; %(task)s</h1>
<div class="sub">Does the highlighted moment really show this event? Keyboard: 1 yes, 2 no, 3 unclear, 0 skip.</div>
<div class="wrap">
  <div>
    <video id="v" controls autoplay muted loop></video>
    <div class="meta" id="meta"></div>
    <button class="yes" onclick="rate('correct')">1 &middot; Correct</button>
    <button class="no" onclick="rate('incorrect')">2 &middot; Incorrect</button>
    <button class="maybe" onclick="rate('unclear')">3 &middot; Unclear</button>
    <button class="skip" onclick="rate(null)">0 &middot; Skip</button>
    <div id="prog"></div>
    <p><button onclick="save()">Download ratings JSON</button></p>
  </div>
  <div><pre id="tally"></pre></div>
</div>
<script>
const CLIPS = %(clips)s;
const KEY = 'review-%(task)s';
let ratings = JSON.parse(localStorage.getItem(KEY) || '{}');
let i = 0;
function next(){ while(i < CLIPS.length && ratings[CLIPS[i].clip_id]) i++; show(); }
function show(){
  if(i >= CLIPS.length){ document.getElementById('meta').textContent = 'All clips rated.'; return; }
  const c = CLIPS[i];
  document.getElementById('v').src = c.filename;
  document.getElementById('meta').textContent =
    c.trial_type + '  |  ' + c.stim_file.split('/').pop() + '  |  frame ' + c.frame_start;
  document.getElementById('prog').textContent =
    (i+1) + ' / ' + CLIPS.length + '  (' + Object.keys(ratings).length + ' rated)';
  tally();
}
function rate(verdict){
  if(i >= CLIPS.length) return;
  if(verdict) ratings[CLIPS[i].clip_id] = {verdict: verdict, trial_type: CLIPS[i].trial_type};
  localStorage.setItem(KEY, JSON.stringify(ratings));
  i++; show();
}
function tally(){
  const by = {};
  for(const id in ratings){ const r = ratings[id];
    by[r.trial_type] = by[r.trial_type] || {correct:0, incorrect:0, unclear:0};
    by[r.trial_type][r.verdict]++; }
  const rows = Object.keys(by).sort().map(t => {
    const b = by[t], n = b.correct + b.incorrect;
    const p = n ? (100*b.correct/n).toFixed(0) + '%%' : '-';
    return t.padEnd(34) + ' ' + String(b.correct).padStart(4) + ' ok ' +
           String(b.incorrect).padStart(4) + ' bad  precision ' + p; });
  document.getElementById('tally').textContent = rows.join('\\n') || 'no ratings yet';
}
function save(){
  const blob = new Blob([JSON.stringify(ratings, null, 2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'ratings-%(task)s.json'; a.click();
}
document.addEventListener('keydown', e => {
  if(e.key === '1') rate('correct'); else if(e.key === '2') rate('incorrect');
  else if(e.key === '3') rate('unclear'); else if(e.key === '0') rate(null);
});
next();
</script>
""" % {"task": manifest["task"], "clips": clips_json}


def score_reviews(ratings_path: str, manifest_path: str,
                  min_precision: float = 0.95) -> pd.DataFrame:
    """Turn saved ratings into precision per event type, with a Wilson interval."""
    with open(ratings_path) as handle:
        ratings = json.load(handle)
    with open(manifest_path) as handle:
        manifest = json.load(handle)

    by_type: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for clip_id, rating in ratings.items():
        by_type[rating["trial_type"]][rating["verdict"]] += 1

    rows = []
    for trial_type, counts in sorted(by_type.items()):
        correct, incorrect = counts["correct"], counts["incorrect"]
        n = correct + incorrect
        if not n:
            continue
        p = correct / n
        lo, hi = _wilson(correct, n)
        rows.append({"trial_type": trial_type, "n_rated": n, "precision": round(p, 3),
                     "ci_low": round(lo, 3), "ci_high": round(hi, 3),
                     "unclear": counts["unclear"],
                     "passes": lo >= min_precision})
    return pd.DataFrame(rows)


def _wilson(successes: int, n: int, z: float = 1.96):
    """Wilson score interval, which behaves sensibly at p near 1."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def build_recall_windows(dataset_dir: str, task: str, out_dir: str, n_windows: int = 20,
                         seconds: float = 10.0, seed: int = 0,
                         events_dir: Optional[str] = None) -> dict:
    """Cut unlabelled windows for exhaustive annotation, to measure recall.

    The rater lists every event of interest they see; comparing that against what the
    generator emitted over the same frame range gives recall (and catches whole event
    types that are never emitted, which a precision-only review cannot).
    """
    os.makedirs(out_dir, exist_ok=True)
    rng = random.Random(seed)
    paths = sorted(glob(op.join(events_dir or dataset_dir, "sub-*", "ses-*", "func",
                                "*_desc-annotated_events.tsv")))
    rng.shuffle(paths)

    windows = []
    for path in paths:
        if len(windows) >= n_windows:
            break
        events = pd.read_csv(path, sep="\t")
        reps = events[events["trial_type"] == "gym-retro_game"]
        if reps.empty:
            continue
        rep = reps.iloc[rng.randrange(len(reps))]
        stim = rep["stim_file"]
        if not isinstance(stim, str):
            continue
        duration = float(rep["duration"])
        if duration <= seconds:
            continue
        start = rng.uniform(0, duration - seconds)
        item = {"task": task, "trial_type": "RECALL_WINDOW", "stim_file": stim,
                "onset": float(rep["onset"]) + start, "rep_onset": float(rep["onset"]),
                "frame_start": int(start * TASK_FRAME_RATES[task])}
        name = cut_clip(dataset_dir, item, out_dir, pad=seconds / 2)
        if name is None:
            continue
        expected = events[(events["stim_file"] == stim)
                          & (events["onset"] >= item["onset"])
                          & (events["onset"] < item["onset"] + seconds)]
        windows.append({**item, "filename": name,
                        "generated": collections.Counter(
                            expected["trial_type"]).most_common()})

    manifest = {"task": task, "seconds": seconds, "windows": windows}
    with open(op.join(out_dir, "recall_manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=2)
    return manifest
