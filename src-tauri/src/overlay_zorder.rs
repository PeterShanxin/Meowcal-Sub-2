//! Keep the subtitle plate and live dock ahead of a topmost video window.

use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Manager, PhysicalPosition, PhysicalSize, WebviewWindow};

use super::{
    anchor_for, clip_pill, dock_bounds, overlay_window, place, OverlayAnchor, DEFAULT_HEIGHT_CSS,
    DOCK_COLLAPSED_CSS,
};

/// Put the dock in its corner at full size, showing only the bead.
pub fn place_dock(
    window: &WebviewWindow,
    anchor: OverlayAnchor,
    scale: f64,
) -> Result<(PhysicalPosition<i32>, PhysicalSize<u32>, f64), String> {
    let (at, extent) = dock_bounds(anchor.monitor_position, anchor.monitor_size, scale);
    window.set_size(extent).map_err(|error| error.to_string())?;
    window.set_position(at).map_err(|error| error.to_string())?;
    clip_pill(window, (DOCK_COLLAPSED_CSS * scale).round() as i32)?;
    raise_topmost(window)?;
    Ok((at, extent, scale))
}

/// Queue the Z-order check on the UI thread, where the synchronous exit-live
/// command also runs. A check queued before exit is harmless: its generation
/// is checked when it runs, so it cannot raise Studio again after exit.
pub(crate) fn queue_dock_refresh(
    app: &AppHandle,
    generation: &Arc<Mutex<u64>>,
    ticket: u64,
    at: PhysicalPosition<i32>,
    size: PhysicalSize<u32>,
    scale: f64,
) -> Result<(), String> {
    let app_for_main = app.clone();
    let generation = Arc::clone(generation);
    app.run_on_main_thread(move || {
        if generation
            .lock()
            .map(|latest| *latest != ticket)
            .unwrap_or(true)
        {
            return;
        }
        let Some(window) = app_for_main.get_webview_window("main") else {
            return;
        };
        if let Err(error) = keep_dock_visible(&window, at, size, scale) {
            crate::log_shell_event("dock.raise.failed", serde_json::json!({ "error": error }));
        }
    })
    .map_err(|error| {
        let message = error.to_string();
        crate::log_shell_event(
            "dock.raise.queue_failed",
            serde_json::json!({ "error": message }),
        );
        message
    })
}

/// The watcher calls this only while a live session owns the dock. The center
/// of its clipped bead is always an actual clickable part of the main window.
/// Check the window that would receive a click there, and reorder only if that
/// point is covered by another topmost window.
fn keep_dock_visible(
    window: &WebviewWindow,
    at: PhysicalPosition<i32>,
    size: PhysicalSize<u32>,
    scale: f64,
) -> Result<(), String> {
    #[cfg(windows)]
    {
        use windows::Win32::Foundation::POINT;
        use windows::Win32::UI::WindowsAndMessaging::{GetAncestor, WindowFromPoint, GA_ROOT};

        let bead = super::pill_rect(at, size, (DOCK_COLLAPSED_CSS * scale).round() as i32);
        let center = POINT {
            x: bead.0 + bead.2 / 2,
            y: bead.1 + bead.3 / 2,
        };
        let hwnd = window.hwnd().map_err(|error| error.to_string())?;
        let top_root = unsafe { GetAncestor(WindowFromPoint(center), GA_ROOT) };
        if top_root != hwnd {
            raise_topmost(window)?;
        }
    }
    #[cfg(not(windows))]
    let _ = (window, at, size, scale);
    Ok(())
}

/// Put the plate on screen beside `region`, returning the anchor it was placed on.
pub fn show(app: &AppHandle, region: [i32; 4]) -> Result<(OverlayAnchor, f64), String> {
    let (anchor, scale) = anchor_for(app, region)?;
    place(app, anchor, scale, DEFAULT_HEIGHT_CSS)?;
    let window = overlay_window(app)?;
    // The plate is scenery, not a control: clicks belong to the player behind it.
    window
        .set_ignore_cursor_events(true)
        .map_err(|error| error.to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window
        .set_always_on_top(true)
        .map_err(|error| error.to_string())?;
    raise_topmost(&window)?;
    Ok((anchor, scale))
}

/// Reinsert a window at the front of the topmost band without taking focus.
///
/// `set_always_on_top(true)` sets the topmost style, but a fullscreen player can
/// already be ahead of another topmost window. Reapplying that style does not
/// reliably move the plate ahead of the player; an explicit Z-order operation
/// does. The player remains active so playback and keyboard controls keep working.
#[cfg(windows)]
pub(super) fn raise_topmost(window: &WebviewWindow) -> Result<(), String> {
    use windows::Win32::UI::WindowsAndMessaging::{
        SetWindowPos, HWND_TOPMOST, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE,
    };

    let hwnd = window.hwnd().map_err(|error| error.to_string())?;
    unsafe {
        SetWindowPos(
            hwnd,
            Some(HWND_TOPMOST),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        .map_err(|error| error.to_string())
    }
}

#[cfg(not(windows))]
pub(super) fn raise_topmost(_window: &WebviewWindow) -> Result<(), String> {
    Ok(())
}
