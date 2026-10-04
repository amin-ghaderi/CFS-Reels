import { describe, expect, it } from "vitest";

import { defaultLayoutSpan } from "./layout";
import {
  clampRect,
  contentBox,
  layoutSaveBody,
  moveRect,
  previewToSource,
  resizeRect,
  sourceRectToPreview,
} from "./geometry";

describe("layout geometry", () => {
  const box = contentBox(640, 360, 1280, 720);
  if (!box) {
    throw new Error("content box");
  }

  it("converts preview pixels to source display pixels", () => {
    expect(box.scale).toBeCloseTo(0.5);
    expect(previewToSource(10, 20, box, 1280, 720)).toEqual({ x: 20, y: 40 });
    const preview = sourceRectToPreview({ x: 20, y: 40, w: 100, h: 80 }, box);
    expect(preview.x).toBeCloseTo(10);
    expect(preview.y).toBeCloseTo(20);
    expect(preview.width).toBeCloseTo(50);
  });

  it("clamps a dragged rectangle inside the picture", () => {
    expect(clampRect({ x: -20, y: -10, w: 5000, h: 40 }, 1280, 720)).toEqual({ x: 0, y: 0, w: 1280, h: 40 });
    const moved = moveRect({ x: 10, y: 10, w: 100, h: 80 }, -1000, 50, box, 1280, 720);
    expect(moved.x).toBe(0);
    expect(moved.y).toBeGreaterThanOrEqual(0);
    expect(moved.x + moved.w).toBeLessThanOrEqual(1280);
    expect(moved.y + moved.h).toBeLessThanOrEqual(720);
  });

  it("resizes and keeps a minimum size", () => {
    const resized = resizeRect({ x: 10, y: 10, w: 100, h: 80 }, -1000, 40, box, 1280, 720);
    expect(resized.w).toBeGreaterThanOrEqual(8);
    expect(resized.h).toBeGreaterThan(80);
    expect(resized.x + resized.w).toBeLessThanOrEqual(1280);
  });

  it("saves source pixels for the whole media and any person id", () => {
    const span = defaultLayoutSpan(0, 5_000_000);
    expect(span).toEqual({ startUs: 0, endUs: 5_000_000 });
    const body = layoutSaveBody({
      participantId: "person-amin",
      rect: { x: 12, y: 20, w: 400, h: 500 },
      startUs: span?.startUs ?? 0,
      endUs: span?.endUs ?? 0,
    });
    expect(body.x).toBe(12);
    expect(body.participant_id).toBe("person-amin");
    expect(body).not.toHaveProperty("binding_id");
    expect(JSON.stringify(body)).not.toMatch(/"A"|"B"|"C"/);
  });
});
