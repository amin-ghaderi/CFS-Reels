"""Cursor Development provider. The agent executable is a local double."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from amix.amix_engine.adapters.ai.cursor_agent import (
    agent_command,
    cursor_generation_active,
    find_cursor_agent,
    neutral_workspace,
    parse_models,
    reset_cursor_for_tests,
)
from amix.amix_engine.adapters.media.process import owned_pids, terminate_owned_processes
from amix.amix_engine.appstate.bind import bind_app, unbind_app
from amix.amix_engine.appstate.local_server import reset_local_server_for_tests
from amix.amix_engine.appstate.secrets import SecretCache
from amix.amix_engine.appstate.store import SettingsRejected, open_app
from amix.amix_engine.jobs.conversation import MapConversationJob
from amix.amix_engine.jobs.reels import DiscoverReelsJob
from amix.amix_engine.jobs.runner import CancellationToken, JobCancelled, JobContext, JobFailed
from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.mapping import map_conversation
from amix.amix_engine.semantic.provider import StructuredRequest
from amix.amix_engine.semantic.registry import check_provider, resolve_provider
from amix.amix_engine.semantic.tasks import SYSTEM_PROMPT
from amix.amix_engine.service.app import create_app
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.storage.kinds import CONVERSATION_MAP
from amix.tests.test_conversation_map import _seeded
from amix.tests.test_local_semantic import FAKE as FAKE_LLAMA
from amix.tests.test_local_semantic import _gguf
FAKE = Path(__file__).resolve().parent / "fake_cursor_agent.py"
MODEL = "grok-4.7-high"


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class CursorSemanticTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_cursor_for_tests()
        reset_local_server_for_tests()
        unbind_app()

    def test_parser_keeps_explicit_models_and_drops_auto(self) -> None:
        models = parse_models("auto - Auto (default)\ngrok-4.7-high - Grok 4.7 High\ncomposer-2.5 - Composer 2.5\n")
        self.assertEqual([item["id"] for item in models], ["grok-4.7-high", "composer-2.5"])
        from amix.amix_engine.adapters.ai.cursor_agent import descriptor_for
        self.assertEqual(descriptor_for(MODEL, "2026.10.01-test").preferred_max_turns, 29)
        command = agent_command(find_cursor_agent() or _missing_install(), MODEL, neutral_workspace())
        self.assertIsInstance(command, list)
        self.assertIn("--model", command)
        self.assertEqual(command[command.index("--model") + 1], MODEL)
        self.assertIn("--mode", command)
        self.assertEqual(command[command.index("--mode") + 1], "ask")
        self.assertNotIn("hello", " ".join(command))
        self.assertNotIn("CFS-Reels", str(neutral_workspace()))

    def test_registration_selection_and_no_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = open_app(Path(tmp) / "app")
            bind_app(store, SecretCache())
            store.set_network_policy("network_enabled")
            store.set_cursor_model(MODEL)
            store.set_semantic_source("cursor-development")
            missing = Path(tmp) / "missing-node"
            with _env(node=missing, script=missing):
                with patch("amix.amix_engine.semantic.registry._from_managed") as managed:
                    with patch("amix.amix_engine.semantic.registry._from_store") as remote:
                        with self.assertRaises(SemanticError) as missing_cli:
                            resolve_provider()
                self.assertEqual(missing_cli.exception.code, "semantic_provider_unavailable")
                managed.assert_not_called()
                remote.assert_not_called()
            with _env():
                provider = resolve_provider()
            self.assertEqual(provider.descriptor.provider_id, "cursor-development")
            self.assertEqual(provider.descriptor.adapter_kind, "cursor_agent")
            self.assertEqual(provider.descriptor.model_id, MODEL)
            self.assertEqual(provider.descriptor.execution, "remote")
            store.set_network_policy("offline")
            with _env():
                with self.assertRaises(SemanticError) as blocked:
                    resolve_provider()
            self.assertEqual(blocked.exception.code, "offline_provider_forbidden")
            self.assertFalse(Path(tmp, "unused-log").exists())
            store.close()

    def test_settings_selection_persists_and_check_is_lightweight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_data = str(Path(tmp) / "app")
            log = Path(tmp) / "agent.log"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="cursor", app_data=app_data))
            client = TestClient(create_app(runtime))
            headers = {"Authorization": "Bearer cursor"}
            try:
                with _env(log=log, auth="no"):
                    runtime.app.set_network_policy("network_enabled")
                    selected = client.post("/v1/runtime/semantic-source", headers=headers, json={"source": "cursor-development"})
                    self.assertEqual(selected.status_code, 200, selected.text)
                    rejected = client.post("/v1/runtime/cursor/model", headers=headers, json={"model_id": "auto"})
                    self.assertEqual(rejected.status_code, 400)
                    saved = client.post("/v1/runtime/cursor/model", headers=headers, json={"model_id": MODEL})
                    self.assertEqual(saved.status_code, 200, saved.text)
                    checked = client.post("/v1/runtime/cursor/check", headers=headers)
                    self.assertEqual(checked.status_code, 200, checked.text)
                    body = client.get("/v1/runtime/status", headers=headers).json()
                    self.assertEqual(body["semantic_source"], "cursor-development")
                    self.assertEqual(body["cursor"]["status"], "login_required")
                    self.assertEqual(body["cursor"]["model_id"], MODEL)
                    self.assertNotIn("sk-", json.dumps(body))
                    self.assertNotIn("hello", log.read_text(encoding="utf-8"))
            finally:
                runtime.shutdown()
            reopened = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="cursor", app_data=app_data))
            again = TestClient(create_app(reopened))
            try:
                body = again.get("/v1/runtime/status", headers=headers).json()
                self.assertEqual(body["semantic_source"], "cursor-development")
                self.assertEqual(body["cursor"]["model_id"], MODEL)
                with _env(auth="yes"):
                    reopened.app.set_network_policy("network_enabled")
                    refreshed = again.post("/v1/runtime/cursor/models", headers=headers)
                    self.assertEqual(refreshed.status_code, 200, refreshed.text)
                    listed = again.get("/v1/runtime/status", headers=headers).json()["cursor"]
                    self.assertIn(MODEL, [item["id"] for item in listed["models"]])
                    self.assertNotIn("auto", [item["id"] for item in listed["models"]])
            finally:
                reopened.shutdown()

    def test_conversation_and_reels_use_the_selected_model_and_keep_a_failed_rebuild(self) -> None:
        store, asset, _root = _seeded()
        app = open_app(store.root.parent / "app-state")
        bind_app(app, SecretCache())
        app.set_network_policy("network_enabled")
        app.set_semantic_source("cursor-development")
        app.set_cursor_model(MODEL)
        log = store.root.parent / "agent.log"
        try:
            with _env(log=log):
                job = store.create_processing_job(kind="map_conversation", spec={}, media_asset_id=asset)
                result = MapConversationJob().run(JobContext(store, job.job_id, {}, CancellationToken(), asset))
                config = store.analysis_record(result["conversation_map_run_id"])["config"]
                self.assertEqual(config["provider_id"], "cursor-development")
                self.assertEqual(config["adapter_kind"], "cursor_agent")
                self.assertEqual(config["model_id"], MODEL)
                self.assertEqual(config["task_id"], "conversation_map")
                self.assertGreaterEqual(config["duration_ms"], 0)
                self.assertEqual(result["repair_count"], 0)
                self.assertNotIn("hello", log.read_text(encoding="utf-8"))
                self.assertNotIn("hello", json.dumps(config))
                argv = " ".join(json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["argv"])
                self.assertIn(MODEL, argv)
                cwd = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["cwd"]
                self.assertNotIn("CFS-Reels", cwd)
                before = result["conversation_map_run_id"]
                os.environ["FAKE_CURSOR_MODE"] = "repair"
                repaired = map_conversation(store, asset, resolve_provider(), CancellationToken(), lambda _value: None)
                self.assertEqual(repaired["repair_count"], 1)
                self.assertEqual(store.analysis_record(repaired["conversation_map_run_id"])["config"]["model_id"], MODEL)
                os.environ["FAKE_CURSOR_MODE"] = "bad"
                with self.assertRaises(SemanticError):
                    map_conversation(store, asset, resolve_provider(), CancellationToken(), lambda _value: None)
                self.assertEqual(store.get_active_run_id(asset, CONVERSATION_MAP), repaired["conversation_map_run_id"])
                self.assertNotEqual(before, repaired["conversation_map_run_id"])
                os.environ["FAKE_CURSOR_MODE"] = "exit"
                failed_job = store.create_processing_job(kind="map_conversation", spec={}, media_asset_id=asset)
                with self.assertRaises(JobFailed) as failed:
                    MapConversationJob().run(JobContext(store, failed_job.job_id, {}, CancellationToken(), asset))
                self.assertEqual(failed.exception.code, "semantic_request_failed")
                self.assertEqual(store.get_active_run_id(asset, CONVERSATION_MAP), repaired["conversation_map_run_id"])
                os.environ["FAKE_CURSOR_MODE"] = "loop"
                os.environ.pop("FAKE_CURSOR_LOOP_STATE", None)
                log.write_text("", encoding="utf-8")
                stuck_job = store.create_processing_job(kind="map_conversation", spec={}, media_asset_id=asset)
                with self.assertRaises(JobFailed) as stuck:
                    MapConversationJob().run(JobContext(store, stuck_job.job_id, {}, CancellationToken(), asset))
                self.assertEqual(stuck.exception.code, "semantic_repetition_stop")
                self.assertIn("repeating", stuck.exception.message)
                self.assertEqual(
                    len([line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]),
                    1,
                )
                self.assertEqual(store.get_active_run_id(asset, CONVERSATION_MAP), repaired["conversation_map_run_id"])
                os.environ["FAKE_CURSOR_MODE"] = "fence"
                with self.assertRaises(SemanticError) as fenced:
                    provider = resolve_provider()
                    provider.generate_structured(StructuredRequest(
                        "conversation_map", "p", "1", "chunk", SYSTEM_PROMPT, {"turns": [["T1", 0, "hello"]]},
                    ))
                self.assertEqual(fenced.exception.code, "semantic_invalid_output")
            mapped = _reel_project(store, asset)
            self.assertIsNotNone(mapped)
            with _env():
                reel_job = store.create_processing_job(kind="discover_reels", spec={}, media_asset_id=asset)
                discovered = DiscoverReelsJob().run(JobContext(store, reel_job.job_id, {}, CancellationToken(), asset))
                reel_config = store.analysis_record(discovered["reel_discovery_run_id"])["config"]
                self.assertEqual(reel_config["provider_id"], "cursor-development")
                self.assertEqual(reel_config["adapter_kind"], "cursor_agent")
                self.assertEqual(reel_config["model_id"], MODEL)
                self.assertEqual(reel_config["task_id"], "reel_discover")
                self.assertGreaterEqual(discovered["candidate_count"], 1)
        finally:
            store.close()
            app.close()

    def test_timeout_cancel_and_shutdown_reap_the_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = open_app(root / "app")
            bind_app(app, SecretCache())
            app.set_network_policy("network_enabled")
            app.set_semantic_source("cursor-development")
            app.set_cursor_model(MODEL)
            child_file = root / "child.txt"
            try:
                with _env(mode="sleep", child=child_file, timeout="0.8"):
                    provider = resolve_provider()
                    with self.assertRaises(SemanticError) as timed:
                        provider.generate_structured(_tiny())
                    self.assertEqual(timed.exception.code, "semantic_timeout")
                    self.assertFalse(_alive(int(child_file.read_text(encoding="utf-8"))))
                    self.assertEqual(owned_pids(), [])
                    self.assertFalse(cursor_generation_active())
                child_file.unlink(missing_ok=True)
                with _env(mode="sleep", child=child_file, timeout="30"):
                    token = CancellationToken()
                    provider = resolve_provider(cancel=token)
                    box: dict = {}

                    def _run() -> None:
                        try:
                            provider.generate_structured(_tiny())
                        except JobCancelled:
                            box["cancelled"] = True

                    thread = threading.Thread(target=_run)
                    thread.start()
                    self.assertTrue(_wait_for(child_file))
                    self.assertTrue(_alive(int(child_file.read_text(encoding="utf-8"))))
                    status = check_provider()
                    self.assertEqual(status["readiness"], "busy")
                    self.assertTrue(_alive(int(child_file.read_text(encoding="utf-8"))))
                    token.request()
                    thread.join(5)
                    self.assertTrue(box.get("cancelled"))
                    self.assertFalse(thread.is_alive())
                    self.assertFalse(_alive(int(child_file.read_text(encoding="utf-8"))))
                    self.assertEqual(owned_pids(), [])
                child_file.unlink(missing_ok=True)
                with _env(mode="sleep", child=child_file, timeout="30"):
                    provider = resolve_provider()
                    box = {}

                    def _run_shutdown() -> None:
                        try:
                            provider.generate_structured(_tiny())
                        except Exception as exc:
                            box["error"] = type(exc).__name__

                    thread = threading.Thread(target=_run_shutdown)
                    thread.start()
                    self.assertTrue(_wait_for(child_file))
                    runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="cursor", app_data=str(root / "other")))
                    runtime.shutdown()
                    thread.join(5)
                    self.assertFalse(thread.is_alive())
                    self.assertFalse(_alive(int(child_file.read_text(encoding="utf-8"))))
                    self.assertEqual(owned_pids(), [])
            finally:
                terminate_owned_processes(1)
                app.close()

    def test_managed_local_and_remote_provider_still_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = _gguf(root)
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="cursor", app_data=str(root / "app")))
            client = TestClient(create_app(runtime))
            headers = {"Authorization": "Bearer cursor"}
            try:
                client.post("/v1/runtime/llama/import", headers=headers, json={"path": str(FAKE_LLAMA)})
                client.post("/v1/runtime/gguf/import", headers=headers, json={"path": str(model)})
                client.post("/v1/runtime/local-ai/use", headers=headers, json={"source": "managed_local"})
                with _clear_ai_env():
                    local = resolve_provider()
                self.assertEqual(local.descriptor.provider_id, "managed-local")
                self.assertEqual(local.descriptor.adapter_kind, "openai_compatible")
                saved = client.post(
                    "/v1/runtime/providers",
                    headers=headers,
                    json={
                        "display_name": "Cloud",
                        "placement": "remote",
                        "base_url": "https://example.test/v1",
                        "model_id": "remote-model",
                    },
                )
                self.assertEqual(saved.status_code, 200, saved.text)
                runtime.app.set_network_policy("network_enabled")
                client.post(f"/v1/runtime/providers/{saved.json()['provider_id']}/select", headers=headers)
                with _clear_ai_env():
                    remote = resolve_provider()
                self.assertEqual(remote.descriptor.provider_id, saved.json()["provider_id"])
                self.assertEqual(remote.descriptor.model_id, "remote-model")
                self.assertEqual(remote.descriptor.adapter_kind, "openai_compatible")
                with self.assertRaises(SettingsRejected):
                    runtime.app.set_cursor_model("auto")
            finally:
                runtime.shutdown()


class _Install:
    def __init__(self) -> None:
        self.node = Path("node")
        self.script = Path("index.js")
        self.version = "test"


def _missing_install():
    return _Install()


def _tiny() -> StructuredRequest:
    return StructuredRequest("conversation_map", "p", "1", "chunk", SYSTEM_PROMPT, {"stage": "chunk", "turns": [["T1", 0, "hello"]]})


def _reel_project(store, asset: str) -> str:
    from amix.amix_engine.domain.types import ParticipantId, Turn
    from amix.amix_engine.semantic.mapping import map_conversation as map_again
    from amix.amix_engine.time.clock import TimeRange
    from amix.tests.test_conversation_map import FakeStructuredProvider, _cover

    assignment = store.get_active_run_id(asset, "participant_assignment")
    window = TimeRange(0, 80_000_000)
    turns = store.save_turns(
        asset_id=asset,
        turns=[
            Turn("T1", ParticipantId("a"), 0, 40_000_000, ("w1", "w2")),
            Turn("T2", None, 40_000_000, 80_000_000, ("w3",)),
        ],
        depends_on=[assignment],
        algorithm_id="amix.turns.v1",
        algorithm_version="1",
        fingerprint="tu-cursor",
        window=window,
    )
    store.set_active(asset, "turns", turns)
    mapped = map_again(store, asset, FakeStructuredProvider(_cover), CancellationToken(), lambda _value: None)
    return mapped["conversation_map_run_id"]


def _wait_for(path: Path) -> bool:
    import time
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if path.is_file() and path.read_text(encoding="utf-8").strip():
            return True
        time.sleep(0.05)
    return False


class _env:
    def __init__(self, node: Path | None = None, script: Path | None = None, log: Path | None = None, auth: str = "yes", mode: str = "ok", child: Path | None = None, timeout: str | None = None) -> None:
        self._values = {
            "AMIX_CURSOR_AGENT_NODE": str(_python() if node is None else node),
            "AMIX_CURSOR_AGENT_SCRIPT": str(script or FAKE),
            "AMIX_CURSOR_AGENT_VERSION": "2026.10.01-test",
            "FAKE_CURSOR_AUTH": "no" if auth == "no" else "yes",
            "FAKE_CURSOR_MODE": mode,
        }
        if log is not None:
            self._values["FAKE_CURSOR_LOG"] = str(log)
        if child is not None:
            self._values["FAKE_CURSOR_CHILD"] = str(child)
        if timeout is not None:
            self._values["AMIX_CURSOR_REQUEST_TIMEOUT"] = timeout
        self._patch = None

    def __enter__(self):
        cleared = {key: os.environ.get(key) for key in ("AMIX_AI_BASE_URL", "AMIX_AI_MODEL", "AMIX_AI_NETWORK")}
        for key in cleared:
            os.environ.pop(key, None)
        self._patch = patch.dict(os.environ, self._values)
        self._patch.start()
        self._cleared = cleared
        return self

    def __exit__(self, exc_type, exc, tb):
        self._patch.stop()
        for key, value in self._cleared.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return False


def _python() -> Path:
    import sys
    return Path(sys.executable)


class _clear_ai_env:
    def __enter__(self):
        self._patch = patch.dict(os.environ, {}, clear=False)
        self._saved = {key: os.environ.pop(key, None) for key in ("AMIX_AI_BASE_URL", "AMIX_AI_MODEL", "AMIX_AI_NETWORK")}
        return self

    def __exit__(self, exc_type, exc, tb):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return False


if __name__ == "__main__":
    unittest.main()
