"""Stable semantic failures. Messages stay short and do not include provider bodies."""
from __future__ import annotations


class SemanticError(Exception):
    def __init__(self, code: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
