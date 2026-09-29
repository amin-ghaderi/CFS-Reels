# Reel discovery

A reel is an optional short-form selection from one source. It is not the primary edit, not a multicam plan, and not an output format. The same reel draft can later be rendered at 16:9, 9:16, or another supported canvas. That choice belongs to a render profile. Phase 15 does not render the reel.

## Independence

A source may have one primary sequence and many reel sequences. A reel draft does not require a primary edit or a shot plan. Creating or editing a reel does not change the primary sequence, another reel, the transcript, turns, the conversation map, overlap, or the shot plan. Rebuilding discovery does not delete drafts. A draft keeps the candidate it was created from as historical provenance.

Discovery reads the current conversation map, the turns that map covers, and the effective corrected transcript. It does not read the primary sequence, the shot plan, camera overrides, or the render profile. A range removed from the primary edit can still be discovered.

## Candidates

A version-1 candidate is one contiguous turn range inside one conversation thread. The model returns a thread id, a first turn id, a last turn id, a title, a short summary, and a hook. It does not own time. Python derives `start_us`, `end_us`, the first and last word ids, and the duration from the stored turns. Model timestamps are ignored. Candidates may overlap. An identical anchor range in one run is kept once. Discovery is sparse: most of the source may have no candidate, and an empty result is valid.

Long sources are split on thread boundaries, then on turn boundaries inside a long thread. A turn is never split. A later consolidation sees candidate anchors, titles, summaries, and derived durations, not the whole transcript. Unknown threads, unknown turns, reversed ranges, and timestamp-only replies are rejected. One repair is allowed. A failed or cancelled rebuild does not replace the active discovery.

The task is `amix.reel.discover.v1`. It asks for structured generation only. There is no score, no ranking provider, and no decision provider in this phase.

## Persistence and staleness

Candidates are rows on an immutable `reel_discovery` analysis run. The run records the source, the conversation map, the transcript, the turns, the effective-text fingerprint, the profile, the provider descriptor, the model id, local or remote execution, the chunk fingerprints, and the request, repair, and candidate counts. Secrets are not stored.

Discovery is stale when the active conversation map changes, that map becomes stale, or the transcript, turns, or effective text no longer match. It is not stale when the primary edit, a reel draft, the shot plan, a camera override, or the render profile changes.

## Drafts

Create Reel Draft makes a new editorial sequence with purpose `reel`. Its source range is the candidate range, and it starts as one clip over that range. Reset restores that range. The existing split and remove operations edit that sequence by id. The timeline is the same canvas as the primary edit, without a required camera track. Playback seeks canonical source time and does not skip removed ranges.

## Deferred

Final reel rendering, captions, music, multi-range assembly, and ranking are later work. The domain notes still describe an older reel plan as a 9:16 edit. This phase does not implement that plan and does not store an aspect on the candidate or the draft.
