import type { CaptionCueView } from "./captions";
import { captionTextDirection, overlayText } from "./captions";

export function CaptionOverlay({ cues, playheadUs }: { cues: readonly CaptionCueView[]; playheadUs: number }) {
  const text = overlayText(cues, playheadUs);
  if (!text) {
    return null;
  }
  return (
    <div className="caption-overlay" aria-live="off">
      <p dir={captionTextDirection()}>
        <bdi>{text}</bdi>
      </p>
    </div>
  );
}
