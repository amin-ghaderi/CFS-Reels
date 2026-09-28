import { describe, expect, it } from "vitest";

import { renderJobSpec } from "../multicam/multicam";
import {
  cameraLabel,
  clipAtSource,
  fitRange,
  panViewport,
  removedRanges,
  requestReset,
  sequenceDurationUs,
  splitAllowed,
  timeToX,
  xToTime,
  zoomViewport,
  type SourceClip,
} from "./timeline";

const clips: SourceClip[] = [
  { clip_id: "a", source_start_us: 0, source_end_us: 20 },
  { clip_id: "b", source_start_us: 30, source_end_us: 50 },
];

describe("timeline viewport", () => {
  it("maps source time and pixels both ways", () => {
    const view = fitRange(0, 100, 200);
    expect(timeToX(0, view)).toBe(0);
    expect(timeToX(50, view)).toBe(100);
    expect(xToTime(100, view)).toBe(50);
    expect(timeToX(25, zoomViewport(view, 0.5, 50))).not.toBe(timeToX(25, view));
  });

  it("zooms around an anchor and pans in source time", () => {
    const view = fitRange(0, 1_000_000, 100);
    const zoomed = zoomViewport(view, 0.5, 400_000);
    expect(zoomed.spanUs).toBe(500_000);
    expect(xToTime(timeToX(400_000, view), zoomed)).toBe(400_000);
    expect(panViewport(zoomed, 10).originUs).toBeGreaterThan(zoomed.originUs);
  });

  it("keeps playhead movement on the same source mapping", () => {
    const view = fitRange(0, 1_000, 100);
    expect(timeToX(100, view)).toBeLessThan(timeToX(400, view));
  });
});

describe("editorial clips", () => {
  it("selects a kept clip and leaves a removed gap unselected", () => {
    expect(clipAtSource(clips, 10)?.clip_id).toBe("a");
    expect(clipAtSource(clips, 20)).toBeNull();
    expect(clipAtSource(clips, 30)?.clip_id).toBe("b");
    const gaps = removedRanges(0, 60, clips);
    expect(gaps.map((gap) => [gap.source_start_us, gap.source_end_us])).toEqual([[20, 30], [50, 60]]);
    expect(clipAtSource(clips, xToTime(timeToX(25, fitRange(0, 60, 60)), fitRange(0, 60, 60)))).toBeNull();
  });

  it("enables split only inside the selected clip", () => {
    expect(splitAllowed(clips[0], 10)).toBe(true);
    expect(splitAllowed(clips[0], 0)).toBe(false);
    expect(splitAllowed(clips[0], 20)).toBe(false);
    expect(splitAllowed(null, 10)).toBe(false);
  });

  it("sums kept duration and ignores removed gaps", () => {
    expect(sequenceDurationUs(clips)).toBe(40);
  });

  it("asks before a reset commits", () => {
    expect(requestReset(false)).toEqual({ confirming: true, commit: false });
    expect(requestReset(true)).toEqual({ confirming: false, commit: true });
  });

  it("labels camera fragments without a second camera authority", () => {
    expect(cameraLabel("full", "Alice", false)).toBe("Full — Alice");
    expect(cameraLabel("untouched_wide", null, false)).toBe("Wide");
    expect(cameraLabel("protected_master", null, true)).toBe("Protected");
  });
});

describe("output aspect", () => {
  it("keeps the same sequence when the preset changes", () => {
    const sequence = { sequenceId: "seq", revision: 3 };
    const landscape = renderJobSpec("16:9", "1080", "plan", sequence);
    const portrait = renderJobSpec("9:16", "1080", "plan", sequence);
    expect(landscape.spec.sequence_id).toBe(portrait.spec.sequence_id);
    expect(landscape.spec.sequence_revision).toBe(portrait.spec.sequence_revision);
    expect(landscape.spec.preset).not.toBe(portrait.spec.preset);
    expect(landscape.kind).toBe("render_multicam");
    expect(portrait.kind).not.toBe("build_multicam_plan");
  });
});
