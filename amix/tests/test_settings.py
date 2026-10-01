"""Global settings, resource registry, and resolution precedence."""
from __future__ import annotations

import hashlib
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile

from amix.amix_engine.adapters.media.discovery import discover_tools
from amix.amix_engine.adapters.media.errors import MediaToolMissing
from amix.amix_engine.adapters.vision.resolver import resolve_vision_model
from amix.amix_engine.appstate.bind import bind_app, unbind_app
from amix.amix_engine.appstate.catalog import ManifestEntry, clear_test_catalog, use_test_catalog
from amix.amix_engine.appstate.download import run_download
from amix.amix_engine.appstate.secrets import SecretCache
from amix.amix_engine.appstate.store import open_app
from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.provider import network_mode
from amix.amix_engine.semantic.registry import resolve_provider
from amix.amix_engine.service.app import create_app
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.stt.resolver import resolve_speech_model
from fastapi.testclient import TestClient


class SettingsTests(unittest.TestCase):
    def tearDown(self) -> None:
        unbind_app()
        clear_test_catalog()

    def test_settings_persist_outside_a_project_and_hide_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "app"
            store = open_app(root)
            secrets = SecretCache()
            bind_app(store, secrets)
            try:
                speech = _speech_dir(Path(tmp) / "model")
                saved = store.add_resource(
                    kind="speech",
                    display_name="Small",
                    local_path=str(speech),
                    ownership="registered",
                    origin="import",
                    identity="abc",
                    runtime="faster-whisper",
                )
                store.select_resource(saved.resource_id)
                vision = Path(tmp) / "yunet.onnx"
                vision.write_bytes(b"x" * 1200)
                face = store.add_resource(
                    kind="vision",
                    display_name="YuNet",
                    local_path=str(vision),
                    ownership="registered",
                    origin="import",
                    identity="face",
                    runtime="opencv",
                )
                store.select_resource(face.resource_id)
                provider = store.save_provider(
                    display_name="Desk",
                    placement="local",
                    base_url="http://127.0.0.1:9/v1",
                    model_id="local-model",
                )
                store.set_network_policy("network_enabled")
                store.close()
                again = open_app(root)
                state = again.state()
                self.assertEqual(state.network_policy, "network_enabled")
                self.assertEqual(state.selected_speech_id, saved.resource_id)
                self.assertEqual(state.selected_vision_id, face.resource_id)
                self.assertEqual(state.selected_provider_id, provider.provider_id)
                script = (root / "app.sqlite").read_bytes()
                self.assertNotIn(b"api_key", script.lower())
                self.assertNotIn(b"sk-secret", script)
                with again.engine.connect() as connection:
                    schema = "\n".join(
                        row[0] for row in connection.exec_driver_sql(
                            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
                        )
                    ).lower()
                for forbidden in ("api_key", "password", "secret", "token"):
                    self.assertNotIn(forbidden, schema)
                again.close()
            finally:
                store.close()

    def test_speech_and_vision_selection_without_env_and_invalid_env_does_not_fall_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = open_app(Path(tmp) / "app")
            bind_app(store, SecretCache())
            speech = _speech_dir(Path(tmp) / "model")
            saved = store.add_resource(
                kind="speech",
                display_name="Small",
                local_path=str(speech),
                ownership="registered",
                origin="import",
                identity="abc",
                runtime="faster-whisper",
            )
            store.select_resource(saved.resource_id)
            vision = Path(tmp) / "yunet.onnx"
            vision.write_bytes(b"x" * 1500)
            face = store.add_resource(
                kind="vision",
                display_name="YuNet",
                local_path=str(vision),
                ownership="registered",
                origin="import",
                identity="face",
                runtime="opencv",
            )
            store.select_resource(face.resource_id)
            clean = {key: value for key, value in os.environ.items() if not key.startswith("AMIX_STT_") and not key.startswith("AMIX_YUNET_")}
            with unittest.mock.patch.dict(os.environ, clean, clear=True):
                resolved = resolve_speech_model()
                self.assertEqual(resolved.model_id, saved.resource_id)
                self.assertEqual(resolved.device, "cpu")
                self.assertEqual(resolved.compute_type, "int8")
                seen = resolve_vision_model()
                self.assertEqual(seen.model_id, face.resource_id)
                self.assertEqual(seen.local_path, str(vision))
                os.environ["AMIX_STT_MODEL_PATH"] = str(Path(tmp) / "missing-model")
                from amix.amix_engine.stt.resolver import SpeechResourceError, resolve_speech_model as resolve_speech
                with self.assertRaises(SpeechResourceError):
                    resolve_speech()
            store.close()

    def test_provider_policy_and_secret_stay_out_of_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="settings", app_data=str(Path(tmp) / "app")))
            client = TestClient(create_app(runtime))
            headers = {"Authorization": "Bearer settings"}
            try:
                status = client.get("/v1/runtime/status", headers=headers)
                self.assertEqual(status.status_code, 200, status.text)
                self.assertEqual(status.json()["network_policy"], "offline")
                saved = client.post(
                    "/v1/runtime/providers",
                    headers=headers,
                    json={
                        "display_name": "Loop",
                        "placement": "local",
                        "base_url": "http://127.0.0.1:9/v1",
                        "model_id": "m",
                    },
                )
                self.assertEqual(saved.status_code, 200, saved.text)
                remote = client.post(
                    "/v1/runtime/providers",
                    headers=headers,
                    json={
                        "display_name": "Cloud",
                        "placement": "remote",
                        "base_url": "https://example.test/v1",
                        "model_id": "remote-model",
                    },
                )
                self.assertEqual(remote.status_code, 200, remote.text)
                self.assertTrue(remote.json()["credential_ref"])
                denied = client.post(
                    "/v1/runtime/credentials",
                    headers=headers,
                    json={"credential_ref": remote.json()["credential_ref"], "secret": "sk-test"},
                )
                self.assertEqual(denied.status_code, 404)
                accepted = client.post(
                    "/v1/runtime/credentials",
                    headers={**headers, "X-Amix-Credential-Write": "1"},
                    json={"credential_ref": remote.json()["credential_ref"], "secret": "sk-test"},
                )
                self.assertEqual(accepted.status_code, 200, accepted.text)
                self.assertNotIn("sk-test", accepted.text)
                listed = client.get("/v1/runtime/status", headers=headers)
                self.assertNotIn("sk-test", listed.text)
                blob = (Path(tmp) / "app" / "app.sqlite").read_bytes()
                self.assertNotIn(b"sk-test", blob)
                selected = client.post(
                    f"/v1/runtime/providers/{remote.json()['provider_id']}/select",
                    headers=headers,
                )
                self.assertEqual(selected.status_code, 200, selected.text)
                isolated = {key: value for key, value in os.environ.items() if not key.startswith("AMIX_AI_")}
                with unittest.mock.patch.dict(os.environ, isolated, clear=True):
                    blocked = resolve_provider()
                    self.fail(f"remote provider resolved while offline: {blocked.descriptor.provider_id}")
            except SemanticError as exc:
                self.assertEqual(exc.code, "offline_provider_forbidden")
            finally:
                client.close()
                runtime.shutdown()

    def test_network_enabled_is_explicit_and_invalid_env_does_not_fall_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = open_app(Path(tmp) / "app")
            bind_app(store, SecretCache())
            store.set_network_policy("network_enabled")
            self.assertEqual(network_mode({}, store.state().network_policy), "network_enabled")
            with self.assertRaises(SemanticError):
                network_mode({"AMIX_AI_NETWORK": "cloud"}, "network_enabled")
            self.assertEqual(network_mode({"AMIX_AI_NETWORK": "offline"}, "network_enabled"), "offline")
            store.close()

    def test_ffmpeg_directory_does_not_fall_through_when_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = open_app(Path(tmp) / "app")
            bind_app(store, SecretCache())
            try:
                empty = Path(tmp) / "tools"
                empty.mkdir()
                store.set_ffmpeg_directory(str(empty))
                isolated = {key: value for key, value in os.environ.items() if key not in {"AMIX_FFMPEG", "AMIX_FFPROBE"}}
                with unittest.mock.patch.dict(os.environ, isolated, clear=True):
                    with self.assertRaises(MediaToolMissing):
                        discover_tools()
            finally:
                store.close()

    def test_registered_remove_keeps_files_and_in_use_blocks_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=2, session_token="settings", app_data=str(app)))
            client = TestClient(create_app(runtime))
            headers = {"Authorization": "Bearer settings"}
            try:
                folder = _speech_dir(Path(tmp) / "model")
                imported = client.post(
                    "/v1/runtime/speech/import",
                    headers=headers,
                    json={"path": str(folder), "display_name": "Small"},
                )
                self.assertEqual(imported.status_code, 200, imported.text)
                resource_id = imported.json()["resource_id"]
                project = client.post(
                    "/v1/projects/create",
                    headers=headers,
                    json={"path": str(Path(tmp) / "Project"), "name": "P"},
                )
                self.assertEqual(project.status_code, 200, project.text)
                handle = project.json()["handle"]
                store = runtime.session(handle).store
                asset = store.add_media_asset(
                    display_name="a.mp4",
                    location_kind="external",
                    external_path=str(Path(tmp) / "a.mp4"),
                )
                job = store.create_processing_job(kind="transcribe", media_asset_id=asset)
                self.assertTrue(store.start_processing_job(job.job_id))
                blocked = client.post(f"/v1/runtime/resources/{resource_id}/remove", headers=headers, json={})
                self.assertEqual(blocked.status_code, 409, blocked.text)
                self.assertEqual(blocked.json()["error"]["code"], "resource_in_use")
                store.finish_job_succeeded(job.job_id, {"ok": True})
                removed = client.post(f"/v1/runtime/resources/{resource_id}/remove", headers=headers, json={})
                self.assertEqual(removed.status_code, 200, removed.text)
                self.assertTrue((folder / "model.bin").is_file())
            finally:
                client.close()
                runtime.shutdown()

    def test_download_checksum_cancel_and_no_caller_url(self) -> None:
        payload = b"model-bytes-for-checksum"
        digest = hashlib.sha256(payload).hexdigest()
        server = _server(payload)
        host, port = server.server_address[:2]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            use_test_catalog([
                ManifestEntry(
                    resource_id="vision-test",
                    kind="vision",
                    display_name="Test face",
                    version="1",
                    url=f"http://{host}:{port}/model",
                    sha256=digest,
                    size_bytes=len(payload),
                    license_name="Test",
                    license_url=None,
                    runtime="opencv",
                )
            ])
            with tempfile.TemporaryDirectory() as tmp:
                store = open_app(Path(tmp) / "app")
                bind_app(store, SecretCache())
                store.set_network_policy("network_enabled")
                job_id = store.create_resource_job("install_resource", "vision-test")
                with unittest.mock.patch("amix.amix_engine.appstate.download.vision_file", lambda _path: None):
                    run_download(store, job_id, lambda: False)
                done = store.resource_job(job_id)
                self.assertEqual(done["status"], "SUCCEEDED", done)
                self.assertTrue(store.resources("vision"))
                bad = store.create_resource_job("install_resource", "vision-test")
                use_test_catalog([
                    ManifestEntry(
                        resource_id="vision-test",
                        kind="vision",
                        display_name="Test face",
                        version="1",
                        url=f"http://{host}:{port}/model",
                        sha256="0" * 64,
                        size_bytes=len(payload),
                        license_name=None,
                        license_url=None,
                        runtime="opencv",
                    )
                ])
                before = len(store.resources())
                run_download(store, bad, lambda: False)
                self.assertEqual(store.resource_job(bad)["status"], "FAILED")
                self.assertEqual(len(store.resources()), before)
                cancelled = store.create_resource_job("install_resource", "vision-test")
                run_download(store, cancelled, lambda: True)
                self.assertEqual(store.resource_job(cancelled)["status"], "CANCELLED")
                self.assertFalse((store.root / "models" / ".incoming" / cancelled).exists())
                store.close()
        finally:
            server.shutdown()


def _speech_dir(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "model.bin").write_bytes(b"weights")
    (path / "config.json").write_text("{}", encoding="utf-8")
    return path


def _server(payload: bytes) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = payload
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args) -> None:
            return

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


import unittest.mock  # noqa: E402
