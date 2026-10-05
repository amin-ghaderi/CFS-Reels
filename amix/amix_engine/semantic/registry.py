"""Provider resolution. Tasks see a descriptor, not storage.

Order, and only this order:

1. ``AMIX_AI_BASE_URL`` or ``AMIX_AI_MODEL`` when either is set. A partial pair
   does not fall through.
2. The managed local model, when that source is selected. A failed local start
   does not fall through to another provider.
3. The selected external provider.
4. Unavailable.
"""
from __future__ import annotations

import os

from amix.amix_engine.adapters.ai.openai_compatible import OpenAICompatibleProvider
from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.provider import (
    GENERATE_STRUCTURED,
    STRICT_JSON_SCHEMA,
    ProviderDescriptor,
    assert_endpoint_allowed,
    endpoint_host,
    is_loopback,
    network_mode,
)


def resolve_provider(environ: dict[str, str] | None = None, cancel=None) -> OpenAICompatibleProvider:
    explicit = environ is not None
    env = os.environ if environ is None else environ
    base_url = env.get("AMIX_AI_BASE_URL", "").strip()
    model_id = env.get("AMIX_AI_MODEL", "").strip()
    if base_url or model_id:
        if not base_url or not model_id:
            raise SemanticError("semantic_provider_unavailable", "The semantic provider configuration is not valid.")
        mode = network_mode(env, None if explicit else _saved_policy())
        return _provider(env.get("AMIX_AI_PROVIDER_ID", ""), base_url, model_id, env.get("AMIX_AI_API_KEY", ""), mode)
    if explicit:
        raise SemanticError("semantic_provider_missing", "No semantic provider is configured.")
    if _semantic_source() == "managed_local":
        return _from_managed(env, cancel)
    return _from_store(env)


def _provider(
    provider_id: str,
    base_url: str,
    model_id: str,
    api_key: str,
    mode: str,
    display_name: str | None = None,
) -> OpenAICompatibleProvider:
    assert_endpoint_allowed(base_url, mode)
    local = is_loopback(base_url)
    chosen = provider_id.strip() or "openai-compatible"
    descriptor = ProviderDescriptor(
        provider_id=chosen,
        display_name=display_name or ("Local model" if local else "Configured provider"),
        adapter_kind="openai_compatible",
        model_id=model_id,
        capabilities=frozenset({GENERATE_STRUCTURED}),
        execution="local" if local else "remote",
        endpoint_host=endpoint_host(base_url),
    )
    return OpenAICompatibleProvider(descriptor, base_url, api_key.strip() or None, mode=mode)


def _from_store(env: dict[str, str]) -> OpenAICompatibleProvider:
    from amix.amix_engine.appstate.bind import bound_secrets, bound_store

    store = bound_store()
    if store is None:
        raise SemanticError("semantic_provider_missing", "No semantic provider is configured.")
    state = store.state()
    if not state.selected_provider_id:
        raise SemanticError("semantic_provider_missing", "No semantic provider is configured.")
    row = store.provider(state.selected_provider_id)
    if row is None:
        raise SemanticError("semantic_provider_missing", "No semantic provider is configured.")
    mode = network_mode(env, state.network_policy)
    secret = bound_secrets().get(row.credential_ref) or ""
    return _provider(row.provider_id, row.base_url, row.model_id, secret, mode, row.display_name)


def _from_managed(env: dict[str, str], cancel) -> OpenAICompatibleProvider:
    from amix.amix_engine.appstate.bind import bound_store
    from amix.amix_engine.appstate.local_server import ensure_local_server

    store = bound_store()
    if store is None:
        raise SemanticError("semantic_provider_missing", "No semantic provider is configured.")
    endpoint = ensure_local_server(store, cancel=cancel)
    mode = network_mode(env, store.state().network_policy)
    provider = _provider("", endpoint.base_url, endpoint.model_id, "", mode, endpoint.display_name)
    provider.descriptor = type(provider.descriptor)(
        provider_id="managed-local",
        display_name=endpoint.display_name,
        adapter_kind="openai_compatible",
        model_id=endpoint.model_id,
        capabilities=provider.descriptor.capabilities,
        execution="local",
        endpoint_host="127.0.0.1",
        runtime_kind="llama.cpp",
        runtime_version=endpoint.runtime_version,
        structured_transport=STRICT_JSON_SCHEMA,
    )
    return provider


