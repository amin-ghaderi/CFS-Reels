import { useEffect, useRef, useState, type FormEvent } from "react";

import { activeTranscript, cancelJob, clearWordText, correctWordText, createJob, listJobs, speechModelStatus, transcriptWords, wordAtTime } from "../../api/client";
import { asFailure } from "../../api/errors";
import { isTerminal } from "../../api/jobs";
import type { ActiveTranscript, JobInfo, ProjectInfo, SpeechModelStatus, TranscriptWord } from "../../api/types";
import { mediaAvailability } from "../../media/present";
import { PreviewPlayer } from "../../playback/PreviewPlayer";
import { usePlayback } from "../../playback/PlaybackSession";
import { pageOffsetForSequence, pageTimeBounds, playheadInsidePage, seekTargetUs, shouldRequestFollow, wordAtPlayhead } from "../../playback/sync";
import { useProjectData } from "../../project/ProjectData";
import { SplitPane } from "../../shell/SplitPane";
import { formatMicroseconds } from "../../time/format";
import {
  RETRANSCRIBE_WARNING,
  activeTranscribeJob,
  keepLoadedTranscript,
  languageSelection,
  transcribeOffer,
  transcriptionJobSpec,
} from "../../transcript/transcribe";
import { EMPTY_TRANSCRIPT, transcriptDir } from "../../transcript/text";

const PAGE = 80;

