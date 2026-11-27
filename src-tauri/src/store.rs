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

pub(crate) async fn update_available() -> windows::core::Result<bool> {
    use windows::{ApplicationModel::Package, Services::Store::StoreContext};

    let current = Package::Current()?.Id()?.FamilyName()?;
    let operation = StoreContext::GetDefault()?.GetAppAndOptionalStorePackageUpdatesAsync()?;
    let updates = operation.await?;
    for index in 0..updates.Size()? {
        let package = updates.GetAt(index)?.Package()?;
        if package.Id()?.FamilyName()? == current {
            return Ok(true);
        }
    }
    Ok(false)
}

pub(crate) async fn open_listing() -> windows::core::Result<bool> {
    use windows::{core::HSTRING, Foundation::Uri, System::Launcher};

    let uri = Uri::CreateUri(&HSTRING::from(STORE_PRODUCT_URI))?;
    Launcher::LaunchUriAsync(&uri)?.await
}
