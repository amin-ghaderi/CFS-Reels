use std::sync::{Arc, Condvar, Mutex};
use std::thread;
#[cfg(test)]
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, State};

use crate::credentials::CredentialVault;
use crate::launch::{self, EngineChild};
use crate::playback::{self, PlaybackBook};
use crate::transport::{self, timeouts_for, HttpTimeouts};

pub const RESTART_NOTICE: &str = "The engine restarted. Reopen your project to continue.";
pub const CRASH_NOTICE: &str =
    "The local engine stopped unexpectedly. Retry the engine, then reopen your project.";

const SESSION_EVENT: &str = "amix-session";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum Phase {
    Starting,
    Ready,
    Failed,
    Stopped,
}

#[derive(Clone, Serialize)]
pub struct ProjectSession {
    pub handle: String,
    pub project_id: String,
    pub name: String,
    pub read_only: bool,
    pub schema_revision: Option<String>,
    pub path: String,
    pub generation: u64,
}

/// Process-lifetime desktop session. Memory only. Never includes the engine token.
#[derive(Clone, Serialize)]
pub struct DesktopSession {
    pub generation: u64,
    pub state: Phase,
    pub message: String,
    pub host: Option<String>,
    pub port: Option<u16>,
    pub version: Option<String>,
    pub project: Option<ProjectSession>,
    pub notice: Option<String>,
}

struct Inner {
    phase: Phase,
    message: String,
    host: Option<String>,
    port: Option<u16>,
    token: Option<String>,
    version: Option<String>,
    engine: Option<EngineChild>,
    project: Option<ProjectSession>,
    notice: Option<String>,
    generation: u64,
}

struct Shared {
    inner: Mutex<Inner>,
    changed: Condvar,
    app: Mutex<Option<AppHandle>>,
    playback: Mutex<PlaybackBook>,
}

#[derive(Clone)]
pub struct EngineState {
    shared: Arc<Shared>,
}

impl EngineState {
    pub fn new() -> Self {
        Self {
            shared: Arc::new(Shared {
                inner: Mutex::new(Inner {
                    phase: Phase::Starting,
                    message: "Starting the local engine.".into(),
                    host: None,
                    port: None,
                    token: None,
                    version: None,
                    engine: None,
                    project: None,
                    notice: None,
                    generation: 0,
                }),
                changed: Condvar::new(),
                app: Mutex::new(None),
                playback: Mutex::new(PlaybackBook::default()),
            }),
        }
    }

    pub(crate) fn app_handle(&self) -> Option<AppHandle> {
        self.shared.app.lock().expect("app handle").clone()
    }

    pub(crate) fn with_playback<T>(&self, f: impl FnOnce(&mut PlaybackBook) -> T) -> T {
        let mut book = self.shared.playback.lock().expect("playback");
        f(&mut book)
    }

    /// Project close, engine restart, crash, and shutdown all drop playback files.
    pub(crate) fn revoke_playback_grants(&self) {
        let app = self.app_handle();
        self.with_playback(|book| {
            let paths = book.clear_all();
            playback::forbid_exposed(app.as_ref(), &paths);
        });
    }

    pub fn attach_app(&self, app: AppHandle) {
        *self.shared.app.lock().expect("app handle") = Some(app);
    }

    pub fn snapshot(&self) -> DesktopSession {
        self.lock().snapshot()
    }

    #[cfg(test)]
    pub fn wait_until(&self, timeout: Duration, pred: impl Fn(&DesktopSession) -> bool) -> bool {
        let started = Instant::now();
        let mut inner = self.lock();
        loop {
            if pred(&inner.snapshot()) {
                return true;
            }
            let remaining = timeout.saturating_sub(started.elapsed());
            if remaining.is_zero() {
                return false;
            }
            let (guard, wait) = self
                .shared
                .changed
                .wait_timeout(inner, remaining)
                .expect("session wait");
            inner = guard;
            if wait.timed_out() && !pred(&inner.snapshot()) {
                return false;
            }
        }
    }

