# Conversation mapping

A conversation map is an immutable `conversation_map` analysis of the source conversation. It is not an editorial sequence and it is not a Reel.

## Input

The model sees the active transcript and the compatible active turns. Turns must depend on the assignment that depends on that transcript. Older turns from another transcript are not used. If turns are missing or incompatible, mapping waits. There is no fallback to silence-gap speaker blocks.

Each turn is sent as a turn id, a participant id or unknown, ordered word ids, the participant display name as presentation only, and the effective text. Effective text includes manual word corrections. Machine word text is not rewritten. The text fingerprint hashes word ids and effective text. It does not hash display names, so renaming a participant does not make the map stale.

The transcript is data. A sentence such as “ignore previous instructions” stays inside the user payload. The task prompt stays separate. That separation is not a claim that a model will always obey it.

## Anchors

The model may return turn ids. It does not own time. Timestamp fields are ignored when turn anchors are valid, and a response with only timestamps is rejected. Python resolves the first and last turn to the turn’s source `start_us` and `end_us`, and stores the first and last word ids from those turns. Those microseconds are computed from the stored turns, not copied from the model.

## Chunks

Turns are grouped by a character budget of 1200 characters of effective text (`amix.conversation.chunk.v1`). That is a conservative stand-in for a few hundred tokens, not a vendor tokenizer. A turn is never split. A turn longer than the budget is its own chunk. The previous chunk’s last turn may be included as context. Chunk coverage applies only to primary turns. Each chunk records its first and last primary turn, the ordered primary turn ids, and a fingerprint. The same input and profile produce the same fingerprints.

When there is more than one chunk, a merge step sees candidate titles, summaries, and boundary turn ids. It does not receive the full transcript. The merge must cover every source turn exactly once.

## Threads

`conversation_thread` rows belong to one analysis run. A thread stores order, first and last turn ids, first and last word ids, title, summary, an optional short topic, and the derived source range. Threads do not overlap, do not leave a gap, and do not skip a turn. The map is not limited to Reel length. A thread may be short or long. No title is invented in code for a missing span. If the model leaves a gap, one repair is attempted and then the job fails without publishing.

The active pointer switches only after the full map is stored. A failed or cancelled rebuild leaves the previous active map in place. Older maps remain stored.

## Staleness

The map is stale when the active transcript changes, the compatible turns change, or the effective-text fingerprint changes. It is not stale because an editorial sequence cut changes, because the render aspect changes, or because a participant is renamed. Cutting the current master does not recompute the source conversation map.

## Workspace

The Conversation workspace reads this project. It distinguishes missing media, missing transcript, missing turns, a missing provider, an offline block, a running map, a ready map, a stale map, and a failed run. Map Conversation starts the first map. Rebuild Map starts another analysis and explains that the previous map is kept until the new one succeeds. Choosing a thread seeks the existing source preview to the thread’s derived start. There is no Create Reel action in this phase.

A real local model is optional and is not required for the test suite. Set `AMIX_AI_INTEGRATION=1` plus a loopback `AMIX_AI_BASE_URL` and `AMIX_AI_MODEL` to run that check. The normal suite uses a deterministic fake provider.

Reel discovery is an optional later consumer of a current conversation map. It does not change the map, and the conversation workspace does not create reel drafts.
