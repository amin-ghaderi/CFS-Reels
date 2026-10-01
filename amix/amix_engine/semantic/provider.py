"""Capability descriptors and the offline endpoint gate.

DecisionProvider is a documentation label for a future SCORE/CHOOSE adapter.
It is not a type and it is not used by conversation mapping.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

GENERATE_TEXT = "GENERATE_TEXT"
GENERATE_STRUCTURED = "GENERATE_STRUCTURED"
SCORE = "SCORE"
CHOOSE = "CHOOSE"
CLASSIFY = "CLASSIFY"
TOOL_CALLING = "TOOL_CALLING"
VISION = "VISION"
LONG_CONTEXT = "LONG_CONTEXT"

CAPABILITIES = frozenset({
    GENERATE_TEXT,
    GENERATE_STRUCTURED,
    SCORE,
    CHOOSE,
    CLASSIFY,
    TOOL_CALLING,
    VISION,
    LONG_CONTEXT,
})


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    adapter_kind: str
    model_id: str
    capabilities: frozenset[str]
    execution: str
    endpoint_host: str | None = None


@dataclass(frozen=True)
class StructuredRequest:
    task_id: str
    profile_id: str
    profile_version: str
    stage: str
    system_prompt: str
    payload: dict


def network_mode(environ: dict[str, str], saved: str | None = None) -> str:
    """Explicit ``AMIX_AI_NETWORK`` wins. An invalid value does not fall through."""
    raw = environ.get("AMIX_AI_NETWORK")
    if raw is not None and raw.strip():
        value = raw.strip().lower()
        if value not in {"offline", "network_enabled", "development"}:
            from amix.amix_engine.semantic.errors import SemanticError
            raise SemanticError("invalid_network_policy", "The network policy is not valid.")
        return value
    if saved in {"offline", "network_enabled"}:
        return saved
    return "offline"


def endpoint_host(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return parsed.hostname


def is_loopback(url: str) -> bool:
    """True only for a parsed loopback host. LAN and private ranges are remote."""
    host = endpoint_host(url)
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def assert_endpoint_allowed(url: str, mode: str) -> None:
    """Reject a remote provider before any socket is opened."""
    from amix.amix_engine.semantic.errors import SemanticError

    if endpoint_host(url) is None:
        raise SemanticError("semantic_provider_unavailable", "The semantic provider endpoint is not valid.")
    if mode == "offline" and not is_loopback(url):
        raise SemanticError(
            "offline_provider_forbidden",
            "Offline mode does not send project data to a remote provider.",
        )
