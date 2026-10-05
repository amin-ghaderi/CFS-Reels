import { useEffect, useRef, useState } from "react";

import { cancelJob, createJob, listJobs, retryJob } from "../api/client";
import { asFailure, jobProblemMessage } from "../api/errors";
import { semanticTimeoutDetail, semanticTimeoutSummary } from "../conversation/conversation";
import { canCancel, canRetry, isTerminal, JOBS_CHANGED_EVENT, jobStatusLabel, jobTitle, orderJobs, progressPercent } from "../api/jobs";
import type { EngineFailure, JobInfo, ProjectInfo } from "../api/types";
import { missingCount } from "../media/present";
import { useProjectData } from "../project/ProjectData";

const POLL_MS = 1000;
const BACKOFF_MS = 2000;

export function ActivityBar({
  project,
  onNotice,
}: {
  project: ProjectInfo;
  onNotice: (notice: EngineFailure | null) => void;
}) {
  const media = useProjectData();
  const [jobs, setJobs] = useState<JobInfo[]>([]);
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState(0);
  const ordered = orderJobs(jobs);
  const active = jobs.filter((job) => !isTerminal(job.status)).length;
  const mediaJobs = useRef("");
  const failed = jobs.filter((job) => job.status === "FAILED").length;
  const missing = missingCount(media.assets);
  const summary = active > 0 ? `${active} running` : failed > 0 ? `${failed} failed` : "No active job";

  useEffect(() => {
    const wake = () => setToken((value) => value + 1);
    window.addEventListener(JOBS_CHANGED_EVENT, wake);
    return () => window.removeEventListener(JOBS_CHANGED_EVENT, wake);
  }, []);

  useEffect(() => {
    let stop = false;
    let timer = 0;
    const tick = async (delay: number) => {
      try {
        const next = await listJobs(project.handle);
        if (stop) {
          return;
        }
        setJobs(next);
        if (next.some((job) => !isTerminal(job.status))) {
          timer = window.setTimeout(() => void tick(POLL_MS), delay);
        }
      } catch (error) {
        if (!stop) {
          onNotice(asFailure(error));
          timer = window.setTimeout(() => void tick(BACKOFF_MS), BACKOFF_MS);
        }
      }
    };
    void tick(POLL_MS);
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [project.handle, token]);

  const mediaSignature = jobs
    .filter((job) => job.kind === "media_probe" || job.kind === "generate_proxy")
    .map((job) => `${job.job_id}:${job.status}`)
    .join("|");

  useEffect(() => {
    if (mediaSignature && mediaSignature !== mediaJobs.current) {
      mediaJobs.current = mediaSignature;
      void media.refresh();
    }
  }, [mediaSignature, media]);

  useEffect(() => {
    if (active > 0) {
      setOpen(true);
    }
  }, [active]);

  async function runIntegrity() {
    onNotice(null);
    try {
      await createJob(project.handle, "project_integrity_check");
      setOpen(true);
      setToken((value) => value + 1);
    } catch (error) {
      onNotice(asFailure(error));
    }
  }

  async function onCancel(jobId: string) {
    try {
      await cancelJob(project.handle, jobId);
      setToken((value) => value + 1);
    } catch (error) {
      onNotice(asFailure(error));
    }
  }

  async function onRetry(jobId: string) {
    try {
      await retryJob(project.handle, jobId);
      setOpen(true);
      setToken((value) => value + 1);
    } catch (error) {
      onNotice(asFailure(error));
    }
  }

  return (
    <>
      {open ? (
        <section className="activity" aria-label="Activity">
          <div className="toolbar">
            <h2>Activity</h2>
            <button type="button" onClick={() => void runIntegrity()} disabled={project.read_only}>
              Check project
            </button>
            <button type="button" onClick={() => setOpen(false)}>
              Hide
            </button>
          </div>
          {ordered.length === 0 ? <p className="muted">No jobs yet.</p> : null}
          <ul className="job-list">
            {ordered.map((job) => (
              <li key={job.job_id} className="job">
                <div className="job-row">
                  <strong>{jobTitle(job.kind, job.spec)}</strong>
                  <span>{jobStatusLabel(job.status)}</span>
                </div>
                {job.progress_bp > 0 ? (
                  <div className="meter" aria-hidden="true">
                    <span style={{ width: `${progressPercent(job.progress_bp)}%` }} />
                  </div>
                ) : null}
                <p className="muted numeric">
                  Attempt {job.attempt}
                  {job.progress_bp > 0 ? ` · ${progressPercent(job.progress_bp)}%` : job.status === "RUNNING" ? " · Working" : ""}
                </p>
                {job.error_code || job.error_message ? (
                  <p>{job.error_code === "semantic_timeout" ? semanticTimeoutSummary(job.error_message) : jobProblemMessage(job.error_code)}</p>
                ) : null}
                {job.error_code === "semantic_timeout" && semanticTimeoutDetail(job.error_message) ? (
                  <details>
                    <summary>Details</summary>
                    <div>{semanticTimeoutDetail(job.error_message)}</div>
                  </details>
                ) : null}
                {import.meta.env.DEV && job.error_message && job.error_code !== "semantic_timeout" ? (
                  <details>
                    <summary>Details</summary>
                    <div>{job.error_message}</div>
                  </details>
                ) : null}
                {canCancel(job.status) || canRetry(job.status) ? (
                  <div className="actions">
                    {canCancel(job.status) ? (
                      <button type="button" onClick={() => void onCancel(job.job_id)}>
                        Cancel
                      </button>
                    ) : null}
                    {canRetry(job.status) ? (
                      <button type="button" onClick={() => void onRetry(job.job_id)}>
                        Retry
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <footer className="statusbar">
        <span>Engine ready</span>
        <span>{project.read_only ? "Read-only project" : "Project open"}</span>
        <span>
          {missing > 0 ? `${missing} media missing` : media.assets.length === 0 ? "No media" : "Media available"}
        </span>
        <button type="button" className="status-button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          {summary}
        </button>
        <span className="live" aria-live="polite">
          {summary}
          {missing > 0 ? `, ${missing} media missing` : ""}
        </span>
      </footer>
    </>
  );
}
