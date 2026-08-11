use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, Emitter};
use thiserror::Error;

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
    app: Mutex<Option<AppHandle>>,
}

impl BridgeSidecar {
    pub fn start() -> Result<Self, BridgeError> {
        let root = project_root();
        if !root.join("src").join("acars_bridge").is_dir() {
            return Err(BridgeError::Message(format!(
                "acars_bridge package not found under {}",
                root.display()
            )));
        }
        let sidecar = Self {
            inner: Mutex::new(None),
            root,
            app: Mutex::new(None),
        };
        sidecar.ensure_running()?;
        Ok(sidecar)
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
        *guard = Some(spawn_sidecar(&self.root)?);
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
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            if dir.join("src").join("acars_bridge").is_dir() {
                return dir.to_path_buf();
            }
            if let Some(parent) = dir.parent() {
                if parent.join("src").join("acars_bridge").is_dir() {
                    return parent.to_path_buf();
                }
            }
        }
    }
    manifest
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or(manifest)
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

fn python_candidates() -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Ok(custom) = std::env::var("ACARS_BRIDGE_PYTHON") {
        out.push(PathBuf::from(custom));
    }
    // Prefer project venv.
    let root = project_root();
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

fn spawn_sidecar(root: &Path) -> Result<SidecarInner, BridgeError> {
    let mut last_err = String::new();
    for py in python_candidates() {
        let mut cmd = Command::new(&py);
        cmd.args(["-m", "acars_bridge.bridge", "serve"])
            .current_dir(root)
            .env("PYTHONPATH", root.join("src"));
        configure_no_console(&mut cmd);
        match cmd.spawn() {
            Ok(mut child) => {
                let stdin = child.stdin.take().ok_or_else(|| {
                    BridgeError::Message("Python bridge stdin unavailable".into())
                })?;
                let stdout = child.stdout.take().ok_or_else(|| {
                    BridgeError::Message("Python bridge stdout unavailable".into())
                })?;
                let mut reader = BufReader::new(stdout);
                let mut ready = String::new();
                if let Err(err) = reader.read_line(&mut ready) {
                    let _ = child.kill();
                    last_err = format!("{}: failed ready handshake ({err})", py.display());
                    continue;
                }
                match serde_json::from_str::<Value>(ready.trim()) {
                    Ok(parsed) => match parse_bridge_response(&parsed) {
                        Ok(_) => {
                            return Ok(SidecarInner {
                                child,
                                stdin,
                                stdout: reader,
                            });
                        }
                        Err(err) => {
                            let _ = child.kill();
                            last_err = format!("{}: {err}", py.display());
                        }
                    },
                    Err(err) => {
                        let _ = child.kill();
                        last_err = format!("{}: invalid ready JSON ({err}): {}", py.display(), ready.trim());
                    }
                }
            }
            Err(err) => {
                last_err = format!("{}: {err}", py.display());
            }
        }
    }
    Err(BridgeError::Message(format!(
        "Could not launch Python bridge ({last_err}). Install Python 3.12+ or set ACARS_BRIDGE_PYTHON."
    )))
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
