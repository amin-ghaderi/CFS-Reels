"""Render plan and FFmpeg graph. One compiler for every output canvas."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from amix.amix_engine.domain.types import LayoutBinding, ParticipantId
from amix.amix_engine.multicam.effective import EffectiveShot
from amix.amix_engine.multicam.framegrid import frame_index
from amix.amix_engine.multicam.framing import FramingError, center_fill, covering_segments
from amix.amix_engine.multicam.profile import PROFILE_ID, RenderPreset

FIT = "fit"
CENTER_FILL = "center_fill"


@dataclass(frozen=True)
class RenderSegment:
    start_us: int
    end_us: int
    start_frame: int
    end_frame: int
    presentation: str
    participant_id: str | None
    framing: str
    crop_x: int | None
    crop_y: int | None
    crop_w: int | None
    crop_h: int | None


@dataclass(frozen=True)
class RenderPlan:
    profile_id: str
    preset_id: str
    output_width: int
    output_height: int
    fps_num: int
    fps_den: int
    start_us: int
    end_us: int
    source_start_us: int
    source_end_us: int
    has_audio: bool
    total_frames: int
    segments: tuple[RenderSegment, ...]
    audio_spans: tuple[tuple[int, int], ...] | None = None
    container_start_us: int = 0


def compile_render(
    *,
    shots: list[EffectiveShot],
    bindings: list[LayoutBinding],
    preset: RenderPreset,
    fps_num: int,
    fps_den: int,
    render_start_us: int,
    render_end_us: int,
    container_start_us: int,
    source_width: int,
    source_height: int,
    has_audio: bool,
) -> RenderPlan:
    if not shots or render_end_us <= render_start_us:
        raise FramingError("empty_plan", "This plan has no shots to render.")
    pieces = _pieces(shots, bindings, preset.width, preset.height, source_width, source_height)
    segments: list[RenderSegment] = []
    for piece in pieces:
        start_frame = frame_index(piece["start_us"], render_start_us, fps_num, fps_den)
        end_frame = frame_index(piece["end_us"], render_start_us, fps_num, fps_den)
        if end_frame <= start_frame:
            continue
        segments.append(RenderSegment(
            start_us=piece["start_us"],
            end_us=piece["end_us"],
            start_frame=start_frame,
            end_frame=end_frame,
            presentation=piece["presentation"],
            participant_id=piece["participant_id"],
            framing=piece["framing"],
            crop_x=piece["crop_x"],
            crop_y=piece["crop_y"],
            crop_w=piece["crop_w"],
            crop_h=piece["crop_h"],
        ))
    total = frame_index(render_end_us, render_start_us, fps_num, fps_den)
    counted = sum(item.end_frame - item.start_frame for item in segments)
    if not segments or counted != total:
        raise FramingError("empty_plan", "This plan has no output frames.")
    relative_start = render_start_us - container_start_us
    relative_end = render_end_us - container_start_us
    if relative_start < 0 or relative_end <= relative_start:
        raise FramingError("invalid_analysis_window", "The render range is outside this media.")
    return RenderPlan(
        profile_id=PROFILE_ID,
        preset_id=preset.preset_id,
        output_width=preset.width,
        output_height=preset.height,
        fps_num=fps_num,
        fps_den=fps_den,
        start_us=render_start_us,
        end_us=render_end_us,
        source_start_us=relative_start,
        source_end_us=relative_end,
        has_audio=has_audio,
        total_frames=total,
        segments=tuple(segments),
    )


def compile_kept_render(
    *,
    shots: list[EffectiveShot],
    clips: list[tuple[int, int]],
    bindings: list[LayoutBinding],
    preset: RenderPreset,
    fps_num: int,
    fps_den: int,
    render_start_us: int,
    render_end_us: int,
    container_start_us: int,
    source_width: int,
    source_height: int,
    has_audio: bool,
) -> RenderPlan:
    """Compile kept source ranges. One full-range clip uses the Phase 12 path."""
    if (
        len(clips) == 1
        and clips[0][0] == render_start_us
        and clips[0][1] == render_end_us
    ):
        return compile_render(
            shots=shots,
            bindings=bindings,
            preset=preset,
            fps_num=fps_num,
            fps_den=fps_den,
            render_start_us=render_start_us,
            render_end_us=render_end_us,
            container_start_us=container_start_us,
            source_width=source_width,
            source_height=source_height,
            has_audio=has_audio,
        )
    pieces = _kept_pieces(shots, clips, bindings, preset.width, preset.height, source_width, source_height)
    duration = sum(end - start for start, end in clips)
    segments: list[RenderSegment] = []
    sequence_origin = 0
    for clip_start, clip_end in clips:
        for piece in pieces:
            if piece["start_us"] < clip_start or piece["end_us"] > clip_end:
                continue
            seq_start = sequence_origin + (piece["start_us"] - clip_start)
            seq_end = sequence_origin + (piece["end_us"] - clip_start)
            start_frame = frame_index(seq_start, 0, fps_num, fps_den)
            end_frame = frame_index(seq_end, 0, fps_num, fps_den)
            if end_frame <= start_frame:
                continue
            segments.append(RenderSegment(
                start_us=piece["start_us"],
                end_us=piece["end_us"],
                start_frame=start_frame,
                end_frame=end_frame,
                presentation=piece["presentation"],
                participant_id=piece["participant_id"],
                framing=piece["framing"],
                crop_x=piece["crop_x"],
                crop_y=piece["crop_y"],
                crop_w=piece["crop_w"],
                crop_h=piece["crop_h"],
            ))
        sequence_origin += clip_end - clip_start
    total = frame_index(duration, 0, fps_num, fps_den)
    counted = sum(item.end_frame - item.start_frame for item in segments)
    if duration <= 0 or not segments or counted != total:
        raise FramingError("empty_plan", "This edit has no output frames.")
    spans = []
    for start_us, end_us in clips:
        relative_start = start_us - container_start_us
        relative_end = end_us - container_start_us
        if relative_start < 0 or relative_end <= relative_start:
            raise FramingError("invalid_analysis_window", "The render range is outside this media.")
        spans.append((relative_start, relative_end))
    return RenderPlan(
        profile_id=PROFILE_ID,
        preset_id=preset.preset_id,
        output_width=preset.width,
        output_height=preset.height,
        fps_num=fps_num,
        fps_den=fps_den,
        start_us=0,
        end_us=duration,
        source_start_us=spans[0][0],
        source_end_us=spans[-1][1],
        has_audio=has_audio,
        total_frames=total,
        segments=tuple(segments),
        audio_spans=tuple(spans),
        container_start_us=container_start_us,
    )


def filter_script(plan: RenderPlan) -> str:
    if plan.audio_spans is not None:
        return _cut_script(plan)
    count = len(plan.segments)
    if count == 1:
        segment = plan.segments[0]
        body = _segment_filter(segment, plan.output_width, plan.output_height)
        lines = [
            (
                f"[0:v]trim=start={_seconds(plan.source_start_us)}:end={_seconds(plan.source_end_us)},"
                f"setpts=PTS-STARTPTS,fps={plan.fps_num}/{plan.fps_den}:start_time=0:round=near,"
                f"trim=start_frame={segment.start_frame}:end_frame={segment.end_frame},"
                f"setpts=PTS-STARTPTS,{body}[outv]"
            )
        ]
        if plan.has_audio:
            lines.append(
                f"[0:a]atrim=start={_seconds(plan.source_start_us)}:end={_seconds(plan.source_end_us)},"
                "asetpts=PTS-STARTPTS[outa]"
            )
        return ";\n".join(lines) + "\n"
    labels = "".join(f"[b{index}]" for index in range(count))
    lines = [
        (
            f"[0:v]trim=start={_seconds(plan.source_start_us)}:end={_seconds(plan.source_end_us)},"
            f"setpts=PTS-STARTPTS,fps={plan.fps_num}/{plan.fps_den}:start_time=0:round=near,"
            f"split={count}{labels}"
        )
    ]
    outputs = []
    for index, segment in enumerate(plan.segments):
        body = _segment_filter(segment, plan.output_width, plan.output_height)
        lines.append(
            f"[b{index}]trim=start_frame={segment.start_frame}:end_frame={segment.end_frame},"
            f"setpts=PTS-STARTPTS,{body}[s{index}]"
        )
        outputs.append(f"[s{index}]")
    lines.append(f"{''.join(outputs)}concat=n={count}:v=1:a=0[outv]")
    if plan.has_audio:
        lines.append(
            f"[0:a]atrim=start={_seconds(plan.source_start_us)}:end={_seconds(plan.source_end_us)},"
            "asetpts=PTS-STARTPTS[outa]"
        )
    return ";\n".join(lines) + "\n"


def ffmpeg_args(ffmpeg: str, source: str, script: Path, dest: Path, plan: RenderPlan) -> list[str]:
    args = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-progress", "pipe:1", "-nostats",
        "-i", source,
        "-filter_complex_script", str(script),
        "-map", "[outv]",
    ]
    if plan.has_audio:
        args.extend(["-map", "[outa]", "-c:a", "aac", "-b:a", "128k", "-ar", "48000"])
    args.extend([
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(dest),
    ])
    return args


def _pieces(shots, bindings, out_w, out_h, source_w, source_h) -> list[dict]:
    if source_w <= 0 or source_h <= 0:
        raise FramingError("render_requires_probe", "Probe this media before rendering.")
    pieces = []
    for shot in shots:
        if shot.effective_presentation == "full":
            if not shot.effective_participant_id:
                raise FramingError("layout_not_covering", "A full shot needs a participant.")
            parts = covering_segments(
                bindings, ParticipantId(shot.effective_participant_id), shot.start_us, shot.end_us,
            )
            if not parts:
                raise FramingError("layout_not_covering", "That participant does not cover this whole shot.")
            for start, end, binding in parts:
                crop = center_fill(binding.x, binding.y, binding.w, binding.h, out_w, out_h)
                pieces.append({
                    "start_us": start,
                    "end_us": end,
                    "presentation": "full",
                    "participant_id": shot.effective_participant_id,
                    "framing": CENTER_FILL,
                    "crop_x": crop.x,
                    "crop_y": crop.y,
                    "crop_w": crop.w,
                    "crop_h": crop.h,
                })
            continue
        pieces.append({
            "start_us": shot.start_us,
            "end_us": shot.end_us,
            "presentation": shot.effective_presentation,
            "participant_id": None,
            "framing": FIT,
            "crop_x": None,
            "crop_y": None,
            "crop_w": None,
            "crop_h": None,
        })
    return pieces


def _kept_pieces(shots, clips, bindings, out_w, out_h, source_w, source_h) -> list[dict]:
    if source_w <= 0 or source_h <= 0:
        raise FramingError("render_requires_probe", "Probe this media before rendering.")
    pieces = []
    ordered = sorted(shots, key=lambda shot: (shot.start_us, shot.end_us))
    for clip_start, clip_end in clips:
        cursor = clip_start
        for shot in ordered:
            left = max(shot.start_us, clip_start)
            right = min(shot.end_us, clip_end)
            if right <= left:
                continue
            if left != cursor:
                raise FramingError("empty_plan", "The shot plan does not cover this edit.")
            if shot.effective_presentation == "full":
                if not shot.effective_participant_id:
                    raise FramingError("layout_not_covering", "A full shot needs a participant.")
                parts = covering_segments(
                    bindings, ParticipantId(shot.effective_participant_id), left, right,
                )
                if not parts:
                    raise FramingError("layout_not_covering", "That participant does not cover this whole shot.")
                for start, end, binding in parts:
                    crop = center_fill(binding.x, binding.y, binding.w, binding.h, out_w, out_h)
                    pieces.append({
                        "start_us": start,
                        "end_us": end,
                        "presentation": "full",
                        "participant_id": shot.effective_participant_id,
                        "framing": CENTER_FILL,
                        "crop_x": crop.x,
                        "crop_y": crop.y,
                        "crop_w": crop.w,
                        "crop_h": crop.h,
                    })
            else:
                pieces.append({
                    "start_us": left,
                    "end_us": right,
                    "presentation": shot.effective_presentation,
                    "participant_id": None,
                    "framing": FIT,
                    "crop_x": None,
                    "crop_y": None,
                    "crop_w": None,
                    "crop_h": None,
                })
            cursor = right
        if cursor != clip_end:
            raise FramingError("empty_plan", "The shot plan does not cover this edit.")
    return pieces


def _cut_script(plan: RenderPlan) -> str:
    lines = []
    labels = []
    for index, segment in enumerate(plan.segments):
        body = _segment_filter(segment, plan.output_width, plan.output_height)
        lines.append(
            f"[0:v]trim=start={_seconds(segment.start_us - plan.container_start_us)}:"
            f"end={_seconds(segment.end_us - plan.container_start_us)},"
            f"setpts=PTS-STARTPTS,{body}[v{index}]"
        )
        labels.append(f"[v{index}]")
    lines.append(
        f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0,"
        f"fps={plan.fps_num}/{plan.fps_den}:start_time=0:round=near[outv]"
    )
    if plan.has_audio and plan.audio_spans:
        audio_labels = []
        for index, (start_us, end_us) in enumerate(plan.audio_spans):
            lines.append(
                f"[0:a]atrim=start={_seconds(start_us)}:end={_seconds(end_us)},"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )
            audio_labels.append(f"[a{index}]")
        lines.append(f"{''.join(audio_labels)}concat=n={len(audio_labels)}:v=0:a=1[outa]")
    return ";\n".join(lines) + "\n"


def _segment_filter(segment: RenderSegment, out_w: int, out_h: int) -> str:
    if segment.framing == CENTER_FILL:
        return (
            f"crop={segment.crop_w}:{segment.crop_h}:{segment.crop_x}:{segment.crop_y},"
            f"scale={out_w}:{out_h}:flags=bilinear,setsar=1"
        )
    return (
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=bilinear,"
        f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    )


def _seconds(microseconds: int) -> str:
    return f"{microseconds // 1_000_000}.{microseconds % 1_000_000:06d}"
