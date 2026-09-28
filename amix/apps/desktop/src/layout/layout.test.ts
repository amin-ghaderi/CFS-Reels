import { describe, expect, it } from "vitest";

import { defaultLayoutSpan, layoutFieldError, parseTimecode } from "./layout";

describe("layout form", () => {
  it("defaults a full span to the canonical source range", () => {
    expect(defaultLayoutSpan(5_000_000, 600_000_000)).toEqual({
      startUs: 5_000_000,
      endUs: 605_000_000,
    });
    expect(defaultLayoutSpan(null, null)).toBeNull();
  });

  it("parses a timecode as integer microseconds", () => {
    expect(parseTimecode("01:23:45.678")).toBe(((1 * 3600 + 23 * 60 + 45) * 1000 + 678) * 1000);
  });

  it("rejects a rectangle outside the picture and a reversed range", () => {
    const base = {
      participantId: "p",
      start: "00:00:01.000",
      end: "00:00:02.000",
      x: "0",
      y: "0",
      width: "10",
      height: "10",
      pictureWidth: 100,
      pictureHeight: 80,
    };
    expect(layoutFieldError({ ...base, x: "100" })).toMatch(/outside/);
    expect(layoutFieldError({ ...base, end: "00:00:01.000" })).toMatch(/start before/);
    expect(layoutFieldError({ ...base, width: "0" })).toMatch(/positive/);
    expect(layoutFieldError(base)).toBeNull();
  });
});
