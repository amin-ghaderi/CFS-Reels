import type { EngineFailure } from "./types";

const MESSAGES: Record<string, string> = {
  unauthorized: "The desktop session could not authenticate with the engine.",
  project_already_open: "This project is already open in AMIX.",
  project_already_locked: "This project is open in another AMIX window.",
  project_close_timeout: "A background job did not stop in time. The project stays open.",
  unsupported_job_kind: "That job is not available.",
  unknown_project_handle: "This project session is no longer valid. Open the project again.",
  project_not_found: "That folder does not contain an AMIX project.",
  project_database_invalid: "That folder is not a usable AMIX project.",
  schema_mismatch: "This project database cannot be opened in the requested mode.",
  invalid_project_path: "The selected folder could not be used.",
  invalid_request: "That request was not valid.",
  engine_shutting_down: "The engine is shutting down.",
  project_read_only: "This project is open read-only.",
  media_missing: "A media file for this project is missing.",
  unknown_job: "That job is no longer available.",
  invalid_job_state: "That job cannot be changed in its current state.",
  job_spec_rejected: "The job request was rejected.",
  internal_error: "The engine hit an unexpected error.",
  handler_failed: "The job did not finish.",
  blank_name: "Enter a project name.",
  invalid_name: "Use a project name without slashes.",
  invalid_parent: "Choose a folder for the new project.",
  unknown_media_asset: "That media file is no longer in this project.",
  invalid_media_path: "Choose an existing media file.",
  invalid_media_role: "That media role is not recognized.",
  no_active_transcript: "No transcript is available for this media yet.",
  unknown_word: "That word is no longer in the active transcript.",
  invalid_word_text: "Enter the corrected word.",
  invalid_word_page: "That transcript page is out of range.",
  media_tool_missing: "FFmpeg tools are not available.",
  ffmpeg_unavailable: "FFmpeg is not available.",
  audio_stream_unavailable: "This media has no audio to transcribe.",
  worker_failed: "Transcription did not finish.",
  media_probe_failed: "The media file could not be analyzed.",
  media_proxy_failed: "The proxy could not be generated.",
  invalid_proxy_profile: "That proxy profile is not available.",
  invalid_proxy_source: "A proxy can be generated for source media.",
  proxy_requires_video: "This media has no video to proxy.",
  speech_model_missing: "Speech model not installed.",
  invalid_speech_model: "The configured speech model cannot be used.",
  speech_runtime_unavailable: "The speech runtime is not available.",
  media_has_no_audio: "This media has no audio.",
  invalid_language: "That language code is not supported. Use Auto or a Whisper language code.",
  invalid_transcription_profile: "That transcription profile is not available.",
  transcription_requires_source: "Transcription uses the original source media.",
  speech_transcription_failed: "Transcription did not finish.",
  invalid_participant_name: "Enter a participant name.",
  unknown_participant: "That participant is not in this project.",
  invalid_layout: "That layout rectangle is not valid.",
  unknown_layout: "That layout is not in this project.",
  layout_requires_probe: "Probe this media before detecting people.",
  layout_requires_source: "Layout uses the original source media.",
  layout_detect_failed: "A frame could not be read from this media.",
  invalid_diarization_profile: "That speaker-analysis profile is not available.",
  diarization_requires_source: "Speaker analysis uses the original source media.",
  diarization_failed: "Speaker analysis did not finish.",
  incomplete_cluster_map: "Map every cluster, including Unknown.",
  unknown_diarization: "That speaker analysis is not available.",
  vision_model_missing: "Face model not installed.",
  invalid_vision_model: "The configured face model cannot be used.",
  vision_runtime_unavailable: "The vision runtime is not available.",
  insufficient_layout: "At least two participant regions are required.",
  overlap_requires_source: "Overlap analysis uses the original source media.",
  overlap_requires_probe: "Probe this media before overlap analysis.",
  overlap_requires_video: "This media has no video to analyze.",
  invalid_analysis_window: "The analysis window is not valid.",
  invalid_overlap_profile: "That overlap profile is not available.",
  overlap_failed: "Overlap analysis did not finish.",
  overlap_stale: "Overlap analysis is out of date for the current layout.",
  overlap_required: "Overlap analysis is not ready for this media.",
  turns_required: "Speaker turns are not ready for this media.",
  transcript_required: "No transcript is available for this media yet.",
  analysis_not_covering: "Turns and overlap do not cover a shared plan range.",
  invalid_plan_profile: "That multicam profile is not available.",
  plan_required: "Build a shot plan before rendering.",
  plan_stale: "The shot plan is out of date.",
  plan_changed: "That shot plan is no longer the active plan.",
  protected_locked: "A protected shot stays on the full program frame.",
  unknown_shot: "That shot is not in this plan.",
  layout_not_covering: "That participant does not cover this whole shot.",
  invalid_render_preset: "That output format is not available.",
  invalid_override: "Choose automatic, wide, or one participant.",
  framing_failed: "The picture could not be framed for this output.",
  region_too_small: "The participant region cannot fill this output.",
  empty_plan: "This plan has no shots to render.",
  render_requires_source: "Rendering uses the original source media.",
  render_requires_probe: "Probe this media before rendering.",
  render_failed: "The render did not finish.",
  invalid_sequence: "The sequence source range is empty.",
  invalid_clip: "A clip range is empty.",
  clip_out_of_range: "A clip is outside the sequence source range.",
  clip_overlap: "Clips must stay in source order without overlap.",
  unknown_clip: "That clip is not in this sequence.",
  unknown_sequence: "That sequence is not in this project.",
  split_out_of_range: "Split inside the selected clip.",
  sequence_changed: "That edit changed before rendering.",
  semantic_provider_missing: "No semantic provider is configured.",
  semantic_provider_unavailable: "The semantic provider could not be reached.",
  offline_provider_forbidden: "Offline mode does not send this project to a remote provider.",
  semantic_timeout: "The semantic provider took too long.",
  semantic_invalid_output: "The semantic result could not be validated.",
  conversation_map_required: "Map the conversation before discovering reels.",
  conversation_map_stale: "The conversation map is out of date.",
  unknown_candidate: "That reel candidate is not in this project.",
  semantic_context_too_large: "This request is larger than the model context.",
  semantic_request_failed: "The semantic provider rejected the request.",
  semantic_capability_missing: "This provider cannot produce structured output.",
  local_model_failed: "The local model failed to start.",
  local_model_missing: "Choose a llama.cpp runtime and a GGUF model.",
  local_model_stopped: "Local AI was stopped.",
  invalid_llama_runtime: "This program is not a usable llama.cpp server.",
  invalid_gguf_model: "This file is not a GGUF model.",
  invalid_local_model: "That local model setting is not valid.",
  invalid_semantic_profile: "That semantic profile is not available.",
  unknown_caption_cue: "That caption is no longer on the current track.",
  captions_missing: "Generate captions before exporting.",
  captions_stale: "Regenerate captions before exporting. Manual caption edits on the old track may not carry over.",
  invalid_caption_text: "Caption text cannot be blank.",
  invalid_caption_format: "Choose SRT or WebVTT.",
  invalid_caption_export: "The subtitle file could not be stored in the project.",
  settings_unavailable: "Application settings are not available.",
  unknown_resource: "That resource is not installed.",
  resource_in_use: "This resource is in use. Wait for the current job to finish.",
  confirmation_required: "Confirm removal of an AMIX-managed resource.",
  invalid_media_tools: "Choose a folder that contains both FFmpeg and FFprobe.",
  invalid_provider: "That provider configuration is not valid.",
  invalid_credential: "The credential could not be stored.",
  invalid_network_policy: "That network policy is not available.",
  download_failed: "The resource download did not finish.",
  unknown_route: "That request was not found.",
};

export function mapEngineFailure(status: number, body: string): EngineFailure {
  const code = readCode(body);
  const message = MESSAGES[code] ?? "The engine could not complete that action.";
  return { code: code || `http_${status}`, message };
}

function readCode(body: string): string {
  try {
    const parsed = JSON.parse(body) as { error?: { code?: unknown } };
    const code = parsed.error?.code;
    if (typeof code === "string" && /^[a-z0-9_]+$/.test(code)) {
      return code;
    }
  } catch {
    return "";
  }
  return "";
}

/** User-facing job text. Raw engine exception text is not part of this sentence. */
export function asFailure(error: unknown): EngineFailure {
  if (typeof error === "string" && error.trim() && !/authorization|bearer\s+/i.test(error)) {
    return { code: "desktop_error", message: error };
  }
  if (error && typeof error === "object" && "code" in error && "message" in error) {
    const failure = error as EngineFailure;
    if (typeof failure.code === "string" && typeof failure.message === "string") {
      return failure;
    }
  }
  return { code: "desktop_error", message: "The desktop could not complete that action." };
}

export function jobProblemMessage(code: string | null): string {
  if (code && MESSAGES[code]) {
    return MESSAGES[code];
  }
  return "The job did not finish.";
}
