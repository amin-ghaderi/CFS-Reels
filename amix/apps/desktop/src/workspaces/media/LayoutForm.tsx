import { useEffect, useState, type FormEvent } from "react";

import { addLayout, listLayout, listParticipants } from "../../api/client";
import { asFailure } from "../../api/errors";
import type { LayoutBindingRecord, MediaAsset, Participant, ProjectInfo } from "../../api/types";
import { defaultLayoutSpan, layoutFieldError, parseTimecode } from "../../layout/layout";
import { useProjectData } from "../../project/ProjectData";
import { formatMicroseconds } from "../../time/format";

export function LayoutForm({ project, asset }: { project: ProjectInfo; asset: MediaAsset }) {
  const data = useProjectData();
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [bindings, setBindings] = useState<LayoutBindingRecord[]>([]);
  const span = defaultLayoutSpan(asset.container_start_us, asset.duration_us);
  const [participantId, setParticipantId] = useState("");
  const [start, setStart] = useState(span ? formatMicroseconds(span.startUs) : "");
  const [end, setEnd] = useState(span ? formatMicroseconds(span.endUs) : "");
  const [x, setX] = useState("0");
  const [y, setY] = useState("0");
  const [width, setWidth] = useState(asset.width ? String(asset.width) : "");
  const [height, setHeight] = useState(asset.height ? String(asset.height) : "");
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    const next = defaultLayoutSpan(asset.container_start_us, asset.duration_us);
    setStart(next ? formatMicroseconds(next.startUs) : "");
    setEnd(next ? formatMicroseconds(next.endUs) : "");
    setX("0");
    setY("0");
    setWidth(asset.width ? String(asset.width) : "");
    setHeight(asset.height ? String(asset.height) : "");
  }, [asset.asset_id, asset.container_start_us, asset.duration_us, asset.width, asset.height]);

  useEffect(() => {
    let stop = false;
    void Promise.all([listParticipants(project.handle), listLayout(project.handle, asset.asset_id)])
      .then(([people, rows]) => {
        if (!stop) {
          setParticipants(people);
          setBindings(rows);
        }
      })
      .catch((error: unknown) => {
        if (!stop) {
          data.setNotice(asFailure(error));
        }
      });
    return () => {
      stop = true;
    };
  }, [project.handle, asset.asset_id]);

  async function save(event: FormEvent) {
    event.preventDefault();
    const problem = layoutFieldError({
      participantId,
      start,
      end,
      x,
      y,
      width,
      height,
      pictureWidth: asset.width,
      pictureHeight: asset.height,
    });
    if (problem) {
      setFormError(problem);
      return;
    }
    const startUs = parseTimecode(start);
    const endUs = parseTimecode(end);
    if (startUs === null || endUs === null) {
      return;
    }
    setFormError(null);
    data.setBusy(true);
    try {
      const saved = await addLayout(project.handle, asset.asset_id, {
        participant_id: participantId,
        start_us: startUs,
        end_us: endUs,
        x: Number(x),
        y: Number(y),
        w: Number(width),
        h: Number(height),
      });
      setBindings((current) => [...current, saved].sort((left, right) => left.start_us - right.start_us));
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      data.setBusy(false);
    }
  }

  const names = new Map(participants.map((row) => [row.participant_id, row.display_name]));

  return (
    <section className="stack" aria-label="Layout">
      <h3>Layout</h3>
      <p className="muted">Display pixels on the probed picture. Times stay on the source timeline.</p>
      {bindings.length === 0 ? <p className="muted">No layout bindings yet.</p> : null}
      <ul className="facts">
        {bindings.map((row) => (
          <li key={row.binding_id}>
            {names.get(row.participant_id) ?? "Participant"} {formatMicroseconds(row.start_us)}–{formatMicroseconds(row.end_us)} {row.w}×{row.h} at {row.x},{row.y}
          </li>
        ))}
      </ul>
      <form className="stack" onSubmit={(event) => void save(event)}>
        <label>
          Participant
          <select value={participantId} onChange={(event) => setParticipantId(event.target.value)} disabled={project.read_only}>
            <option value="">Choose</option>
            {participants.map((row) => (
              <option key={row.participant_id} value={row.participant_id}>{row.display_name}</option>
            ))}
          </select>
        </label>
        <label>
          Start
          <input value={start} onChange={(event) => setStart(event.target.value)} dir="ltr" disabled={project.read_only} />
        </label>
        <label>
          End
          <input value={end} onChange={(event) => setEnd(event.target.value)} dir="ltr" disabled={project.read_only} />
        </label>
        <label>
          X
          <input value={x} onChange={(event) => setX(event.target.value)} dir="ltr" disabled={project.read_only} />
        </label>
        <label>
          Y
          <input value={y} onChange={(event) => setY(event.target.value)} dir="ltr" disabled={project.read_only} />
        </label>
        <label>
          Width
          <input value={width} onChange={(event) => setWidth(event.target.value)} dir="ltr" disabled={project.read_only} />
        </label>
        <label>
          Height
          <input value={height} onChange={(event) => setHeight(event.target.value)} dir="ltr" disabled={project.read_only} />
        </label>
        {formError ? <p>{formError}</p> : null}
        <button type="submit" disabled={data.busy || project.read_only}>Add layout</button>
      </form>
    </section>
  );
}
