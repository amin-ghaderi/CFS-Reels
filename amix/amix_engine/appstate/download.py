"""Manifest-controlled resource download.

The URL comes from the trusted catalog. A caller-supplied URL is ignored.
"""
from __future__ import annotations

import hashlib
import shutil
import urllib.error
import urllib.request
from pathlib import Path

from amix.amix_engine.appstate.catalog import find_entry
from amix.amix_engine.appstate.store import FAILED, READY, AppStore
from amix.amix_engine.appstate.validate import file_identity, speech_directory, vision_file, ResourceInvalid

_CHUNK = 64 * 1024


class DownloadCancelled(Exception):
    pass


def run_download(store: AppStore, job_id: str, cancel) -> None:
    job = store.resource_job(job_id)
    if job is None:
        return
    entry = find_entry(str(job["resource_id"] or ""))
    if entry is None:
        _fail(store, job_id, "unknown_resource", "That download is not in the catalog.")
        return
    incoming = store.root / "models" / ".incoming" / job_id
    target_file = incoming / "payload"
    try:
        incoming.mkdir(parents=True, exist_ok=True)
        store.update_resource_job(job_id, status="RUNNING", progress_bp=100)
        digest = hashlib.sha256()
        size = 0
        request = urllib.request.Request(entry.url, method="GET")
        with urllib.request.urlopen(request, timeout=10) as response, target_file.open("wb") as handle:
            while True:
                if cancel():
                    raise DownloadCancelled()
                block = response.read(_CHUNK)
                if not block:
                    break
                handle.write(block)
                digest.update(block)
                size += len(block)
                if entry.size_bytes:
                    store.update_resource_job(
                        job_id,
                        progress_bp=min(8000, int(8000 * size / entry.size_bytes)),
                    )
        if digest.hexdigest() != entry.sha256:
            raise ValueError("checksum")
        if entry.size_bytes is not None and size != entry.size_bytes:
            raise ValueError("checksum")
        if cancel():
            raise DownloadCancelled()
        installed = _publish(store, entry, target_file, size)
        store.update_resource_job(
            job_id,
            status="SUCCEEDED",
            progress_bp=10000,
            resource_id=installed.resource_id,
            finished_at=_finished(),
        )
    except DownloadCancelled:
        _fail(store, job_id, "cancelled", "The download was cancelled.")
        store.update_resource_job(job_id, status="CANCELLED")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, ResourceInvalid):
        _fail(store, job_id, "download_failed", "The download could not be installed.")
    finally:
        shutil.rmtree(incoming, ignore_errors=True)


def _publish(store: AppStore, entry, payload: Path, size: int):
    if entry.kind == "speech":
        dest = store.root / "models" / "speech" / entry.resource_id
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        # A speech payload is a zip-less directory marker: tests may send a model.bin body.
        model_bin = dest / "model.bin"
        shutil.copyfile(payload, model_bin)
        try:
            speech_directory(dest)
        except ResourceInvalid:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        identity = file_identity(model_bin)
        return store.add_resource(
            kind="speech",
            display_name=entry.display_name,
            local_path=str(dest),
            ownership="managed",
            origin="download",
            identity=identity,
            runtime=entry.runtime,
            version=entry.version,
            license_name=entry.license_name,
            license_url=entry.license_url,
            byte_size=size,
            status=READY,
        )
    if entry.kind == "vision":
        dest_dir = store.root / "models" / "vision" / entry.resource_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "model.onnx"
        shutil.copyfile(payload, dest)
        try:
            vision_file(dest)
        except ResourceInvalid:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise
        return store.add_resource(
            kind="vision",
            display_name=entry.display_name,
            local_path=str(dest),
            ownership="managed",
            origin="download",
            identity=file_identity(dest),
            runtime=entry.runtime,
            version=entry.version,
            license_name=entry.license_name,
            license_url=entry.license_url,
            byte_size=size,
            status=READY,
        )
    raise ValueError("kind")


def _fail(store: AppStore, job_id: str, code: str, message: str) -> None:
    store.update_resource_job(
        job_id,
        status=FAILED,
        error_code=code,
        error_message=message,
        finished_at=_finished(),
    )


def _finished() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
