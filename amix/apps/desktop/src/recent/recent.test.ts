import { describe, expect, it } from "vitest";

import {
  CREATE_PROJECT,
  LOCATE_PROJECT,
  MISSING_PROJECT,
  OPEN_EXISTING,
  REMOVE_RECENT,
  SHOW_ALL,
  canOpen,
  cardTitle,
  formatOpened,
  pathHint,
  showAllLabel,
  thumbnailSrc,
  visibleRecents,
  type RecentProject,
} from "./recent";

function project(id: string, overrides: Partial<RecentProject> = {}): RecentProject {
  return {
    project_id: id,
    display_name: `Show ${id}`,
    root_path: `C:\\AMIX\\Folder\\${id}`,
    last_opened_at: "2026-10-04T10:15:00+00:00",
    availability: "available",
    thumbnail: "none",
    ...overrides,
  };
}

describe("recent projects", () => {
  const projects = ["a", "b", "c", "d", "e", "f"].map((id) => project(id));

  it("shows the first few projects until Show all", () => {
    expect(visibleRecents(projects, false)).toHaveLength(4);
    expect(visibleRecents(projects, false).map((item) => item.project_id)).toEqual(["a", "b", "c", "d"]);
    expect(showAllLabel(false)).toBe(SHOW_ALL);
  });

  it("shows every project after Show all and can collapse", () => {
    expect(visibleRecents(projects, true)).toEqual(projects);
    expect(showAllLabel(true)).toBe("Show less");
  });

  it("keeps the project name primary and the path short", () => {
    const item = project("alpha", {
      display_name: "Alpha",
      root_path: "C:\\Users\\Public\\AMIX-alpha-scratch\\Alpha",
    });
    expect(cardTitle(item)).toBe("Alpha");
    expect(pathHint(item.root_path)).toBe("AMIX-alpha-scratch\\Alpha");
    expect(pathHint(item.root_path)).not.toBe(item.root_path);
    expect(pathHint(`C:\\${"very-long-segment-".repeat(8)}\\tail`)).toMatch(/^…/);
  });

  it("formats the last opened time without using the path", () => {
    const now = new Date(2026, 9, 4, 12, 0, 0);
    expect(formatOpened("2026-10-04T08:15:00", now)).toBe("Opened today 08:15");
    expect(formatOpened("2026-10-01T08:15:00", now)).toBe("Opened 2026-10-01");
  });

  it("uses a thumbnail only when image data exists", () => {
    expect(thumbnailSrc(null)).toBeNull();
    expect(thumbnailSrc("abc")).toBe("data:image/jpeg;base64,abc");
  });

  it("does not open a missing project from the card", () => {
    expect(canOpen(project("gone", { availability: "missing" }))).toBe(false);
    expect(MISSING_PROJECT).toBe("Missing");
    expect(LOCATE_PROJECT).toBe("Locate");
    expect(REMOVE_RECENT).toBe("Remove from Recent");
  });

  it("keeps create, open, and the recent labels available", () => {
    expect(CREATE_PROJECT).toBe("Create Project");
    expect(OPEN_EXISTING).toBe("Open Existing Project");
  });
});
