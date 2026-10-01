import { open } from "@tauri-apps/plugin-dialog";
import { useState } from "react";

import { createProject, desktopSession, joinProjectPath, openProject } from "../api/client";
import { asFailure } from "../api/errors";
import type { EngineFailure, EngineStatus } from "../api/types";
import { Alert } from "../components/Alert";
import { Diagnostics } from "../components/Diagnostics";
import { NameDialog } from "../components/NameDialog";

export function StartScreen({
  engine,
  notice,
  setNotice,
  applySession,
  onSettings,
}: {
  engine: EngineStatus;
  notice: EngineFailure | null;
  setNotice: (notice: EngineFailure | null) => void;
  applySession: (session: EngineStatus) => void;
  onSettings: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [naming, setNaming] = useState<string | null>(null);

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
    } catch (error) {
      setNotice(asFailure(error));
    } finally {
      applySession(await desktopSession());
      setBusy(false);
    }
  }

  return (
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
          <button type="button" onClick={onSettings} disabled={busy}>
            Settings
          </button>
        </div>
        <Diagnostics engine={engine} />
      </section>
      {naming ? (
        <NameDialog parent={naming} busy={busy} onCancel={() => setNaming(null)} onSubmit={(name) => void submitCreate(name)} />
      ) : null}
    </main>
  );
}
