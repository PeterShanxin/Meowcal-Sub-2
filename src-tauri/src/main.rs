#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

use reqwest::blocking::Client;
use serde::Serialize;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Listener, LogicalPosition, LogicalSize, Manager,
    PhysicalPosition, PhysicalSize, State,
};
use tokio::time::sleep;
use url::Url;
use windows::Win32::Foundation::POINT;
use windows::Win32::UI::WindowsAndMessaging::GetCursorPos;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

const CREATE_NO_WINDOW: u32 = 0x08000000;

#[derive(Clone)]
struct BackendProcess(Arc<Mutex<Option<Child>>>);

#[derive(Serialize, Clone, Copy)]
#[serde(rename_all = "camelCase")]
struct CaptureRegionPayload {
    x: i32,
    y: i32,
    width: i32,
    height: i32,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct HudRegionPayload {
    left: i32,
    top: i32,
    width: i32,
    height: i32,
    frame_left: i32,
    frame_top: i32,
    top_margin: i32,
    bottom_margin: i32,
    subtitle_position: &'static str,
}

#[derive(Serialize, Clone, Copy)]
#[serde(rename_all = "camelCase")]
struct HoverStatePayload {
    hovering: bool,
}

#[derive(Clone, Copy)]
struct CaptureRegionState {
    x: i32,
    y: i32,
    width: i32,
    height: i32,
    device_scale_factor: f64,
}

#[derive(Clone, Copy)]
struct MainWindowBounds {
    position: PhysicalPosition<i32>,
    size: PhysicalSize<u32>,
    maximized: bool,
}

#[derive(Clone)]
struct ShellState {
    capture_region: Arc<Mutex<Option<CaptureRegionState>>>,
    hud_enabled: Arc<AtomicBool>,
    hud_hovering: Arc<AtomicBool>,
    prev_main_bounds: Arc<Mutex<Option<MainWindowBounds>>>,
}

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("repo root")
        .to_path_buf()
}

fn python_executable() -> PathBuf {
    if let Ok(path) = std::env::var("MEOWCAL_PYTHON") {
        let candidate = PathBuf::from(path);
        if candidate.exists() {
            return candidate;
        }
    }
    repo_root().join(".venv").join("Scripts").join("python.exe")
}

fn config_path() -> PathBuf {
    let appdata = std::env::var("APPDATA").unwrap_or_else(|_| String::from("."));
    PathBuf::from(appdata).join("meowcal-sub-2").join("config.toml")
}

fn event_log_path() -> PathBuf {
    if let Ok(path) = std::env::var("MEOCOSUB2_EVENT_LOG_PATH") {
        return PathBuf::from(path);
    }
    let appdata = std::env::var("APPDATA").unwrap_or_else(|_| String::from("."));
    PathBuf::from(appdata)
        .join("meowcal-sub-2")
        .join("logs")
        .join("meowcal-sub-2.events.jsonl")
}

fn log_shell_event(event: &str, fields: serde_json::Value) {
    let ts_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();
    let mut record = serde_json::Map::new();
    record.insert("ts_ms".to_string(), serde_json::json!(ts_ms));
    record.insert("layer".to_string(), serde_json::json!("tauri"));
    record.insert("level".to_string(), serde_json::json!("info"));
    record.insert("event".to_string(), serde_json::json!(event));
    if let serde_json::Value::Object(extra) = fields {
        for (key, value) in extra {
            record.insert(key, value);
        }
    }
    let path = event_log_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(mut file) = fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{}", serde_json::Value::Object(record));
    }
}

fn overlay_port() -> u16 {
    let Ok(raw) = fs::read_to_string(config_path()) else {
        return 8765;
    };
    let Ok(value) = raw.parse::<toml::Value>() else {
        return 8765;
    };
    value
        .get("overlay")
        .and_then(|overlay| overlay.get("port"))
        .and_then(|port| port.as_integer())
        .and_then(|port| u16::try_from(port).ok())
        .unwrap_or(8765)
}

fn api_base() -> String {
    format!("http://127.0.0.1:{}", overlay_port())
}

fn backend_ready() -> bool {
    let api_base = api_base();
    Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .ok()
        .and_then(|client| client.get(format!("{api_base}/api/state")).send().ok())
        .map(|response| response.status().is_success())
        .unwrap_or(false)
}

