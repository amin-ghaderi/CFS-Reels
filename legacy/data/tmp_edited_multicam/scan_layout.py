"""Classify Edited.mp4 into program layout vs protected master.

One forward decode at 2 fps. The three known tiles and the static
branded side panels are the only test. Uncertain samples stay protected.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.faces import CachedYunet, ensure_yunet_model
from reels_factory.speaker_resolver_v2 import TILES

SOURCE = ROOT / "data" / "inbox" / "Edited.mp4"
OUT = ROOT / "data" / "tmp_edited_multicam" / "layout_samples.npz"
MAP_OUT = ROOT / "data" / "director_tests" / "Edited_editability_map.json"
FPS = 2
W, H = 1920, 1080
# Side panels measured on confirmed program frames. They do not move.
LEFT = (40, 480, 560, 1040)
RIGHT = (1440, 1860, 560, 1040)
LEFT_MEAN = (28.0, 40.0)
RIGHT_MEAN = (50.0, 68.0)
LEFT_STD = (10.0, 22.0)
RIGHT_STD = (24.0, 40.0)


def gutter_ok(gray: np.ndarray) -> tuple[bool, float, float]:
    x0, x1, y0, y1 = LEFT
    left = gray[y0:y1, x0:x1]
    x0, x1, y0, y1 = RIGHT
    right = gray[y0:y1, x0:x1]
    lm, rm = float(left.mean()), float(right.mean())
    ls, rs = float(left.std()), float(right.std())
    ok = (
        LEFT_MEAN[0] <= lm <= LEFT_MEAN[1]
        and RIGHT_MEAN[0] <= rm <= RIGHT_MEAN[1]
        and LEFT_STD[0] <= ls <= LEFT_STD[1]
        and RIGHT_STD[0] <= rs <= RIGHT_STD[1]
    )
    return ok, lm, rm


def face_counts(frame: np.ndarray, detector: CachedYunet) -> list[int]:
    counts = []
    for box in TILES.values():
        x, y, w, h = box
        crop = frame[y:y + h, x:x + w]
        if crop.size == 0:
            counts.append(0)
            continue
        small = cv2.resize(crop, (448, 252), interpolation=cv2.INTER_AREA)
        found = detector.detect(small)
        counts.append(sum(1 for face in found if face.w * face.h > 2500))
    return counts


def main() -> None:
    model = ensure_yunet_model()
    if model is None:
        raise RuntimeError("YuNet model is not available")
    detector = CachedYunet(model, score_threshold=0.5)
    cmd = [
        "ffmpeg", "-v", "error",
        "-i", str(SOURCE),
        "-vf", f"fps={FPS}",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    frame_bytes = W * H * 3
    times = []
    gutter = []
    faces = []
    full_mean = []
    index = 0
    assert proc.stdout is not None
    try:
        while True:
            raw = proc.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 3)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ok, lm, rm = gutter_ok(gray)
            counts = face_counts(frame, detector) if ok else [0, 0, 0]
            times.append(index / FPS)
            gutter.append(1 if ok else 0)
            faces.append(counts)
            full_mean.append(float(gray.mean()))
            index += 1
            if index % 400 == 0:
                print(f"scanned {index} t={times[-1]:.1f}", flush=True)
    finally:
        proc.stdout.close()
        proc.wait()
    times_a = np.asarray(times, dtype=np.float64)
    gutter_a = np.asarray(gutter, dtype=np.uint8)
    faces_a = np.asarray(faces, dtype=np.uint8)
    mean_a = np.asarray(full_mean, dtype=np.float32)
    np.savez(OUT, times=times_a, gutter=gutter_a, faces=faces_a, full_mean=mean_a)
    print("frames", index, "gutter_ok", int(gutter_a.sum()), flush=True)
    print("saved", OUT, flush=True)


if __name__ == "__main__":
    main()
