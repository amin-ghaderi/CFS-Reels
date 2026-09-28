use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;

use crate::ready::{parse_ready_line, ReadyRecord};

const READY_TIMEOUT: Duration = Duration::from_secs(20);

pub struct EngineChild {
    child: Option<Child>,
    pub record: ReadyRecord,
    stdout_thread: Option<thread::JoinHandle<()>>,
    stderr_thread: Option<thread::JoinHandle<()>>,
}

impl EngineChild {
    pub fn process_id(&self) -> u32 {
        self.child.as_ref().map(Child::id).unwrap_or(0)
    }
}

pub fn development_command() -> Result<(PathBuf, PathBuf), String> {
    let repo = find_repository().ok_or_else(|| {
        "The AMIX development tree was not found beside this application.".to_string()
    })?;
    let python = interpreter(&repo);
    if !python.is_file() {
        return Err(
            "The development engine was not found in amix/.venv. AMIX will not use another Python."
                .into(),
        );
    }
    Ok((repo, python))
}

pub fn spawn_development_engine() -> Result<EngineChild, String> {
    let (repo, python) = development_command()?;
    let mut command = Command::new(&python);
    command
        .arg("-m")
        .arg("amix.amix_engine.service")
        .current_dir(&repo)
        .env("PYTHONUNBUFFERED", "1")
        .env("AMIX_HOST", "127.0.0.1")
        .env("AMIX_PORT", "0")
        .env_remove("AMIX_SESSION_TOKEN")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    hide_console(&mut command);
    isolate_process_group(&mut command);
    let mut child = command.spawn().map_err(|_| {
        "The development engine process could not be started.".to_string()
    })?;
    let stdout = child.stdout.take().ok_or("Engine stdout was unavailable.")?;
    let stderr = child.stderr.take().ok_or("Engine stderr was unavailable.")?;
    let secret = Arc::new(Mutex::new(None::<String>));
    let stderr_secret = Arc::clone(&secret);
    let stderr_thread = Some(thread::spawn(move || drain_stderr(stderr, stderr_secret)));
    let (sender, receiver) = mpsc::channel();
    let stdout_thread = Some(thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let result = read_until_ready(&mut reader);
        let _ = sender.send(result);
        let mut discarded = String::new();
        while reader.read_line(&mut discarded).unwrap_or(0) > 0 {
            discarded.clear();
        }
    }));
    let record = match receiver.recv_timeout(READY_TIMEOUT) {
        Ok(Ok(record)) => record,
        Ok(Err(message)) => {
            cleanup(child, stdout_thread, stderr_thread);
            return Err(message);
        }
        Err(_) => {
            cleanup(child, stdout_thread, stderr_thread);
            return Err("The engine did not become ready in time.".into());
        }
    };
    if let Ok(mut slot) = secret.lock() {
        *slot = Some(record.token.clone());
    }
    Ok(EngineChild {
        child: Some(child),
        record,
        stdout_thread,
        stderr_thread,
    })
}

pub fn stop_engine(engine: EngineChild) {
    drop(engine);
}

impl Drop for EngineChild {
    fn drop(&mut self) {
        if let Some(mut child) = self.child.take() {
            terminate(&mut child);
        }
        if let Some(thread) = self.stdout_thread.take() {
            let _ = thread.join();
        }
        if let Some(thread) = self.stderr_thread.take() {
            let _ = thread.join();
        }
    }
}

fn cleanup(
    mut child: Child,
    stdout_thread: Option<thread::JoinHandle<()>>,
    stderr_thread: Option<thread::JoinHandle<()>>,
) {
    terminate(&mut child);
    if let Some(thread) = stdout_thread {
        let _ = thread.join();
    }
    if let Some(thread) = stderr_thread {
        let _ = thread.join();
    }
}

fn read_until_ready(reader: &mut impl BufRead) -> Result<ReadyRecord, String> {
    let mut line = String::new();
    loop {
        line.clear();
        match reader.read_line(&mut line) {
            Ok(0) => return Err("The engine exited before it was ready.".into()),
            Ok(_) if line.trim().is_empty() => continue,
            Ok(_) => return parse_ready_line(&line),
            Err(_) => return Err("The engine ready record could not be read.".into()),
        }
    }
}

fn drain_stderr(stderr: impl std::io::Read, secret: Arc<Mutex<Option<String>>>) {
    let reader = BufReader::new(stderr);
    for line in reader.lines() {
        let Ok(line) = line else {
            break;
        };
        let token = secret.lock().ok().and_then(|slot| slot.clone());
        let redacted = crate::transport::redact(&line, token.as_deref());
        eprintln!("{redacted}");
    }
}

fn find_repository() -> Option<PathBuf> {
    let mut starts = Vec::new();
    if let Ok(current) = std::env::current_dir() {
        starts.push(current);
    }
    if let Ok(executable) = std::env::current_exe() {
        if let Some(parent) = executable.parent() {
            starts.push(parent.to_path_buf());
        }
    }
    starts.into_iter().find_map(|start| walk_for_repository(&start))
}

fn walk_for_repository(start: &Path) -> Option<PathBuf> {
    let mut current = Some(start);
    while let Some(directory) = current {
        let marker = directory.join("amix").join("pyproject.toml");
        let service = directory
            .join("amix")
            .join("amix_engine")
            .join("service")
            .join("__main__.py");
        if marker.is_file() && service.is_file() {
            return Some(directory.to_path_buf());
        }
        current = directory.parent();
    }
    None
}

fn interpreter(repo: &Path) -> PathBuf {
    let venv = repo.join("amix").join(".venv");
    if cfg!(windows) {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

fn hide_console(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let _ = command;
}

fn isolate_process_group(command: &mut Command) {
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let _ = command;
}

pub fn terminate(child: &mut Child) {
    #[cfg(unix)]
    {
        let pid = child.id() as i32;
        unsafe {
            libc::kill(-pid, libc::SIGTERM);
        }
        let started = std::time::Instant::now();
        loop {
            match child.try_wait() {
                Ok(Some(_)) => return,
                Ok(None) if started.elapsed() < Duration::from_secs(3) => {
                    thread::sleep(Duration::from_millis(50));
                }
                _ => {
                    unsafe {
                        libc::kill(-pid, libc::SIGKILL);
                    }
                    let _ = child.wait();
                    return;
                }
            }
        }
    }
    #[cfg(windows)]
    {
        let _ = Command::new("taskkill")
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        let _ = child.kill();
        let _ = child.wait();
    }
}
