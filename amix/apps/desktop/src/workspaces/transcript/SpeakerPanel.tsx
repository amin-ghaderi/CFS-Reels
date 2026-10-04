import { useEffect, useState } from "react";

import { applySpeakerMap, cancelJob, createJob, listParticipants, speakerAnalysis } from "../../api/client";
import { asFailure } from "../../api/errors";
import { isTerminal } from "../../api/jobs";
import type { JobInfo, MediaAsset, Participant, ProjectInfo, SpeakerAnalysis } from "../../api/types";
import { useProjectData } from "../../project/ProjectData";
import { formatMicroseconds } from "../../time/format";
import {
  DIARIZE_PROFILE,
  THREE_CLUSTER_LIMIT,
  canAnalyzeSpeakers,
  mappingReady,
  presentedSpeakerState,
  representativeSeekUs,
  speakerAnalysisCopy,
  type SpeakerServerState,
} from "../../transcript/speakers";

export function SpeakerPanel({
  project,
  asset,
  hasTranscript,
  jobs,
  onSeek,
  onApplied,
}: {
  project: ProjectInfo;
  asset: MediaAsset;
  hasTranscript: boolean;
  jobs: JobInfo[];
  onSeek: (canonicalUs: number) => void;
  onApplied: () => void;
}) {
  const data = useProjectData();
  const [analysis, setAnalysis] = useState<SpeakerAnalysis | null>(null);
  const [people, setPeople] = useState<Participant[]>([]);
  const [choices, setChoices] = useState<Record<string, string | null | undefined>>({});

  useEffect(() => {
    let stop = false;
    void Promise.all([speakerAnalysis(project.handle, asset.asset_id), listParticipants(project.handle)])
      .then(([status, participants]) => {
        if (stop) {
          return;
        }
        setAnalysis(status);
        setPeople(participants);
        const next: Record<string, string | null | undefined> = {};
        for (const cluster of status.clusters) {
          const previous = status.previous_map?.[cluster.cluster_key];
          if (previous === undefined) {
            continue;
          }
          next[cluster.cluster_key] = previous;
        }
        setChoices(next);
      })
      .catch((error: unknown) => {
        if (!stop) {
          data.setNotice(asFailure(error));
        }
      });
    return () => {
      stop = true;
    };
  }, [project.handle, asset.asset_id, jobs.map((job) => `${job.job_id}:${job.status}:${job.progress_bp}`).join("|")]);

  if (asset.role !== "master" || !analysis) {
    return null;
  }

  const review = analysis;
  const server = review.state as SpeakerServerState;
  const state = presentedSpeakerState(server, jobs, asset.asset_id);
  const copy = speakerAnalysisCopy(state);
  const running = jobs.find((job) => job.kind === "diarize_audio" && job.media_asset_id === asset.asset_id && !isTerminal(job.status));
  const analyze = canAnalyzeSpeakers({
    role: asset.role,
    sourcePresent: review.source_present && asset.status === "present",
    hasTranscript,
    participantCount: review.participant_count,
    running: Boolean(running),
  }) && copy.analyzeEnabled;

  async function start() {
    data.setNotice(null);
    try {
      await createJob(project.handle, "diarize_audio", {
        mediaAssetId: asset.asset_id,
        spec: { profile: DIARIZE_PROFILE },
      });
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function apply() {
    if (!review.diarization_run_id) {
      return;
    }
    const mapped = mappingReady(review.clusters.map((cluster) => cluster.cluster_key), choices);
    if (!mapped) {
      data.setNotice({ code: "incomplete_cluster_map", message: "Map every cluster, including Unknown." });
      return;
    }
    data.setBusy(true);
    data.setNotice(null);
    try {
      await applySpeakerMap(
        project.handle,
        asset.asset_id,
        review.diarization_run_id,
        mapped.map((item) => ({ cluster_key: item.clusterKey, participant_id: item.participantId })),
      );
      const status = await speakerAnalysis(project.handle, asset.asset_id);
      setAnalysis(status);
      onApplied();
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      data.setBusy(false);
    }
  }

  return (
    <section className="stack speaker-analysis" aria-label="Speaker analysis">
      <h2>Speaker analysis</h2>
      <p>{copy.message}</p>
      {copy.showLimitation ? <p className="muted">{analysis.limitation || THREE_CLUSTER_LIMIT}</p> : null}
      {analyze ? (
        <button type="button" onClick={() => void start()} disabled={data.busy || project.read_only}>Analyze speakers</button>
      ) : null}
      {running ? (
        <button type="button" onClick={() => void cancelJob(project.handle, running.job_id)} disabled={project.read_only}>Cancel</button>
      ) : null}
      {copy.showMapping ? (
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            void apply();
          }}
        >
          {analysis.clusters.map((cluster) => (
            <fieldset key={cluster.cluster_key}>
              <legend>Cluster {cluster.cluster_key}</legend>
              <p className="muted">{cluster.segment_count} segments, {formatMicroseconds(cluster.voiced_us)} voiced</p>
              <div className="actions">
                {cluster.samples.map((sample) => (
                  <button
                    key={`${sample.start_us}-${sample.end_us}`}
                    type="button"
                    onClick={() => onSeek(representativeSeekUs(sample.start_us))}
                  >
                    {formatMicroseconds(sample.start_us)}
                  </button>
                ))}
              </div>
              <label>
                Person
                <select
                  value={choices[cluster.cluster_key] === null ? "unknown" : choices[cluster.cluster_key] ?? ""}
                  onChange={(event) => {
                    const value = event.target.value;
                    setChoices((current) => ({
                      ...current,
                      [cluster.cluster_key]: value === "" ? undefined : value === "unknown" ? null : value,
                    }));
                  }}
                  disabled={project.read_only}
                >
                  <option value="">Choose</option>
                  <option value="unknown">Unknown</option>
                  {people.map((person) => (
                    <option key={person.participant_id} value={person.participant_id}>{person.display_name}</option>
                  ))}
                </select>
              </label>
            </fieldset>
          ))}
          <button type="submit" className="primary" disabled={data.busy || project.read_only}>{copy.applyLabel}</button>
        </form>
      ) : null}
    </section>
  );
}
