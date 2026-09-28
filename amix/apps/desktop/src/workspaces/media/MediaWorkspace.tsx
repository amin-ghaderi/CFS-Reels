import { open } from "@tauri-apps/plugin-dialog";

import { linkMedia, relinkMedia } from "../../api/client";
import { asFailure } from "../../api/errors";
import type { ProjectInfo } from "../../api/types";
import { mediaAvailability, mediaFacts, roleLabel } from "../../media/present";
import { useProjectData } from "../../project/ProjectData";
import { SplitPane } from "../../shell/SplitPane";

export function MediaWorkspace({ project }: { project: ProjectInfo }) {
  const data = useProjectData();
  const selected = data.selected;

  async function chooseFile(title: string): Promise<string | null> {
    const selectedPath = await open({ multiple: false, directory: false, title });
    return typeof selectedPath === "string" ? selectedPath : null;
  }

  async function link() {
    data.setNotice(null);
    const path = await chooseFile("Link a media file");
    if (!path) {
      return;
    }
    data.setBusy(true);
    try {
      const asset = await linkMedia(project.handle, path);
      await data.refresh();
      data.select(asset.asset_id);
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      data.setBusy(false);
    }
  }

  async function relink() {
    if (!selected) {
      return;
    }
    data.setNotice(null);
    const path = await chooseFile("Relink media file");
    if (!path) {
      return;
    }
    data.setBusy(true);
    try {
      const asset = await relinkMedia(project.handle, selected.asset_id, path);
      await data.refresh();
      data.select(asset.asset_id);
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      data.setBusy(false);
    }
  }

  const inspector = selected ? (
    <aside className="inspector" aria-label="Media details">
      <h2>{selected.display_name}</h2>
      <dl className="facts">
        <div>
          <dt>Role</dt>
          <dd>{roleLabel(selected.role)}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{mediaAvailability(selected.status)}</dd>
        </div>
        <div>
          <dt>Location</dt>
          <dd>{selected.location_kind === "external" ? "External file" : "Inside the project"}</dd>
        </div>
        {mediaFacts(selected).map((fact) => (
          <div key={fact}>
            <dt>Detail</dt>
            <dd className="numeric">{fact}</dd>
          </div>
        ))}
      </dl>
      {selected.external_path ? <p className="path">{selected.external_path}</p> : null}
      {selected.relative_path ? <p className="path">{selected.relative_path}</p> : null}
      {selected.status === "missing" ? (
        <button type="button" className="primary" onClick={() => void relink()} disabled={data.busy || project.read_only}>
          Relink
        </button>
      ) : null}
    </aside>
  ) : null;

  return (
    <SplitPane
      side={inspector}
      sideWidth={280}
      main={
        <section className="workspace-main" aria-label="Media">
          <div className="toolbar">
            <h1>Media</h1>
            <button type="button" className="primary" onClick={() => void link()} disabled={data.busy || project.read_only}>
              Link file
            </button>
          </div>
          {data.assets.length === 0 ? <p className="muted">No media is linked to this project yet.</p> : null}
          <ul className="asset-list">
            {data.assets.map((asset) => (
              <li key={asset.asset_id}>
                <button
                  type="button"
                  className={asset.asset_id === data.selectedId ? "selected" : undefined}
                  aria-current={asset.asset_id === data.selectedId ? "true" : undefined}
                  onClick={() => data.select(asset.asset_id)}
                >
                  <span>{asset.display_name}</span>
                  <span className={asset.status === "missing" ? "status missing" : "status"}>
                    {mediaAvailability(asset.status)}
                  </span>
                  <span className="muted">{roleLabel(asset.role)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      }
    />
  );
}