fn spawn_backend(process: &BackendProcess) {
    let python = python_executable();
    log_shell_event(
        "backend.spawn.requested",
        serde_json::json!({
            "python": python.display().to_string(),
            "using_repo_venv": python.exists(),
        }),
    );
    let mut command = if python.exists() {
        let mut command = Command::new(python);
        command.current_dir(repo_root());
        command.args(["-m", "meocosub2.cli", "serve"]);
        command
    } else {
        let mut command = Command::new("python");
        command.current_dir(repo_root());
        command.args(["-m", "meocosub2.cli", "serve"]);
        command
    };

    #[cfg(target_os = "windows")]
    {
        command.creation_flags(CREATE_NO_WINDOW);
    }

    match command.spawn() {
        Ok(child) => {
            let pid = child.id();
            log_shell_event("backend.spawn.started", serde_json::json!({ "pid": pid }));
            *process.0.lock().expect("backend process lock") = Some(child);
        }
        Err(error) => {
            log_shell_event(
                "backend.spawn.failed",
                serde_json::json!({ "error": error.to_string() }),
            );
        }
    }
}

fn wait_for_backend(timeout: Duration) -> bool {
    let start = std::time::Instant::now();
    while start.elapsed() < timeout {
        if backend_ready() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(400));
    }
    false
}

fn post_json(path: &str, body: serde_json::Value) -> Result<(), String> {
    let api_base = api_base();
    let client = Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .map_err(|error| error.to_string())?;
    let response = client
        .post(format!("{api_base}{path}"))
        .json(&body)
        .send()
        .map_err(|error| error.to_string())?;
    if response.status().is_success() {
        Ok(())
    } else {
        Err(format!("Backend request failed: {}", response.status()))
    }
}

fn fetch_capture_region_from_backend() -> Option<CaptureRegionState> {
    let api_base = api_base();
    let client = Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .ok()?;
    let payload: serde_json::Value = client
        .get(format!("{api_base}/api/config"))
        .send()
        .ok()?
        .error_for_status()
        .ok()?
        .json()
        .ok()?;

    let region = payload.get("capture")?.get("region")?.as_array()?;
    if region.len() != 4 {
        return None;
    }
    let x = region[0].as_i64()? as i32;
    let y = region[1].as_i64()? as i32;
    let width = region[2].as_i64()? as i32;
    let height = region[3].as_i64()? as i32;
    if width <= 0 || height <= 0 {
        return None;
    }
    Some(CaptureRegionState {
        x,
        y,
        width,
        height,
        device_scale_factor: 1.0,
    })
}

fn current_cursor_position() -> Option<(i32, i32)> {
    unsafe {
        let mut point = POINT::default();
        if GetCursorPos(&mut point).is_ok() {
            Some((point.x, point.y))
        } else {
            None
        }
    }
}

fn compute_hud_region(region: CaptureRegionState) -> HudRegionPayload {
    let left_margin = 18;
    let right_margin = 18;
    let top_margin = if region.y >= 150 { 150 } else { 48 };
    let bottom_margin = 122;
    HudRegionPayload {
        left: region.x - left_margin,
        top: region.y - top_margin,
        width: region.width + left_margin + right_margin,
        height: region.height + top_margin + bottom_margin,
        frame_left: left_margin,
        frame_top: top_margin,
        top_margin,
        bottom_margin,
        subtitle_position: if top_margin >= 110 { "above" } else { "below" },
    }
}

fn main_window(app: &AppHandle) -> Result<tauri::WebviewWindow, String> {
    app.get_webview_window("main")
        .ok_or_else(|| "Main window not found".to_string())
}

fn hide_window_to_tray(window: &tauri::WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|error| error.to_string())
}

