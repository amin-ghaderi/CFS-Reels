"""YuNet through OpenCV. Imported only by the overlap worker."""
from __future__ import annotations

from pathlib import Path

from amix.amix_engine.adapters.vision.lips import FaceSample


class YunetDetector:
    def __init__(self, model_path: str, score_threshold: float = 0.5) -> None:
        import cv2

        self._cv2 = cv2
        self._path = str(Path(model_path))
        self._threshold = score_threshold
        self._detector = None
        self._size: tuple[int, int] | None = None

    def detect(self, frame) -> list[FaceSample]:
        height, width = frame.shape[:2]
        size = (width, height)
        if self._detector is None or self._size != size:
            self._detector = self._cv2.FaceDetectorYN.create(
                self._path,
                "",
                size,
                float(self._threshold),
                0.3,
                5000,
            )
            self._size = size
        self._detector.setInputSize(size)
        _faces, rows = self._detector.detect(frame)
        if rows is None:
            return []
        samples = []
        for row in rows:
            landmarks = None
            if len(row) >= 15:
                landmarks = tuple((float(row[4 + 2 * index]), float(row[5 + 2 * index])) for index in range(5))
            samples.append(FaceSample(w=float(row[2]), h=float(row[3]), landmarks=landmarks))
        return samples
