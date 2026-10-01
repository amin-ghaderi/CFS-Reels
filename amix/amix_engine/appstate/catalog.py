"""Trusted resource manifests.

The product catalog is empty until a source, license, and checksum are known.
Tests may add entries. Callers cannot supply a download URL.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ManifestEntry:
    resource_id: str
    kind: str
    display_name: str
    version: str
    url: str
    sha256: str
    size_bytes: int | None
    license_name: str | None
    license_url: str | None
    runtime: str


CATALOG: tuple[ManifestEntry, ...] = ()

_extra: list[ManifestEntry] = []


def catalog() -> tuple[ManifestEntry, ...]:
    return CATALOG + tuple(_extra)


def find_entry(resource_id: str) -> ManifestEntry | None:
    for entry in catalog():
        if entry.resource_id == resource_id:
            return entry
    return None


def use_test_catalog(entries: list[ManifestEntry]) -> None:
    _extra.clear()
    _extra.extend(entries)


def clear_test_catalog() -> None:
    _extra.clear()
