import { describe, expect, it } from "vitest";

import {
  CAPTION_ACTIONS,
  CAPTION_COPY,
  captionCopyMentionsPortraitOrStyle,
  captionStatusLabel,
  captionTextDirection,
  cueAtSource,
  exportEnabled,
  overlayText,
  seekTargetUs,
  type CaptionCueView,
} from "./captions";

const cue = (overrides: Partial<CaptionCueView> = {}): CaptionCueView => ({
  cue_id: "c1",
  order_index: 0,
  first_word_id: "w1",
  last_word_id: "w1",
  source_start_us: 20_000_000,
  source_end_us: 25_000_000,
  sequence_start_us: 10_000_000,
  sequence_end_us: 15_000_000,
  generated_text: "سلام",
  manual_text: null,
  effective_text: "سلام",
  ...overrides,
});

describe("caption state", () => {
  it("labels primary and reel tracks the same way", () => {
    expect(captionStatusLabel(null)).toBe("No captions");
    expect(captionStatusLabel("absent")).toBe(CAPTION_COPY.none);
    expect(captionStatusLabel("ready")).toBe("Captions ready");
    expect(captionStatusLabel("stale")).toBe("Captions out of date");
    expect(exportEnabled("ready")).toBe(true);
    expect(exportEnabled("stale")).toBe(false);
    expect(exportEnabled("absent")).toBe(false);
  });

  it("keeps portrait, burn-in, and font language out of the caption controls", () => {
    expect(captionCopyMentionsPortraitOrStyle()).toBe(false);
    expect(CAPTION_ACTIONS).toContain("Generate Captions");
    expect(CAPTION_ACTIONS).toContain("Regenerate Captions");
    expect(CAPTION_ACTIONS).toContain("Export SRT");
    expect(CAPTION_ACTIONS).toContain("Export VTT");
    expect(CAPTION_ACTIONS).toContain("Use Generated Text");
    expect(CAPTION_ACTIONS.join(" ")).not.toMatch(/burn|font|theme|9:16|vertical/i);
  });
});

describe("caption cues", () => {
  it("highlights the current cue by source range and seeks to source time", () => {
    const first = cue();
    const second = cue({
      cue_id: "c2",
      order_index: 1,
      source_start_us: 25_000_000,
      source_end_us: 30_000_000,
      sequence_start_us: 15_000_000,
      sequence_end_us: 20_000_000,
      effective_text: "hello سلام",
    });
    expect(cueAtSource([first, second], 20_000_000)?.cue_id).toBe("c1");
    expect(cueAtSource([first, second], 24_999_999)?.cue_id).toBe("c1");
    expect(cueAtSource([first, second], 25_000_000)?.cue_id).toBe("c2");
    expect(overlayText([first, second], 12_000_000)).toBeNull();
    expect(overlayText([first], 20_000_000)).toBe("سلام");
    expect(seekTargetUs(first)).toBe(first.source_start_us);
    expect(seekTargetUs(first)).not.toBe(first.sequence_start_us);
    expect(captionTextDirection()).toBe("auto");
  });

  it("shows manual text and hides a cue outside its source range", () => {
    const edited = cue({ manual_text: "ویرایش", effective_text: "ویرایش" });
    expect(overlayText([edited], edited.source_start_us)).toBe("ویرایش");
    expect(overlayText([edited], edited.source_end_us)).toBeNull();
  });
});
