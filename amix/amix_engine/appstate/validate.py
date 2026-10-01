"""Cheap local checks for imported resources. Exceptions stay inside this module."""
from __future__ import annotations

import hashlib
import subprocess
import sys
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


def llama_executable(path: Path) -> tuple[Path, str]:
    """Return the llama-server file and a short version line."""
    executable = _llama_candidate(path)
    if executable is None or not executable.is_file():
        raise ResourceInvalid("invalid_llama_runtime", "This program is not a usable llama.cpp server.")
    completed = _bounded_run(executable, ["--version"])
    if completed is None:
        completed = _bounded_run(executable, ["-h"])
    if completed is None or completed.returncode != 0:
        raise ResourceInvalid("invalid_llama_runtime", "This program is not a usable llama.cpp server.")
    text = (completed.stdout or completed.stderr).strip().splitlines()
    version = text[0][:120] if text else None
    if not version:
        raise ResourceInvalid("invalid_llama_runtime", "This program is not a usable llama.cpp server.")
    return executable, version


def gguf_file(path: Path) -> tuple[int, str | None]:
    """Read the GGUF header. The rest of a large file is not loaded."""
    if not path.is_file():
        raise ResourceInvalid("invalid_gguf_model", "This file is not a GGUF model.")
    try:
        with path.open("rb") as handle:
            if handle.read(4) != b"GGUF":
                raise ResourceInvalid("invalid_gguf_model", "This file is not a GGUF model.")
            version_raw = handle.read(4)
            counts = handle.read(16)
            if len(version_raw) < 4 or len(counts) < 16:
                raise ResourceInvalid("invalid_gguf_model", "This file is not a GGUF model.")
            version = int.from_bytes(version_raw, "little")
            if version < 1 or version > 3:
                raise ResourceInvalid("invalid_gguf_model", "This GGUF version is not supported.")
            kv_count = int.from_bytes(counts[8:16], "little")
            architecture = _gguf_architecture(handle, min(kv_count, 64))
    except ResourceInvalid:
        raise
    except OSError as exc:
        raise ResourceInvalid("invalid_gguf_model", "This file is not a GGUF model.") from exc
    return version, architecture


def command_for(executable: Path, args: list[str]) -> list[str]:
    if executable.suffix.lower() == ".py":
        return [sys.executable, str(executable), *args]
    return [str(executable), *args]


def _llama_candidate(path: Path) -> Path | None:
    if path.is_file():
        return path
    if not path.is_dir():
        return None
    for name in ("llama-server.exe", "llama-server"):
        candidate = path / name
        if candidate.is_file():
            return candidate
    return None


def _bounded_run(executable: Path, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command_for(executable, args),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=8,
            shell=False,
            text=True,
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _gguf_architecture(handle, limit: int) -> str | None:
    consumed = 0
    for _ in range(limit):
        if consumed > 1_000_000:
            return None
        key, used = _gguf_string(handle)
        consumed += used
        type_raw = handle.read(4)
        if len(type_raw) < 4:
            return None
        consumed += 4
        value_type = int.from_bytes(type_raw, "little")
        if key == "general.architecture" and value_type == 8:
            value, _used = _gguf_string(handle)
            return value[:128]
        skipped = _skip_gguf_value(handle, value_type, 1_000_000 - consumed)
        if skipped is None:
            return None
        consumed += skipped
    return None


def _gguf_string(handle) -> tuple[str, int]:
    raw = handle.read(8)
    if len(raw) < 8:
        raise ResourceInvalid("invalid_gguf_model", "This file is not a GGUF model.")
    length = int.from_bytes(raw, "little")
    if length > 4096:
        raise ResourceInvalid("invalid_gguf_model", "This file is not a GGUF model.")
    data = handle.read(length)
    if len(data) < length:
        raise ResourceInvalid("invalid_gguf_model", "This file is not a GGUF model.")
    return data.decode("utf-8", "replace"), 8 + length


def _skip_gguf_value(handle, value_type: int, budget: int) -> int | None:
    widths = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
    if value_type in widths:
        size = widths[value_type]
        if size > budget:
            return None
        return size if len(handle.read(size)) == size else None
    if value_type == 8:
        raw = handle.read(8)
        if len(raw) < 8:
            return None
        length = int.from_bytes(raw, "little")
        if length > budget:
            return None
        return 8 + length if len(handle.read(length)) == length else None
    if value_type == 9:
        header = handle.read(12)
        if len(header) < 12:
            return None
        element_type = int.from_bytes(header[:4], "little")
        count = int.from_bytes(header[4:12], "little")
        if count > 32:
            return None
        used = 12
        for _ in range(count):
            skipped = _skip_gguf_value(handle, element_type, budget - used)
            if skipped is None:
                return None
            used += skipped
        return used
    return None
