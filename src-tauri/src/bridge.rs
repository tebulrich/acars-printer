use serde_json::{json, Value};
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter};
use thiserror::Error;

#[cfg(windows)]
use std::os::windows::ffi::OsStrExt;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Debug, Error)]
pub enum BridgeError {
    #[error("{0}")]
    Message(String),
}

impl serde::Serialize for BridgeError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(&self.to_string())
    }
}

struct SidecarInner {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

pub struct BridgeSidecar {
    inner: Mutex<Option<SidecarInner>>,
    root: PathBuf,
    log_path: PathBuf,
    app: Mutex<Option<AppHandle>>,
    start_error: Mutex<Option<String>>,
}

impl BridgeSidecar {
    /// Construct without starting the child. Call ``manage()`` first, then
    /// ``bootstrap()`` so Tauri state is never missing.
    pub fn create() -> Self {
        let exe_dir = exe_directory();
        let log_path = exe_dir
            .as_ref()
            .map(|d| d.join("acars-print-bridge.log"))
            .unwrap_or_else(|| PathBuf::from("acars-print-bridge.log"));
        startup_log(
            &log_path,
            &format!(
                "launch exe_dir={} cwd={}",
                exe_dir
                    .as_ref()
                    .map(|p| p.display().to_string())
                    .unwrap_or_else(|| "(unknown)".into()),
                std::env::current_dir()
                    .map(|p| p.display().to_string())
                    .unwrap_or_else(|_| "(unknown)".into())
            ),
        );
        let root = project_root();
        startup_log(&log_path, &format!("project_root={}", root.display()));
        Self {
            inner: Mutex::new(None),
            root,
            log_path,
            app: Mutex::new(None),
            start_error: Mutex::new(None),
        }
    }

    pub fn log_path(&self) -> &Path {
        &self.log_path
    }

    /// Start the embedded bridge after Tauri has managed this state.
    pub fn bootstrap(&self) {
        preempt_orphan_bridges(&self.log_path);
        match self.ensure_running() {
            Ok(()) => {
                startup_log(&self.log_path, "bridge ready");
            }
            Err(err) => {
                let msg = err.to_string();
                startup_log(&self.log_path, &format!("bridge start FAILED: {msg}"));
                if let Ok(mut guard) = self.start_error.lock() {
                    *guard = Some(msg);
                }
            }
        }
    }

    pub fn set_app(&self, app: AppHandle) {
        if let Ok(mut guard) = self.app.lock() {
            *guard = Some(app);
        }
    }

    fn ensure_running(&self) -> Result<(), BridgeError> {
        let mut guard = self
            .inner
            .lock()
            .map_err(|_| BridgeError::Message("Bridge lock poisoned".into()))?;
        if let Some(inner) = guard.as_mut() {
            match inner.child.try_wait() {
                Ok(None) => return Ok(()),
                Ok(Some(_)) | Err(_) => {
                    *guard = None;
                }
            }
        }
        *guard = Some(spawn_sidecar(&self.root, &self.log_path)?);
        if let Ok(mut err) = self.start_error.lock() {
            *err = None;
        }
        Ok(())
    }

    pub fn request(&self, command: &str, args: Value) -> Result<Value, BridgeError> {
        if let Err(err) = self.ensure_running() {
            if let Ok(mut stored) = self.start_error.lock() {
                *stored = Some(err.to_string());
            }
            return Err(err);
        }
        let mut guard = self
            .inner
            .lock()
            .map_err(|_| BridgeError::Message("Bridge lock poisoned".into()))?;
        let inner = guard
            .as_mut()
            .ok_or_else(|| BridgeError::Message("Bridge sidecar is not running".into()))?;

        let payload = json!({
            "command": command,
            "args": args,
        });
        let line = format!("{payload}\n");
        if let Err(err) = inner
            .stdin
            .write_all(line.as_bytes())
            .and_then(|_| inner.stdin.flush())
        {
            *guard = None;
            return Err(BridgeError::Message(format!(
                "Failed to talk to Python bridge: {err}"
            )));
        }

        loop {
            let mut response = String::new();
            match inner.stdout.read_line(&mut response) {
                Ok(0) => {
                    *guard = None;
                    return Err(BridgeError::Message(
                        "Python bridge closed unexpectedly.".into(),
                    ));
                }
                Ok(_) => {}
                Err(err) => {
                    *guard = None;
                    return Err(BridgeError::Message(format!(
                        "Failed to read Python bridge response: {err}"
                    )));
                }
            }

            let trimmed = response.trim();
            if trimmed.is_empty() {
                continue;
            }
            // Library chatter (e.g. python-escpos print()) must not kill the RPC.
            let parsed: Value = match serde_json::from_str(trimmed) {
                Ok(value) => value,
                Err(_) => {
                    eprintln!("bridge: ignoring non-JSON stdout: {trimmed}");
                    continue;
                }
            };
            if parsed.get("event").is_some() {
                self.emit_bridge_event(&parsed);
                continue;
            }
            return parse_bridge_response(&parsed);
        }
    }

