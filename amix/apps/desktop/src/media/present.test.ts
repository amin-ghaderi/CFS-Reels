import { describe, expect, it } from "vitest";

import type { MediaAsset } from "../api/types";
import { mediaAvailability, mediaFacts } from "./present";

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
  status: "missing",
};

describe("media presentation", () => {
  it("names missing media without inventing a picture size", () => {
    expect(mediaAvailability("missing")).toBe("Missing");
    expect(mediaAvailability("present")).toBe("Available");
    expect(mediaFacts(asset).join(" ")).toBe("12 B");
    expect(mediaFacts(asset).join(" ")).not.toContain("1920");
  });
});
