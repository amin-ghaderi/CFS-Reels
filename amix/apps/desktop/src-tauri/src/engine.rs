use std::thread;
use std::time::Duration;

use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Manager, State};

use crate::launch::{self, EngineChild};
use crate::transport;

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum Phase {
    Starting,
    Ready,
    Failed,
    Stopped,
}

#[derive(Clone, Serialize)]
pub struct EngineStatus {
    pub state: Phase,
    pub message: String,
    pub host: Option<String>,
    pub port: Option<u16>,
    pub version: Option<String>,
}

#[derive(Serialize)]
pub struct EngineResponse {
    pub status: u16,
    pub body: String,
}

pub struct EngineState {
    inner: std::sync::Mutex<Inner>,
}

struct Inner {
    phase: Phase,
    message: String,
    host: Option<String>,
    port: Option<u16>,
    token: Option<String>,
    version: Option<String>,
    engine: Option<EngineChild>,
    project_handle: Option<String>,
    generation: u64,
}

impl EngineState {
    pub fn new() -> Self {
        Self {
            inner: std::sync::Mutex::new(Inner {
                phase: Phase::Starting,
                message: "Starting the local engine.".into(),
                host: None,
                port: None,
                token: None,
                version: None,
                engine: None,
                project_handle: None,
                generation: 0,
            }),
        }
    }

    pub fn status(&self) -> EngineStatus {
        let inner = self.inner.lock().expect("engine state");
        EngineStatus {
            state: inner.phase,
            message: inner.message.clone(),
            host: inner.host.clone(),
            port: inner.port,
            version: inner.version.clone(),
        }
    }

    pub fn request(
        &self,
        method: &str,
        path: &str,
        body: Option<&str>,
    ) -> Result<EngineResponse, String> {
        let (port, token) = {
            let inner = self.inner.lock().expect("engine state");
            if !matches!(inner.phase, Phase::Ready) {
                return Err("The engine is not ready.".into());
            }
            let port = inner.port.ok_or("The engine is not ready.")?;
            let token = inner.token.clone().ok_or("The engine is not ready.")?;
            (port, token)
        };
        let response = transport::engine_http(
            port,
            &token,
            method,
            path,
            body,
            Duration::from_secs(15),
        )?;
        if response.status < 400 {
            self.remember_project(method, path, &response.body);
        }
        Ok(EngineResponse {
            status: response.status,
            body: response.body,
        })
    }

    pub fn shutdown(&self) {
        let (engine, token, port, handle) = {
            let mut inner = self.inner.lock().expect("engine state");
            inner.generation = inner.generation.wrapping_add(1);
            inner.phase = Phase::Stopped;
            inner.message = "Engine stopped.".into();
            inner.host = None;
            inner.version = None;
            (
                inner.engine.take(),
                inner.token.take(),
                inner.port.take(),
                inner.project_handle.take(),
            )
        };
        if let (Some(token), Some(port), Some(handle)) = (token, port, handle) {
            let path = format!("/v1/projects/{handle}/close");
            let _ = transport::engine_http(port, &token, "POST", &path, None, Duration::from_secs(3));
        }
        if let Some(engine) = engine {
            launch::stop_engine(engine);
        }
    }

    fn remember_project(&self, method: &str, path: &str, body: &str) {
        let mut inner = self.inner.lock().expect("engine state");
        if method == "POST" && (path == "/v1/projects/create" || path == "/v1/projects/open") {
            if let Some(handle) = json_field(body, "handle") {
                inner.project_handle = Some(handle);
            }
        } else if method == "POST" && path.starts_with("/v1/projects/") && path.ends_with("/close") {
            inner.project_handle = None;
        }
    }
}

pub fn schedule_start(app: AppHandle) {
    let generation = begin_start(&app);
    thread::spawn(move || finish_start(app, generation));
}

