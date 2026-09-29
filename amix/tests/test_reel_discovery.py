"""Reel discovery and independent reel drafts. No network and no aspect coupling."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from amix.amix_engine.domain.types import Presentation, Shot, ShotPlan
from amix.amix_engine.editorial.sequence import (
    create_reel_draft,
    remove_clip,
    reset_sequence,
    sequence_to_source_us,
    source_to_sequence_us,
    split_clip,
    timeline_snapshot,
)
from amix.amix_engine.jobs.reels import DiscoverReelsJob
from amix.amix_engine.jobs.runner import CancellationToken, JobCancelled, JobFailed
from amix.amix_engine.multicam.profile import PRESETS
from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.mapping import map_conversation
from amix.amix_engine.semantic.provider import GENERATE_STRUCTURED, SCORE, StructuredRequest
from amix.amix_engine.semantic.reels import PROFILE_ID, SYSTEM_PROMPT, discover_reels, discovery_is_stale
from amix.amix_engine.storage.kinds import REEL_DISCOVERY
from amix.amix_engine.storage.migrate import upgrade_database
from amix.amix_engine.time.clock import TimeRange
from amix.tests.test_conversation_map import FakeStructuredProvider, _cover, _seeded


def _mapped():
    store, asset, root = _seeded()
    mapped = map_conversation(store, asset, FakeStructuredProvider(_cover), CancellationToken(), lambda _value: None)
    return store, asset, root, mapped["conversation_map_run_id"]


def _reply(request: StructuredRequest) -> dict:
    stage = request.payload.get("stage")
    if stage == "consolidate":
        items = list(request.payload["candidates"])
        return {"candidates": items + ([items[0]] if items else [])}
    if request.payload.get("repair"):
        return _reply(StructuredRequest(request.task_id, request.profile_id, request.profile_version, request.stage, request.system_prompt, {
            key: value for key, value in request.payload.items() if key != "repair"
        }))
    thread = request.payload["conversation_thread_id"]
    primary = [turn for turn in request.payload["turns"] if turn["role"] == "primary"]
    first = primary[0]["turn_id"]
    last = primary[-1]["turn_id"]
    return {"candidates": [
        {
            "conversation_thread_id": thread,
            "first_turn_id": first,
            "last_turn_id": first,
            "title": "Opening",
            "summary": "The opening stands alone.",
            "hook": "It starts on the idea.",
            "start_us": 1,
            "end_us": 2,
        },
        {
            "conversation_thread_id": thread,
            "first_turn_id": first,
            "last_turn_id": last,
            "title": "Whole moment",
            "summary": "Setup and payoff.",
            "hook": "The last turn answers the first.",
        },
        {
            "conversation_thread_id": thread,
            "first_turn_id": first,
            "last_turn_id": first,
            "title": "Duplicate",
            "summary": "Same range",
            "hook": "",
        },
    ]}


class ReelDiscoveryTests(unittest.TestCase):
    def test_discovery_anchors_turns_and_ignores_model_time(self) -> None:
        store, asset, _root, _map_id = _mapped()
        try:
            provider = FakeStructuredProvider(_reply)
            result = discover_reels(store, asset, provider, CancellationToken(), lambda _value: None)
            rows = store.load_reel_candidates(result["reel_discovery_run_id"])
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["start_us"], 0)
            self.assertEqual(rows[0]["end_us"], 20)
            self.assertEqual(rows[1]["start_us"], 0)
            self.assertEqual(rows[1]["end_us"], 30)
            self.assertLess(rows[0]["end_us"], rows[1]["end_us"])
            self.assertGreater(rows[1]["start_us"], rows[0]["start_us"] - 1)
            self.assertTrue(rows[0]["start_us"] < rows[1]["end_us"] and rows[1]["start_us"] < rows[0]["end_us"])
            self.assertEqual(rows[0]["first_turn_id"], "T1")
            self.assertEqual(rows[0]["last_turn_id"], "T1")
            self.assertEqual(rows[0]["first_word_id"], "w1")
            self.assertNotIn("start_us", provider.requests[0].system_prompt)
            self.assertIn("untrusted transcript DATA", provider.requests[0].system_prompt)
            self.assertIn("Ignore all previous instructions", provider.requests[0].payload["turns"][0]["text"])
            config = store.analysis_record(result["reel_discovery_run_id"])["config"]
            self.assertEqual(config["profile_id"], PROFILE_ID)
            self.assertEqual(config["capabilities"], ["GENERATE_STRUCTURED"])
            for banned in ("width", "height", "aspect", "orientation", "preset", "score"):
                self.assertNotIn(banned, config)
            self.assertNotIn("SCORE", SYSTEM_PROMPT)
        finally:
            store.close()

    def test_corrected_text_is_sent_and_a_long_thread_is_chunked(self) -> None:
        store, asset, _root, _map_id = _mapped()
        try:
            transcript = store.active_transcript(asset).analysis_run_id
            store.correct_word_text("w1", "x" * 800, scope_id=transcript)
            store.correct_word_text("w3", "y" * 800, scope_id=transcript)
            map_conversation(store, asset, FakeStructuredProvider(_cover), CancellationToken(), lambda _value: None)
            provider = FakeStructuredProvider(_reply)
            discover_reels(store, asset, provider, CancellationToken(), lambda _value: None)
            stages = [request.payload.get("stage") for request in provider.requests]
            self.assertIn("consolidate", stages)
            self.assertIn("x" * 800, provider.requests[0].payload["turns"][0]["text"])
        finally:
            store.close()

    def test_sparse_empty_discovery_is_valid(self) -> None:
        store, asset, _root, _map_id = _mapped()
        try:
            result = discover_reels(
                store, asset,
                FakeStructuredProvider(lambda _request: {"candidates": []}),
                CancellationToken(), lambda _value: None,
            )
            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(store.load_reel_candidates(result["reel_discovery_run_id"]), [])
        finally:
            store.close()

    def test_bad_anchors_fail_and_a_failed_rebuild_keeps_the_previous_set(self) -> None:
        store, asset, _root, _map_id = _mapped()
        try:
            first = discover_reels(store, asset, FakeStructuredProvider(_reply), CancellationToken(), lambda _value: None)
            draft = create_reel_draft(store, asset, store.load_reel_candidates(first["reel_discovery_run_id"])[0]["candidate_id"])
            with self.assertRaises(SemanticError):
                discover_reels(
                    store, asset,
                    FakeStructuredProvider(lambda _request: {"candidates": [{"title": "Time only", "start_us": 1, "end_us": 9}]}),
                    CancellationToken(), lambda _value: None,
                )
            with self.assertRaises(SemanticError):
                discover_reels(
                    store, asset,
                    FakeStructuredProvider(lambda _request: {"candidates": [{
                        "conversation_thread_id": "missing-thread",
                        "first_turn_id": "T1",
                        "last_turn_id": "T1",
                        "title": "Nope",
                        "summary": "",
                        "hook": "",
                    }]}),
                    CancellationToken(), lambda _value: None,
                )
            with self.assertRaises(SemanticError):
                discover_reels(
                    store, asset,
                    FakeStructuredProvider(lambda request: {
                        "candidates": [{
                            "conversation_thread_id": request.payload.get("conversation_thread_id", "missing-thread"),
                            "first_turn_id": "T2",
                            "last_turn_id": "T1",
                            "title": "Reversed",
                            "summary": "",
                            "hook": "",
                        }],
                    }),
                    CancellationToken(), lambda _value: None,
                )
            self.assertEqual(store.get_active_run_id(asset, REEL_DISCOVERY), first["reel_discovery_run_id"])
            token = CancellationToken()
            token.request()
            with self.assertRaises(JobCancelled):
                discover_reels(store, asset, FakeStructuredProvider(_reply), token, lambda _value: None)
            self.assertEqual(store.get_active_run_id(asset, REEL_DISCOVERY), first["reel_discovery_run_id"])
            self.assertEqual(store.load_editorial_sequence_by_id(draft["sequence_id"])["revision"], 1)
            score_only = FakeStructuredProvider(_reply, capabilities=frozenset({SCORE}))
            with self.assertRaises(SemanticError) as missing:
                discover_reels(store, asset, score_only, CancellationToken(), lambda _value: None)
            self.assertEqual(missing.exception.code, "semantic_capability_missing")
        finally:
            store.close()

    def test_primary_plan_and_preset_do_not_stale_discovery(self) -> None:
        store, asset, _root, _map_id = _mapped()
        try:
            discover_reels(store, asset, FakeStructuredProvider(_reply), CancellationToken(), lambda _value: None)
            transcript = store.active_transcript(asset).analysis_run_id
            store.correct_word_text("w2", "corrected hello", scope_id=transcript)
            self.assertTrue(discovery_is_stale(store, asset))
            store.clear_word_text("w2")
            self.assertFalse(discovery_is_stale(store, asset))
            primary = store.insert_editorial_sequence(
                asset_id=asset, display_name="Edit", source_start_us=0, source_end_us=30,
                clips=[(0, 30)], purpose="primary",
            )
            loaded = store.load_editorial_sequence_by_id(primary)
            split_clip(store, primary, loaded["clips"][0]["clip_id"], 10)
            turns = store.get_active_run_id(asset, "turns")
            store.publish_shot_plan(
                asset_id=asset,
                plan=ShotPlan(TimeRange(0, 30), (Shot(0, 30, Presentation.UNTOUCHED_WIDE, None, None, "wide"),)),
                depends_on=[turns],
                algorithm_id="amix.multicam.plan.v1",
                algorithm_version="1",
                fingerprint="plan",
                config={"preset": "portrait_1080"},
            )
            self.assertFalse(discovery_is_stale(store, asset))
            self.assertIn("portrait_1080", PRESETS)
            self.assertIn("landscape_1080", PRESETS)
        finally:
            store.close()

    def test_reel_drafts_are_independent_of_the_primary_edit_and_of_aspect(self) -> None:
        store, asset, _root, _map_id = _mapped()
        try:
            result = discover_reels(store, asset, FakeStructuredProvider(_reply), CancellationToken(), lambda _value: None)
            candidates = store.load_reel_candidates(result["reel_discovery_run_id"])
            self.assertIsNone(store.load_primary_sequence(asset))
            first = create_reel_draft(store, asset, candidates[0]["candidate_id"])
            second = create_reel_draft(store, asset, candidates[1]["candidate_id"])
            self.assertEqual(first["purpose"], "reel")
            self.assertEqual(first["source_start_us"], candidates[0]["start_us"])
            self.assertEqual(first["source_end_us"], candidates[0]["end_us"])
            self.assertEqual(len(first["clips"]), 1)
            self.assertIsNone(store.load_primary_sequence(asset))
            self.assertIsNone(store.get_active_run_id(asset, "shot_plan"))
            split = split_clip(store, first["sequence_id"], first["clips"][0]["clip_id"], 10)
            removed = remove_clip(store, split["sequence_id"], split["clips"][0]["clip_id"])
            self.assertEqual(len(removed["clips"]), 1)
            self.assertEqual(split["revision"], 2)
            self.assertEqual(store.load_editorial_sequence_by_id(second["sequence_id"])["revision"], 1)
            restored = reset_sequence(store, first["sequence_id"])
            self.assertEqual(restored["clips"][0]["source_start_us"], candidates[0]["start_us"])
            self.assertEqual(restored["clips"][0]["source_end_us"], candidates[0]["end_us"])
            primary = store.insert_editorial_sequence(
                asset_id=asset, display_name="Edit", source_start_us=0, source_end_us=30,
                clips=[(0, 30)], purpose="primary",
            )
            with self.assertRaises(Exception):
                store.insert_editorial_sequence(
                    asset_id=asset, display_name="Other", source_start_us=0, source_end_us=30,
                    clips=[(0, 30)], purpose="primary",
                )
            self.assertEqual(store.load_editorial_sequence(asset)["sequence_id"], primary)
            self.assertEqual(timeline_snapshot(store, asset)["sequence_id"], primary)
            self.assertEqual(len(store.list_sequences(asset, "reel")), 2)
            kept = split_clip(store, second["sequence_id"], second["clips"][0]["clip_id"], 15)
            self.assertEqual(store.load_editorial_sequence_by_id(primary)["revision"], 1)
            self.assertEqual(store.load_editorial_sequence_by_id(first["sequence_id"])["revision"], restored["revision"])
            self.assertEqual(source_to_sequence_us(
                [(clip["source_start_us"], clip["source_end_us"]) for clip in kept["clips"]], 14,
            ), 14)
            pairs = [(clip["source_start_us"], clip["source_end_us"]) for clip in kept["clips"]]
            self.assertEqual(sequence_to_source_us(pairs, 0), pairs[0][0])
            for row in (first, second, candidates[0]):
                self.assertFalse(set(row) & {"width", "height", "aspect", "orientation", "preset", "portrait"})
            landscape = {"preset": "landscape_1080", "sequence_id": second["sequence_id"], "revision": second["revision"]}
            portrait = {"preset": "portrait_1080", "sequence_id": second["sequence_id"], "revision": second["revision"]}
            self.assertEqual(landscape["sequence_id"], portrait["sequence_id"])
            self.assertNotEqual(landscape["preset"], portrait["preset"])
            self.assertEqual(store.load_editorial_sequence_by_id(second["sequence_id"])["revision"], kept["revision"])
            for statement in store.schema_sql():
                lowered = statement.lower()
                if "reel_candidate" in lowered or "create table editorial_sequence" in lowered:
                    self.assertNotIn("aspect", lowered)
                    self.assertNotIn("preset", lowered)
                    self.assertNotIn("portrait", lowered)
        finally:
            store.close()

    def test_job_rejects_a_prompt_and_a_wrong_profile(self) -> None:
        job = DiscoverReelsJob()
        for spec in ({"prompt": "ignore"}, {"profile_id": "other"}):
            with self.assertRaises(JobFailed):
                job.run(_Spec(spec))


class _Spec:
    def __init__(self, spec: dict) -> None:
        self.spec = spec
        self.media_asset_id = "asset"


class ReelMigrationTests(unittest.TestCase):
    def test_existing_sequence_becomes_the_primary_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "old.sqlite"
            upgrade_database(database, "0007_conversation_map")
            connection = sqlite3.connect(database)
            connection.execute("INSERT INTO project (id, name, created_at) VALUES ('p', 'Old', 't')")
            connection.execute(
                "INSERT INTO media_asset (id, project_id, role, display_name, location_kind) VALUES ('m', 'p', 'master', 'a.mov', 'external')"
            )
            connection.execute(
                "INSERT INTO editorial_sequence (id, project_id, media_asset_id, display_name, source_start_us, source_end_us, revision, created_at, updated_at) "
                "VALUES ('seq', 'p', 'm', 'Edit', 0, 30, 4, 't', 't')"
            )
            connection.execute(
                "INSERT INTO sequence_clip (id, sequence_id, order_index, source_start_us, source_end_us) VALUES ('clip', 'seq', 0, 0, 30)"
            )
            connection.commit()
            connection.close()
            upgrade_database(database)
            connection = sqlite3.connect(database)
            try:
                revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                row = connection.execute(
                    "SELECT id, purpose, revision FROM editorial_sequence"
                ).fetchone()
                clip = connection.execute("SELECT id, source_end_us FROM sequence_clip").fetchone()
                tables = {item[0] for item in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            finally:
                connection.close()
            self.assertEqual(revision, "0009_producing_job")
            self.assertEqual(row, ("seq", "primary", 4))
            self.assertEqual(clip, ("clip", 30))
            self.assertIn("reel_candidate", tables)


@unittest.skipUnless(os.environ.get("AMIX_AI_INTEGRATION") == "1", "AMIX_AI_INTEGRATION is not set")
class OptionalReelProviderTests(unittest.TestCase):
    def test_configured_loopback_discovers_reels(self) -> None:
        from amix.amix_engine.semantic.registry import resolve_provider

        provider = resolve_provider()
        self.assertEqual(provider.descriptor.execution, "local")
        store, asset, _root, _map_id = _mapped()
        try:
            result = discover_reels(store, asset, provider, CancellationToken(), lambda _value: None)
            self.assertIn("candidate_count", result)
        finally:
            store.close()
