"""Process binding for the engine's global store.

Resolvers consult this only when they are using the process environment.
A caller that passes an explicit environ mapping does not see this store.
"""
from __future__ import annotations

from amix.amix_engine.appstate.secrets import SecretCache
from amix.amix_engine.appstate.store import AppStore

_store: AppStore | None = None
_secrets = SecretCache()


def bind_app(store: AppStore, secrets: SecretCache) -> None:
    global _store, _secrets
    _store = store
    _secrets = secrets


def unbind_app() -> None:
    global _store
    _store = None


def bound_store() -> AppStore | None:
    return _store


def bound_secrets() -> SecretCache:
    return _secrets
