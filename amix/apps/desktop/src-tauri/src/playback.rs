// Playback session registry.
//
// JavaScript asks for a media asset id. Rust asks the engine which file that
// asset plays, then exposes one hard link of that file through Tauri's asset
// protocol. The original path is never added to the scope. Each session link
// is unique so it can be forbidden permanently without blocking a later preview.
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Manager, State};

use crate::engine::{EngineState, Phase};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Grant {
    pub generation: u64,
    pub project_id: String,
    pub source_id: String,
    pub request_id: u64,
    pub exposed: PathBuf,
}

#[derive(Debug)]
pub struct PlaybackBook {
    epoch: u64,
    latest_request: u64,
    cancelled: HashSet<u64>,
    grants: Vec<Grant>,
}

impl Default for PlaybackBook {
    fn default() -> Self {
        Self {
            epoch: 0,
            latest_request: 0,
            cancelled: HashSet::new(),
            grants: Vec::new(),
        }
    }
}

impl PlaybackBook {
    /// Accept a newer request. A late result for an older request must not run.
    pub fn begin(&mut self, request_id: u64) -> Option<u64> {
        if request_id < self.latest_request || self.cancelled.contains(&request_id) {
            return None;
        }
        self.latest_request = request_id;
        Some(self.epoch)
    }

    pub fn is_current(&self, request_id: u64, epoch: u64) -> bool {
        self.epoch == epoch && self.latest_request == request_id && !self.cancelled.contains(&request_id)
    }

    /// Replace the exposed file. Returns the hard links that must be revoked.
    pub fn install(&mut self, grant: Grant) -> Vec<PathBuf> {
        let removed = self.grants.drain(..).map(|existing| existing.exposed).collect();
        self.grants.push(grant);
        removed
    }

    pub fn cancel(&mut self, request_id: u64) -> Vec<PathBuf> {
        self.cancelled.insert(request_id);
        let mut removed = Vec::new();
        self.grants.retain(|grant| {
            if grant.request_id == request_id {
                removed.push(grant.exposed.clone());
                false
            } else {
                true
            }
        });
        removed
    }

    /// Drop every grant and invalidate in-flight prepares.
    pub fn clear_all(&mut self) -> Vec<PathBuf> {
        self.epoch = self.epoch.wrapping_add(1);
        self.grants.drain(..).map(|grant| grant.exposed).collect()
    }

    #[cfg(test)]
    pub fn exposed(&self) -> Vec<PathBuf> {
        self.grants.iter().map(|grant| grant.exposed.clone()).collect()
    }

    #[cfg(test)]
    pub fn allows(&self, path: &Path) -> bool {
        self.grants.iter().any(|grant| grant.exposed == path)
    }
}

pub fn valid_asset_id(id: &str) -> bool {
    let bytes = id.as_bytes();
    (32..=36).contains(&bytes.len())
        && bytes.iter().all(|byte| byte.is_ascii_hexdigit() || *byte == b'-')
        && id.matches('-').count() <= 4
}

/// Same encoding as `@tauri-apps/api` `convertFileSrc`. Windows uses the HTTP
/// asset host. Other platforms use the `asset` scheme. macOS playback of that
/// form has not been verified on a Mac.
pub fn asset_url(path: &Path) -> String {
    let encoded = encode_uri_component(&path.to_string_lossy());
    if cfg!(windows) {
        format!("http://asset.localhost/{encoded}")
    } else {
        format!("asset://localhost/{encoded}")
    }
}

