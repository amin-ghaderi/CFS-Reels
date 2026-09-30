import { useEffect, useState } from "react";

import { createEdit, createJob, listExports, listJobs, multicamReadiness, overlapState, removeEditClip, resetEdit, saveShotOverride, shotPlanState, splitEdit, timelineState } from "../../api/client";
import { asFailure, jobProblemMessage } from "../../api/errors";
import { isTerminal } from "../../api/jobs";
import type { ExportRecord, JobInfo, MulticamReadiness, OverlapState, ProjectInfo, ShotPlanState, ShotView, TimelineState } from "../../api/types";
import { PreviewPlayer } from "../../playback/PreviewPlayer";
import { usePlayback } from "../../playback/PlaybackSession";
import { useProjectData } from "../../project/ProjectData";
import { formatMicroseconds } from "../../time/format";
import {
  automaticLabel,
  currentShot,
  latestFailure,
  multicamPhase,
  phaseLabel,
  presetId,
  regionSeekUs,
  renderBlockReason,
  renderJobSpec,
  runningJob,
  shotLabel,
  shotSeekUs,
  shotStatus,
  type OutputFormat,
  type OutputResolution,
} from "../../multicam/multicam";
import { TimelineCanvas } from "../../timeline/TimelineCanvas";
import { requestReset, splitAllowed } from "../../timeline/timeline";
import { CaptionOverlay } from "../../captions/CaptionOverlay";
import { CaptionPanel, useCaptionTrack } from "../../captions/CaptionPanel";

const EMPTY_OVERLAP: OverlapState = {
  run_id: null,
  stale: false,
  window_start_us: null,
  window_end_us: null,
  profile_id: null,
  regions: [],
};

const EMPTY_TIMELINE: TimelineState = {
  sequence_id: null,
  revision: null,
  fingerprint: null,
  source_start_us: null,
  source_end_us: null,
  duration_us: null,
  clips: [],
  removed: [],
  camera: [],
  protected: [],
};

const EMPTY_PLAN: ShotPlanState = {
  run_id: null,
  stale: false,
  start_us: null,
  end_us: null,
  shots: [],
};

