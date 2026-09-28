"""Automatic multicam plan. This job calls the existing planner. It does not direct."""
from __future__ import annotations

from amix.amix_engine.jobs.runner import JobContext, JobFailed
from amix.amix_engine.multicam.apply import PLAN_PROFILE, PlanRejected, build_automatic_plan

BUILD_MULTICAM_PLAN = "build_multicam_plan"
_SPEC_KEYS = frozenset({"profile"})


class BuildMulticamPlanJob:
    kind = BUILD_MULTICAM_PLAN

    def run(self, ctx: JobContext) -> dict:
        _profile(ctx.spec)
        if not ctx.media_asset_id:
            raise JobFailed("unknown_media_asset", "That media file is no longer in this project.")
        ctx.cancellation.raise_if_cancelled()
        ctx.report_progress(1000)
        try:
            run_id = build_automatic_plan(ctx.store, ctx.media_asset_id)
        except PlanRejected as exc:
            raise JobFailed(exc.code, exc.message) from exc
        ctx.cancellation.raise_if_cancelled()
        ctx.store.set_job_progress(ctx.job_id, 10000)
        plan = ctx.store.load_shot_plan(run_id)
        return {"activated": True, "shot_plan_run_id": run_id, "shot_count": len(plan.shots)}


def _profile(spec: dict) -> None:
    if not isinstance(spec, dict) or set(spec) - _SPEC_KEYS:
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    profile = spec.get("profile")
    if profile is not None and profile != PLAN_PROFILE:
        raise JobFailed("invalid_plan_profile", "That multicam profile is not available.")
