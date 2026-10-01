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
    open: bool,
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
        if let Err(error) = keep_dock_visible(&window, at, size, scale, open) {
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

/// The watcher calls this only while a live session owns the dock. Check the
/// bead and, when open, points across the controls. A windowed player can cover
/// the controls without covering the bead at the right edge.
fn keep_dock_visible(
    window: &WebviewWindow,
    at: PhysicalPosition<i32>,
    size: PhysicalSize<u32>,
    scale: f64,
    open: bool,
) -> Result<(), String> {
    #[cfg(windows)]
    {
        use windows::Win32::Foundation::POINT;
        use windows::Win32::UI::WindowsAndMessaging::{GetAncestor, WindowFromPoint, GA_ROOT};

        let hwnd = window.hwnd().map_err(|error| error.to_string())?;
        for (x, y) in dock_probe_points(at, size, scale, open) {
            let top_root = unsafe { GetAncestor(WindowFromPoint(POINT { x, y }), GA_ROOT) };
            if top_root != hwnd {
                raise_topmost(window)?;
                break;
            }
        }
    }
    #[cfg(not(windows))]
    let _ = (window, at, size, scale, open);
    Ok(())
}

/// Screen points that must stay clickable as the dock grows from the bead.
fn dock_probe_points(
    at: PhysicalPosition<i32>,
    size: PhysicalSize<u32>,
    scale: f64,
    open: bool,
) -> Vec<(i32, i32)> {
    let bead = super::pill_rect(at, size, (DOCK_COLLAPSED_CSS * scale).round() as i32);
    let mut points = vec![(bead.0 + bead.2 / 2, bead.1 + bead.3 / 2)];
    if open {
        let full = super::pill_rect(at, size, size.width as i32);
        for quarter in 1..=3 {
            points.push((full.0 + full.2 * quarter / 4, full.1 + full.3 / 2));
        }
    }
    points
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn expanded_dock_detects_a_window_covering_controls_but_not_bead() {
        let at = PhysicalPosition { x: 1500, y: 20 };
        let size = PhysicalSize {
            width: 380,
            height: 44,
        };
        let covered_controls = (1700, 20, 100, 44);
        assert!(dock_probe_points(at, size, 1.0, false)
            .iter()
            .all(|&point| !super::super::rect_holds(covered_controls, point)));
        assert!(dock_probe_points(at, size, 1.0, true)
            .iter()
            .any(|&point| super::super::rect_holds(covered_controls, point)));
    }
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
