# AI provider architecture

AMIX calls **capabilities** to perform **tasks**. It does not call “the LLM” as one type.

Cursor, Grok, OpenAI, Anthropic, Gemini, Jev, llama.cpp, and an OpenAI-compatible HTTP endpoint are adapters. None is required for the media spine.

## Capabilities

| Capability | Meaning |
|---|---|
| `GENERATE_TEXT` | Prose. |
| `GENERATE_STRUCTURED` | JSON matching a schema. |
| `SCORE` | Numeric or ordinal score for items the app already created. |
| `CHOOSE` | Pick among ids the app supplies. |
| `CLASSIFY` | Label into a closed set. |
| `TOOL_CALLING` | Model invokes tools. Not required for V1 tasks below. |
| `VISION` | Image or frame input. Not required for V1 semantic tasks. |
| `LONG_CONTEXT` | Input larger than a short window. The app still chunks when the chosen model cannot. |

An adapter advertises the subset it implements. The router does not shim a missing capability by pretending `GENERATE_TEXT` is `SCORE`.

## Two roles

**GenerativeProvider** — implements `GENERATE_TEXT` and/or `GENERATE_STRUCTURED`. Used for normalization text, thread summaries, summaries.

**DecisionProvider** — implements `SCORE` and/or `CHOOSE`. Used to rank Reel candidates the deterministic miner already proposed. Jev-like services fit here if they do not generate the timeline.

One vendor may implement both. The task still declares which role it needs. A local llama.cpp adapter is a generative provider with whatever subset the runtime actually supports, recorded on the model definition.

## Modes

Defined in [PRODUCT_ARCHITECTURE.md](PRODUCT_ARCHITECTURE.md): private/offline, hybrid, best quality, custom.

Routing:

- Offline: no network call at all. A missing local model is `resource_missing`, not a download and not a cloud fallback. Semantic tasks with no local adapter are `skipped_no_provider`.
- Hybrid: local generative work by default; a configured decision provider may score; individual tasks may opt into cloud.
- Best quality: the user-selected frontier adapter may run the semantic tasks that list it as allowed.
- Custom: a map `task_id → provider_config_id` overrides the mode defaults.

Media stages are not in this map. They have no provider slot.

## Task contracts

Each task defines input schema, output schema, required capabilities, validation, and fallback. Validators run in the engine after the provider returns. Invalid output is a failed task, not a partially applied timeline.

### `transcript_normalization`

| | |
|---|---|
| Input | Segment id, raw text. No instruction to return timestamps. |
| Output | List of `{segment_id, clean_text}` patches. |
| Capabilities | `GENERATE_STRUCTURED`. `LONG_CONTEXT` optional; otherwise chunk as legacy did (~90 segments). |
| Validation | Every `segment_id` exists. Unknown ids dropped. `clean_text` is a string. Times copied from source segments only. Word links applied by the deterministic aligner, not the model. |
| Fallback | Keep raw text. Transcript remains usable. |

### `conversation_mapping`

| | |
|---|---|
| Input | Turns or segments as ids plus text. |
| Output | Threads whose members are turn ids or word ids. |
| Capabilities | `GENERATE_STRUCTURED`. |
| Validation | Ids exist. Time bounds derived from members. Threads with no valid ids discarded. |
| Fallback | No threads. Conversation workspace shows turns only. |

### `topic_extraction`

| | |
|---|---|
| Input | Thread or turn texts. |
| Output | Labels attached to existing thread ids. |
| Capabilities | `CLASSIFY` or `GENERATE_STRUCTURED`. |
| Validation | Closed label set if the product defines one; otherwise short strings with a length cap. |
| Fallback | Untitled threads. |

### `reel_candidate_generation`

| | |
|---|---|
| Input | Turns and thread ids. |
| Output | Candidates as word-id or turn-id spans plus a reason string. |
| Capabilities | `GENERATE_STRUCTURED`, or none when the heuristic miner runs. |
| Validation | Spans snap with the deterministic word snapper. Duration limits applied after snap. |
| Fallback | Heuristic miner only (legacy keyword windows). That path is local and does not need a provider. Current discovery does not persist a score or an aspect. |

### `reel_candidate_scoring`

| | |
|---|---|
| Input | Candidate ids and compact text. |
| Output | Score per candidate id. |
| Capabilities | `SCORE` or `CHOOSE`. |
| Validation | Unknown ids ignored. Scores stored with provider id. Missing scores do not delete candidates. |
| Fallback | Heuristic score only. This task is not part of V1 discovery. A candidate is valid with no score. |

### `final_reel_edit`

| | |
|---|---|
| Input | Candidate plus transcript revision by ids. |
| Output | Ordered word-id ranges. |
| Capabilities | `GENERATE_STRUCTURED`. |
| Validation | Same structural checks as today’s semantic plan validator (ids, order, duration, source span), then id expansion to microseconds. |
| Fallback | The candidate’s snapped span becomes the plan without a generative rewrite. |

### `summary_generation`

| | |
|---|---|
| Input | Thread or episode text by ids. |
| Output | Text plus optional chapter ids. |
| Capabilities | `GENERATE_TEXT` or `GENERATE_STRUCTURED`. |
| Validation | No timestamp fields accepted. |
| Fallback | Skip. Episode summary scripts in legacy are not on the V1 critical path. |

## Provenance

Every accepted model output stores provider id, model id, model version, prompt template hash, input artifact hashes, `execution` (`local` or `cloud`), and raw payload hash. The applied domain rows point at that `AnalysisRun`.

## Development adapter

A Cursor CLI adapter may exist so engineers can reproduce legacy semantic behavior during migration. It is not the default product provider, not assumed to be installed for end users, and not named by task code. Task code asks for `GENERATE_STRUCTURED`.

## What V1 does not build

- Tool-calling agent loops inside the editor.
- A vision model that overrides diarization (legacy visual verification may override a shot locally; that is a deterministic vision stage, not this provider layer).
- Automatic provider failover that sends a private project to cloud when the local model fails. Failover to cloud requires the active mode to allow cloud and the task’s fallback policy to say so.
