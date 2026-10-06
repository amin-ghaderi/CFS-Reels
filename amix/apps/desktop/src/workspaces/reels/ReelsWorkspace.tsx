import { useEffect, useState } from "react";

import { createJob, createReelDraft, dismissReelSuggestion, listExports, listJobs, reelState, removeEditClip, resetEdit, sequenceRenderReadiness, splitEdit } from "../../api/client";
import { asFailure } from "../../api/errors";
import { isTerminal } from "../../api/jobs";
import type { ExportRecord, JobInfo, ProjectInfo, ReelCandidate, ReelDraft, ReelState, SequenceRenderReadiness } from "../../api/types";
import { CaptionOverlay } from "../../captions/CaptionOverlay";
import { CaptionPanel, useCaptionTrack } from "../../captions/CaptionPanel";
import type { OutputFormat, OutputResolution } from "../../multicam/multicam";
import { usePlayback } from "../../playback/PlaybackSession";
import { PreviewPlayer } from "../../playback/PreviewPlayer";
import { useProjectData } from "../../project/ProjectData";
import {
  DISMISS_LABEL,
  EXPORT_REEL_LABEL,
  FORMAT_LABELS,
  PICTURE_LABELS,
  REEL_PROFILE,
  SUGGESTIONS_LABEL,
  USE_REEL_LABEL,
  candidateSeekUs,
  discoveryAction,
  discoveryActivity,
  draftTimeline,
  editorActions,
  pictureChoices,
  reelPhase,
  reelRenderSpec,
  renderEnabled,
  suggestionEmptyMessage,
  treatmentReason,
  type PictureTreatment,
} from "../../reels/reels";
import { formatMicroseconds } from "../../time/format";
import { TimelineCanvas } from "../../timeline/TimelineCanvas";
import { splitAllowed } from "../../timeline/timeline";

const EMPTY: ReelState = {
  transcript_present: false,
  turns_ready: false,
  blocking_reason: null,
  provider_configured: false,
  capability_ready: false,
  offline_blocked: false,
  map_present: false,
  map_stale: false,
  discovery_present: false,
  discovery_stale: false,
  reel_discovery_run_id: null,
  candidates: [],
  dismissed_count: 0,
  drafts: [],
};

type ReelMode = "suggestions" | "edit" | "export";

