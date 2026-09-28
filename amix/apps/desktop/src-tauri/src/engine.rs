use std::sync::{Arc, Condvar, Mutex};
use std::thread;
#[cfg(test)]
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, State};

use crate::launch::{self, EngineChild};
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
            }),
        }
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
        let response = transport::engine_http(port, &token, method, path, body, timeouts_for(method, path))?;
        self.apply_response(generation, method, path, response.status, &response.body, body);
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
        match launch::spawn_development_engine() {
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
                self.publish();
            }
        } else if method == "POST" && path.starts_with("/v1/projects/") && path.ends_with("/close") && status < 400
        {
            inner.project = None;
            drop(inner);
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

#[tauri::command]
pub fn join_project_path(parent: String, name: String) -> Result<String, String> {
    crate::paths::join_project_path(&parent, &name).map(|path| path.to_string_lossy().into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

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
