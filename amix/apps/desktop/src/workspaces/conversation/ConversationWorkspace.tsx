import { useEffect, useState } from "react";

import { checkSemanticProvider, conversationState, createJob, listJobs } from "../../api/client";
import { asFailure } from "../../api/errors";
import { isTerminal } from "../../api/jobs";
import type { ConversationState, ConversationThread, JobInfo, ProjectInfo } from "../../api/types";
import { usePlayback } from "../../playback/PlaybackSession";
import { useProjectData } from "../../project/ProjectData";
import { formatMicroseconds } from "../../time/format";
import {
  CONVERSATION_PROFILE,
  conversationActions,
  conversationPhase,
  providerLabel,
  showExistingThreads,
  threadSeekUs,
} from "../../conversation/conversation";

const EMPTY: ConversationState = {
  transcript_present: false,
  turns_ready: false,
  blocking_reason: null,
  provider_configured: false,
  provider_display_name: null,
  provider_model_id: null,
  provider_execution: null,
  capability_ready: false,
  offline_blocked: false,
  network_mode: "offline",
  map_present: false,
  map_stale: false,
  conversation_map_run_id: null,
  threads: [],
};

export function ConversationWorkspace({ project }: { project: ProjectInfo }) {
  const data = useProjectData();
  const playback = usePlayback();
  const asset = data.selected;
  const [state, setState] = useState<ConversationState>(EMPTY);
  const [jobs, setJobs] = useState<JobInfo[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (!asset) {
      setState(EMPTY);
      return;
    }
    let cancel = false;
    const tick = () => {
      Promise.all([
        conversationState(project.handle, asset.asset_id),
        listJobs(project.handle),
      ]).then(([next, listed]) => {
        if (!cancel) {
          setState(next);
          setJobs(listed);
        }
      }).catch((error: unknown) => {
        if (!cancel) {
          data.setNotice(asFailure(error));
        }
      });
    };
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => {
      cancel = true;
      window.clearInterval(timer);
    };
  }, [asset, project.handle]);

  const mapping = jobs.some((job) => job.kind === "map_conversation" && job.media_asset_id === asset?.asset_id && !isTerminal(job.status));
  const failedJob = jobs.find((job) => job.kind === "map_conversation" && job.media_asset_id === asset?.asset_id && job.status === "FAILED");
  const phase = conversationPhase({
    hasMedia: Boolean(asset),
    state,
    mapping,
    failed: Boolean(failedJob),
  });
  const selected = state.threads.find((thread) => thread.thread_id === selectedId) ?? null;
  const actions = conversationActions(phase);
  const visible = showExistingThreads(phase, state.threads) || (phase === "mapped" && state.threads.length > 0);

  async function runMap() {
    if (!asset) {
      return;
    }
    data.setNotice(null);
    try {
      await createJob(project.handle, "map_conversation", {
        mediaAssetId: asset.asset_id,
        spec: { profile_id: CONVERSATION_PROFILE },
      });
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  async function checkProvider() {
    data.setNotice(null);
    try {
      await checkSemanticProvider(project.handle);
      if (asset) {
        setState(await conversationState(project.handle, asset.asset_id));
      }
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  function choose(thread: ConversationThread) {
    setSelectedId(thread.thread_id);
    playback.requestSeek(threadSeekUs(thread));
  }

  return (
    <div className="stack">
      <h2>Conversation</h2>
      <p>{phaseText(phase)}</p>
      <p>{providerLabel(state)}</p>
      <div className="row">
        {actions.map((action) => (
          <button key={action} type="button" onClick={() => void runMap()} disabled={mapping}>
            {action}
          </button>
        ))}
        <button type="button" onClick={() => void checkProvider()}>Check provider</button>
      </div>
      {phase === "stale" || phase === "mapped" ? (
        <p>Rebuild Map creates a new semantic analysis and keeps the previous map.</p>
      ) : null}
      {failedJob && state.map_present ? <p>The latest map did not replace the current one. {failedJob.error_message}</p> : null}
      {visible ? (
        <ul className="review-list" aria-label="Conversation threads">
          {state.threads.map((thread) => (
            <li key={thread.thread_id}>
              <button type="button" onClick={() => choose(thread)} aria-current={thread.thread_id === selectedId ? "true" : undefined}>
                {thread.title} · {formatMicroseconds(thread.start_us)} – {formatMicroseconds(thread.end_us)} · {formatMicroseconds(thread.duration_us)}
                {thread.participant_names.length ? ` · ${thread.participant_names.join(", ")}` : ""}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {selected ? (
        <section aria-label="Thread details">
          <h3>{selected.title}</h3>
          <p>{selected.summary}</p>
          <p>{formatMicroseconds(selected.start_us)} – {formatMicroseconds(selected.end_us)}</p>
          <p>{selected.participant_names.join(", ") || "Unknown participant"}</p>
          <p>Turns {selected.first_turn_id} – {selected.last_turn_id}</p>
        </section>
      ) : null}
    </div>
  );
}

function phaseText(phase: ReturnType<typeof conversationPhase>): string {
  switch (phase) {
    case "no_media":
      return "No media selected.";
    case "no_transcript":
      return "No transcript.";
    case "turns_required":
      return "Speaker analysis is required before a conversation map.";
    case "provider_missing":
      return "Semantic provider is not configured.";
    case "offline_blocked":
      return "Offline mode blocks this provider.";
    case "mapping":
      return "Mapping conversation.";
    case "failed":
      return "Conversation mapping failed.";
    case "stale":
      return "The conversation map is stale.";
    case "mapped":
      return "Conversation map is ready.";
    default:
      return "Ready to map the conversation.";
  }
}
