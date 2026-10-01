"""Memory-only provider secrets.

The OS credential store is the durable authority. This cache exists only inside
the engine process and is never written to SQLite or logs.
"""
from __future__ import annotations

import threading


class SecretCache:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._guard = threading.Lock()

    def put(self, credential_ref: str, secret: str) -> None:
        ref = credential_ref.strip()
        if not ref or not secret or any(char in secret for char in "\r\n"):
            raise ValueError("credential")
        with self._guard:
            self._values[ref] = secret

    def configured(self, credential_ref: str | None) -> bool:
        if not credential_ref:
            return False
        with self._guard:
            return bool(self._values.get(credential_ref))

    def get(self, credential_ref: str | None) -> str | None:
        if not credential_ref:
            return None
        with self._guard:
            return self._values.get(credential_ref)

    def remove(self, credential_ref: str) -> None:
        with self._guard:
            self._values.pop(credential_ref, None)
