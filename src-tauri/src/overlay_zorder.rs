//! Show the subtitle plate ahead of topmost video windows without taking focus.

use tauri::{AppHandle, WebviewWindow};

use super::{anchor_for, overlay_window, place, OverlayAnchor, DEFAULT_HEIGHT_CSS};

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
    raise_plate(&window)?;
    Ok((anchor, scale))
}

/// Reinsert the plate at the front of the topmost band without taking focus.
///
/// `set_always_on_top(true)` sets the topmost style, but a fullscreen player can
/// already be ahead of another topmost window. Reapplying that style does not
/// reliably move the plate ahead of the player; an explicit Z-order operation
/// does. The player remains active so playback and keyboard controls keep working.
#[cfg(windows)]
pub(super) fn raise_plate(window: &WebviewWindow) -> Result<(), String> {
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
pub(super) fn raise_plate(_window: &WebviewWindow) -> Result<(), String> {
    Ok(())
}
