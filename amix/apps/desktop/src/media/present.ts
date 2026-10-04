import type { MediaAsset } from "../api/types";
import { formatMicroseconds } from "../time/format";

export function mediaAvailability(status: MediaAsset["status"]): "Available" | "Missing" {
  return status === "present" ? "Available" : "Missing";
}

export const IMPORT_MEDIA = "Import Media";
export const PEOPLE_LABEL = "People";

export function mediaCardLabel(state: string | null | undefined): "Preparing" | "Ready" | "Missing" | "Failed" {
  if (state === "ready") {
    return "Ready";
  }
  if (state === "missing") {
    return "Missing";
  }
  if (state === "failed") {
    return "Failed";
  }
  return "Preparing";
}

export function mediaGuidance(hasMedia: boolean, state: string | null | undefined): string {
  if (!hasMedia) {
    return "Import media to begin.";
  }
  const label = mediaCardLabel(state);
  if (label === "Preparing") {
    return "AMIX is analyzing the file and preparing playback.";
  }
  if (label === "Ready") {
    return "Media is ready. Next: Transcribe.";
  }
  if (label === "Missing") {
    return "The media file is missing. Relink it.";
  }
  return "Media preparation failed.";
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

export interface MediaFact {
  label: string;
  value: string;
}

/** Known facts only. Unknown probe fields are omitted. */
export function mediaFacts(asset: MediaAsset): MediaFact[] {
  const facts: MediaFact[] = [];
  if (asset.byte_size != null) {
    facts.push({ label: "Size", value: formatBytes(asset.byte_size) });
  }
  if (asset.duration_us != null) {
    facts.push({ label: "Duration", value: formatMicroseconds(asset.duration_us) });
  }
  if (asset.width != null && asset.height != null) {
    facts.push({ label: "Picture", value: `${asset.width}×${asset.height}` });
  }
  if (asset.video_codec) {
    facts.push({ label: "Video", value: asset.video_codec });
  }
  const audio = audioFact(asset);
  if (audio) {
    facts.push({ label: "Audio", value: audio });
  }
  if (asset.fps_num != null && asset.fps_den != null) {
    facts.push({ label: "Frame rate", value: `${asset.fps_num}/${asset.fps_den}` });
  }
  if (asset.container_start_us != null) {
    facts.push({ label: "Start", value: formatMicroseconds(asset.container_start_us) });
  }
  if (asset.container) {
    facts.push({ label: "Container", value: asset.container });
  }
  return facts;
}

function audioFact(asset: MediaAsset): string | null {
  const parts: string[] = [];
  if (asset.audio_codec) {
    parts.push(asset.audio_codec);
  }
  if (asset.sample_rate != null) {
    parts.push(`${asset.sample_rate} Hz`);
  }
  if (asset.audio_channels != null) {
    parts.push(`${asset.audio_channels} ch`);
  }
  if (asset.channel_layout) {
    parts.push(asset.channel_layout);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

export function proxyLabel(state: string | null): string {
  switch (state) {
    case "queued":
      return "Queued";
    case "generating":
      return "Generating";
    case "ready":
      return "Ready";
    case "stale":
      return "Stale";
    case "failed":
      return "Failed";
    case "missing":
      return "Missing";
    default:
      return "Not generated";
  }
}

export function sourceAssets(assets: readonly MediaAsset[]): MediaAsset[] {
  return assets.filter((asset) => asset.role !== "proxy" && asset.role !== "sidecar");
}

export function missingCount(assets: readonly MediaAsset[]): number {
  return sourceAssets(assets).filter((asset) => asset.status === "missing").length;
}
