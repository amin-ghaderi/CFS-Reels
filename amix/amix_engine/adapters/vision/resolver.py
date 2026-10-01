"""YuNet resolution.

Order, and only this order:

1. ``AMIX_YUNET_MODEL_PATH`` when it is set. An invalid file does not fall through.
2. The selected global vision resource, when the engine has an application store.
3. Unavailable.

Overlap code depends on the descriptor. An explicit environ mapping does not
read the process-global store.
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
    return _evaluate(_env(environ), _store(environ)).status


def resolve_vision_model(environ: Mapping[str, str] | None = None) -> VisionModelDescriptor:
    evaluated = _evaluate(_env(environ), _store(environ))
    if evaluated.descriptor is None:
        raise VisionResourceError(evaluated.code, evaluated.status.message)
    return evaluated.descriptor


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _store(environ: Mapping[str, str] | None):
    if environ is not None:
        return None
    from amix.amix_engine.appstate.bind import bound_store
    return bound_store()


@dataclass(frozen=True)
class _Evaluated:
    status: VisionModelStatus
    descriptor: VisionModelDescriptor | None
    code: str


def _evaluate(environ: Mapping[str, str], store) -> _Evaluated:
    if importlib.util.find_spec("cv2") is None:
        return _Evaluated(
            VisionModelStatus(RUNTIME_UNAVAILABLE, None, None, None, "The vision runtime is not available."),
            None,
            "vision_runtime_unavailable",
        )
    configured = environ.get(_PATH)
    if configured is not None and str(configured).strip():
        override = Path(str(configured).strip())
        return _from_file(override, _optional(environ, _ID), _optional(environ, _VERSION))
    if store is not None:
        selected = _selected_vision(store)
        if selected is not None:
            return selected
    return _Evaluated(
        VisionModelStatus(MODEL_MISSING, None, None, "opencv", "Face model not installed."),
        None,
        "vision_model_missing",
    )


def _from_file(path: Path, model_id: str | None, version: str | None) -> _Evaluated:
    if not path.is_file() or path.stat().st_size < 1000:
        return _Evaluated(
            VisionModelStatus(INVALID_MODEL, model_id, model_id, "opencv", "The configured face model cannot be used."),
            None,
            "invalid_vision_model",
        )
    chosen = model_id or path.name
    return _ready(chosen, path, version)


def _selected_vision(store) -> _Evaluated | None:
    state = store.state()
    if not state.selected_vision_id:
        return None
    resource = store.resource(state.selected_vision_id)
    if resource is None or resource.kind != "vision":
        return None
    path = Path(resource.local_path)
    if not path.is_file():
        return _Evaluated(
            VisionModelStatus(MODEL_MISSING, resource.resource_id, resource.display_name, "opencv", "Face model is missing."),
            None,
            "vision_model_missing",
        )
    return _ready(resource.resource_id, path, resource.version, resource.display_name)


def _ready(model_id: str, path: Path, version: str | None, display_name: str = "YuNet") -> _Evaluated:
    if not path.is_file() or path.stat().st_size < 1000:
        return _Evaluated(
            VisionModelStatus(INVALID_MODEL, model_id, display_name, "opencv", "The configured face model cannot be used."),
            None,
            "invalid_vision_model",
        )
    return _Evaluated(
        VisionModelStatus(READY, model_id, display_name, "opencv", "Face model ready."),
        VisionModelDescriptor(
            model_id=model_id,
            display_name=display_name,
            runtime="opencv",
            local_path=str(path),
            version=version,
            identity=_identity(path),
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
