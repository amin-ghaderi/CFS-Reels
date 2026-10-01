"""OpenAI-compatible chat completions. Local and remote share this protocol."""
from __future__ import annotations

import json
import logging
import time
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlparse

from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.provider import (
    JSON_OBJECT_ONLY,
    PROMPT_ONLY_STRUCTURED,
    STRICT_JSON_SCHEMA,
    ProviderDescriptor,
    StructuredRequest,
    assert_endpoint_allowed,
)

log = logging.getLogger("amix.semantic")

CONNECT_TIMEOUT_S = 5
READ_TIMEOUT_S = 60
# Inference wait. Model startup uses a separate timeout in the local server.
LOCAL_READ_TIMEOUT_S = 120
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
        self.last_inference: dict = {}

    def generate_structured(self, request: StructuredRequest) -> dict:
        url = f"{self._base_url}/chat/completions"
        assert_endpoint_allowed(url, self._mode)
        body = {
            "model": self.descriptor.model_id,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": json.dumps(request.payload, sort_keys=True)},
            ],
        }
        response_format = _response_format(self.descriptor.structured_transport, request.output_schema)
        if response_format is not None:
            body["response_format"] = response_format
        started = time.monotonic()
        try:
            read_timeout = LOCAL_READ_TIMEOUT_S if self.descriptor.execution == "local" else READ_TIMEOUT_S
            try:
                parsed = self._transport(
                    "POST",
                    url,
                    body,
                    _headers(self._api_key),
                    CONNECT_TIMEOUT_S,
                    read_timeout,
                    MAX_RESPONSE_BYTES,
                )
            except TimeoutError as exc:
                raise SemanticError("semantic_timeout", "The semantic provider took too long.") from exc
            self.last_inference = _inference_metrics(parsed)
            result = _content_json(parsed)
            _log(self.descriptor, request, started, True, self.last_inference)
            return result
        except SemanticError:
            _log(self.descriptor, request, started, False, self.last_inference)
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


def _response_format(transport: str, schema: dict | None) -> dict | None:
    if transport == STRICT_JSON_SCHEMA and schema:
        return {
            "type": "json_schema",
            "json_schema": {"name": "amix_structured", "strict": True, "schema": schema},
        }
    if transport == JSON_OBJECT_ONLY:
        return {"type": "json_object"}
    if transport == PROMPT_ONLY_STRUCTURED:
        return None
    return None


def _inference_metrics(body: dict) -> dict:
    metrics: dict = {}
    if not isinstance(body, dict):
        return metrics
    for source in (body.get("usage"), body.get("timings")):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            metrics[key] = value
    prompt_ms = metrics.get("prompt_ms") or metrics.get("prompt_eval_ms")
    prompt_tokens = metrics.get("prompt_tokens") or metrics.get("prompt_n")
    if prompt_ms and prompt_tokens and "prompt_per_second" not in metrics:
        metrics["prompt_per_second"] = round(float(prompt_tokens) / (float(prompt_ms) / 1000), 2)
    predicted_ms = metrics.get("predicted_ms") or metrics.get("eval_ms")
    predicted_tokens = metrics.get("completion_tokens") or metrics.get("predicted_n")
    if predicted_ms and predicted_tokens and "predicted_per_second" not in metrics:
        metrics["predicted_per_second"] = round(float(predicted_tokens) / (float(predicted_ms) / 1000), 2)
    return metrics


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


_DIAGNOSTIC_KEYS = (
    "profile_id",
    "ordinal",
    "chunk_id",
    "turns",
    "words",
    "context_turns",
    "system_chars",
    "schema_chars",
    "payload_chars",
    "text_chars",
    "turn_id_chars",
    "word_id_chars",
    "participant_id_chars",
    "participant_name_chars",
    "estimated_tokens",
    "data_tokens",
    "instruction_tokens",
)


def _log(descriptor: ProviderDescriptor, request: StructuredRequest, started: float, ok: bool, metrics: dict) -> None:
    diagnostics = request.diagnostics or {}
    safe = {key: diagnostics[key] for key in _DIAGNOSTIC_KEYS if key in diagnostics}
    numbers = {key: value for key, value in metrics.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
    log.info(
        "semantic provider=%s model=%s task=%s duration_ms=%s ok=%s diagnostics=%s inference=%s",
        descriptor.provider_id,
        descriptor.model_id,
        request.task_id,
        int((time.monotonic() - started) * 1000),
        ok,
        safe,
        numbers,
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
            snippet = data[:800].decode("utf-8", "replace").lower()
            if "context" in snippet and ("exceed" in snippet or "n_ctx" in snippet):
                raise SemanticError("semantic_context_too_large", "The model context is too small for this request.")
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
