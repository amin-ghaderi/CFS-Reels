/** Layout V1 uses probed display pixels. Times stay canonical microseconds. */

export function defaultLayoutSpan(
  containerStartUs: number | null,
  durationUs: number | null,
): { startUs: number; endUs: number } | null {
  if (!Number.isInteger(durationUs) || durationUs === null || durationUs <= 0) {
    return null;
  }
  const startUs = Number.isInteger(containerStartUs) && containerStartUs !== null && containerStartUs >= 0
    ? containerStartUs
    : 0;
  return { startUs, endUs: startUs + durationUs };
}

export function parseTimecode(value: string): number | null {
  const match = /^(\d+):([0-5]\d):([0-5]\d)\.(\d{3})$/.exec(value.trim());
  if (!match) {
    return null;
  }
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  const seconds = Number(match[3]);
  const millis = Number(match[4]);
  return ((hours * 3600 + minutes * 60 + seconds) * 1000 + millis) * 1000;
}

export function layoutFieldError(input: {
  participantId: string;
  start: string;
  end: string;
  x: string;
  y: string;
  width: string;
  height: string;
  pictureWidth: number | null;
  pictureHeight: number | null;
}): string | null {
  if (!input.participantId) {
    return "Choose a person.";
  }
  const startUs = parseTimecode(input.start);
  const endUs = parseTimecode(input.end);
  if (startUs === null || endUs === null) {
    return "Use times as HH:MM:SS.mmm.";
  }
  if (startUs >= endUs) {
    return "The layout range must start before it ends.";
  }
  const x = strictInt(input.x);
  const y = strictInt(input.y);
  const width = strictInt(input.width);
  const height = strictInt(input.height);
  if (x === null || y === null || width === null || height === null) {
    return "Position and size must be whole pixels.";
  }
  if (x < 0 || y < 0) {
    return "Layout position must stay on the picture.";
  }
  if (width <= 0 || height <= 0) {
    return "Layout width and height must be positive.";
  }
  if (input.pictureWidth !== null && input.pictureHeight !== null) {
    if (x >= input.pictureWidth || y >= input.pictureHeight) {
      return "That rectangle is outside the picture.";
    }
  }
  return null;
}

function strictInt(value: string): number | null {
  if (!/^\d+$/.test(value.trim())) {
    return null;
  }
  return Number(value.trim());
}
