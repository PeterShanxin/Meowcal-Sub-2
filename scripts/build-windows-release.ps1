[CmdletBinding()]
param(
    [ValidateSet('auto', 'x64', 'arm64')][string]$Architecture = 'auto',
    [string]$Python = 'python',
    [string]$Tag,
    [switch]$SignedUpdater
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repositoryRoot = Split-Path -Parent $PSScriptRoot
if ($Architecture -eq 'auto') {
    $Architecture = switch ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture) {
        'Arm64' { 'arm64' }
        'X64' { 'x64' }
        default { throw 'Release builds require Windows x64 or ARM64.' }
    }
}
$target = if ($Architecture -eq 'arm64') { 'aarch64-pc-windows-msvc' } else { 'x86_64-pc-windows-msvc' }
$config = Get-Content (Join-Path $repositoryRoot 'src-tauri/tauri.conf.json') -Raw | ConvertFrom-Json
$version = $config.version
$versionCheck = @((Join-Path $PSScriptRoot 'check_app_version.py'))
if ($Tag) { $versionCheck += @('--tag', $Tag, '--require-head-tag') }
& $Python @versionCheck
if ($LASTEXITCODE -ne 0) { throw 'App manifests or release tag do not match.' }
if ($SignedUpdater) {
    if (-not $Tag) { throw 'Signed updater builds require a release tag at HEAD.' }
    $workingChanges = git -C $repositoryRoot status --porcelain
    if ($LASTEXITCODE -ne 0 -or $workingChanges) {
        throw 'Signed updater builds require a clean tagged checkout.'
    }
    if ([string]::IsNullOrWhiteSpace($env:TAURI_SIGNING_PRIVATE_KEY) -or
        [string]::IsNullOrWhiteSpace($env:MEOWCAL_UPDATER_PUBLIC_KEY)) {
        throw 'Signed updater builds require TAURI_SIGNING_PRIVATE_KEY and MEOWCAL_UPDATER_PUBLIC_KEY.'
    }
}
& $Python (Join-Path $PSScriptRoot 'update_branding.py')
if ($LASTEXITCODE -ne 0) { throw "Banner generation failed: $LASTEXITCODE" }
$releaseName = "meowcal-sub-2-v$version-windows-$Architecture"
$distribution = Join-Path $repositoryRoot 'dist'
$portable = Join-Path $distribution $releaseName
if (Test-Path -LiteralPath $portable) {
    throw "Release staging directory already exists; move it aside before rebuilding: $portable"
}
& (Join-Path $PSScriptRoot 'fetch-meowcal-core.ps1') -Architecture $Architecture -UsePrepared
npm --prefix (Join-Path $repositoryRoot 'src/meocosub2/overlay/ui') run build
if ($LASTEXITCODE -ne 0) { throw "Studio build failed: $LASTEXITCODE" }
& (Join-Path $PSScriptRoot 'prepare-python-backend.ps1') -Architecture $Architecture -Python $Python
& $Python (Join-Path $PSScriptRoot 'collect-third-party-notices.py')
if ($LASTEXITCODE -ne 0) { throw "Third-party notice collection failed: $LASTEXITCODE" }

Push-Location (Join-Path $repositoryRoot 'src-tauri')
$previousRustFlags = $env:CARGO_ENCODED_RUSTFLAGS
$previousBuildJobs = $env:CARGO_BUILD_JOBS
$previousUpdaterPublicKey = $env:MEOWCAL_UPDATER_PUBLIC_KEY
try {
    if (-not $SignedUpdater) { Remove-Item Env:MEOWCAL_UPDATER_PUBLIC_KEY -ErrorAction SilentlyContinue }
    if (-not $env:CARGO_BUILD_JOBS) { $env:CARGO_BUILD_JOBS = '1' }
    $remap = "--remap-path-prefix=$repositoryRoot=."
    $cargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } else { Join-Path $env:USERPROFILE '.cargo' }
    $remap += [char]31 + "--remap-path-prefix=$cargoHome=/cargo"
    $rustSysroot = rustc --print sysroot
    if ($LASTEXITCODE -ne 0) { throw 'Could not locate the Rust toolchain for path remapping.' }
    $remap += [char]31 + "--remap-path-prefix=$rustSysroot=/rust-toolchain"
    $env:CARGO_ENCODED_RUSTFLAGS = if ($previousRustFlags) {
        $previousRustFlags + [char]31 + $remap
    } else { $remap }
    $tauriConfigs = @('--config', 'tauri.release.conf.json')
    if ($SignedUpdater) {
        $updaterKeyConfig = @{ plugins = @{ updater = @{ pubkey = $env:MEOWCAL_UPDATER_PUBLIC_KEY } } } |
            ConvertTo-Json -Compress -Depth 4
        $tauriConfigs += @('--config', 'tauri.updater.conf.json', '--config', $updaterKeyConfig)
    }
    npx --yes @tauri-apps/cli@2.11.4 build --target $target --features custom-protocol @tauriConfigs
    if ($LASTEXITCODE -ne 0) { throw "Tauri release build failed: $LASTEXITCODE" }
} finally {
    $env:CARGO_ENCODED_RUSTFLAGS = $previousRustFlags
    $env:CARGO_BUILD_JOBS = $previousBuildJobs
    $env:MEOWCAL_UPDATER_PUBLIC_KEY = $previousUpdaterPublicKey
    Pop-Location
}