    fn emit_bridge_event(&self, parsed: &Value) {
        let Ok(guard) = self.app.lock() else {
            return;
        };
        let Some(app) = guard.as_ref() else {
            return;
        };
        let event = parsed
            .get("event")
            .and_then(|v| v.as_str())
            .unwrap_or("bridge");
        let data = parsed.get("data").cloned().unwrap_or(Value::Null);
        let _ = app.emit(&format!("bridge://{event}"), data);
    }
}

impl Drop for BridgeSidecar {
    fn drop(&mut self) {
        if let Ok(mut guard) = self.inner.lock() {
            if let Some(mut inner) = guard.take() {
                let _ = writeln!(inner.stdin, "quit");
                let _ = inner.stdin.flush();
                let _ = inner.child.kill();
                let _ = inner.child.wait();
            }
        }
    }
}

fn exe_directory() -> Option<PathBuf> {
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
}

fn project_root() -> PathBuf {
    if let Ok(root) = std::env::var("ACARS_BRIDGE_ROOT") {
        return PathBuf::from(root);
    }
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    if let Some(parent) = manifest.parent() {
        if parent.join("src").join("acars_bridge").is_dir() {
            return parent.to_path_buf();
        }
    }
    if let Some(dir) = exe_directory() {
        if dir.join("src").join("acars_bridge").is_dir() {
            return dir;
        }
        if let Some(parent) = dir.parent() {
            if parent.join("src").join("acars_bridge").is_dir() {
                return parent.to_path_buf();
            }
        }
    }
    manifest
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or(manifest)
}

/// Unpack the frozen bridge from inside this EXE into LocalAppData (not next to
/// the download). End users never see a second app.
fn ensure_embedded_sidecar(log_path: &Path) -> Result<Option<PathBuf>, BridgeError> {
    #[cfg(not(has_embedded_sidecar))]
    {
        let _ = log_path;
        return Ok(None);
    }

    #[cfg(has_embedded_sidecar)]
    {
        const BYTES: &[u8] = include_bytes!("../embedded/acars-bridge.exe");
        let version = env!("CARGO_PKG_VERSION");
        let base = std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .ok_or_else(|| {
                BridgeError::Message("LOCALAPPDATA is not set; cannot extract bridge".into())
            })?;
        let dir = base
            .join("acars-bridge")
            .join("sidecar")
            .join(version);
        let dest = dir.join("acars-bridge.exe");
        let need_write = match std::fs::metadata(&dest) {
            Ok(meta) => meta.len() as usize != BYTES.len(),
            Err(_) => true,
        };
        if need_write {
            startup_log(
                log_path,
                &format!("extracting embedded bridge to {}", dest.display()),
            );
            std::fs::create_dir_all(&dir).map_err(|err| {
                BridgeError::Message(format!(
                    "Could not create {} ({err})",
                    dir.display()
                ))
            })?;
            let tmp = dir.join("acars-bridge.exe.partial");
            std::fs::write(&tmp, BYTES).map_err(|err| {
                BridgeError::Message(format!(
                    "Could not write {} ({err})",
                    tmp.display()
                ))
            })?;
            std::fs::rename(&tmp, &dest).map_err(|err| {
                BridgeError::Message(format!(
                    "Could not finalize {} ({err})",
                    dest.display()
                ))
            })?;
        } else {
            startup_log(
                log_path,
                &format!("using extracted bridge {}", dest.display()),
            );
        }
        Ok(Some(dest))
    }
}

#[cfg(not(has_embedded_sidecar))]
fn python_candidates(root: &Path) -> Vec<PathBuf> {
    // Dev only: never use bare PATH python/pythonw (system installs break easily).
    let mut out = Vec::new();
    if let Ok(custom) = std::env::var("ACARS_BRIDGE_PYTHON") {
        out.push(PathBuf::from(custom));
    }
    #[cfg(windows)]
    {
        out.push(root.join(".venv").join("Scripts").join("python.exe"));
        out.push(root.join(".venv").join("Scripts").join("pythonw.exe"));
    }
    #[cfg(not(windows))]
    {
        out.push(root.join(".venv").join("bin").join("python"));
    }
    out
}

fn configure_no_console(cmd: &mut Command) {
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
}

fn spawn_sidecar(root: &Path, log_path: &Path) -> Result<SidecarInner, BridgeError> {
    let mut last_err = String::new();

    match ensure_embedded_sidecar(log_path) {
        Ok(Some(path)) => {
            startup_log(
                log_path,
                &format!("trying embedded bridge {}", path.display()),
            );
            match spawn_process(&path, &[], root, log_path, /*bundled*/ true) {
                Ok(inner) => return Ok(inner),
                Err(err) => {
                    last_err = err;
                    startup_log(log_path, &format!("embedded bridge failed: {last_err}"));
                    #[cfg(has_embedded_sidecar)]
                    {
                        // Packaged builds must not fall back to a random Python on PATH
                        // (especially when dist/ sits next to the source tree).
                        return Err(BridgeError::Message(format!(
                            "Could not start the embedded ACARS bridge ({last_err}). \
Reinstall from GitHub Releases. See acars-print-bridge.log next to the app."
                        )));
                    }
                }
            }
        }
        Ok(None) => {
            startup_log(log_path, "no embedded bridge in this build (dev mode)");
        }
        Err(err) => {
            startup_log(log_path, &format!("embedded extract failed: {err}"));
            #[cfg(has_embedded_sidecar)]
            {
                return Err(err);
            }
            #[cfg(not(has_embedded_sidecar))]
            {
                last_err = err.to_string();
            }
        }
    }

    #[cfg(not(has_embedded_sidecar))]
    {
        let has_source = root.join("src").join("acars_bridge").is_dir();
        if has_source {
            for py in python_candidates(root) {
                if !py.is_file() {
                    continue;
                }
                startup_log(log_path, &format!("trying python {}", py.display()));
                match spawn_process(
                    &py,
                    &["-m", "acars_bridge.bridge", "serve"],
                    root,
                    log_path,
                    /*bundled*/ false,
                ) {
                    Ok(inner) => return Ok(inner),
                    Err(err) => {
                        last_err = err;
                        startup_log(log_path, &format!("python launch failed: {last_err}"));
                    }
                }
            }
        } else if last_err.is_empty() {
            last_err = "no embedded bridge and no project source tree".into();
        }
    }

    Err(BridgeError::Message(format!(
        "Could not start the ACARS bridge ({last_err}). \
See acars-print-bridge.log next to the app."
    )))
}

fn spawn_process(
    program: &Path,
    args: &[&str],
    root: &Path,
    log_path: &Path,
    bundled: bool,
) -> Result<SidecarInner, String> {
    let mut cmd = Command::new(program);
    cmd.args(args);
    if !bundled {
        cmd.current_dir(root)
            .env("PYTHONPATH", root.join("src"));
    }
    // Shared support log next to the desktop EXE.
    cmd.env("ACARS_BRIDGE_EXE_LOG", log_path);
    if let Ok(shell) = std::env::current_exe() {
        cmd.env("ACARS_BRIDGE_SHELL_EXE", &shell);
    }
    cmd.env("ACARS_BRIDGE_SHELL_PID", std::process::id().to_string());
    configure_no_console(&mut cmd);
    let mut child = cmd
        .spawn()
        .map_err(|err| format!("{}: {err}", program.display()))?;
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| format!("{}: stdin unavailable", program.display()))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| format!("{}: stdout unavailable", program.display()))?;
    let mut stderr = child.stderr.take();
    let mut reader = BufReader::new(stdout);
    let mut ready = String::new();
    if let Err(err) = reader.read_line(&mut ready) {
        let _ = child.kill();
        let err_tail = read_stderr_tail(&mut stderr);
        return Err(format!(
            "{}: failed ready handshake ({err}){err_tail}",
            program.display()
        ));
    }
    match serde_json::from_str::<Value>(ready.trim()) {
        Ok(parsed) => match parse_bridge_response(&parsed) {
            Ok(_) => Ok(SidecarInner {
                child,
                stdin,
                stdout: reader,
            }),
            Err(err) => {
                let _ = child.kill();
                let err_tail = read_stderr_tail(&mut stderr);
                Err(format!("{err}{err_tail}"))
            }
        },
        Err(err) => {
            let _ = child.kill();
            let err_tail = read_stderr_tail(&mut stderr);
            Err(format!(
                "{}: invalid ready JSON ({err}): {}{err_tail}",
                program.display(),
                ready.trim()
            ))
        }
    }
}

