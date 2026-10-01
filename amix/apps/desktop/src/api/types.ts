/** Shapes returned by the Phase 4 engine. The session token is not one of them. */

export type EnginePhase = "STARTING" | "READY" | "FAILED" | "STOPPED";

export interface EngineStatus {
  generation: number;
  state: EnginePhase;
  message: string;
  host: string | null;
  port: number | null;
  version: string | null;
  project: SessionProject | null;
  notice: string | null;
}

/** Project session owned by this desktop process. The handle belongs to `generation`. */
export interface SessionProject {
  handle: string;
  project_id: string;
  name: string;
  read_only: boolean;
  schema_revision: string | null;
  path: string;
  generation: number;
}

export interface ProjectInfo {
  handle: string;
  project_id: string;
  name: string;
  read_only: boolean;
  schema_revision: string | null;
}

export type JobStatus =
  | "QUEUED"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCEL_REQUESTED"
  | "CANCELLED"
  | "INTERRUPTED";

export interface JobInfo {
  job_id: string;
  project_id: string;
  media_asset_id: string | null;
  kind: string;
  status: JobStatus;
  progress_bp: number;
  spec: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  cancel_requested: boolean;
  attempt: number;
  resumed_from_job_id: string | null;
  interrupt_reason: string | null;
}

export type SpeechModelState = "READY" | "MODEL_MISSING" | "INVALID_MODEL" | "RUNTIME_UNAVAILABLE";

export interface SpeechModelStatus {
  state: SpeechModelState;
  model_id: string | null;
  display_name: string | null;
  runtime: string | null;
  message: string;
}

export interface EngineFailure {
  code: string;
  message: string;
}

export interface MediaAsset {
  asset_id: string;
  role: string;
  display_name: string;
  location_kind: string;
  relative_path: string | null;
  external_path: string | null;
  byte_size: number | null;
  duration_us: number | null;
  width: number | null;
  height: number | null;
  fps_num: number | null;
  fps_den: number | null;
  container: string | null;
  container_start_us: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  sample_rate: number | null;
  audio_channels: number | null;
  channel_layout: string | null;
  rotation_degrees: number | null;
  probed_at: string | null;
  source_media_asset_id: string | null;
  proxy_state: string | null;
  proxy_asset_id: string | null;
  status: "present" | "missing";
}

export interface ActiveTranscript {
  active: boolean;
  transcript_id: string | null;
  analysis_run_id: string | null;
  media_asset_id: string | null;
  language: string | null;
  word_count: number | null;
}

export interface TranscriptWord {
  word_id: string;
  sequence: number;
  effective_text: string;
  machine_text: string;
  start_us: number;
  end_us: number;
  confidence: number | null;
  text_corrected: boolean;
  participant_id: string | null;
  participant_name: string | null;
}

export interface TranscriptWordPage {
  offset: number;
  limit: number;
  word_count: number;
  words: TranscriptWord[];
}

export interface Participant {
  participant_id: string;
  display_name: string;
}

export interface LayoutBindingRecord {
  binding_id: string;
  participant_id: string;
  start_us: number;
  end_us: number;
  x: number;
  y: number;
  w: number;
  h: number;
  coordinate_space: string;
}

export interface ClusterSample {
  start_us: number;
  end_us: number;
}

export interface ClusterSummary {
  cluster_key: string;
  segment_count: number;
  voiced_us: number;
  samples: ClusterSample[];
}

export interface SpeakerAnalysis {
  state: string;
  participant_count: number;
  transcript_run_id: string | null;
  diarization_run_id: string | null;
  assignment_run_id: string | null;
  assignment_compatible: boolean;
  turns_run_id: string | null;
  turns_match_assignment: boolean;
  source_present: boolean;
  clusters: ClusterSummary[];
  previous_map: Record<string, string | null> | null;
  profile_id: string;
  cluster_count: number;
  limitation: string;
}

export interface WordAtTime {
  found: boolean;
  word_id: string | null;
  sequence: number | null;
  start_us: number | null;
  end_us: number | null;
}

