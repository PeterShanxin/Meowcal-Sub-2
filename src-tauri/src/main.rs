#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

mod overlay_window;

use overlay_window::OverlayAnchor;
use reqwest::blocking::Client;
use serde::Serialize;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Listener, Manager,
    PhysicalPosition, PhysicalSize, State,
};
use url::Url;

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

#[derive(Clone, Copy)]
struct MainWindowBounds {
    position: PhysicalPosition<i32>,
    size: PhysicalSize<u32>,
    maximized: bool,
}

struct ShellState {
    prev_main_bounds: Arc<Mutex<Option<MainWindowBounds>>>,
    /// The still the capture selector draws on, held only while it is open.
    selector_backdrop: Arc<Mutex<Option<String>>>,
    /// Where the subtitle plate is anchored, so the page can ask to be a
    /// different height without the shell measuring the region again.
    overlay_anchor: Arc<Mutex<Option<(OverlayAnchor, f64)>>>,
    /// Which dock resize is the current one. The pointer crossing the bead twice
    /// in quick succession starts two, and only the later one should finish.
    dock_resize: Arc<Mutex<u64>>,
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

/// This run's Studio token, written by the backend when it starts listening.
///
/// Read fresh every time: the token changes with each backend start, and the
/// shell can outlive a backend restart.
fn access_token() -> String {
    let Some(appdata) = std::env::var_os("APPDATA") else {
        return String::new();
    };
    let path = PathBuf::from(appdata)
        .join("meowcal-sub-2")
        .join("runtime.json");
    std::fs::read_to_string(path)
        .ok()
        .and_then(|body| serde_json::from_str::<serde_json::Value>(&body).ok())
        .and_then(|value| {
            value
                .get("token")
                .and_then(|token| token.as_str())
                .map(str::to_string)
        })
        .unwrap_or_default()
}

fn authorized(builder: reqwest::blocking::RequestBuilder) -> reqwest::blocking::RequestBuilder {
    builder.header("X-Meowcal-Token", access_token())
}

fn backend_ready() -> bool {
    let api_base = api_base();
    Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .ok()
        .and_then(|client| authorized(client.get(format!("{api_base}/api/state"))).send().ok())
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
    let response = authorized(client.post(format!("{api_base}{path}")))
        .json(&body)
        .send()
        .map_err(|error| error.to_string())?;
    if response.status().is_success() {
        Ok(())
    } else {
        Err(format!("Backend request failed: {}", response.status()))
    }
}

fn main_window(app: &AppHandle) -> Result<tauri::WebviewWindow, String> {
    app.get_webview_window("main")
        .ok_or_else(|| "Main window not found".to_string())
}

fn hide_window_to_tray(window: &tauri::WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|error| error.to_string())
}

#[tauri::command]
async fn open_area_selector(app: AppHandle) -> Result<(), String> {
    show_area_selector(app).await
}

/// Puts the selector up over a still of the screen, from wherever it was asked
/// for - the studio's own button or the tray.
async fn show_area_selector(app: AppHandle) -> Result<(), String> {
    log_shell_event("selector.open.requested", serde_json::json!({}));
    let window = app
        .get_webview_window("selector")
        .ok_or("Selector window not found")?;
    // The region being drawn is the subtitle band of whatever the user is
    // watching, which is behind this window. Both the confirm and the cancel
    // path bring it back.
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.hide();
    }
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "no monitor".to_string())?;
    let origin = *monitor.position();
    let size = *monitor.size();
    // The studio window was covering the video a moment ago. The still is taken
    // after the compositor has had a beat to take it off screen, or the studio
    // is what the user ends up drawing on.
    tokio::time::sleep(Duration::from_millis(160)).await;
    let backdrop = tauri::async_runtime::spawn_blocking(move || {
        fetch_selector_backdrop(origin.x, origin.y, size.width, size.height)
    })
    .await
    .map_err(|error| error.to_string())?;
    match &backdrop {
        Ok(_) => log_shell_event("selector.backdrop.captured", serde_json::json!({})),
        Err(error) => {
            log_shell_event("selector.backdrop.failed", serde_json::json!({ "error": error }))
        }
    }
    if let Some(shell) = app.try_state::<ShellState>() {
        *shell
            .selector_backdrop
            .lock()
            .map_err(|_| "backdrop lock poisoned")? = backdrop.ok();
    }
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;
    Ok(())
}