    pub fn request(&self, method: &str, path: &str, body: Option<&str>) -> Result<EngineResponse, String> {
        let (port, token, generation) = {
            let inner = self.lock();
            if inner.phase != Phase::Ready {
                return Err("The engine is not ready.".into());
            }
            (
                inner.port.ok_or("The engine is not ready.")?,
                inner.token.clone().ok_or("The engine is not ready.")?,
                inner.generation,
            )
        };
        let clean = body.map(crate::redact::strip_secret_fields);
        let response = transport::engine_http(
            port,
            &token,
            method,
            path,
            clean.as_deref(),
            timeouts_for(method, path),
        )?;
        self.apply_response(generation, method, path, response.status, &response.body, clean.as_deref());
        Ok(EngineResponse {
            status: response.status,
            body: response.body,
        })
    }

    pub fn schedule_restart(&self) {
        let this = self.clone();
        let (generation, previous) = this.prepare_restart();
        thread::spawn(move || this.finish_start(generation, previous));
    }

    pub fn shutdown(&self) {
        let (engine, token, port, handle) = {
            let mut inner = self.lock();
            inner.generation = inner.generation.wrapping_add(1);
            inner.phase = Phase::Stopped;
            inner.message = "Engine stopped.".into();
            inner.host = None;
            inner.version = None;
            inner.notice = None;
            let project = inner.project.take();
            let token = inner.token.take();
            let port = inner.port.take();
            let engine = inner.engine.take();
            (engine, token, port, project.map(|project| project.handle))
        };
        self.revoke_playback_grants();
        // Generation already moved on, so the process watcher will not report this as a crash.
        self.notify();
        if let (Some(token), Some(port), Some(handle)) = (token, port, handle) {
            let path = format!("/v1/projects/{handle}/close");
            let _ = transport::engine_http(port, &token, "POST", &path, None, HttpTimeouts::close());
        }
        if let Some(engine) = engine {
            launch::stop_engine(engine);
        }
    }

    fn prepare_restart(&self) -> (u64, Option<EngineChild>) {
        let mut inner = self.lock();
        inner.generation = inner.generation.wrapping_add(1);
        let generation = inner.generation;
        let announce = inner.project.is_some() || inner.notice.is_some();
        inner.project = None;
        inner.phase = Phase::Starting;
        inner.message = "Starting the local engine.".into();
        inner.host = None;
        inner.port = None;
        inner.token = None;
        inner.version = None;
        if announce {
            inner.notice = Some(RESTART_NOTICE.to_string());
        }
        let previous = inner.engine.take();
        drop(inner);
        self.revoke_playback_grants();
        self.publish();
        (generation, previous)
    }

    fn finish_start(&self, generation: u64, previous: Option<EngineChild>) {
        if let Some(engine) = previous {
            launch::stop_engine(engine);
        }
        if self.lock().generation != generation {
            return;
        }
        let app_data = self.app_data_dir();
        match launch::spawn_development_engine(app_data.as_deref()) {
            Ok(engine) => self.publish_ready(generation, engine),
            Err(message) => self.publish_failure(generation, message),
        }
    }

    fn publish_ready(&self, generation: u64, mut engine: EngineChild) {
        let health = transport::engine_http(
            engine.record.port,
            &engine.record.token,
            "GET",
            "/v1/health",
            None,
            HttpTimeouts::health(),
        );
        let version = health.as_ref().ok().and_then(|response| {
            if response.status == 200 {
                json_field(&response.body, "version")
            } else {
                None
            }
        });
        if self.lock().generation != generation {
            launch::stop_engine(engine);
            return;
        }
        if version.is_none() {
            launch::stop_engine(engine);
            self.publish_failure(generation, "The engine started but did not answer a health check.".into());
            return;
        }
        let exit_rx = engine.take_exit();
        {
            let mut inner = self.lock();
            if inner.generation != generation {
                drop(inner);
                launch::stop_engine(engine);
                return;
            }
            inner.phase = Phase::Ready;
            inner.message = "Engine ready.".into();
            inner.host = Some(engine.record.host.clone());
            inner.port = Some(engine.record.port);
            inner.token = Some(engine.record.token.clone());
            inner.version = version;
            inner.engine = Some(engine);
        }
        if let Some(exit_rx) = exit_rx {
            let this = self.clone();
            thread::spawn(move || {
                let _ = exit_rx.recv();
                this.on_process_exit(generation);
            });
        }
        self.publish();
        self.install_saved_credentials();
    }