def _semantic_source() -> str | None:
    from amix.amix_engine.appstate.bind import bound_store

    store = bound_store()
    if store is None:
        return None
    return store.state().semantic_source


def _saved_policy() -> str | None:
    from amix.amix_engine.appstate.bind import bound_store

    store = bound_store()
    if store is None:
        return None
    return store.state().network_policy


def provider_status(environ: dict[str, str] | None = None) -> dict:
    explicit = environ is not None
    env = os.environ if environ is None else environ
    try:
        mode = network_mode(env, None if explicit else _saved_policy())
    except SemanticError as exc:
        return _status(False, "offline", None, False) | {"message": exc.message, "state": "INVALID"}
    if not explicit and _semantic_source() == "managed_local":
        described = _describe_managed(mode)
        if described is not None:
            return described
        return _status(False, mode, None, False) | {"local_ai_state": "STOPPED"}
    try:
        provider = resolve_provider(environ)
    except SemanticError as exc:
        if exc.code == "semantic_provider_missing":
            return _status(False, mode, None, False)
        if exc.code == "offline_provider_forbidden":
            model_id = env.get("AMIX_AI_MODEL", "").strip() or None
            return _status(True, mode, model_id, True, execution="remote", display_name="Configured provider")
        raise
    descriptor = provider.descriptor
    return _status(
        True,
        mode,
        descriptor.model_id,
        False,
        execution=descriptor.execution,
        display_name=descriptor.display_name,
        provider_id=descriptor.provider_id,
        capability=GENERATE_STRUCTURED in descriptor.capabilities,
    )


def _describe_managed(mode: str) -> dict | None:
    from amix.amix_engine.appstate.bind import bound_store
    from amix.amix_engine.appstate.local_server import local_server_snapshot

    store = bound_store()
    if store is None:
        return None
    state = store.state()
    model = store.resource(state.selected_gguf_model_id or "")
    if model is None or model.kind != "gguf":
        return None
    snapshot = local_server_snapshot()
    status = _status(
        True,
        mode,
        model.resource_id,
        False,
        execution="local",
        display_name=model.display_name,
        provider_id="managed-local",
        capability=True,
    )
    status["local_ai_state"] = snapshot["state"]
    return status


def check_provider(environ: dict[str, str] | None = None) -> dict:
    """Reachability only. This does not run a semantic task or cancel one."""
    if environ is None and _semantic_source() == "managed_local":
        waiting = _managed_readiness()
        if waiting is not None:
            return waiting
    provider = resolve_provider(environ)
    try:
        provider.check()
    except SemanticError as exc:
        status = provider_status(environ)
        status["readiness"] = readiness_for_check_error(exc.code)
        status["reachable"] = exc.code == "semantic_timeout"
        return status
    status = provider_status(environ)
    status["readiness"] = "ready"
    status["reachable"] = True
    return status


def readiness_for_check_error(code: str) -> str:
    if code == "semantic_timeout":
        return "busy"
    if code == "semantic_provider_unavailable":
        return "unavailable"
    return "failed"


def _managed_readiness() -> dict | None:
    from amix.amix_engine.appstate.local_server import local_server_snapshot

    state = local_server_snapshot()["state"]
    if state in {"STARTING", "LOADING"}:
        readiness, reachable = "loading", None
    elif state == "FAILED":
        readiness, reachable = "failed", False
    elif state != "READY":
        readiness, reachable = "unavailable", False
    else:
        return None
    status = provider_status()
    status["readiness"] = readiness
    status["reachable"] = reachable
    return status


def _status(
    configured: bool,
    mode: str,
    model_id: str | None,
    offline_blocked: bool,
    *,
    execution: str | None = None,
    display_name: str | None = None,
    provider_id: str | None = None,
    capability: bool = False,
) -> dict:
    return {
        "configured": configured,
        "network_mode": mode,
        "execution": execution,
        "display_name": display_name,
        "model_id": model_id,
        "provider_id": provider_id,
        "capability_ready": capability and not offline_blocked,
        "offline_blocked": offline_blocked,
        "reachable": None,
        "local_ai_state": None,
        "readiness": None,
    }
