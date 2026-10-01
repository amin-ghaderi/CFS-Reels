import { open } from "@tauri-apps/plugin-dialog";
import { useEffect, useState } from "react";

import {
  importSpeechModel,
  importVisionModel,
  removeProvider,
  removeProviderCredential,
  removeResource,
  runtimeStatus,
  saveMediaTools,
  saveNetworkPolicy,
  saveProvider,
  selectProvider,
  selectSpeechModel,
  selectVisionModel,
  setProviderCredential,
  testProvider,
} from "../api/client";
import { asFailure } from "../api/errors";
import type { EngineFailure, InstalledResource, ProviderConfig, RuntimeStatus } from "../api/types";
import { Alert } from "../components/Alert";
import {
  applyState,
  catalogMessage,
  credentialLabel,
  importSpeechCopy,
  networkLabel,
  offlineRemoteWarning,
  originLabel,
  providerSummary,
  resourceSummary,
  testResultLabel,
  toolSummary,
} from "./settings";

export function SettingsScreen({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [notice, setNotice] = useState<EngineFailure | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testState, setTestState] = useState<"idle" | "ok" | "failed">("idle");

  async function reload() {
    setStatus(await runtimeStatus());
  }

  useEffect(() => {
    void reload().catch((error) => setNotice(asFailure(error)));
  }, []);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setNotice(null);
    setNote(null);
    try {
      const result = await action();
      const restart = Boolean(result && typeof result === "object" && "restart_required" in result && result.restart_required);
      setNote(applyState(restart));
      setStatus(await runtimeStatus());
    } catch (error) {
      setNotice(asFailure(error));
    } finally {
      setBusy(false);
    }
  }

  if (!status) {
    return (
      <main className="settings">
        <header className="toolbar">
          <h1>Settings</h1>
          <button type="button" onClick={onClose}>Back</button>
        </header>
        {notice ? <Alert failure={notice} /> : <p className="muted">Loading settings.</p>}
      </main>
    );
  }

  const speech = status.resources.filter((item) => item.kind === "speech");
  const vision = status.resources.filter((item) => item.kind === "vision");
  const catalogNote = catalogMessage(status.catalog.length);

  return (
    <main className="settings">
      <header className="toolbar">
        <h1>Settings</h1>
        <button type="button" onClick={onClose}>Back</button>
      </header>
      {notice ? <Alert failure={notice} /> : null}
      {note ? <p className="muted">{note}</p> : null}
      <section>
        <h2>General / Privacy</h2>
        <p>{networkLabel(status.network_policy)}</p>
        <p className="muted">Offline keeps project data on this computer. Network enabled allows a configured remote provider.</p>
        <div className="actions">
          <button type="button" disabled={busy || status.network_policy === "offline"} onClick={() => void run(() => saveNetworkPolicy("offline"))}>
            Offline
          </button>
          <button type="button" disabled={busy || status.network_policy === "network_enabled"} onClick={() => void run(() => saveNetworkPolicy("network_enabled"))}>
            Network enabled
          </button>
        </div>
      </section>
      <section>
        <h2>Speech</h2>
        <p>{resourceSummary("Speech model", status.speech.state)}</p>
        <p className="muted">
          {status.speech.display_name || "None selected"}
          {status.speech.runtime ? ` · ${status.speech.runtime}` : ""}
          {status.speech.device ? ` · ${status.speech.device}` : ""}
          {status.speech.compute_type ? ` · ${status.speech.compute_type}` : ""}
        </p>
        <p className="muted">{importSpeechCopy()}</p>
        <ResourceList
          items={speech}
          busy={busy}
          onSelect={(id) => void run(() => selectSpeechModel(id))}
          onRemove={(item) => void run(() => removeResource(item.resource_id, item.ownership === "managed"))}
        />
        <button type="button" disabled={busy} onClick={() => void importFolder("Import a speech model folder", (path) => importSpeechModel(path, folderName(path)))}>
          Import local speech model
        </button>
      </section>
      <section>
        <h2>Vision</h2>
        <p>{resourceSummary("Vision model", status.vision.state)}</p>
        <p className="muted">{status.vision.display_name || "None selected"}{status.vision.runtime ? ` · ${status.vision.runtime}` : ""}</p>
        <p className="muted">Remove unregisters an imported file and does not delete it.</p>
        <ResourceList
          items={vision}
          busy={busy}
          onSelect={(id) => void run(() => selectVisionModel(id))}
          onRemove={(item) => void run(() => removeResource(item.resource_id, item.ownership === "managed"))}
        />
        <button type="button" disabled={busy} onClick={() => void importFile()}>
          Import YuNet model
        </button>
      </section>
      <section>
        <h2>Semantic AI</h2>
        <p>{providerSummary(status.semantic)}</p>
        <p className="muted">{testResultLabel(testState)}</p>
        {status.providers.map((provider) => (
          <ProviderRow
            key={provider.provider_id}
            provider={provider}
            policy={status.network_policy}
            busy={busy}
            onSelect={() => void run(() => selectProvider(provider.provider_id))}
            onRemove={() => void run(() => removeProvider(provider.provider_id))}
            onRemoveKey={() => void removeKey(provider)}
          />
        ))}
        <ProviderForm placement="local" busy={busy} onSave={(body, secret) => void save(body, secret)} />
        <ProviderForm placement="remote" busy={busy} onSave={(body, secret) => void save(body, secret)} />
        <button type="button" disabled={busy} onClick={() => void check()}>
          Test connection
        </button>
        {catalogNote ? <p className="muted">{catalogNote}</p> : null}
      </section>
      <section>
        <h2>Media tools</h2>
        <p>{toolSummary("FFmpeg", status.ffmpeg.state, status.ffmpeg.version)}</p>
        <p>{toolSummary("FFprobe", status.ffprobe.state, status.ffprobe.version)}</p>
        <p className="muted">Choose a folder that contains both programs. AMIX does not install FFmpeg.</p>
        <button type="button" disabled={busy} onClick={() => void importFolder("Choose the FFmpeg folder", (path) => saveMediaTools(path))}>
          Choose FFmpeg folder
        </button>
      </section>
    </main>
  );

  async function importFolder(title: string, action: (path: string) => Promise<unknown>) {
    const selected = await open({ directory: true, multiple: false, title });
    if (typeof selected !== "string") {
      return;
    }
    await run(() => action(selected));
  }

  async function importFile() {
    const selected = await open({
      directory: false,
      multiple: false,
      title: "Import a YuNet model",
      filters: [{ name: "YuNet", extensions: ["onnx"] }],
    });
    if (typeof selected !== "string") {
      return;
    }
    await run(() => importVisionModel(selected, "YuNet"));
  }

  async function save(
    body: { display_name: string; placement: "local" | "remote"; base_url: string; model_id: string },
    secret: string,
  ) {
    setBusy(true);
    setNotice(null);
    try {
      const saved = await saveProvider(body);
      if (body.placement === "remote" && secret.trim() && saved.credential_ref) {
        await setProviderCredential(saved.credential_ref, secret.trim());
      }
      await selectProvider(saved.provider_id);
      setNote(applyState(false));
      setTestState("idle");
      setStatus(await runtimeStatus());
    } catch (error) {
      setNotice(asFailure(error));
    } finally {
      setBusy(false);
    }
  }

  async function check() {
    setBusy(true);
    setNotice(null);
    try {
      const result = await testProvider();
      setTestState(result.reachable ? "ok" : "failed");
      setStatus(await runtimeStatus());
    } catch (error) {
      setTestState("failed");
      setNotice(asFailure(error));
    } finally {
      setBusy(false);
    }
  }

  async function removeKey(provider: ProviderConfig) {
    if (!provider.credential_ref) {
      return;
    }
    await run(() => removeProviderCredential(provider.credential_ref as string));
  }
}

