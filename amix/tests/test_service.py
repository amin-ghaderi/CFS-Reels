"""Local engine service. Temporary projects only. No network, video, or models."""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated",
)
from fastapi.testclient import TestClient

from amix.amix_engine.jobs.runner import JobCancelled, JobContext
from amix.amix_engine.service.app import create_app
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.service.__main__ import startup_record
from amix.amix_engine.storage.errors import InvalidJobState
from amix.amix_engine.storage.jobs import INTERRUPT_REASON
from amix.amix_engine.storage.project import DATABASE_NAME, create_project

TOKEN = "phase4-session-token"
REPO = Path(__file__).resolve().parents[2]


class StepHandler:
    def __init__(self) -> None:
        self.ready = threading.Event()
        self.release = threading.Event()

    def run(self, ctx: JobContext) -> dict:
        ctx.report_progress(2000)
        self.ready.set()
        while not self.release.is_set():
            ctx.cancellation.raise_if_cancelled()
            time.sleep(0.01)
        ctx.report_progress(10000)
        return {"done": True}


class FailHandler:
    def run(self, ctx: JobContext) -> dict:
        ctx.report_progress(1000)
        raise RuntimeError("boom")


class GateHandler:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()

    def run(self, ctx: JobContext) -> dict:
        ctx.report_progress(1000)
        self.started.set()
        while not ctx.cancellation.is_cancelled():
            time.sleep(0.01)
        self.stopped.set()
        raise JobCancelled()


class SlowHandler:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, ctx: JobContext) -> dict:
        self.started.set()
        ctx.report_progress(1000)
        while not self.release.is_set():
            time.sleep(0.01)
        ctx.cancellation.raise_if_cancelled()
        return {"late": True}


