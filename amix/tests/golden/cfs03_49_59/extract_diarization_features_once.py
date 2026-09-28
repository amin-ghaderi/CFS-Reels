"""One-shot feature extraction for the CFS03 proof window. Not part of the test suite.

Reads the local master read-only, writes pre-clustering window features, and
does not write audio or video. AMIX tests skip the comparison when this
fixture is absent. They must not import this module.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from amix.amix_engine.adapters.diarize.mfcc_kmeans import SR, frame_features, window_matrix
from amix.amix_engine.adapters.media.process import run_process

REPO = Path(__file__).resolve().parents[4]
SOURCE = REPO / "legacy" / "data" / "inbox" / "03.mp4"
OUT = Path(__file__).resolve().parent / "inputs" / "diarization_features.npz"
ORIGIN_S = 2960.0
DURATION_S = 600.0


class _Never:
    def is_cancelled(self) -> bool:
        return False


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"source not available: {SOURCE}")
    from amix.amix_engine.adapters.media.discovery import discover_tools

    ffmpeg = str(discover_tools().ffmpeg)
    pcm = OUT.with_suffix(".f32le")
    completed = run_process(
        [
            ffmpeg, "-v", "error",
            "-ss", f"{ORIGIN_S:.3f}", "-t", f"{DURATION_S:.3f}",
            "-i", str(SOURCE),
            "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", str(pcm),
        ],
        _Never(),
    )
    if completed.code != 0:
        raise SystemExit(completed.stderr_tail)
    audio = np.memmap(pcm, dtype=np.float32, mode="r")
    cep, centroid, rms = frame_features(audio)
    features, times, energy = window_matrix(cep, centroid, rms)
    del audio
    np.savez_compressed(
        OUT,
        features=features.astype(np.float32),
        times=times.astype(np.float64),
        energy=energy.astype(np.float32),
    )
    pcm.unlink(missing_ok=True)
    print("wrote", OUT, features.shape)


if __name__ == "__main__":
    main()
