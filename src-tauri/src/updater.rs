use serde::Serialize;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;
use tauri::AppHandle;
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
    store_update_available: bool,
    portable_update_version: Option<String>,
    reason: Option<&'static str>,
}

fn updater(
    app: &AppHandle,
    timeout: Duration,
) -> Result<(Option<Updater>, Option<&'static str>), String> {
    if cfg!(feature = "microsoft-store") {
        return Ok((
            None,
            Some("Microsoft Store manages updates for this installation."),
        ));
    }
    if cfg!(debug_assertions) {
        return Ok((None, Some("Update checks are available in release builds.")));
    }
    if is_portable()? {
        return Ok((
            None,
            Some("Portable copies are updated from GitHub Releases."),
        ));
    }
    let Some(public_key) = PUBLIC_KEY.filter(|key| !key.trim().is_empty()) else {
        return Ok((None, Some("Updates are not configured for this build.")));
    };
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

fn is_portable() -> Result<bool, String> {
    let executable = std::env::current_exe().map_err(|error| error.to_string())?;
    Ok(executable
        .parent()
        .is_some_and(|directory| directory.join("release.json").is_file()))
}

#[tauri::command]
pub(crate) async fn check_app_update(app: AppHandle) -> Result<UpdateCheck, String> {
    let current_version = app.package_info().version.to_string();
    #[cfg(feature = "microsoft-store")]
    {
        check_store_update(&app, current_version).await
    }
    #[cfg(not(feature = "microsoft-store"))]
    if !cfg!(debug_assertions) && is_portable()? {
        super::portable_updates::check(app.package_info().version.clone())
            .await
            .map(|portable_update_version| UpdateCheck {
                enabled: true,
                current_version,
                available_version: None,
                store_update_available: false,
                portable_update_version,
                reason: None,
            })
    } else {
        check_github_update(&app, current_version).await
    }
}

#[cfg(feature = "microsoft-store")]
async fn check_store_update(
    app: &AppHandle,
    current_version: String,
) -> Result<UpdateCheck, String> {
    let store_update_available =
        tokio::time::timeout(Duration::from_secs(15), super::store::update_available(app))
            .await
            .ok()
            .and_then(Result::ok)
            .ok_or("Could not check Microsoft Store for updates. Try again later.")?;
    Ok(UpdateCheck {
        enabled: true,
        current_version,
        available_version: None,
        store_update_available,
        portable_update_version: None,
        reason: None,
    })
}

#[cfg(not(feature = "microsoft-store"))]
async fn check_github_update(
    app: &AppHandle,
    current_version: String,
) -> Result<UpdateCheck, String> {
    let (updater, reason) = updater(app, Duration::from_secs(20))?;
    let Some(updater) = updater else {
        return Ok(UpdateCheck {
            enabled: false,
            current_version,
            available_version: None,
            store_update_available: false,
            portable_update_version: None,
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
        store_update_available: false,
        portable_update_version: None,
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

#[tauri::command]
pub(crate) async fn open_update_page(portable_version: Option<String>) -> Result<(), String> {
    #[cfg(not(feature = "microsoft-store"))]
    {
        if !cfg!(debug_assertions) && is_portable()? {
            return super::portable_updates::open_release(portable_version.as_deref()).await;
        }
        Err("Could not open GitHub Releases.".to_string())
    }
    #[cfg(feature = "microsoft-store")]
    {
        if portable_version.is_some() {
            return Err("Could not open Microsoft Store.".to_string());
        }
        if matches!(
            tokio::time::timeout(Duration::from_secs(15), super::store::open_listing()).await,
            Ok(Ok(true))
        ) {
            return Ok(());
        }
        Err("Could not open Microsoft Store.".to_string())
    }
}
