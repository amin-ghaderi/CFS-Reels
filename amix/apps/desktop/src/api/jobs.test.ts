import { describe, expect, it } from "vitest";

import { canCancel, canRetry, isTerminal, progressPercent } from "./jobs";

describe("job display helpers", () => {
  it("converts basis points for display only", () => {
    expect(progressPercent(0)).toBe(0);
    expect(progressPercent(5000)).toBe(50);
    expect(progressPercent(10000)).toBe(100);
  });

  it("treats succeeded history as terminal and not cancellable", () => {
    expect(isTerminal("SUCCEEDED")).toBe(true);
    expect(canCancel("SUCCEEDED")).toBe(false);
    expect(canRetry("SUCCEEDED")).toBe(false);
  });

  it("allows cancel while running and retry after failure", () => {
    expect(canCancel("RUNNING")).toBe(true);
    expect(canRetry("FAILED")).toBe(true);
    expect(canRetry("INTERRUPTED")).toBe(true);
    expect(isTerminal("QUEUED")).toBe(false);
  });
});
