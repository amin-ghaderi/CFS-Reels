"""Recent projects and project-lock recovery."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import textwrap
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from amix.amix_engine.appstate.store import open_app
from amix.amix_engine.service.app import create_app
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.storage.project import DATABASE_NAME, create_project, open_project, private_directory

REPO = Path(__file__).resolve().parents[2]
TOKEN = "startup-session"


def _client(app_root: Path):
    config = ServiceConfig(
        shutdown_timeout_s=5,
        session_token=TOKEN,
        app_data=str(app_root),
        worker_count=1,
    )
    runtime = EngineRuntime(config, token=TOKEN)
    return runtime, TestClient(create_app(runtime))


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _create(client: TestClient, path: Path, name: str) -> dict:
    response = client.post("/v1/projects/create", headers=_headers(), json={"path": str(path), "name": name})
    if response.status_code != 200:
        raise AssertionError(response.text)
    return response.json()


def _open(client: TestClient, path: Path) -> dict:
    response = client.post("/v1/projects/open", headers=_headers(), json={"path": str(path), "read_only": False})
    if response.status_code != 200:
        raise AssertionError(response.text)
    return response.json()


def _close(client: TestClient, handle: str) -> None:
    response = client.post(f"/v1/projects/{handle}/close", headers=_headers())
    if response.status_code != 200:
        raise AssertionError(response.text)


def _recent(client: TestClient) -> list[dict]:
    response = client.get("/v1/runtime/recent-projects", headers=_headers())
    if response.status_code != 200:
        raise AssertionError(response.text)
    return response.json()["projects"]


def _probe(root: Path) -> int:
    script = root / "_probe.py"
    script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from amix.amix_engine.storage.errors import ProjectAlreadyLocked\n"
        "from amix.amix_engine.storage.project import open_project\n"
        "try:\n"
        "    store = open_project(Path(sys.argv[2]))\n"
        "except ProjectAlreadyLocked:\n"
        "    raise SystemExit(2)\n"
        "store.close()\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(script), str(REPO), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in (0, 2):
        raise AssertionError(completed.stderr or completed.stdout)
    return completed.returncode


class RecentProjectTests(unittest.TestCase):
    def test_create_and_open_update_recent_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, client = _client(root / "app")
            try:
                first = _create(client, root / "One", "One")
                _close(client, first["handle"])
                second = _create(client, root / "Two", "Two")
                _close(client, second["handle"])
                listed = _recent(client)
                self.assertEqual([item["display_name"] for item in listed], ["Two", "One"])
                opened = _open(client, root / "One")
                self.assertEqual(opened["project_id"], first["project_id"])
                _close(client, opened["handle"])
                again = _recent(client)
                self.assertEqual([item["project_id"] for item in again], [first["project_id"], second["project_id"]])
                self.assertGreater(again[0]["last_opened_at"], again[1]["last_opened_at"])
            finally:
                client.close()
                runtime.shutdown()

    def test_recent_order_is_deterministic_for_equal_times(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = open_app(Path(tmp) / "app")
            try:
                moment = "2026-01-01T00:00:00+00:00"
                app.remember_project("b-project", "B", str(Path(tmp) / "B"), opened_at=moment)
                app.remember_project("a-project", "A", str(Path(tmp) / "A"), opened_at=moment)
                self.assertEqual([item.project_id for item in app.recent_projects()], ["a-project", "b-project"])
            finally:
                app.close()

    def test_missing_project_stays_listed_until_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "Show"
            store = create_project(show, "Show")
            project_id = store.project_id
            database = private_directory(show) / DATABASE_NAME
            store.close()
            app = open_app(root / "app")
            try:
                app.remember_project(project_id, "Show", str(show), opened_at="2026-02-01T00:00:00+00:00")
                show.rename(root / "moved-aside")
                listed = app.recent_projects()
                self.assertEqual(listed[0].availability, "missing")
                self.assertEqual(listed[0].thumbnail, "none")
                app.remove_recent(project_id)
                self.assertEqual(app.recent_projects(), [])
                self.assertTrue((root / "moved-aside" / ".amix" / DATABASE_NAME).is_file() or database.is_file())
            finally:
                app.close()

    def test_locate_updates_the_same_project_and_rejects_a_different_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "Original"
            store = create_project(original, "Original")
            project_id = store.project_id
            store.close()
            other = create_project(root / "Other", "Other")
            other_id = other.project_id
            other.close()
            moved = root / "Moved"
            original.rename(moved)
            app = open_app(root / "app")
            try:
                app.remember_project(project_id, "Original", str(original), opened_at="2026-03-01T00:00:00+00:00")
                located = app.locate_recent(project_id, str(moved))
                self.assertEqual(located.project_id, project_id)
                self.assertEqual(Path(located.root_path), moved.resolve())
                self.assertEqual(located.availability, "available")
                with self.assertRaises(Exception) as raised:
                    app.locate_recent(project_id, str(root / "Other"))
                self.assertEqual(raised.exception.code, "recent_project_mismatch")
                self.assertNotEqual(other_id, project_id)
                opened = open_project(moved)
                try:
                    self.assertEqual(opened.project_id, project_id)
                finally:
                    opened.close()
            finally:
                app.close()

    def test_new_and_previous_layouts_open_from_recent_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            modern = root / "Modern"
            store = create_project(modern, "Modern")
            modern_id = store.project_id
            store.close()
            previous = root / "Previous"
            store = create_project(previous, "Previous")
            previous_id = store.project_id
            store.close()
            private = previous / ".amix"
            (previous / DATABASE_NAME).write_bytes((private / DATABASE_NAME).read_bytes())
            (private / DATABASE_NAME).unlink()
            (previous / "manifest.json").write_text((private / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
            app = open_app(root / "app")
            try:
                app.remember_project(modern_id, "Modern", str(modern))
                app.remember_project(previous_id, "Previous", str(previous))
                for path, expected in ((modern, modern_id), (previous, previous_id)):
                    opened = open_project(path)
                    try:
                        self.assertEqual(opened.project_id, expected)
                    finally:
                        opened.close()
            finally:
                app.close()

    def test_http_remove_does_not_delete_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, client = _client(root / "app")
            try:
                created = _create(client, root / "Show", "Show")
                _close(client, created["handle"])
                removed = client.post(
                    f"/v1/runtime/recent-projects/{created['project_id']}/remove",
                    headers=_headers(),
                )
                self.assertEqual(removed.status_code, 200, removed.text)
                self.assertEqual(_recent(client), [])
                self.assertTrue((root / "Show" / ".amix" / DATABASE_NAME).is_file())
            finally:
                client.close()
                runtime.shutdown()


class LockRecoveryTests(unittest.TestCase):
    def test_live_os_lock_blocks_a_second_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Held"
            holder = create_project(root, "Held")
            try:
                self.assertEqual(_probe(root), 2)
            finally:
                holder.close()
            self.assertEqual(_probe(root), 0)

    def test_stale_note_with_a_live_pid_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Noted"
            store = create_project(root, "Noted")
            store.close()
            note = private_directory(root) / "project.lock.json"
            note.write_text(
                json.dumps({"pid": os.getpid(), "hostname": "not-the-owner", "opened_at": "2000-01-01T00:00:00+00:00"}),
                encoding="utf-8",
            )
            self.assertEqual(_probe(root), 0)

    def test_crash_leaves_the_note_and_the_next_open_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Crashed"
            store = create_project(root, "Crashed")
            store.close()
            script = Path(tmp) / "crash.py"
            script.write_text(
                textwrap.dedent(
                    """\
                    import os
                    import sys
                    from pathlib import Path
                    sys.path.insert(0, sys.argv[1])
                    from amix.amix_engine.storage.project import open_project
                    open_project(Path(sys.argv[2]))
                    os._exit(9)
                    """
                ),
                encoding="utf-8",
            )
            completed = subprocess.run([sys.executable, str(script), str(REPO), str(root)], check=False)
            self.assertEqual(completed.returncode, 9)
            note = private_directory(root) / "project.lock.json"
            self.assertTrue(note.is_file())
            opened = open_project(root)
            try:
                self.assertEqual(opened.project_name, "Crashed")
            finally:
                opened.close()

    def test_second_instance_opens_after_the_holder_closes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Shared"
            store = create_project(root, "Shared")
            store.close()
            ready = Path(tmp) / "ready"
            release = Path(tmp) / "release"
            done = Path(tmp) / "done"
            script = Path(tmp) / "hold.py"
            script.write_text(
                textwrap.dedent(
                    """\
                    import sys
                    import time
                    from pathlib import Path
                    sys.path.insert(0, sys.argv[1])
                    from amix.amix_engine.storage.project import open_project
                    root = Path(sys.argv[2])
                    ready = Path(sys.argv[3])
                    release = Path(sys.argv[4])
                    done = Path(sys.argv[5])
                    store = open_project(root)
                    ready.write_text("held", encoding="utf-8")
                    deadline = time.time() + 15
                    while not release.exists() and time.time() < deadline:
                        time.sleep(0.05)
                    store.close()
                    done.write_text("closed", encoding="utf-8")
                    """
                ),
                encoding="utf-8",
            )
            holder = subprocess.Popen([sys.executable, str(script), str(REPO), str(root), str(ready), str(release), str(done)])
            try:
                deadline = time.time() + 15
                while not ready.exists():
                    if time.time() > deadline:
                        raise AssertionError("holder did not acquire the lock")
                    time.sleep(0.05)
                self.assertEqual(_probe(root), 2)
                release.write_text("go", encoding="utf-8")
                self.assertEqual(holder.wait(timeout=15), 0)
                self.assertTrue(done.is_file())
                self.assertEqual(_probe(root), 0)
            finally:
                if holder.poll() is None:
                    holder.kill()
                    holder.wait(timeout=5)

    def test_engine_exits_when_the_owner_process_exits(self) -> None:
        owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        env = os.environ.copy()
        env["AMIX_OWNER_PID"] = str(owner.pid)
        env["PYTHONPATH"] = str(REPO)
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from amix.amix_engine.service.owner import exit_when_owner_exits; import time; exit_when_owner_exits(); time.sleep(30)",
            ],
            env=env,
        )
        try:
            time.sleep(0.4)
            self.assertIsNone(child.poll())
            owner.kill()
            owner.wait(timeout=5)
            self.assertEqual(child.wait(timeout=5), 0)
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=5)
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
