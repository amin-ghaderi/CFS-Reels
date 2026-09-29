export const WORKSPACES = ["Media", "Transcript", "Conversation", "Multicam", "Reels", "Export"] as const;

export type WorkspaceId = (typeof WORKSPACES)[number];

export const PLACEHOLDER_WORKSPACES = ["Reels", "Export"] as const;

export function isPlaceholder(workspace: WorkspaceId): boolean {
  return (PLACEHOLDER_WORKSPACES as readonly string[]).includes(workspace);
}
