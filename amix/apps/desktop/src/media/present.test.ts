import { describe, expect, it } from "vitest";

import type { MediaAsset } from "../api/types";
import { IMPORT_MEDIA, PEOPLE_LABEL, mediaAvailability, mediaCardLabel, mediaFacts, mediaGuidance, playbackLabel, proxyLabel, sourceAssets } from "./present";

const asset: MediaAsset = {
  asset_id: "a",
  role: "master",
  display_name: "clip.bin",
  location_kind: "external",
  relative_path: null,
  external_path: "C:\\clip.bin",
  byte_size: 12,
  duration_us: null,
  width: null,
  height: null,
  fps_num: null,
  fps_den: null,
  container: null,
  container_start_us: null,
  video_codec: null,
  audio_codec: null,
  sample_rate: null,
  audio_channels: null,
  channel_layout: null,
  rotation_degrees: null,
  probed_at: null,
  source_media_asset_id: null,
  proxy_state: "not_generated",
  proxy_asset_id: null,
  status: "missing",
};

describe("media presentation", () => {
  it("uses import language and simple preparation states", () => {
    expect(IMPORT_MEDIA).toBe("Import Media");
    expect(IMPORT_MEDIA).not.toMatch(/link file/i);
    expect(PEOPLE_LABEL).toBe("People");
    expect(mediaCardLabel("preparing")).toBe("Preparing");
    expect(mediaCardLabel("ready")).toBe("Ready");
    expect(mediaCardLabel("missing")).toBe("Missing");
    expect(mediaCardLabel("failed")).toBe("Failed");
    expect(mediaGuidance(false, null)).toBe("Import media to begin.");
    expect(mediaCardLabel("preview_required")).toBe("Preview needed");
    expect(mediaGuidance(true, "preparing")).toMatch(/analyzing the file/i);
    expect(mediaGuidance(true, "preparing")).not.toMatch(/proxy/i);
    expect(mediaGuidance(true, "ready")).toMatch(/Transcribe/);
    expect(mediaGuidance(true, "ready")).not.toMatch(/Generate proxy|Analyze media/);
    expect(mediaGuidance(true, "preview_required")).toMatch(/proxy/);
    expect(playbackLabel("source")).toBe("Original");
    expect(playbackLabel("proxy")).toBe("Proxy");
    expect(playbackLabel(null)).toBe("Unavailable");
    expect(proxyLabel("not_generated")).toBe("Not generated");
  });

  it("names missing media without inventing a picture size", () => {
    expect(mediaAvailability("missing")).toBe("Missing");
    expect(mediaAvailability("present")).toBe("Available");
    expect(mediaFacts(asset).map((fact) => fact.value).join(" ")).toBe("12 B");
    expect(mediaFacts(asset).map((fact) => fact.value).join(" ")).not.toContain("1920");
  });

  it("shows probed rationals and keeps proxies out of the source list", () => {
    const probed: MediaAsset = {
      ...asset,
      status: "present",
      duration_us: 1_500_000,
      width: 320,
      height: 240,
      fps_num: 30000,
      fps_den: 1001,
      video_codec: "h264",
      audio_codec: "aac",
      sample_rate: 48000,
      audio_channels: 2,
      container_start_us: 1_500_000,
      proxy_state: "ready",
    };
    const values = mediaFacts(probed).map((fact) => fact.value);
    expect(values).toContain("30000/1001");
    expect(values).toContain("320×240");
    expect(values).toContain("h264");
    expect(values.join(" ")).not.toContain("29.97");
    expect(proxyLabel("stale")).toBe("Stale");
    expect(proxyLabel(null)).toBe("Not generated");
    const proxy: MediaAsset = { ...asset, asset_id: "p", role: "proxy", source_media_asset_id: "a" };
    const sidecar: MediaAsset = { ...asset, asset_id: "s", role: "sidecar", source_media_asset_id: "a" };
    expect(sourceAssets([probed, proxy, sidecar]).map((item) => item.asset_id)).toEqual(["a"]);
  });
});
