import { useEffect, useState } from "react";

import { captionState, editCaptionCue, exportCaptions, generateCaptions, resetCaptionCue } from "../api/client";
import { asFailure } from "../api/errors";
import type { CaptionState, ProjectInfo } from "../api/types";
import { usePlayback } from "../playback/PlaybackSession";
import { useProjectData } from "../project/ProjectData";
import { formatMicroseconds } from "../time/format";
import {
  CAPTION_COPY,
  captionStatusLabel,
  captionTextDirection,
  cueAtSource,
  exportEnabled,
  seekTargetUs,
  type CaptionCueView,
} from "./captions";

export function useCaptionTrack(handle: string, sequenceId: string | null, sequenceRevision: number | null) {
  const [state, setState] = useState<CaptionState | null>(null);

  useEffect(() => {
    if (!sequenceId) {
      setState(null);
      return;
    }
    let stop = false;
    const load = () => {
      void captionState(handle, sequenceId)
        .then((next) => {
          if (!stop) {
            setState(next);
          }
        })
        .catch(() => {
          if (!stop) {
            setState(null);
          }
        });
    };
    load();
    const timer = window.setInterval(load, 1000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [handle, sequenceId, sequenceRevision]);

  return { state, setState };
}

export function CaptionPanel({
  project,
  sequenceId,
  state,
  onChange,
}: {
  project: ProjectInfo;
  sequenceId: string | null;
  state: CaptionState | null;
  onChange: (next: CaptionState) => void;
}) {
  const data = useProjectData();
  const playback = usePlayback();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const cues = state?.cues ?? [];
  const selected = cues.find((cue) => cue.cue_id === selectedId) ?? null;
  const current = cueAtSource(cues, playback.playheadUs);
  const status = state?.status ?? null;

  useEffect(() => {
    if (!selected) {
      setDraft("");
      return;
    }
    setDraft(selected.effective_text);
  }, [selected?.cue_id, selected?.effective_text]);

  async function generate() {
    if (!sequenceId || project.read_only) {
      return;
    }
    data.setNotice(null);
    try {
      onChange(await generateCaptions(project.handle, sequenceId));
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function save() {
    if (!sequenceId || !selected || project.read_only) {
      return;
    }
    data.setNotice(null);
    try {
      onChange(await editCaptionCue(project.handle, sequenceId, selected.cue_id, draft));
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function reset() {
    if (!sequenceId || !selected || project.read_only) {
      return;
    }
    data.setNotice(null);
    try {
      onChange(await resetCaptionCue(project.handle, sequenceId, selected.cue_id));
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function exportSidecar(format: "srt" | "vtt") {
    if (!sequenceId || !exportEnabled(status) || project.read_only) {
      return;
    }
    data.setNotice(null);
    try {
      await exportCaptions(project.handle, sequenceId, format);
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  function choose(cue: CaptionCueView) {
    setSelectedId(cue.cue_id);
    playback.requestSeek(seekTargetUs(cue));
  }

  return (
    <section aria-label="Captions">
      <h2>Captions</h2>
      {!sequenceId ? <p>Captions follow the editorial sequence.</p> : <p>{captionStatusLabel(status)}</p>}
      {status === "stale" ? <p>{CAPTION_COPY.staleNote}</p> : null}
      <div className="row">
        {status === "ready" || status === "stale" ? (
          <button type="button" disabled={project.read_only} onClick={() => void generate()}>
            {CAPTION_COPY.regenerate}
          </button>
        ) : (
          <button type="button" disabled={!sequenceId || project.read_only} onClick={() => void generate()}>
            {CAPTION_COPY.generate}
          </button>
        )}
        <button type="button" disabled={!exportEnabled(status) || project.read_only} onClick={() => void exportSidecar("srt")}>
          {CAPTION_COPY.exportSrt}
        </button>
        <button type="button" disabled={!exportEnabled(status) || project.read_only} onClick={() => void exportSidecar("vtt")}>
          {CAPTION_COPY.exportVtt}
        </button>
      </div>
      {cues.length === 0 ? null : (
        <ul className="caption-cues">
          {cues.map((cue) => (
            <li key={cue.cue_id} className={current?.cue_id === cue.cue_id ? "is-current" : undefined}>
              <button type="button" onClick={() => choose(cue)}>
                <span className="numeric" dir="ltr">
                  {formatMicroseconds(cue.sequence_start_us)}–{formatMicroseconds(cue.sequence_end_us)}
                </span>
                <span dir={captionTextDirection()}>
                  <bdi>{cue.effective_text}</bdi>
                </span>
                {cue.manual_text ? <span>{CAPTION_COPY.edited}</span> : null}
              </button>
            </li>
          ))}
        </ul>
      )}
      {selected ? (
        <label>
          Caption text
          <textarea dir={captionTextDirection()} value={draft} onChange={(event) => setDraft(event.target.value)} />
          <span className="row">
            <button type="button" disabled={project.read_only} onClick={() => void save()}>{CAPTION_COPY.save}</button>
            <button type="button" disabled={project.read_only || !selected.manual_text} onClick={() => void reset()}>
              {CAPTION_COPY.useGenerated}
            </button>
          </span>
        </label>
      ) : null}
    </section>
  );
}
