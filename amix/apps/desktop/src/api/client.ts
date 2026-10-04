import { invoke } from "@tauri-apps/api/core";

import type { RecentProject } from "../recent/recent";
import { mapEngineFailure } from "./errors";
import { JOBS_CHANGED_EVENT } from "./jobs";
import type {
  ActiveTranscript,
  EngineStatus,
  JobInfo,
  MediaAsset,
  ProjectInfo,
  TranscriptWord,
  TranscriptWordPage,
  WordAtTime,
  LayoutBindingRecord,
  Participant,
  PreparedPlayback,
  SpeakerAnalysis,
  SpeechModelStatus,
  MulticamReadiness,
  OverlapState,
  ShotPlanState,
  ConversationState,
  ReelState,
  SequenceRenderReadiness,
  ExportRecord,
  TimelineState,
  CaptionExport,
  CaptionState,
  RuntimeStatus,
  SemanticStatus,
} from "./types";

interface RawResponse {
  status: number;
  body: string;
}

export async function desktopSession(): Promise<EngineStatus> {
  return invoke<EngineStatus>("desktop_session_snapshot");
}

export async function engineStatus(): Promise<EngineStatus> {
  return desktopSession();
}

export async function engineRetry(): Promise<EngineStatus> {
  return invoke<EngineStatus>("engine_retry");
}

export async function joinProjectPath(parent: string, name: string): Promise<string> {
  return invoke<string>("join_project_path", { parent, name });
}

export async function health(): Promise<{ status: string; service: string; version: string }> {
  return request("GET", "/v1/health");
}

export async function speechModelStatus(): Promise<SpeechModelStatus> {
  return request("GET", "/v1/runtime/speech-model");
}

export async function createProject(path: string, name: string): Promise<ProjectInfo> {
  return request("POST", "/v1/projects/create", { path, name });
}

export async function openProject(path: string): Promise<ProjectInfo> {
  return request("POST", "/v1/projects/open", { path, read_only: false });
}

export async function listRecentProjects(): Promise<RecentProject[]> {
  const body = await request<{ projects: RecentProject[] }>("GET", "/v1/runtime/recent-projects");
  return body.projects;
}

export async function removeRecentProject(projectId: string): Promise<void> {
  await request("POST", `/v1/runtime/recent-projects/${projectId}/remove`);
}

export async function locateRecentProject(projectId: string, path: string): Promise<RecentProject> {
  return request("POST", `/v1/runtime/recent-projects/${projectId}/locate`, { path });
}

export async function recentThumbnail(projectId: string): Promise<string | null> {
  try {
    const body = await request<{ data_base64: string }>("GET", `/v1/runtime/recent-projects/${projectId}/thumbnail`);
    return body.data_base64;
  } catch {
    return null;
  }
}

export async function getProject(handle: string): Promise<ProjectInfo> {
  return request("GET", `/v1/projects/${handle}`);
}

export async function closeProject(handle: string): Promise<void> {
  await request("POST", `/v1/projects/${handle}/close`);
}

export async function createJob(
  handle: string,
  kind: string,
  options?: { mediaAssetId?: string; spec?: Record<string, unknown> },
): Promise<JobInfo> {
  const job = await request<JobInfo>("POST", `/v1/projects/${handle}/jobs`, {
    kind,
    spec: options?.spec ?? {},
    media_asset_id: options?.mediaAssetId ?? null,
  });
  window.dispatchEvent(new Event(JOBS_CHANGED_EVENT));
  return job;
}

export async function listJobs(handle: string): Promise<JobInfo[]> {
  return request("GET", `/v1/projects/${handle}/jobs`);
}

export async function getJob(handle: string, jobId: string): Promise<JobInfo> {
  return request("GET", `/v1/projects/${handle}/jobs/${jobId}`);
}

export async function cancelJob(handle: string, jobId: string): Promise<JobInfo> {
  return request("POST", `/v1/projects/${handle}/jobs/${jobId}/cancel`);
}

export async function retryJob(handle: string, jobId: string): Promise<JobInfo> {
  return request("POST", `/v1/projects/${handle}/jobs/${jobId}/retry`);
}