/** Safe playback view. The filesystem path is not included. */
export interface PreparedPlayback {
  playable: boolean;
  status: string;
  warning: string | null;
  message: string | null;
  source_media_asset_id: string;
  playback_media_asset_id: string | null;
  canonical_origin_us: number;
  playback_duration_us: number | null;
  source_duration_us: number | null;
  asset_url: string | null;
  request_id: number;
  byte_size: number | null;
  file_mtime_ns: number | null;
  stale: boolean;
}

export interface OverlapRegionView {
  start_us: number;
  end_us: number;
  duration_us: number;
  confidence: number;
  participant_ids: string[];
}

export interface OverlapState {
  run_id: string | null;
  stale: boolean;
  window_start_us: number | null;
  window_end_us: number | null;
  profile_id: string | null;
  regions: OverlapRegionView[];
}

export interface MulticamReadiness {
  turns_ready: boolean;
  overlap_ready: boolean;
  overlap_stale: boolean;
  layout_ready: boolean;
  plan_ready: boolean;
  plan_present: boolean;
  plan_stale: boolean;
  blocking_reason: string | null;
  vision_state: string;
  ffmpeg_ready: boolean;
  plan_start_us: number | null;
  plan_end_us: number | null;
}

export interface FullChoice {
  participant_id: string;
  display_name: string;
}

export interface ShotView {
  shot_id: string;
  start_us: number;
  end_us: number;
  presentation: string;
  participant_id: string | null;
  participant_name: string | null;
  reason: string;
  automatic_presentation: string;
  automatic_participant_id: string | null;
  automatic_participant_name: string | null;
  override_decision: string;
  locked: boolean;
  overridden: boolean;
  full_choices: FullChoice[];
}

export interface ShotPlanState {
  run_id: string | null;
  stale: boolean;
  start_us: number | null;
  end_us: number | null;
  shots: ShotView[];
}

export interface TimelineClip {
  clip_id: string;
  order_index: number;
  source_start_us: number;
  source_end_us: number;
  sequence_start_us: number | null;
}

export interface TimelineRange {
  source_start_us: number;
  source_end_us: number;
}

export interface TimelineCamera {
  shot_id: string;
  source_start_us: number;
  source_end_us: number;
  presentation: string;
  participant_name: string | null;
  locked: boolean;
}

export interface TimelineState {
  sequence_id: string | null;
  revision: number | null;
  fingerprint: string | null;
  source_start_us: number | null;
  source_end_us: number | null;
  duration_us: number | null;
  clips: TimelineClip[];
  removed: TimelineRange[];
  camera: TimelineCamera[];
  protected: TimelineRange[];
}

export interface ConversationThread {
  thread_id: string;
  order_index: number;
  first_turn_id: string;
  last_turn_id: string;
  first_word_id: string;
  last_word_id: string;
  title: string;
  summary: string;
  topic: string | null;
  start_us: number;
  end_us: number;
  duration_us: number;
  participant_names: string[];
}

export interface ConversationState {
  transcript_present: boolean;
  turns_ready: boolean;
  blocking_reason: string | null;
  provider_configured: boolean;
  provider_display_name: string | null;
  provider_model_id: string | null;
  provider_execution: string | null;
  capability_ready: boolean;
  offline_blocked: boolean;
  network_mode: string;
  map_present: boolean;
  map_stale: boolean;
  conversation_map_run_id: string | null;
  threads: ConversationThread[];
}

export interface ReelCandidate {
  candidate_id: string;
  order_index: number;
  conversation_thread_id: string;
  first_turn_id: string;
  last_turn_id: string;
  first_word_id: string;
  last_word_id: string;
  start_us: number;
  end_us: number;
  duration_us: number;
  title: string;
  summary: string;
  hook: string;
  thread_title: string | null;
  participant_names: string[];
}

export interface ReelClip {
  clip_id: string;
  order_index: number;
  source_start_us: number;
  source_end_us: number;
}

