"""Run the CFS03 offline speaker resolver. Does not render video."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.speaker_resolver_v2 import (  # noqa: E402
    build_turns,
    measure_blocks,
    resolve_blocks,
    write_resolution,
)

blocks = json.loads(
    (ROOT / "data/speakers/CFS03.speakers.json").read_text(encoding="utf-8")
)["blocks"]
limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(blocks)
chosen = blocks[:limit]
samples = {}
for block in chosen:
    speaker = block.get("speaker")
    conf = float(block.get("confidence") or 0)
    samples[block["block_id"]] = 6 if speaker == "unknown" or conf < 0.75 else 4

print(f"[resolver] blocks={len(chosen)}", flush=True)
measures = measure_blocks(
    ROOT / "data/inbox/03.mp4",
    chosen,
    ROOT / "data/tmp_cfs03_preview/mouth_v2_measures.json",
    ROOT / "data/tmp_cfs03_preview/cfs03_audio_100hz.f32",
    samples=samples,
)
if limit < len(blocks):
    print(f"[resolver] timing stop after {limit}", flush=True)
    raise SystemExit(0)

rows = resolve_blocks(blocks, measures)
turns = build_turns(rows)
text = write_resolution(
    rows,
    turns,
    ROOT / "data/speakers/CFS03.speakers_resolved_v2.json",
    ROOT / "data/speakers/CFS03.speaker_resolution_report.md",
)
print(text, flush=True)
print("DONE", flush=True)
