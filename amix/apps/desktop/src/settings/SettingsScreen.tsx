import { open } from "@tauri-apps/plugin-dialog";
import { useEffect, useState } from "react";

import {
  importGgufModel,
  importLlamaRuntime,
  importSpeechModel,
  importVisionModel,
  removeProvider,
  removeProviderCredential,
  removeResource,
  runtimeStatus,
  saveLocalLimits,
  saveMediaTools,
  saveNetworkPolicy,
  saveProvider,
  selectInstalledResource,
  selectProvider,
  selectSpeechModel,
  selectVisionModel,
  setProviderCredential,
  startLocalAi,
  stopLocalAi,
  checkCursor,
  refreshCursorModels,
  saveCursorModel,
  setSemanticSource,
  signInCursor,
  testProvider,
  useManagedLocalAi,
} from "../api/client";
import { asFailure } from "../api/errors";
import type { EngineFailure, InstalledResource, ProviderConfig, RuntimeStatus } from "../api/types";
import { Alert } from "../components/Alert";
import {
  applyState,
  catalogMessage,
  cursorStatusLabel,
  credentialLabel,
  importSpeechCopy,
  localAiSummary,
  modelDetail,
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

  useEffect(() => {
    const state = status?.local_ai.state;
    if (state !== "STARTING" && state !== "LOADING") {
      return;
    }
    const timer = window.setInterval(() => {
      void runtimeStatus().then(setStatus).catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [status?.local_ai.state]);

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
  const runtimes = status.resources.filter((item) => item.kind === "llama_runtime");
  const models = status.resources.filter((item) => item.kind === "gguf");
  const localProviders = status.providers.filter((item) => item.placement === "local");
  const remoteProviders = status.providers.filter((item) => item.placement !== "local");
  const catalogNote = catalogMessage(status.catalog.length);
  const localSummary = localAiSummary({
    runtimeReady: runtimes.some((item) => item.selected),
    modelRegistered: models.some((item) => item.selected),
    state: status.local_ai.state,
  });

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
        <p className="muted">Offline keeps project data on this computer. Network enabled allows a configured remote provider and Cursor Development.</p>
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
        <h3>Semantic Provider</h3>
        <p className="muted">One provider is used for Conversation Mapping, Reel Discovery, and later semantic tasks.</p>
        <div className="actions">
          <button type="button" disabled={busy || status.semantic_source === "managed_local"} onClick={() => void run(() => useManagedLocalAi())}>
            Managed Local
          </button>
          <button type="button" disabled={busy || status.semantic_source === "cursor-development"} onClick={() => void run(() => setSemanticSource("cursor-development"))}>
            Cursor Development
          </button>
          <button
            type="button"
            disabled={busy || status.semantic_source === "provider"}
            onClick={() => {
              const current = [...remoteProviders, ...localProviders].find((item) => item.selected)
                || remoteProviders[0]
                || localProviders[0];
              if (!current) {
                setNote("Add a provider below, then select it.");
                return;
              }
              void run(() => selectProvider(current.provider_id));
            }}
          >
            Remote API
          </button>
        </div>
        {status.semantic_source === "managed_local" ? (
          <p>Managed Local is selected. Gemma / llama.cpp. Private. Offline capable.</p>
        ) : null}
        {status.semantic_source === "cursor-development" ? (
          <CursorDevelopment
            status={status}
            busy={busy}
            onCheck={() => void run(async () => { await checkCursor(); })}
            onRefresh={() => void run(async () => { await refreshCursorModels(); })}
            onModel={(modelId) => void run(async () => { await saveCursorModel(modelId); })}
            onSignIn={() => void run(async () => { await signInCursor(); })}
          />
        ) : null}
        {status.semantic_source === "provider" ? (
          <p>Remote API is selected. Network required. Credentials stay in the existing credential store.</p>
        ) : null}
        <h3>Managed local model</h3>
        <p>{localSummary}{status.local_ai.selected ? " · Selected" : ""}</p>
        <p className="muted">{status.local_ai.message}</p>
        {status.local_ai.state === "FAILED" && status.local_ai.diagnostic ? (
          <p className="muted">{status.local_ai.diagnostic}</p>
        ) : null}
        <p className="muted">Runtime and model stay registered after AMIX closes. The server stops when AMIX closes.</p>
        <ResourceList
          items={runtimes}
          busy={busy}
          onSelect={(id) => void run(() => selectInstalledResource(id))}
          onRemove={(item) => void run(() => removeResource(item.resource_id, false))}
        />
        <ResourceList
          items={models}
          busy={busy}
          onSelect={(id) => void run(() => selectInstalledResource(id))}
          onRemove={(item) => void run(() => removeResource(item.resource_id, false))}
        />
        <LocalLimits status={status} busy={busy} onApply={(context, threads) => void run(() => saveLocalLimits(context, threads))} />
        <div className="actions">
          <button type="button" disabled={busy} onClick={() => void importExecutable()}>Import llama.cpp program</button>
          <button type="button" disabled={busy} onClick={() => void importFolder("Choose a folder containing llama-server", (path) => importLlamaRuntime(path, "llama.cpp"))}>Import llama.cpp folder</button>
          <button type="button" disabled={busy} onClick={() => void importGguf()}>Import local GGUF model</button>
          <button type="button" disabled={busy || status.local_ai.selected} onClick={() => void run(() => useManagedLocalAi())}>Use managed local model</button>
          <button type="button" disabled={busy || status.local_ai.state === "STARTING" || status.local_ai.state === "LOADING" || status.local_ai.state === "READY"} onClick={() => void run(() => startLocalAi())}>Start / Test</button>
          <button type="button" disabled={busy || status.local_ai.state === "STOPPED"} onClick={() => void run(() => stopLocalAi())}>Stop Local AI</button>
        </div>
        <h3>External local provider</h3>
        <p className="muted">Use this when llama.cpp, LM Studio, or another OpenAI-compatible server is already running on this computer.</p>
        {localProviders.map((provider) => (
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
        <h3>Remote provider</h3>
        <p>{status.local_ai.selected ? "Managed local model is active." : providerSummary(status.semantic)}</p>
        <p className="muted">{testResultLabel(testState)}</p>
        {remoteProviders.map((provider) => (
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

  async function importExecutable() {
    const selected = await open({
      directory: false,
      multiple: false,
      title: "Choose llama-server",
      filters: [{ name: "llama-server", extensions: ["exe"] }],
    });
    if (typeof selected !== "string") {
      return;
    }
    await run(() => importLlamaRuntime(selected, "llama.cpp"));
  }

  async function importGguf() {
    const selected = await open({
      directory: false,
      multiple: false,
      title: "Import a GGUF model",
      filters: [{ name: "GGUF", extensions: ["gguf"] }],
    });
    if (typeof selected !== "string") {
      return;
    }
    const name = selected.split(/[\\/]/).filter(Boolean).pop() || "Local model";
    await run(() => importGgufModel(selected, name.replace(/\.gguf$/i, "")));
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

function CursorDevelopment({
  status,
  busy,
  onCheck,
  onRefresh,
  onModel,
  onSignIn,
}: {
  status: RuntimeStatus;
  busy: boolean;
  onCheck: () => void;
  onRefresh: () => void;
  onModel: (modelId: string) => void;
  onSignIn: () => void;
}) {
  const cursor = status.cursor;
  const listed = cursor.model_id && !cursor.models.some((item) => item.id === cursor.model_id)
    ? [{ id: cursor.model_id, name: cursor.model_id }, ...cursor.models]
    : cursor.models;
  return (
    <div>
      <p>Development</p>
      <p>Cursor Agent CLI. Uses your Cursor account. Network required. Development only.</p>
      <p className="muted">Transcript and semantic text are sent through your Cursor account. This is not local or private processing.</p>
      <p>Status: {cursorStatusLabel(cursor.status)}</p>
      <p className="muted">{cursor.message}</p>
      <p>{cursor.installed ? `Agent CLI ${cursor.version || ""}`.trim() : "Agent CLI is not installed."}</p>
      {cursor.path ? <p className="muted">{cursor.path}</p> : null}
      <label>
        Model{" "}
        <select
          value={cursor.model_id || ""}
          disabled={busy || listed.length === 0}
          onChange={(event) => onModel(event.target.value)}
        >
          {cursor.model_id ? null : <option value="">Choose a model</option>}
          {listed.map((item) => (
            <option key={item.id} value={item.id}>{item.name}</option>
          ))}
        </select>
      </label>
      <div className="actions">
        <button type="button" disabled={busy || cursor.status === "busy"} onClick={onCheck}>Check Cursor</button>
        <button type="button" disabled={busy || cursor.status === "busy"} onClick={onRefresh}>Refresh Models</button>
        {cursor.status === "login_required" ? (
          <button type="button" disabled={busy} onClick={onSignIn}>Sign in</button>
        ) : null}
      </div>
    </div>
  );
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
            {modelDetail(item)}
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
      <h3>{placement === "local" ? "Add external local provider" : "Add remote provider"}</h3>
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

function LocalLimits({
  status,
  busy,
  onApply,
}: {
  status: RuntimeStatus;
  busy: boolean;
  onApply: (context: number | null, threads: number | null) => void;
}) {
  const [contextText, setContextText] = useState(status.local_ai.context_size == null ? "" : String(status.local_ai.context_size));
  const [threadsText, setThreadsText] = useState(status.local_ai.threads == null ? "" : String(status.local_ai.threads));
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setContextText(status.local_ai.context_size == null ? "" : String(status.local_ai.context_size));
    setThreadsText(status.local_ai.threads == null ? "" : String(status.local_ai.threads));
  }, [status.local_ai.context_size, status.local_ai.threads]);
  return (
    <form
      className="provider-form"
      onSubmit={(event) => {
        event.preventDefault();
        const context = optionalBound(contextText);
        const threads = optionalBound(threadsText);
        if (context === undefined || threads === undefined) {
          setError("Context size and threads must be whole numbers, or left blank.");
          return;
        }
        setError(null);
        onApply(context, threads);
      }}
    >
      <label>
        Context size
        <input inputMode="numeric" value={contextText} onChange={(event) => setContextText(event.target.value)} placeholder="16384 if blank" />
      </label>
      <label>
        Threads
        <input inputMode="numeric" value={threadsText} onChange={(event) => setThreadsText(event.target.value)} placeholder="Runtime default" />
      </label>
      {error ? <p>{error}</p> : null}
      <button type="submit" disabled={busy}>Apply local settings</button>
    </form>
  );
}

function optionalBound(value: string): number | null | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) ? parsed : undefined;
}

function folderName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || "Speech model";
}