export function TranscriptWorkspace({ project }: { project: ProjectInfo }) {
  const data = useProjectData();
  const asset = data.selected;
  const [described, setDescribed] = useState<ActiveTranscript | null>(null);
  const [words, setWords] = useState<TranscriptWord[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [picked, setPicked] = useState<TranscriptWord | null>(null);
  const [draft, setDraft] = useState("");
  const followPending = useRef(false);
  const followHeld = useRef(false);
  const followAsset = useRef<string | null>(null);
  const [followEpoch, setFollowEpoch] = useState(0);
  const playback = usePlayback();
  const [model, setModel] = useState<SpeechModelStatus | null>(null);
  const [jobs, setJobs] = useState<JobInfo[]>([]);
  const [dialog, setDialog] = useState(false);
  const [autoLanguage, setAutoLanguage] = useState(true);
  const [languageCode, setLanguageCode] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const seenJobs = useRef(new Set<string>());

  useEffect(() => {
    let stop = false;
    void speechModelStatus()
      .then((status) => {
        if (!stop) {
          setModel(status);
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
  }, [project.handle]);

  useEffect(() => {
    if (!asset) {
      return;
    }
    let stop = false;
    let timer = 0;
    const tick = () => {
      void listJobs(project.handle)
        .then((listed) => {
          if (stop) {
            return;
          }
          setJobs(listed);
          const active = listed.some((job) => job.kind === "transcribe" && job.media_asset_id === asset.asset_id && !isTerminal(job.status));
          if (active && timer === 0) {
            timer = window.setInterval(tick, 1000);
          }
          if (!active && timer !== 0) {
            window.clearInterval(timer);
            timer = 0;
          }
        })
        .catch((error: unknown) => {
          if (!stop) {
            data.setNotice(asFailure(error));
          }
        });
    };
    tick();
    return () => {
      stop = true;
      if (timer !== 0) {
        window.clearInterval(timer);
      }
    };
  }, [project.handle, asset?.asset_id]);

  useEffect(() => {
    if (!asset) {
      return;
    }
    const assetId = asset.asset_id;
    for (const job of jobs) {
      if (job.kind !== "transcribe" || job.media_asset_id !== assetId || !isTerminal(job.status)) {
        continue;
      }
      if (seenJobs.current.has(job.job_id)) {
        continue;
      }
      seenJobs.current.add(job.job_id);
      if (keepLoadedTranscript(Boolean(described?.active), job.status)) {
        continue;
      }
      setOffset(0);
      setPicked(null);
      void activeTranscript(project.handle, assetId)
        .then((next) => {
          setDescribed(next);
        })
        .catch((error: unknown) => {
          data.setNotice(asFailure(error));
        });
    }
  }, [jobs, asset?.asset_id, project.handle, described?.active]);

  useEffect(() => {
    setDescribed(null);
    setWords([]);
    setOffset(0);
    setTotal(0);
    setPicked(null);
    if (!asset) {
      return;
    }
    let stop = false;
    void activeTranscript(project.handle, asset.asset_id)
      .then((next) => {
        if (!stop) {
          setDescribed(next);
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
  }, [project.handle, asset?.asset_id]);

  useEffect(() => {
    if (!asset || !described?.active) {
      return;
    }
    let stop = false;
    void transcriptWords(project.handle, asset.asset_id, offset, PAGE)
      .then((page) => {
        if (stop) {
          return;
        }
        setWords(page.words);
        setTotal(page.word_count);
        setPicked((current) => page.words.find((word) => word.word_id === current?.word_id) ?? null);
      })
      .catch((error: unknown) => {
        if (!stop) {
          data.setNotice(asFailure(error));
        }
      });
    return () => {
      stop = true;
    };
  }, [project.handle, asset?.asset_id, described?.active, described?.analysis_run_id, offset]);

  useEffect(() => {
    followHeld.current = false;
    followPending.current = false;
  }, [asset?.asset_id, playback.seekSerial]);

  useEffect(() => {
    if (!asset || !described?.active) {
      return;
    }
    const assetId = asset.asset_id;
    followAsset.current = assetId;
    const timed = words.map((word) => ({
      word_id: word.word_id,
      sequence: word.sequence,
      start_us: word.start_us,
      end_us: word.end_us,
    }));
    const bounds = pageTimeBounds(timed);
    if (playheadInsidePage(playback.playheadUs, bounds)) {
      followHeld.current = false;
      return;
    }
    if (!shouldRequestFollow({
      playheadUs: playback.playheadUs,
      bounds,
      pending: followPending.current,
      held: followHeld.current,
    })) {
      return;
    }
    const time = playback.playheadUs;
    followPending.current = true;
    void wordAtTime(project.handle, assetId, time)
      .then((hit) => {
        if (followAsset.current !== assetId) {
          return;
        }
        if (hit.found && hit.sequence != null) {
          const next = pageOffsetForSequence(hit.sequence, PAGE);
          if (next === offset) {
            followHeld.current = true;
          } else {
            setOffset(next);
          }
        } else {
          followHeld.current = true;
        }
      })
      .catch((error: unknown) => {
        if (followAsset.current !== assetId) {
          return;
        }
        followHeld.current = true;
        data.setNotice(asFailure(error));
      })
      .finally(() => {
        followPending.current = false;
        setFollowEpoch((value) => value + 1);
      });
  }, [playback.playheadUs, playback.seekSerial, words, asset?.asset_id, described?.active, offset, project.handle, followEpoch]);

  const runningJob = asset ? activeTranscribeJob(jobs, asset.asset_id) : null;
  const offer = transcribeOffer({
    readOnly: project.read_only,
    hasAsset: Boolean(asset),
    role: asset?.role ?? null,
    mediaStatus: asset?.status ?? null,
    hasTranscript: Boolean(described?.active),
    modelState: model?.state ?? null,
    activeJob: runningJob,
  });
  const running = offer.running;

  async function startTranscription(event: FormEvent) {
    event.preventDefault();
    if (!asset) {
      return;
    }
    const selected = languageSelection(autoLanguage, languageCode);
    if ("error" in selected) {
      setFormError(selected.error);
      return;
    }
    setFormError(null);
    data.setBusy(true);
    data.setNotice(null);
    try {
      const created = await createJob(project.handle, "transcribe", {
        mediaAssetId: asset.asset_id,
        spec: transcriptionJobSpec(selected.language),
      });
      setJobs((current) => [created, ...current.filter((job) => job.job_id !== created.job_id)]);
      setDialog(false);
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      data.setBusy(false);
    }
  }

  async function cancelTranscription(jobId: string) {
    data.setNotice(null);
    try {
      const updated = await cancelJob(project.handle, jobId);
      setJobs((current) => current.map((job) => (job.job_id === updated.job_id ? updated : job)));
    } catch (error) {
      data.setNotice(asFailure(error));
    }
  }

  function choose(word: TranscriptWord) {
    setPicked(word);
    setDraft(word.effective_text);
    playback.requestSeek(seekTargetUs(word));
  }

  async function save() {
    if (!asset || !picked) {
      return;
    }
    data.setBusy(true);
    data.setNotice(null);
    try {
      const saved = await correctWordText(project.handle, asset.asset_id, picked.word_id, draft);
      setPicked(saved);
      setWords((current) => current.map((word) => (word.word_id === saved.word_id ? saved : word)));
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      data.setBusy(false);
    }
  }

  async function revert() {
    if (!asset || !picked) {
      return;
    }
    data.setBusy(true);
    data.setNotice(null);
    try {
      const saved = await clearWordText(project.handle, asset.asset_id, picked.word_id);
      setPicked(saved);
      setDraft(saved.effective_text);
      setWords((current) => current.map((word) => (word.word_id === saved.word_id ? saved : word)));
    } catch (error) {
      data.setNotice(asFailure(error));
    } finally {
      data.setBusy(false);
    }
  }

  const direction = transcriptDir(described?.language ?? null);
  const activeWordId = wordAtPlayhead(words, playback.playheadUs);
  const context = (
    <aside className="context" aria-label="Media context">
      <h2>Media</h2>
      {asset ? (
        <>
          <p>{asset.display_name}</p>
          <p className={asset.status === "missing" ? "status missing" : "status"}>{mediaAvailability(asset.status)}</p>
          {asset.status === "missing" ? (
            <p className="warning">Source media is missing. Relink it before media-dependent work. The stored transcript stays readable.</p>
          ) : null}
        </>
      ) : (
        <p className="muted">Select a media file in Media.</p>
      )}
    </aside>
  );

  const inspector = picked ? (
    <aside className="inspector" aria-label="Selected word">
      <h2>Word</h2>
      <dl className="facts">
        <div>
          <dt>Machine text</dt>
          <dd dir="auto">{picked.machine_text}</dd>
        </div>
        <div>
          <dt>Effective text</dt>
          <dd dir="auto">{picked.effective_text}</dd>
        </div>
        <div>
          <dt>Start</dt>
          <dd className="numeric" dir="ltr">{formatMicroseconds(picked.start_us)}</dd>
        </div>
        <div>
          <dt>End</dt>
          <dd className="numeric" dir="ltr">{formatMicroseconds(picked.end_us)}</dd>
        </div>
        {picked.confidence != null ? (
          <div>
            <dt>Confidence</dt>
            <dd className="numeric" dir="ltr">{picked.confidence.toFixed(2)}</dd>
          </div>
        ) : null}
        <div>
          <dt>Participant</dt>
          <dd dir="auto">{picked.participant_name ?? (picked.participant_id ? picked.participant_id : "Unknown")}</dd>
        </div>
        <div>
          <dt>Correction</dt>
          <dd>{picked.text_corrected ? "Manual text" : "Machine text"}</dd>
        </div>
      </dl>
      <label htmlFor="word-text">Edit text</label>
      <input
        id="word-text"
        dir="auto"
        value={draft}
        disabled={project.read_only || data.busy}
        onChange={(event) => setDraft(event.target.value)}
      />
      <div className="actions">
        <button type="button" className="primary" disabled={project.read_only || data.busy || draft.trim().length === 0} onClick={() => void save()}>
          Save correction
        </button>
        <button type="button" disabled={project.read_only || data.busy || !picked.text_corrected} onClick={() => void revert()}>
          Revert
        </button>
      </div>
    </aside>
  ) : (
    <aside className="inspector" aria-label="Selected word">
      <h2>Word</h2>
      <p className="muted">Select a word to see its timing and text.</p>
    </aside>
  );

  return (
    <SplitPane
      sideFirst
      sideWidth={220}
      side={context}
      main={
        <SplitPane
          sideWidth={280}
          side={inspector}
          main={
            <section className="workspace-main" aria-label="Transcript">
              <div className="toolbar">
                <h1>Transcript</h1>
                {described?.language ? <span className="muted" dir="ltr">{described.language}</span> : null}
                {described?.active ? (
                  <span className="muted numeric" dir="ltr">
                    {offset + 1}–{Math.min(offset + words.length, total)} of {total}
                  </span>
                ) : null}
                {offer.start === "transcribe" ? (
                  <button type="button" onClick={() => { setFormError(null); setDialog(true); }}>Transcribe</button>
                ) : null}
                {offer.start === "retranscribe" ? (
                  <button type="button" onClick={() => { setFormError(null); setDialog(true); }}>Re-transcribe</button>
                ) : null}
                {running ? (
                  <>
                    <span className="muted">{running.label}</span>
                    <button
                      type="button"
                      onClick={() => {
                        if (running) {
                          void cancelTranscription(running.jobId);
                        }
                      }}
                    >
                      Cancel
                    </button>
                  </>
                ) : null}
              </div>
              <PreviewPlayer project={project} />
              {!asset ? <p className="muted">Select a media file in Media.</p> : null}
              {asset && described && !described.active ? <p>{EMPTY_TRANSCRIPT}</p> : null}
              {offer.blocked ? <p>{offer.blocked}</p> : null}
              {dialog && asset && offer.start ? (
                <form className="transcribe-panel" onSubmit={(event) => void startTranscription(event)}>
                  <p>Selected media: <span dir="auto">{asset.display_name}</span></p>
                  <p>Speech model: {model?.display_name ?? model?.message}</p>
                  {offer.start === "retranscribe" ? <p>{RETRANSCRIBE_WARNING}</p> : null}
                  <label>
                    <span>
                      <input
                        type="checkbox"
                        checked={autoLanguage}
                        onChange={(event) => setAutoLanguage(event.target.checked)}
                      />
                      {" "}Auto
                    </span>
                  </label>
                  <label>
                    Language code
                    <input
                      value={languageCode}
                      disabled={autoLanguage}
                      onChange={(event) => setLanguageCode(event.target.value)}
                      spellCheck={false}
                      autoCapitalize="off"
                    />
                  </label>
                  {formError ? <p>{formError}</p> : null}
                  <div className="actions">
                    <button type="submit" className="primary" disabled={data.busy}>Transcribe</button>
                    <button type="button" onClick={() => setDialog(false)}>Cancel</button>
                  </div>
                </form>
              ) : null}
              {described?.active ? (
                <>
                  <div className="transcript" dir={direction} lang={described.language ?? undefined}>
                    {words.map((word) => {
                      const current = word.word_id === activeWordId;
                      const selectedWord = picked?.word_id === word.word_id;
                      return (
                        <button
                          key={word.word_id}
                          type="button"
                          className={["word", selectedWord ? "selected" : "", current ? "current" : ""].filter(Boolean).join(" ")}
                          aria-pressed={selectedWord}
                          aria-current={current ? "true" : undefined}
                          onClick={() => choose(word)}
                        >
                          <bdi dir="auto">{word.effective_text}</bdi>
                          {word.participant_name ? <span className="speaker" dir="auto">{word.participant_name}</span> : null}
                        </button>
                      );
                    })}
                  </div>
                  <div className="actions">
                    <button type="button" disabled={offset === 0} onClick={() => setOffset((value) => Math.max(0, value - PAGE))}>
                      Previous
                    </button>
                    <button type="button" disabled={offset + PAGE >= total} onClick={() => setOffset((value) => value + PAGE)}>
                      Next
                    </button>
                  </div>
                </>
              ) : null}
            </section>
          }
        />
      }
    />
  );
}
