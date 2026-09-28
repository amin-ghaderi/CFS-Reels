import { invoke } from "@tauri-apps/api/core";

import { mapEngineFailure } from "./errors";
import type { EngineStatus, JobInfo, ProjectInfo } from "./types";

interface RawResponse {
  status: number;
  body: string;
}

export async function engineStatus(): Promise<EngineStatus> {
  return invoke<EngineStatus>("engine_status");
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
