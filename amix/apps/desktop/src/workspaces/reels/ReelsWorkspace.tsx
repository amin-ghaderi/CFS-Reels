import { useEffect, useState } from "react";

import { createJob, createReelDraft, listExports, listJobs, reelState, removeEditClip, resetEdit, sequenceRenderReadiness, splitEdit } from "../../api/client";
import { asFailure } from "../../api/errors";
import { isTerminal } from "../../api/jobs";
import type { ExportRecord, JobInfo, ProjectInfo, ReelCandidate, ReelDraft, ReelState, SequenceRenderReadiness } from "../../api/types";
import type { OutputFormat, OutputResolution } from "../../multicam/multicam";
import { usePlayback } from "../../playback/PlaybackSession";
import { PreviewPlayer } from "../../playback/PreviewPlayer";
import { useProjectData } from "../../project/ProjectData";
import {
  REEL_PROFILE,
  candidateSeekUs,
  discoveryAction,
  discoveryActivity,
  draftTimeline,
  editorActions,
  FORMAT_LABELS,
  PICTURE_LABELS,
  reelPhase,
  reelRenderSpec,
  renderEnabled,
  treatmentReason,
  type PictureTreatment,
} from "../../reels/reels";
import { formatMicroseconds } from "../../time/format";
import { TimelineCanvas } from "../../timeline/TimelineCanvas";
import { splitAllowed } from "../../timeline/timeline";
import { CaptionOverlay } from "../../captions/CaptionOverlay";
import { CaptionPanel, useCaptionTrack } from "../../captions/CaptionPanel";

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
  drafts: [],
};

