import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef, useState } from "react";

import { desktopSession, engineRetry } from "../api/client";
import { projectInfo, visibleProject } from "../api/session";
import type { EngineFailure, EngineStatus, ProjectInfo } from "../api/types";
import { Diagnostics } from "../components/Diagnostics";
import { ProjectShell } from "./ProjectShell";
import { StartScreen } from "./StartScreen";

export function EngineGate() {
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [folder, setFolder] = useState<string | null>(null);
  const [notice, setNotice] = useState<EngineFailure | null>(null);
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

  async function retryEngine() {
    setNotice(null);
    applySession(await engineRetry());
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

  if (!project) {
    return <StartScreen engine={engine} notice={notice} setNotice={setNotice} applySession={applySession} />;
  }

  return (
    <ProjectShell
      project={project}
      folder={folder}
      generation={engine.generation}
      notice={notice}
      setNotice={setNotice}
      applySession={applySession}
    />
  );
}
