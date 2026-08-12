mod bridge;

use bridge::{acquire_shell_lock, BridgeError, BridgeSidecar};
use serde_json::{json, Value};
use std::sync::Arc;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager,
};

#[tauri::command]
async fn bridge_command(
    state: tauri::State<'_, Arc<BridgeSidecar>>,
    command: String,
    args: Option<Value>,
) -> Result<Value, BridgeError> {
    let sidecar = Arc::clone(&state);
    let args = args.unwrap_or_else(json_object);
    tauri::async_runtime::spawn_blocking(move || sidecar.request(&command, args))
        .await
        .map_err(|err| BridgeError::Message(format!("Bridge task failed: {err}")))?
}

/// Relaunch this EXE elevated (UAC). Used when Connect needs Admin but the
/// process is still unelevated (e.g. `tauri dev`). Release builds request
/// Admin via the embedded Windows manifest on every launch.
#[tauri::command]
fn relaunch_elevated(app: AppHandle) -> Result<(), String> {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        use std::process::Command;

        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let exe = std::env::current_exe().map_err(|err| err.to_string())?;
        let exe_arg = exe.to_string_lossy().replace('\'', "''");
        let status = Command::new("powershell.exe")
            .args([
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                &format!("Start-Process -FilePath '{exe_arg}' -Verb RunAs"),
            ])
            .creation_flags(CREATE_NO_WINDOW)
            .status()
            .map_err(|err| err.to_string())?;
        if !status.success() {
            return Err("Administrator approval was cancelled.".into());
        }
        // Quit the unelevated instance; the elevated one is starting.
        app.exit(0);
        Ok(())
    }
    #[cfg(not(windows))]
    {
        let _ = app;
        Err("Elevation is only supported on Windows.".into())
    }
}

/// Stop the Python bridge sidecar and exit the whole process (tray included).
#[tauri::command]
fn quit_app(app: AppHandle, state: tauri::State<'_, Arc<BridgeSidecar>>) -> Result<(), String> {
    let sidecar = Arc::clone(&state);
    let _ = sidecar.request("quit", json_object());
    app.exit(0);
    Ok(())
}

fn json_object() -> Value {
    Value::Object(serde_json::Map::new())
}

fn tray_action(app: &tauri::AppHandle, command: &str, args: Value) {
    if let Some(sidecar) = app.try_state::<Arc<BridgeSidecar>>() {
        let sidecar = Arc::clone(&sidecar);
        let command = command.to_string();
        let _ = tauri::async_runtime::spawn_blocking(move || sidecar.request(&command, args));
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            // Manage state FIRST so invoke never sees "state not managed".
            let sidecar = BridgeSidecar::create();
            sidecar.set_app(app.handle().clone());
            let log_path = sidecar.log_path().to_path_buf();
            let sidecar = Arc::new(sidecar);
            app.manage(Arc::clone(&sidecar));

            if let Err(_err) = acquire_shell_lock(&log_path) {
                // Message already shown; exit without a broken UI session.
                app.handle().exit(0);
                return Ok(());
            }
            sidecar.bootstrap();

            let show = MenuItem::with_id(app, "show", "Show window", true, None::<&str>)?;
            let reprint =
                MenuItem::with_id(app, "reprint_last", "Reprint last", true, None::<&str>)?;
            let toggle =
                MenuItem::with_id(app, "toggle_auto_print", "Toggle auto-print", true, None::<&str>)?;
            let test = MenuItem::with_id(app, "test_print", "Test print", true, None::<&str>)?;
            let feed = MenuItem::with_id(app, "feed", "Feed", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &reprint, &toggle, &test, &feed, &quit])?;

            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .tooltip("ACARS Print Bridge")
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "reprint_last" => tray_action(app, "hotkey", json!({"action": "reprint_last"})),
                    "toggle_auto_print" => {
                        tray_action(app, "hotkey", json!({"action": "toggle_auto_print"}))
                    }
                    "test_print" => tray_action(app, "hotkey", json!({"action": "test_print"})),
                    "feed" => tray_action(app, "hotkey", json!({"action": "feed"})),
                    "quit" => {
                        tray_action(app, "quit", json!({}));
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            bridge_command,
            relaunch_elevated,
            quit_app
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