function ResourceList({
  items,
  busy,
  onSelect,
  onRemove,
}: {
  items: InstalledResource[];
  busy: boolean;
  onSelect: (id: string) => void;
  onRemove: (item: InstalledResource) => void;
}) {
  if (items.length === 0) {
    return null;
  }
  return (
    <ul className="resource-list">
      {items.map((item) => (
        <li key={item.resource_id}>
          <strong>{item.display_name}</strong>
          <span className="muted">
            {" "}
            {originLabel(item.origin, item.ownership)}
            {item.license_name ? ` · ${item.license_name}` : ""}
            {item.selected ? " · Selected" : ""}
          </span>
          <div className="actions">
            {item.selected ? null : (
              <button type="button" disabled={busy} onClick={() => onSelect(item.resource_id)}>
                Select
              </button>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (item.ownership === "managed" && !window.confirm("Remove this AMIX-managed resource and its files?")) {
                  return;
                }
                onRemove(item);
              }}
            >
              Remove
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

function ProviderRow({
  provider,
  policy,
  busy,
  onSelect,
  onRemove,
  onRemoveKey,
}: {
  provider: ProviderConfig;
  policy: string;
  busy: boolean;
  onSelect: () => void;
  onRemove: () => void;
  onRemoveKey: () => void;
}) {
  const warning = offlineRemoteWarning(policy, provider.placement);
  return (
    <div className="provider-row">
      <strong>{provider.display_name}</strong>
      <span className="muted">
        {" "}
        {provider.placement === "local" ? "Local" : "Remote"} · {provider.model_id}
        {provider.selected ? " · Selected" : ""}
      </span>
      {provider.placement === "remote" ? <p>{credentialLabel(provider.credential_configured)}</p> : null}
      {warning ? <p>{warning}</p> : null}
      <div className="actions">
        {provider.selected ? null : (
          <button type="button" disabled={busy} onClick={onSelect}>
            Select
          </button>
        )}
        {provider.placement === "remote" && provider.credential_configured ? (
          <button type="button" disabled={busy} onClick={onRemoveKey}>
            Remove credential
          </button>
        ) : null}
        <button type="button" disabled={busy} onClick={onRemove}>
          Remove
        </button>
      </div>
    </div>
  );
}

function ProviderForm({
  placement,
  busy,
  onSave,
}: {
  placement: "local" | "remote";
  busy: boolean;
  onSave: (
    body: { display_name: string; placement: "local" | "remote"; base_url: string; model_id: string },
    secret: string,
  ) => void;
}) {
  const [name, setName] = useState(placement === "local" ? "Local model" : "Remote model");
  const [baseUrl, setBaseUrl] = useState(placement === "local" ? "http://127.0.0.1:11434/v1" : "");
  const [modelId, setModelId] = useState("");
  const [secret, setSecret] = useState("");
  return (
    <form
      className="provider-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSave({ display_name: name.trim(), placement, base_url: baseUrl.trim(), model_id: modelId.trim() }, secret);
        setSecret("");
      }}
    >
      <h3>{placement === "local" ? "Local OpenAI-compatible" : "Remote OpenAI-compatible"}</h3>
      <label>
        Name
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label>
        Base URL
        <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
      </label>
      <label>
        Model
        <input value={modelId} onChange={(event) => setModelId(event.target.value)} />
      </label>
      {placement === "remote" ? (
        <label>
          API key
          <input type="password" value={secret} autoComplete="off" onChange={(event) => setSecret(event.target.value)} />
        </label>
      ) : null}
      <button className="primary" type="submit" disabled={busy || !name.trim() || !baseUrl.trim() || !modelId.trim()}>
        Save provider
      </button>
    </form>
  );
}

function folderName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || "Speech model";
}