fn read_stderr_tail(stderr: &mut Option<std::process::ChildStderr>) -> String {
    let Some(err) = stderr.take() else {
        return String::new();
    };
    let mut reader = BufReader::new(err);
    let mut buf = String::new();
    for _ in 0..20 {
        let mut line = String::new();
        match reader.read_line(&mut line) {
            Ok(0) => break,
            Ok(_) => buf.push_str(&line),
            Err(_) => break,
        }
    }
    let trimmed = buf.trim();
    if trimmed.is_empty() {
        String::new()
    } else {
        format!(" | stderr: {trimmed}")
    }
}

fn parse_bridge_response(parsed: &Value) -> Result<Value, BridgeError> {
    let ok = parsed.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
    if ok {
        Ok(parsed.get("data").cloned().unwrap_or(Value::Null))
    } else {
        let msg = parsed
            .get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("Bridge command failed");
        Err(BridgeError::Message(msg.to_string()))
    }
}

fn startup_log(path: &Path, message: &str) {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let line = format!("[{stamp}] {message}\n");
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = file.write_all(line.as_bytes());
        let _ = file.flush();
    }
}

fn preempt_orphan_bridges(log_path: &Path) {
    // Previous shells may die without killing the embedded child; that leaves
    // acars-bridge.exe (+ app.lock) around and breaks the next launch.
    #[cfg(windows)]
    {
        startup_log(log_path, "preempt: stopping leftover acars-bridge.exe if any");
        let mut cmd = Command::new("taskkill");
        cmd.args(["/F", "/IM", "acars-bridge.exe", "/T"]);
        configure_no_console_output(&mut cmd);
        let _ = cmd.output();
        if let Some(local) = std::env::var_os("LOCALAPPDATA") {
            let lock = PathBuf::from(local)
                .join("acars-bridge")
                .join("acars-bridge")
                .join("app.lock");
            if lock.is_file() {
                let _ = std::fs::remove_file(&lock);
                startup_log(log_path, &format!("preempt: removed {}", lock.display()));
            }
        }
    }
    #[cfg(not(windows))]
    {
        let _ = log_path;
    }
}

