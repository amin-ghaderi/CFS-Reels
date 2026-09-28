"""Read-only scan of CFS03 00:30-00:40 speaker turns. Does not write pipeline data."""
import json
from pathlib import Path

speakers = json.loads(Path("data/speakers/CFS03.speakers.json").read_text(encoding="utf-8"))
blocks = speakers["blocks"]
LO, HI = 1800.0, 2400.0

def ts(s):
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:05.2f}"

rows = []
for b in blocks:
    s, e = float(b["start"]), float(b["end"])
    if e <= LO or s >= HI:
        continue
    s2, e2 = max(s, LO), min(e, HI)
    rows.append({
        "id": b.get("block_id"),
        "spk": b.get("speaker"),
        "start": s2,
        "end": e2,
        "dur": round(e2 - s2, 2),
        "conf": round(float(b.get("confidence") or 0), 3),
        "text": (b.get("text") or "").replace("\n", " ")[:140],
    })

print(f"blocks overlapping window: {len(rows)}")
# 30s buckets
print("\n=== 30s occupancy ===")
for t in range(1800, 2400, 30):
    occ = {"speaker_a": 0.0, "speaker_b": 0.0, "speaker_c": 0.0, "unknown": 0.0}
    n = 0
    for r in rows:
        ov = max(0.0, min(r["end"], t + 30) - max(r["start"], t))
        if ov > 0:
            occ[r["spk"] if r["spk"] in occ else "unknown"] += ov
            n += 1
    parts = " ".join(f"{k[-1]}={v:5.1f}" for k, v in occ.items())
    print(f"{ts(t)} {parts} blocks={n}")

print("\n=== turns >= 1.2s ===")
for r in rows:
    if r["dur"] < 1.2:
        continue
    print(f"{ts(r['start'])}-{ts(r['end'])} {r['dur']:6.1f}s {r['spk']:10} c={r['conf']:.2f} {r['text']}")

print("\n=== short backchannels < 1.2s ===")
for r in rows:
    if r["dur"] >= 1.2:
        continue
    print(f"{ts(r['start'])} {r['dur']:4.2f}s {r['spk']:10} c={r['conf']:.2f} {r['text']}")
