import { open } from "@tauri-apps/plugin-dialog";
import { useEffect, useState } from "react";

import { createProject, desktopSession, joinProjectPath, listRecentProjects, locateRecentProject, openProject, recentThumbnail, removeRecentProject } from "../api/client";
import { asFailure } from "../api/errors";
import type { EngineFailure, EngineStatus } from "../api/types";
import { Alert } from "../components/Alert";
import { Diagnostics } from "../components/Diagnostics";
import { NameDialog } from "../components/NameDialog";
import {
  CREATE_PROJECT,
  LOCATE_PROJECT,
  MISSING_PROJECT,
  OPEN_EXISTING,
  RECENT_HEADING,
  RECENT_PREVIEW_COUNT,
  REMOVE_RECENT,
  canOpen,
  cardTitle,
  formatOpened,
  pathHint,
  showAllLabel,
  thumbnailSrc,
  visibleRecents,
  type RecentProject,
} from "../recent/recent";

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
  const [projects, setProjects] = useState<RecentProject[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [thumbs, setThumbs] = useState<Record<string, string | null>>({});

  async function refreshRecent() {
    try {
      setProjects(await listRecentProjects());
    } catch (error) {
      setNotice(asFailure(error));
    }
  }

  useEffect(() => {
    void refreshRecent();
  }, [engine.generation]);

  useEffect(() => {
    let stop = false;
    for (const project of projects) {
      if (project.thumbnail !== "ready" || thumbs[project.project_id] !== undefined) {
        continue;
      }
      void recentThumbnail(project.project_id).then((data) => {
        if (!stop) {
          setThumbs((current) => ({ ...current, [project.project_id]: data }));
        }
      });
    }
    return () => {
      stop = true;
    };
  }, [projects]);

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
    await openAt(selected);
  }

  async function openAt(path: string) {
    setBusy(true);
    setNotice(null);
    try {
      await openProject(path);
    } catch (error) {
      setNotice(asFailure(error));
      await refreshRecent();
    } finally {
      applySession(await desktopSession());
      setBusy(false);
    }
  }

  async function locate(project: RecentProject) {
    setNotice(null);
    const selected = await open({ directory: true, multiple: false, title: "Locate the project folder" });
    if (typeof selected !== "string") {
      return;
    }
    setBusy(true);
    try {
      await locateRecentProject(project.project_id, selected);
      await refreshRecent();
    } catch (error) {
      setNotice(asFailure(error));
    } finally {
      setBusy(false);
    }
  }

  async function remove(project: RecentProject) {
    setNotice(null);
    setBusy(true);
    try {
      await removeRecentProject(project.project_id);
      setThumbs((current) => {
        const next = { ...current };
        delete next[project.project_id];
        return next;
      });
      await refreshRecent();
    } catch (error) {
      setNotice(asFailure(error));
    } finally {
      setBusy(false);
    }
  }

  const shown = visibleRecents(projects, expanded);

  return (
    <main className="start-screen">
      <section className="launcher">
        <h1>AMIX</h1>
        <div className="recent-heading">
          <h2>{RECENT_HEADING}</h2>
          {projects.length > RECENT_PREVIEW_COUNT ? (
            <button type="button" onClick={() => setExpanded((value) => !value)} disabled={busy}>
              {showAllLabel(expanded)}
            </button>
          ) : null}
        </div>
        {projects.length === 0 ? <p className="muted">Projects you open will appear here.</p> : null}
        <ul className="recent-list">
          {shown.map((project) => {
            const image = thumbnailSrc(thumbs[project.project_id]);
            return (
              <li key={project.project_id} className="recent-row">
                <button
                  type="button"
                  className="recent-card"
                  disabled={busy || !canOpen(project)}
                  onClick={() => void openAt(project.root_path)}
                >
                  {image ? <img className="thumb" alt="" src={image} /> : <span className="thumb-placeholder" aria-hidden="true" />}
                  <span className="recent-copy">
                    <strong>{cardTitle(project)}</strong>
                    <span className="muted">{formatOpened(project.last_opened_at)}</span>
                    <span className="path-hint" title={project.root_path}>{pathHint(project.root_path)}</span>
                  </span>
                  {project.availability === "missing" ? <span className="status missing">{MISSING_PROJECT}</span> : null}
                </button>
                <div className="recent-overflow">
                  <button type="button" onClick={() => void locate(project)} disabled={busy}>{LOCATE_PROJECT}</button>
                  <button type="button" onClick={() => void remove(project)} disabled={busy}>{REMOVE_RECENT}</button>
                </div>
              </li>
            );
          })}
        </ul>
        {notice ? <Alert failure={notice} /> : null}
        <div className="actions">
          <button className="primary" type="button" onClick={() => void chooseCreate()} disabled={busy}>
            {CREATE_PROJECT}
          </button>
          <button type="button" onClick={() => void chooseOpen()} disabled={busy}>
            {OPEN_EXISTING}
          </button>
          <button type="button" onClick={onSettings} disabled={busy}>
            Settings
          </button>
        </div>
        {import.meta.env.DEV ? (
          <details className="launcher-diagnostics">
            <summary>Diagnostics</summary>
            <Diagnostics engine={engine} />
          </details>
        ) : null}
      </section>
      {naming ? (
        <NameDialog parent={naming} busy={busy} onCancel={() => setNaming(null)} onSubmit={(name) => void submitCreate(name)} />
      ) : null}
    </main>
  );
}
