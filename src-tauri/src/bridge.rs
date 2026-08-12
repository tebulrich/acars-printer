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
}

impl BridgeSidecar {
    pub fn start() -> Result<Self, BridgeError> {
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

        let sidecar = Self {
            inner: Mutex::new(None),
            root,
            log_path: log_path.clone(),
            app: Mutex::new(None),
        };
        match sidecar.ensure_running() {
            Ok(()) => {
                startup_log(&log_path, "bridge ready");
                Ok(sidecar)
            }
            Err(err) => {
                startup_log(&log_path, &format!("bridge start FAILED: {err}"));
                show_fatal(
                    "ACARS Print Bridge",
                    &format!(
                        "{err}\n\nA log was written next to the app:\n{}",
                        log_path.display()
                    ),
                );
                Err(err)
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
        Ok(())
    }

    pub fn request(&self, command: &str, args: Value) -> Result<Value, BridgeError> {
        self.ensure_running()?;
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

fn bundled_sidecar_candidates() -> Vec<PathBuf> {
    let mut out = Vec::new();
    let Some(dir) = exe_directory() else {
        return out;
    };
    out.push(dir.join("acars-bridge.exe"));
    out.push(dir.join("acars-bridge"));
    // Dev / odd layouts may keep the target-triple suffix.
    #[cfg(windows)]
    {
        out.push(dir.join("acars-bridge-x86_64-pc-windows-msvc.exe"));
    }
    // Tauri sometimes places resources one level up from a nested install folder.
    if let Some(parent) = dir.parent() {
        out.push(parent.join("acars-bridge.exe"));
    }
    out
}

fn python_candidates(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Ok(custom) = std::env::var("ACARS_BRIDGE_PYTHON") {
        out.push(PathBuf::from(custom));
    }
    #[cfg(windows)]
    {
        out.push(root.join(".venv").join("Scripts").join("python.exe"));
        out.push(root.join(".venv").join("Scripts").join("pythonw.exe"));
        out.push(PathBuf::from("python.exe"));
        out.push(PathBuf::from("pythonw.exe"));
    }
    #[cfg(not(windows))]
    {
        out.push(root.join(".venv").join("bin").join("python"));
        out.push(PathBuf::from("python3"));
        out.push(PathBuf::from("python"));
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

    for path in bundled_sidecar_candidates() {
        if !path.is_file() {
            continue;
        }
        startup_log(log_path, &format!("trying bundled sidecar {}", path.display()));
        match spawn_process(&path, &[], root, log_path, /*bundled*/ true) {
            Ok(inner) => return Ok(inner),
            Err(err) => {
                last_err = err;
                startup_log(log_path, &format!("bundled sidecar failed: {last_err}"));
            }
        }
    }

    let has_source = root.join("src").join("acars_bridge").is_dir();
    if has_source {
        for py in python_candidates(root) {
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
    } else {
        startup_log(
            log_path,
            &format!(
                "no source tree at {} — release builds need acars-bridge.exe next to the app",
                root.display()
            ),
        );
    }

    Err(BridgeError::Message(format!(
        "Could not start the ACARS bridge ({last_err}). \
Reinstall from GitHub Releases, or keep acars-bridge.exe next to ACARS-Print-Bridge.exe. \
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
    // Shared support log next to the desktop EXE (same folder as the sidecar).
    cmd.env("ACARS_BRIDGE_EXE_LOG", log_path);
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