fn configure_capture_hud(app: &AppHandle, shell: &ShellState) -> Result<(), String> {
    let region = *shell.capture_region.lock().map_err(|_| "capture region lock poisoned")?;
    let window = app
        .get_webview_window("capture-hud")
        .ok_or("Capture HUD window not found")?;
    if let Some(region) = region {
        let hud = compute_hud_region(region);
        window
            .set_position(LogicalPosition::new(hud.left as f64, hud.top as f64))
            .map_err(|error| error.to_string())?;
        window
            .set_size(LogicalSize::new(hud.width as f64, hud.height as f64))
            .map_err(|error| error.to_string())?;
        app.emit_to("capture-hud", "capture-hud-region", hud)
            .map_err(|error| error.to_string())?;
        if shell.hud_enabled.load(Ordering::SeqCst) {
            window.show().map_err(|error| error.to_string())?;
            window
                .set_ignore_cursor_events(!shell.hud_hovering.load(Ordering::SeqCst))
                .map_err(|error| error.to_string())?;
        } else {
            window.hide().map_err(|error| error.to_string())?;
        }
    } else {
        window.hide().map_err(|error| error.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn open_area_selector(app: AppHandle) -> Result<(), String> {
    log_shell_event("selector.open.requested", serde_json::json!({}));
    let window = app
        .get_webview_window("selector")
        .ok_or("Selector window not found")?;
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn close_area_selector(app: AppHandle) -> Result<(), String> {
    log_shell_event("selector.close.requested", serde_json::json!({}));
    let window = app
        .get_webview_window("selector")
        .ok_or("Selector window not found")?;
    window.hide().map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn hide_main_window(app: AppHandle) -> Result<(), String> {
    log_shell_event("window.main.hide_requested", serde_json::json!({}));
    let window = main_window(&app)?;
    hide_window_to_tray(&window)
}

#[tauri::command]
fn show_main_window(app: AppHandle) -> Result<(), String> {
    log_shell_event("window.main.show_requested", serde_json::json!({}));
    show_main(&app);
    Ok(())
}

#[tauri::command]
fn enter_live_mode(app: AppHandle, shell: State<'_, ShellState>) -> Result<(), String> {
    log_shell_event("window.live.enter_requested", serde_json::json!({}));
    let window = main_window(&app)?;
    let maximized = window.is_maximized().map_err(|e| e.to_string())?;
    if maximized {
        window.unmaximize().map_err(|e| e.to_string())?;
    }
    let current_pos = window
        .outer_position()
        .map_err(|e| e.to_string())?;
    let current_size = window.outer_size().map_err(|e| e.to_string())?;
    *shell
        .prev_main_bounds
        .lock()
        .map_err(|_| "prev bounds lock poisoned")? = Some(MainWindowBounds {
        position: current_pos,
        size: current_size,
        maximized,
    });

    let monitor = window
        .current_monitor()
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "no monitor".to_string())?;
    let monitor_size = monitor.size();
    let monitor_pos = monitor.position();
    let scale = monitor.scale_factor();
    let strip_height = ((220.0_f64) * scale).round() as u32;
    let strip_height = strip_height.min(monitor_size.height);

    window.set_decorations(false).map_err(|e| e.to_string())?;
    window.set_always_on_top(true).map_err(|e| e.to_string())?;
    window.set_resizable(false).map_err(|e| e.to_string())?;
    window
        .set_size(PhysicalSize {
            width: monitor_size.width,
            height: strip_height,
        })
        .map_err(|e| e.to_string())?;
    window
        .set_position(PhysicalPosition {
            x: monitor_pos.x,
            y: monitor_pos.y + (monitor_size.height as i32) - (strip_height as i32),
        })
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn exit_live_mode(app: AppHandle, shell: State<'_, ShellState>) -> Result<(), String> {
    log_shell_event("window.live.exit_requested", serde_json::json!({}));
    let window = main_window(&app)?;
    window.set_always_on_top(false).map_err(|e| e.to_string())?;
    window.set_decorations(true).map_err(|e| e.to_string())?;
    window.set_resizable(true).map_err(|e| e.to_string())?;

    let restore = shell
        .prev_main_bounds
        .lock()
        .map_err(|_| "prev bounds lock poisoned")?
        .take();
    if let Some(bounds) = restore {
        window
            .set_size(bounds.size)
            .map_err(|e| e.to_string())?;
        window
            .set_position(bounds.position)
            .map_err(|e| e.to_string())?;
        if bounds.maximized {
            window.maximize().map_err(|e| e.to_string())?;
        }
    }
    // No prev bounds = app was never in live mode. Leave window where the
    // user put it; do not re-center on every phase transition.
    Ok(())
}

#[tauri::command]
fn show_capture_hud(app: AppHandle, shell: State<'_, ShellState>) -> Result<(), String> {
    log_shell_event("capture_hud.show_requested", serde_json::json!({}));
    if shell
        .capture_region
        .lock()
        .map_err(|_| "capture region lock poisoned")?
        .is_none()
    {
        *shell
            .capture_region
            .lock()
            .map_err(|_| "capture region lock poisoned")? = fetch_capture_region_from_backend();
    }
    shell.hud_enabled.store(true, Ordering::SeqCst);
    shell.hud_hovering.store(false, Ordering::SeqCst);
    configure_capture_hud(&app, &shell)?;
    app.emit_to("capture-hud", "capture-hud-pulse", serde_json::json!({}))
        .map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn get_api_base() -> String {
    api_base()
}

#[tauri::command]
fn stop_translation(app: AppHandle, shell: State<'_, ShellState>) -> Result<(), String> {
    log_shell_event("session.stop.requested", serde_json::json!({ "source": "tauri" }));
    post_json("/api/session/stop", serde_json::json!({}))?;
    shell.hud_enabled.store(false, Ordering::SeqCst);
    shell.hud_hovering.store(false, Ordering::SeqCst);
    if let Some(window) = app.get_webview_window("capture-hud") {
        let _ = window.hide();
    }
    show_main(&app);
    Ok(())
}

#[tauri::command]
fn set_capture_region(
    app: AppHandle,
    shell: State<'_, ShellState>,
    x: i32,
    y: i32,
    width: i32,
    height: i32,
    device_scale_factor: f64,
) -> Result<(), String> {
    log_shell_event(
        "capture_region.set_requested",
        serde_json::json!({
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "device_scale_factor": device_scale_factor,
        }),
    );
    let region = [
        (x as f64 * device_scale_factor).round() as i32,
        (y as f64 * device_scale_factor).round() as i32,
        (width as f64 * device_scale_factor).round() as i32,
        (height as f64 * device_scale_factor).round() as i32,
    ];

    let client = Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .map_err(|error| error.to_string())?;
    let api_base = api_base();
    let mut payload: serde_json::Value = client
        .get(format!("{api_base}/api/config"))
        .send()
        .and_then(|response| response.error_for_status())
        .map_err(|error| error.to_string())?
        .json()
        .map_err(|error| error.to_string())?;
    payload["capture"]["region"] = serde_json::json!(region);

    client
        .put(format!("{api_base}/api/config"))
        .json(&payload)
        .send()
        .and_then(|response| response.error_for_status())
        .map_err(|error| error.to_string())?;

    app.emit(
        "capture-region-selected",
        CaptureRegionPayload {
            x,
            y,
            width,
            height,
        },
    )
    .map_err(|error| error.to_string())?;

    *shell.capture_region.lock().map_err(|_| "capture region lock poisoned")? = Some(CaptureRegionState {
        x,
        y,
        width,
        height,
        device_scale_factor,
    });
    configure_capture_hud(&app, &shell)?;

    if let Some(selector) = app.get_webview_window("selector") {
        let _ = selector.hide();
    }
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.show();
        let _ = main.set_focus();
    }

    Ok(())
}

fn emit_splash_status(app: &AppHandle, text: &str) {
    let _ = app.emit_to("main", "splash-status", serde_json::json!({ "text": text }));
}

fn run_backend_boot(app: &AppHandle) {
    // The Tauri shell is a wrapper around the same served dashboard path used in
    // the browser, so boot success is defined by the local backend becoming ready.
    let started = std::time::Instant::now();
    log_shell_event("backend.boot.start", serde_json::json!({}));
    emit_splash_status(app, "Checking backend...");
    if backend_ready() {
        log_shell_event("backend.boot.ready_existing", serde_json::json!({ "duration_ms": started.elapsed().as_millis() }));
        navigate_main_to_backend(app);
        return;
    }
    emit_splash_status(app, "Starting Python backend...");
    spawn_backend(app.state::<BackendProcess>().inner());
    emit_splash_status(app, "Waiting for backend (up to 60s)...");
    if wait_for_backend(Duration::from_secs(60)) {
        log_shell_event("backend.boot.ready", serde_json::json!({ "duration_ms": started.elapsed().as_millis() }));
        navigate_main_to_backend(app);
    } else {
        log_shell_event("backend.boot.failed", serde_json::json!({ "duration_ms": started.elapsed().as_millis() }));
        let _ = app.emit_to("main", "splash-error", serde_json::json!({}));
    }
}

fn navigate_main_to_backend(app: &AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    // Once the backend is ready, the shell simply navigates the main window to
    // the served dashboard rather than loading a separate desktop-only frontend.
    let Ok(mut url) = Url::parse(&api_base()) else {
        return;
    };
    let launch_id = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().to_string())
        .unwrap_or_else(|_| "0".to_string());
    url.query_pairs_mut().append_pair("desktopLaunch", &launch_id);
    log_shell_event("window.main.navigate", serde_json::json!({ "url": url.as_str() }));
    let _ = window.navigate(url);
    let _ = window.set_focus();
}

fn show_main(app: &AppHandle) {
    if let Ok(window) = main_window(app) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn main() {
    let backend_process = BackendProcess(Arc::new(Mutex::new(None)));
    let shell_state = ShellState {
        capture_region: Arc::new(Mutex::new(None)),
        hud_enabled: Arc::new(AtomicBool::new(false)),
        hud_hovering: Arc::new(AtomicBool::new(false)),
        prev_main_bounds: Arc::new(Mutex::new(None)),
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            log_shell_event("app.single_instance.focus_requested", serde_json::json!({}));
            show_main(app);
        }))
        .manage(backend_process.clone())
        .manage(shell_state.clone())
        .invoke_handler(tauri::generate_handler![
            open_area_selector,
            close_area_selector,
            hide_main_window,
            show_main_window,
            enter_live_mode,
            exit_live_mode,
            show_capture_hud,
            get_api_base,
            stop_translation,
            set_capture_region,
        ])
        .setup(move |app| {
            log_shell_event("app.setup.start", serde_json::json!({}));
            if let Some(main) = app.get_webview_window("main") {
                let _ = main.set_decorations(true);
            }

            let app_handle_for_boot = app.handle().clone();
            std::thread::spawn(move || {
                run_backend_boot(&app_handle_for_boot);
            });

            let app_handle_for_retry = app.handle().clone();
            app.listen_any("splash-retry", move |_event| {
                log_shell_event("backend.boot.retry_requested", serde_json::json!({}));
                let handle = app_handle_for_retry.clone();
                std::thread::spawn(move || {
                    run_backend_boot(&handle);
                });
            });

            let show_item = MenuItem::with_id(app, "show", "Open App", true, None::<&str>)?;
            let selector_item =
                MenuItem::with_id(app, "select-area", "Select Capture Area", true, None::<&str>)?;
            let stop_item = MenuItem::with_id(app, "stop", "Stop Translation", true, None::<&str>)?;
            let exit_item = MenuItem::with_id(app, "exit", "Exit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &selector_item, &stop_item, &exit_item])?;

            let icon = app
                .default_window_icon()
                .cloned()
                .ok_or("Default window icon is missing")?;
            let handle = app.handle().clone();
            TrayIconBuilder::new()
                .icon(icon)
                .tooltip("Meowcal Sub 2")
                .menu(&menu)
                .on_menu_event(move |tray, event| match event.id.as_ref() {
                    "show" => {
                        log_shell_event("tray.show.selected", serde_json::json!({}));
                        show_main(tray.app_handle())
                    }
                    "select-area" => {
                        log_shell_event("tray.select_area.selected", serde_json::json!({}));
                        if let Some(window) = tray.app_handle().get_webview_window("selector") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "stop" => {
                        log_shell_event("tray.stop.selected", serde_json::json!({}));
                        let app_handle = tray.app_handle().clone();
                        let _ = post_json("/api/session/stop", serde_json::json!({}));
                        {
                            let shell = app_handle.state::<ShellState>();
                            shell.hud_enabled.store(false, Ordering::SeqCst);
                            shell.hud_hovering.store(false, Ordering::SeqCst);
                        }
                        if let Some(window) = app_handle.get_webview_window("capture-hud") {
                            let _ = window.hide();
                        }
                        show_main(&app_handle);
                    }
                    "exit" => {
                        log_shell_event("tray.exit.selected", serde_json::json!({}));
                        tray.app_handle().exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(move |tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        log_shell_event("tray.icon.clicked", serde_json::json!({ "button": "left" }));
                        show_main(tray.app_handle());
                    }
                })
                .build(app)?;

            if let Some(main) = app.get_webview_window("main") {
                let app_handle = handle.clone();
                main.on_window_event(move |event| {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                        log_shell_event("window.main.close_intercepted", serde_json::json!({}));
                        api.prevent_close();
                        if let Ok(window) = main_window(&app_handle) {
                            let _ = hide_window_to_tray(&window);
                        }
                    }
                });
            }

            if let Some(hud) = app.get_webview_window("capture-hud") {
                let _ = hud.set_ignore_cursor_events(true);
            }

            let app_handle = app.handle().clone();
            let shell = shell_state.clone();
            tauri::async_runtime::spawn(async move {
                loop {
                    if shell.hud_enabled.load(Ordering::SeqCst) {
                        let region = *shell.capture_region.lock().expect("capture region lock");
                        if let Some(region) = region {
                            if let Some((cursor_x, cursor_y)) = current_cursor_position() {
                                let hovering = cursor_x >= region.x
                                    && cursor_x <= region.x + region.width
                                    && cursor_y >= region.y
                                    && cursor_y <= region.y + region.height;
                                let previous = shell.hud_hovering.swap(hovering, Ordering::SeqCst);
                                if previous != hovering {
                                    if let Some(window) = app_handle.get_webview_window("capture-hud") {
                                        let _ = window.set_ignore_cursor_events(!hovering);
                                    }
                                    let _ = app_handle.emit_to(
                                        "capture-hud",
                                        "capture-hud-hover",
                                        HoverStatePayload { hovering },
                                    );
                                }
                            }
                        }
                    }
                    sleep(Duration::from_millis(120)).await;
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri app");
}
