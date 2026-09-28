use std::path::PathBuf;
use std::process::Command;
use std::time::{Duration, Instant};

use amix_desktop_lib::launch::{self, stop_engine};
use amix_desktop_lib::paths::join_project_path;
use amix_desktop_lib::transport::{engine_http, HttpTimeouts};

#[test]
fn development_engine_serves_a_project_and_releases_its_lock() {
    let before = service_process_count();
    let (repo, python) = launch::development_command().expect("development engine");
    let engine = launch::spawn_development_engine().expect("engine ready record");
    let port = engine.record.port;
    let token = engine.record.token.clone();
    let pid = engine.process_id();
    assert_eq!(engine.record.host, "127.0.0.1");
    assert!(port > 0);

    let health = engine_http(port, &token, "GET", "/v1/health", None, HttpTimeouts::health())
        .expect("health");
    assert_eq!(health.status, 200);
    assert!(health.body.contains("amix-engine"));
    assert!(!health.body.contains(&token));

    let parent = std::env::temp_dir().join(format!("amix-desktop-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&parent);
    std::fs::create_dir_all(&parent).unwrap();
    let project = join_project_path(&parent.to_string_lossy(), "Smoke").unwrap();
    let created = engine_http(
        port,
        &token,
        "POST",
        "/v1/projects/create",
        Some(&serde_json::json!({ "path": project, "name": "Smoke" }).to_string()),
        HttpTimeouts::standard(),
    )
    .expect("create");
    assert_eq!(created.status, 200, "{}", created.body);
    let handle = serde_json::from_str::<serde_json::Value>(&created.body)
        .unwrap()["handle"]
        .as_str()
        .unwrap()
        .to_string();

    let job = engine_http(
        port,
        &token,
        "POST",
        &format!("/v1/projects/{handle}/jobs"),
        Some(r#"{"kind":"project_integrity_check","spec":{}}"#),
        HttpTimeouts::standard(),
    )
    .expect("job");
    assert_eq!(job.status, 200, "{}", job.body);
    let job_id = serde_json::from_str::<serde_json::Value>(&job.body).unwrap()["job_id"]
        .as_str()
        .unwrap()
        .to_string();

    let started = Instant::now();
    let mut status = String::new();
    while started.elapsed() < Duration::from_secs(10) {
        status = job_status(port, &token, &handle, &job_id);
        if is_settled(&status) {
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    assert_eq!(status, "SUCCEEDED");

    let cancel = engine_http(
        port,
        &token,
        "POST",
        &format!("/v1/projects/{handle}/jobs/{job_id}/cancel"),
        None,
        HttpTimeouts::health(),
    )
    .expect("cancel");
    assert_eq!(cancel.status, 409, "{}", cancel.body);
    assert!(cancel.body.contains("invalid_job_state"));

    let closed = engine_http(
        port,
        &token,
        "POST",
        &format!("/v1/projects/{handle}/close"),
        None,
        HttpTimeouts::close(),
    )
    .expect("close");
    assert_eq!(closed.status, 200, "{}", closed.body);

    stop_engine(engine);
    assert!(process_is_gone(pid), "engine process {pid} was still running");
    std::thread::sleep(Duration::from_millis(200));
    assert_eq!(
        service_process_count(),
        before,
        "an engine process was still running after shutdown"
    );
    let lock = project.join("project.lock");
    let probe = lock_probe(&python, &lock);
    assert!(probe.is_ok(), "project lock still held: {probe:?}");

    let _ = std::fs::remove_dir_all(&parent);
    let _ = repo;
}

fn is_settled(status: &str) -> bool {
    status != "QUEUED" && status != "RUNNING" && status != "CANCEL_REQUESTED"
}

fn job_status(port: u16, token: &str, handle: &str, job_id: &str) -> String {
    let current = engine_http(
        port,
        token,
        "GET",
        &format!("/v1/projects/{handle}/jobs/{job_id}"),
        None,
        HttpTimeouts::health(),
    )
    .expect("job status");
    json_string(&current.body, "status")
}

fn json_string(body: &str, field: &str) -> String {
    serde_json::from_str::<serde_json::Value>(body).unwrap()[field]
        .as_str()
        .unwrap_or("")
        .to_string()
}

fn service_process_count() -> usize {
    #[cfg(windows)]
    {
        let output = Command::new("powershell")
            .args([
                "-NoProfile",
                "-Command",
                "$rows = @(Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | Where-Object { $_.CommandLine -like '*amix.amix_engine.service*' }); $rows.Count",
            ])
            .output()
            .expect("process list");
        let text = String::from_utf8_lossy(&output.stdout);
        return text.trim().parse().unwrap_or(0);
    }
    #[cfg(unix)]
    {
        let output = Command::new("ps")
            .args(["-ax", "-o", "command="])
            .output()
            .expect("process list");
        let text = String::from_utf8_lossy(&output.stdout);
        text.lines()
            .filter(|line| line.contains("amix.amix_engine.service"))
            .count()
    }
}

fn process_is_gone(pid: u32) -> bool {
    #[cfg(windows)]
    {
        let output = Command::new("tasklist")
            .args(["/FI", &format!("PID eq {pid}"), "/NH"])
            .output()
            .expect("tasklist");
        let text = String::from_utf8_lossy(&output.stdout);
        return !text.contains(&pid.to_string());
    }
    #[cfg(unix)]
    {
        let listed = Command::new("ps")
            .args(["-p", &pid.to_string()])
            .status()
            .map(|status| status.success())
            .unwrap_or(false);
        !listed
    }
}

fn lock_probe(python: &PathBuf, lock_path: &PathBuf) -> Result<(), String> {
    let output = Command::new(python)
        .arg("-c")
        .arg("import sys; handle=open(sys.argv[1],'a+b'); handle.seek(0); exec('import msvcrt; msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)' if sys.platform=='win32' else 'import fcntl; fcntl.flock(handle.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB); fcntl.flock(handle.fileno(), fcntl.LOCK_UN)'); handle.close()")
        .arg(lock_path)
        .output()
        .map_err(|error| error.to_string())?;
    if output.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).into_owned())
    }
}