    fn app_data_dir(&self) -> Option<std::path::PathBuf> {
        let app = self.app_handle()?;
        let path = app.path().app_data_dir().ok()?;
        std::fs::create_dir_all(&path).ok()?;
        Some(path)
    }

    fn install_saved_credentials(&self) {
        let Ok(status) = self.request("GET", "/v1/runtime/status", None) else {
            return;
        };
        if status.status != 200 {
            return;
        }
        let Ok(value) = serde_json::from_str::<Value>(&status.body) else {
            return;
        };
        let Some(providers) = value.get("providers").and_then(Value::as_array) else {
            return;
        };
        let vault = crate::credentials::KeyringVault;
        for provider in providers {
            let Some(reference) = provider.get("credential_ref").and_then(Value::as_str) else {
                continue;
            };
            let account = crate::credentials::credential_account(reference);
            let Ok(Some(secret)) = vault.get(&account) else {
                continue;
            };
            let _ = self.push_credential(reference, &secret);
        }
    }

    fn push_credential(&self, credential_ref: &str, secret: &str) -> Result<(), String> {
        let body = serde_json::json!({
            "credential_ref": credential_ref,
            "secret": secret,
        })
        .to_string();
        self.credential_write("/v1/runtime/credentials", &body)
    }

    fn credential_write(&self, path: &str, body: &str) -> Result<(), String> {
        let (port, token) = {
            let inner = self.lock();
            if inner.phase != Phase::Ready {
                return Err("The engine is not ready.".into());
            }
            (
                inner.port.ok_or("The engine is not ready.")?,
                inner.token.clone().ok_or("The engine is not ready.")?,
            )
        };
        let response = transport::engine_credential_http(port, &token, path, body)?;
        if response.status == 200 {
            Ok(())
        } else {
            Err("The credential could not be applied.".into())
        }
    }

    fn publish_failure(&self, generation: u64, message: String) {
        let mut inner = self.lock();
        if inner.generation != generation {
            return;
        }
        inner.phase = Phase::Failed;
        inner.message = message;
        inner.host = None;
        inner.port = None;
        inner.token = None;
        inner.version = None;
        inner.project = None;
        inner.engine = None;
        drop(inner);
        self.revoke_playback_grants();
        self.publish();
    }

    fn on_process_exit(&self, generation: u64) {
        let engine = {
            let mut inner = self.lock();
            if inner.generation != generation || inner.phase != Phase::Ready {
                return;
            }
            inner.phase = Phase::Failed;
            inner.message = CRASH_NOTICE.to_string();
            inner.notice = Some(CRASH_NOTICE.to_string());
            inner.host = None;
            inner.port = None;
            inner.token = None;
            inner.version = None;
            inner.project = None;
            inner.engine.take()
        };
        drop(engine);
        self.revoke_playback_grants();
        self.publish();
    }

    fn apply_response(
        &self,
        generation: u64,
        method: &str,
        path: &str,
        status: u16,
        body: &str,
        request_body: Option<&str>,
    ) {
        let mut inner = self.lock();
        if inner.generation != generation || inner.phase != Phase::Ready {
            return;
        }
        if method == "POST" && (path == "/v1/projects/create" || path == "/v1/projects/open") && status < 400 {
            let path = request_body.and_then(|raw| json_field(raw, "path")).unwrap_or_default();
            if let Some(project) = parse_project(body, path, generation) {
                inner.project = Some(project);
                inner.notice = None;
                drop(inner);
                self.revoke_playback_grants();
                self.publish();
            }
        } else if method == "POST" && path.starts_with("/v1/projects/") && path.ends_with("/close") && status < 400
        {
            inner.project = None;
            drop(inner);
            self.revoke_playback_grants();
            self.publish();
        }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.shared.inner.lock().expect("desktop session")
    }

    fn notify(&self) {
        self.shared.changed.notify_all();
    }

    fn publish(&self) {
        self.notify();
        let snapshot = self.snapshot();
        if let Some(app) = self.shared.app.lock().expect("app handle").clone() {
            let _ = app.emit(SESSION_EVENT, snapshot);
        }
    }

