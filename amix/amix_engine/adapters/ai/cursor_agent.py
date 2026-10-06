"""Cursor Development semantic adapter.

Headless `agent -p` with an explicit model. ACP cannot pin the model id
returned by `agent models`, so this adapter does not use it.

The request body goes through stdin. The working directory is a neutral
temp folder, outside the AMIX source tree. Ask mode is read-only.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from amix.amix_engine.adapters.media.process import (
    ProcessCancelled,
    ProcessResult,
    run_process,
    spawn_background,
    terminate_owned_processes,
)
from amix.amix_engine.jobs.runner import JobCancelled
from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.provider import (
    GENERATE_STRUCTURED,
    SCHEMA_IN_PROMPT,
    ProviderDescriptor,
    StructuredRequest,
)

log = logging.getLogger("amix.semantic")

PROVIDER_ID = "cursor-development"
ADAPTER_KIND = "cursor_agent"
PREFERRED_MODEL_ID = "grok-4.7-high"
REQUEST_TIMEOUT_S = 300.0
PROBE_TIMEOUT_S = 20.0
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")

_INFLIGHT = 0
_INFLIGHT_LOCK = threading.Lock()
_CACHE_LOCK = threading.Lock()
_CACHE: dict = {"auth": None, "models": []}
_LOGIN = None
_LOGIN_LOCK = threading.Lock()


@dataclass(frozen=True)
class CursorInstall:
    node: Path
    script: Path
    version: str


def validate_model_id(model_id: str) -> str:
    """An explicit Cursor model id. Auto is not a selection."""
    chosen = (model_id or "").strip()
    if chosen.lower() == "auto" or _MODEL_ID.fullmatch(chosen) is None:
        raise ValueError("explicit model id required")
    return chosen


def cursor_generation_active() -> bool:
    with _INFLIGHT_LOCK:
        return _INFLIGHT > 0


def reset_cursor_for_tests() -> None:
    global _INFLIGHT, _LOGIN
    with _INFLIGHT_LOCK:
        _INFLIGHT = 0
    with _CACHE_LOCK:
        _CACHE["auth"] = None
        _CACHE["models"] = []
    with _LOGIN_LOCK:
        _LOGIN = None
    terminate_owned_processes(1.0)


def neutral_workspace() -> Path:
    path = Path(tempfile.gettempdir()) / "amix-cursor-neutral"
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_cursor_agent() -> CursorInstall | None:
    """The bundled node runtime. The PowerShell wrapper is not used."""
    override_node = os.environ.get("AMIX_CURSOR_AGENT_NODE", "").strip()
    override_script = os.environ.get("AMIX_CURSOR_AGENT_SCRIPT", "").strip()
    if override_node or override_script:
        node = Path(override_node)
        script = Path(override_script)
        if node.is_file() and script.is_file():
            version = os.environ.get("AMIX_CURSOR_AGENT_VERSION", "").strip() or "test"
            return CursorInstall(node, script, version)
        return None
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        return None
    versions = Path(local) / "cursor-agent" / "versions"
    if not versions.is_dir():
        return None
    found = []
    for child in versions.iterdir():
        node = child / "node.exe"
        script = child / "index.js"
        if child.is_dir() and node.is_file() and script.is_file():
            found.append(child)
    if not found:
        return None
    chosen = sorted(found, key=lambda item: item.name)[-1]
    return CursorInstall(chosen / "node.exe", chosen / "index.js", chosen.name)


def agent_command(install: CursorInstall, model_id: str, workspace: Path) -> list[str]:
    return [
        str(install.node),
        str(install.script),
        "-p",
        "--model", model_id,
        "--output-format", "json",
        "--mode", "ask",
        "--trust",
        "--workspace", str(workspace),
    ]


def parse_models(text: str) -> list[dict]:
    """Lines from `agent models`: ``id - display name``. Auto is omitted."""
    found: list[dict] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.replace("\ufeff", "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").strip()
        if " - " not in line:
            continue
        model_id, name = line.split(" - ", 1)
        model_id = model_id.strip()
        try:
            model_id = validate_model_id(model_id)
        except ValueError:
            continue
        if model_id in seen:
            continue
        seen.add(model_id)
        found.append({"id": model_id, "name": name.strip() or model_id})
    return found


def cursor_facts(model_id: str | None = None) -> dict:
    install = find_cursor_agent()
    with _CACHE_LOCK:
        auth = _CACHE["auth"]
        models = list(_CACHE["models"])
    ids = [item["id"] for item in models]
    if cursor_generation_active():
        status = "busy"
        message = "A semantic request is running."
    elif install is None:
        status = "not_installed"
        message = "Cursor Agent CLI is not installed."
    elif auth is False:
        status = "login_required"
        message = "Sign in with your Cursor account to use this provider."
    elif auth is True and model_id and model_id in ids:
        status = "ready"
        message = "Ready."
    elif auth is True and model_id and ids and model_id not in ids:
        status = "unavailable"
        message = "The selected model is not in the Cursor model list."
    elif not model_id:
        status = "unavailable"
        message = "Choose an explicit Cursor model."
    else:
        status = "unavailable"
        message = "Check Cursor to confirm sign-in and the selected model."
    return {
        "installed": install is not None,
        "version": None if install is None else install.version,
        "path": None if install is None else str(install.node),
        "model_id": model_id,
        "models": models,
        "status": status,
        "message": message,
        "development": True,
    }


class CursorAgentSemanticProvider:
    def __init__(self, descriptor: ProviderDescriptor, install: CursorInstall, mode: str, cancel=None) -> None:
        self.descriptor = descriptor
        self._install = install
        self._mode = mode
        self._cancel = cancel
        self.last_inference: dict = {}
        self.transport_attempts = 0

    def generate_structured(self, request: StructuredRequest) -> dict:
        if self._mode == "offline":
            raise SemanticError(
                "offline_provider_forbidden",
                "Offline mode does not send project data to Cursor.",
            )
        prompt = semantic_prompt(request)
        workspace = neutral_workspace()
        command = agent_command(self._install, self.descriptor.model_id, workspace)
        started = time.monotonic()
        _enter()
        try:
            try:
                result = self._invoke(command, prompt, workspace)
                if result.code != 0 and _repeating(result.stderr_tail):
                    raise SemanticError(
                        "semantic_repetition_stop",
                        "Cursor Agent stopped a repeating response.",
                    )
            except TimeoutError as exc:
                raise SemanticError("semantic_timeout", "The semantic provider took too long.") from exc
            except ProcessCancelled as exc:
                raise JobCancelled() from exc
        finally:
            _leave()
        if result.code != 0:
            raise SemanticError("semantic_request_failed", "Cursor Agent rejected the request.")
        parsed = _inner_json(result.stdout)
        _log(self.descriptor, request, started, True)
        return parsed

    def _invoke(self, command: list[str], prompt: str, workspace) -> ProcessResult:
        self.transport_attempts += 1
        return run_process(
            command,
            self._cancel,
            cwd=str(workspace),
            stdin_text=prompt,
            timeout_s=_request_timeout(),
        )

    def check(self) -> None:
        """Executable, sign-in, and selected model. No transcript is sent."""
        if cursor_generation_active():
            return
        if self._mode == "offline":
            raise SemanticError(
                "offline_provider_forbidden",
                "Offline mode does not send project data to Cursor.",
            )
        _probe(self._install, self.descriptor.model_id, select_preferred=False)


def _repeating(stderr: str) -> bool:
    return "agent looping detected" in (stderr or "").lower()


def semantic_prompt(request: StructuredRequest) -> str:
    """The task prompt and payload already built for every semantic provider."""
    blocks = [request.system_prompt.strip()]
    if request.output_schema:
        blocks.append(
            "Response schema:\n"
            + json.dumps(request.output_schema, ensure_ascii=False, separators=(",", ":"))
        )
    blocks.append("Return one JSON object and nothing else. No markdown.")
    blocks.append(
        "DATA\n" + json.dumps(request.payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    )
    return "\n\n".join(blocks)


def check_cursor(store) -> dict:
    """Lightweight probe. An in-flight semantic request is left running."""
    if cursor_generation_active():
        return cursor_panel(store)
    mode = _store_mode(store)
    if mode == "offline":
        return cursor_panel(store)
    install = find_cursor_agent()
    if install is None:
        with _CACHE_LOCK:
            _CACHE["auth"] = None
            _CACHE["models"] = []
        return cursor_panel(store)
    try:
        _probe(install, store.state().cursor_model_id, select_preferred=True, store=store)
    except SemanticError:
        return cursor_panel(store)
    return cursor_panel(store)


def refresh_cursor_models(store) -> dict:
    if cursor_generation_active():
        return cursor_panel(store)
    if _store_mode(store) == "offline":
        return cursor_panel(store)
    install = find_cursor_agent()
    if install is None:
        return cursor_panel(store)
    _load_models(install, store, select_preferred=True)
    return cursor_panel(store)


def start_cursor_login() -> bool:
    """Official `agent login`. The browser step belongs to the user."""
    global _LOGIN
    install = find_cursor_agent()
    if install is None:
        return False
    with _LOGIN_LOCK:
        if _LOGIN is not None and _LOGIN.poll() is None:
            return True
        _LOGIN = spawn_background(
            [str(install.node), str(install.script), "login"],
            cwd=str(neutral_workspace()),
        )
    return True


def cursor_panel(store) -> dict:
    model_id = None if store is None else store.state().cursor_model_id
    selected = False if store is None else store.state().semantic_source == "cursor-development"
    facts = cursor_facts(model_id)
    if store is not None and _store_mode(store) == "offline" and facts["status"] != "not_installed":
        facts = {
            **facts,
            "status": "unavailable",
            "message": "Offline mode does not send transcript content to Cursor.",
        }
    return {**facts, "selected": selected}


def _probe(install: CursorInstall, model_id: str | None, *, select_preferred: bool, store=None) -> None:
    try:
        result = run_process(
            [str(install.node), str(install.script), "status"],
            None,
            cwd=str(neutral_workspace()),
            timeout_s=PROBE_TIMEOUT_S,
        )
    except (TimeoutError, ProcessCancelled, OSError) as exc:
        with _CACHE_LOCK:
            _CACHE["auth"] = None
        raise SemanticError("semantic_provider_unavailable", "Cursor Agent did not respond.") from exc
    if not _authenticated(result.stdout, result.code):
        with _CACHE_LOCK:
            _CACHE["auth"] = False
            _CACHE["models"] = []
        raise SemanticError("cursor_login_required", "Sign in with your Cursor account to use this provider.")
    with _CACHE_LOCK:
        _CACHE["auth"] = True
    _load_models(install, store, select_preferred=select_preferred)
    chosen = store.state().cursor_model_id if store is not None else model_id
    with _CACHE_LOCK:
        ids = [item["id"] for item in _CACHE["models"]]
    if not chosen or chosen not in ids:
        raise SemanticError("semantic_provider_unavailable", "Choose an explicit Cursor model.")


def _load_models(install: CursorInstall, store, *, select_preferred: bool) -> None:
    try:
        result = run_process(
            [str(install.node), str(install.script), "models"],
            None,
            cwd=str(neutral_workspace()),
            timeout_s=PROBE_TIMEOUT_S,
        )
    except (TimeoutError, ProcessCancelled, OSError):
        return
    text = result.stdout or ""
    if result.code != 0 and _auth_required(text):
        with _CACHE_LOCK:
            _CACHE["auth"] = False
            _CACHE["models"] = []
        return
    models = parse_models(text)
    with _CACHE_LOCK:
        if models:
            _CACHE["models"] = models
            if _CACHE["auth"] is None:
                _CACHE["auth"] = True
    if store is None or not select_preferred or not models:
        return
    ids = [item["id"] for item in models]
    current = store.state().cursor_model_id
    if not current and PREFERRED_MODEL_ID in ids:
        store.set_cursor_model(PREFERRED_MODEL_ID)


def _authenticated(text: str, code: int) -> bool:
    lowered = text.lower()
    if _auth_required(lowered):
        return False
    return code == 0 and "logged in" in lowered


def _auth_required(text: str) -> bool:
    lowered = text.lower()
    return "not logged in" in lowered or "authentication required" in lowered


def _inner_json(stdout: str) -> dict:
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SemanticError("semantic_invalid_output", "The model response was not valid JSON.") from exc
    if not isinstance(envelope, dict):
        raise SemanticError("semantic_invalid_output", "The model response was not a JSON object.")
    if envelope.get("is_error") is True:
        raise SemanticError("semantic_request_failed", "Cursor Agent rejected the request.")
    result = envelope.get("result")
    if not isinstance(result, str):
        raise SemanticError("semantic_invalid_output", "The model response could not be read.")
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError as exc:
        raise SemanticError("semantic_invalid_output", "The model response was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise SemanticError("semantic_invalid_output", "The model response was not a JSON object.")
    return parsed


def _request_timeout() -> float:
    raw = os.environ.get("AMIX_CURSOR_REQUEST_TIMEOUT", "").strip()
    if not raw:
        return REQUEST_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return REQUEST_TIMEOUT_S
    if value <= 0:
        return REQUEST_TIMEOUT_S
    return value


def _store_mode(store) -> str:
    from amix.amix_engine.semantic.provider import network_mode

    return network_mode(os.environ, None if store is None else store.state().network_policy)


def _enter() -> None:
    global _INFLIGHT
    with _INFLIGHT_LOCK:
        _INFLIGHT += 1


def _leave() -> None:
    global _INFLIGHT
    with _INFLIGHT_LOCK:
        _INFLIGHT = max(0, _INFLIGHT - 1)


def _log(descriptor: ProviderDescriptor, request: StructuredRequest, started: float, ok: bool) -> None:
    log.info(
        "semantic provider=%s model=%s task=%s duration_ms=%s ok=%s",
        descriptor.provider_id,
        descriptor.model_id,
        request.task_id,
        int((time.monotonic() - started) * 1000),
        ok,
    )


def descriptor_for(model_id: str, version: str) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=PROVIDER_ID,
        display_name="Cursor Development",
        adapter_kind=ADAPTER_KIND,
        model_id=model_id,
        capabilities=frozenset({GENERATE_STRUCTURED}),
        execution="remote",
        endpoint_host="api2.cursor.sh",
        runtime_kind="cursor-agent",
        runtime_version=version,
        structured_transport=SCHEMA_IN_PROMPT,
        # 29-turn halves of a looping 58-turn chunk succeeded. Larger packs stay split.
        preferred_max_turns=29,
    )