fn configure_no_console_output(cmd: &mut Command) {
    cmd.stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
}

/// One desktop shell at a time (file + PID). Returns Err if another live shell holds it.
pub fn acquire_shell_lock(log_path: &Path) -> Result<(), String> {
    let Some(local) = std::env::var_os("LOCALAPPDATA") else {
        return Ok(());
    };
    let dir = PathBuf::from(local).join("acars-bridge").join("acars-bridge");
    let _ = std::fs::create_dir_all(&dir);
    let path = dir.join("shell.lock");
    let me = std::process::id();
    if path.is_file() {
        if let Ok(raw) = std::fs::read_to_string(&path) {
            if let Ok(pid) = raw.trim().parse::<u32>() {
                if pid != me && windows_pid_alive(pid) {
                    let msg = format!(
                        "ACARS Print Bridge is already running (PID {pid}). Quit the other copy from the tray first."
                    );
                    startup_log(log_path, &msg);
                    show_fatal("ACARS Print Bridge", &msg);
                    return Err(msg);
                }
            }
        }
        let _ = std::fs::remove_file(&path);
    }
    if let Err(err) = std::fs::write(&path, format!("{me}\n")) {
        startup_log(
            log_path,
            &format!("shell.lock write failed ({err}); continuing"),
        );
    } else {
        startup_log(log_path, &format!("shell.lock acquired pid={me}"));
    }
    Ok(())
}

fn windows_pid_alive(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }
    #[cfg(windows)]
    {
        let mut cmd = Command::new("tasklist");
        cmd.args(["/FI", &format!("PID eq {pid}"), "/NH"])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        cmd.creation_flags(CREATE_NO_WINDOW);
        match cmd.output() {
            Ok(out) => {
                let text = String::from_utf8_lossy(&out.stdout).to_lowercase();
                text.contains(&pid.to_string()) && !text.contains("no tasks")
            }
            Err(_) => false,
        }
    }
    #[cfg(not(windows))]
    {
        let _ = pid;
        false
    }
}

fn show_fatal(title: &str, message: &str) {
    #[cfg(windows)]
    {
        fn wide(s: &str) -> Vec<u16> {
            std::ffi::OsStr::new(s)
                .encode_wide()
                .chain(std::iter::once(0))
                .collect()
        }
        #[link(name = "user32")]
        extern "system" {
            fn MessageBoxW(
                hwnd: *mut core::ffi::c_void,
                text: *const u16,
                caption: *const u16,
                flags: u32,
            ) -> i32;
        }
        const MB_ICONERROR: u32 = 0x0000_0010;
        let text = wide(message);
        let caption = wide(title);
        unsafe {
            MessageBoxW(
                std::ptr::null_mut(),
                text.as_ptr(),
                caption.as_ptr(),
                MB_ICONERROR,
            );
        }
    }
    #[cfg(not(windows))]
    {
        eprintln!("{title}: {message}");
    }
}
