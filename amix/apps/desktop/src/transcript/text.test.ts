import { describe, expect, it } from "vitest";

import { afterCorrection, afterRevert, CHROME_DIR, correctionDraft, EMPTY_TRANSCRIPT, transcriptDir } from "./text";

describe("transcript text", () => {
  it("keeps application chrome LTR and isolates Persian transcript direction", () => {
    expect(CHROME_DIR).toBe("ltr");
    expect(transcriptDir("fa")).toBe("rtl");
    expect(transcriptDir(null)).toBe("auto");
    expect(transcriptDir("en")).toBe("ltr");
  });

  it("describes an empty transcript without offering transcription", () => {
    expect(EMPTY_TRANSCRIPT).toContain("No transcript");
    expect(EMPTY_TRANSCRIPT.toLowerCase()).not.toContain("transcribe");
  });

  it("tracks a manual correction separately from machine text", () => {
    expect(correctionDraft({ effective_text: "سلام", text_corrected: true }).corrected).toBe(true);
    expect(afterCorrection("one", "ONE")).toEqual({ effective: "ONE", corrected: true });
    expect(afterRevert("one")).toEqual({ effective: "one", corrected: false });
  });
});
