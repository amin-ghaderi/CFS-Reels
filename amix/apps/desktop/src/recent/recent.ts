export interface RecentProject {
  project_id: string;
  display_name: string;
  root_path: string;
  last_opened_at: string;
  availability: "available" | "missing";
  thumbnail: "ready" | "none";
}

export const RECENT_PREVIEW_COUNT = 4;
export const CREATE_PROJECT = "Create Project";
export const OPEN_EXISTING = "Open Existing Project";
export const RECENT_HEADING = "Recent Projects";
export const SHOW_ALL = "Show all";
export const SHOW_LESS = "Show less";
export const MISSING_PROJECT = "Missing";
export const LOCATE_PROJECT = "Locate";
export const REMOVE_RECENT = "Remove from Recent";

export function visibleRecents(projects: readonly RecentProject[], expanded: boolean): RecentProject[] {
  if (expanded) {
    return [...projects];
  }
  return projects.slice(0, RECENT_PREVIEW_COUNT);
}

export function showAllLabel(expanded: boolean): string {
  return expanded ? SHOW_LESS : SHOW_ALL;
}

export function cardTitle(project: RecentProject): string {
  return project.display_name;
}

export function pathHint(path: string): string {
  const parts = path.split(/[\\/]/).filter((part) => part.length > 0);
  let hint = parts.slice(-2).join("\\");
  if (hint.length > 48) {
    hint = `…${hint.slice(-47)}`;
  }
  return hint;
}

export function formatOpened(iso: string, now = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "Opened earlier";
  }
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const time = `${hours}:${minutes}`;
  if (date.toDateString() === now.toDateString()) {
    return `Opened today ${time}`;
  }
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `Opened ${date.getFullYear()}-${month}-${day}`;
}

export function thumbnailSrc(dataBase64: string | null | undefined): string | null {
  if (!dataBase64) {
    return null;
  }
  return `data:image/jpeg;base64,${dataBase64}`;
}

export function canOpen(project: RecentProject): boolean {
  return project.availability === "available";
}
