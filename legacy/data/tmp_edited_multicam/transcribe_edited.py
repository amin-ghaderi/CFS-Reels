"""Transcribe Edited.mp4 only. Does not touch CFS03 transcript files."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reels_factory.config import load_config
from reels_factory.transcribe import transcribe_longform

def main() -> None:
    cfg = load_config(ROOT)
    tcfg = dict(cfg["transcription"])
    tcfg["language"] = "fa"
    tcfg["model"] = "small"
    tcfg["device"] = "cpu"
    tcfg["compute_type"] = "int8"
    cfg = dict(cfg)
    cfg["transcription"] = tcfg
    video = ROOT / "data" / "inbox" / "Edited.mp4"
    transcripts = ROOT / "data" / "transcripts"
    transcripts.mkdir(parents=True, exist_ok=True)
    transcribe_longform(
        video,
        transcripts / "Edited.transcript.json",
        transcripts / "Edited.srt",
        cfg,
        words_json=transcripts / "Edited.words.json",
        language="fa",
        chunk_s=600.0,
        overlap_s=1.5,
    )
    print("TRANSCRIBE_DONE", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
