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

export interface EngineFailure {
  code: string;
  message: string;
}