class ServiceTests(unittest.TestCase):
    def test_non_loopback_host_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ServiceConfig(host="0.0.0.0")

    def test_startup_record_is_one_json_line(self) -> None:
        line = startup_record("127.0.0.1", 43123, TOKEN)
        self.assertTrue(line.endswith("\n"))
        payload = json.loads(line)
        self.assertEqual(payload["event"], "amix.engine.ready")
        self.assertEqual(payload["host"], "127.0.0.1")
        self.assertEqual(payload["port"], 43123)
        self.assertEqual(payload["token"], TOKEN)

    def test_process_binds_loopback_and_prints_startup_first(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "launch.py"
            script.write_text(
                "import sys\n"
                f"sys.path.insert(0, {str(REPO)!r})\n"
                "from amix.amix_engine.service.__main__ import run\n"
                "from amix.amix_engine.service.config import ServiceConfig\n"
                f"run(ServiceConfig(port=0, session_token={TOKEN!r}, log_level='ERROR'))\n",
                encoding="utf-8",
            )
            process = subprocess.Popen(
                [sys.executable, str(script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            line_holder: list[str] = []

            def _read_startup() -> None:
                if process.stdout is not None:
                    line_holder.append(process.stdout.readline())

            reader = threading.Thread(target=_read_startup, daemon=True)
            reader.start()
            try:
                reader.join(5)
                if reader.is_alive():
                    raise AssertionError("startup record was not printed")
                line = line_holder[0]
                payload = json.loads(line)
                self.assertEqual(payload["host"], "127.0.0.1")
                self.assertNotEqual(payload["port"], 0)
                self.assertEqual(payload["token"], TOKEN)
                import urllib.request
                health = urllib.request.urlopen(
                    f"http://127.0.0.1:{payload['port']}/v1/health",
                    timeout=2,
                )
                body = json.loads(health.read().decode("utf-8"))
                self.assertEqual(body["status"], "ok")
                self.assertNotIn("token", body)
                self.assertNotIn(TOKEN, json.dumps(body))
            finally:
                process.kill()
                process.wait(timeout=5)
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()

    def test_auth_health_and_token_are_not_echoed(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            runtime, client = _client(tmp)
            records: list[str] = []

            class Capture(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    records.append(record.getMessage())

            handler = Capture()
            logger = logging.getLogger("amix.engine")
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            try:
                health = client.get("/v1/health")
                self.assertEqual(health.status_code, 200)
                self.assertNotIn(TOKEN, health.text)
                self.assertNotIn("token", health.json())
                missing = client.post("/v1/projects/create", json={"path": str(Path(tmp) / "A"), "name": "A"})
                self.assertEqual(missing.status_code, 401)
                self.assertEqual(missing.json()["error"]["code"], "unauthorized")
                wrong = client.post(
                    "/v1/projects/create",
                    headers={"Authorization": "Bearer nope"},
                    json={"path": str(Path(tmp) / "A"), "name": "A"},
                )
                self.assertEqual(wrong.status_code, 401)
                created = client.post(
                    "/v1/projects/create",
                    headers=_headers(),
                    json={"path": str(Path(tmp) / "A"), "name": "A"},
                )
                self.assertEqual(created.status_code, 200, created.text)
                self.assertNotIn(TOKEN, created.text)
                self.assertNotIn(TOKEN, "\n".join(records))
                self.assertNotIn("Bearer", "\n".join(records))
                self.assertNotIn("authorization", "\n".join(records).lower())
            finally:
                logger.removeHandler(handler)
                client.close()
                runtime.shutdown()

    def test_project_create_close_reopen_and_lock(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Proj"
            runtime, client = _client(tmp)
            try:
                created = client.post(
                    "/v1/projects/create",
                    headers=_headers(),
                    json={"path": str(root), "name": "Proj"},
                )
                self.assertEqual(created.status_code, 200, created.text)
                body = created.json()
                self.assertNotEqual(body["handle"], body["project_id"])
                self.assertNotIn(str(root), created.text)
                self.assertEqual(_probe(root, "write"), 2)
                again = client.post(
                    "/v1/projects/create",
                    headers=_headers(),
                    json={"path": str(root), "name": "Proj"},
                )
                self.assertEqual(again.status_code, 409)
                self.assertEqual(again.json()["error"]["code"], "project_already_open")
                self.assertEqual(client.get(f"/v1/projects/{body['handle']}", headers=_headers()).status_code, 200)
                closed = client.post(f"/v1/projects/{body['handle']}/close", headers=_headers())
                self.assertEqual(closed.status_code, 200)
                self.assertEqual(_probe(root, "write"), 0)
                opened = client.post(
                    "/v1/projects/open",
                    headers=_headers(),
                    json={"path": str(root)},
                )
                self.assertEqual(opened.status_code, 200, opened.text)
                self.assertEqual(opened.json()["project_id"], body["project_id"])
                self.assertNotEqual(opened.json()["handle"], body["handle"])
            finally:
                client.close()
                runtime.shutdown()

    def test_two_projects_are_independent(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            runtime, client = _client(tmp, extra={"test_step": StepHandler()})
            try:
                first = _create(client, Path(tmp) / "One", "One")
                second = _create(client, Path(tmp) / "Two", "Two")
                self.assertNotEqual(first["handle"], second["handle"])
                self.assertNotEqual(first["project_id"], second["project_id"])
                job = client.post(
                    f"/v1/projects/{first['handle']}/jobs",
                    headers=_headers(),
                    json={"kind": "project_integrity_check"},
                )
                self.assertEqual(job.status_code, 200, job.text)
                _wait(client, first["handle"], job.json()["job_id"], {"SUCCEEDED"})
                other = client.get(f"/v1/projects/{second['handle']}/jobs", headers=_headers())
                self.assertEqual(other.json(), [])
                client.post(f"/v1/projects/{first['handle']}/close", headers=_headers())
                self.assertEqual(_probe(Path(tmp) / "One", "write"), 0)
                self.assertEqual(_probe(Path(tmp) / "Two", "write"), 2)
                still = client.get(f"/v1/projects/{second['handle']}", headers=_headers())
                self.assertEqual(still.status_code, 200)
            finally:
                client.close()
                runtime.shutdown()

    def test_integrity_job_succeeds_with_integer_progress(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Check"
            runtime, client = _client(tmp)
            try:
                created = _create(client, root, "Check")
                client.post(f"/v1/projects/{created['handle']}/close", headers=_headers())
                store = __import__(
                    "amix.amix_engine.storage.project",
                    fromlist=["open_project"],
                ).open_project(root)
                try:
                    store.add_media_asset(
                        display_name="missing",
                        location_kind="external",
                        external_path=str(Path(tmp) / "nope.bin"),
                    )
                    self.assertEqual(store.count_analysis_runs(), 0)
                finally:
                    store.close()
                opened = client.post(
                    "/v1/projects/open",
                    headers=_headers(),
                    json={"path": str(root)},
                ).json()
                response = client.post(
                    f"/v1/projects/{opened['handle']}/jobs",
                    headers=_headers(),
                    json={"kind": "project_integrity_check", "spec": {"note": "local"}},
                )
                self.assertEqual(response.status_code, 200, response.text)
                job = _wait(client, opened["handle"], response.json()["job_id"], {"SUCCEEDED"})
                self.assertEqual(job["progress_bp"], 10000)
                self.assertEqual(job["attempt"], 1)
                self.assertEqual(job["result"]["analysis_run_count"], 0)
                self.assertEqual(job["result"]["assets"][0]["status"], "missing")
                self.assertEqual(job["result"]["problems"], [])
                unknown = client.post(
                    f"/v1/projects/{opened['handle']}/jobs",
                    headers=_headers(),
                    json={"kind": "os.system"},
                )
                self.assertEqual(unknown.status_code, 400)
                self.assertEqual(unknown.json()["error"]["code"], "unsupported_job_kind")
                secret = client.post(
                    f"/v1/projects/{opened['handle']}/jobs",
                    headers=_headers(),
                    json={"kind": "project_integrity_check", "spec": {"token": "nope"}},
                )
                self.assertEqual(secret.status_code, 400)
                self.assertEqual(secret.json()["error"]["code"], "job_spec_rejected")
                connection = sqlite3.connect(root / DATABASE_NAME)
                try:
                    kind = connection.execute("SELECT typeof(progress_bp) FROM processing_job").fetchone()[0]
                finally:
                    connection.close()
                self.assertEqual(kind, "integer")
            finally:
                client.close()
                runtime.shutdown()

    def test_progress_is_monotonic_and_failure_is_structured(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            step = StepHandler()
            runtime, client = _client(tmp, extra={"test_step": step, "test_fail": FailHandler()})
            try:
                created = _create(client, Path(tmp) / "Jobs", "Jobs")
                handle = created["handle"]
                started = client.post(
                    f"/v1/projects/{handle}/jobs",
                    headers=_headers(),
                    json={"kind": "test_step"},
                ).json()
                seen = _wait_progress(client, handle, started["job_id"], 2000)
                self.assertGreaterEqual(seen, 2000)
                step.release.set()
                done = _wait(client, handle, started["job_id"], {"SUCCEEDED"})
                self.assertEqual(done["progress_bp"], 10000)
                self.assertGreaterEqual(done["progress_bp"], seen)
                failed = client.post(
                    f"/v1/projects/{handle}/jobs",
                    headers=_headers(),
                    json={"kind": "test_fail"},
                ).json()
                body = _wait(client, handle, failed["job_id"], {"FAILED"})
                self.assertEqual(body["error_code"], "handler_failed")
                self.assertEqual(body["error_message"], "boom")
                self.assertNotIn("Traceback", body["error_message"])
            finally:
                client.close()
                runtime.shutdown()

    def test_progress_cannot_decrease(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store = create_project(Path(tmp) / "Prog", "Prog")
            try:
                job = store.create_processing_job(kind="project_integrity_check")
                self.assertTrue(store.start_processing_job(job.job_id))
                store.set_job_progress(job.job_id, 5000)
                with self.assertRaises(InvalidJobState):
                    store.set_job_progress(job.job_id, 1000)
                self.assertEqual(store.get_processing_job(job.job_id).progress_bp, 5000)
                finished = store.finish_job_succeeded(job.job_id, {"ok": True})
                self.assertEqual(finished.progress_bp, 10000)
                self.assertEqual(finished.status, "SUCCEEDED")
                self.assertFalse(store.start_processing_job(job.job_id))
                self.assertEqual(store.get_processing_job(job.job_id).status, "SUCCEEDED")
            finally:
                store.close()

    def test_cancel_is_cooperative(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            gate = GateHandler()
            runtime, client = _client(tmp, extra={"test_gate": gate})
            try:
                created = _create(client, Path(tmp) / "Cancel", "Cancel")
                handle = created["handle"]
                queued = client.post(
                    f"/v1/projects/{handle}/jobs",
                    headers=_headers(),
                    json={"kind": "test_gate"},
                )
                job_id = queued.json()["job_id"]
                self.assertTrue(gate.started.wait(2))
                _wait(client, handle, job_id, {"RUNNING"})
                cancelled = client.post(f"/v1/projects/{handle}/jobs/{job_id}/cancel", headers=_headers())
                self.assertEqual(cancelled.status_code, 200, cancelled.text)
                body = _wait(client, handle, job_id, {"CANCELLED"})
                self.assertTrue(body["cancel_requested"])
                self.assertTrue(gate.stopped.wait(2))
                self.assertNotEqual(body["status"], "SUCCEEDED")
            finally:
                client.close()
                runtime.shutdown()

    def test_retry_creates_a_new_history_row(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            runtime, client = _client(tmp, extra={"test_fail": FailHandler()})
            try:
                created = _create(client, Path(tmp) / "Retry", "Retry")
                handle = created["handle"]
                first = client.post(
                    f"/v1/projects/{handle}/jobs",
                    headers=_headers(),
                    json={"kind": "test_fail", "spec": {"attempt_note": "one"}},
                ).json()
                failed = _wait(client, handle, first["job_id"], {"FAILED"})
                retried = client.post(
                    f"/v1/projects/{handle}/jobs/{first['job_id']}/retry",
                    headers=_headers(),
                )
                self.assertEqual(retried.status_code, 200, retried.text)
                second = retried.json()
                self.assertNotEqual(second["job_id"], first["job_id"])
                self.assertEqual(second["resumed_from_job_id"], first["job_id"])
                self.assertEqual(second["attempt"], 2)
                self.assertEqual(failed["attempt"], 1)
                _wait(client, handle, second["job_id"], {"FAILED"})
                old = client.get(
                    f"/v1/projects/{handle}/jobs/{first['job_id']}",
                    headers=_headers(),
                ).json()
                self.assertEqual(old["status"], "FAILED")
                self.assertEqual(old["attempt"], 1)
                self.assertEqual(old["error_message"], "boom")
                self.assertIsNone(old["resumed_from_job_id"])
            finally:
                client.close()
                runtime.shutdown()

    def test_stale_jobs_become_interrupted_on_writable_open(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Recover"
            store = create_project(root, "Recover")
            try:
                queued = store.create_processing_job(kind="project_integrity_check", spec={"slot": "queued"})
                running = store.create_processing_job(kind="project_integrity_check", spec={"slot": "running"})
                store.start_processing_job(running.job_id)
                requested = store.create_processing_job(kind="project_integrity_check", spec={"slot": "cancel"})
                store.start_processing_job(requested.job_id)
                store.request_job_cancel(requested.job_id)
                done = store.create_processing_job(kind="project_integrity_check", spec={"slot": "done"})
                store.start_processing_job(done.job_id)
                store.finish_job_succeeded(done.job_id, {"kept": True})
            finally:
                store.close()
            runtime, client = _client(tmp)
            try:
                opened = client.post(
                    "/v1/projects/open",
                    headers=_headers(),
                    json={"path": str(root)},
                )
                self.assertEqual(opened.status_code, 200, opened.text)
                jobs = {
                    item["spec"]["slot"]: item
                    for item in client.get(
                        f"/v1/projects/{opened.json()['handle']}/jobs",
                        headers=_headers(),
                    ).json()
                }
                for slot in ("queued", "running", "cancel"):
                    self.assertEqual(jobs[slot]["status"], "INTERRUPTED", slot)
                    self.assertEqual(jobs[slot]["interrupt_reason"], INTERRUPT_REASON)
                self.assertEqual(jobs["done"]["status"], "SUCCEEDED")
                self.assertEqual(jobs["done"]["result"], {"kept": True})
                self.assertEqual(jobs["queued"]["job_id"], queued.job_id)
            finally:
                client.close()
                runtime.shutdown()

    def test_close_waits_for_cancellation_before_releasing_the_lock(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Close"
            gate = GateHandler()
            runtime, client = _client(tmp, extra={"test_gate": gate})
            try:
                created = _create(client, root, "Close")
                response = client.post(
                    f"/v1/projects/{created['handle']}/jobs",
                    headers=_headers(),
                    json={"kind": "test_gate"},
                )
                self.assertTrue(gate.started.wait(2))
                self.assertEqual(_probe(root, "write"), 2)
                closed = client.post(f"/v1/projects/{created['handle']}/close", headers=_headers())
                self.assertEqual(closed.status_code, 200, closed.text)
                self.assertTrue(gate.stopped.wait(2))
                self.assertEqual(_probe(root, "write"), 0)
                reopened = client.post(
                    "/v1/projects/open",
                    headers=_headers(),
                    json={"path": str(root)},
                )
                self.assertEqual(reopened.status_code, 200, reopened.text)
            finally:
                client.close()
                runtime.shutdown()

    def test_close_timeout_keeps_the_lock(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Busy"
            slow = SlowHandler()
            runtime, client = _client(tmp, extra={"test_slow": slow}, timeout_s=0.05)
            try:
                created = _create(client, root, "Busy")
                client.post(
                    f"/v1/projects/{created['handle']}/jobs",
                    headers=_headers(),
                    json={"kind": "test_slow"},
                )
                self.assertTrue(slow.started.wait(2))
                closed = client.post(f"/v1/projects/{created['handle']}/close", headers=_headers())
                self.assertEqual(closed.status_code, 409)
                self.assertEqual(closed.json()["error"]["code"], "project_close_timeout")
                self.assertEqual(_probe(root, "write"), 2)
                slow.release.set()
                self.assertEqual(
                    client.post(f"/v1/projects/{created['handle']}/close", headers=_headers()).status_code,
                    200,
                )
                self.assertEqual(_probe(root, "write"), 0)
            finally:
                slow.release.set()
                client.close()
                runtime.shutdown()

    def test_read_only_open_does_not_migrate_or_start_jobs(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Read"
            runtime, client = _client(tmp)
            try:
                created = _create(client, root, "Read")
                client.post(f"/v1/projects/{created['handle']}/close", headers=_headers())
                connection = sqlite3.connect(root / DATABASE_NAME)
                connection.execute("UPDATE alembic_version SET version_num = '9999_future'")
                connection.commit()
                connection.close()
                refused = client.post(
                    "/v1/projects/open",
                    headers=_headers(),
                    json={"path": str(root), "read_only": True},
                )
                self.assertEqual(refused.status_code, 409)
                self.assertEqual(refused.json()["error"]["code"], "schema_mismatch")
                connection = sqlite3.connect(root / DATABASE_NAME)
                self.assertEqual(
                    connection.execute("SELECT version_num FROM alembic_version").fetchone()[0],
                    "9999_future",
                )
                connection.execute("UPDATE alembic_version SET version_num = '0009_producing_job'")
                connection.commit()
                connection.close()
                reader = client.post(
                    "/v1/projects/open",
                    headers=_headers(),
                    json={"path": str(root), "read_only": True},
                )
                self.assertEqual(reader.status_code, 200, reader.text)
                denied = client.post(
                    f"/v1/projects/{reader.json()['handle']}/jobs",
                    headers=_headers(),
                    json={"kind": "project_integrity_check"},
                )
                self.assertEqual(denied.status_code, 409)
                self.assertEqual(denied.json()["error"]["code"], "project_read_only")
            finally:
                client.close()
                runtime.shutdown()

    def test_openapi_lists_the_service_routes(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            runtime, client = _client(tmp)
            try:
                document = client.get("/openapi.json")
                self.assertEqual(document.status_code, 200)
                paths = document.json()["paths"]
                for path in (
                    "/v1/health",
                    "/v1/projects/create",
                    "/v1/projects/open",
                    "/v1/projects/{handle}",
                    "/v1/projects/{handle}/close",
                    "/v1/projects/{handle}/jobs",
                    "/v1/projects/{handle}/jobs/{job_id}",
                    "/v1/projects/{handle}/jobs/{job_id}/cancel",
                    "/v1/projects/{handle}/jobs/{job_id}/retry",
                ):
                    self.assertIn(path, paths)
                self.assertNotIn(TOKEN, document.text)
            finally:
                client.close()
                runtime.shutdown()

    def test_shutdown_releases_project_locks(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Down"
            runtime, client = _client(tmp)
            created = _create(client, root, "Down")
            self.assertEqual(_probe(root, "write"), 2)
            client.close()
            runtime.shutdown()
            self.assertEqual(_probe(root, "write"), 0)
            self.assertTrue(created["project_id"])


def _client(tmp: str, extra: dict | None = None, timeout_s: float = 2.0):
    config = ServiceConfig(shutdown_timeout_s=timeout_s, session_token=TOKEN, log_level="INFO")
    runtime = EngineRuntime(config, token=TOKEN, extra_handlers=extra)
    return runtime, TestClient(create_app(runtime))


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _create(client: TestClient, path: Path, name: str) -> dict:
    response = client.post(
        "/v1/projects/create",
        headers=_headers(),
        json={"path": str(path), "name": name},
    )
    if response.status_code != 200:
        raise AssertionError(response.text)
    return response.json()


def _wait(client: TestClient, handle: str, job_id: str, wanted: set[str]) -> dict:
    deadline = time.monotonic() + 2
    last = None
    while time.monotonic() < deadline:
        response = client.get(f"/v1/projects/{handle}/jobs/{job_id}", headers=_headers())
        last = response.json()
        if last.get("status") in wanted:
            return last
        time.sleep(0.01)
    raise AssertionError(last)


def _wait_progress(client: TestClient, handle: str, job_id: str, minimum: int) -> int:
    deadline = time.monotonic() + 2
    last = None
    while time.monotonic() < deadline:
        last = client.get(f"/v1/projects/{handle}/jobs/{job_id}", headers=_headers()).json()
        if last["progress_bp"] >= minimum:
            return last["progress_bp"]
        time.sleep(0.01)
    raise AssertionError(last)


def _probe(root: Path, mode: str) -> int:
    script = root.parent / f"_probe_{root.name}.py"
    script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from amix.amix_engine.storage.errors import ProjectAlreadyLocked\n"
        "from amix.amix_engine.storage.project import open_project\n"
        "try:\n"
        "    store = open_project(Path(sys.argv[3]), read_only=sys.argv[2] == 'read')\n"
        "except ProjectAlreadyLocked:\n"
        "    raise SystemExit(2)\n"
        "store.close()\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(script), str(REPO), mode, str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in (0, 2):
        raise AssertionError(completed.stderr or completed.stdout)
    return completed.returncode


if __name__ == "__main__":
    unittest.main()
