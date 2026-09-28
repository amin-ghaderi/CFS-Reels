import { invoke } from "@tauri-apps/api/core";

import { mapEngineFailure } from "./errors";
import type {
  ActiveTranscript,
  EngineStatus,
  JobInfo,
  MediaAsset,
  ProjectInfo,
  TranscriptWord,
  TranscriptWordPage,
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

export async function createProject(path: string, name: string): Promise<ProjectInfo> {
  return request("POST", "/v1/projects/create", { path, name });
}

export async function openProject(path: string): Promise<ProjectInfo> {
  return request("POST", "/v1/projects/open", { path, read_only: false });
}

export async function getProject(handle: string): Promise<ProjectInfo> {
  return request("GET", `/v1/projects/${handle}`);
}

export async function closeProject(handle: string): Promise<void> {
  await request("POST", `/v1/projects/${handle}/close`);
}

export async function createJob(handle: string, kind: string): Promise<JobInfo> {
  return request("POST", `/v1/projects/${handle}/jobs`, { kind, spec: {} });
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
  return request("POST", `/v1/projects/${handle}/media`, { path, role });
}

export async function relinkMedia(handle: string, assetId: string, path: string): Promise<MediaAsset> {
  return request("POST", `/v1/projects/${handle}/media/${assetId}/relink`, { path });
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
