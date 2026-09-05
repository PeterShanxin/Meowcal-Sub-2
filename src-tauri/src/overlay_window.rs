//! The subtitle plate window: where it goes, and how big it is.
//!
//! The plate is its own small window rather than a full-screen transparent one.
//! A window that covers the player is free to make the player stop painting -
//! that is what turned the capture selector's backdrop black - and it would also
//! sit over the burned-in subtitles the session is reading. A window the size of
//! the plate does neither.

use tauri::{AppHandle, Manager, PhysicalPosition, PhysicalSize, WebviewWindow};

/// Distance between the capture region and the plate, in CSS pixels.
const GAP_CSS: f64 = 12.0;
/// Space kept between the plate and the edge of the monitor, in CSS pixels.
const EDGE_MARGIN_CSS: f64 = 8.0;
/// Room for two lines at the default font size, until the page measures itself.
pub const DEFAULT_HEIGHT_CSS: f64 = 116.0;
/// A plate narrower than this wraps short dialogue onto several lines.
const MIN_WIDTH_CSS: f64 = 480.0;
/// The widest the plate may grow, as a fraction of the monitor.
const MAX_WIDTH_FRACTION: f64 = 0.9;

/// The capture region and the monitor it sits on, in physical pixels.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct OverlayAnchor {
    pub region: [i32; 4],
    pub monitor_position: (i32, i32),
    pub monitor_size: (u32, u32),
}

/// Where the plate goes, given the room its content needs.
///
/// Below the capture region when the monitor has room for it, above when it does
/// not: the region is where the burned-in subtitles are, so the plate has to
/// clear it either way.
pub fn plate_bounds(
    anchor: OverlayAnchor,
    scale: f64,
    height_css: f64,
) -> (PhysicalPosition<i32>, PhysicalSize<u32>) {
    let [region_x, region_y, region_w, region_h] = anchor.region;
    let (monitor_x, monitor_y) = anchor.monitor_position;
    let (monitor_w, monitor_h) = anchor.monitor_size;

    let gap = (GAP_CSS * scale).round() as i32;
    let margin = (EDGE_MARGIN_CSS * scale).round() as i32;
    let height = (height_css * scale).round().max(1.0) as i32;

    let max_width = (monitor_w as f64 * MAX_WIDTH_FRACTION).round() as i32;
    let min_width = ((MIN_WIDTH_CSS * scale).round() as i32).min(max_width);
    let width = region_w.clamp(min_width, max_width);

    let monitor_right = monitor_x + monitor_w as i32;
    let monitor_bottom = monitor_y + monitor_h as i32;
    let centered_x = region_x + (region_w - width) / 2;
    let x = centered_x.clamp(
        monitor_x + margin,
        (monitor_right - width - margin).max(monitor_x),
    );

    let below = region_y + region_h + gap;
    let above = region_y - gap - height;
    let y = if below + height <= monitor_bottom - margin {
        below
    } else if above >= monitor_y + margin {
        above
    } else {
        // Neither side has room, which means the region nearly fills the screen.
        // Sitting on the bottom edge still leaves the plate readable.
        (monitor_bottom - height - margin).max(monitor_y)
    };

    (
        PhysicalPosition { x, y },
        PhysicalSize {
            width: width.max(1) as u32,
            height: height.max(1) as u32,
        },
    )
}

/// Space kept between the dock and the corner it sits in, in CSS pixels.
const DOCK_MARGIN_CSS: f64 = 16.0;
/// The dock at rest: a bead the viewer can find but not trip over.
pub const DOCK_COLLAPSED_CSS: f64 = 44.0;
/// The dock with the pointer on it, wide enough for the three controls.
pub const DOCK_EXPANDED_CSS: f64 = 284.0;
/// The dock's height, which does not change.
pub const DOCK_HEIGHT_CSS: f64 = 44.0;

