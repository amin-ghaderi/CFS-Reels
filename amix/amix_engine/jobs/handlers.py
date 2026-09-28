"""Explicit production job handlers.

An HTTP client chooses a kind from this set. It cannot name an arbitrary callable.
"""
from __future__ import annotations

from amix.amix_engine.jobs.runner import JobContext
from amix.amix_engine.storage.errors import ProjectDatabaseInvalid

PROJECT_INTEGRITY_CHECK = "project_integrity_check"


class ProjectIntegrityCheck:
    """Read project invariants. This handler does not change analysis rows."""

    kind = PROJECT_INTEGRITY_CHECK

    def run(self, ctx: JobContext) -> dict:
        ctx.report_progress(2000)
        assets = []
        for media in ctx.store.list_media_assets():
            ctx.cancellation.raise_if_cancelled()
            assets.append({
                "asset_id": media.asset_id,
                "status": ctx.store.media_status(media.asset_id),
            })
        ctx.report_progress(7000)
        active = []
        problems = []
        for asset_id, kind, run_id in ctx.store.list_active_analyses():
            try:
                ctx.store.run_window(run_id)
            except ProjectDatabaseInvalid:
                problems.append({"code": "active_run_missing", "analysis_run_id": run_id})
            active.append({
                "media_asset_id": asset_id,
                "kind": kind,
                "analysis_run_id": run_id,
            })
        ctx.report_progress(10000)
        return {
            "assets": assets,
            "active": active,
            "problems": problems,
            "analysis_run_count": ctx.store.count_analysis_runs(),
        }