/// A still of the screen the selector is about to cover.
///
/// A player left underneath a full-screen window is free to stop painting its
/// video, so the live desktop is not something the selector can rely on showing.
fn fetch_selector_backdrop(x: i32, y: i32, width: u32, height: u32) -> Result<String, String> {
    let client = Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .map_err(|error| error.to_string())?;
    let payload: serde_json::Value = authorized(client.get(format!(
        "{}/api/capture/screen?x={x}&y={y}&width={width}&height={height}",
        api_base()
    )))
    .send()
    .and_then(|response| response.error_for_status())
    .map_err(|error| error.to_string())?
    .json()
    .map_err(|error| error.to_string())?;
    payload["dataUrl"]
        .as_str()
        .map(str::to_string)
        .ok_or_else(|| "capture returned no image".to_string())
}

/// The still for the selector to paint, one per open.
#[tauri::command]
fn get_selector_backdrop(shell: State<'_, ShellState>) -> Result<Option<String>, String> {
    Ok(shell
        .selector_backdrop
        .lock()
        .map_err(|_| "backdrop lock poisoned")?
        .clone())
}

/// Drops the held still. It is a picture of the user's screen, and the next open
/// takes its own.
fn release_selector_backdrop(shell: &ShellState) {
    if let Ok(mut held) = shell.selector_backdrop.lock() {
        *held = None;
    }
}

/// Closes the selector after the user backed out, so a start that was waiting on
/// a region can stop waiting instead of hanging on an event that never comes.
#[tauri::command]
fn cancel_area_selector(app: AppHandle, shell: State<'_, ShellState>) -> Result<(), String> {
    log_shell_event("selector.cancel.requested", serde_json::json!({}));
    release_selector_backdrop(&shell);
    if let Some(selector) = app.get_webview_window("selector") {
        selector.hide().map_err(|error| error.to_string())?;
    }
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.show();
        let _ = main.set_focus();
    }
    app.emit("capture-region-cancelled", ())
        .map_err(|error| error.to_string())
}

/// The saved region in the selector window's own CSS pixels, so a reselect starts
/// from the box the last session used. `None` once it belongs to another monitor.
#[tauri::command]
fn get_capture_region(app: AppHandle) -> Result<Option<CaptureRegionPayload>, String> {
    let selector = app
        .get_webview_window("selector")
        .ok_or("Selector window not found")?;
    let monitor = selector
        .current_monitor()
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "no monitor".to_string())?;
    let scale = monitor.scale_factor();
    let origin = monitor.position();
    let size = monitor.size();

    let client = Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .map_err(|error| error.to_string())?;
    let payload: serde_json::Value = authorized(client.get(format!("{}/api/config", api_base())))
        .send()
        .and_then(|response| response.error_for_status())
        .map_err(|error| error.to_string())?
        .json()
        .map_err(|error| error.to_string())?;
    let region = payload["capture"]["region"]
        .as_array()
        .map(|values| {
            values
                .iter()
                .filter_map(|value| value.as_i64().map(|n| n as i32))
                .collect::<Vec<i32>>()
        })
        .unwrap_or_default();
    if region.len() != 4 || region[2] <= 0 || region[3] <= 0 {
        return Ok(None);
    }

    // A region saved on another monitor maps outside this window, and a box the
    // user cannot see is worse than starting blank.
    let on_this_monitor = region[0] >= origin.x
        && region[1] >= origin.y
        && region[0] + region[2] <= origin.x + size.width as i32
        && region[1] + region[3] <= origin.y + size.height as i32;
    if !on_this_monitor {
        return Ok(None);
    }

    let to_css = |value: i32| (value as f64 / scale).round() as i32;
    Ok(Some(CaptureRegionPayload {
        x: to_css(region[0] - origin.x),
        y: to_css(region[1] - origin.y),
        width: to_css(region[2]),
        height: to_css(region[3]),
    }))
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
fn enter_live_mode(
    app: AppHandle,
    shell: State<'_, ShellState>,
    region: Vec<i32>,
) -> Result<(), String> {
    log_shell_event(
        "window.live.enter_requested",
        serde_json::json!({ "region": region }),
    );
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
    let scale = monitor.scale_factor();

    window.set_decorations(false).map_err(|e| e.to_string())?;
    window.set_always_on_top(true).map_err(|e| e.to_string())?;
    window.set_resizable(false).map_err(|e| e.to_string())?;
    // The dock starts as a bead. The page grows it when the pointer arrives, so
    // the rest of the corner belongs to whatever is playing underneath. The
    // studio's own minimum is far larger than a bead, so it is lifted first.
    let bead = (overlay_window::DOCK_COLLAPSED_CSS * scale).round() as u32;
    window
        .set_min_size(Some(PhysicalSize {
            width: bead,
            height: bead,
        }))
        .map_err(|e| e.to_string())?;
    overlay_window::place_dock(
        &window,
        overlay_window::DOCK_COLLAPSED_CSS,
        overlay_window::DOCK_COLLAPSED_CSS,
    )?;

    show_subtitle_plate(&app, &shell, &region);
    Ok(())
}

