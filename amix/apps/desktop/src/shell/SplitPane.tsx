import { useRef, useState, type PointerEvent, type ReactNode } from "react";

/** Pointer resize for one optional side panel. Sizes stay in memory for this visit. */
export function SplitPane({
  main,
  side,
  sideWidth,
  minSide = 220,
  maxSide = 420,
  sideFirst = false,
}: {
  main: ReactNode;
  side: ReactNode | null;
  sideWidth: number;
  minSide?: number;
  maxSide?: number;
  sideFirst?: boolean;
}) {
  const [width, setWidth] = useState(sideWidth);
  const drag = useRef<{ x: number; width: number } | null>(null);

  if (!side) {
    return <div className="split-main">{main}</div>;
  }

  function onPointerDown(event: PointerEvent<HTMLButtonElement>) {
    drag.current = { x: event.clientX, width };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event: PointerEvent<HTMLButtonElement>) {
    if (!drag.current) {
      return;
    }
    const delta = event.clientX - drag.current.x;
    const next = sideFirst ? drag.current.width + delta : drag.current.width - delta;
    setWidth(Math.min(maxSide, Math.max(minSide, next)));
  }

  function onPointerUp() {
    drag.current = null;
  }

  const panel = (
    <div className="split-side" style={{ width }}>
      {side}
    </div>
  );
  const separator = (
    <button
      type="button"
      className="split-handle"
      aria-label="Resize panel"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    />
  );

  return (
    <div className="split-row">
      {sideFirst ? panel : null}
      {sideFirst ? separator : null}
      <div className="split-main">{main}</div>
      {sideFirst ? null : separator}
      {sideFirst ? null : panel}
    </div>
  );
}
