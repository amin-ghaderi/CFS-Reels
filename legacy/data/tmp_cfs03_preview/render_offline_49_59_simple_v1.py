"""Render the simplified 00:49:20-00:59:20 plan. Does not touch the verified cut."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.cfs_offline_multicam_16x9 import render_offline

out = ROOT / "data/director_tests/CFS03_49-59_offline_multicam_16x9_simple_v1.mp4"
render_offline(
    ROOT / "data/director_tests/CFS03_49-59_offline_multicam_16x9_simple_v1_plan.json",
    ROOT / "data/inbox/03.mp4",
    out,
    work_dir=ROOT / "data/director_tests/_work_offline_49_59_simple_v1",
)
print("RENDER_DONE", out, flush=True)
