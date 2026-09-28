# AMIX

AMIX is a local-first, cross-platform intelligent video editing platform for
long-form conversational video.

Current status:
Phase 2 deterministic engine core.

`amix_engine` can import the CFS03 49–59 minute fixture and recompute word
assignments, speaking turns, overlap regions (from saved lip activity, not
from video), and an automatic 16:9 shot plan. Time is integer microseconds
on the source timeline.

## Tests

From the repository root, with Python 3.12 and no extra packages:

```
python -m unittest discover -s amix/tests -p "test_*.py" -t .
```

The suite does not use the network, the source video, FFmpeg, Whisper, or OpenCV.

## Not implemented yet

Desktop shell, database, rendering, transcription, diarization from audio,
face detection, cloud or local LLM providers, Reel editing, and conversation maps.