fn encode_uri_component(value: &str) -> String {
    let mut out = String::new();
    for byte in value.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'!' | b'~' | b'*' | b'\'' | b'(' | b')' => {
                out.push(byte as char);
            }
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

pub fn playback_link_dir(project_root: &Path) -> PathBuf {
    if project_root.join(".amix").join("project.sqlite").is_file() {
        project_root.join(".amix").join("proxy").join(".playback")
    } else {
        project_root.join("proxy").join(".playback")
    }
}

pub fn confined_proxy(project_root: &Path, resolved: &Path) -> Result<PathBuf, String> {
    let root = project_root
        .canonicalize()
        .map_err(|_| "The project folder is unavailable.".to_string())?;
    let file = resolved
        .canonicalize()
        .map_err(|_| "The preview file is unavailable.".to_string())?;
    if !file.is_file() {
        return Err("The preview file is unavailable.".into());
    }
    let roots = [root.join(".amix").join("proxy"), root.join("proxy")];
    let allowed = roots.iter().any(|proxy_root| {
        file.starts_with(proxy_root) && !file.starts_with(proxy_root.join(".playback"))
    });
    if !allowed {
        return Err("The preview file is unavailable.".into());
    }
    Ok(file)
}

/// The engine named one regular file. Only a session hard link of it is exposed.
pub fn accept_source_file(project_root: &Path, resolved: &Path) -> Result<PathBuf, String> {
    let _root = project_root
        .canonicalize()
        .map_err(|_| "The project folder is unavailable.".to_string())?;
    let file = resolved
        .canonicalize()
        .map_err(|_| "The preview file is unavailable.".to_string())?;
    if !file.is_file() {
        return Err("The preview file is unavailable.".into());
    }
    if file.components().any(|part| part.as_os_str() == ".playback") {
        return Err("The preview file is unavailable.".into());
    }
    Ok(file)
}

pub fn create_session_link(project_root: &Path, source_file: &Path, request_id: u64) -> Result<PathBuf, String> {
    let dir = playback_link_dir(project_root);
    std::fs::create_dir_all(&dir).map_err(|_| "Preview could not be prepared.".to_string())?;
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or(0);
    let link = dir.join(format!("{request_id}-{nanos}.mp4"));
    std::fs::hard_link(source_file, &link).map_err(|_| "Preview could not be prepared on this volume.".to_string())?;
    Ok(link)
}

pub(crate) fn forbid_exposed(app: Option<&AppHandle>, paths: &[PathBuf]) {
    for path in paths {
        if let Some(app) = app {
            let _ = app.asset_protocol_scope().forbid_file(path);
        }
        let _ = std::fs::remove_file(path);
    }
}

fn allow_one(app: &AppHandle, path: &Path) -> Result<(), String> {
    app.asset_protocol_scope()
        .allow_file(path)
        .map_err(|_| "Preview could not be opened.".to_string())
}

#[derive(Serialize)]
pub struct PreparedPlayback {
    pub playable: bool,
    pub status: String,
    pub warning: Option<String>,
    pub message: Option<String>,
    pub source_media_asset_id: String,
    pub playback_media_asset_id: Option<String>,
    pub canonical_origin_us: i64,
    pub playback_duration_us: Option<i64>,
    pub source_duration_us: Option<i64>,
    pub asset_url: Option<String>,
    pub request_id: u64,
    pub byte_size: Option<i64>,
    pub file_mtime_ns: Option<i64>,
    pub stale: bool,
    pub playback_kind: Option<String>,
}

#[derive(Deserialize)]
struct EnginePlayback {
    playable: bool,
    status: String,
    warning: Option<String>,
    source_media_asset_id: String,
    playback_media_asset_id: Option<String>,
    resolved_path: Option<String>,
    playback_duration_us: Option<i64>,
    source_duration_us: Option<i64>,
    canonical_origin_us: Option<i64>,
    byte_size: Option<i64>,
    file_mtime_ns: Option<i64>,
    #[serde(default = "default_playback_kind")]
    playback_kind: String,
}

fn default_playback_kind() -> String {
    "proxy".to_string()
}

#[tauri::command]
pub async fn prepare_playback(
    state: State<'_, EngineState>,
    source_media_asset_id: String,
    request_id: u64,
    prefer: Option<String>,
) -> Result<PreparedPlayback, String> {
    let engine = EngineState::clone(&state);
    tauri::async_runtime::spawn_blocking(move || {
        prepare_blocking(&engine, &source_media_asset_id, request_id, prefer.as_deref())
    })
    .await
    .map_err(|_| "Preview could not be prepared.".to_string())?
}

#[tauri::command]
pub fn release_playback(state: State<'_, EngineState>, request_id: u64) {
    let app = state.app_handle();
    state.with_playback(|book| {
        let paths = book.cancel(request_id);
        forbid_exposed(app.as_ref(), &paths);
    });
}

fn prepare_blocking(
    state: &EngineState,
    source_id: &str,
    request_id: u64,
    prefer: Option<&str>,
) -> Result<PreparedPlayback, String> {
    if !valid_asset_id(source_id) {
        return Err("Choose a media asset to preview.".into());
    }
    let session = state.snapshot();
    let project = session.project.ok_or("Open a project before preview.")?;
    if session.state != Phase::Ready || project.generation != session.generation {
        return Err("The engine is not ready.".into());
    }
    if project.handle.contains(['/', '\\']) {
        return Err("Open a project before preview.".into());
    }
    let epoch = match state.with_playback(|book| book.begin(request_id)) {
        Some(epoch) => epoch,
        None => return Ok(stale_view(source_id, request_id)),
    };
    let preference = match prefer {
        Some("proxy") => "?prefer=proxy",
        _ => "",
    };
    let path = format!("/v1/projects/{}/media/{source_id}/playback{preference}", project.handle);
    let response = match state.request("GET", &path, None) {
        Ok(response) => response,
        Err(_) => return Err("The engine is not ready.".into()),
    };
    if !state.with_playback(|book| book.is_current(request_id, epoch)) {
        return Ok(stale_view(source_id, request_id));
    }
    if response.status >= 400 {
        return Ok(message_view(source_id, request_id, &safe_message(&response.body)));
    }
    let described: EnginePlayback = serde_json::from_str(&response.body).map_err(|_| "Preview could not be prepared.".to_string())?;
    if described.source_media_asset_id != source_id {
        return Ok(message_view(source_id, request_id, "Preview could not be prepared."));
    }
    if !described.playable {
        release_current_grants(state, request_id, epoch);
        return Ok(described_view(&described, request_id, None));
    }
    let after = state.snapshot();
    if after.generation != session.generation || after.project.as_ref().map(|item| item.handle.as_str()) != Some(project.handle.as_str())
    {
        return Ok(stale_view(source_id, request_id));
    }
    let resolved = described.resolved_path.as_deref().ok_or("The preview file is unavailable.")?;
    let project_path = Path::new(&project.path);
    let file = if described.playback_kind == "source" {
        accept_source_file(project_path, Path::new(resolved))?
    } else {
        confined_proxy(project_path, Path::new(resolved))?
    };
    let link = create_session_link(Path::new(&project.path), &file, request_id)?;
    let app = state.app_handle();
    let committed = state.with_playback(|book| {
        if !book.is_current(request_id, epoch) {
            let _ = std::fs::remove_file(&link);
            return Commit::Superseded;
        }
        let removed = book.install(Grant {
            generation: session.generation,
            project_id: project.project_id.clone(),
            source_id: source_id.to_string(),
            request_id,
            exposed: link.clone(),
        });
        let Some(app) = app.as_ref() else {
            let _ = std::fs::remove_file(&link);
            book.cancel(request_id);
            return Commit::Failed;
        };
        forbid_exposed(Some(app), &removed);
        if allow_one(app, &link).is_err() {
            let _ = std::fs::remove_file(&link);
            book.cancel(request_id);
            return Commit::Failed;
        }
        Commit::Ready
    });
    match committed {
        Commit::Superseded => Ok(stale_view(source_id, request_id)),
        Commit::Failed => Ok(message_view(source_id, request_id, "Preview could not be opened.")),
        Commit::Ready => Ok(described_view(&described, request_id, Some(asset_url(&link)))),
    }
}

enum Commit {
    Ready,
    Superseded,
    Failed,
}

fn release_current_grants(state: &EngineState, request_id: u64, epoch: u64) {
    let app = state.app_handle();
    state.with_playback(|book| {
        if book.is_current(request_id, epoch) {
            let paths = book.clear_all();
            // clear_all bumps the epoch, which would also drop this request.
            // Restore current-ness for this still-active request id by beginning it again.
            let _ = book.begin(request_id);
            forbid_exposed(app.as_ref(), &paths);
        }
    });
}

fn stale_view(source_id: &str, request_id: u64) -> PreparedPlayback {
    PreparedPlayback {
        playable: false,
        status: "stale_request".into(),
        warning: None,
        message: None,
        source_media_asset_id: source_id.into(),
        playback_media_asset_id: None,
        canonical_origin_us: 0,
        playback_duration_us: None,
        source_duration_us: None,
        asset_url: None,
        request_id,
        byte_size: None,
        file_mtime_ns: None,
        stale: true,
        playback_kind: None,
    }
}

fn message_view(source_id: &str, request_id: u64, message: &str) -> PreparedPlayback {
    PreparedPlayback {
        playable: false,
        status: "unavailable".into(),
        warning: None,
        message: Some(message.to_string()),
        source_media_asset_id: source_id.into(),
        playback_media_asset_id: None,
        canonical_origin_us: 0,
        playback_duration_us: None,
        source_duration_us: None,
        asset_url: None,
        request_id,
        byte_size: None,
        file_mtime_ns: None,
        stale: false,
        playback_kind: None,
    }
}

fn described_view(described: &EnginePlayback, request_id: u64, asset_url: Option<String>) -> PreparedPlayback {
    PreparedPlayback {
        playable: described.playable && asset_url.is_some(),
        status: described.status.clone(),
        warning: described.warning.clone(),
        message: None,
        source_media_asset_id: described.source_media_asset_id.clone(),
        playback_media_asset_id: described.playback_media_asset_id.clone(),
        canonical_origin_us: described.canonical_origin_us.unwrap_or(0),
        playback_duration_us: described.playback_duration_us,
        source_duration_us: described.source_duration_us,
        asset_url,
        request_id,
        byte_size: described.byte_size,
        file_mtime_ns: described.file_mtime_ns,
        stale: false,
        playback_kind: Some(described.playback_kind.clone()),
    }
}

fn safe_message(body: &str) -> String {
    let fallback = "Preview could not be prepared.";
    let Ok(value) = serde_json::from_str::<Value>(body) else {
        return fallback.into();
    };
    let Some(message) = value.get("error").and_then(|error| error.get("message")).and_then(|message| message.as_str()) else {
        return fallback.into();
    };
    if message.len() > 200 || message.contains(['/', '\\']) {
        return fallback.into();
    }
    message.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn an_asset_id_is_not_a_filesystem_path() {
        assert!(valid_asset_id("11111111-1111-4111-8111-111111111111"));
        assert!(!valid_asset_id(r"C:\Users\Public\secret.mp4"));
        assert!(!valid_asset_id("/etc/passwd"));
        assert!(!valid_asset_id("../proxy/clip.mp4"));
        assert!(!valid_asset_id(""));
        assert!(!valid_asset_id("not a uuid"));
    }

    #[test]
    fn asset_url_matches_the_tauri_converter() {
        let path = if cfg!(windows) {
            PathBuf::from(r"C:\project\proxy\.playback\1.mp4")
        } else {
            PathBuf::from("/project/proxy/.playback/1.mp4")
        };
        let url = asset_url(&path);
        if cfg!(windows) {
            assert!(url.starts_with("http://asset.localhost/"));
            assert!(url.contains("%5C"));
            assert!(!url.contains("asset://"));
        } else {
            assert!(url.starts_with("asset://localhost/"));
        }
        assert!(!url.contains(' '));
    }

    #[test]
    fn a_late_request_cannot_replace_the_current_file() {
        let mut book = PlaybackBook::default();
        let first = book.begin(1).unwrap();
        let second = book.begin(2).unwrap();
        assert!(!book.is_current(1, first));
        assert!(book.is_current(2, second));
        assert!(book.begin(1).is_none());
        let link = PathBuf::from("link-b.mp4");
        book.install(Grant {
            generation: 1,
            project_id: "p".into(),
            source_id: "b".into(),
            request_id: 2,
            exposed: link.clone(),
        });
        assert!(book.allows(&link));
        assert_eq!(book.exposed(), vec![link]);
    }

    #[test]
    fn only_the_session_link_is_exposed() {
        let mut book = PlaybackBook::default();
        let epoch = book.begin(1).unwrap();
        let original = PathBuf::from("proxy/original.mp4");
        let sibling = PathBuf::from("proxy/sibling.mp4");
        let link = PathBuf::from("proxy/.playback/1.mp4");
        book.install(Grant {
            generation: 1,
            project_id: "p".into(),
            source_id: "source".into(),
            request_id: 1,
            exposed: link.clone(),
        });
        assert!(book.is_current(1, epoch));
        assert!(book.allows(&link));
        assert!(!book.allows(&original));
        assert!(!book.allows(&sibling));
        assert_eq!(book.exposed().len(), 1);
    }

    #[test]
    fn close_restart_and_cancel_drop_the_exposed_file() {
        let mut book = PlaybackBook::default();
        let epoch = book.begin(4).unwrap();
        book.install(Grant {
            generation: 3,
            project_id: "p".into(),
            source_id: "source".into(),
            request_id: 4,
            exposed: PathBuf::from("link.mp4"),
        });
        let removed = book.clear_all();
        assert_eq!(removed, vec![PathBuf::from("link.mp4")]);
        assert!(book.exposed().is_empty());
        assert!(!book.is_current(4, epoch));

        let mut book = PlaybackBook::default();
        book.begin(2).unwrap();
        book.install(Grant {
            generation: 1,
            project_id: "p".into(),
            source_id: "a".into(),
            request_id: 1,
            exposed: PathBuf::from("old.mp4"),
        });
        book.install(Grant {
            generation: 1,
            project_id: "p".into(),
            source_id: "b".into(),
            request_id: 2,
            exposed: PathBuf::from("new.mp4"),
        });
        let dropped = book.cancel(1);
        assert!(dropped.is_empty());
        assert!(book.allows(Path::new("new.mp4")));
        let dropped = book.cancel(2);
        assert_eq!(dropped, vec![PathBuf::from("new.mp4")]);
        assert!(!book.allows(Path::new("new.mp4")));
    }

    #[test]
    fn a_session_link_is_a_hard_link_and_stays_inside_proxy() {
        let root = std::env::temp_dir().join(format!("amix-playback-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("proxy")).unwrap();
        let source = root.join("proxy").join("clip.mp4");
        let sibling = root.join("proxy").join("other.mp4");
        fs::write(&source, b"preview-bytes").unwrap();
        fs::write(&sibling, b"sibling").unwrap();
        let outside = root.join("secret.mp4");
        fs::write(&outside, b"nope").unwrap();
        let link = create_session_link(&root, &source, 7).unwrap();
        assert!(link.starts_with(root.join("proxy").join(".playback")));
        assert_eq!(fs::read(&link).unwrap(), b"preview-bytes");
        fs::write(&source, b"changed").unwrap();
        assert_eq!(fs::read(&link).unwrap(), b"changed");
        assert_eq!(fs::read(&sibling).unwrap(), b"sibling");
        let confined = confined_proxy(&root, &source).unwrap();
        assert_eq!(confined, source.canonicalize().unwrap());
        assert!(confined_proxy(&root, &outside).is_err());
        assert!(confined_proxy(&root, &link).is_err());
        let mut book = PlaybackBook::default();
        book.begin(7).unwrap();
        book.install(Grant {
            generation: 1,
            project_id: "p".into(),
            source_id: "source".into(),
            request_id: 7,
            exposed: link.clone(),
        });
        assert!(book.allows(&link));
        assert!(!book.allows(&source));
        assert!(!book.allows(&sibling));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn a_modern_proxy_and_an_external_source_link_inside_the_session_dir() {
        let root = std::env::temp_dir().join(format!("amix-source-playback-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join(".amix").join("proxy")).unwrap();
        fs::write(root.join(".amix").join("project.sqlite"), b"db").unwrap();
        let proxy = root.join(".amix").join("proxy").join("clip.mp4");
        fs::write(&proxy, b"proxy-bytes").unwrap();
        let outside = root.join("secret.mp4");
        fs::write(&outside, b"nope").unwrap();
        assert!(confined_proxy(&root, &proxy).is_ok());
        assert!(confined_proxy(&root, &outside).is_err());
        let source = std::env::temp_dir().join(format!("amix-source-file-{}.mp4", std::process::id()));
        fs::write(&source, b"source-bytes").unwrap();
        let accepted = accept_source_file(&root, &source).unwrap();
        assert_eq!(accepted, source.canonicalize().unwrap());
        let link = create_session_link(&root, &accepted, 9).unwrap();
        assert!(link.starts_with(root.join(".amix").join("proxy").join(".playback")));
        assert_eq!(fs::read(&link).unwrap(), b"source-bytes");
        let mut book = PlaybackBook::default();
        book.begin(9).unwrap();
        book.install(Grant {
            generation: 1,
            project_id: "p".into(),
            source_id: "source".into(),
            request_id: 9,
            exposed: link.clone(),
        });
        assert!(book.allows(&link));
        assert!(!book.allows(&source));
        assert!(!book.allows(&proxy));
        let _ = fs::remove_file(&source);
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn the_prepared_view_does_not_carry_a_filesystem_path() {
        let view = described_view(
            &EnginePlayback {
                playable: true,
                status: "ready".into(),
                warning: None,
                source_media_asset_id: "11111111-1111-4111-8111-111111111111".into(),
                playback_media_asset_id: None,
                resolved_path: Some(r"C:\secret\proxy.mp4".into()),
                playback_duration_us: Some(10),
                source_duration_us: Some(10),
                canonical_origin_us: Some(1_500_000),
                byte_size: Some(4),
                file_mtime_ns: Some(9),
                playback_kind: "proxy".into(),
            },
            3,
            Some("http://asset.localhost/link".into()),
        );
        let json = serde_json::to_string(&view).unwrap();
        assert!(!json.contains("resolved_path"));
        assert!(!json.contains("secret"));
        assert!(json.contains("\"canonical_origin_us\":1500000"));
        assert!(json.contains("http://asset.localhost/link"));
    }
}
