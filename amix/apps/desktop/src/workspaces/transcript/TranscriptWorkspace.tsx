import { useEffect, useRef, useState } from "react";

import { activeTranscript, clearWordText, correctWordText, transcriptWords, wordAtTime } from "../../api/client";
import { asFailure } from "../../api/errors";
import type { ActiveTranscript, ProjectInfo, TranscriptWord } from "../../api/types";
import { mediaAvailability } from "../../media/present";
import { PreviewPlayer } from "../../playback/PreviewPlayer";
import { usePlayback } from "../../playback/PlaybackSession";
import { pageOffsetForSequence, pageTimeBounds, playheadInsidePage, seekTargetUs, shouldRequestFollow, wordAtPlayhead } from "../../playback/sync";
import { useProjectData } from "../../project/ProjectData";
import { SplitPane } from "../../shell/SplitPane";
import { formatMicroseconds } from "../../time/format";
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
                {described?.active ? (
                  <span className="muted numeric" dir="ltr">
                    {offset + 1}–{Math.min(offset + words.length, total)} of {total}
                  </span>
                ) : null}
              </div>
              <PreviewPlayer project={project} />
              {!asset ? <p className="muted">Select a media file in Media.</p> : null}
              {asset && described && !described.active ? <p>{EMPTY_TRANSCRIPT}</p> : null}
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
