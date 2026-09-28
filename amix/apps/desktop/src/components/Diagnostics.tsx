import type { EngineStatus } from "../api/types";

export function Diagnostics({ engine }: { engine: EngineStatus }) {
  if (!import.meta.env.DEV) {
    return null;
  }
  return (
    <div className="diagnostics">
      <div>Development diagnostics</div>
      <div>Status: {engine.state}</div>
      <div>Version: {engine.version ?? "unknown"}</div>
      <div>Host: {engine.host ?? "unknown"}</div>
      <div>Port: {engine.port ?? "unknown"}</div>
    </div>
  );
}
