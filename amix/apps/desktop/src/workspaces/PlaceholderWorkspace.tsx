import type { WorkspaceId } from "../shell/workspaces";

export function PlaceholderWorkspace({ workspace }: { workspace: WorkspaceId }) {
  return (
    <main className="workspace-placeholder">
      <h1>{workspace}</h1>
      {workspace === "Export" ? (
        <>
          <p>Rendered programs are started from Multicam and Reels.</p>
          <p className="muted">Caption sidecars are exported from those same workspaces. This page does not start a render.</p>
        </>
      ) : (
        <>
          <p className="muted">Not implemented yet.</p>
          <p className="muted">This destination is reserved for a later editing workspace.</p>
        </>
      )}
    </main>
  );
}
