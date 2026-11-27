//! Keep the Store installation's writable data in its own Windows package.
use std::path::PathBuf;
use windows::Storage::ApplicationData;

pub(crate) fn initialize() -> windows::core::Result<()> {
    let root = PathBuf::from(
        ApplicationData::Current()?
            .LocalFolder()?
            .Path()?
            .to_os_string(),
    );
    // Set before Tauri creates threads or WebView2 starts. All backend children
    // inherit the same profile, including embedded Python and Meowcal Core.
    std::env::set_var("APPDATA", &root);
    std::env::set_var("MEOCOSUB2_DISTRIBUTION", "store");
    std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", root.join("WebView2"));
    std::env::set_var("MEOWCAL_CORE_STORAGE_ROOT", root.join("Core"));
    Ok(())
}

const STORE_PRODUCT_URI: &str = "ms-windows-store://pdp/?ProductId=9NH782JNLWJP";

pub(crate) async fn update_available(app: &tauri::AppHandle) -> Result<bool, String> {
    use tauri::Manager;
    use windows::{
        core::Interface, ApplicationModel::Package, Services::Store::StoreContext,
        Win32::UI::Shell::IInitializeWithWindow,
    };

    // The Store requires the STA UI thread and an owner HWND for desktop apps.
    // Start the WinRT query there, then await it off the UI thread.
    let ui_app = app.clone();
    let (sender, receiver) = tokio::sync::oneshot::channel();
    app.run_on_main_thread(move || {
        let start = || -> Result<_, String> {
            let window = ui_app.get_webview_window("main").ok_or("Studio not open")?;
            let hwnd = window.hwnd().map_err(|error| error.to_string())?;
            let operation = || -> windows::core::Result<_> {
                let family = Package::Current()?.Id()?.FamilyName()?;
                let context = StoreContext::GetDefault()?;
                let owner: IInitializeWithWindow = context.cast()?;
                // The handle belongs to our live Studio window on this thread.
                unsafe { owner.Initialize(hwnd)? };
                Ok((family, context.GetAppAndOptionalStorePackageUpdatesAsync()?))
            };
            operation().map_err(|error| error.to_string())
        };
        let _ = sender.send(start());
    })
    .map_err(|error| error.to_string())?;
    let (current, operation) = receiver.await.map_err(|error| error.to_string())??;
    let matches_current_package = async {
        let updates = operation.await?;
        for index in 0..updates.Size()? {
            let package = updates.GetAt(index)?.Package()?;
            if package.Id()?.FamilyName()? == current {
                return Ok(true);
            }
        }
        Ok(false)
    };
    matches_current_package
        .await
        .map_err(|error: windows::core::Error| error.to_string())
}

pub(crate) async fn open_listing() -> windows::core::Result<bool> {
    use windows::{core::HSTRING, Foundation::Uri, System::Launcher};

    let uri = Uri::CreateUri(&HSTRING::from(STORE_PRODUCT_URI))?;
    Launcher::LaunchUriAsync(&uri)?.await
}