export function ReelsWorkspace({ project }: { project: ProjectInfo }) {
  const data = useProjectData();
  const playback = usePlayback();
  const asset = data.selected;
  const [state, setState] = useState<ReelState>(EMPTY);
  const [jobs, setJobs] = useState<JobInfo[]>([]);
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

  const timeline = selectedDraft ? draftTimeline(selectedDraft) : null;
  const captions = useCaptionTrack(project.handle, selectedDraft?.sequence_id ?? null, selectedDraft?.revision ?? null);
  const selectedClip = timeline?.clips.find((clip) => clip.clip_id === clipId) ?? null;

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

  function chooseCandidate(candidate: ReelCandidate) {
    setCandidateId(candidate.candidate_id);
    playback.requestSeek(candidateSeekUs(candidate));
  }

  async function makeDraft() {
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
      }
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
    <div className="reels-workspace">
      <section className="reels-context">
        <h1>Reels</h1>
        <p>{phaseText(phase, state.drafts.length, Boolean(selectedDraft), state.local_ai_state)}</p>
        {action ? <button type="button" onClick={() => void discover()}>{action}</button> : null}
        <h2>Candidates</h2>
        <ul className="review-list">
          {state.candidates.map((candidate) => (
            <li key={candidate.candidate_id} className={candidate.candidate_id === candidateId ? "is-current" : ""}>
              <button type="button" onClick={() => chooseCandidate(candidate)}>
                <span dir="auto">{candidate.title}</span>
                <span dir="ltr"> {formatMicroseconds(candidate.start_us)}–{formatMicroseconds(candidate.end_us)}</span>
              </button>
            </li>
          ))}
        </ul>
        <h2>Drafts</h2>
        {state.drafts.length === 0 ? <p>No reel drafts.</p> : null}
        <ul className="review-list">
          {state.drafts.map((draft) => (
            <li key={draft.sequence_id} className={draft.sequence_id === draftId ? "is-current" : ""}>
              <button type="button" onClick={() => { setDraftId(draft.sequence_id); setClipId(null); }}>
                <span dir="auto">{draft.display_name}</span>
                <span dir="ltr"> {formatMicroseconds(draft.duration_us)} · rev {draft.revision}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section className="reels-main">
        <PreviewPlayer
          project={project}
          overlay={<CaptionOverlay cues={captions.state?.cues ?? []} playheadUs={playback.playheadUs} />}
        />
        {timeline ? (
          <TimelineCanvas
            timeline={timeline}
            playheadUs={playback.playheadUs}
            selectedClipId={clipId}
            showCamera={false}
            onSeek={(sourceUs) => playback.requestSeek(sourceUs)}
            onSelect={setClipId}
          />
        ) : <p>Select a reel draft to edit it.</p>}
        {selectedDraft ? (
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
          </div>
        ) : null}
        <CaptionPanel
          project={project}
          sequenceId={selectedDraft?.sequence_id ?? null}
          state={captions.state}
          onChange={captions.setState}
        />
        {selectedDraft && readiness ? (
          <section aria-label="Render">
            <h2>Render</h2>
            <label>
              Picture
              <select value={picture} onChange={(event) => setPicture(event.target.value as PictureTreatment)}>
                <option value="source_program">{PICTURE_LABELS.source_program}</option>
                <option value="multicam" disabled={!readiness.multicam_ready}>{PICTURE_LABELS.multicam}</option>
              </select>
            </label>
            {!readiness.multicam_ready ? <p>{treatmentReason(readiness.multicam_reason)}</p> : null}
            <label>
              Format
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
            <button
              type="button"
              disabled={!renderEnabled(readiness, picture) || rendering}
              onClick={() => void renderDraft()}
            >
              Render
            </button>
            {exportsForDraft.length === 0 ? <p>No completed exports for this draft.</p> : (
              <ul className="review-list">
                {exportsForDraft.map((row) => (
                  <li key={row.job_id}>
                    {row.filename} · {row.visual_treatment === "source_program" ? PICTURE_LABELS.source_program : PICTURE_LABELS.multicam}
                    {" · "}{row.width ?? "?"}×{row.height ?? "?"} · {row.aspect ?? ""} · {row.status}
                  </li>
                ))}
              </ul>
            )}
          </section>
        ) : null}
        {confirmReset ? (
          <div className="row">
            <span>Reset this reel draft to its original candidate range?</span>
            <button type="button" onClick={() => void reset()}>Reset</button>
            <button type="button" onClick={() => setConfirmReset(false)}>Cancel</button>
          </div>
        ) : null}
      </section>
      <Inspector candidate={selectedCandidate} draft={selectedDraft} onCreate={() => void makeDraft()} />
    </div>
  );
}

function Inspector({
  candidate,
  draft,
  onCreate,
}: {
  candidate: ReelCandidate | null;
  draft: ReelDraft | null;
  onCreate: () => void;
}) {
  return (
    <section className="reels-inspector" aria-label="Reel details">
      {candidate ? (
        <>
          <h2 dir="auto">{candidate.title}</h2>
          <p dir="auto">{candidate.summary}</p>
          <p dir="auto">{candidate.hook}</p>
          <p dir="ltr">{formatMicroseconds(candidate.start_us)} – {formatMicroseconds(candidate.end_us)}</p>
          <p>{candidate.thread_title}</p>
          <p>{candidate.participant_names.join(", ")}</p>
          <button type="button" onClick={onCreate}>Create Reel Draft</button>
        </>
      ) : null}
      {draft ? (
        <>
          <h3 dir="auto">{draft.display_name}</h3>
          <p dir="ltr">{formatMicroseconds(draft.source_start_us)} – {formatMicroseconds(draft.source_end_us)}</p>
          <p>Revision {draft.revision}</p>
          <p>Kept {formatMicroseconds(draft.duration_us)}</p>
        </>
      ) : null}
    </section>
  );
}

function phaseText(phase: ReturnType<typeof reelPhase>, drafts: number, selected: boolean, localAiState?: string | null): string {
  switch (phase) {
    case "no_media":
      return "No media selected.";
    case "no_transcript":
      return "No transcript.";
    case "turns_required":
      return "Speaker turns are required.";
    case "map_required":
      return "A conversation map is required.";
    case "map_stale":
      return "The conversation map is stale.";
    case "provider_unavailable":
      return "Semantic provider is unavailable.";
    case "discovering":
      return discoveryActivity(localAiState);
    case "failed":
      return "Reel discovery failed.";
    case "discovery_stale":
      return drafts ? "Discovery is stale. Existing reel drafts are unchanged." : "Discovery is stale.";
    case "candidates_ready":
      return selected ? "Reel draft selected." : drafts ? "Candidates are ready." : "Candidates are ready. No reel drafts.";
    default:
      return "Ready to discover reels.";
  }
}
