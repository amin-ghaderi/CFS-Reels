import { open } from "@tauri-apps/plugin-dialog";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef, useState } from "react";

import {
  cancelJob,
  closeProject,
  createJob,
  createProject,
  desktopSession,
  engineRetry,
  joinProjectPath,
  listJobs,
  openProject,
  retryJob,
} from "./api/client";
import { jobProblemMessage } from "./api/errors";
import { canCancel, canRetry, isTerminal, jobTitle, progressPercent } from "./api/jobs";
import { projectInfo, visibleProject } from "./api/session";
import type { EngineFailure, EngineStatus, JobInfo, ProjectInfo } from "./api/types";

const DESTINATIONS = ["Media", "Transcript", "Conversation", "Multicam", "Reels", "Export"] as const;
const POLL_MS = 1000;

export function App() {
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [folder, setFolder] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobInfo[]>([]);
  const [destination, setDestination] = useState<(typeof DESTINATIONS)[number]>("Media");
  const [notice, setNotice] = useState<EngineFailure | null>(null);
  const [busy, setBusy] = useState(false);
  const [naming, setNaming] = useState<string | null>(null);
  const [pollToken, setPollToken] = useState(0);
  const generationRef = useRef(0);

  function applySession(session: EngineStatus) {
    if (session.generation < generationRef.current) {
      return;
    }
    generationRef.current = session.generation;
    setEngine(session);
    const current = visibleProject(session);
    if (current) {
      setProject(projectInfo(current));
      setFolder(current.path);
      setNotice((existing) => (existing?.code === "engine_session" ? null : existing));
    } else {
      setProject(null);
      setFolder(null);
      setJobs([]);
      if (session.notice) {
        setNotice({ code: "engine_session", message: session.notice });
      }
    }
  }

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let stop = false;
    void (async () => {
      unlisten = await listen<EngineStatus>("amix-session", (event) => {
        if (!stop) {
          applySession(event.payload);
        }
      });
      if (stop) {
        unlisten();
        return;
      }
      applySession(await desktopSession());
    })().catch(() => {
      if (!stop) {
        setEngine({
          generation: generationRef.current,
          state: "FAILED",
          message: "The desktop shell could not read engine status.",
          host: null,
          port: null,
          version: null,
          project: null,
          notice: null,
        });
      }
    });
    return () => {
      stop = true;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    if (!project) {
      return;
    }
    let stop = false;
    let timer = 0;
    const tick = async () => {
      try {
        const next = await listJobs(project.handle);
        if (stop) {
          return;
        }
        setJobs(next);
        if (next.some((job) => !isTerminal(job.status))) {
          timer = window.setTimeout(() => void tick(), POLL_MS);
        }
      } catch (error) {
        if (!stop) {
          setNotice(asFailure(error));
        }
      }
    };
    void tick();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [project, pollToken]);

  async function retryEngine() {
    setNotice(null);
    applySession(await engineRetry());
  }

  async function chooseCreate() {
    setNotice(null);
    const parent = await open({ directory: true, multiple: false, title: "Choose a folder for the new project" });
    if (typeof parent !== "string") {
      return;
    }
    setNaming(parent);
  }

  async function submitCreate(name: string) {
    if (!naming) {
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const path = await joinProjectPath(naming, name);
      await createProject(path, name.trim());
      setNaming(null);
      setPollToken((value) => value + 1);
    } catch (error) {
      setNotice(asFailure(error));
    } finally {
      applySession(await desktopSession());
      setBusy(false);
    }
  }

  async function chooseOpen() {
    setNotice(null);
    const selected = await open({ directory: true, multiple: false, title: "Open an AMIX project" });
    if (typeof selected !== "string") {
      return;
    }
    setBusy(true);
    try {
      await openProject(selected);
      setPollToken((value) => value + 1);
    } catch (error) {
      setNotice(asFailure(error));
    } finally {
      applySession(await desktopSession());
      setBusy(false);
    }
  }

  async function closeCurrent() {
    if (!project) {
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      await closeProject(project.handle);
    } catch (error) {
      setNotice(asFailure(error));
    } finally {
      applySession(await desktopSession());
      setBusy(false);
    }
  }

  async function runIntegrity() {
    if (!project) {
      return;
    }
    setNotice(null);
    try {
      await createJob(project.handle, "project_integrity_check");
      setPollToken((value) => value + 1);
    } catch (error) {
      setNotice(asFailure(error));
    }
  }

  async function onCancel(jobId: string) {
    if (!project) {
      return;
    }
    try {
      await cancelJob(project.handle, jobId);
      setPollToken((value) => value + 1);
    } catch (error) {
      setNotice(asFailure(error));
    }
  }

  async function onRetry(jobId: string) {
    if (!project) {
      return;
    }
    try {
      await retryJob(project.handle, jobId);
      setPollToken((value) => value + 1);
    } catch (error) {
      setNotice(asFailure(error));
    }
  }

  if (!engine || engine.state === "STARTING" || engine.state === "STOPPED") {
    return (
      <main className="gate">
        <section className="card">
          <h1>AMIX</h1>
          <p className="muted">Starting the local engine.</p>
        </section>
      </main>
    );
  }

  if (engine.state === "FAILED") {
    return (
      <main className="gate">
        <section className="card">
          <h1>AMIX</h1>
          <p>The local engine is unavailable.</p>
          <p className="muted">{engine.message}</p>
          <div className="actions">
            <button className="primary" type="button" onClick={() => void retryEngine()}>
              Retry engine
            </button>
          </div>
          <Diagnostics engine={engine} />
        </section>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">AMIX</div>
        <div className="project-name">{project ? project.name : "No project"}</div>
        {project ? (
          <button type="button" onClick={() => void closeCurrent()} disabled={busy}>
            {busy ? "Closing" : "Close project"}
          </button>
        ) : null}
      </header>
      {project ? (
        <div className="workspace-body">
          <nav className="nav" aria-label="Workspaces">
            {DESTINATIONS.map((item) => (
              <button
                key={item}
                type="button"
                aria-current={item === destination ? "page" : undefined}
                onClick={() => setDestination(item)}
              >
                {item}
              </button>
            ))}
          </nav>
          <main className="workspace">
            {notice ? <Alert failure={notice} /> : null}
            <h1>{destination}</h1>
            <p className="muted">Not implemented yet.</p>
            <p className="muted">This destination is reserved for a later editing workspace.</p>
          </main>
          <aside className="inspector" aria-label="Jobs">
            <h2>Jobs</h2>
            <button className="primary" type="button" onClick={() => void runIntegrity()} disabled={busy}>
              Run project integrity check
            </button>
            <div style={{ height: 12 }} />
            {jobs.length === 0 ? <p className="muted">No jobs yet.</p> : null}
            {jobs.map((job) => (
              <article className="job" key={job.job_id}>
                <div className="job-row">
                  <strong>{jobTitle(job.kind)}</strong>
                  <span>{job.status}</span>
                </div>
                <div className="meter" aria-hidden="true">
                  <span style={{ width: `${progressPercent(job.progress_bp)}%` }} />
                </div>
                <p className="muted">
                  Attempt {job.attempt} · {progressPercent(job.progress_bp)}%
                </p>
                {job.error_code || job.error_message ? <p>{jobProblemMessage(job.error_code)}</p> : null}
                {import.meta.env.DEV && job.error_message ? (
                  <details>
                    <summary>Details</summary>
                    <div>{job.error_message}</div>
                  </details>
                ) : null}
                <div className="actions">
                  <button type="button" disabled={!canCancel(job.status)} onClick={() => void onCancel(job.job_id)}>
                    Cancel
                  </button>
                  <button type="button" disabled={!canRetry(job.status)} onClick={() => void onRetry(job.job_id)}>
                    Retry
                  </button>
                </div>
              </article>
            ))}
          </aside>
        </div>
      ) : (
        <main className="start-screen">
          <section className="card">
            <h1>AMIX</h1>
            <p className="muted">Create a project or open an existing project folder.</p>
            {notice ? <Alert failure={notice} /> : null}
            <div className="actions">
              <button className="primary" type="button" onClick={() => void chooseCreate()} disabled={busy}>
                Create project
              </button>
              <button type="button" onClick={() => void chooseOpen()} disabled={busy}>
                Open project
              </button>
            </div>
            <Diagnostics engine={engine} />
          </section>
        </main>
      )}
      <footer className="statusbar">
        <span>Engine ready</span>
        <span>{project ? "Project open" : "No project"}</span>
        <span>{jobs.some((job) => !isTerminal(job.status)) ? "Background job running" : "No active job"}</span>
        {folder && project ? <span className="project-name">{folder}</span> : null}
      </footer>
      {naming ? (
        <NameDialog
          parent={naming}
          busy={busy}
          onCancel={() => setNaming(null)}
          onSubmit={(name) => void submitCreate(name)}
        />
      ) : null}
    </div>
  );
}

function Alert({ failure }: { failure: EngineFailure }) {
  return (
    <div className="banner" role="alert">
      <div>{failure.message}</div>
      <details>
        <summary>Details</summary>
        <div>Code: {failure.code}</div>
      </details>
    </div>
  );
}

function Diagnostics({ engine }: { engine: EngineStatus }) {
  if (!import.meta.env.DEV) {
    return null;
  }
  return (
    <div className="diagnostics">
      <div>Development diagnostics</div>
      <div>Status: {engine.state}</div>
      <div>Version: {engine.version ?? "unknown"}</div>
      <div>Host: {engine.host ?? "unknown"}</div>
      <div>Port: {engine.port ?? "unknown"}</div>
    </div>
  );
}

function NameDialog({
  parent,
  busy,
  onCancel,
  onSubmit,
}: {
  parent: string;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (name: string) => void;
}) {
  const [name, setName] = useState("");
  const blank = name.trim().length === 0;
  return (
    <div className="dialog-backdrop">
      <form
        className="card"
        onSubmit={(event) => {
          event.preventDefault();
          if (!blank) {
            onSubmit(name);
          }
        }}
      >
        <h2>Name the project</h2>
        <p className="muted">{parent}</p>
        <label htmlFor="project-name">Project name</label>
        <input
          id="project-name"
          type="text"
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              onCancel();
            }
          }}
        />
        <div className="actions">
          <button className="primary" type="submit" disabled={blank || busy}>
            Create
          </button>
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

function asFailure(error: unknown): EngineFailure {
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