fn begin_start(app: &AppHandle) -> u64 {
    let state = app.state::<EngineState>();
    let mut inner = state.inner.lock().expect("engine state");
    inner.generation = inner.generation.wrapping_add(1);
    inner.phase = Phase::Starting;
    inner.message = "Starting the local engine.".into();
    inner.host = None;
    inner.port = None;
    inner.token = None;
    inner.version = None;
    let generation = inner.generation;
    let previous = inner.engine.take();
    let handle = inner.project_handle.take();
    drop(inner);
    if previous.is_some() || handle.is_some() {
        let app = app.clone();
        thread::spawn(move || {
            release_previous(&app, previous, handle);
        });
    }
    generation
}

fn release_previous(app: &AppHandle, engine: Option<EngineChild>, handle: Option<String>) {
    if let Some(engine) = engine {
        if let Some(handle) = handle {
            let path = format!("/v1/projects/{handle}/close");
            let _ = transport::engine_http(
                engine.record.port,
                &engine.record.token,
                "POST",
                &path,
                None,
                Duration::from_secs(3),
            );
        }
        launch::stop_engine(engine);
    }
    let _ = app;
}

fn finish_start(app: AppHandle, generation: u64) {
    match launch::spawn_development_engine() {
        Ok(engine) => publish_ready(&app, generation, engine),
        Err(message) => publish_failure(&app, generation, message),
    }
}

fn publish_ready(app: &AppHandle, generation: u64, engine: EngineChild) {
    let health = transport::engine_http(
        engine.record.port,
        &engine.record.token,
        "GET",
        "/v1/health",
        None,
        Duration::from_secs(5),
    );
    let version = health.as_ref().ok().and_then(|response| {
        if response.status == 200 {
            json_field(&response.body, "version")
        } else {
            None
        }
    });
    let state = app.state::<EngineState>();
    let mut inner = state.inner.lock().expect("engine state");
    if inner.generation != generation {
        drop(inner);
        launch::stop_engine(engine);
        return;
    }
    if version.is_none() {
        drop(inner);
        launch::stop_engine(engine);
        publish_failure(app, generation, "The engine started but did not answer a health check.".into());
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

fn publish_failure(app: &AppHandle, generation: u64, message: String) {
    let state = app.state::<EngineState>();
    let mut inner = state.inner.lock().expect("engine state");
    if inner.generation != generation {
        return;
    }
    inner.phase = Phase::Failed;
    inner.message = message;
    inner.host = None;
    inner.port = None;
    inner.token = None;
    inner.version = None;
    inner.engine = None;
}

fn json_field(body: &str, field: &str) -> Option<String> {
    let value: Value = serde_json::from_str(body).ok()?;
    value.get(field)?.as_str().map(str::to_string)
}

#[tauri::command]
pub fn engine_status(state: State<'_, EngineState>) -> EngineStatus {
    state.status()
}

#[tauri::command]
pub fn engine_retry(app: AppHandle) -> EngineStatus {
    schedule_start(app.clone());
    app.state::<EngineState>().status()
}

#[tauri::command]
pub fn engine_request(
    state: State<'_, EngineState>,
    method: String,
    path: String,
    body: Option<String>,
) -> Result<EngineResponse, String> {
    state.request(&method, &path, body.as_deref())
}

#[tauri::command]
pub fn join_project_path(parent: String, name: String) -> Result<String, String> {
    crate::paths::join_project_path(&parent, &name).map(|path| path.to_string_lossy().into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn status_does_not_serialize_a_session_token() {
        let status = EngineStatus {
            state: Phase::Ready,
            message: "Engine ready.".into(),
            host: Some("127.0.0.1".into()),
            port: Some(9),
            version: Some("0.4.0".into()),
        };
        let json = serde_json::to_string(&status).unwrap();
        assert!(json.contains("\"READY\""));
        assert!(!json.to_ascii_lowercase().contains("token"));
        assert!(!json.to_ascii_lowercase().contains("authorization"));
    }
}