    #[cfg(test)]
    fn testing_ready(&self, port: u16) {
        let mut inner = self.lock();
        inner.generation = 1;
        inner.phase = Phase::Ready;
        inner.host = Some("127.0.0.1".into());
        inner.port = Some(port);
        inner.token = Some("test-token".into());
        inner.version = Some("test".into());
        inner.message = "Engine ready.".into();
    }

    #[cfg(test)]
    pub fn testing_kill_owned_process(&self) {
        use crate::launch::kill_process_tree;
        let pid = self.lock().engine.as_ref().map(EngineChild::process_id).unwrap_or(0);
        kill_process_tree(pid);
    }
}

impl Inner {
    fn snapshot(&self) -> DesktopSession {
        DesktopSession {
            generation: self.generation,
            state: self.phase,
            message: self.message.clone(),
            host: self.host.clone(),
            port: self.port,
            version: self.version.clone(),
            project: self.project.clone(),
            notice: self.notice.clone(),
        }
    }
}

#[derive(Serialize)]
pub struct EngineResponse {
    pub status: u16,
    pub body: String,
}

fn parse_project(body: &str, path: String, generation: u64) -> Option<ProjectSession> {
    let value: Value = serde_json::from_str(body).ok()?;
    Some(ProjectSession {
        handle: value.get("handle")?.as_str()?.to_string(),
        project_id: value.get("project_id")?.as_str()?.to_string(),
        name: value.get("name")?.as_str()?.to_string(),
        read_only: value.get("read_only")?.as_bool()?,
        schema_revision: value
            .get("schema_revision")
            .and_then(|item| item.as_str().map(str::to_string)),
        path,
        generation,
    })
}

fn json_field(body: &str, field: &str) -> Option<String> {
    let value: Value = serde_json::from_str(body).ok()?;
    value.get(field)?.as_str().map(str::to_string)
}

pub fn schedule_start(app: AppHandle) {
    app.state::<EngineState>().schedule_restart();
}

#[tauri::command]
pub fn desktop_session_snapshot(state: State<'_, EngineState>) -> DesktopSession {
    state.snapshot()
}

#[tauri::command]
pub fn engine_status(state: State<'_, EngineState>) -> DesktopSession {
    state.snapshot()
}

#[tauri::command]
pub fn engine_retry(state: State<'_, EngineState>) -> DesktopSession {
    state.schedule_restart();
    state.snapshot()
}

#[tauri::command]
pub async fn engine_request(
    state: State<'_, EngineState>,
    method: String,
    path: String,
    body: Option<String>,
) -> Result<EngineResponse, String> {
    let engine = EngineState::clone(&state);
    tauri::async_runtime::spawn_blocking(move || engine.request(&method, &path, body.as_deref()))
        .await
        .map_err(|_| "The engine request could not be completed.".to_string())?
}

#[derive(serde::Deserialize)]
pub struct CredentialWrite {
    pub credential_ref: String,
    pub secret: String,
}

#[derive(serde::Deserialize)]
pub struct CredentialRef {
    pub credential_ref: String,
}

#[derive(Serialize)]
pub struct CredentialStatus {
    pub configured: bool,
}

#[tauri::command]
pub fn set_provider_credential(
    state: State<'_, EngineState>,
    request: CredentialWrite,
) -> Result<CredentialStatus, String> {
    if request.credential_ref.trim().is_empty() || request.secret.trim().is_empty() {
        return Err("Enter an API key.".into());
    }
    let vault = crate::credentials::KeyringVault;
    let account = crate::credentials::credential_account(&request.credential_ref);
    vault.set(&account, &request.secret)?;
    let _ = state.push_credential(&request.credential_ref, &request.secret);
    Ok(CredentialStatus { configured: true })
}

#[tauri::command]
pub fn credential_configured(
    request: CredentialRef,
) -> Result<CredentialStatus, String> {
    let vault = crate::credentials::KeyringVault;
    let account = crate::credentials::credential_account(&request.credential_ref);
    let configured = vault.get(&account)?.is_some();
    Ok(CredentialStatus { configured })
}

