import { open } from "@tauri-apps/plugin-dialog";

import { createJob, linkMedia, relinkMedia } from "../../api/client";
import { asFailure } from "../../api/errors";
import type { ProjectInfo } from "../../api/types";
import { IMPORT_MEDIA, mediaCardLabel, mediaFacts, mediaGuidance, playbackLabel, proxyLabel, roleLabel, sourceAssets } from "../../media/present";
import { usePlayback } from "../../playback/PlaybackSession";
import { useProjectData } from "../../project/ProjectData";
import { SplitPane } from "../../shell/SplitPane";
import { LayoutEditor } from "./LayoutEditor";
import { LayoutForm } from "./LayoutForm";
import { ParticipantsPanel } from "./ParticipantsPanel";

export function MediaWorkspace({ project }: { project: ProjectInfo }) {
  const data = useProjectData();
  const playback = usePlayback();
  const selected = data.selected;
  const sources = sourceAssets(data.assets);
  const guidanceAsset = selected ?? sources[0];

  async function chooseFile(title: string): Promise<string | null> {
    const selectedPath = await open({ multiple: false, directory: false, title: title });
    return typeof selectedPath === "string" ? selectedPath : null;
  }

  async function link() {
    data.setNotice(null);
    const path = await chooseFile(IMPORT_MEDIA);
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
          <dd>{mediaCardLabel(selected.prepare_state)}</dd>
        </div>
        {selected.role === "master" ? (
          <div>
            <dt>Playback</dt>
            <dd>{playbackLabel(playback.view?.source_media_asset_id === selected.asset_id ? playback.view.playback_kind : selected.playback_kind)}</dd>
          </div>
        ) : null}
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
      {selected.role === "master" && selected.status === "present" && selected.proxy_state !== "ready" && selected.proxy_state !== "queued" && selected.proxy_state !== "generating" ? (
        <button type="button" onClick={() => void generateProxy()} disabled={data.busy || project.read_only}>
          Generate proxy
        </button>
      ) : null}
      {selected.role === "master" && selected.proxy_state === "ready" && playback.previewPreference !== "proxy" ? (
        <button type="button" onClick={() => playback.setPreviewPreference("proxy")} disabled={data.busy}>
          Play proxy
        </button>
      ) : null}
      {selected.role === "master" && playback.previewPreference === "proxy" ? (
        <button type="button" onClick={() => playback.setPreviewPreference("source")} disabled={data.busy}>
          Play original
        </button>
      ) : null}
      {selected.status === "missing" ? (
        <button type="button" className="primary" onClick={() => void relink()} disabled={data.busy || project.read_only}>
          Relink
        </button>
      ) : null}
      {selected.role === "master" && selected.status === "present" ? (
        <details>
          <summary>Details</summary>
          <div className="actions">
            <button type="button" onClick={() => void analyze()} disabled={data.busy || project.read_only}>
              Re-analyze Media
            </button>
            <button type="button" onClick={() => void generateProxy()} disabled={data.busy || project.read_only}>
              Rebuild Proxy
            </button>
          </div>
          <LayoutForm project={project} asset={selected} />
        </details>
      ) : null}
    </aside>
  ) : null;

  const list = (
    <section className="context" aria-label="Media">
      <div className="toolbar">
        <h2>Media</h2>
        <button type="button" className="primary" onClick={() => void link()} disabled={data.busy || project.read_only}>
          {IMPORT_MEDIA}
        </button>
      </div>
      <p>{mediaGuidance(sources.length > 0, guidanceAsset?.prepare_state)}</p>
      {sources.length === 0 ? <p className="muted">Import media to begin.</p> : null}
      <ul className="asset-list">
        {sources.map((asset) => (
          <li key={asset.asset_id}>
            <button
              type="button"
              className={asset.asset_id === data.selectedId ? "selected" : undefined}
              aria-current={asset.asset_id === data.selectedId ? "true" : undefined}
              onClick={() => data.select(asset.asset_id)}
            >
              <span>{asset.display_name}</span>
              <span className={asset.prepare_state === "missing" || asset.prepare_state === "failed" ? "status missing" : "status"}>
                {mediaCardLabel(asset.prepare_state)}
              </span>
              <span className="muted">{roleLabel(asset.role)}</span>
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
      side={
        <div className="setup-column">
          {list}
          <ParticipantsPanel project={project} />
        </div>
      }
      main={
        <SplitPane
          sideWidth={280}
          side={inspector}
          main={
            <section className="workspace-main" aria-label="Preview">
              <div className="toolbar">
                <h1>Preview</h1>
              </div>
              {selected?.role === "master" ? <LayoutEditor project={project} asset={selected} /> : null}
            </section>
          }
        />
      }
    />
  );
}
