from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from reels_factory.config import load_config
from reels_factory.conversation import analyze_conversation


def main() -> int:
    cfg = load_config(ROOT)
    video = ROOT / "data" / "inbox" / "CFS03.mp4"
    wav = ROOT / "data" / "tmp_cfs03_preview" / "CFS03.16k.wav"
    result = analyze_conversation(
        video,
        cfg,
        root=ROOT,
        force=False,
        language="fa",
        audio_wav=wav if wav.is_file() else None,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