/// Where the live dock goes: the top-right corner.
///
/// The plate is anchored to the capture region, which is wherever the burned-in
/// subtitles are - the lower half of the picture, in every player. Putting the
/// controls in the opposite corner keeps them off both the plate and the
/// player's own bar along the bottom.
///
/// The window is always the expanded size. Only the pill cut out of it changes,
/// so opening and closing the dock never resizes the webview - resizing it once
/// per animation frame is what made the dock tear as it grew.
pub fn dock_bounds(
    monitor_position: (i32, i32),
    monitor_size: (u32, u32),
    scale: f64,
) -> (PhysicalPosition<i32>, PhysicalSize<u32>) {
    let (monitor_x, monitor_y) = monitor_position;
    let (monitor_w, monitor_h) = monitor_size;
    let margin = (DOCK_MARGIN_CSS * scale).round() as i32;
    let width = ((DOCK_EXPANDED_CSS * scale).round() as i32).min(monitor_w as i32);
    let height = ((DOCK_HEIGHT_CSS * scale).round() as i32).min(monitor_h as i32);
    (
        PhysicalPosition {
            x: monitor_x + monitor_w as i32 - width - margin,
            y: monitor_y + margin,
        },
        PhysicalSize {
            width: width as u32,
            height: height as u32,
        },
    )
}

/// The part of the dock window the viewer can see and click, given how far open
/// it is. Right-aligned, because the dock grows out of its corner.
pub fn pill_rect(
    dock_at: PhysicalPosition<i32>,
    dock_size: PhysicalSize<u32>,
    visible_width_px: i32,
) -> (i32, i32, i32, i32) {
    let visible = visible_width_px.clamp(1, dock_size.width as i32);
    (
        dock_at.x + dock_size.width as i32 - visible,
        dock_at.y,
        visible,
        dock_size.height as i32,
    )
}

/// Whether a point is inside a rectangle given as (x, y, width, height).
pub fn rect_holds(rect: (i32, i32, i32, i32), point: (i32, i32)) -> bool {
    let (x, y, width, height) = rect;
    point.0 >= x && point.0 < x + width && point.1 >= y && point.1 < y + height
}

/// Cut the dock window down to the pill the viewer sees.
///
/// The studio window is created with decorations, and a decorated window on this
/// platform does not take a transparent frame - asking for one left the bead as
/// a black square with the video showing round it. A native window region is not
/// a paint at all: what falls outside it stops being part of the window, so it
/// is neither drawn nor clickable, and opening the dock is a clip rather than a
/// resize.
#[cfg(windows)]
pub fn clip_pill(window: &WebviewWindow, visible_width_px: i32) -> Result<(), String> {
    use windows::Win32::Graphics::Gdi::{CreateRoundRectRgn, DeleteObject, SetWindowRgn};

    let hwnd = window.hwnd().map_err(|error| error.to_string())?;
    // A window without decorations still carries an invisible resize frame, and
    // the region is measured from the outer edge of it. Cutting the pill from
    // the outer size leaves that frame inside the shape, showing as a pale rim
    // around the dark bead, so the shape is cut from the webview's own rect.
    let outer = window.outer_position().map_err(|error| error.to_string())?;
    let inner = window.inner_position().map_err(|error| error.to_string())?;
    let size = window.inner_size().map_err(|error| error.to_string())?;
    let inset_x = inner.x - outer.x;
    let top = inner.y - outer.y;
    let width = size.width as i32;
    let height = size.height as i32;
    let visible = visible_width_px.clamp(1, width);
    let left = inset_x + width - visible;
    // SetWindowRgn takes ownership of the region on success, and the rectangle
    // is exclusive of its right and bottom edge.
    unsafe {
        let region = CreateRoundRectRgn(
            left,
            top,
            left + visible + 1,
            top + height + 1,
            height,
            height,
        );
        if region.is_invalid() {
            return Err("CreateRoundRectRgn failed".to_string());
        }
        if SetWindowRgn(hwnd, Some(region), true) == 0 {
            let _ = DeleteObject(region.into());
            return Err("SetWindowRgn failed".to_string());
        }
    }
    Ok(())
}

#[cfg(not(windows))]
pub fn clip_pill(_window: &WebviewWindow, _visible_width_px: i32) -> Result<(), String> {
    Ok(())
}

/// Give the window its square corners back, for when it is the studio again.
pub fn unclip(window: &WebviewWindow) -> Result<(), String> {
    #[cfg(windows)]
    {
        use windows::Win32::Graphics::Gdi::SetWindowRgn;
        let hwnd = window.hwnd().map_err(|error| error.to_string())?;
        unsafe {
            SetWindowRgn(hwnd, None, true);
        }
    }
    #[cfg(not(windows))]
    let _ = window;
    Ok(())
}

