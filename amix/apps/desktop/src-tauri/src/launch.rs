use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{mpsc, Arc, Mutex, OnceLock};
use std::thread;
use std::time::Duration;

use crate::ready::{parse_ready_line, ReadyRecord};

const READY_TIMEOUT: Duration = Duration::from_secs(20);

pub struct EngineChild {
    pid: u32,
    pub record: ReadyRecord,
    /// Fires once when the owned process has been reaped. Taken by the session watcher.
    exit_rx: Option<mpsc::Receiver<()>>,
    waiter: Option<thread::JoinHandle<()>>,
    stdout_thread: Option<thread::JoinHandle<()>>,
    stderr_thread: Option<thread::JoinHandle<()>>,
}

impl EngineChild {
    pub fn process_id(&self) -> u32 {
        self.pid
    }

    pub fn take_exit(&mut self) -> Option<mpsc::Receiver<()>> {
        self.exit_rx.take()
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

pub fn engine_arguments(app_data: Option<&Path>) -> Vec<String> {
    let mut args = vec!["-m".to_string(), "amix.amix_engine.service".to_string()];
    if let Some(path) = app_data {
        args.push("--app-data".to_string());
        args.push(path.to_string_lossy().into_owned());
    }
    args
}

pub fn spawn_development_engine(app_data: Option<&Path>) -> Result<EngineChild, String> {
    let (repo, python) = development_command()?;
    let mut command = Command::new(&python);
    for arg in engine_arguments(app_data) {
        command.arg(arg);
    }
    command
        .current_dir(&repo)
        .env("PYTHONUNBUFFERED", "1")
        .env("AMIX_HOST", "127.0.0.1")
        .env("AMIX_PORT", "0")
        .env("AMIX_OWNER_PID", std::process::id().to_string())
        .env_remove("AMIX_SESSION_TOKEN")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    hide_console(&mut command);
    isolate_process_group(&mut command);
    let mut child = command.spawn().map_err(|_| {
        "The development engine process could not be started.".to_string()
    })?;
    // A closed or crashed desktop must not leave the engine holding a project lock.
    // The job covers a normal launch. AMIX_OWNER_PID covers a desktop that is already
    // inside another job, where assigning this child can fail.
    bind_engine_lifetime(&child);
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
    let pid = child.id();
    let (exit_tx, exit_rx) = mpsc::channel();
    let waiter = Some(thread::spawn(move || {
        let _ = child.wait();
        let _ = exit_tx.send(());
    }));
    Ok(EngineChild {
        pid,
        record,
        exit_rx: Some(exit_rx),
        waiter,
        stdout_thread,
        stderr_thread,
    })
}

pub fn stop_engine(engine: EngineChild) {
    drop(engine);
}

impl Drop for EngineChild {
    fn drop(&mut self) {
        kill_process_tree(self.pid);
        if let Some(exit_rx) = self.exit_rx.take() {
            let _ = exit_rx.recv_timeout(Duration::from_secs(5));
        }
        if let Some(waiter) = self.waiter.take() {
            let _ = waiter.join();
        }
        if let Some(thread) = self.stdout_thread.take() {
            let _ = thread.join();
        }
        if let Some(thread) = self.stderr_thread.take() {
            let _ = thread.join();
        }
    }
}

/// Stops the engine process and every child it spawned. Does not wait; the waiter thread reaps it.
pub fn kill_process_tree(pid: u32) {
    if pid == 0 {
        return;
    }
    #[cfg(unix)]
    {
        let pid = pid as i32;
        unsafe {
            libc::kill(-pid, libc::SIGTERM);
        }
        thread::sleep(Duration::from_millis(200));
        unsafe {
            libc::kill(-pid, libc::SIGKILL);
        }
    }
    #[cfg(windows)]
    {
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
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

fn bind_engine_lifetime(child: &Child) {
    #[cfg(windows)]
    {
        use std::os::windows::io::AsRawHandle;
        unsafe {
            let job = engine_job();
            if !job.is_null() {
                let _ = AssignProcessToJobObject(job, child.as_raw_handle());
            }
        }
    }
    let _ = child;
}

#[cfg(windows)]
struct SharedJob(*mut core::ffi::c_void);
#[cfg(windows)]
unsafe impl Send for SharedJob {}
#[cfg(windows)]
unsafe impl Sync for SharedJob {}

#[cfg(windows)]
fn engine_job() -> *mut core::ffi::c_void {
    static JOB: OnceLock<SharedJob> = OnceLock::new();
    JOB.get_or_init(|| unsafe { SharedJob(create_kill_on_close_job()) }).0
}

#[cfg(windows)]
unsafe fn create_kill_on_close_job() -> *mut core::ffi::c_void {
    let job = CreateJobObjectW(std::ptr::null_mut(), std::ptr::null());
    if job.is_null() {
        return job;
    }
    let mut limits = JobObjectBasicLimitInformation::default();
    limits.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    let ok = SetInformationJobObject(
        job,
        JOB_OBJECT_BASIC_LIMIT_INFORMATION_CLASS,
        &limits as *const JobObjectBasicLimitInformation as *const core::ffi::c_void,
        std::mem::size_of::<JobObjectBasicLimitInformation>() as u32,
    );
    if ok == 0 {
        let _ = CloseHandle(job);
        return std::ptr::null_mut();
    }
    job
}

#[cfg(windows)]
const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x0000_2000;
#[cfg(windows)]
const JOB_OBJECT_BASIC_LIMIT_INFORMATION_CLASS: i32 = 2;

#[cfg(windows)]
#[repr(C)]
#[derive(Default)]
struct JobObjectBasicLimitInformation {
    per_process_user_time_limit: i64,
    per_job_user_time_limit: i64,
    limit_flags: u32,
    minimum_working_set_size: usize,
    maximum_working_set_size: usize,
    active_process_limit: u32,
    affinity: usize,
    priority_class: u32,
    scheduling_class: u32,
}

#[cfg(windows)]
#[link(name = "kernel32")]
unsafe extern "system" {
    fn CreateJobObjectW(attrs: *mut core::ffi::c_void, name: *const u16) -> *mut core::ffi::c_void;
    fn SetInformationJobObject(
        job: *mut core::ffi::c_void,
        class: i32,
        info: *const core::ffi::c_void,
        length: u32,
    ) -> i32;
    fn AssignProcessToJobObject(job: *mut core::ffi::c_void, process: *mut core::ffi::c_void) -> i32;
    fn CloseHandle(handle: *mut core::ffi::c_void) -> i32;
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

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::engine_arguments;

    #[test]
    fn app_data_is_forwarded_and_omitted_when_absent() {
        let path = Path::new("C:/amix-app-data");
        let with_data = engine_arguments(Some(path));
        assert_eq!(with_data[0], "-m");
        assert_eq!(with_data[1], "amix.amix_engine.service");
        assert_eq!(with_data[2], "--app-data");
        assert_eq!(with_data[3], path.to_string_lossy());
        let without = engine_arguments(None);
        assert_eq!(without.len(), 2);
        assert!(!without.iter().any(|arg| arg == "--app-data"));
    }
}
