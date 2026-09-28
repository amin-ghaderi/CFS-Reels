import { open } from "@tauri-apps/plugin-dialog";

import { createJob, linkMedia, relinkMedia } from "../../api/client";
import { asFailure } from "../../api/errors";
import type { ProjectInfo } from "../../api/types";
import { mediaAvailability, mediaFacts, proxyLabel, roleLabel, sourceAssets } from "../../media/present";
import { PreviewPlayer } from "../../playback/PreviewPlayer";
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

  async function analyze() {
    if (!selected) {
      return;
    }
    data.setNotice(null);
    data.setBusy(true);
    try {
      await createJob(project.handle, "media_probe", { mediaAssetId: selected.asset_id });
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      data.setBusy(false);
    }
  }

  async function generateProxy() {
    if (!selected) {
      return;
    }
    data.setNotice(null);
    data.setBusy(true);
    try {
      await createJob(project.handle, "generate_proxy", {
        mediaAssetId: selected.asset_id,
        spec: { profile: "amix.proxy.v1" },
      });
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
        {selected.role === "master" ? (
          <div>
            <dt>Proxy</dt>
            <dd className={selected.proxy_state === "failed" ? "status failed" : selected.proxy_state === "stale" ? "status stale" : undefined}>
              {proxyLabel(selected.proxy_state)}
            </dd>
          </div>
        ) : null}
        {mediaFacts(selected).map((fact) => (
          <div key={fact.label}>
            <dt>{fact.label}</dt>
            <dd className="numeric" dir="ltr">{fact.value}</dd>
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
      {selected.role === "master" && selected.status === "present" ? (
        <div className="actions">
          <button type="button" onClick={() => void analyze()} disabled={data.busy || project.read_only}>
            Analyze media
          </button>
          <button type="button" className="primary" onClick={() => void generateProxy()} disabled={data.busy || project.read_only}>
            Generate proxy
          </button>
        </div>
      ) : null}
    </aside>
  ) : null;

  const list = (
    <section className="context" aria-label="Media">
      <div className="toolbar">
        <h2>Media</h2>
        <button type="button" className="primary" onClick={() => void link()} disabled={data.busy || project.read_only}>
          Link file
        </button>
      </div>
      {sourceAssets(data.assets).length === 0 ? <p className="muted">No media is linked to this project yet.</p> : null}
      <ul className="asset-list">
        {sourceAssets(data.assets).map((asset) => (
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
              {asset.role === "master" ? <span className="muted">Proxy {proxyLabel(asset.proxy_state)}</span> : null}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );

  return (
    <SplitPane
      sideFirst
      sideWidth={280}
      side={list}
      main={
        <SplitPane
          sideWidth={280}
          side={inspector}
          main={
            <section className="workspace-main" aria-label="Preview">
              <div className="toolbar">
                <h1>Preview</h1>
              </div>
              <PreviewPlayer project={project} />
            </section>
          }
        />
      }
    />
  );
}
