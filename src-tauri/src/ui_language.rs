//! The interface language of what the shell draws itself: the tray menu, and the
//! saved choice the splash and capture selector read before the backend answers.

use tauri::menu::MenuItem;
use tauri::{AppHandle, Manager, Wry};

/// The saved preference: `system`, `en` or `zh-CN`. Pages resolve `system`
/// against the display language, as the studio does.
pub(crate) fn parse_ui_language(raw: &str) -> &'static str {
    let value: Option<toml::Value> = toml::from_str(raw).ok();
    match value
        .as_ref()
        .and_then(|value| value.get("ui"))
        .and_then(|ui| ui.get("language"))
        .and_then(|language| language.as_str())
    {
        Some("en") => "en",
        Some("zh-CN") => "zh-CN",
        _ => "system",
    }
}

/// Tray labels in the given locale: open, select area, stop, exit.
pub(crate) fn tray_labels(locale: &str) -> [&'static str; 4] {
    if locale == "zh-CN" {
        ["打开应用", "选择捕获区域", "停止翻译", "退出"]
    } else {
        [
            "Open App",
            "Select Capture Area",
            "Stop Translation",
            "Exit",
        ]
    }
}

/// The tray's items, kept so their labels can follow the studio's language.
pub(crate) struct TrayMenu(pub(crate) [MenuItem<Wry>; 4]);

#[tauri::command]
pub(crate) fn ui_language() -> &'static str {
    parse_ui_language(&std::fs::read_to_string(crate::config_path()).unwrap_or_default())
}

/// The studio resolves `system` to a locale, so the tray follows what it shows.
#[tauri::command]
pub(crate) fn set_tray_locale(app: AppHandle, locale: String) -> Result<(), String> {
    let menu = app.state::<TrayMenu>();
    for (item, label) in menu.0.iter().zip(tray_labels(&locale)) {
        item.set_text(label).map_err(|error| error.to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_saved_language_is_read_and_anything_else_follows_the_system() {
        assert_eq!(parse_ui_language("[ui]\nlanguage = \"zh-CN\"\n"), "zh-CN");
        assert_eq!(parse_ui_language("[ui]\nlanguage = \"en\"\n"), "en");
        assert_eq!(parse_ui_language("[ui]\nlanguage = \"fr\"\n"), "system");
        assert_eq!(parse_ui_language("[overlay]\nport = 8765\n"), "system");
        assert_eq!(parse_ui_language("[ui\nlanguage = \"en\""), "system");
    }

    #[test]
    fn the_tray_reads_chinese_only_for_a_chinese_locale() {
        assert_eq!(tray_labels("zh-CN")[3], "退出");
        assert_eq!(tray_labels("en")[0], "Open App");
        assert_eq!(tray_labels("system")[0], "Open App");
    }
}
