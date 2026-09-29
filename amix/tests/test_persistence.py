"""Project database round trips. Temporary directories only."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

from amix.amix_engine.analysis.assign import assign_words
from amix.amix_engine.analysis.overlap import overlap_regions
from amix.amix_engine.analysis.turns import build_turns
from amix.amix_engine.domain.types import (
    DiarizationSegment,
    LayoutBinding,
    LipActivitySeries,
    ParticipantId,
    ProtectedRegion,
    ShotPlan,
    Word,
)
from amix.amix_engine.multicam.planner import plan_shots
from amix.amix_engine.storage.errors import (
    MediaMissing,
    ProjectAlreadyLocked,
    ProjectDatabaseInvalid,
    SchemaMismatch,
)
from amix.amix_engine.storage.kinds import PARTICIPANT_ASSIGNMENT, SPEAKER_OVERRIDE, TURNS, WORD_TEXT
from amix.amix_engine.storage.migrate import head_revision, upgrade_database
from amix.amix_engine.storage.project import DATABASE_NAME, create_project, open_project
from amix.amix_engine.time.clock import TimeRange, legacy_seconds_to_us

FIXTURE = Path(__file__).resolve().parent / "golden" / "cfs03_49_59"
REPO = Path(__file__).resolve().parents[2]
WINDOW = TimeRange(legacy_seconds_to_us("2960"), legacy_seconds_to_us("3560"))
SENTINEL = b"AMIX-MEDIA-SENTINEL-NOT-A-BLOB"
BANNED = (b"speaker_a", b"speaker_b", b"speaker_c", b"FULL_A", b"FULL_B", b"FULL_C")


def _doc(name: str, kind: str) -> dict:
    return json.loads((FIXTURE / kind / name).read_text(encoding="utf-8"))


class SchemaTests(unittest.TestCase):
    def test_empty_directory_becomes_a_migrated_project(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Empty"
            store = create_project(root, "Empty")
            try:
                self.assertEqual(head_revision(), "0007_conversation_map")
                self.assertEqual(store.alembic_revision(), head_revision())
                self.assertEqual(store.pragma("foreign_keys"), "1")
                self.assertEqual(store.pragma("journal_mode"), "delete")
                self.assertEqual(store.pragma("synchronous"), "2")
                for folder in ("media", "proxy", "cache", "artifacts", "exports", "logs"):
                    self.assertTrue((root / folder).is_dir(), folder)
                sql = "\n".join(store.schema_sql()).upper()
                self.assertNotIn("BLOB", sql)
                self.assertIn("ACTIVE_ANALYSIS", sql)
                self.assertIn("MANUAL_CORRECTION", sql)
                self.assertIn("PROCESSING_JOB", sql)
            finally:
                store.close()
            with self.assertRaises(ProjectDatabaseInvalid):
                create_project(root, "Again")

    def test_upgrade_database_on_a_new_file(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "fresh.sqlite"
            upgrade_database(database)
            connection = sqlite3.connect(database)
            try:
                revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                tables = {
                    row[0]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                }
            finally:
                connection.close()
            self.assertEqual(revision, "0007_conversation_map")
            self.assertIn("project", tables)
            self.assertIn("diarization_segment", tables)
            self.assertIn("word", tables)
            self.assertIn("shot", tables)
            self.assertIn("processing_job", tables)
            self.assertIn("conversation_thread", tables)
            self.assertNotIn("render_job", tables)

    def test_revision_0001_upgrades_to_processing_jobs(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "step.sqlite"
            upgrade_database(database, "0001_project")
            connection = sqlite3.connect(database)
            try:
                revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                names = {
                    row[0]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                }
            finally:
                connection.close()
            self.assertEqual(revision, "0001_project")
            self.assertNotIn("processing_job", names)
            upgrade_database(database)
            connection = sqlite3.connect(database)
            try:
                revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                sql = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE name = 'processing_job'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(revision, "0007_conversation_map")
            self.assertNotIn("REAL", sql.upper())
            self.assertNotIn("BLOB", sql.upper())

    def test_read_only_refuses_an_unknown_revision(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Future"
            store = create_project(root, "Future")
            store.close()
            connection = sqlite3.connect(root / DATABASE_NAME)
            connection.execute("UPDATE alembic_version SET version_num = '9999_future'")
            connection.commit()
            connection.close()
            with self.assertRaises(SchemaMismatch):
                open_project(root, read_only=True)


class GoldenRoundTripTests(unittest.TestCase):
    def test_cfs03_survives_close_and_reopen(self) -> None:
        import tempfile
        words_doc = _doc("words.json", "inputs")
        segments_doc = _doc("diarization_segments.json", "inputs")
        map_doc = _doc("cluster_map.json", "inputs")
        layout_doc = _doc("layout.json", "inputs")
        activity_doc = _doc("lip_activity.json", "inputs")
        expected_assign = _doc("assignments.json", "expected")["assignments"]
        expected_turns = _doc("turns.json", "expected")["turns"]
        expected_overlaps = _doc("overlaps.json", "expected")["regions"]
        expected_shots = _doc("shots.json", "expected")["shots"]

        words = [
            Word(row["word_id"], legacy_seconds_to_us(row["start"]), legacy_seconds_to_us(row["end"]), row["text"])
            for row in words_doc["words"]
        ]
        segments = [
            DiarizationSegment(
                legacy_seconds_to_us(row["start"]),
                legacy_seconds_to_us(row["end"]),
                row["cluster_id"],
            )
            for row in segments_doc["segments"]
        ]
        cluster_map = {key: ParticipantId(value) for key, value in map_doc["map"].items()}
        bindings = [
            LayoutBinding(
                ParticipantId(row["participant_id"]),
                row["x"], row["y"], row["w"], row["h"],
                WINDOW,
            )
            for row in layout_doc["bindings"]
        ]
        series = LipActivitySeries(
            legacy_seconds_to_us(activity_doc["origin_seconds"]),
            1_000_000 // activity_doc["sample_fps"],
            tuple(ParticipantId(value) for value in activity_doc["column_order"]),
            tuple(tuple(frame) for frame in activity_doc["scores"]),
            tuple(activity_doc["audio_rms"]),
        )
        assignments = assign_words(words, segments, cluster_map)
        turns = build_turns(words, assignments)
        overlaps = overlap_regions(series, WINDOW)
        plan = plan_shots(WINDOW, turns, words, overlaps, bindings, [])
        protected = ProtectedRegion(TimeRange(WINDOW.start_us + 5_000_000, WINDOW.start_us + 8_000_000))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CFS03"
            store = create_project(root, "CFS03")
            try:
                media_path = root / "media" / "master.bin"
                media_path.write_bytes(SENTINEL)
                for index, binding in enumerate(bindings):
                    store.add_participant(binding.participant_id.value, binding.participant_id.value, sort_order=index)
                asset_id = store.add_media_asset(
                    display_name="CFS03",
                    role="master",
                    location_kind="project",
                    relative_path="media/master.bin",
                    byte_size=len(SENTINEL),
                    duration_us=4 * 60 * 60 * 1_000_000,
                    width=1920,
                    height=1080,
                    fps_num=30000,
                    fps_den=1001,
                    container_start_us=0,
                    container="bin",
                )
                for binding in bindings:
                    store.add_layout_binding(asset_id, binding)
                store.add_protected_region(asset_id, protected)
                fingerprint = f"cfs03-49-59:{len(words)}:{WINDOW.start_us}:{WINDOW.end_us}"
                config = {"window_start_us": WINDOW.start_us, "window_end_us": WINDOW.end_us}
                transcript_run = store.save_transcript(
                    asset_id=asset_id,
                    words=words,
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint=fingerprint,
                    window=WINDOW,
                    config=config,
                )
                assignment_run = store.save_assignments(
                    asset_id=asset_id,
                    assignments=assignments,
                    depends_on=[transcript_run],
                    algorithm_id="amix.assign",
                    algorithm_version="1",
                    fingerprint=fingerprint,
                    window=WINDOW,
                    config=config,
                )
                turn_run = store.save_turns(
                    asset_id=asset_id,
                    turns=turns,
                    depends_on=[assignment_run],
                    algorithm_id="amix.turns",
                    algorithm_version="1",
                    fingerprint=fingerprint,
                    window=WINDOW,
                    config=config,
                )
                overlap_run = store.save_overlaps(
                    asset_id=asset_id,
                    regions=overlaps,
                    depends_on=[],
                    algorithm_id="amix.overlap",
                    algorithm_version="1",
                    fingerprint=fingerprint,
                    window=WINDOW,
                    config=config,
                )
                plan_run = store.save_shot_plan(
                    asset_id=asset_id,
                    plan=plan,
                    depends_on=[turn_run, overlap_run],
                    algorithm_id="amix.shot_plan",
                    algorithm_version="1",
                    fingerprint=fingerprint,
                    config=config,
                )
                for kind, run_id in (
                    ("transcript", transcript_run),
                    (PARTICIPANT_ASSIGNMENT, assignment_run),
                    ("turns", turn_run),
                    ("overlap", overlap_run),
                    ("shot_plan", plan_run),
                ):
                    store.set_active(asset_id, kind, run_id)
                self.assertEqual(store.run_window(transcript_run), (WINDOW.start_us, WINDOW.end_us))
                self.assertNotEqual(WINDOW.start_us, 0)
                self.assertEqual(sorted(store.run_dependencies(plan_run)), sorted([turn_run, overlap_run]))
                self.assertEqual(store.run_dependencies(overlap_run), [])
            finally:
                store.close()

            database = root / DATABASE_NAME
            raw = database.read_bytes()
            self.assertNotIn(SENTINEL, raw)
            for token in BANNED:
                self.assertNotIn(token, raw)
            connection = sqlite3.connect(database)
            try:
                for table, column in (
                    ("word", "start_us"),
                    ("word", "end_us"),
                    ("turn", "start_us"),
                    ("overlap_region", "start_us"),
                    ("shot", "start_us"),
                    ("layout_binding", "start_us"),
                    ("protected_region", "start_us"),
                    ("analysis_run", "window_start_us"),
                ):
                    kind = connection.execute(f"SELECT typeof({column}) FROM {table} LIMIT 1").fetchone()[0]
                    self.assertEqual(kind, "integer", f"{table}.{column}")
                window = connection.execute(
                    "SELECT window_start_us, window_end_us FROM analysis_run WHERE kind = 'transcript'"
                ).fetchone()
                self.assertEqual(window, (WINDOW.start_us, WINDOW.end_us))
            finally:
                connection.close()

            store = open_project(root)
            try:
                self.assertEqual(store.get_active_run_id(asset_id, "transcript"), transcript_run)
                self.assertEqual(store.get_active_run_id(asset_id, PARTICIPANT_ASSIGNMENT), assignment_run)
                self.assertEqual(store.get_active_run_id(asset_id, "turns"), turn_run)
                self.assertEqual(store.get_active_run_id(asset_id, "overlap"), overlap_run)
                self.assertEqual(store.get_active_run_id(asset_id, "shot_plan"), plan_run)
                loaded_words = store.load_words(transcript_run)
                self.assertEqual(
                    [(row.word_id, row.machine_text, row.effective_text, row.start_us, row.end_us) for row in loaded_words],
                    [(word.word_id, word.text, word.text, word.start_us, word.end_us) for word in words],
                )
                loaded_assignments = store.load_assignments(assignment_run)
                self.assertEqual(loaded_assignments, assignments)
                for row, want in zip(loaded_assignments, expected_assign):
                    got = None if row.participant_id is None else row.participant_id.value
                    self.assertEqual(row.word_id, want["word_id"])
                    self.assertEqual(got, want["participant_id"])
                loaded_turns = store.load_turns(turn_run)
                self.assertEqual(loaded_turns, turns)
                for turn, want in zip(loaded_turns, expected_turns):
                    got = None if turn.participant_id is None else turn.participant_id.value
                    self.assertEqual(turn.turn_id, want["turn_id"])
                    self.assertEqual(got, want["participant_id"])
                    self.assertEqual(turn.start_us, want["start_us"])
                    self.assertEqual(turn.end_us, want["end_us"])
                    self.assertEqual(turn.word_count, want["word_count"])
                loaded_overlaps = store.load_overlaps(overlap_run)
                self.assertEqual(loaded_overlaps, overlaps)
                for region, want in zip(loaded_overlaps, expected_overlaps):
                    self.assertEqual(region.start_us, want["start_us"])
                    self.assertEqual(region.end_us, want["end_us"])
                    self.assertEqual([item.value for item in region.participant_ids], want["participant_ids"])
                    self.assertEqual(region.confidence, want["confidence"])
                loaded_plan = store.load_shot_plan(plan_run)
                self.assertEqual(loaded_plan, plan)
                self.assertIsInstance(loaded_plan, ShotPlan)
                for shot, want in zip(loaded_plan.shots, expected_shots):
                    self.assertEqual(shot.start_us, want["start_us"])
                    self.assertEqual(shot.end_us, want["end_us"])
                    self.assertEqual(shot.presentation.value, want["presentation"])
                    got = None if shot.participant_id is None else shot.participant_id.value
                    floor = None if shot.floor_participant_id is None else shot.floor_participant_id.value
                    self.assertEqual(got, want["participant_id"])
                    self.assertEqual(floor, want["floor_participant_id"])
                    self.assertEqual(shot.reason, want["reason"])
                self.assertEqual(store.load_layout_bindings(asset_id), bindings)
                self.assertEqual(store.load_protected_regions(asset_id), [protected])
                media = store.get_media(asset_id)
                self.assertEqual(media.duration_us, 4 * 60 * 60 * 1_000_000)
                self.assertEqual(media.container_start_us, 0)
                self.assertEqual(media.fps_num, 30000)
                self.assertEqual(media.relative_path, "media/master.bin")
                self.assertEqual(store.resolve_media(asset_id), media_path)
                self.assertEqual(store.media_status(asset_id), "present")
            finally:
                store.close()

            reader = open_project(root, read_only=True)
            try:
                self.assertEqual(reader.pragma("query_only"), "1")
                self.assertEqual(reader.load_turns(turn_run), turns)
            finally:
                reader.close()


class RerunTests(unittest.TestCase):
    def test_old_turn_run_remains_after_the_active_pointer_moves(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store = create_project(Path(tmp) / "Rerun", "Rerun")
            try:
                store.add_participant("p1", "One")
                asset_id = store.add_media_asset(
                    display_name="clip",
                    location_kind="external",
                    external_path=str(Path(tmp) / "missing.mp4"),
                )
                word = Word("w1", 10_000_000, 11_000_000, "hello")
                transcript_run = store.save_transcript(
                    asset_id=asset_id,
                    words=[word],
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="rerun-words",
                    window=TimeRange(10_000_000, 20_000_000),
                )
                from amix.amix_engine.domain.types import Turn
                first = [Turn("T0001", ParticipantId("p1"), 10_000_000, 12_000_000, ("w1",))]
                second = [Turn("T0001", ParticipantId("p1"), 10_000_000, 15_000_000, ("w1",))]
                run_1 = store.save_turns(
                    asset_id=asset_id,
                    turns=first,
                    depends_on=[transcript_run],
                    algorithm_id="amix.turns",
                    algorithm_version="1",
                    fingerprint="run-1",
                    window=TimeRange(10_000_000, 20_000_000),
                )
                store.set_active(asset_id, TURNS, run_1)
                self.assertEqual(store.get_active_run_id(asset_id, TURNS), run_1)
                run_2 = store.save_turns(
                    asset_id=asset_id,
                    turns=second,
                    depends_on=[transcript_run],
                    algorithm_id="amix.turns",
                    algorithm_version="1",
                    fingerprint="run-2",
                    window=TimeRange(10_000_000, 20_000_000),
                )
                self.assertNotEqual(run_1, run_2)
                store.set_active(asset_id, TURNS, run_2)
                self.assertEqual(store.get_active_run_id(asset_id, TURNS), run_2)
                self.assertEqual(store.list_run_ids(asset_id, TURNS), [run_1, run_2])
                self.assertEqual(store.load_turns(run_1), first)
                self.assertEqual(store.load_turns(run_2), second)
                self.assertEqual(store.media_status(asset_id), "missing")
                with self.assertRaises(MediaMissing):
                    store.require_media(asset_id)
            finally:
                store.close()
            connection = sqlite3.connect(Path(tmp) / "Rerun" / DATABASE_NAME)
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("DELETE FROM analysis_run WHERE id = ?", (run_1,))
            finally:
                connection.close()


class PerAssetTests(unittest.TestCase):
    def test_active_transcripts_are_independent(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store = create_project(Path(tmp) / "Two", "Two")
            try:
                asset_a = store.add_media_asset(
                    display_name="A clip",
                    location_kind="external",
                    external_path=str(Path(tmp) / "a.mp4"),
                )
                asset_b = store.add_media_asset(
                    display_name="B clip",
                    location_kind="external",
                    external_path=str(Path(tmp) / "b.mp4"),
                )
                run_a = store.save_transcript(
                    asset_id=asset_a,
                    words=[Word("wa", 0, 1_000, "alpha")],
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="a",
                    window=TimeRange(0, 1_000),
                )
                run_b = store.save_transcript(
                    asset_id=asset_b,
                    words=[Word("wb", 0, 1_000, "beta")],
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="b",
                    window=TimeRange(0, 1_000),
                )
                store.set_active(asset_a, "transcript", run_a)
                store.set_active(asset_b, "transcript", run_b)
                run_a2 = store.save_transcript(
                    asset_id=asset_a,
                    words=[Word("wa2", 0, 1_000, "alpha-2")],
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="a2",
                    window=TimeRange(0, 1_000),
                )
                store.set_active(asset_a, "transcript", run_a2)
                self.assertEqual(store.get_active_run_id(asset_a, "transcript"), run_a2)
                self.assertEqual(store.get_active_run_id(asset_b, "transcript"), run_b)
                self.assertEqual(store.load_words(run_b)[0].machine_text, "beta")
                self.assertEqual(store.load_words(run_a)[0].machine_text, "alpha")
                with self.assertRaises(ProjectDatabaseInvalid):
                    store.set_active(asset_b, "transcript", run_a2)
            finally:
                store.close()


class CorrectionTests(unittest.TestCase):
    def test_word_text_overlay_does_not_follow_a_new_transcript(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store = create_project(Path(tmp) / "Edit", "Edit")
            try:
                store.add_participant("p1", "One")
                store.add_participant("p2", "Two")
                asset_id = store.add_media_asset(
                    display_name="clip",
                    location_kind="external",
                    external_path=str(Path(tmp) / "clip.mp4"),
                )
                first = store.save_transcript(
                    asset_id=asset_id,
                    words=[Word("w-old", 1_000, 2_000, "foo")],
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="t1",
                    window=TimeRange(0, 5_000),
                )
                from amix.amix_engine.domain.types import SpeakerAssignment
                assignment_run = store.save_assignments(
                    asset_id=asset_id,
                    assignments=[SpeakerAssignment("w-old", ParticipantId("p1"))],
                    depends_on=[first],
                    algorithm_id="amix.assign",
                    algorithm_version="1",
                    fingerprint="assign",
                    window=TimeRange(0, 5_000),
                )
                store.correct_word_text("w-old", "bar", scope_id=first)
                store.correct_speaker("w-old", "p2", scope_id=assignment_run)
                loaded = store.load_words(first)[0]
                self.assertEqual(loaded.machine_text, "foo")
                self.assertEqual(loaded.effective_text, "bar")
                self.assertEqual(store.machine_word_text("w-old"), "foo")
                self.assertEqual(store.load_assignments(assignment_run)[0].participant_id, ParticipantId("p1"))
                self.assertEqual(store.correction_value(SPEAKER_OVERRIDE, "w-old"), "p2")
                self.assertEqual(store.correction_value(WORD_TEXT, "w-old"), "bar")
                second = store.save_transcript(
                    asset_id=asset_id,
                    words=[Word("w-new", 1_000, 2_000, "baz")],
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="t2",
                    window=TimeRange(0, 5_000),
                )
                store.set_active(asset_id, "transcript", second)
                self.assertIn("w-old", store.inapplicable_corrections(second))
                self.assertNotIn("w-old", store.inapplicable_corrections(first))
                fresh = store.load_words(second)[0]
                self.assertEqual(fresh.machine_text, "baz")
                self.assertEqual(fresh.effective_text, "baz")
                self.assertEqual(store.load_words(first)[0].effective_text, "bar")
                self.assertEqual(store.machine_word_text("w-old"), "foo")
            finally:
                store.close()


class RelocationTests(unittest.TestCase):
    def test_relative_media_resolves_after_the_directory_moves(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "Original"
            store = create_project(original, "Move")
            media = original / "media" / "clip.bin"
            media.write_bytes(b"dummy")
            try:
                asset_id = store.add_media_asset(
                    display_name="clip",
                    location_kind="project",
                    relative_path="media/clip.bin",
                    byte_size=5,
                    duration_us=1_000_000,
                )
                run_id = store.save_transcript(
                    asset_id=asset_id,
                    words=[Word("w", 0, 500_000, "hi")],
                    algorithm_id="amix.transcript.import",
                    algorithm_version="1",
                    fingerprint="move",
                    window=TimeRange(0, 1_000_000),
                )
                store.set_active(asset_id, "transcript", run_id)
            finally:
                store.close()
            moved = Path(tmp) / "Moved"
            original.rename(moved)
            store = open_project(moved)
            try:
                resolved = store.resolve_media(asset_id)
                self.assertEqual(resolved, moved / "media" / "clip.bin")
                self.assertTrue(resolved.is_file())
                self.assertEqual(store.media_status(asset_id), "present")
                self.assertEqual(store.get_active_run_id(asset_id, "transcript"), run_id)
                self.assertEqual(store.load_words(run_id)[0].machine_text, "hi")
                relinked = moved / "media" / "clip-relinked.bin"
                relinked.write_bytes(b"dummy")
                store.relink_media(asset_id, relative_path="media/clip-relinked.bin")
                self.assertEqual(store.resolve_media(asset_id), relinked)
                self.assertEqual(store.get_active_run_id(asset_id, "transcript"), run_id)
                self.assertEqual(store.load_words(run_id)[0].start_us, 0)
            finally:
                store.close()


class LockTests(unittest.TestCase):
    def test_second_local_writer_is_blocked_until_close(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Locked"
            holder = create_project(root, "Locked")
            try:
                self.assertEqual(_probe(root, "write"), 2)
                self.assertEqual(_probe(root, "read"), 0)
                note = json.loads((root / "project.lock.json").read_text(encoding="utf-8"))
                self.assertIn("pid", note)
                self.assertIn("hostname", note)
            finally:
                holder.close()
            (root / "project.lock.json").write_text(
                json.dumps({"pid": 1, "hostname": "stale", "opened_at": "2000-01-01T00:00:00+00:00"}),
                encoding="utf-8",
            )
            self.assertEqual(_probe(root, "write"), 0)


def _probe(root: Path, mode: str) -> int:
    script = root / "_probe.py"
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


class ProductBoundaryTests(unittest.TestCase):
    def test_storage_modules_do_not_use_create_all_or_legacy(self) -> None:
        root = Path(__file__).resolve().parents[1] / "amix_engine" / "storage"
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("create_all", text, path.name)
            self.assertNotIn("legacy", text, path.name)
            self.assertNotIn("FULL_A", text, path.name)


if __name__ == "__main__":
    unittest.main()
