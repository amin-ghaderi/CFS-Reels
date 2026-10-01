/** Settings view copy. These functions do not read or return a stored secret. */

export function settingsReachableWithoutProject(): boolean {
  return true;
}

export function resourceSummary(label: string, state: string): string {
  if (state === "READY") {
    return `${label} is ready.`;
  }
  if (state === "MISSING") {
    return `${label} is missing.`;
  }
  if (state === "INVALID") {
    return `${label} is invalid.`;
  }
  if (state === "FAILED") {
    return `${label} is unavailable.`;
  }
  if (state === "INSTALLING") {
    return `${label} is installing.`;
  }
  if (state === "VALIDATING") {
    return `${label} is being checked.`;
  }
  if (state === "VERSION_UNSUPPORTED") {
    return `${label} is not a supported version.`;
  }
  return `${label} is not configured.`;
}

export function resourceFix(state: string, kind: "speech" | "vision" | "tools"): string {
  if (state === "READY") {
    return "No action needed.";
  }
  if (kind === "tools") {
    return "Choose the folder that contains FFmpeg and FFprobe.";
  }
  if (kind === "speech") {
    return "Import a local speech model folder.";
  }
  return "Import a YuNet model file.";
}

export function credentialLabel(configured: boolean): string {
  return configured ? "API key configured" : "No API key";
}

export function networkLabel(policy: string): string {
  if (policy === "network_enabled") {
    return "Network enabled";
  }
  return "Offline";
}

export function offlineRemoteWarning(policy: string, placement: string): string | null {
  if (policy !== "network_enabled" && placement === "remote") {
    return "Offline mode blocks this remote provider. Choose Network enabled before using it.";
  }
  return null;
}

export function providerSummary(input: {
  configured: boolean;
  offline_blocked: boolean;
  display_name: string | null;
}): string {
  if (!input.configured) {
    return "Semantic provider is not configured.";
  }
  if (input.offline_blocked) {
    return "Offline mode blocks this provider.";
  }
  return `${input.display_name || "Semantic provider"} is configured.`;
}

export function applyState(restartRequired: boolean): string {
  if (restartRequired) {
    return "Restart the engine to apply this setting.";
  }
  return "Applied.";
}

export function importSpeechCopy(): string {
  return "AMIX registers this folder in place. Remove unregisters it and does not delete your files.";
}

export function catalogMessage(count: number): string | null {
  if (count === 0) {
    return "No managed downloads are available.";
  }
  return null;
}

export function originLabel(origin: string, ownership: string): string {
  if (ownership === "managed") {
    return "Installed by AMIX";
  }
  if (origin === "import") {
    return "Registered in place";
  }
  return "Configured";
}

export function toolSummary(name: string, state: string, version: string | null): string {
  if (state === "READY") {
    return version ? `${name} is ready (${version}).` : `${name} is ready.`;
  }
  if (state === "INVALID") {
    return `${name} is invalid.`;
  }
  return `${name} is missing.`;
}

/** A settings snapshot must not carry a stored API key. */
export function testResultLabel(state: "idle" | "ok" | "failed"): string {
  if (state === "ok") {
    return "Connection test succeeded.";
  }
  if (state === "failed") {
    return "Connection test failed.";
  }
  return "Connection has not been tested.";
}

export function exposesStoredSecret(view: Record<string, unknown>): boolean {
  const blocked = ["api_key", "secret", "token", "password", "authorization"];
  return Object.keys(view).some((key) => blocked.includes(key.toLowerCase()));
}
