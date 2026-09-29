import { useEffect, useState } from "react";

import { createJob, createReelDraft, listJobs, reelState, removeEditClip, resetEdit, splitEdit } from "../../api/client";
import { asFailure } from "../../api/errors";
import { isTerminal } from "../../api/jobs";
import type { JobInfo, ProjectInfo, ReelCandidate, ReelDraft, ReelState } from "../../api/types";
import { usePlayback } from "../../playback/PlaybackSession";
import { PreviewPlayer } from "../../playback/PreviewPlayer";
import { useProjectData } from "../../project/ProjectData";
import {
  REEL_PROFILE,
  candidateSeekUs,
  discoveryAction,
  draftTimeline,
  editorActions,
  reelPhase,
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
  const failed = jobs.some((job) => job.kind === "discover_reels" && job.media_asset_id === asset?.asset_id && job.status === "FAILED");
  const phase = reelPhase({ hasMedia: Boolean(asset), state, discovering, failed });
  const action = discoveryAction(phase);
  const selectedCandidate = state.candidates.find((item) => item.candidate_id === candidateId) ?? null;
  const selectedDraft = state.drafts.find((item) => item.sequence_id === draftId) ?? null;
  const timeline = selectedDraft ? draftTimeline(selectedDraft) : null;
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
        <p>{phaseText(phase, state.drafts.length, Boolean(selectedDraft))}</p>
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
        <PreviewPlayer project={project} />
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

function phaseText(phase: ReturnType<typeof reelPhase>, drafts: number, selected: boolean): string {
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
      return "Discovering reels.";
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