export interface ReelDraft {
  sequence_id: string;
  display_name: string;
  revision: number;
  source_start_us: number;
  source_end_us: number;
  duration_us: number;
  origin_candidate_id: string | null;
  clips: ReelClip[];
}

export interface ReelState {
  transcript_present: boolean;
  turns_ready: boolean;
  blocking_reason: string | null;
  provider_configured: boolean;
  capability_ready: boolean;
  offline_blocked: boolean;
  map_present: boolean;
  map_stale: boolean;
  discovery_present: boolean;
  discovery_stale: boolean;
  reel_discovery_run_id: string | null;
  candidates: ReelCandidate[];
  drafts: ReelDraft[];
}

export interface SequenceRenderReadiness {
  source_program_ready: boolean;
  multicam_ready: boolean;
  source_program_reason: string | null;
  multicam_reason: string | null;
  ffmpeg_ready: boolean;
}

export interface ExportRecord {
  job_id: string;
  filename: string;
  relative_path: string;
  width: number | null;
  height: number | null;
  aspect: string | null;
  preset_id: string | null;
  visual_treatment?: string | null;
  sequence_id?: string | null;
  created_at: string | null;
  status: string;
}

export interface CaptionCue {
  cue_id: string;
  order_index: number;
  first_word_id: string;
  last_word_id: string;
  source_start_us: number;
  source_end_us: number;
  sequence_start_us: number;
  sequence_end_us: number;
  generated_text: string;
  manual_text: string | null;
  effective_text: string;
}

export interface CaptionState {
  sequence_id: string;
  media_asset_id: string;
  purpose: string;
  status: "absent" | "ready" | "stale";
  track_id: string | null;
  revision: number | null;
  profile: string | null;
  transcript_analysis_run_id: string | null;
  effective_text_fingerprint: string | null;
  sequence_revision_at_generation: number | null;
  stale_reasons: string[];
  cues: CaptionCue[];
}

export interface CaptionExport {
  export_id: string;
  asset_id: string;
  relative_path: string | null;
  role: string | null;
  source_media_asset_id: string;
  sequence_id: string;
  sequence_purpose: string;
  sequence_revision: number;
  sequence_fingerprint: string;
  caption_track_id: string;
  caption_track_revision: number;
  transcript_analysis_run_id: string;
  effective_text_fingerprint: string;
  generation_profile: string;
  format: string;
  created_at: string;
}

export interface RuntimeResourceState {
  state: string;
  message: string;
  resource_id: string | null;
  display_name: string | null;
  runtime: string | null;
  device?: string | null;
  compute_type?: string | null;
  version?: string | null;
  identity?: string | null;
}

export interface ToolStatus {
  state: string;
  version: string | null;
  message: string;
}

export interface InstalledResource {
  resource_id: string;
  kind: string;
  display_name: string;
  version: string | null;
  ownership: string;
  origin: string;
  license_name: string | null;
  license_url: string | null;
  identity: string | null;
  runtime: string | null;
  status: string;
  selected: boolean;
}

export interface ProviderConfig {
  provider_id: string;
  display_name: string;
  placement: string;
  base_url: string;
  model_id: string;
  credential_ref: string | null;
  credential_configured: boolean;
  selected: boolean;
}

export interface SemanticStatus {
  configured: boolean;
  network_mode: string;
  execution: string | null;
  display_name: string | null;
  model_id: string | null;
  provider_id: string | null;
  capability_ready: boolean;
  offline_blocked: boolean;
  reachable: boolean | null;
}

export interface CatalogEntry {
  resource_id: string;
  kind: string;
  display_name: string;
  version: string | null;
  license_name: string | null;
  license_url: string | null;
}

export interface RuntimeStatus {
  restart_required: boolean;
  network_policy: string;
  speech: RuntimeResourceState;
  vision: RuntimeResourceState;
  semantic: SemanticStatus;
  ffmpeg: ToolStatus;
  ffprobe: ToolStatus;
  resources: InstalledResource[];
  providers: ProviderConfig[];
  catalog: CatalogEntry[];
}
