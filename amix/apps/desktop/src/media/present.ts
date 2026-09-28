import type { MediaAsset } from "../api/types";
import { formatMicroseconds } from "../time/format";

export function mediaAvailability(status: MediaAsset["status"]): "Available" | "Missing" {
  return status === "present" ? "Available" : "Missing";
}

export function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function roleLabel(role: string): string {
  return role.replaceAll("_", " ");
}

/** Known facts only. Unknown probe fields are omitted. */
export function mediaFacts(asset: MediaAsset): string[] {
  const facts: string[] = [];
  if (asset.byte_size != null) {
    facts.push(formatBytes(asset.byte_size));
  }
  if (asset.duration_us != null) {
    facts.push(formatMicroseconds(asset.duration_us));
  }
  if (asset.width != null && asset.height != null) {
    facts.push(`${asset.width}×${asset.height}`);
  }
  return facts;
}

export function missingCount(assets: readonly MediaAsset[]): number {
  return assets.filter((asset) => asset.status === "missing").length;
}
