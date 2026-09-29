"""OpenAI-compatible chat completions. Local and remote share this protocol."""
from __future__ import annotations

import json
import logging
import time
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlparse

from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.provider import ProviderDescriptor, StructuredRequest, assert_endpoint_allowed

log = logging.getLogger("amix.semantic")

CONNECT_TIMEOUT_S = 5
READ_TIMEOUT_S = 60
MAX_RESPONSE_BYTES = 1_000_000


class OpenAICompatibleProvider:
    def __init__(
        self,
        descriptor: ProviderDescriptor,
        base_url: str,
        api_key: str | None,
        *,
        mode: str,
        transport=None,
    ) -> None:
        self.descriptor = descriptor
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or ""
        self._mode = mode
        self._transport = transport or _http_json

    def generate_structured(self, request: StructuredRequest) -> dict:
        url = f"{self._base_url}/chat/completions"
        assert_endpoint_allowed(url, self._mode)
        body = {
            "model": self.descriptor.model_id,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": json.dumps(request.payload, sort_keys=True)},
            ],
        }
        started = time.monotonic()
        try:
            try:
                parsed = self._transport(
                    "POST",
                    url,
                    body,
                    _headers(self._api_key),
                    CONNECT_TIMEOUT_S,
                    READ_TIMEOUT_S,
                    MAX_RESPONSE_BYTES,
                )
            except TimeoutError as exc:
                raise SemanticError("semantic_timeout", "The semantic provider took too long.") from exc
            result = _content_json(parsed)
            _log(self.descriptor, request.task_id, started, True)
            return result
        except SemanticError:
            _log(self.descriptor, request.task_id, started, False)
            raise

    def check(self) -> None:
        url = f"{self._base_url}/models"
        assert_endpoint_allowed(url, self._mode)
        self._transport("GET", url, None, _headers(self._api_key), CONNECT_TIMEOUT_S, 5, MAX_RESPONSE_BYTES)


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _content_json(body: dict) -> dict:
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices:
        raise SemanticError("semantic_invalid_output", "The model response could not be read.")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise SemanticError("semantic_invalid_output", "The model response could not be read.")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise SemanticError("semantic_invalid_output", "The model response was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise SemanticError("semantic_invalid_output", "The model response was not a JSON object.")
    return parsed


def _log(descriptor: ProviderDescriptor, task_id: str, started: float, ok: bool) -> None:
    log.info(
        "semantic provider=%s model=%s task=%s duration_ms=%s ok=%s",
        descriptor.provider_id,
        descriptor.model_id,
        task_id,
        int((time.monotonic() - started) * 1000),
        ok,
    )


def _http_json(method: str, url: str, payload: dict | None, headers: dict, connect_timeout: float, read_timeout: float, max_bytes: int) -> dict:
    parsed = urlparse(url)
    host = parsed.hostname
    if host is None:
        raise SemanticError("semantic_provider_unavailable", "The semantic provider endpoint is not valid.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    connection = connection_type(host, port, timeout=connect_timeout)
    try:
        connection.timeout = read_timeout
        raw = None if payload is None else json.dumps(payload).encode("utf-8")
        try:
            connection.request(method, path, body=raw, headers=headers)
            response = connection.getresponse()
            data = response.read(max_bytes + 1)
        except TimeoutError as exc:
            raise SemanticError("semantic_timeout", "The semantic provider took too long.") from exc
        except OSError as exc:
            raise SemanticError("semantic_provider_unavailable", "The semantic provider could not be reached.") from exc
        if len(data) > max_bytes:
            raise SemanticError("semantic_request_failed", "The semantic provider response was too large.")
        if response.status >= 400:
            raise SemanticError("semantic_request_failed", "The semantic provider rejected the request.")
        try:
            parsed_body = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SemanticError("semantic_invalid_output", "The model response was not valid JSON.") from exc
        if not isinstance(parsed_body, dict):
            raise SemanticError("semantic_invalid_output", "The model response was not a JSON object.")
        return parsed_body
    finally:
        connection.close()
