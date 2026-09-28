import { describe, expect, it } from "vitest";

import { reconcileSelection } from "./selection";

describe("reconcileSelection", () => {
  it("clears the selection when the project session changes", () => {
    expect(reconcileSelection("asset-1", ["asset-1"], "project-b", "project-a")).toBeNull();
  });

  it("clears a selection that is no longer in the project", () => {
    expect(reconcileSelection("gone", ["asset-1"], "project-a", "project-a")).toBeNull();
  });

  it("keeps a selection that still belongs to the same project", () => {
    expect(reconcileSelection("asset-1", ["asset-1"], "project-a", "project-a")).toBe("asset-1");
  });
});