/// Where the pointer is on the desktop, for deciding whether it is on the dock.
///
/// The webview's own leave event is not enough on its own: the pointer can end
/// up somewhere the dock never hears about, which leaves it stuck open. The
/// cursor position is the one answer that holds whatever the webview saw.
#[cfg(windows)]
pub fn cursor_position() -> Option<(i32, i32)> {
    use windows::Win32::Foundation::POINT;
    use windows::Win32::UI::WindowsAndMessaging::GetCursorPos;

    let mut point = POINT::default();
    unsafe { GetCursorPos(&mut point).ok()? };
    Some((point.x, point.y))
}

#[cfg(not(windows))]
pub fn cursor_position() -> Option<(i32, i32)> {
    None
}

/// Put the dock in its corner at full size, showing only the bead.
pub fn place_dock(
    window: &WebviewWindow,
) -> Result<(PhysicalPosition<i32>, PhysicalSize<u32>, f64), String> {
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "no monitor".to_string())?;
    let position = *monitor.position();
    let size = *monitor.size();
    let scale = monitor.scale_factor();
    let (at, extent) = dock_bounds((position.x, position.y), (size.width, size.height), scale);
    window.set_size(extent).map_err(|error| error.to_string())?;
    window.set_position(at).map_err(|error| error.to_string())?;
    clip_pill(window, (DOCK_COLLAPSED_CSS * scale).round() as i32)?;
    Ok((at, extent, scale))
}

/// How far along an ease-out curve the dock is, `t` running 0 to 1.
///
/// Quintic: almost all of the travel happens immediately and the last few pixels
/// settle, which is what makes the dock read as a movement rather than a jump.
pub fn ease_out(t: f64) -> f64 {
    let inverse = 1.0 - t.clamp(0.0, 1.0);
    1.0 - inverse * inverse * inverse * inverse * inverse
}

/// How wide the pill is at step `step` of an animation of `steps` steps.
pub fn tween(from: f64, to: f64, step: u32, steps: u32) -> f64 {
    from + (to - from) * ease_out(f64::from(step) / f64::from(steps.max(1)))
}

fn overlay_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    app.get_webview_window("overlay")
        .ok_or_else(|| "Overlay window not found".to_string())
}

/// The monitor holding the middle of the capture region, so a region on a second
/// screen puts its plate on that screen too.
fn anchor_for(app: &AppHandle, region: [i32; 4]) -> Result<(OverlayAnchor, f64), String> {
    let window = overlay_window(app)?;
    let center_x = region[0] + region[2] / 2;
    let center_y = region[1] + region[3] / 2;
    let monitor = window
        .monitor_from_point(center_x as f64, center_y as f64)
        .map_err(|error| error.to_string())?
        .or(window.current_monitor().map_err(|error| error.to_string())?)
        .ok_or_else(|| "no monitor".to_string())?;
    let position = *monitor.position();
    let size = *monitor.size();
    Ok((
        OverlayAnchor {
            region,
            monitor_position: (position.x, position.y),
            monitor_size: (size.width, size.height),
        },
        monitor.scale_factor(),
    ))
}

pub fn place(
    app: &AppHandle,
    anchor: OverlayAnchor,
    scale: f64,
    height_css: f64,
) -> Result<(), String> {
    let window = overlay_window(app)?;
    let (position, size) = plate_bounds(anchor, scale, height_css);
    window.set_size(size).map_err(|error| error.to_string())?;
    window
        .set_position(position)
        .map_err(|error| error.to_string())?;
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
    Ok((anchor, scale))
}

