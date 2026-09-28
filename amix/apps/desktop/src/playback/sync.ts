/** Transcript sync against the canonical playhead. Page size stays a frontend choice. */

export interface TimedWord {
  word_id: string;
  sequence: number;
  start_us: number;
  end_us: number;
  effective_text?: string;
}

export interface PageBounds {
  startUs: number;
  endUs: number;
}

export function seekTargetUs(word: { start_us: number }): number {
  return word.start_us;
}

/** Exact containment: [start_us, end_us). */
export function wordAtPlayhead(words: TimedWord[], playheadUs: number): string | null {
  for (const word of words) {
    if (playheadUs >= word.start_us && playheadUs < word.end_us) {
      return word.word_id;
    }
  }
  return null;
}

export function pageTimeBounds(words: TimedWord[]): PageBounds | null {
  if (words.length === 0) {
    return null;
  }
  return {
    startUs: words[0].start_us,
    endUs: words[words.length - 1].end_us,
  };
}

export function pageOffsetForSequence(sequence: number, pageSize: number): number {
  if (pageSize < 1 || sequence < 0) {
    return 0;
  }
  return Math.floor(sequence / pageSize) * pageSize;
}

export function playheadInsidePage(playheadUs: number, bounds: PageBounds | null): boolean {
  return bounds != null && playheadUs >= bounds.startUs && playheadUs < bounds.endUs;
}

/**
 * One follow request when the playhead leaves the loaded page.
 * Pending or a settled miss blocks a request on every later tick.
 */
export function shouldRequestFollow(input: {
  playheadUs: number;
  bounds: PageBounds | null;
  pending: boolean;
  held: boolean;
}): boolean {
  if (playheadInsidePage(input.playheadUs, input.bounds)) {
    return false;
  }
  if (input.bounds == null || input.pending || input.held) {
    return false;
  }
  return true;
}
