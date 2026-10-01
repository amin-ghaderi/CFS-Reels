import { describe, expect, it } from "vitest";

import { mapEngineFailure } from "../api/errors";
import {
  applyState,
  byteLabel,
  catalogMessage,
  localAiSummary,
  modelDetail,
  credentialLabel,
  exposesStoredSecret,
  importSpeechCopy,
  networkLabel,
  offlineRemoteWarning,
  originLabel,
  providerSummary,
  resourceFix,
  resourceSummary,
  settingsReachableWithoutProject,
  testResultLabel,
  toolSummary,
} from "./settings";

describe("settings", () => {
  it("is reachable before a project exists", () => {
    expect(settingsReachableWithoutProject()).toBe(true);
  });

  it("maps speech, vision, and media tool status into product copy", () => {
    expect(resourceSummary("Speech model", "READY")).toBe("Speech model is ready.");
    expect(resourceSummary("Speech model", "INVALID")).toBe("Speech model is invalid.");
    expect(resourceSummary("Speech model", "MISSING")).toBe("Speech model is missing.");
    expect(resourceSummary("Vision model", "NOT_CONFIGURED")).toBe("Vision model is not configured.");
    expect(resourceFix("MISSING", "speech")).toContain("Import");
    expect(resourceFix("MISSING", "vision")).toContain("YuNet");
    expect(toolSummary("FFmpeg", "READY", "8.1")).toContain("8.1");
    expect(toolSummary("FFprobe", "MISSING", null)).toBe("FFprobe is missing.");
    expect(toolSummary("FFmpeg", "INVALID", null)).toBe("FFmpeg is invalid.");
  });

  it("describes network policy and an offline remote provider", () => {
    expect(networkLabel("offline")).toBe("Offline");
    expect(networkLabel("network_enabled")).toBe("Network enabled");
    expect(offlineRemoteWarning("offline", "remote")).toContain("Offline mode");
    expect(offlineRemoteWarning("network_enabled", "remote")).toBeNull();
    expect(providerSummary({ configured: false, offline_blocked: false, display_name: null })).toContain("not configured");
  });

  it("shows a credential indicator and never a stored key", () => {
    expect(credentialLabel(true)).toBe("API key configured");
    expect(credentialLabel(false)).toBe("No API key");
    expect(exposesStoredSecret({ credential_configured: true, display_name: "Remote" })).toBe(false);
    expect(exposesStoredSecret({ api_key: "sk-test" })).toBe(true);
  });

  it("describes import, apply, catalog, and mapped resource errors", () => {
    expect(importSpeechCopy()).toContain("in place");
    expect(applyState(false)).toBe("Applied.");
    expect(applyState(true)).toContain("Restart");
    expect(catalogMessage(0)).toContain("No managed downloads");
    expect(originLabel("import", "registered")).toBe("Registered in place");
    expect(originLabel("download", "managed")).toBe("Installed by AMIX");
    const failure = mapEngineFailure(409, JSON.stringify({ error: { code: "resource_in_use" } }));
    expect(failure.message).toContain("in use");
    expect(failure.message).not.toContain("FileNotFoundError");
    expect(testResultLabel("idle")).toContain("not been tested");
    expect(testResultLabel("ok")).toContain("succeeded");
    expect(testResultLabel("failed")).toContain("failed");
  });

  it("describes a managed local model without guessing quality", () => {
    expect(localAiSummary({ runtimeReady: false, modelRegistered: false, state: "STOPPED" })).toContain("Runtime");
    expect(localAiSummary({ runtimeReady: true, modelRegistered: true, state: "STOPPED" })).toBe("Local AI stopped");
    expect(localAiSummary({ runtimeReady: true, modelRegistered: true, state: "LOADING" })).toBe("Local AI loading");
    expect(localAiSummary({ runtimeReady: true, modelRegistered: true, state: "READY" })).toBe("Local AI ready");
    expect(localAiSummary({ runtimeReady: true, modelRegistered: true, state: "FAILED" })).toBe("Load failed");
    expect(byteLabel(1_500_000_000)).toContain("GB");
    const detail = modelDetail({
      kind: "gguf",
      version: "3",
      byte_size: 2_000_000_000,
      architecture: "qwen2",
      semantic_compatibility: "unknown",
    });
    expect(detail).toContain("GGUF 3");
    expect(detail).toContain("qwen2");
    expect(detail).toContain("unknown");
    expect(detail).not.toMatch(/Q4|7B|license/i);
  });
});
