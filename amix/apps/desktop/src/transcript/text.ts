import type { TranscriptWord } from "../api/types";

export const CHROME_DIR = "ltr" as const;

export function transcriptDir(language: string | null): "ltr" | "rtl" | "auto" {
  if (!language) {
    return "auto";
  }
  if (/^(fa|ar|he|ur)\b/i.test(language)) {
    return "rtl";
  }
  return "ltr";
}

export const EMPTY_TRANSCRIPT = "No transcript is available for this media yet.";

export function correctionDraft(word: Pick<TranscriptWord, "effective_text" | "text_corrected">): {
  draft: string;
  corrected: boolean;
} {
  return { draft: word.effective_text, corrected: word.text_corrected };
}

export function afterCorrection(machineText: string, savedText: string): { effective: string; corrected: boolean } {
  return { effective: savedText, corrected: savedText !== machineText };
}

export function afterRevert(machineText: string): { effective: string; corrected: boolean } {
  return { effective: machineText, corrected: false };
}
