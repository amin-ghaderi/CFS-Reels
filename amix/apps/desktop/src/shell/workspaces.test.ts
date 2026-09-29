import { describe, expect, it } from "vitest";

import { isPlaceholder, WORKSPACES } from "./workspaces";

describe("workspace navigation", () => {
  it("keeps editing destinations and leaves the later ones as placeholders", () => {
    expect(WORKSPACES).toContain("Media");
    expect(WORKSPACES).toContain("Transcript");
    expect(isPlaceholder("Media")).toBe(false);
    expect(isPlaceholder("Transcript")).toBe(false);
    expect(isPlaceholder("Multicam")).toBe(false);
    expect(isPlaceholder("Conversation")).toBe(false);
    expect(isPlaceholder("Reels")).toBe(false);
    expect(isPlaceholder("Export")).toBe(true);
  });
});
