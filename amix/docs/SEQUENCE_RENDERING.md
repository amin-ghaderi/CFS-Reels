# Sequence rendering

Rendering is three independent inputs:

1. **EditorialSequence** — which source ranges are kept (content)
2. **VisualTreatment** — how those ranges are pictured (source/program or multicam)
3. **RenderProfile** — output canvas, aspect, and frame-rate policy

Changing one does not rewrite the other two. A reel is not portrait. Multicam is not a reel. The primary edit is not a reel.

## Visual treatment

`source_program` draws the complete displayed source picture for each kept clip. It uses the existing WIDE/FIT policy: preserve aspect ratio, fit inside the canvas, pad with black. No shot plan, layout, participant assignment, or camera override is required. Camera boundaries do not create splits.

`multicam` intersects the selected sequence with the current effective shot plan, layout boundaries, and protected regions. Manual shot overrides stay on the source shot plan and are not copied onto the sequence. A reel may use multicam without a primary sequence. If the plan is missing or stale, multicam is unavailable; source/program may still be ready.

## Compiler

One compiler owns crop, audio, and the global sequence-time frame grid. `compile_source_program`, `compile_kept_render`, and `compile_render` are policies on that compiler. There is no separate reel FFmpeg pipeline.

Every visual segment uses frame indexes on one sequence-time grid. Clip durations and camera fragment durations are not rounded separately and then added. Editorial cuts cut audio. Camera decisions do not. The same sequence and profile therefore share the same kept audio spans under both picture treatments. The output frame count for a given sequence and profile is the same for both treatments.

## Job

`render_sequence` accepts only `sequence_id`, `visual_treatment`, `render_profile_id`, and an optional `sequence_revision`. The engine resolves the source, plan, overrides, layout, and FFmpeg. React cannot pass a filter graph, output path, or executable.

Historic `render_multicam` jobs remain readable. That handler is a thin adapter: primary sequence when present, visual treatment multicam, selected preset. Multicam workspace rendering uses `render_sequence` with the same multicam treatment.

## Provenance

Every successful export records the source, sequence id and purpose, revision, sequence fingerprint, clip fingerprint, visual treatment, profile and preset, canvas size, frame-rate rational, framing policy, FFmpeg version, lightweight source identity, and export media id. Multicam also records the shot-plan run and override, effective, layout, and protected fingerprints. Source/program records that no camera-analysis dependency was used.

Export media assets store their producing job under `producing_job_id`. That column used to be named for proxies only.

## Workspace use

The Reels workspace renders a selected reel draft. Picture and format are separate controls. Landscape and portrait use the same reel sequence and revision. Export history is filtered by sequence id.

The Multicam workspace remains the camera-directed path. Internally it asks for the primary sequence and multicam treatment.

## Deferred

Reel-local camera overrides, captions, music, smart portrait reframing, social templates, and publication are later work.
