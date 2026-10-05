"""Managed local semantic runtime. The server double is not a product option."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from amix.amix_engine.adapters.media.process import owned_pids
from amix.amix_engine.appstate.local_server import (
    desktop_thread_count,
    ensure_local_server,
    failure_message,
    local_server_snapshot,
    reset_local_server_for_tests,
    server_arguments,
    stop_local_server,
)
from amix.amix_engine.appstate.validate import gguf_file
from amix.amix_engine.jobs.conversation import _spec as conversation_spec
from amix.amix_engine.jobs.runner import JobFailed
from amix.amix_engine.semantic.provider import StructuredRequest
from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.registry import provider_status, resolve_provider
from amix.amix_engine.service.app import create_app
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.runtime import EngineRuntime

FAKE = Path(__file__).resolve().parent / "fake_llama_server.py"


def _gguf(path: Path, name: str = "model.gguf") -> Path:
    target = path / name
    target.write_bytes(b"GGUF" + (3).to_bytes(4, "little") + (0).to_bytes(8, "little") + (0).to_bytes(8, "little"))
    return target


class LocalSemanticTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_local_server_for_tests()

    def test_arguments_are_loopback_and_have_no_shell_text(self) -> None:
        args = server_arguments(str(FAKE), r"C:\models\model.gguf", 43111, "model-id", 2048, 4)
        self.assertNotIn("0.0.0.0", args)
        self.assertIn("127.0.0.1", args)
        self.assertIn("--port", args)
        self.assertIn("2048", args)
        self.assertIn("--parallel", args)
        self.assertEqual(args[args.index("--parallel") + 1], "1")
        self.assertIn("-t", args)
        self.assertEqual(args[args.index("-t") + 1], "4")
        blank = server_arguments(str(FAKE), r"C:\models\model.gguf", 43111, "model-id", None, None)
        self.assertEqual(blank[-1], "16384")
        self.assertEqual(blank[blank.index("--parallel") + 1], "1")
        self.assertEqual(blank[blank.index("-t") + 1], str(desktop_thread_count()))
        self.assertNotIn(";", " ".join(args))

    def test_failure_messages_stay_short(self) -> None:
        self.assertIn("memory", failure_message("CUDA failed to allocate", "exit").lower())
        self.assertIn("too long", failure_message("", "timeout").lower())
        self.assertNotIn("transcript", failure_message("hello", "exit").lower())

    def test_gguf_header_and_register_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = _gguf(root)
            version, architecture = gguf_file(model)
            self.assertEqual(version, 3)
            self.assertIsNone(architecture)
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="local", app_data=str(root / "app")))
            client = TestClient(create_app(runtime))
            headers = {"Authorization": "Bearer local"}
            try:
                imported = client.post("/v1/runtime/gguf/import", headers=headers, json={"path": str(model), "display_name": "Local"})
                self.assertEqual(imported.status_code, 200, imported.text)
                self.assertTrue(model.is_file())
                bad = client.post("/v1/runtime/gguf/import", headers=headers, json={"path": str(root / "missing.gguf")})
                self.assertEqual(bad.status_code, 400)
                self.assertEqual(bad.json()["error"]["code"], "invalid_gguf_model")
            finally:
                runtime.shutdown()

    def test_server_lifecycle_provider_and_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = _gguf(root)
            argv = root / "argv.txt"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=3, session_token="local", app_data=str(root / "app")))
            client = TestClient(create_app(runtime))
            headers = {"Authorization": "Bearer local"}
            previous = os.environ.get("FAKE_LLAMA_ARGV")
            os.environ["FAKE_LLAMA_ARGV"] = str(argv)
            try:
                llama = client.post("/v1/runtime/llama/import", headers=headers, json={"path": str(FAKE), "display_name": "Test runtime"})
                gguf = client.post("/v1/runtime/gguf/import", headers=headers, json={"path": str(model), "display_name": "Local"})
                self.assertEqual(llama.status_code, 200, llama.text)
                self.assertEqual(gguf.status_code, 200, gguf.text)
                used = client.post("/v1/runtime/local-ai/use", headers=headers, json={"source": "managed_local"})
                self.assertEqual(used.status_code, 200, used.text)
                endpoint = ensure_local_server(runtime.app, timeout_s=5)
                self.assertTrue(endpoint.base_url.startswith("http://127.0.0.1:"))
                self.assertNotIn(str(endpoint.base_url.rsplit(":", 1)[-1]), endpoint.model_id)
                provider = resolve_provider()
                self.assertEqual(provider.descriptor.execution, "local")
                self.assertEqual(provider.descriptor.provider_id, "managed-local")
                self.assertIn("GENERATE_STRUCTURED", provider.descriptor.capabilities)
                self.assertNotIn("SCORE", provider.descriptor.capabilities)
                parsed = provider.generate_structured(StructuredRequest("task", "profile", "1", "map", "system", {"turns": []}))
                self.assertEqual(parsed, {"ok": True})
                first_nonce = _nonce(endpoint.base_url)
                stop_local_server()
                self.assertEqual(local_server_snapshot()["state"], "STOPPED")
                self.assertEqual(owned_pids(), [])
                again = ensure_local_server(runtime.app, timeout_s=5)
                self.assertIn("--host", Path(argv).read_text(encoding="utf-8"))
                self.assertNotIn("0.0.0.0", Path(argv).read_text(encoding="utf-8"))
                self.assertTrue(again.base_url.startswith("http://127.0.0.1:"))
                self.assertNotEqual(first_nonce, _nonce(again.base_url))
                blocked = client.post(
                    "/v1/runtime/resources/" + gguf.json()["resource_id"] + "/remove",
                    headers=headers,
                    json={"confirm": False},
                )
                self.assertEqual(blocked.status_code, 409)
                self.assertTrue(model.is_file())
                runtime.shutdown()
                runtime.app = None
                self.assertEqual(owned_pids(), [])
                self.assertEqual(local_server_snapshot()["state"], "STOPPED")
            finally:
                if previous is None:
                    os.environ.pop("FAKE_LLAMA_ARGV", None)
                else:
                    os.environ["FAKE_LLAMA_ARGV"] = previous
                if runtime.app is not None:
                    runtime.shutdown()

    def test_crash_does_not_fall_through_to_a_remote_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = _gguf(root, "crash.gguf")
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="local", app_data=str(root / "app")))
            client = TestClient(create_app(runtime))
            headers = {"Authorization": "Bearer local"}
            try:
                client.post("/v1/runtime/llama/import", headers=headers, json={"path": str(FAKE)})
                client.post("/v1/runtime/gguf/import", headers=headers, json={"path": str(model)})
                client.post(
                    "/v1/runtime/providers",
                    headers=headers,
                    json={"display_name": "Remote", "placement": "remote", "base_url": "https://example.com/v1", "model_id": "paid"},
                )
                client.post("/v1/runtime/local-ai/use", headers=headers, json={"source": "managed_local"})
                with self.assertRaises(Exception) as caught:
                    resolve_provider()
                self.assertEqual(caught.exception.code, "local_model_failed")
                self.assertNotIn("example.com", str(caught.exception))
            finally:
                runtime.shutdown()

    def test_startup_timeout_and_cancel_leave_no_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = _gguf(root, "hang.gguf")
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="local", app_data=str(root / "app")))
            client = TestClient(create_app(runtime))
            headers = {"Authorization": "Bearer local"}
            try:
                client.post("/v1/runtime/llama/import", headers=headers, json={"path": str(FAKE)})
                client.post("/v1/runtime/gguf/import", headers=headers, json={"path": str(model)})
                client.post("/v1/runtime/local-ai/use", headers=headers, json={"source": "managed_local"})
                with self.assertRaises(Exception) as caught:
                    ensure_local_server(runtime.app, timeout_s=0.4)
                self.assertEqual(caught.exception.code, "local_model_failed")
                self.assertEqual(owned_pids(), [])

                class Cancel:
                    def is_cancelled(self) -> bool:
                        return True

                with self.assertRaises(Exception) as stopped:
                    ensure_local_server(runtime.app, timeout_s=2, cancel=Cancel())
                self.assertEqual(stopped.exception.code, "local_model_stopped")
                self.assertEqual(owned_pids(), [])
            finally:
                runtime.shutdown()

    def test_status_does_not_start_the_server_and_settings_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = _gguf(root)
            app_data = str(root / "app")
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="local", app_data=app_data))
            client = TestClient(create_app(runtime))
            headers = {"Authorization": "Bearer local"}
            try:
                client.post("/v1/runtime/llama/import", headers=headers, json={"path": str(FAKE)})
                client.post("/v1/runtime/gguf/import", headers=headers, json={"path": str(model)})
                client.post("/v1/runtime/local-ai/use", headers=headers, json={"source": "managed_local"})
                status = provider_status()
                self.assertEqual(status["local_ai_state"], "STOPPED")
                self.assertEqual(status["execution"], "local")
                self.assertTrue(status["configured"])
                self.assertEqual(owned_pids(), [])
            finally:
                runtime.shutdown()
            reopened = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="local", app_data=app_data))
            again = TestClient(create_app(reopened))
            try:
                listed = again.get("/v1/runtime/status", headers=headers)
                self.assertEqual(listed.status_code, 200, listed.text)
                body = listed.json()
                self.assertEqual(body["semantic_source"], "managed_local")
                kinds = {item["kind"] for item in body["resources"]}
                self.assertIn("llama_runtime", kinds)
                self.assertIn("gguf", kinds)
                self.assertTrue(model.is_file())
                self.assertNotIn(str(model), listed.text)
            finally:
                reopened.shutdown()

    def test_invalid_structured_output_keeps_the_existing_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = _gguf(root, "invalid-json.gguf")
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="local", app_data=str(root / "app")))
            client = TestClient(create_app(runtime))
            headers = {"Authorization": "Bearer local"}
            try:
                client.post("/v1/runtime/llama/import", headers=headers, json={"path": str(FAKE)})
                client.post("/v1/runtime/gguf/import", headers=headers, json={"path": str(model)})
                client.post("/v1/runtime/local-ai/use", headers=headers, json={"source": "managed_local"})
                provider = resolve_provider()
                with self.assertRaises(SemanticError) as caught:
                    provider.generate_structured(StructuredRequest("task", "profile", "1", "map", "system", {"turns": []}))
                self.assertEqual(caught.exception.code, "semantic_invalid_output")
            finally:
                runtime.shutdown()

    def test_conversation_and_reels_do_not_name_the_runtime(self) -> None:
        root = Path(__file__).resolve().parents[1] / "amix_engine"
        for relative in ("semantic/mapping.py", "semantic/reels.py", "jobs/conversation.py", "jobs/reels.py"):
            text = (root / relative).read_text(encoding="utf-8").lower()
            self.assertNotIn("llama", text)
            self.assertNotIn("gguf", text)
        server = (root / "appstate" / "local_server.py").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", server)
        self.assertNotIn("0.0.0.0", server)

    @unittest.skipUnless(os.environ.get("AMIX_LLAMA_SERVER") and os.environ.get("AMIX_GGUF_MODEL"), "real llama.cpp resources are not configured")
    def test_real_llama_structured_request(self) -> None:
        executable = Path(os.environ["AMIX_LLAMA_SERVER"])
        model = Path(os.environ["AMIX_GGUF_MODEL"])
        with tempfile.TemporaryDirectory() as tmp:
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=5, session_token="local", app_data=str(Path(tmp) / "app")))
            client = TestClient(create_app(runtime))
            headers = {"Authorization": "Bearer local"}
            try:
                llama = client.post("/v1/runtime/llama/import", headers=headers, json={"path": str(executable)})
                gguf = client.post("/v1/runtime/gguf/import", headers=headers, json={"path": str(model)})
                self.assertEqual(llama.status_code, 200, llama.text)
                self.assertEqual(gguf.status_code, 200, gguf.text)
                client.post("/v1/runtime/local-ai/use", headers=headers, json={"source": "managed_local"})
                provider = resolve_provider()
                self.assertEqual(provider.descriptor.execution, "local")
                try:
                    parsed = provider.generate_structured(StructuredRequest(
                        "task",
                        "profile",
                        "1",
                        "ping",
                        "Reply with a JSON object.",
                        {"reply": "ok"},
                    ))
                except SemanticError as exc:
                    self.assertEqual(exc.code, "semantic_invalid_output")
                else:
                    self.assertIsInstance(parsed, dict)
            finally:
                runtime.shutdown()

    def test_semantic_job_rejects_a_model_path(self) -> None:
        with self.assertRaises(JobFailed) as caught:
            conversation_spec({"profile_id": "amix.conversation.map.v1", "gguf_path": "C:/model.gguf", "executable": "llama-server"})
        self.assertEqual(caught.exception.code, "job_spec_rejected")


def _nonce(base_url: str) -> int:
    import json
    import urllib.request
    with urllib.request.urlopen(base_url + "/models", timeout=2) as response:
        return int(json.load(response)["nonce"])
