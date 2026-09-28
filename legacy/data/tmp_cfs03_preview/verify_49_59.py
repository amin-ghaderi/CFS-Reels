"""Measure and snapshot the 49:20-59:20 floor changes. Does not render."""
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_offline_verify import open_verifier, verify_boundary, measure_mouth_window
from reels_factory.speaker_resolver_v2 import TILES

OUT = Path("data/tmp_cfs03_preview/offline_49_59")
OUT.mkdir(parents=True, exist_ok=True)
VIDEO = Path("data/inbox/03.mp4")

checks = [
    (3144.20, "speaker_b", "A_to_B"),
    (3171.50, "speaker_a", "B_to_A"),
    (3176.81, "speaker_a", "interior_B0191"),
    (3304.00, "speaker_a", "gap_after_A"),
    (3317.00, "speaker_a", "gap_mid"),
    (3362.78, "speaker_c", "to_C"),
    (3368.94, "speaker_a", "C_to_A"),
    (3498.76, "speaker_c", "A_to_C"),
    (3539.36, "speaker_a", "C_to_A_return"),
]
frames = [
    2965, 2988, 3010, 3035, 3060, 3085, 3110, 3125, 3146, 3158, 3173,
    3179, 3190, 3210, 3230, 3255, 3280, 3306, 3318, 3340, 3364, 3372,
    3390, 3416, 3430, 3445, 3470, 3490, 3502, 3518, 3532, 3542, 3555,
]

cap, detector = open_verifier(VIDEO)
rows = []
for boundary, resolved, name in checks:
    row = verify_boundary(cap, detector, boundary, resolved)
    row["name"] = name
    rows.append(row)
    print(name, row["verified_active_speaker"], "override" if row["visual_override"] else "accept", row["mouth_activity"], flush=True)

for t in frames:
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
    ok, frame = cap.read()
    if not ok or frame is None:
        print("miss", t)
        continue
    tiles = []
    for key, box in TILES.items():
        x, y, w, h = box
        tile = frame[y:y + h, x:x + w]
        if tile.shape[0] < h:
            tile = cv2.copyMakeBorder(tile, 0, h - tile.shape[0], 0, 0, cv2.BORDER_CONSTANT)
        tile = cv2.resize(tile, (640, 360))
        cv2.putText(tile, f"{key[-1].upper()} {t}", (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        tiles.append(tile)
    stack = cv2.vconcat(tiles)
    cv2.imwrite(str(OUT / f"t_{t}.jpg"), stack, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    print("frame", t, flush=True)
cap.release()
Path(OUT / "verify.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE")
