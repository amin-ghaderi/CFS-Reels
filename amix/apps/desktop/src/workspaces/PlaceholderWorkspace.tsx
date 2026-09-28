import type { WorkspaceId } from "../shell/workspaces";

export function PlaceholderWorkspace({ workspace }: { workspace: WorkspaceId }) {
  return (
    <main className="workspace-placeholder">
      <h1>{workspace}</h1>
      <p className="muted">Not implemented yet.</p>
      <p className="muted">This destination is reserved for a later editing workspace.</p>
    </main>
  );
}
