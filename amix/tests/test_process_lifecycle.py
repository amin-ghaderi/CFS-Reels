"""Owned-process registration and atomic pid publication.

These tests synchronize on lifecycle hooks. They do not treat a short sleep
as proof that a child is ready.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from amix.amix_engine.adapters.media.discovery import MediaTools
from amix.amix_engine.adapters.media.errors import ProcessCancelled
from amix.amix_engine.adapters.media.process import (
    owned_pids,
    run_process,
    set_lifecycle_hook,
    terminate_owned_processes,
)
from amix.amix_engine.adapters.media.publish import publish_pid, read_pid
from amix.amix_engine.jobs.media import GENERATE_PROXY
from amix.amix_engine.jobs.runner import CancellationToken
from amix.amix_engine.service.config import ServiceConfig
from amix.amix_engine.service.runtime import EngineRuntime
from amix.amix_engine.storage.project import MediaProbeRecord, open_project

_SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]
_STRESS_CYCLES = 50


def _alive(pid: int) -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _record() -> MediaProbeRecord:
    return MediaProbeRecord(
        container="mp4",
        duration_us=1_000_000,
        duration_source="video",
        container_start_us=0,
        bit_rate=800000,
        video_codec="h264",
        width=320,
        height=240,
        pixel_format="yuv420p",
        fps_num=25,
        fps_den=1,
        r_fps_num=25,
        r_fps_den=1,
        time_base_num=1,
        time_base_den=12800,
        video_start_us=0,
        video_duration_us=1_000_000,
        rotation_degrees=0,
        audio_codec="aac",
        sample_rate=48000,
        audio_channels=2,
        channel_layout="stereo",
        audio_start_us=0,
        audio_duration_us=1_000_000,
        byte_size=4,
        file_mtime_ns=1,
        probe_tool="ffprobe version test",
        probe_config="amix.probe.v1",
    )


class PublicationTests(unittest.TestCase):
    def test_pid_marker_never_exposes_empty_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "worker.pid"
            path.write_text("", encoding="utf-8")
            self.assertIsNone(read_pid(path))
            path.write_text(" \n", encoding="utf-8")
            self.assertIsNone(read_pid(path))
            path.unlink()
            bad: list[str] = []
            stop = threading.Event()

            def reader() -> None:
                while not stop.is_set():
                    try:
                        text = path.read_text(encoding="utf-8")
                    except (FileNotFoundError, PermissionError):
                        continue
                    if not text.strip().isdigit():
                        bad.append(text)
                    time.sleep(0.001)

            threads = [threading.Thread(target=reader) for _ in range(2)]
            for thread in threads:
                thread.start()
            try:
                for value in range(10000, 10080):
                    publish_pid(path, value)
            finally:
                stop.set()
                for thread in threads:
                    thread.join()
            self.assertEqual(bad, [])
            self.assertEqual(read_pid(path), 10079)


class SpawnTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_lifecycle_hook(None)
        terminate_owned_processes(2)

    def test_cancel_during_spawn_kills_the_registered_child(self) -> None:
        token = CancellationToken()
        seen: list[int] = []

        def hook(stage: str) -> None:
            if stage != "after_register":
                return
            pids = owned_pids()
            seen.extend(pids)
            if not pids or not _alive(pids[0]):
                raise AssertionError("child was not registered while it was alive")
            token.request()

        set_lifecycle_hook(hook)
        with self.assertRaises(ProcessCancelled):
            run_process(_SLEEP, token)
        self.assertTrue(seen)
        self.assertFalse(_alive(seen[0]))
        self.assertEqual(owned_pids(), [])
        terminate_owned_processes(1)
        terminate_owned_processes(1)

    def test_cancel_before_spawn_does_not_create_a_child(self) -> None:
        token = CancellationToken()
        token.request()
        with self.assertRaises(ProcessCancelled):
            run_process(_SLEEP, token)
        self.assertEqual(owned_pids(), [])

    def test_shutdown_during_spawn_kills_the_child_and_releases_the_lock(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        waiting = threading.Event()
        recorded: list[int] = []

        def hook(stage: str) -> None:
            if stage == "after_register":
                recorded.extend(owned_pids())
                entered.set()
                release.wait(5)
            elif stage == "shutdown_waiting":
                waiting.set()

        set_lifecycle_hook(hook)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Stop"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=5, session_token="phase16-1"))
            try:
                session = runtime.create_project(root, "Stop")
                source = root / "clip.bin"
                source.write_bytes(b"clip")
                asset_id = session.store.add_media_asset(
                    display_name="clip.bin",
                    location_kind="external",
                    external_path=str(source),
                    byte_size=4,
                )
                session.store.apply_probe(asset_id, _record())
                tools = MediaTools(Path("ffmpeg"), Path("ffprobe"), "ffmpeg test", "ffprobe test")
                errors: list[BaseException] = []

                def stop() -> None:
                    try:
                        runtime.shutdown()
                    except BaseException as exc:
                        errors.append(exc)

                with patch("amix.amix_engine.jobs.media.discover_tools", return_value=tools), patch(
                    "amix.amix_engine.jobs.media.proxy_command",
                    return_value=_SLEEP,
                ):
                    runtime.jobs.submit(session.store, GENERATE_PROXY, {"profile": "amix.proxy.v1"}, asset_id)
                    self.assertTrue(entered.wait(5))
                    self.assertTrue(recorded)
                    self.assertTrue(_alive(recorded[0]))
                    thread = threading.Thread(target=stop)
                    thread.start()
                    self.assertTrue(waiting.wait(5))
                    release.set()
                    thread.join(5)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(errors, [])
                self.assertFalse(_alive(recorded[0]))
                self.assertEqual(owned_pids(), [])
                reopened = open_project(root)
                try:
                    self.assertEqual(reopened.list_processing_jobs()[0].status, "CANCELLED")
                finally:
                    reopened.close()
            finally:
                release.set()
                set_lifecycle_hook(None)
                runtime.shutdown()

    def test_concurrent_cancel_and_shutdown_are_idempotent(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        waiting = threading.Event()
        recorded: list[int] = []

        def hook(stage: str) -> None:
            if stage == "after_register":
                recorded.extend(owned_pids())
                entered.set()
                release.wait(5)
            elif stage == "shutdown_waiting":
                waiting.set()

        set_lifecycle_hook(hook)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Both"
            runtime = EngineRuntime(ServiceConfig(shutdown_timeout_s=5, session_token="phase16-1"))
            try:
                session = runtime.create_project(root, "Both")
                source = root / "clip.bin"
                source.write_bytes(b"clip")
                asset_id = session.store.add_media_asset(
                    display_name="clip.bin",
                    location_kind="external",
                    external_path=str(source),
                    byte_size=4,
                )
                session.store.apply_probe(asset_id, _record())
                tools = MediaTools(Path("ffmpeg"), Path("ffprobe"), "ffmpeg test", "ffprobe test")
                errors: list[BaseException] = []

                def cancel(job_id: str) -> None:
                    try:
                        runtime.jobs.cancel(session.store, job_id)
                    except BaseException as exc:
                        errors.append(exc)

                def stop() -> None:
                    try:
                        runtime.shutdown()
                    except BaseException as exc:
                        errors.append(exc)

                with patch("amix.amix_engine.jobs.media.discover_tools", return_value=tools), patch(
                    "amix.amix_engine.jobs.media.proxy_command",
                    return_value=_SLEEP,
                ):
                    job = runtime.jobs.submit(
                        session.store, GENERATE_PROXY, {"profile": "amix.proxy.v1"}, asset_id,
                    )
                    self.assertTrue(entered.wait(5))
                    cancel_thread = threading.Thread(target=cancel, args=(job.job_id,))
                    stop_thread = threading.Thread(target=stop)
                    cancel_thread.start()
                    stop_thread.start()
                    self.assertTrue(waiting.wait(5))
                    cancel_thread.join(5)
                    release.set()
                    stop_thread.join(5)
                    self.assertFalse(cancel_thread.is_alive())
                    self.assertFalse(stop_thread.is_alive())
                    self.assertEqual(errors, [])
                self.assertFalse(_alive(recorded[0]))
                self.assertEqual(owned_pids(), [])
                reopened = open_project(root)
                try:
                    self.assertEqual(reopened.get_processing_job(job.job_id).status, "CANCELLED")
                finally:
                    reopened.close()
            finally:
                release.set()
                set_lifecycle_hook(None)
                runtime.shutdown()

    def test_two_cleanup_paths_do_not_throw(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        both = threading.Event()
        waiting: list[int] = []
        guard = threading.Lock()

        def hook(stage: str) -> None:
            if stage == "after_register":
                entered.set()
                release.wait(5)
            elif stage == "shutdown_waiting":
                with guard:
                    waiting.append(1)
                    if len(waiting) >= 2:
                        both.set()

        set_lifecycle_hook(hook)
        errors: list[BaseException] = []

        def run() -> None:
            try:
                run_process(_SLEEP, None)
            except BaseException as exc:
                errors.append(exc)

        def kill() -> None:
            try:
                terminate_owned_processes(5)
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(entered.wait(5))
        first = threading.Thread(target=kill)
        second = threading.Thread(target=kill)
        first.start()
        second.start()
        self.assertTrue(both.wait(5))
        release.set()
        first.join(5)
        second.join(5)
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(owned_pids(), [])

    def test_normal_exit_can_race_cancel_without_an_orphan(self) -> None:
        token = CancellationToken()

        def hook(stage: str) -> None:
            if stage == "after_register":
                threading.Thread(target=token.request).start()

        set_lifecycle_hook(hook)
        try:
            result = run_process([sys.executable, "-c", "import sys; sys.exit(0)"], token)
        except ProcessCancelled:
            result = None
        self.assertTrue(result is None or result.code == 0)
        self.assertEqual(owned_pids(), [])

    def test_process_tree_stop_reaps_the_grandchild(self) -> None:
        token = CancellationToken()
        parent: list[int] = []
        child: list[int] = []

        def hook(stage: str) -> None:
            if stage == "after_register":
                parent.extend(owned_pids())

        def on_line(line: str) -> None:
            child.append(int(line))
            token.request()

        script = (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "print(child.pid, flush=True)\n"
            "time.sleep(60)\n"
        )
        set_lifecycle_hook(hook)
        with self.assertRaises(ProcessCancelled):
            run_process([sys.executable, "-c", script], token, on_line=on_line)
        self.assertTrue(parent)
        self.assertTrue(child)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and (_alive(parent[0]) or _alive(child[0])):
            time.sleep(0.02)
        self.assertFalse(_alive(parent[0]))
        self.assertFalse(_alive(child[0]))
        self.assertEqual(owned_pids(), [])

    def test_spawn_cancel_stress(self) -> None:
        for _ in range(_STRESS_CYCLES):
            token = CancellationToken()

            def hook(stage: str, token: CancellationToken = token) -> None:
                if stage == "after_register":
                    token.request()

            set_lifecycle_hook(hook)
            try:
                with self.assertRaises(ProcessCancelled):
                    run_process(_SLEEP, token)
            finally:
                set_lifecycle_hook(None)
            self.assertEqual(owned_pids(), [])
