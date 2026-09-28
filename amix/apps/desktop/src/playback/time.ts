/** Browser seconds cross this boundary once. Canonical time stays integer microseconds. */

const MICROSECONDS = 1_000_000;

export function secondsToPlaybackUs(seconds: number): number {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return 0;
  }
  return Math.round(seconds * MICROSECONDS);
}

export function playbackUsToSeconds(playbackUs: number): number {
  return playbackUs / MICROSECONDS;
}

/** Playback position 0 is canonical_origin_us. */
export function playbackUsToCanonical(originUs: number, playbackUs: number): number {
  return originUs + playbackUs;
}

export function canonicalToPlaybackUs(originUs: number, canonicalUs: number, durationUs: number | null): number {
  let playback = canonicalUs - originUs;
  if (playback < 0) {
    playback = 0;
  }
  if (durationUs != null && playback > durationUs) {
    playback = durationUs;
  }
  return playback;
}

export function canonicalToCurrentTime(originUs: number, canonicalUs: number, durationUs: number | null): number {
  return playbackUsToSeconds(canonicalToPlaybackUs(originUs, canonicalUs, durationUs));
}

export function currentTimeToCanonical(originUs: number, seconds: number, durationUs: number | null): number {
  let playback = secondsToPlaybackUs(seconds);
  if (durationUs != null && playback > durationUs) {
    playback = durationUs;
  }
  return playbackUsToCanonical(originUs, playback);
}
