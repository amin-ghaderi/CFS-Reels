import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { listMedia } from "../api/client";
import { asFailure } from "../api/errors";
import type { EngineFailure, MediaAsset, ProjectInfo } from "../api/types";
import { reconcileSelection } from "./selection";

interface ProjectDataValue {
  assets: MediaAsset[];
  selectedId: string | null;
  selected: MediaAsset | null;
  notice: EngineFailure | null;
  busy: boolean;
  refresh: () => Promise<void>;
  select: (assetId: string) => void;
  setNotice: (notice: EngineFailure | null) => void;
  setBusy: (busy: boolean) => void;
}

const ProjectDataContext = createContext<ProjectDataValue | null>(null);

export function ProjectDataProvider({ project, children }: { project: ProjectInfo; children: ReactNode }) {
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [projectKey, setProjectKey] = useState(project.project_id);
  const [notice, setNotice] = useState<EngineFailure | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const next = await listMedia(project.handle);
    setAssets(next);
    setSelectedId((current) => reconcileSelection(current, next.map((asset) => asset.asset_id), project.project_id, projectKey));
    setProjectKey(project.project_id);
  }

  useEffect(() => {
    let stop = false;
    setSelectedId(null);
    setAssets([]);
    setProjectKey(project.project_id);
    void listMedia(project.handle)
      .then((next) => {
        if (!stop) {
          setAssets(next);
        }
      })
      .catch((error: unknown) => {
        if (!stop) {
          setNotice(asFailure(error));
        }
      });
    return () => {
      stop = true;
    };
  }, [project.handle, project.project_id]);

  const value = useMemo<ProjectDataValue>(() => {
    const selected = assets.find((asset) => asset.asset_id === selectedId) ?? null;
    return {
      assets,
      selectedId: selected?.asset_id ?? null,
      selected,
      notice,
      busy,
      refresh,
      select: setSelectedId,
      setNotice,
      setBusy,
    };
  }, [assets, selectedId, notice, busy, project.handle]);

  return <ProjectDataContext.Provider value={value}>{children}</ProjectDataContext.Provider>;
}

export function useProjectData(): ProjectDataValue {
  const value = useContext(ProjectDataContext);
  if (!value) {
    throw new Error("Project data is only available while a project is open.");
  }
  return value;
}
