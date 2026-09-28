import { describe, expect, it } from "vitest";

import { visibleProject } from "./session";
import type { EngineStatus, SessionProject } from "./types";

const project: SessionProject = {
  handle: "handle-1",
  project_id: "project-1",
  name: "Smoke",
  read_only: false,
  schema_revision: "0002",
  path: "C:\\work\\Smoke",
  generation: 3,
};

function session(overrides: Partial<EngineStatus>): EngineStatus {
  return {
    generation: 3,
    state: "READY",
    message: "Engine ready.",
    host: "127.0.0.1",
    port: 9,
    version: "0.4.0",
    project,
    notice: null,
    ...overrides,
  };
}

describe("visibleProject", () => {
  it("restores a project that belongs to the ready engine generation", () => {
    expect(visibleProject(session({}))?.handle).toBe("handle-1");
  });

  it("drops a project after the engine is no longer ready", () => {
    expect(visibleProject(session({ state: "FAILED", project }))).toBeNull();
  });

  it("drops a handle from an older engine generation", () => {
    expect(visibleProject(session({ generation: 4 }))).toBeNull();
  });
});