export function MulticamWorkspace({ project }: { project: ProjectInfo }) {
  const data = useProjectData();
  const playback = usePlayback();
  const asset = data.selected?.role === "master" ? data.selected : null;
  const [jobs, setJobs] = useState<JobInfo[]>([]);
  const [readiness, setReadiness] = useState<MulticamReadiness | null>(null);
  const [overlap, setOverlap] = useState<OverlapState>(EMPTY_OVERLAP);
  const [plan, setPlan] = useState<ShotPlanState>(EMPTY_PLAN);
  const [picked, setPicked] = useState<ShotView | null>(null);
  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [timeline, setTimeline] = useState<TimelineState>(EMPTY_TIMELINE);
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [format, setFormat] = useState<OutputFormat>("16:9");
  const [resolution, setResolution] = useState<OutputResolution>("1080");

  useEffect(() => {
    if (!asset) {
      setReadiness(null);
      setOverlap(EMPTY_OVERLAP);
      setPlan(EMPTY_PLAN);
      setExports([]);
      setTimeline(EMPTY_TIMELINE);
      return;
    }
    let stop = false;
    const load = () => {
      void Promise.all([
        listJobs(project.handle),
        multicamReadiness(project.handle, asset.asset_id),
        overlapState(project.handle, asset.asset_id),
        shotPlanState(project.handle, asset.asset_id),
        listExports(project.handle, asset.asset_id),
        timelineState(project.handle, asset.asset_id),
      ]).then(([listed, nextReady, nextOverlap, nextPlan, nextExports, nextTimeline]) => {
        if (stop) {
          return;
        }
        setJobs(listed);
        setReadiness(nextReady);
        setOverlap(nextOverlap);
        setPlan(nextPlan);
        setExports(nextExports);
        setTimeline(nextTimeline);
      }).catch((error: unknown) => {
        if (!stop) {
          data.setNotice(asFailure(error));
        }
      });
    };
    load();
    const timer = window.setInterval(load, 1000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [project.handle, asset?.asset_id]);

  const phase = multicamPhase(asset?.asset_id ?? null, readiness, jobs);
  const captions = useCaptionTrack(project.handle, timeline.sequence_id, timeline.revision);
  const waiting = Boolean(asset) && readiness === null && !runningJob(jobs, asset?.asset_id ?? "", "detect_overlap") && !runningJob(jobs, asset?.asset_id ?? "", "build_multicam_plan");
  const followed = currentShot(plan.shots, playback.playheadUs);
  const shown = followed ?? (picked ? plan.shots.find((shot) => shot.shot_id === picked.shot_id) ?? null : null);
  const overlapJob = asset ? runningJob(jobs, asset.asset_id, "detect_overlap") : null;
  const planJob = asset ? runningJob(jobs, asset.asset_id, "build_multicam_plan") : null;
  const failed = asset ? latestFailure(jobs, asset.asset_id) : null;
  const renderJob = asset
    ? runningJob(jobs, asset.asset_id, "render_sequence") ?? runningJob(jobs, asset.asset_id, "render_multicam")
    : null;
  const chosenPreset = presetId(format, resolution);
  const block = readiness ? renderBlockReason({
    planPresent: Boolean(plan.run_id),
    planStale: Boolean(plan.stale || readiness.plan_stale),
    sourceAvailable: Boolean(asset),
    ffmpegReady: readiness.ffmpeg_ready,
    presetKnown: Boolean(chosenPreset),
  }) : "Loading";

  async function analyzeOverlap() {
    if (!asset) {
      return;
    }
    data.setNotice(null);
    try {
      await createJob(project.handle, "detect_overlap", {
        mediaAssetId: asset.asset_id,
        spec: { profile: "amix.overlap.lip_audio.v1" },
      });
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function buildPlan() {
    if (!asset) {
      return;
    }
    data.setNotice(null);
    try {
      await createJob(project.handle, "build_multicam_plan", { mediaAssetId: asset.asset_id });
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function chooseOverride(decision: string, participantId?: string) {
    if (!asset || !plan.run_id || !shown) {
      return;
    }
    data.setNotice(null);
    try {
      const next = await saveShotOverride(project.handle, asset.asset_id, {
        shot_plan_run_id: plan.run_id,
        shot_id: shown.shot_id,
        decision,
        participant_id: participantId ?? null,
      });
      setPlan(next);
      setPicked(next.shots.find((shot) => shot.shot_id === shown.shot_id) ?? null);
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function renderProgram() {
    if (!asset || !plan.run_id || block) {
      return;
    }
    data.setNotice(null);
    const request = renderJobSpec(
      format,
      resolution,
      plan.run_id,
      timeline.sequence_id !== null && timeline.revision !== null
        ? { sequenceId: timeline.sequence_id, revision: timeline.revision }
        : undefined,
    );
    try {
      await createJob(project.handle, request.kind, { mediaAssetId: asset.asset_id, spec: request.spec });
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  const selectedClip = timeline.clips.find((clip) => clip.clip_id === selectedClipId) ?? null;
  const canSplit = splitAllowed(selectedClip, playback.playheadUs);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);
      if (typing || !asset || !timeline.sequence_id || !selectedClip) {
        return;
      }
      if (event.key === "s" || event.key === "S") {
        if (!canSplit) {
          return;
        }
        event.preventDefault();
        void splitEdit(project.handle, asset.asset_id, timeline.sequence_id, selectedClip.clip_id, playback.playheadUs)
          .then(setTimeline)
          .catch((error: unknown) => data.setNotice(asFailure(error)));
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        void removeEditClip(project.handle, asset.asset_id, timeline.sequence_id, selectedClip.clip_id)
          .then((next) => {
            setSelectedClipId(null);
            setTimeline(next);
          })
          .catch((error: unknown) => data.setNotice(asFailure(error)));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [asset, timeline.sequence_id, selectedClip, canSplit, playback.playheadUs, project.handle]);

  async function makeEdit() {
    if (!asset) {
      return;
    }
    data.setNotice(null);
    try {
      setTimeline(await createEdit(project.handle, asset.asset_id));
      setConfirmReset(false);
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function splitSelected() {
    if (!asset || !timeline.sequence_id || !selectedClip || !canSplit) {
      return;
    }
    data.setNotice(null);
    try {
      setTimeline(await splitEdit(project.handle, asset.asset_id, timeline.sequence_id, selectedClip.clip_id, playback.playheadUs));
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function removeSelected() {
    if (!asset || !timeline.sequence_id || !selectedClip) {
      return;
    }
    data.setNotice(null);
    try {
      setSelectedClipId(null);
      setTimeline(await removeEditClip(project.handle, asset.asset_id, timeline.sequence_id, selectedClip.clip_id));
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function resetSelected() {
    if (!asset || !timeline.sequence_id) {
      return;
    }
    const step = requestReset(confirmReset);
    setConfirmReset(step.confirming);
    if (!step.commit) {
      return;
    }
    data.setNotice(null);
    try {
      setSelectedClipId(null);
      setTimeline(await resetEdit(project.handle, asset.asset_id, timeline.sequence_id));
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  return (
    <div className="multicam">
      <div className="multicam-main">
        <PreviewPlayer
          project={project}
          overlay={<CaptionOverlay cues={captions.state?.cues ?? []} playheadUs={playback.playheadUs} />}
        />
        <p className="shot-indicator">{shown ? shotLabel(shown) : "Wide"}</p>
        <section className="stack" aria-label="Multicam status">
          <h2>{waiting ? "Loading" : phaseLabel(phase)}</h2>
          {phase === "failed" && failed ? <p>{jobProblemMessage(failed.error_code)}</p> : null}
          {phase === "overlap_stale" ? <p>Layout changed. Overlap can be analyzed again. The previous result stays stored.</p> : null}
          {phase === "plan_stale" ? <p>Plan out of date. Rebuild when you are ready. The previous plan stays stored.</p> : null}
          <div className="row">
            <button type="button" onClick={() => void analyzeOverlap()} disabled={waiting || !asset || Boolean(overlapJob) || phase === "no_transcript" || phase === "speaker_required" || phase === "layout_incomplete" || phase === "vision_missing" || readiness?.vision_state !== "READY"}>
              {overlapJob && !isTerminal(overlapJob.status) ? "Analyzing overlap" : "Analyze overlap"}
            </button>
            <button type="button" onClick={() => void buildPlan()} disabled={!readiness?.plan_ready || Boolean(planJob)}>
              {planJob ? "Building plan" : "Build plan"}
            </button>
          </div>
        </section>
        <section aria-label="Overlap regions">
          <h2>Overlap</h2>
          {overlap.regions.length === 0 ? <p>No overlap regions.</p> : (
            <ul className="review-list">
              {overlap.regions.map((region) => (
                <li key={`${region.start_us}-${region.end_us}`}>
                  <button type="button" onClick={() => playback.requestSeek(regionSeekUs(region))}>
                    {formatMicroseconds(region.start_us)} – {formatMicroseconds(region.end_us)} · {formatMicroseconds(region.duration_us)} · {region.confidence.toFixed(2)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section aria-label="Shot list">
          <h2>Shots</h2>
          {plan.shots.length === 0 ? <p>No automatic shot plan.</p> : (
            <ul className="review-list">
              {plan.shots.map((shot) => {
                const active = followed?.start_us === shot.start_us && followed.end_us === shot.end_us;
                return (
                  <li key={shot.shot_id} className={active ? "is-current" : undefined}>
                    <button type="button" onClick={() => { setPicked(shot); playback.requestSeek(shotSeekUs(shot)); }}>
                      {formatMicroseconds(shot.start_us)} – {formatMicroseconds(shot.end_us)} · {shotLabel(shot)} · {shotStatus(shot)}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
        <section aria-label="Timeline">
          <h2>Timeline</h2>
          <p>Source preview. Removed ranges stay out of the export and are not skipped during playback.</p>
          <div className="row">
            <button type="button" onClick={() => void makeEdit()} disabled={!plan.run_id || plan.stale}>Create edit</button>
            <button type="button" onClick={() => void splitSelected()} disabled={!canSplit}>Split at playhead</button>
            <button type="button" onClick={() => void removeSelected()} disabled={!selectedClip}>Remove clip</button>
            <button type="button" onClick={() => void resetSelected()} disabled={!timeline.sequence_id}>
              {confirmReset ? "Confirm reset" : "Reset edit"}
            </button>
            {confirmReset ? <button type="button" onClick={() => setConfirmReset(false)}>Cancel reset</button> : null}
          </div>
          <p>
            {selectedClip
              ? `Selected ${formatMicroseconds(selectedClip.source_start_us)} – ${formatMicroseconds(selectedClip.source_end_us)}`
              : "No clip selected"}
            {timeline.duration_us !== null ? ` · Edit length ${formatMicroseconds(timeline.duration_us)}` : ""}
          </p>
          {timeline.source_start_us !== null && timeline.source_end_us !== null ? (
            <TimelineCanvas
              timeline={timeline}
              playheadUs={playback.playheadUs}
              selectedClipId={selectedClipId}
              onSeek={(sourceUs) => playback.requestSeek(sourceUs)}
              onSelect={setSelectedClipId}
            />
          ) : <p>No source range yet.</p>}
        </section>
        <CaptionPanel
          project={project}
          sequenceId={timeline.sequence_id}
          state={captions.state}
          onChange={captions.setState}
        />
        <section aria-label="Render">
          <h2>Render</h2>
          <p>Output size. This does not rebuild the shot plan.</p>
          <div className="row">
            <label>
              Format
              <select value={format} onChange={(event) => setFormat(event.target.value as OutputFormat)}>
                <option value="16:9">Landscape 16:9</option>
                <option value="9:16">Portrait 9:16</option>
              </select>
            </label>
            <label>
              Resolution
              <select value={resolution} onChange={(event) => setResolution(event.target.value as OutputResolution)}>
                <option value="1080">1080</option>
                <option value="720">720</option>
              </select>
            </label>
            <button type="button" onClick={() => void renderProgram()} disabled={Boolean(block) || Boolean(renderJob)}>
              {renderJob ? "Rendering" : "Render"}
            </button>
          </div>
          {block ? <p>{block}</p> : null}
          {exports.length === 0 ? <p>No completed exports.</p> : (
            <ul className="review-list">
              {exports.map((row) => (
                <li key={row.job_id}>
                  {row.filename} · {row.width ?? "?"}×{row.height ?? "?"} · {row.aspect ?? ""} · {row.created_at ?? ""} · {row.status}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <aside className="multicam-inspector" aria-label="Current shot">
        <h2>Current</h2>
        {shown ? (
          <>
            <p>{shotLabel(shown)}</p>
            <p>{shotStatus(shown)}{shown.locked ? " / Locked" : ""}</p>
            <p>{formatMicroseconds(shown.start_us)} – {formatMicroseconds(shown.end_us)}</p>
            <p>Automatic: {automaticLabel(shown)}</p>
            {shown.locked ? <p>Protected / Locked</p> : (
              <label>
                Override
                <select
                  value={shown.override_decision === "full" ? `full:${shown.participant_id ?? ""}` : shown.override_decision}
                  onChange={(event) => {
                    const value = event.target.value;
                    if (value === "auto" || value === "wide") {
                      void chooseOverride(value);
                      return;
                    }
                    void chooseOverride("full", value.slice("full:".length));
                  }}
                >
                  <option value="auto">Auto</option>
                  <option value="wide">Wide</option>
                  {shown.full_choices.map((choice) => (
                    <option key={choice.participant_id} value={`full:${choice.participant_id}`}>
                      Full — {choice.display_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {shown.overridden && !shown.locked ? (
              <button type="button" onClick={() => void chooseOverride("auto")}>Use Automatic</button>
            ) : null}
          </>
        ) : <p>No shot at the playhead.</p>}
      </aside>
    </div>
  );
}