pub fn hide(app: &AppHandle) -> Result<(), String> {
    overlay_window(app)?
        .hide()
        .map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    const MONITOR: OverlayAnchor = OverlayAnchor {
        region: [700, 700, 520, 90],
        monitor_position: (0, 0),
        monitor_size: (1920, 1080),
    };

    #[test]
    fn sits_below_the_region_when_the_screen_has_room() {
        let (position, size) = plate_bounds(MONITOR, 1.0, 100.0);
        assert_eq!(position.y, 700 + 90 + 12);
        assert_eq!(size.height, 100);
        // Centred on the region, which is already wider than the minimum.
        assert_eq!(size.width, 520);
        assert_eq!(position.x, 700);
    }

    #[test]
    fn sits_above_a_region_that_reaches_the_bottom_of_the_screen() {
        let anchor = OverlayAnchor {
            region: [700, 960, 520, 110],
            ..MONITOR
        };
        let (position, _) = plate_bounds(anchor, 1.0, 100.0);
        assert_eq!(position.y, 960 - 12 - 100);
    }

    #[test]
    fn a_narrow_region_still_gets_a_readable_plate() {
        let anchor = OverlayAnchor {
            region: [900, 900, 120, 60],
            ..MONITOR
        };
        let (position, size) = plate_bounds(anchor, 1.0, 100.0);
        assert_eq!(size.width, 480);
        // Still centred on the region rather than pinned to its left edge.
        assert_eq!(position.x + size.width as i32 / 2, 900 + 60);
    }

    #[test]
    fn stays_on_screen_when_the_region_hugs_an_edge() {
        let anchor = OverlayAnchor {
            region: [1850, 900, 60, 60],
            ..MONITOR
        };
        let (position, size) = plate_bounds(anchor, 1.0, 100.0);
        assert!(position.x >= 0);
        assert!(position.x + size.width as i32 <= 1920);
    }

    #[test]
    fn follows_the_region_onto_a_monitor_left_of_the_primary_one() {
        let anchor = OverlayAnchor {
            region: [-1500, 400, 600, 80],
            monitor_position: (-1920, 0),
            monitor_size: (1920, 1080),
        };
        let (position, _) = plate_bounds(anchor, 1.0, 100.0);
        assert_eq!(position.y, 400 + 80 + 12);
        assert!(position.x < 0);
    }

    #[test]
    fn scales_its_spacing_with_the_display() {
        let (position, size) = plate_bounds(MONITOR, 1.25, 100.0);
        assert_eq!(size.height, 125);
        assert_eq!(position.y, 700 + 90 + 15);
    }

    #[test]
    fn the_dock_sits_in_the_top_right_corner() {
        let (position, size) = dock_bounds((0, 0), (1920, 1080), 1.0);
        assert_eq!(size.width, 284);
        assert_eq!(position.y, 16);
        assert_eq!(position.x + size.width as i32, 1920 - 16);
    }

    #[test]
    fn the_bead_is_the_right_hand_end_of_the_dock() {
        let (position, size) = dock_bounds((0, 0), (1920, 1080), 1.0);
        let bead = pill_rect(position, size, 44);
        let full = pill_rect(position, size, size.width as i32);
        // Both end at the same edge, so opening the dock grows it leftwards
        // rather than moving it.
        assert_eq!(bead.0 + bead.2, full.0 + full.2);
        assert_eq!(bead.2, 44);
        assert!(bead.0 > full.0);
    }

    #[test]
    fn the_pointer_over_the_video_beside_the_bead_is_not_on_the_dock() {
        let (position, size) = dock_bounds((0, 0), (1920, 1080), 1.0);
        let bead = pill_rect(position, size, 44);
        assert!(rect_holds(bead, (bead.0 + 2, bead.1 + 2)));
        // The window reaches this far left even while closed; the clip is what
        // makes it not the dock.
        assert!(!rect_holds(bead, (position.x + 2, bead.1 + 2)));
    }

    #[test]
    fn a_pill_can_never_be_wider_than_the_window_holding_it() {
        let (position, size) = dock_bounds((0, 0), (1920, 1080), 1.0);
        let clamped = pill_rect(position, size, 9999);
        assert_eq!(clamped.2, size.width as i32);
        assert_eq!(clamped.0, position.x);
    }

    #[test]
    fn an_animation_starts_where_it_was_and_ends_where_it_was_asked_to() {
        assert_eq!(tween(44.0, 284.0, 0, 20), 44.0);
        assert_eq!(tween(44.0, 284.0, 20, 20), 284.0);
    }

    #[test]
    fn an_animation_covers_most_of_its_travel_early() {
        assert!(tween(44.0, 284.0, 10, 20) > (44.0 + 284.0) / 2.0);
    }

    #[test]
    fn the_dock_follows_the_monitor_it_is_on() {
        let (position, size) = dock_bounds((-1920, 0), (1920, 1080), 1.0);
        assert_eq!(position.x + size.width as i32, -1920 + 1920 - 16);
    }

    #[test]
    fn a_region_filling_the_screen_leaves_the_plate_on_the_bottom_edge() {
        let anchor = OverlayAnchor {
            region: [0, 0, 1920, 1080],
            ..MONITOR
        };
        let (position, size) = plate_bounds(anchor, 1.0, 100.0);
        assert_eq!(position.y + size.height as i32, 1080 - 8);
    }
}
