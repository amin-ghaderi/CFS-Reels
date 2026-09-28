import { describe, expect, it } from "vitest";

import {
  canonicalToCurrentTime,
  canonicalToPlaybackUs,
  currentTimeToCanonical,
  playbackUsToCanonical,
  secondsToPlaybackUs,
} from "./time";

describe("playback time mapping", () => {
  it("maps currentTime 0 to canonical_origin_us", () => {
    expect(currentTimeToCanonical(1_500_000, 0, 2_000_000)).toBe(1_500_000);
    expect(playbackUsToCanonical(1_500_000, secondsToPlaybackUs(0))).toBe(1_500_000);
  });

  it("adds a positive playback position to the origin", () => {
    expect(secondsToPlaybackUs(2)).toBe(2_000_000);
    expect(currentTimeToCanonical(1_500_000, 2, 10_000_000)).toBe(3_500_000);
  });

  it("converts a canonical source time to playback seconds once", () => {
    expect(canonicalToPlaybackUs(1_500_000, 3_500_000, 10_000_000)).toBe(2_000_000);
    expect(canonicalToCurrentTime(1_500_000, 3_500_000, 10_000_000)).toBe(2);
  });

  it("keeps a non-zero source container start in the origin", () => {
    const origin = 1_500_000;
    expect(currentTimeToCanonical(origin, 0, 2_000_000)).toBe(origin);
    expect(canonicalToPlaybackUs(origin, origin, 2_000_000)).toBe(0);
  });

  it("clamps before the beginning and after the duration", () => {
    expect(canonicalToPlaybackUs(1_500_000, 0, 2_000_000)).toBe(0);
    expect(canonicalToCurrentTime(1_500_000, 0, 2_000_000)).toBe(0);
    expect(canonicalToPlaybackUs(0, 9_000_000, 2_000_000)).toBe(2_000_000);
    expect(canonicalToCurrentTime(0, 9_000_000, 2_000_000)).toBe(2);
    expect(currentTimeToCanonical(0, 9, 2_000_000)).toBe(2_000_000);
  });

  it("round-trips by comparing integer microseconds", () => {
    const origin = 1_500_000;
    const canonical = 3_500_000;
    const duration = 10_000_000;
    const seconds = canonicalToCurrentTime(origin, canonical, duration);
    expect(currentTimeToCanonical(origin, seconds, duration)).toBe(canonical);
    expect(secondsToPlaybackUs(0.5 / 1_000_000)).toBe(1);
  });
});