export async function listMedia(handle: string): Promise<MediaAsset[]> {
  return request("GET", `/v1/projects/${handle}/media`);
}

export async function linkMedia(handle: string, path: string, role = "master"): Promise<MediaAsset> {
  const asset = await request<MediaAsset>("POST", `/v1/projects/${handle}/media`, { path, role });
  window.dispatchEvent(new Event(JOBS_CHANGED_EVENT));
  return asset;
}

export async function relinkMedia(handle: string, assetId: string, path: string): Promise<MediaAsset> {
  const asset = await request<MediaAsset>("POST", `/v1/projects/${handle}/media/${assetId}/relink`, { path });
  window.dispatchEvent(new Event(JOBS_CHANGED_EVENT));
  return asset;
}

export async function activeTranscript(handle: string, assetId: string): Promise<ActiveTranscript> {
  return request("GET", `/v1/projects/${handle}/media/${assetId}/transcript`);
}

export async function transcriptWords(
  handle: string,
  assetId: string,
  offset: number,
  limit: number,
): Promise<TranscriptWordPage> {
  return request("GET", `/v1/projects/${handle}/media/${assetId}/transcript/words/${offset}/${limit}`);
}

export async function correctWordText(
  handle: string,
  assetId: string,
  wordId: string,
  text: string,
): Promise<TranscriptWord> {
  return request("POST", `/v1/projects/${handle}/media/${assetId}/words/${wordId}/text`, { text });
}

export async function clearWordText(handle: string, assetId: string, wordId: string): Promise<TranscriptWord> {
  return request("POST", `/v1/projects/${handle}/media/${assetId}/words/${wordId}/text/clear`);
}

export async function wordAtTime(handle: string, assetId: string, timeUs: number): Promise<WordAtTime> {
  return request("GET", `/v1/projects/${handle}/media/${assetId}/transcript/word-at/${timeUs}`);
}

export async function listParticipants(handle: string): Promise<Participant[]> {
  return request("GET", `/v1/projects/${handle}/participants`);
}

export async function createParticipant(handle: string, displayName: string): Promise<Participant> {
  return request("POST", `/v1/projects/${handle}/participants`, { display_name: displayName });
}

export async function renameParticipant(handle: string, participantId: string, displayName: string): Promise<Participant> {
  return request("POST", `/v1/projects/${handle}/participants/${participantId}/rename`, { display_name: displayName });
}

export async function listLayout(handle: string, assetId: string): Promise<LayoutBindingRecord[]> {
  return request("GET", `/v1/projects/${handle}/media/${assetId}/layout`);
}

export async function addLayout(
  handle: string,
  assetId: string,
  body: {
    participant_id: string;
    start_us: number;
    end_us: number;
    x: number;
    y: number;
    w: number;
    h: number;
    binding_id?: string | null;
  },
): Promise<LayoutBindingRecord> {
  return request("POST", `/v1/projects/${handle}/media/${assetId}/layout`, body);
}

export async function detectLayoutCandidates(
  handle: string,
  assetId: string,
  timeUs: number | null,
): Promise<{ picture_width: number; picture_height: number; candidates: { x: number; y: number; w: number; h: number }[] }> {
  return request("POST", `/v1/projects/${handle}/media/${assetId}/layout-candidates`, {
    time_us: timeUs,
  });
}

export async function speakerAnalysis(handle: string, assetId: string): Promise<SpeakerAnalysis> {
  return request("GET", `/v1/projects/${handle}/media/${assetId}/speaker-analysis`);
}

export async function applySpeakerMap(
  handle: string,
  assetId: string,
  diarizationRunId: string,
  mappings: { cluster_key: string; participant_id: string | null }[],
): Promise<{ assignment_run_id: string; turns_run_id: string; state: string }> {
  return request("POST", `/v1/projects/${handle}/media/${assetId}/speaker-map`, {
    diarization_run_id: diarizationRunId,
    mappings,
  });
}

export function overlapState(handle: string, assetId: string): Promise<OverlapState> {
  return request("GET", `/v1/projects/${handle}/media/${assetId}/overlap`);
}

