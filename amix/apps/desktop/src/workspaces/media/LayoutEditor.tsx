import { useEffect, useState, type PointerEvent as ReactPointerEvent } from "react";

import { addLayout, detectLayoutCandidates, listLayout, listParticipants } from "../../api/client";
import { asFailure } from "../../api/errors";
import type { MediaAsset, Participant, ProjectInfo } from "../../api/types";
import { defaultLayoutSpan } from "../../layout/layout";
import {
  clampRect,
  contentBox,
  layoutSaveBody,
  moveRect,
  resizeRect,
  sourceRectToPreview,
  type SourceRect,
} from "../../layout/geometry";
import { PreviewPlayer } from "../../playback/PreviewPlayer";
import { usePlayback } from "../../playback/PlaybackSession";
import { PARTICIPANTS_CHANGED_EVENT } from "../../participants/participants";
import { useProjectData } from "../../project/ProjectData";

interface Draft {
  key: string;
  rect: SourceRect;
  participantId: string | null;
  bindingId: string | null;
  startUs: number;
  endUs: number;
}

export function LayoutEditor({ project, asset }: { project: ProjectInfo; asset: MediaAsset }) {
  const data = useProjectData();
  const playback = usePlayback();
  const [people, setPeople] = useState<Participant[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [personId, setPersonId] = useState("");
  const [detecting, setDetecting] = useState(false);
  const [frame, setFrame] = useState({ width: 0, height: 0 });
  const span = defaultLayoutSpan(asset.container_start_us, asset.duration_us);
  const picture = asset.width !== null && asset.height !== null ? { width: asset.width, height: asset.height } : null;

  useEffect(() => {
    let stop = false;
    const load = () => {
      void Promise.all([listParticipants(project.handle), listLayout(project.handle, asset.asset_id)])
        .then(([listed, bindings]) => {
          if (stop) {
            return;
          }
          setPeople(listed);
          setDrafts(bindings.map((row) => ({
            key: row.binding_id,
            rect: { x: row.x, y: row.y, w: row.w, h: row.h },
            participantId: row.participant_id,
            bindingId: row.binding_id,
            startUs: row.start_us,
            endUs: row.end_us,
          })));
        })
        .catch((error: unknown) => {
          if (!stop) {
            data.setNotice(asFailure(error));
          }
        });
    };
    load();
    window.addEventListener(PARTICIPANTS_CHANGED_EVENT, load);
    return () => {
      stop = true;
      window.removeEventListener(PARTICIPANTS_CHANGED_EVENT, load);
    };
  }, [project.handle, asset.asset_id]);

  useEffect(() => {
    const video = playback.videoRef.current;
    if (!video) {
      return;
    }
    const measure = () => setFrame({ width: video.clientWidth, height: video.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(video);
    return () => observer.disconnect();
  }, [playback.videoRef, asset.asset_id, playback.view?.playable]);

  async function detect() {
    data.setNotice(null);
    setDetecting(true);
    try {
      const found = await detectLayoutCandidates(project.handle, asset.asset_id, playback.playheadUs);
      const range = defaultLayoutSpan(asset.container_start_us, asset.duration_us);
      if (!range) {
        data.setNotice({ code: "layout_requires_probe", message: "Probe this media before detecting people." });
        return;
      }
      setDrafts((current) => {
        const saved = current.filter((item) => item.bindingId);
        const fresh = found.candidates.map((rect, index) => ({
          key: `candidate-${index}-${rect.x}-${rect.y}`,
          rect,
          participantId: null,
          bindingId: null,
          startUs: range.startUs,
          endUs: range.endUs,
        }));
        return [...saved, ...fresh];
      });
      setSelected(null);
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      setDetecting(false);
    }
  }

  function assign() {
    if (!selected || !personId) {
      data.setNotice({ code: "unknown_participant", message: "Choose a person for this region." });
      return;
    }
    setDrafts((current) => current.map((item) => (
      item.key === selected ? { ...item, participantId: personId } : item
    )));
  }

  async function save() {
    const range = span;
    if (!range) {
      data.setNotice({ code: "layout_requires_probe", message: "Probe this media before saving a layout." });
      return;
    }
    const ready = drafts.filter((item) => item.participantId);
    if (ready.length === 0) {
      data.setNotice({ code: "invalid_layout", message: "Assign a person to a region before saving." });
      return;
    }
    data.setBusy(true);
    data.setNotice(null);
    try {
      for (const item of ready) {
        const startUs = item.bindingId ? item.startUs : range.startUs;
        const endUs = item.bindingId ? item.endUs : range.endUs;
        await addLayout(project.handle, asset.asset_id, layoutSaveBody({
          participantId: item.participantId as string,
          rect: item.rect,
          startUs,
          endUs,
          bindingId: item.bindingId,
        }));
      }
      const bindings = await listLayout(project.handle, asset.asset_id);
      setDrafts(bindings.map((row) => ({
        key: row.binding_id,
        rect: { x: row.x, y: row.y, w: row.w, h: row.h },
        participantId: row.participant_id,
        bindingId: row.binding_id,
        startUs: row.start_us,
        endUs: row.end_us,
      })));
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      data.setBusy(false);
    }
  }

  function onPointerDown(event: ReactPointerEvent<HTMLElement>, key: string, mode: "move" | "resize") {
    if (!picture) {
      return;
    }
    const box = contentBox(frame.width, frame.height, picture.width, picture.height);
    if (!box) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setSelected(key);
    const originX = event.clientX;
    const originY = event.clientY;
    const start = drafts.find((item) => item.key === key);
    if (!start) {
      return;
    }
    const target = event.currentTarget as HTMLElement;
    target.setPointerCapture(event.pointerId);
    const move = (next: PointerEvent) => {
      const deltaX = next.clientX - originX;
      const deltaY = next.clientY - originY;
      const rect = mode === "move"
        ? moveRect(start.rect, deltaX, deltaY, box, picture.width, picture.height)
        : resizeRect(start.rect, deltaX, deltaY, box, picture.width, picture.height);
      setDrafts((current) => current.map((item) => (item.key === key ? { ...item, rect } : item)));
    };
    const up = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
  }

  const names = new Map(people.map((person) => [person.participant_id, person.display_name]));
  const box = picture ? contentBox(frame.width, frame.height, picture.width, picture.height) : null;
  const chosen = drafts.find((item) => item.key === selected);

  const overlay = box ? (
    <div className="layout-overlay" aria-label="Layout regions">
      {drafts.map((item) => {
        const view = sourceRectToPreview(item.rect, box);
        const name = item.participantId ? names.get(item.participantId) : null;
        return (
          <div
            key={item.key}
            className={item.key === selected ? "layout-rect selected" : "layout-rect"}
            style={{ left: view.x, top: view.y, width: view.width, height: view.height }}
            onPointerDown={(event) => onPointerDown(event, item.key, "move")}
          >
            <span>{name ?? "Unassigned"}</span>
            <button
              type="button"
              className="layout-handle"
              aria-label="Resize region"
              onPointerDown={(event) => onPointerDown(event, item.key, "resize")}
            />
          </div>
        );
      })}
    </div>
  ) : null;

  return (
    <div className="layout-editor">
      <PreviewPlayer project={project} overlay={overlay} />
      <div className="actions">
        <button type="button" onClick={() => void detect()} disabled={detecting || data.busy || project.read_only || !picture}>
          {detecting ? "Detecting…" : "Detect Faces"}
        </button>
        <button type="button" className="primary" onClick={() => void save()} disabled={data.busy || project.read_only}>
          Save layout
        </button>
      </div>
      <label>
        Person
        <select value={personId} onChange={(event) => setPersonId(event.target.value)} disabled={project.read_only}>
          <option value="">Choose a person</option>
          {people.map((person) => (
            <option key={person.participant_id} value={person.participant_id}>{person.display_name}</option>
          ))}
        </select>
      </label>
      <button type="button" onClick={assign} disabled={!chosen || !personId || project.read_only}>
        {personId ? `This is ${names.get(personId) ?? "this person"}` : "Assign person"}
      </button>
      {chosen ? <p className="muted">Drag the region, then save. The time range is the whole media unless you edit it in Details.</p> : null}
    </div>
  );
}

export function draftFromDetection(rect: SourceRect, sourceWidth: number, sourceHeight: number): SourceRect {
  return clampRect(rect, sourceWidth, sourceHeight);
}
