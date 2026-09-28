"""Development speech-model resolution.

A later Model Manager replaces this module. Callers keep using the descriptor
and the status view. Environment variables are only this phase's adapter.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_PATH = "AMIX_STT_MODEL_PATH"
_ID = "AMIX_STT_MODEL_ID"
_VERSION = "AMIX_STT_MODEL_VERSION"
_DEVICE = "AMIX_STT_DEVICE"
_COMPUTE = "AMIX_STT_COMPUTE_TYPE"

DEVICES = frozenset({"cpu", "cuda"})
COMPUTE_TYPES = frozenset({
    "int8",
    "int8_float16",
    "int8_float32",
    "int16",
    "float16",
    "float32",
    "bfloat16",
})

READY = "READY"
MODEL_MISSING = "MODEL_MISSING"
INVALID_MODEL = "INVALID_MODEL"
RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"


class SpeechResourceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SpeechModelDescriptor:
    model_id: str
    display_name: str
    runtime: str
    local_path: str
    version: str | None
    identity: str
    device: str
    compute_type: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class SpeechModelStatus:
    """Desktop view. This does not include a filesystem path."""

    state: str
    model_id: str | None
    display_name: str | None
    runtime: str | None
    message: str


def speech_model_status(environ: Mapping[str, str] | None = None) -> SpeechModelStatus:
    return _evaluate(os.environ if environ is None else environ).status


def resolve_speech_model(environ: Mapping[str, str] | None = None) -> SpeechModelDescriptor:
    evaluated = _evaluate(os.environ if environ is None else environ)
    if evaluated.descriptor is None:
        raise SpeechResourceError(evaluated.code, evaluated.status.message)
    return evaluated.descriptor


@dataclass(frozen=True)
class _Evaluated:
    status: SpeechModelStatus
    descriptor: SpeechModelDescriptor | None
    code: str


def _evaluate(environ: Mapping[str, str]) -> _Evaluated:
    runtime_ok = importlib.util.find_spec("faster_whisper") is not None
    if not runtime_ok:
        return _Evaluated(
            SpeechModelStatus(
                RUNTIME_UNAVAILABLE,
                None,
                None,
                None,
                "The speech runtime is not available.",
            ),
            None,
            "speech_runtime_unavailable",
        )
    configured = environ.get(_PATH)
    if configured is None or not configured.strip():
        return _Evaluated(
            SpeechModelStatus(
                MODEL_MISSING,
                _optional(environ, _ID),
                None,
                "faster-whisper",
                "Speech model not installed.",
            ),
            None,
            "speech_model_missing",
        )
    path = Path(configured.strip())
    model_id = _optional(environ, _ID) or (path.name if path.name else None)
    device = _choice(environ, _DEVICE, "cpu", DEVICES)
    compute = _choice(environ, _COMPUTE, "int8", COMPUTE_TYPES)
    if device is None or compute is None or not path.is_dir() or not (path / "model.bin").is_file():
        return _Evaluated(
            SpeechModelStatus(
                INVALID_MODEL,
                model_id,
                model_id,
                "faster-whisper",
                "The configured speech model cannot be used.",
            ),
            None,
            "invalid_speech_model",
        )
    identity = _identity(path / "model.bin")
    version = _optional(environ, _VERSION)
    display = model_id or path.name
    descriptor = SpeechModelDescriptor(
        model_id=display,
        display_name=display,
        runtime="faster-whisper",
        local_path=str(path.resolve()),
        version=version,
        identity=identity,
        device=device,
        compute_type=compute,
        capabilities=("transcribe", "word_timestamps"),
    )
    return _Evaluated(
        SpeechModelStatus(READY, descriptor.model_id, descriptor.display_name, descriptor.runtime, "Speech model is ready."),
        descriptor,
        "",
    )


def _choice(environ: Mapping[str, str], name: str, default: str, allowed: frozenset[str]) -> str | None:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value not in allowed:
        return None
    return value


def _optional(environ: Mapping[str, str], name: str) -> str | None:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()[:128]


def _identity(model_bin: Path) -> str:
    stat = model_bin.stat()
    digest = hashlib.sha256(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii")).hexdigest()
    return digest[:16]
