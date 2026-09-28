import { useEffect, useState } from "react";

import { createJob, listJobs, multicamReadiness, overlapState, shotPlanState } from "../../api/client";
import { asFailure, jobProblemMessage } from "../../api/errors";
import { isTerminal } from "../../api/jobs";
import type { JobInfo, MulticamReadiness, OverlapState, ProjectInfo, ShotPlanState, ShotView } from "../../api/types";
import { PreviewPlayer } from "../../playback/PreviewPlayer";
import { usePlayback } from "../../playback/PlaybackSession";
import { useProjectData } from "../../project/ProjectData";
import { formatMicroseconds } from "../../time/format";
import {
  currentShot,
  latestFailure,
  multicamPhase,
  phaseLabel,
  regionSeekUs,
  runningJob,
  shotLabel,
  shotSeekUs,
} from "../../multicam/multicam";

const EMPTY_OVERLAP: OverlapState = {
  run_id: null,
  stale: false,
  window_start_us: null,
  window_end_us: null,
  profile_id: null,
  regions: [],
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

  useEffect(() => {
    if (!asset) {
      setReadiness(null);
      setOverlap(EMPTY_OVERLAP);
      setPlan(EMPTY_PLAN);
      return;
    }
    let stop = false;
    const load = () => {
      void Promise.all([
        listJobs(project.handle),
        multicamReadiness(project.handle, asset.asset_id),
        overlapState(project.handle, asset.asset_id),
        shotPlanState(project.handle, asset.asset_id),
      ]).then(([listed, nextReady, nextOverlap, nextPlan]) => {
        if (stop) {
          return;
        }
        setJobs(listed);
        setReadiness(nextReady);
        setOverlap(nextOverlap);
        setPlan(nextPlan);
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
  const waiting = Boolean(asset) && readiness === null && !runningJob(jobs, asset?.asset_id ?? "", "detect_overlap") && !runningJob(jobs, asset?.asset_id ?? "", "build_multicam_plan");
  const followed = currentShot(plan.shots, playback.playheadUs);
  const shown = picked && followed && picked.start_us === followed.start_us ? picked : followed ?? picked;
  const overlapJob = asset ? runningJob(jobs, asset.asset_id, "detect_overlap") : null;
  const planJob = asset ? runningJob(jobs, asset.asset_id, "build_multicam_plan") : null;
  const failed = asset ? latestFailure(jobs, asset.asset_id) : null;

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

  return (
    <div className="multicam">
      <div className="multicam-main">
        <PreviewPlayer project={project} />
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
                  <li key={`${shot.start_us}-${shot.end_us}-${shot.reason}`} className={active ? "is-current" : undefined}>
                    <button type="button" onClick={() => { setPicked(shot); playback.requestSeek(shotSeekUs(shot)); }}>
                      {formatMicroseconds(shot.start_us)} – {formatMicroseconds(shot.end_us)} · {shotLabel(shot)} · {shot.reason}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
      <aside className="multicam-inspector" aria-label="Current shot">
        <h2>Current</h2>
        {shown ? (
          <>
            <p>{shotLabel(shown)}</p>
            <p>{formatMicroseconds(shown.start_us)} – {formatMicroseconds(shown.end_us)}</p>
            <p>{shown.reason}</p>
          </>
        ) : <p>No shot at the playhead.</p>}
      </aside>
    </div>
  );
}
