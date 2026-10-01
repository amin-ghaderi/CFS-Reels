# Semantic AI runtime

AMIX calls a capability to perform a task. It does not call “the LLM” as one type, and task code does not name a vendor.

## Capabilities

`GENERATE_TEXT`, `GENERATE_STRUCTURED`, `SCORE`, `CHOOSE`, `CLASSIFY`, `TOOL_CALLING`, `VISION`, and `LONG_CONTEXT` are the capability names. A provider descriptor lists the subset it implements. Conversation mapping requires `GENERATE_STRUCTURED`. A missing capability is not filled in by pretending text generation is a score.

`SCORE`, `CHOOSE`, and `CLASSIFY` are reserved for a future decision provider. Jev is not implemented. A decision provider would rank candidates the application already created. It would not generate timestamps or a timeline.

## Providers

The descriptor carries provider id, display name, adapter kind, model id, capabilities, local or remote execution, a hostname when one exists, and a structured-output transport mode. It does not carry secrets. The transport mode is `strict_json_schema`, `json_object_only`, or `prompt_only_structured`. It is not a product capability. The managed llama.cpp descriptor uses `strict_json_schema`. An external OpenAI-compatible provider uses `json_object_only`. Prompt-only omits `response_format`. An unrecognized mode does not send a guessed field.

Phase 14 has one protocol adapter: OpenAI-compatible chat completions. A loopback endpoint is the local provider. Any other host is remote. The application asks the registry for a descriptor. It does not branch on a vendor name.

The product path is application settings. See [SETTINGS_AND_RESOURCES.md](SETTINGS_AND_RESOURCES.md). A managed local model is a llama.cpp server and a GGUF file that AMIX starts on loopback. An external local provider is a loopback OpenAI-compatible server the user already runs. A remote provider stores its API key as an OS credential, not a database column. All three become the same provider descriptor. The managed descriptor advertises `GENERATE_STRUCTURED` only. Its identity is the local configuration, runtime kind and version, and the GGUF resource id and display name. The ephemeral port is not provenance.

Development overrides remain when they are set:

| Variable | Meaning |
| --- | --- |
| `AMIX_AI_BASE_URL` | API root, including `/v1` when the server uses that prefix. If this or `AMIX_AI_MODEL` is set, both are required. An incomplete pair does not fall through to the saved provider. |
| `AMIX_AI_MODEL` | Model id sent to that endpoint |
| `AMIX_AI_PROVIDER_ID` | Optional descriptor id. Defaults to `openai-compatible` |
| `AMIX_AI_API_KEY` | Bearer token for the environment override only |
| `AMIX_AI_NETWORK` | `offline`, `network_enabled`, or `development`. A set value that is not one of these is invalid and does not fall through. |

When `AMIX_AI_NETWORK` is unset, the saved policy is used. The saved policy is `offline` until the user chooses Network enabled. `development` is a development alias that permits a remote endpoint. The Settings screen offers only Offline and Network enabled.

AMIX can start a registered llama.cpp server for the managed local model. It does not download a model in this phase. The managed-download catalog stays empty until a source, checksum, and license are already verified. Cursor CLI is not a runtime dependency. A failed managed start does not switch to another provider.

## Offline

`offline` is the default. Before a socket is opened, the endpoint is parsed and accepted only when the host is loopback: `127.0.0.1`, `localhost`, or `::1`. A private LAN address is remote. A remote provider in offline mode fails with `offline_provider_forbidden` and no request is sent.

`network_enabled` and the development alias `development` may call a configured remote OpenAI-compatible endpoint. Entering a remote URL does not change the policy. Network enabled has to be saved explicitly.

There is no semantic telemetry. Logs may include provider id, model id, task id, duration, success or failure, numeric request diagnostics, and numeric inference counters when the server returns them. They do not include the transcript, the API key, or the Authorization header. Inference counters such as prompt tokens, generated tokens, and tokens per second are diagnostics. The application does not require a llama.cpp-specific metric.

## Secrets

A development API key is read from `AMIX_AI_API_KEY` only for an environment override. A saved remote provider uses a credential reference. The desktop stores the secret in the OS credential store and pushes it into engine memory for the request. It is not written to `project.sqlite`, `app.sqlite`, job specs, analysis provenance, localStorage, or logs. React can see "API key configured" or "No API key". It cannot read the stored secret. The React client cannot submit a model path or an executable path on a job. It submits the product task `map_conversation` and the profile id. Provider base URL and model id are saved through Settings, not through a project.

Saved remote credentials use Windows Credential Manager or macOS Keychain. The managed local model does not use an API key.

## Tasks

A task has an input schema, an output schema, required capabilities, a versioned prompt, and a repair policy. Conversation mapping is `amix.conversation.map.v1`. The profile id and version are stored on the analysis run. A mutable prompt filename is not the authority.

Structured output is parsed as JSON and checked with the application schema. A constrained `response_format` is an output aid. The application still parses the body, checks ids, ranges, conversation coverage, and reel anchors. Markdown wrapped around JSON is invalid. The parser does not strip fences. At most one repair request is sent, and the repair count is stored. A second failure fails the job. The previous active map stays active. When a draft parsed, the repair sends that draft, the error, and the anchor ids. It does not resend the transcript.

Requests use a connect timeout and a read timeout, and responses are size-limited. A remote provider read timeout is 60 seconds. A loopback inference timeout is 120 seconds. Loading the managed local model uses a separate 180 second startup timeout. A provider cannot hang the engine forever. Cancellation between calls stops further calls. An in-flight HTTP call ends at its timeout, and cancellation is honored when it returns. A cancelled run does not publish a partial map.

The total semantic request stays under 4096 estimated tokens: instructions and schema, plus at most 3072 estimated tokens of semantic data, plus bounded context. The configured local context window may be 16384. The request budget does not try to fill it. A request over the profile limit fails with `semantic_context_too_large` before it is sent.

The model has no tools, filesystem access, or network tools. Transcript text is sent as data, delimited from the task instructions.

## Limits

There is no embedding index and no conversation chat. Jev, ranking, and tool calling are not implemented. A future Cursor adapter would still be asked for `GENERATE_STRUCTURED` and would be classified as remote.
