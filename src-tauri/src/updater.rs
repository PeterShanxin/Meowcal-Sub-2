use serde::Serialize;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;
use tauri::{AppHandle, Manager};
use tauri_plugin_updater::{Updater, UpdaterExt};
use url::Url;

const MANIFEST_URL: &str =
    "https://github.com/PeterShanxin/Meowcal-Sub-2/releases/latest/download/latest.json";
const PUBLIC_KEY: Option<&str> = option_env!("MEOWCAL_UPDATER_PUBLIC_KEY");
static INSTALLING: AtomicBool = AtomicBool::new(false);

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct UpdateCheck {
    enabled: bool,
    current_version: String,
    available_version: Option<String>,
    reason: Option<&'static str>,
}

fn updater(
    app: &AppHandle,
    timeout: Duration,
) -> Result<(Option<Updater>, Option<&'static str>), String> {
    if cfg!(debug_assertions) {
        return Ok((None, Some("Update checks are available in release builds.")));
    }
    let Some(public_key) = PUBLIC_KEY.filter(|key| !key.trim().is_empty()) else {
        return Ok((None, Some("Updates are not configured for this build.")));
    };
    let executable = std::env::current_exe().map_err(|error| error.to_string())?;
    if executable
        .parent()
        .is_some_and(|directory| directory.join("release.json").is_file())
    {
        return Ok((None, Some("Portable copies must be updated manually.")));
    }
    let endpoint = Url::parse(MANIFEST_URL).map_err(|error| error.to_string())?;
    let app_for_exit = app.clone();
    let builder = app
        .updater_builder()
        .pubkey(public_key)
        .endpoints(vec![endpoint])
        .map_err(|error| error.to_string())?
        .timeout(timeout)
        .on_before_exit(move || super::shutdown_owned_runtime(&app_for_exit));
    let updater = builder.build().map_err(|error| error.to_string())?;
    Ok((Some(updater), None))
}

#[tauri::command]
pub(crate) async fn check_app_update(app: AppHandle) -> Result<UpdateCheck, String> {
    let current_version = app.package_info().version.to_string();
    let (updater, reason) = updater(&app, Duration::from_secs(20))?;
    let Some(updater) = updater else {
        return Ok(UpdateCheck {
            enabled: false,
            current_version,
            available_version: None,
            reason,
        });
    };
    let available_version = updater
        .check()
        .await
        .map_err(|error| error.to_string())?
        .map(|update| update.version);
    Ok(UpdateCheck {
        enabled: true,
        current_version,
        available_version,
        reason: None,
    })
}

#[tauri::command]
pub(crate) async fn install_app_update(
    app: AppHandle,
    expected_version: String,
) -> Result<(), String> {
    if INSTALLING.swap(true, Ordering::AcqRel) {
        return Err("An update is already being installed.".to_string());
    }
    let result = install_checked_update(&app, &expected_version).await;
    INSTALLING.store(false, Ordering::Release);
    result
}

async fn install_checked_update(app: &AppHandle, expected_version: &str) -> Result<(), String> {
    let (updater, _) = updater(app, Duration::from_secs(600))?;
    let updater = updater.ok_or("Updates are unavailable for this build.")?;
    let update = updater
        .check()
        .await
        .map_err(|error| error.to_string())?
        .ok_or("No update is available.")?;
    if update.version != expected_version {
        return Err(format!(
            "Available version changed to {}; check again before installing.",
            update.version
        ));
    }
    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(|error| error.to_string())
}