/// How a dock resize is drawn: long enough to read as a movement, short enough
/// that the controls are usable the moment the pointer lands on them.
const DOCK_RESIZE_STEPS: u32 = 18;
const DOCK_RESIZE_FRAME_MS: u64 = 14;

/// Resize the live dock to what the page has drawn.
///
/// The pointer arriving turns a bead into a row of controls, and the window has
/// to be the size of whichever of those is on screen: any larger and it takes
/// clicks meant for the video behind it. The window is the shape the viewer
/// sees, so the change is walked rather than jumped.
#[tauri::command]
async fn set_dock_size(
    app: AppHandle,
    shell: State<'_, ShellState>,
    width_css: f64,
    height_css: f64,
) -> Result<(), String> {
    let window = main_window(&app)?;
    let scale = window.scale_factor().map_err(|e| e.to_string())?;
    let current = window.outer_size().map_err(|e| e.to_string())?;
    let from = (
        f64::from(current.width) / scale,
        f64::from(current.height) / scale,
    );

    let resize = {
        let mut latest = shell.dock_resize.lock().map_err(|_| "dock resize lock poisoned")?;
        *latest += 1;
        *latest
    };
    let generation = Arc::clone(&shell.dock_resize);

    for step in 1..=DOCK_RESIZE_STEPS {
        if generation.lock().map(|latest| *latest != resize).unwrap_or(true) {
            return Ok(());
        }
        let (width, height) =
            overlay_window::tween_size(from, (width_css, height_css), step, DOCK_RESIZE_STEPS);
        overlay_window::place_dock(&window, width, height)?;
        tokio::time::sleep(Duration::from_millis(DOCK_RESIZE_FRAME_MS)).await;
    }
    Ok(())
}

/// Put the subtitle plate beside the capture region, and remember where.
///
/// A session without a usable region has nothing to anchor to; the studio blocks
/// starting one, so this only guards against a config written by hand.
fn show_subtitle_plate(app: &AppHandle, shell: &ShellState, region: &[i32]) {
    let Ok(region) = <[i32; 4]>::try_from(region) else {
        log_shell_event(
            "overlay.place.skipped",
            serde_json::json!({ "reason": "region is not four numbers" }),
        );
        return;
    };
    match overlay_window::show(app, region) {
        Ok(placed) => {
            if let Ok(mut anchor) = shell.overlay_anchor.lock() {
                *anchor = Some(placed);
            }
            log_shell_event("overlay.shown", serde_json::json!({ "region": region }));
        }
        Err(error) => log_shell_event("overlay.show.failed", serde_json::json!({ "error": error })),
    }
}

/// Resize the plate to the height its content actually needs.
///
/// The shell guesses two lines at the default font; the page is the only side
/// that knows what the viewer's font size and this line's wrapping came to.
#[tauri::command]
fn set_overlay_height(
    app: AppHandle,
    shell: State<'_, ShellState>,
    height_css: f64,
) -> Result<(), String> {
    let placed = *shell
        .overlay_anchor
        .lock()
        .map_err(|_| "overlay anchor lock poisoned")?;
    let Some((anchor, scale)) = placed else {
        return Ok(());
    };
    overlay_window::place(&app, anchor, scale, height_css)
}

