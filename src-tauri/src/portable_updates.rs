use semver::Version;
use serde::Deserialize;
use std::time::Duration;

const API: &str = "https://api.github.com/repos/PeterShanxin/Meowcal-Sub-2/releases/latest";
const TAG_PAGE: &str = "https://github.com/PeterShanxin/Meowcal-Sub-2/releases/tag";
const CHECK_ERROR: &str = "Could not check GitHub for portable updates. Try again later.";
const OPEN_ERROR: &str = "Could not open GitHub Releases.";

#[derive(Deserialize)]
struct Release {
    tag_name: String,
    draft: bool,
    prerelease: bool,
    assets: Vec<Asset>,
}

#[derive(Deserialize)]
struct Asset {
    name: String,
    state: String,
}

fn stable_version(raw: &str) -> Option<Version> {
    let version = Version::parse(raw).ok()?;
    (version.pre.is_empty() && version.build.is_empty() && version.to_string() == raw)
        .then_some(version)
}

fn portable_update(release: Release, current: &Version, arch: &str) -> Option<String> {
    if release.draft || release.prerelease {
        return None;
    }
    let version = stable_version(release.tag_name.strip_prefix('v')?)?;
    let name = format!("meowcal-sub-2-v{version}-windows-{arch}-portable.zip");
    (version > *current
        && release
            .assets
            .iter()
            .any(|asset| asset.name == name && asset.state == "uploaded"))
    .then(|| version.to_string())
}

pub(crate) async fn check(current: Version) -> Result<Option<String>, String> {
    let arch = match std::env::consts::ARCH {
        "aarch64" => "arm64",
        "x86_64" => "x64",
        _ => return Ok(None),
    };
    let result = async {
        let response = reqwest::Client::builder()
            .user_agent("Meowcal-Sub-2-portable-updates")
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(15))
            .build()?
            .get(API)
            .send()
            .await?;
        response.error_for_status()?.json::<Release>().await
    }
    .await
    .map_err(|_| CHECK_ERROR.to_string())?;
    Ok(portable_update(result, &current, arch))
}

pub(crate) async fn open_release(raw: Option<&str>) -> Result<(), String> {
    use windows::{core::HSTRING, Foundation::Uri, System::Launcher};
    let version = raw.and_then(stable_version).ok_or(OPEN_ERROR)?;
    let uri =
        Uri::CreateUri(&HSTRING::from(format!("{TAG_PAGE}/v{version}"))).map_err(|_| OPEN_ERROR)?;
    let operation = Launcher::LaunchUriAsync(&uri).map_err(|_| OPEN_ERROR)?;
    if matches!(
        tokio::time::timeout(Duration::from_secs(15), operation).await,
        Ok(Ok(true))
    ) {
        Ok(())
    } else {
        Err(OPEN_ERROR.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn release(tag: &str, name: &str) -> Release {
        Release {
            tag_name: tag.into(),
            draft: false,
            prerelease: false,
            assets: vec![Asset {
                name: name.into(),
                state: "uploaded".into(),
            }],
        }
    }

    #[test]
    fn checks_only_newer_stable_releases_with_the_matching_portable_zip() {
        let current = Version::new(0, 4, 0);
        let zip = "meowcal-sub-2-v0.4.1-windows-arm64-portable.zip";
        assert_eq!(
            portable_update(release("v0.4.1", zip), &current, "arm64").as_deref(),
            Some("0.4.1")
        );
        assert_eq!(
            portable_update(release("v0.4.1", zip), &current, "x64"),
            None
        );
        assert_eq!(
            portable_update(
                release("v0.4.1", "meowcal-sub-2-v0.4.1-windows-arm64-setup.exe"),
                &current,
                "arm64"
            ),
            None
        );
        assert_eq!(
            portable_update(
                release("v0.4.0", "meowcal-sub-2-v0.4.0-windows-arm64-portable.zip"),
                &current,
                "arm64"
            ),
            None
        );
        assert_eq!(
            portable_update(release("v0.4.1-beta", zip), &current, "arm64"),
            None
        );
        let mut draft = release("v0.4.1", zip);
        draft.draft = true;
        assert_eq!(portable_update(draft, &current, "arm64"), None);
        assert!(stable_version("../../settings").is_none());
    }
}
