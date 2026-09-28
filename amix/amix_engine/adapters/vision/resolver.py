"""Development YuNet resolution. No download and no legacy cache.

A later Model Manager replaces this module. Overlap code depends on the
descriptor, not on the environment variable.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_PATH = "AMIX_YUNET_MODEL_PATH"
_ID = "AMIX_YUNET_MODEL_ID"
_VERSION = "AMIX_YUNET_MODEL_VERSION"

READY = "READY"
MODEL_MISSING = "MODEL_MISSING"
INVALID_MODEL = "INVALID_MODEL"
RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"


class VisionResourceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class VisionModelDescriptor:
    model_id: str
    display_name: str
    runtime: str
    local_path: str
    version: str | None
    identity: str


@dataclass(frozen=True)
class VisionModelStatus:
    """Desktop view. This does not include a filesystem path."""

    state: str
    model_id: str | None
    display_name: str | None
    runtime: str | None
    message: str


def vision_model_status(environ: Mapping[str, str] | None = None) -> VisionModelStatus:
    return _evaluate(os.environ if environ is None else environ).status


def resolve_vision_model(environ: Mapping[str, str] | None = None) -> VisionModelDescriptor:
    evaluated = _evaluate(os.environ if environ is None else environ)
    if evaluated.descriptor is None:
        raise VisionResourceError(evaluated.code, evaluated.status.message)
    return evaluated.descriptor


@dataclass(frozen=True)
class _Evaluated:
    status: VisionModelStatus
    descriptor: VisionModelDescriptor | None
    code: str


def _evaluate(environ: Mapping[str, str]) -> _Evaluated:
    if importlib.util.find_spec("cv2") is None:
        return _Evaluated(
            VisionModelStatus(RUNTIME_UNAVAILABLE, None, None, None, "The vision runtime is not available."),
            None,
            "vision_runtime_unavailable",
        )
    configured = environ.get(_PATH)
    if configured is None or not str(configured).strip():
        return _Evaluated(
            VisionModelStatus(MODEL_MISSING, None, None, "opencv", "Face model not installed."),
            None,
            "vision_model_missing",
        )
    path = Path(str(configured).strip())
    if not path.is_file() or path.stat().st_size < 1000:
        return _Evaluated(
            VisionModelStatus(INVALID_MODEL, None, None, "opencv", "The configured face model cannot be used."),
            None,
            "invalid_vision_model",
        )
    model_id = _optional(environ, _ID) or path.name
    version = _optional(environ, _VERSION)
    identity = _identity(path)
    return _Evaluated(
        VisionModelStatus(READY, model_id, "YuNet", "opencv", "Face model ready."),
        VisionModelDescriptor(
            model_id=model_id,
            display_name="YuNet",
            runtime="opencv",
            local_path=str(path),
            version=version,
            identity=identity,
        ),
        "vision_model_ready",
    )


def _optional(environ: Mapping[str, str], key: str) -> str | None:
    value = environ.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _identity(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(f"{stat.st_size}:{stat.st_mtime_ns}:".encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(65536))
    return digest.hexdigest()
