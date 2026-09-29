# Semantic AI runtime

AMIX calls a capability to perform a task. It does not call “the LLM” as one type, and task code does not name a vendor.

## Capabilities

`GENERATE_TEXT`, `GENERATE_STRUCTURED`, `SCORE`, `CHOOSE`, `CLASSIFY`, `TOOL_CALLING`, `VISION`, and `LONG_CONTEXT` are the capability names. A provider descriptor lists the subset it implements. Conversation mapping requires `GENERATE_STRUCTURED`. A missing capability is not filled in by pretending text generation is a score.

`SCORE`, `CHOOSE`, and `CLASSIFY` are reserved for a future decision provider. Jev is not implemented. A decision provider would rank candidates the application already created. It would not generate timestamps or a timeline.

## Providers

The descriptor carries provider id, display name, adapter kind, model id, capabilities, local or remote execution, and a hostname when one exists. It does not carry secrets.

Phase 14 has one protocol adapter: OpenAI-compatible chat completions. A loopback endpoint is the local provider. Any other host is remote. The application asks the registry for a descriptor. It does not branch on a vendor name.

Development configuration is environment-based:

| Variable | Meaning |
| --- | --- |
| `AMIX_AI_BASE_URL` | API root, including `/v1` when the server uses that prefix |
| `AMIX_AI_MODEL` | Model id sent to that endpoint |
| `AMIX_AI_PROVIDER_ID` | Optional descriptor id. Defaults to `openai-compatible` |
| `AMIX_AI_API_KEY` | Optional bearer token for development only |
| `AMIX_AI_NETWORK` | `offline` (default) or `development` |

The product does not start llama.cpp and does not download a model. Cursor CLI is not a runtime dependency.

## Offline

`offline` is the default. Before a socket is opened, the endpoint is parsed and accepted only when the host is loopback: `127.0.0.1`, `localhost`, or `::1`. A private LAN address is remote. A remote provider in offline mode fails with `offline_provider_forbidden` and no request is sent.

`development` may call a remote OpenAI-compatible endpoint. That mode is not a settings screen.

There is no semantic telemetry. Logs may include provider id, model id, task id, duration, and success or failure. They do not include the transcript, the API key, or the Authorization header.

## Secrets

API keys are read from the environment for development. They are not written to `project.db`, job specs, analysis provenance, localStorage, or the React tree. The React client cannot submit a base URL, an API key, a system prompt, or a raw provider payload. It submits the product task `map_conversation` and the profile id.

Before a user-facing cloud provider is enabled, credentials must come from Windows Credential Manager, macOS Keychain, or the architecture-approved OS credential store. This phase does not add that store.

## Tasks

A task has an input schema, an output schema, required capabilities, a versioned prompt, and a repair policy. Conversation mapping is `amix.conversation.map.v1`. The profile id and version are stored on the analysis run. A mutable prompt filename is not the authority.

Structured output is parsed as JSON and checked with a schema. Markdown wrapped around JSON is invalid. At most one repair request is sent, and the repair count is stored. A second failure fails the job. The previous active map stays active.

Requests use a connect timeout and a read timeout, and responses are size-limited. A provider cannot hang the engine forever. Cancellation between calls stops further calls. An in-flight HTTP call ends at its timeout, and cancellation is honored when it returns. A cancelled run does not publish a partial map.

The model has no tools, filesystem access, or network tools. Transcript text is sent as data, delimited from the task instructions.

## Limits

There is no cloud account UI, no key-storage UI, no model manager, no embedding index, and no conversation chat. A future Cursor adapter would still be asked for `GENERATE_STRUCTURED` and would be classified as remote.
