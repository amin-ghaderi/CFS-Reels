/** Preview pixels and probed display pixels. Stored layout uses the source picture. */

export interface SourceRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PreviewBox {
  x: number;
  y: number;
  width: number;
  height: number;
  scale: number;
}

const MIN_SIZE = 8;

export function contentBox(
  elementWidth: number,
  elementHeight: number,
  sourceWidth: number,
  sourceHeight: number,
): PreviewBox | null {
  if (elementWidth <= 0 || elementHeight <= 0 || sourceWidth <= 0 || sourceHeight <= 0) {
    return null;
  }
  const scale = Math.min(elementWidth / sourceWidth, elementHeight / sourceHeight);
  const width = sourceWidth * scale;
  const height = sourceHeight * scale;
  return {
    x: (elementWidth - width) / 2,
    y: (elementHeight - height) / 2,
    width,
    height,
    scale,
  };
}

export function previewToSource(
  previewX: number,
  previewY: number,
  box: PreviewBox,
  sourceWidth: number,
  sourceHeight: number,
): { x: number; y: number } {
  const x = clamp((previewX - box.x) / box.scale, 0, sourceWidth);
  const y = clamp((previewY - box.y) / box.scale, 0, sourceHeight);
  return { x: Math.round(x), y: Math.round(y) };
}

export function sourceRectToPreview(rect: SourceRect, box: PreviewBox): PreviewBox {
  return {
    x: box.x + rect.x * box.scale,
    y: box.y + rect.y * box.scale,
    width: rect.w * box.scale,
    height: rect.h * box.scale,
    scale: box.scale,
  };
}

export function clampRect(rect: SourceRect, sourceWidth: number, sourceHeight: number): SourceRect {
  const width = clamp(Math.round(rect.w), MIN_SIZE, sourceWidth);
  const height = clamp(Math.round(rect.h), MIN_SIZE, sourceHeight);
  const x = clamp(Math.round(rect.x), 0, sourceWidth - width);
  const y = clamp(Math.round(rect.y), 0, sourceHeight - height);
  return { x, y, w: width, h: height };
}

export function moveRect(
  rect: SourceRect,
  deltaPreviewX: number,
  deltaPreviewY: number,
  box: PreviewBox,
  sourceWidth: number,
  sourceHeight: number,
): SourceRect {
  return clampRect(
    {
      x: rect.x + deltaPreviewX / box.scale,
      y: rect.y + deltaPreviewY / box.scale,
      w: rect.w,
      h: rect.h,
    },
    sourceWidth,
    sourceHeight,
  );
}

export function resizeRect(
  rect: SourceRect,
  deltaPreviewX: number,
  deltaPreviewY: number,
  box: PreviewBox,
  sourceWidth: number,
  sourceHeight: number,
): SourceRect {
  return clampRect(
    {
      x: rect.x,
      y: rect.y,
      w: rect.w + deltaPreviewX / box.scale,
      h: rect.h + deltaPreviewY / box.scale,
    },
    sourceWidth,
    sourceHeight,
  );
}

export function layoutSaveBody(input: {
  participantId: string;
  rect: SourceRect;
  startUs: number;
  endUs: number;
  bindingId?: string | null;
}): {
  participant_id: string;
  start_us: number;
  end_us: number;
  x: number;
  y: number;
  w: number;
  h: number;
  binding_id?: string;
} {
  const body = {
    participant_id: input.participantId,
    start_us: input.startUs,
    end_us: input.endUs,
    x: input.rect.x,
    y: input.rect.y,
    w: input.rect.w,
    h: input.rect.h,
  };
  if (input.bindingId) {
    return { ...body, binding_id: input.bindingId };
  }
  return body;
}

function clamp(value: number, low: number, high: number): number {
  if (high < low) {
    return low;
  }
  return Math.min(high, Math.max(low, value));
}
