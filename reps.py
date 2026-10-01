#!/data/data/com.termux/files/usr/bin/python3
"""reps.py - count push-ups in a video.

Strategy: sample a small number of frames with ffmpeg, ask a vision model to
label each frame UP (arms extended, body high) or DOWN (chest near the floor)
or NONE, then count DOWN -> UP cycles in the resulting sequence. The model is
only used as a per-frame classifier, which is far more reliable than asking it
to count directly.

  reps.py VIDEO                 # count, human readable
  reps.py VIDEO --json          # count + timeline as JSON
  reps.py VIDEO --mock down,up  # skip the model, test the counter
  reps.py VIDEO --fps 1 --max-frames 30

Requires: ffmpeg, NAN_API_KEY (see ~/phone/bin/nan).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

BASE = os.environ.get("NAN_BASE_URL", "https://api.nan.builders/v1")
MODEL = os.environ.get("PUSHUP_VLM", "qwen3.8-flash")
KEY_PATHS = ["~/.config/nan/key", "~/phone/etc/nan.key"]

PHASES = ("UP", "DOWN", "NONE")
PROMPT = (
    "These are consecutive frames from a video of one person doing push-ups.\n"
    "For EACH image, classify the person's phase:\n"
    "  UP   = arms extended, body pushed away from the floor (top of the rep)\n"
    "  DOWN = elbows bent, chest lowered near the floor (bottom of the rep)\n"
    "  NONE = no person, standing/resting, or a blurry in-between frame\n"
    "Reply with ONLY a JSON array, one string per image, in order. "
    'Example: ["UP","UP","DOWN","NONE","UP"]'
)


def api_key() -> str:
    key = os.environ.get("NAN_API_KEY")
    if key:
        return key.strip()
    for p in KEY_PATHS:
        f = os.path.expanduser(p)
        if os.path.exists(f):
            k = open(f).read().strip()
            if k:
                return k
    sys.exit("reps: no API key. Set NAN_API_KEY or write one to ~/.config/nan/key")


def http_json(path: str, payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + api_key(),
            "Content-Type": "application/json",
            "User-Agent": "curl/8.5.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit("reps: HTTP %s: %s" % (e.code, e.read().decode()[:400]))
    except urllib.error.URLError as e:
        sys.exit("reps: network error: %s" % e)


# ----------------------------------------------------------------- frames
def probe_duration(video: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", video],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def extract_frames(video: str, outdir: str, fps: float) -> list[str]:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", video,
         "-vf", "fps=%s,scale=320:-2" % fps, "-q:v", "5",
         os.path.join(outdir, "%04d.jpg")],
        check=True,
    )
    return sorted(
        os.path.join(outdir, f) for f in os.listdir(outdir) if f.endswith(".jpg")
    )


def data_url(path: str) -> str:
    with open(path, "rb") as fh:
        return "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode()


# ----------------------------------------------------------------- classifier
def classify_batch(frames: list[str]) -> list[str]:
    content = [{"type": "text", "text": PROMPT}]
    for f in frames:
        content.append({"type": "image_url", "image_url": {"url": data_url(f)}})
    out = http_json("/chat/completions", {
        "model": MODEL,
        "max_tokens": 200,
        "temperature": 0,
        "messages": [{"role": "user", "content": content}],
    })
    msg = out["choices"][0]["message"]
    text = (msg.get("content") or msg.get("reasoning") or "").strip()
    labels = parse_labels(text, len(frames))
    return labels


def parse_labels(text: str, n: int) -> list[str]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return ["NONE"] * n
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError:
        raw = re.findall(r"UP|DOWN|NONE", text, re.I)
    labels = []
    for item in raw:
        s = str(item).strip().upper()
        labels.append(s if s in PHASES else "NONE")
    if len(labels) < n:
        labels += ["NONE"] * (n - len(labels))
    return labels[:n]


def classify(frames: list[str], batch: int = 6) -> list[str]:
    labels: list[str] = []
    for i in range(0, len(frames), batch):
        chunk = frames[i:i + batch]
        labels.extend(classify_batch(chunk))
    return labels


# ----------------------------------------------------------------- counter
def numeric(labels: list[str]) -> list[int | None]:
    return [{"UP": 1, "DOWN": 0}.get(s) for s in labels]


def smooth(seq: list[int | None], window: int = 1) -> list[int | None]:
    """Fill NONE by carrying the last known value; optionally median-filter.

    At ~1.5 fps a whole push-up phase is only a few frames, so aggressive
    filtering destroys real reps. window=1 (the default) only bridges gaps;
    pass a larger odd window when sampling a slow, dense video.
    """
    filled: list[int | None] = []
    last: int | None = None
    for v in seq:
        if v is not None:
            last = v
        filled.append(last)
    while filled and filled[0] is None:
        filled.pop(0)
    if window < 3 or len(filled) < window:
        return filled
    half = window // 2
    pad = [filled[0]] * half + filled + [filled[-1]] * half
    out: list[int | None] = []
    for i in range(len(filled)):
        win = sorted(pad[i:i + window])
        out.append(win[len(win) // 2])
    return out


def count_reps(labels: list[str], min_dwell: int = 1) -> int:
    """Count DOWN -> UP transitions, requiring `min_dwell` frames in each state."""
    seq = smooth(numeric(labels))
    reps = 0
    state: int | None = None
    run = 0
    for v in seq:
        if v is None:
            continue
        if v == state:
            run += 1
            continue
        # starting a new state; a completed rep is a DOWN run followed by UP
        if state == 0 and v == 1 and run >= min_dwell:
            reps += 1
        state = v
        run = 1
    return reps


def confidence(labels: list[str]) -> float:
    known = sum(1 for s in labels if s in ("UP", "DOWN"))
    return round(known / len(labels), 2) if labels else 0.0


# ----------------------------------------------------------------- main
def analyze(video: str, fps: float, max_frames: int, mock: str | None) -> dict:
    if mock:
        labels = [s.strip().upper() for s in mock.split(",") if s.strip()]
        return {
            "reps": count_reps(labels),
            "confidence": 1.0,
            "frames": len(labels),
            "timeline": labels,
            "mock": True,
        }

    duration = probe_duration(video)
    if duration > 0:
        fps = min(fps, max_frames / duration)
    fps = max(fps, 0.1)

    tmp = tempfile.mkdtemp(prefix="reps-")
    try:
        frames = extract_frames(video, tmp, fps)
        if not frames:
            return {"reps": 0, "confidence": 0.0, "frames": 0, "timeline": []}
        labels = classify(frames)
        return {
            "reps": count_reps(labels),
            "confidence": confidence(labels),
            "frames": len(frames),
            "timeline": labels,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    p = argparse.ArgumentParser(prog="reps", description="count push-ups in a video")
    p.add_argument("video", help="path to a video file")
    p.add_argument("--fps", type=float, default=1.5, help="sampling rate (default 1.5)")
    p.add_argument("--max-frames", type=int, default=24)
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.add_argument("--mock", help="comma-separated labels, skip the model")
    a = p.parse_args()

    if not shutil.which("ffmpeg") and not a.mock:
        sys.exit("reps: ffmpeg not found")
    if not os.path.exists(a.video) and not a.mock:
        sys.exit("reps: no such file: %s" % a.video)

    result = analyze(a.video, a.fps, a.max_frames, a.mock)
    if a.json:
        print(json.dumps(result))
    else:
        print("push-ups: %d  (confidence %.2f, %d frames)"
              % (result["reps"], result["confidence"], result["frames"]))
        if result["timeline"]:
            print("timeline: " + " ".join(result["timeline"]))


if __name__ == "__main__":
    main()