export function ReelsWorkspace({ project }: { project: ProjectInfo }) {
  const data = useProjectData();
  const playback = usePlayback();
  const asset = data.selected;
  const [state, setState] = useState<ReelState>(EMPTY);
  const [jobs, setJobs] = useState<JobInfo[]>([]);
  const [mode, setMode] = useState<ReelMode>("suggestions");
  const [candidateId, setCandidateId] = useState<string | null>(null);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [clipId, setClipId] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [format, setFormat] = useState<OutputFormat>("16:9");
  const [resolution, setResolution] = useState<OutputResolution>("1080");
  const [picture, setPicture] = useState<PictureTreatment>("source_program");
  const [readiness, setReadiness] = useState<SequenceRenderReadiness | null>(null);
  const [exportsForDraft, setExportsForDraft] = useState<ExportRecord[]>([]);

  useEffect(() => {
    if (!asset) {
      setState(EMPTY);
      return;
    }
    let cancel = false;
    const load = () => {
      void reelState(project.handle, asset.asset_id)
        .then((next) => {
          if (!cancel) {
            setState(next);
          }
        })
        .catch((error: unknown) => {
          if (!cancel) {
            data.setNotice(asFailure(error));
          }
        });
      void listJobs(project.handle)
        .then((next) => {
          if (!cancel) {
            setJobs(next);
          }
        })
        .catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, 1000);
    return () => {
      cancel = true;
      window.clearInterval(timer);
    };
  }, [asset, data, project.handle]);

  const discovering = jobs.some((job) => job.kind === "discover_reels" && job.media_asset_id === asset?.asset_id && !isTerminal(job.status));
  const rendering = jobs.some((job) => job.kind === "render_sequence" && job.spec?.sequence_id === draftId && !isTerminal(job.status));
  const failed = jobs.some((job) => job.kind === "discover_reels" && job.media_asset_id === asset?.asset_id && job.status === "FAILED");
  const phase = reelPhase({ hasMedia: Boolean(asset), state, discovering, failed });
  const action = discoveryAction(phase);
  const selectedCandidate = state.candidates.find((item) => item.candidate_id === candidateId) ?? null;
  const selectedDraft = state.drafts.find((item) => item.sequence_id === draftId) ?? null;
  const editing = mode === "edit" && selectedDraft != null;
  const exporting = mode === "export" && selectedDraft != null;

  useEffect(() => {
    if (!asset || !draftId) {
      setReadiness(null);
      setExportsForDraft([]);
      return;
    }
    let cancel = false;
    void sequenceRenderReadiness(project.handle, asset.asset_id, draftId)
      .then((next) => {
        if (!cancel) {
          setReadiness(next);
          if (!next.multicam_ready) {
            setPicture("source_program");
          }
        }
      })
      .catch(() => undefined);
    void listExports(project.handle, asset.asset_id, draftId)
      .then((next) => {
        if (!cancel) {
          setExportsForDraft(next);
        }
      })
      .catch(() => undefined);
    return () => {
      cancel = true;
    };
  }, [asset, draftId, jobs, project.handle, state.drafts]);

  const timeline = editing && selectedDraft ? draftTimeline(selectedDraft) : null;
  const captions = useCaptionTrack(
    project.handle,
    (editing || exporting) ? selectedDraft?.sequence_id ?? null : null,
    (editing || exporting) ? selectedDraft?.revision ?? null : null,
  );
  const selectedClip = timeline?.clips.find((clip) => clip.clip_id === clipId) ?? null;
  const previewRange = (editing || exporting) && selectedDraft
    ? { startUs: selectedDraft.source_start_us, endUs: selectedDraft.source_end_us }
    : selectedCandidate
      ? { startUs: selectedCandidate.start_us, endUs: selectedCandidate.end_us }
      : null;
  const emptyMessage = state.discovery_present
    ? suggestionEmptyMessage(state.candidates.length, state.dismissed_count ?? 0)
    : null;
  const choices = readiness ? pictureChoices(readiness) : [];

  async function discover() {
    if (!asset) {
      return;
    }
    data.setNotice(null);
    try {
      await createJob(project.handle, "discover_reels", {
        mediaAssetId: asset.asset_id,
        spec: { profile_id: REEL_PROFILE },
      });
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  function chooseSuggestion(candidate: ReelCandidate) {
    setMode("suggestions");
    setCandidateId(candidate.candidate_id);
    playback.requestSeek(candidateSeekUs(candidate));
  }

  function openReel(draft: ReelDraft) {
    setDraftId(draft.sequence_id);
    setClipId(null);
    setMode("edit");
    playback.requestSeek(draft.source_start_us);
  }

  async function useReel() {
    if (!asset || !selectedCandidate) {
      return;
    }
    data.setNotice(null);
    try {
      const next = await createReelDraft(project.handle, asset.asset_id, selectedCandidate.candidate_id);
      setState(next);
      const created = [...next.drafts].reverse().find((item) => item.origin_candidate_id === selectedCandidate.candidate_id);
      if (created) {
        setDraftId(created.sequence_id);
        setClipId(null);
        setMode("edit");
        playback.requestSeek(created.source_start_us);
      }
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function dismiss() {
    if (!asset || !selectedCandidate) {
      return;
    }
    data.setNotice(null);
    try {
      const next = await dismissReelSuggestion(project.handle, asset.asset_id, selectedCandidate.candidate_id);
      setState(next);
      setCandidateId(null);
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function renderDraft() {
    if (!asset || !selectedDraft || !readiness || !renderEnabled(readiness, picture)) {
      return;
    }
    const request = reelRenderSpec(selectedDraft.sequence_id, selectedDraft.revision, picture, format, resolution);
    data.setNotice(null);
    try {
      await createJob(project.handle, request.kind, { mediaAssetId: asset.asset_id, spec: request.spec });
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function refresh() {
    if (!asset) {
      return;
    }
    setState(await reelState(project.handle, asset.asset_id));
  }

  async function split() {
    if (!asset || !selectedDraft || !selectedClip || !splitAllowed(selectedClip, playback.playheadUs)) {
      return;
    }
    data.setNotice(null);
    try {
      await splitEdit(project.handle, asset.asset_id, selectedDraft.sequence_id, selectedClip.clip_id, playback.playheadUs);
      await refresh();
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function remove() {
    if (!asset || !selectedDraft || !selectedClip) {
      return;
    }
    data.setNotice(null);
    try {
      await removeEditClip(project.handle, asset.asset_id, selectedDraft.sequence_id, selectedClip.clip_id);
      setClipId(null);
      await refresh();
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function reset() {
    if (!asset || !selectedDraft) {
      return;
    }
    data.setNotice(null);
    try {
      await resetEdit(project.handle, asset.asset_id, selectedDraft.sequence_id);
      setConfirmReset(false);
      setClipId(null);
      await refresh();
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  return (
    <div className="reels-workspace sticky-actions">
      <section className="reels-context">
        <h1>Reels</h1>
        <p>{phaseText(phase, state.local_ai_state, editing)}</p>
        {action ? <button type="button" onClick={() => void discover()}>{action}</button> : null}
        <h2>{SUGGESTIONS_LABEL}</h2>
        {emptyMessage ? <p>{emptyMessage}</p> : null}
        <ul className="review-list">
          {state.candidates.map((candidate) => (
            <li key={candidate.candidate_id} className={candidate.candidate_id === candidateId && mode === "suggestions" ? "is-current" : ""}>
              <button type="button" onClick={() => chooseSuggestion(candidate)}>
                <span dir="auto">{candidate.title}</span>
                <span dir="ltr"> {formatMicroseconds(candidate.duration_us)}</span>
                <span dir="ltr"> Episode {formatMicroseconds(candidate.start_us)}–{formatMicroseconds(candidate.end_us)}</span>
                {candidate.thread_title ? <span dir="auto"> {candidate.thread_title}</span> : null}
                {candidate.hook ? <span dir="auto"> {candidate.hook}</span> : <span dir="auto"> {candidate.summary}</span>}
              </button>
            </li>
          ))}
        </ul>
        {state.drafts.length > 0 ? (
          <>
            <h2>Your Reels</h2>
            <ul className="review-list">
              {state.drafts.map((draft) => (
                <li key={draft.sequence_id} className={draft.sequence_id === draftId && (editing || exporting) ? "is-current" : ""}>
                  <button type="button" onClick={() => openReel(draft)}>
                    <span dir="auto">{draft.display_name}</span>
                    <span dir="ltr"> {formatMicroseconds(draft.duration_us)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </section>
      <section className="reels-main">
        <PreviewPlayer
          project={project}
          range={previewRange}
          overlay={(editing || exporting) ? <CaptionOverlay cues={captions.state?.cues ?? []} playheadUs={playback.playheadUs} /> : undefined}
        />
        {mode === "suggestions" && selectedCandidate ? (
          <div className="row">
            <p dir="ltr">Reel {formatMicroseconds(selectedCandidate.duration_us)}</p>
            <p dir="ltr">Episode {formatMicroseconds(selectedCandidate.start_us)}–{formatMicroseconds(selectedCandidate.end_us)}</p>
            <button type="button" onClick={() => void useReel()}>{USE_REEL_LABEL}</button>
            <button type="button" onClick={() => void dismiss()}>{DISMISS_LABEL}</button>
          </div>
        ) : null}
        {editing && timeline && selectedDraft ? (
          <>
            <p dir="ltr">Kept {formatMicroseconds(selectedDraft.duration_us)}</p>
            <TimelineCanvas
              timeline={timeline}
              playheadUs={playback.playheadUs}
              selectedClipId={clipId}
              showCamera={false}
              onSeek={(sourceUs) => playback.requestSeek(sourceUs)}
              onSelect={setClipId}
            />
            <div className="row">
              {editorActions().map((label) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => {
                    if (label === "Split at Playhead") {
                      void split();
                    } else if (label === "Remove Clip") {
                      void remove();
                    } else {
                      setConfirmReset(true);
                    }
                  }}
                >
                  {label}
                </button>
              ))}
              <button type="button" onClick={() => setMode("export")}>{EXPORT_REEL_LABEL}</button>
              <button type="button" onClick={() => setMode("suggestions")}>Back to suggestions</button>
            </div>
            <CaptionPanel
              project={project}
              sequenceId={selectedDraft.sequence_id}
              state={captions.state}
              onChange={captions.setState}
            />
          </>
        ) : null}
        {mode === "export" && selectedDraft && readiness ? (
          <section aria-label="Export">
            <h2>Export</h2>
            <label>
              Aspect ratio
              <select value={format} onChange={(event) => setFormat(event.target.value as OutputFormat)}>
                <option value="16:9">{FORMAT_LABELS["16:9"]}</option>
                <option value="9:16">{FORMAT_LABELS["9:16"]}</option>
              </select>
            </label>
            <label>
              Resolution
              <select value={resolution} onChange={(event) => setResolution(event.target.value as OutputResolution)}>
                <option value="1080">1080</option>
                <option value="720">720</option>
              </select>
            </label>
            <label>
              Picture
              <select value={picture} onChange={(event) => setPicture(event.target.value as PictureTreatment)}>
                {choices.map((choice) => (
                  <option key={choice} value={choice}>{PICTURE_LABELS[choice]}</option>
                ))}
              </select>
            </label>
            {!readiness.multicam_ready ? <p>{treatmentReason(readiness.multicam_reason) || "Multicam is not available for this reel."}</p> : null}
            {!readiness.source_program_ready ? <p>{treatmentReason(readiness.source_program_reason)}</p> : null}
            <p>Captions export as a subtitle file from the edit step. This video export does not burn them in.</p>
            <button
              type="button"
              disabled={!renderEnabled(readiness, picture) || rendering}
              onClick={() => void renderDraft()}
            >
              {rendering ? "Exporting…" : EXPORT_REEL_LABEL}
            </button>
            {exportsForDraft.length > 0 ? (
              <ul className="review-list">
                {exportsForDraft.map((row) => (
                  <li key={row.job_id}>
                    {row.filename} · {row.visual_treatment === "source_program" ? PICTURE_LABELS.source_program : PICTURE_LABELS.multicam}
                    {" · "}{row.width ?? "?"}×{row.height ?? "?"} · {row.aspect ?? ""} · {row.status}
                  </li>
                ))}
              </ul>
            ) : null}
            <button type="button" onClick={() => setMode("edit")}>Back to edit</button>
          </section>
        ) : null}
        {confirmReset ? (
          <div className="row">
            <span>Reset this reel to the original suggestion?</span>
            <button type="button" onClick={() => void reset()}>Reset to original suggestion</button>
            <button type="button" onClick={() => setConfirmReset(false)}>Cancel</button>
          </div>
        ) : null}
      </section>
      <section className="reels-inspector" aria-label="Reel details">
        {mode === "suggestions" && selectedCandidate ? (
          <>
            <h2 dir="auto">{selectedCandidate.title}</h2>
            <p dir="auto">{selectedCandidate.hook}</p>
            <p dir="auto">{selectedCandidate.summary}</p>
            <p dir="ltr">Reel {formatMicroseconds(selectedCandidate.duration_us)}</p>
            <p dir="ltr">Episode {formatMicroseconds(selectedCandidate.start_us)} – {formatMicroseconds(selectedCandidate.end_us)}</p>
            {selectedCandidate.thread_title ? <p dir="auto">{selectedCandidate.thread_title}</p> : null}
            <button type="button" onClick={() => void useReel()}>{USE_REEL_LABEL}</button>
          </>
        ) : null}
        {(editing || exporting) && selectedDraft ? (
          <>
            <h2 dir="auto">{selectedDraft.display_name}</h2>
            <p dir="ltr">Kept {formatMicroseconds(selectedDraft.duration_us)}</p>
            <p dir="ltr">Episode {formatMicroseconds(selectedDraft.source_start_us)} – {formatMicroseconds(selectedDraft.source_end_us)}</p>
          </>
        ) : null}
      </section>
    </div>
  );
}

function phaseText(phase: ReturnType<typeof reelPhase>, localAiState: string | null | undefined, editing: boolean): string {
  switch (phase) {
    case "no_media":
      return "No media selected.";
    case "no_transcript":
      return "Create a transcript to continue.";
    case "turns_required":
      return "Analyze speakers before discovering reels.";
    case "map_required":
      return "Map the conversation before discovering reels.";
    case "map_stale":
      return "The conversation map is stale.";
    case "provider_unavailable":
      return "Semantic provider is unavailable.";
    case "discovering":
      return discoveryActivity(localAiState);
    case "failed":
      return "Reel discovery failed.";
    case "discovery_stale":
      return "Discovery is stale. Reels you already chose are unchanged.";
    case "candidates_ready":
      return editing ? "Editing this reel." : "Reel suggestions are ready.";
    default:
      return "Ready to discover reels.";
  }
}
