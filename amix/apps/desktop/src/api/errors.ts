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
