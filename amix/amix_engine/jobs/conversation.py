"""Conversation map job. The request names a product task, not a provider endpoint."""
from __future__ import annotations

from amix.amix_engine.jobs.runner import JobCancelled, JobContext, JobFailed
from amix.amix_engine.semantic.errors import SemanticError
from amix.amix_engine.semantic.mapping import map_conversation
from amix.amix_engine.semantic.registry import resolve_provider
from amix.amix_engine.semantic.tasks import PROFILE_ID

MAP_CONVERSATION = "map_conversation"
_SPEC_KEYS = frozenset({"profile_id"})


class MapConversationJob:
    kind = MAP_CONVERSATION

    def run(self, ctx: JobContext) -> dict:
        _spec(ctx.spec)
        if not ctx.media_asset_id:
            raise JobFailed("unknown_media_asset", "That media file is no longer in this project.")
        try:
            provider = resolve_provider(cancel=ctx.cancellation)
        except SemanticError as exc:
            if exc.code == "local_model_stopped":
                raise JobCancelled() from exc
            raise JobFailed(exc.code, exc.message) from exc
        try:
            result = map_conversation(
                ctx.store,
                ctx.media_asset_id,
                provider,
                ctx.cancellation,
                ctx.report_progress,
            )
        except JobCancelled:
            raise
        except SemanticError as exc:
            raise JobFailed(exc.code, exc.message) from exc
        ctx.store.set_job_progress(ctx.job_id, 10000)
        return result


def _spec(spec: dict) -> None:
    if not isinstance(spec, dict) or set(spec) - _SPEC_KEYS:
        raise JobFailed("job_spec_rejected", "The job request was rejected.")
    profile = spec.get("profile_id")
    if profile is not None and profile != PROFILE_ID:
        raise JobFailed("invalid_semantic_profile", "That conversation profile is not available.")
