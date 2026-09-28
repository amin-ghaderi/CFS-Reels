import { describe, expect, it } from "vitest";

import {
  pageOffsetForSequence,
  pageTimeBounds,
  seekTargetUs,
  shouldRequestFollow,
  wordAtPlayhead,
  type TimedWord,
} from "./sync";

const page: TimedWord[] = [
  { word_id: "w0", sequence: 80, start_us: 1_000_000, end_us: 1_400_000, effective_text: "one" },
  { word_id: "w1", sequence: 81, start_us: 1_800_000, end_us: 2_200_000, effective_text: "two" },
];

describe("transcript playback sync", () => {
  it("seeks a word click to that word's exact start", () => {
    expect(seekTargetUs(page[0])).toBe(1_000_000);
    expect(Number.isInteger(seekTargetUs(page[0]))).toBe(true);
  });

  it("highlights a word inside its half-open range", () => {
    expect(wordAtPlayhead(page, 1_200_000)).toBe("w0");
    expect(wordAtPlayhead(page, 1_000_000)).toBe("w0");
    expect(wordAtPlayhead(page, 1_400_000)).toBeNull();
  });

  it("does not invent a word during silence", () => {
    expect(wordAtPlayhead(page, 1_600_000)).toBeNull();
    expect(wordAtPlayhead(page, 2_200_000)).toBeNull();
  });

  it("requests a follow once when the playhead leaves the page", () => {
    const bounds = pageTimeBounds(page);
    expect(shouldRequestFollow({ playheadUs: 1_200_000, bounds, pending: false, held: false })).toBe(false);
    expect(shouldRequestFollow({ playheadUs: 500_000, bounds, pending: false, held: false })).toBe(true);
    expect(shouldRequestFollow({ playheadUs: 500_000, bounds, pending: true, held: false })).toBe(false);
    expect(shouldRequestFollow({ playheadUs: 500_000, bounds, pending: false, held: true })).toBe(false);
    expect(pageOffsetForSequence(83, 80)).toBe(80);
    expect(pageOffsetForSequence(80, 80)).toBe(80);
    expect(pageOffsetForSequence(79, 80)).toBe(0);
  });

  it("keeps the same word id after a text correction", () => {
    const corrected = page.map((word) => (word.word_id === "w0" ? { ...word, effective_text: "ONE" } : word));
    expect(wordAtPlayhead(corrected, 1_000_000)).toBe("w0");
    expect(corrected[0].effective_text).toBe("ONE");
  });
});
