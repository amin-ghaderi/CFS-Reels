from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reels_factory.config import load_config
from reels_factory.transcribe import transcribe_longform


def main() -> int:
    cfg = load_config(ROOT)
    video = ROOT / "data" / "inbox" / "CFS03.mp4"
    wav = ROOT / "data" / "tmp_cfs03_preview" / "CFS03.16k.wav"
    transcripts = Path(cfg["paths"]["transcripts"])
    transcripts.mkdir(parents=True, exist_ok=True)
    out_json = transcripts / "CFS03.transcript.json"
    out_srt = transcripts / "CFS03.srt"
    words_json = transcripts / "CFS03.words.json"
    tcfg = dict(cfg["transcription"])
    tcfg["language"] = tcfg.get("language") or "fa"
    cfg = dict(cfg)
    cfg["transcription"] = tcfg
    transcribe_longform(
        video,
        out_json,
        out_srt,
        cfg,
        audio_wav=wav if wav.is_file() else None,
        words_json=words_json,
        language="fa",
        chunk_s=600.0,
        overlap_s=1.5,
    )
    print(f"words: {words_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
