import { describe, expect, it } from "vitest";

import { formatMicroseconds } from "./format";

describe("formatMicroseconds", () => {
  it("formats integer microseconds as hours, minutes, seconds, and milliseconds", () => {
    expect(formatMicroseconds(0)).toBe("00:00:00.000");
    expect(formatMicroseconds(1_500_000)).toBe("00:00:01.500");
    expect(formatMicroseconds(3_661_250_000)).toBe("01:01:01.250");
  });

  it("does not invent a time for a non-integer", () => {
    expect(formatMicroseconds(1.5)).toBe("00:00:00.000");
  });
});