#[tauri::command]
pub fn remove_provider_credential(
    state: State<'_, EngineState>,
    request: CredentialRef,
) -> Result<CredentialStatus, String> {
    let vault = crate::credentials::KeyringVault;
    let account = crate::credentials::credential_account(&request.credential_ref);
    vault.delete(&account)?;
    let body = serde_json::json!({ "resource_id": request.credential_ref }).to_string();
    let _ = state.credential_write("/v1/runtime/credentials/remove", &body);
    Ok(CredentialStatus { configured: false })
}

#[tauri::command]
pub fn join_project_path(parent: String, name: String) -> Result<String, String> {
    crate::paths::join_project_path(&parent, &name).map(|path| path.to_string_lossy().into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::{Arc, Mutex};

    #[test]
    fn engine_request_strips_a_secret_before_it_reaches_the_engine() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let received = Arc::new(Mutex::new(String::new()));
        let slot = received.clone();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut buf = vec![0u8; 4096];
            let count = stream.read(&mut buf).unwrap_or(0);
            *slot.lock().unwrap() = String::from_utf8_lossy(&buf[..count]).into_owned();
            let body = "{}";
            let response = format!(
                "HTTP/1.1 200 OK\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = stream.write_all(response.as_bytes());
        });
        let state = EngineState::new();
        state.testing_ready(port);
        let _ = state.request(
            "POST",
            "/v1/runtime/providers",
            Some(r#"{"display_name":"Loop","api_key":"sk-visible","model_path":"C:\\models"}"#),
        );
        let text = received.lock().unwrap().clone();
        assert!(text.contains("Loop"));
        assert!(!text.contains("sk-visible"));
        assert!(!text.contains("model_path"));
    }

    #[test]
    fn snapshot_does_not_serialize_a_session_token() {
        let state = EngineState::new();
        state.testing_ready(9);
        let json = serde_json::to_string(&state.snapshot()).unwrap();
        assert!(json.contains("\"READY\""));
        assert!(json.contains("\"generation\":1"));
        assert!(!json.to_ascii_lowercase().contains("token"));
        assert!(!json.to_ascii_lowercase().contains("authorization"));
    }

    #[test]
    fn a_failed_close_keeps_the_project_session() {
        let port = serve_once(409, r#"{"error":{"code":"project_close_timeout","message":"trace"}}"#);
        let state = EngineState::new();
        state.testing_ready(port);
        state.apply_response(
            1,
            "POST",
            "/v1/projects/create",
            200,
            r#"{"handle":"h1","project_id":"p1","name":"Smoke","read_only":false,"schema_revision":"0002"}"#,
            Some(r#"{"path":"C:\\work\\Smoke","name":"Smoke"}"#),
        );
        let response = state.request("POST", "/v1/projects/h1/close", None).unwrap();
        assert_eq!(response.status, 409);
        let snapshot = state.snapshot();
        assert_eq!(snapshot.project.unwrap().handle, "h1");
    }

    #[test]
    fn a_stale_generation_cannot_restore_a_project() {
        let state = EngineState::new();
        state.testing_ready(9);
        let (_generation, _previous) = state.prepare_restart();
        state.apply_response(
            1,
            "POST",
            "/v1/projects/open",
            200,
            r#"{"handle":"old","project_id":"p","name":"Old","read_only":false,"schema_revision":null}"#,
            Some(r#"{"path":"C:\\work\\Old"}"#),
        );
        assert!(state.snapshot().project.is_none());
        assert_eq!(state.snapshot().generation, 2);
        assert_eq!(state.snapshot().notice.as_deref(), None);
    }

    #[test]
    fn restart_clears_an_open_project_and_records_the_notice() {
        let state = EngineState::new();
        state.testing_ready(9);
        state.apply_response(
            1,
            "POST",
            "/v1/projects/open",
            200,
            r#"{"handle":"h","project_id":"p","name":"Demo","read_only":false,"schema_revision":null}"#,
            Some(r#"{"path":"C:\\work\\Demo"}"#),
        );
        let (generation, previous) = state.prepare_restart();
        assert!(previous.is_none());
        let snapshot = state.snapshot();
        assert_eq!(generation, 2);
        assert!(snapshot.project.is_none());
        assert_eq!(snapshot.state, Phase::Starting);
        assert_eq!(snapshot.notice.as_deref(), Some(RESTART_NOTICE));
    }

    #[test]
    fn a_slow_engine_request_does_not_block_a_session_snapshot() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut buf = [0; 16];
            let _ = stream.read(&mut buf);
            thread::sleep(Duration::from_millis(400));
            let _ = stream.write_all(b"HTTP/1.1 200 OK\r\ncontent-length: 11\r\n\r\n{\"status\":1}");
        });
        let state = EngineState::new();
        state.testing_ready(port);
        let slow = {
            let state = state.clone();
            thread::spawn(move || state.request("GET", "/v1/health", None))
        };
        thread::sleep(Duration::from_millis(40));
        let started = Instant::now();
        let snapshot = state.snapshot();
        assert!(
            started.elapsed() < Duration::from_millis(150),
            "snapshot waited {:?}",
            started.elapsed()
        );
        assert_eq!(snapshot.state, Phase::Ready);
        let _ = slow.join().unwrap();
    }

    #[test]
    fn spawn_blocking_returns_before_the_slow_work_finishes() {
        let (sender, receiver) = std::sync::mpsc::channel();
        let started = Instant::now();
        let handle = tauri::async_runtime::spawn_blocking(move || {
            thread::sleep(Duration::from_millis(250));
            let _ = sender.send(());
        });
        assert!(
            started.elapsed() < Duration::from_millis(100),
            "blocking work ran on the caller"
        );
        let snapshot_started = Instant::now();
        let _ = EngineState::new().snapshot();
        assert!(snapshot_started.elapsed() < Duration::from_millis(50));
        tauri::async_runtime::block_on(handle).unwrap();
        receiver.recv_timeout(Duration::from_secs(2)).unwrap();
    }

    #[test]
    fn expected_shutdown_is_not_reported_as_a_crash() {
        let state = EngineState::new();
        state.schedule_restart();
        assert!(state.wait_until(Duration::from_secs(20), |session| session.state == Phase::Ready));
        state.shutdown();
        let session = state.snapshot();
        assert_eq!(session.state, Phase::Stopped);
        assert!(session.project.is_none());
        assert!(session.notice.is_none());
    }

    #[test]
    fn unexpected_exit_invalidates_the_session_and_reopen_uses_a_new_generation() {
        let state = EngineState::new();
        let _guard = StopOnDrop(state.clone());
        state.schedule_restart();
        assert!(
            state.wait_until(Duration::from_secs(20), |session| session.state == Phase::Ready),
            "{}",
            state.snapshot().message
        );
        let generation = state.snapshot().generation;
        let parent = std::env::temp_dir().join(format!("amix-session-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&parent);
        std::fs::create_dir_all(&parent).unwrap();
        let project = parent.join("Smoke");
        let body = serde_json::json!({ "path": &project, "name": "Smoke" }).to_string();
        let created = state.request("POST", "/v1/projects/create", Some(&body)).unwrap();
        assert_eq!(created.status, 200, "{}", created.body);
        let opened = state.snapshot();
        let handle = opened.project.as_ref().unwrap().handle.clone();
        let project_id = opened.project.as_ref().unwrap().project_id.clone();
        let reloaded = state.snapshot();
        assert_eq!(reloaded.generation, generation);
        assert_eq!(reloaded.project.as_ref().unwrap().handle, handle);
        assert_eq!(reloaded.project.as_ref().unwrap().project_id, project_id);

        state.testing_kill_owned_process();
        assert!(
            state.wait_until(Duration::from_secs(5), |session| session.state == Phase::Failed),
            "engine death was not observed"
        );
        let crashed = state.snapshot();
        assert!(crashed.project.is_none());
        assert_eq!(crashed.generation, generation);
        assert_eq!(crashed.notice.as_deref(), Some(CRASH_NOTICE));
        let (_repo, python) = launch::development_command().unwrap();
        assert!(lock_is_free(&python, &project.join("project.lock")));

        state.schedule_restart();
        assert!(state.wait_until(Duration::from_secs(20), |session| session.state == Phase::Ready));
        let restarted = state.snapshot();
        assert!(restarted.generation > generation);
        assert!(restarted.project.is_none());
        assert_eq!(restarted.notice.as_deref(), Some(RESTART_NOTICE));
        let reopened = state.request(
            "POST",
            "/v1/projects/open",
            Some(&serde_json::json!({ "path": &project, "read_only": false }).to_string()),
        )
        .unwrap();
        assert_eq!(reopened.status, 200, "{}", reopened.body);
        let current = state.snapshot().project.unwrap();
        assert_ne!(current.handle, handle);
        assert_eq!(current.project_id, project_id);
        assert_eq!(current.generation, restarted.generation);
        let _ = std::fs::remove_dir_all(&parent);
    }

    fn read_headers(stream: &mut std::net::TcpStream) -> std::io::Result<()> {
        let mut seen = Vec::new();
        let mut byte = [0u8; 1];
        while seen.len() < 8192 {
            if stream.read(&mut byte)? == 0 {
                break;
            }
            seen.push(byte[0]);
            if seen.ends_with(b"\r\n\r\n") {
                break;
            }
        }
        Ok(())
    }

    fn serve_once(status: u16, body: &str) -> u16 {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let body = body.to_string();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let _ = read_headers(&mut stream);
            let response = format!(
                "HTTP/1.1 {status} ERR\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = stream.write_all(response.as_bytes());
        });
        port
    }

    #[test]
    fn playback_files_are_removed_on_close_crash_restart_and_shutdown() {
        let dir = std::env::temp_dir().join(format!("amix-playback-session-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let close_file = dir.join("close.mp4");
        let crash_file = dir.join("crash.mp4");
        let restart_file = dir.join("restart.mp4");
        let shutdown_file = dir.join("shutdown.mp4");
        for path in [&close_file, &crash_file, &restart_file, &shutdown_file] {
            std::fs::write(path, b"preview").unwrap();
        }

        let state = EngineState::new();
        state.testing_ready(9);
        state.apply_response(
            1,
            "POST",
            "/v1/projects/create",
            200,
            r#"{"handle":"h1","project_id":"p1","name":"Smoke","read_only":false,"schema_revision":"0003"}"#,
            Some(r#"{"path":"C:\\work\\Smoke","name":"Smoke"}"#),
        );
        plant_playback(&state, &close_file, 1);
        state.apply_response(1, "POST", "/v1/projects/h1/close", 200, "{}", None);
        assert!(!close_file.exists());
        assert!(state.with_playback(|book| book.exposed().is_empty()));

        state.testing_ready(9);
        plant_playback(&state, &crash_file, 2);
        state.on_process_exit(1);
        assert!(!crash_file.exists());
        assert!(state.with_playback(|book| book.exposed().is_empty()));

        let restarted = EngineState::new();
        restarted.testing_ready(9);
        plant_playback(&restarted, &restart_file, 3);
        let _ = restarted.prepare_restart();
        assert!(!restart_file.exists());

        let stopped = EngineState::new();
        stopped.testing_ready(9);
        plant_playback(&stopped, &shutdown_file, 4);
        stopped.shutdown();
        assert!(!shutdown_file.exists());
        let _ = std::fs::remove_dir_all(&dir);
    }
}

#[cfg(test)]
fn plant_playback(state: &EngineState, path: &std::path::Path, request: u64) {
    state.with_playback(|book| {
        let _ = book.begin(request);
        book.install(crate::playback::Grant {
            generation: 1,
            project_id: "p1".into(),
            source_id: "11111111-1111-4111-8111-111111111111".into(),
            request_id: request,
            exposed: path.to_path_buf(),
        });
    });
}

#[cfg(test)]
struct StopOnDrop(EngineState);

#[cfg(test)]
impl Drop for StopOnDrop {
    fn drop(&mut self) {
        if self.0.snapshot().state != Phase::Stopped {
            self.0.shutdown();
        }
    }
}

#[cfg(test)]
fn lock_is_free(python: &std::path::Path, lock_path: &std::path::Path) -> bool {
    std::process::Command::new(python)
        .arg("-c")
        .arg("import sys; handle=open(sys.argv[1],'a+b'); handle.seek(0); exec('import msvcrt; msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)' if sys.platform=='win32' else 'import fcntl; fcntl.flock(handle.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB); fcntl.flock(handle.fileno(), fcntl.LOCK_UN)'); handle.close()")
        .arg(lock_path)
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}
