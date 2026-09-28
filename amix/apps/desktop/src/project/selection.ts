/** In-memory media selection. It is not stored on disk or in the engine. */

export function reconcileSelection(
  selectedId: string | null,
  assetIds: readonly string[],
  projectKey: string,
  previousKey: string,
): string | null {
  if (projectKey !== previousKey) {
    return null;
  }
  if (selectedId && !assetIds.includes(selectedId)) {
    return null;
  }
  return selectedId;
}