export function multicamReadiness(handle: string, assetId: string): Promise<MulticamReadiness> {
  return request("GET", `/v1/projects/${handle}/media/${assetId}/multicam`);
}

export function shotPlanState(handle: string, assetId: string): Promise<ShotPlanState> {
  return request("GET", `/v1/projects/${handle}/media/${assetId}/shot-plan`);
}

export function saveShotOverride(
  handle: string,
  assetId: string,
  body: { shot_plan_run_id: string; shot_id: string; decision: string; participant_id?: string | null },
): Promise<ShotPlanState> {
  return request("POST", `/v1/projects/${handle}/media/${assetId}/shot-overrides`, body);
}

export function listExports(handle: string, assetId: string, sequenceId?: string): Promise<ExportRecord[]> {
  const query = sequenceId ? `?sequence_id=${encodeURIComponent(sequenceId)}` : "";
  return request("GET", `/v1/projects/${handle}/media/${assetId}/exports${query}`);
}

export function sequenceRenderReadiness(handle: string, assetId: string, sequenceId: string): Promise<SequenceRenderReadiness> {
  return request("GET", `/v1/projects/${handle}/media/${assetId}/sequences/${sequenceId}/render-readiness`);
}

export function timelineState(handle: string, assetId: string): Promise<TimelineState> {
  return request("GET", `/v1/projects/${handle}/media/${assetId}/timeline`);
}

export function createEdit(handle: string, assetId: string): Promise<TimelineState> {
  return request("POST", `/v1/projects/${handle}/media/${assetId}/sequence`);
}

export function splitEdit(handle: string, assetId: string, sequenceId: string, clipId: string, sourceTimeUs: number): Promise<TimelineState> {
  return request("POST", `/v1/projects/${handle}/media/${assetId}/sequence/split`, {
    sequence_id: sequenceId,
    clip_id: clipId,
    source_time_us: sourceTimeUs,
  });
}

export function removeEditClip(handle: string, assetId: string, sequenceId: string, clipId: string): Promise<TimelineState> {
  return request("POST", `/v1/projects/${handle}/media/${assetId}/sequence/remove`, {
    sequence_id: sequenceId,
    clip_id: clipId,
  });
}

export function resetEdit(handle: string, assetId: string, sequenceId: string): Promise<TimelineState> {
  return request("POST", `/v1/projects/${handle}/media/${assetId}/sequence/reset`, {
    sequence_id: sequenceId,
  });
}

export function reelState(handle: string, assetId: string): Promise<ReelState> {
  return request("GET", `/v1/projects/${handle}/media/${assetId}/reels`);
}

export function createReelDraft(handle: string, assetId: string, candidateId: string): Promise<ReelState> {
  return request("POST", `/v1/projects/${handle}/media/${assetId}/reel-drafts`, { candidate_id: candidateId });
}

export function conversationState(handle: string, assetId: string): Promise<ConversationState> {
  return request("GET", `/v1/projects/${handle}/media/${assetId}/conversation`);
}

export function checkSemanticProvider(handle: string): Promise<unknown> {
  return request("POST", `/v1/projects/${handle}/semantic/provider/check`);
}

export function captionState(handle: string, sequenceId: string): Promise<CaptionState> {
  return request("GET", `/v1/projects/${handle}/sequences/${sequenceId}/captions`);
}

export function generateCaptions(handle: string, sequenceId: string): Promise<CaptionState> {
  return request("POST", `/v1/projects/${handle}/sequences/${sequenceId}/captions`);
}

export function editCaptionCue(handle: string, sequenceId: string, cueId: string, text: string): Promise<CaptionState> {
  return request("POST", `/v1/projects/${handle}/sequences/${sequenceId}/captions/cues/${cueId}/text`, { text });
}

export function resetCaptionCue(handle: string, sequenceId: string, cueId: string): Promise<CaptionState> {
  return request("POST", `/v1/projects/${handle}/sequences/${sequenceId}/captions/cues/${cueId}/reset`);
}