$targetRoot = if ($env:CARGO_TARGET_DIR) { $env:CARGO_TARGET_DIR } else { Join-Path $repositoryRoot 'src-tauri/target' }
$releaseDirectory = Join-Path $targetRoot "$target/release"
New-Item -ItemType Directory -Path $portable -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $releaseDirectory 'meowcal-sub-2-shell.exe') -Destination (Join-Path $portable 'Meowcal Sub 2.exe')
Copy-Item -LiteralPath (Join-Path $repositoryRoot 'src-tauri/resources/backend') -Destination $portable -Recurse
New-Item -ItemType Directory -Path (Join-Path $portable 'core') | Out-Null
foreach ($name in @('meowcal-core.exe', 'meowcal-core.json', 'LICENSE')) {
    Copy-Item -LiteralPath (Join-Path $repositoryRoot "src-tauri/resources/core/$name") -Destination (Join-Path $portable 'core')
}
Copy-Item -LiteralPath (Join-Path $repositoryRoot 'LICENSE') -Destination $portable
Copy-Item -LiteralPath (Join-Path $repositoryRoot 'output/third-party-licenses') -Destination $portable -Recurse
$commit = git -C $repositoryRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Could not resolve release source commit.' }
$workingChanges = git -C $repositoryRoot status --porcelain
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect release source state.' }
@{ version = $version; architecture = $Architecture; sourceCommit = $commit; sourceDirty = [bool]$workingChanges } |
    ConvertTo-Json | Set-Content (Join-Path $portable 'release.json') -Encoding utf8
& $Python (Join-Path $PSScriptRoot 'check_windows_package.py') $portable $Architecture
if ($LASTEXITCODE -ne 0) { throw "Windows package validation failed: $LASTEXITCODE" }
& $Python (Join-Path $PSScriptRoot 'smoke_packaged_backend.py') $portable
if ($LASTEXITCODE -ne 0) { throw "Packaged backend smoke failed: $LASTEXITCODE" }
Compress-Archive -LiteralPath $portable -DestinationPath (Join-Path $distribution "$releaseName-portable.zip") -Force
$installers = @(Get-ChildItem -Path (Join-Path $releaseDirectory 'bundle/nsis') -Filter '*-setup.exe')
if ($installers.Count -ne 1) { throw 'Expected exactly one NSIS installer.' }
Copy-Item -LiteralPath $installers[0].FullName -Destination (Join-Path $distribution "$releaseName-setup.exe")
$artifacts = @("$releaseName-portable.zip", "$releaseName-setup.exe")
if ($SignedUpdater) {
    $signature = "$($installers[0].FullName).sig"
    if (-not (Test-Path -LiteralPath $signature -PathType Leaf) -or
        [string]::IsNullOrWhiteSpace((Get-Content -LiteralPath $signature -Raw))) {
        throw 'Signed NSIS installer is missing its updater signature.'
    }
    cargo run --quiet --locked --manifest-path (Join-Path $repositoryRoot 'src-tauri/Cargo.toml') `
        --example verify_update_signature -- $installers[0].FullName $signature
    if ($LASTEXITCODE -ne 0) { throw 'Updater signature does not match the embedded public key.' }
    $signatureName = "$releaseName-setup.exe.sig"
    Copy-Item -LiteralPath $signature -Destination (Join-Path $distribution $signatureName)
    $artifacts += $signatureName
}
$checksums = foreach ($artifact in $artifacts) {
    $hash = (Get-FileHash -LiteralPath (Join-Path $distribution $artifact) -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $artifact"
}
$checksums | Set-Content (Join-Path $distribution "$releaseName-SHA256SUMS.txt") -Encoding ascii
Write-Host "Release artifacts are ready in $distribution. Native Windows acceptance is still required before publishing."
