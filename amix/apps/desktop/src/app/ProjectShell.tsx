import { useState } from "react";

import { closeProject, desktopSession, listJobs } from "../api/client";
import { asFailure } from "../api/errors";
import { isTerminal } from "../api/jobs";
import type { EngineFailure, EngineStatus, ProjectInfo } from "../api/types";
import { Alert } from "../components/Alert";
import { ActivityBar } from "../jobs/ActivityBar";
import { ProjectDataProvider, useProjectData } from "../project/ProjectData";
import { PlaybackProvider } from "../playback/PlaybackSession";
import type { WorkspaceId } from "../shell/workspaces";
import { WORKSPACES, isPlaceholder } from "../shell/workspaces";
import { MediaWorkspace } from "../workspaces/media/MediaWorkspace";
import { MulticamWorkspace } from "../workspaces/multicam/MulticamWorkspace";
import { PlaceholderWorkspace } from "../workspaces/PlaceholderWorkspace";
import { TranscriptWorkspace } from "../workspaces/transcript/TranscriptWorkspace";

export function ProjectShell({
  project,
  folder,
  generation,
  notice,
  setNotice,
  applySession,
}: {
  project: ProjectInfo;
  folder: string | null;
  generation: number;
  notice: EngineFailure | null;
  setNotice: (notice: EngineFailure | null) => void;
  applySession: (session: EngineStatus) => void;
}) {
  const [workspace, setWorkspace] = useState<WorkspaceId>("Media");
  const [busy, setBusy] = useState(false);

  async function closeCurrent() {
    setNotice(null);
    const jobs = await listJobs(project.handle).catch(() => []);
    if (jobs.some((job) => !isTerminal(job.status))) {
      const confirmed = window.confirm("A background job is still running. Close the project anyway?");
      if (!confirmed) {
        return;
      }
    }
    setBusy(true);
    try {
      await closeProject(project.handle);
    } catch (error) {
      setNotice(asFailure(error));
    } finally {
      applySession(await desktopSession());
      setBusy(false);
    }
  }

  return (
    <ProjectDataProvider project={project}>
      <PlaybackProvider generation={generation}>
      <div className="app-shell">
        <header className="topbar">
          <div className="brand">AMIX</div>
          <div className="project-name">
            {project.name}
            {folder ? <span className="project-path">{folder}</span> : null}
          </div>
          <nav className="switcher" aria-label="Workspaces">
            {WORKSPACES.map((item) => (
              <button
                key={item}
                type="button"
                aria-current={item === workspace ? "page" : undefined}
                onClick={() => setWorkspace(item)}
              >
                {item}
              </button>
            ))}
          </nav>
          <button type="button" onClick={() => void closeCurrent()} disabled={busy}>
            {busy ? "Closing" : "Close project"}
          </button>
        </header>
        <ShellNotice notice={notice} />
        <div className="workspace-slot">
          {workspace === "Media" ? <MediaWorkspace project={project} /> : null}
          {workspace === "Transcript" ? <TranscriptWorkspace project={project} /> : null}
          {workspace === "Multicam" ? <MulticamWorkspace project={project} /> : null}
          {isPlaceholder(workspace) ? <PlaceholderWorkspace workspace={workspace} /> : null}
        </div>
        <ActivityBar project={project} onNotice={setNotice} />
      </div>
      </PlaybackProvider>
    </ProjectDataProvider>
  );
}

function ShellNotice({ notice }: { notice: EngineFailure | null }) {
  const data = useProjectData();
  const shown = notice ?? data.notice;
  if (!shown) {
    return null;
  }
  return (
    <div className="shell-notice">
      <Alert failure={shown} />
    </div>
  );
}