export function exportCaptions(handle: string, sequenceId: string, format: "srt" | "vtt"): Promise<CaptionExport> {
  return request("POST", `/v1/projects/${handle}/sequences/${sequenceId}/captions/export`, { format });
}

export function preparePlayback(sourceMediaAssetId: string, requestId: number): Promise<PreparedPlayback> {
  return invoke<PreparedPlayback>("prepare_playback", { sourceMediaAssetId, requestId });
}

export function releasePlayback(requestId: number): Promise<void> {
  return invoke("release_playback", { requestId });
}

export function runtimeStatus(): Promise<RuntimeStatus> {
  return request("GET", "/v1/runtime/status");
}

export function importSpeechModel(path: string, displayName: string): Promise<{ resource_id: string }> {
  return request("POST", "/v1/runtime/speech/import", { path, display_name: displayName });
}

export function selectSpeechModel(resourceId: string): Promise<void> {
  return request("POST", "/v1/runtime/speech/select", { resource_id: resourceId });
}

export function importVisionModel(path: string, displayName: string): Promise<{ resource_id: string }> {
  return request("POST", "/v1/runtime/vision/import", { path, display_name: displayName });
}

export function selectVisionModel(resourceId: string): Promise<void> {
  return request("POST", "/v1/runtime/vision/select", { resource_id: resourceId });
}

export function removeResource(resourceId: string, confirm: boolean): Promise<void> {
  return request("POST", `/v1/runtime/resources/${resourceId}/remove`, { confirm });
}

export function saveNetworkPolicy(policy: "offline" | "network_enabled"): Promise<void> {
  return request("POST", "/v1/runtime/network", { policy });
}

export function saveMediaTools(directory: string): Promise<void> {
  return request("POST", "/v1/runtime/tools", { directory });
}

export function saveProvider(body: {
  display_name: string;
  placement: "local" | "remote";
  base_url: string;
  model_id: string;
  provider_id?: string;
}): Promise<{ provider_id: string; credential_ref: string | null }> {
  return request("POST", "/v1/runtime/providers", body);
}

export function selectProvider(providerId: string): Promise<void> {
  return request("POST", `/v1/runtime/providers/${providerId}/select`);
}

export function removeProvider(providerId: string): Promise<void> {
  return request("POST", `/v1/runtime/providers/${providerId}/remove`);
}

export function testProvider(): Promise<SemanticStatus> {
  return request("POST", "/v1/runtime/providers/test");
}

export function importLlamaRuntime(path: string, displayName: string): Promise<{ resource_id: string }> {
  return request("POST", "/v1/runtime/llama/import", { path, display_name: displayName });
}

export function importGgufModel(path: string, displayName: string): Promise<{ resource_id: string }> {
  return request("POST", "/v1/runtime/gguf/import", { path, display_name: displayName });
}

export function selectInstalledResource(resourceId: string): Promise<void> {
  return request("POST", "/v1/runtime/resources/select", { resource_id: resourceId });
}

export function useManagedLocalAi(): Promise<void> {
  return request("POST", "/v1/runtime/local-ai/use", { source: "managed_local" });
}

export function startLocalAi(): Promise<void> {
  return request("POST", "/v1/runtime/local-ai/start");
}

export function stopLocalAi(): Promise<void> {
  return request("POST", "/v1/runtime/local-ai/stop");
}

export function saveLocalLimits(contextSize: number | null, threads: number | null): Promise<void> {
  return request("POST", "/v1/runtime/local-ai/limits", { context_size: contextSize, threads });
}

export function setProviderCredential(credentialRef: string, secret: string): Promise<{ configured: boolean }> {
  return invoke("set_provider_credential", { request: { credentialRef, secret } });
}

export function removeProviderCredential(credentialRef: string): Promise<{ configured: boolean }> {
  return invoke("remove_provider_credential", { request: { credentialRef } });
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const response = await invoke<RawResponse>("engine_request", {
    method,
    path,
    body: body === undefined ? null : JSON.stringify(body),
  });
  if (response.status >= 400) {
    throw mapEngineFailure(response.status, response.body);
  }
  if (!response.body) {
    return undefined as T;
  }
  return JSON.parse(response.body) as T;
}
