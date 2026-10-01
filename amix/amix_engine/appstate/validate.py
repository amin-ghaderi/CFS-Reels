"""Cheap local checks for imported resources. Exceptions stay inside this module."""
from __future__ import annotations

import hashlib
from pathlib import Path

SPEECH_COMPANIONS = (
    "config.json",
    "tokenizer.json",
    "vocabulary.txt",
    "preprocessor_config.json",
)


class ResourceInvalid(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def speech_directory(path: Path) -> None:
    if not path.is_dir() or not (path / "model.bin").is_file():
        raise ResourceInvalid("invalid_speech_model", "Speech model is invalid.")
    if not any((path / name).is_file() for name in SPEECH_COMPANIONS):
        raise ResourceInvalid("invalid_speech_model", "Speech model is invalid.")


def file_identity(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(f"{stat.st_size}:{stat.st_mtime_ns}:".encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(65536))
    return digest.hexdigest()


def speech_identity(model_dir: Path) -> str:
    return file_identity(model_dir / "model.bin")[:16]


def vision_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 1000:
        raise ResourceInvalid("invalid_vision_model", "Face model is invalid.")
    try:
        import cv2
    except Exception as exc:
        raise ResourceInvalid("vision_runtime_unavailable", "The vision runtime is not available.") from exc
    try:
        detector = cv2.FaceDetectorYN.create(str(path), "", (320, 320))
    except Exception as exc:
        raise ResourceInvalid("invalid_vision_model", "Face model is invalid.") from exc
    if detector is None:
        raise ResourceInvalid("invalid_vision_model", "Face model is invalid.")
