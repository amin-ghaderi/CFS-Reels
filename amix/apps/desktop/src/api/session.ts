import type { EngineStatus, ProjectInfo, SessionProject } from "./types";

/** The open project, only when it belongs to the engine generation that is ready. */
export function visibleProject(session: EngineStatus): SessionProject | null {
  const project = session.project;
  if (!project || session.state !== "READY" || project.generation !== session.generation) {
    return null;
  }
  return project;
}

export function projectInfo(project: SessionProject): ProjectInfo {
  return {
    handle: project.handle,
    project_id: project.project_id,
    name: project.name,
    read_only: project.read_only,
    schema_revision: project.schema_revision,
  };
}