#[tauri::command]
fn exit_live_mode(app: AppHandle, shell: State<'_, ShellState>) -> Result<(), String> {
    log_shell_event("window.live.exit_requested", serde_json::json!({}));
    let _ = overlay_window::hide(&app);
    if let Ok(mut anchor) = shell.overlay_anchor.lock() {
        *anchor = None;
    }
    let window = main_window(&app)?;
    let _ = overlay_window::unclip(&window);
    let _ = window.set_min_size(None::<PhysicalSize<u32>>);
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
fn get_api_base() -> String {
    api_base()
}

#[tauri::command]
fn get_api_token() -> String {
    access_token()
}

#[tauri::command]
fn stop_translation(app: AppHandle) -> Result<(), String> {
    log_shell_event("session.stop.requested", serde_json::json!({ "source": "tauri" }));
    post_json("/api/session/stop", serde_json::json!({}))?;
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
) -> Result<(), String> {
    // The selector reports CSS pixels inside its own fullscreen window. Screen
    // capture wants physical pixels on the virtual desktop, so the monitor's
    // scale factor and its origin both have to be applied - on a second monitor
    // the origin is not zero, and it can be negative.
    let selector = app
        .get_webview_window("selector")
        .ok_or("Selector window not found")?;
    let monitor = selector
        .current_monitor()
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "no monitor".to_string())?;
    let scale = monitor.scale_factor();
    let origin = monitor.position();
    log_shell_event(
        "capture_region.set_requested",
        serde_json::json!({
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "scale_factor": scale,
            "monitor_origin": [origin.x, origin.y],
        }),
    );
    let region = [
        origin.x + (x as f64 * scale).round() as i32,
        origin.y + (y as f64 * scale).round() as i32,
        (width as f64 * scale).round() as i32,
        (height as f64 * scale).round() as i32,
    ];

    let client = Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .map_err(|error| error.to_string())?;
    let api_base = api_base();
    let mut payload: serde_json::Value = authorized(client.get(format!("{api_base}/api/config")))
        .send()
        .and_then(|response| response.error_for_status())
        .map_err(|error| error.to_string())?
        .json()
        .map_err(|error| error.to_string())?;
    payload["capture"]["region"] = serde_json::json!(region);

    authorized(client.put(format!("{api_base}/api/config")))
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

    // A region re-drawn during a session moves the plate with it; outside one
    // the plate is hidden and has nothing to follow.
    if shell
        .overlay_anchor
        .lock()
        .map(|anchor| anchor.is_some())
        .unwrap_or(false)
    {
        show_subtitle_plate(&app, &shell, &region);
    }

    release_selector_backdrop(&shell);
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
    url.query_pairs_mut().append_pair("token", &access_token());
    log_shell_event("window.main.navigate", serde_json::json!({ "url": url.as_str() }));
    let _ = window.navigate(url);
    let _ = window.set_focus();
    navigate_overlay_to_backend(app);
}

/// Point the (hidden) subtitle plate at its page, so it is already listening for
/// lines by the time a session starts.
fn navigate_overlay_to_backend(app: &AppHandle) {
    let Some(window) = app.get_webview_window("overlay") else {
        return;
    };
    let Ok(mut url) = Url::parse(&format!("{}/overlay", api_base())) else {
        return;
    };
    url.query_pairs_mut().append_pair("token", &access_token());
    log_shell_event("window.overlay.navigate", serde_json::json!({}));
    let _ = window.navigate(url);
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
        prev_main_bounds: Arc::new(Mutex::new(None)),
        selector_backdrop: Arc::new(Mutex::new(None)),
        overlay_anchor: Arc::new(Mutex::new(None)),
        dock_resize: Arc::new(Mutex::new(0)),
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            log_shell_event("app.single_instance.focus_requested", serde_json::json!({}));
            show_main(app);
        }))
        .manage(backend_process.clone())
        .manage(shell_state)
        .invoke_handler(tauri::generate_handler![
            open_area_selector,
            cancel_area_selector,
            get_capture_region,
            get_selector_backdrop,
            hide_main_window,
            show_main_window,
            enter_live_mode,
            exit_live_mode,
            set_overlay_height,
            set_dock_size,
            get_api_base,
            stop_translation,
            set_capture_region,
            get_api_token,
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
                        let app_handle = tray.app_handle().clone();
                        tauri::async_runtime::spawn(async move {
                            let _ = show_area_selector(app_handle).await;
                        });
                    }
                    "stop" => {
                        log_shell_event("tray.stop.selected", serde_json::json!({}));
                        let app_handle = tray.app_handle().clone();
                        let _ = post_json("/api/session/stop", serde_json::json!({}));
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

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri app");
}
