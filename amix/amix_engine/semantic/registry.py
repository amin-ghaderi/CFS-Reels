"""Environment feeds the provider registry. Tasks see a descriptor, not env vars."""
from __future__ import annotations

import os

from amix.amix_engine.adapters.ai.openai_compatible import OpenAICompatibleProvider
from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.provider import (
    GENERATE_STRUCTURED,
    ProviderDescriptor,
    assert_endpoint_allowed,
    endpoint_host,
    is_loopback,
    network_mode,
)


def resolve_provider(environ: dict[str, str] | None = None) -> OpenAICompatibleProvider:
    env = os.environ if environ is None else environ
    base_url = env.get("AMIX_AI_BASE_URL", "").strip()
    model_id = env.get("AMIX_AI_MODEL", "").strip()
    if not base_url or not model_id:
        raise SemanticError("semantic_provider_missing", "No semantic provider is configured.")
    mode = network_mode(env)
    assert_endpoint_allowed(base_url, mode)
    local = is_loopback(base_url)
    provider_id = env.get("AMIX_AI_PROVIDER_ID", "").strip() or "openai-compatible"
    descriptor = ProviderDescriptor(
        provider_id=provider_id,
        display_name="Local model" if local else "Configured provider",
        adapter_kind="openai_compatible",
        model_id=model_id,
        capabilities=frozenset({GENERATE_STRUCTURED}),
        execution="local" if local else "remote",
        endpoint_host=endpoint_host(base_url),
    )
    return OpenAICompatibleProvider(
        descriptor,
        base_url,
        env.get("AMIX_AI_API_KEY", "").strip() or None,
        mode=mode,
    )


def provider_status(environ: dict[str, str] | None = None) -> dict:
    env = os.environ if environ is None else environ
    mode = network_mode(env)
    try:
        provider = resolve_provider(env)
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


def check_provider(environ: dict[str, str] | None = None) -> dict:
    provider = resolve_provider(environ)
    try:
        provider.check()
    except SemanticError:
        raise
    status = provider_status(environ)
    status["reachable"] = True
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
    }
