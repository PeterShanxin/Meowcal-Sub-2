[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$fetchScript = Join-Path $repositoryRoot "scripts\fetch-meowcal-core.ps1"
$writeLockScript = Join-Path $repositoryRoot "scripts\write-meowcal-core-lock.ps1"
$temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) (
    "meowcal-core-consumer-tests-" + [guid]::NewGuid().ToString("N")
)

function Assert-Throws {
    param([scriptblock]$Action, [string]$ExpectedSubstring)
    try {
        & $Action
    } catch {
        if ($_.Exception.Message -notlike "*$ExpectedSubstring*") {
            throw "Expected an error containing '$ExpectedSubstring', got '$($_.Exception.Message)'."
        }
        return
    }
    throw "Expected an error containing '$ExpectedSubstring', but the action succeeded."
}

function New-TestPe {
    param([Parameter(Mandatory)][string]$Path, [string]$Architecture = "x64")

    $bytes = [byte[]]::new(512)
    $bytes[0] = 0x4D
    $bytes[1] = 0x5A
    [BitConverter]::GetBytes([uint32]0x80).CopyTo($bytes, 0x3C)
    [BitConverter]::GetBytes([uint32]0x00004550).CopyTo($bytes, 0x80)
    $machine = if ($Architecture -eq "arm64") { [uint16]0xAA64 } else { [uint16]0x8664 }
    [BitConverter]::GetBytes($machine).CopyTo($bytes, 0x84)
    [IO.File]::WriteAllBytes($Path, $bytes)
}

function New-CoreArchive {
    param(
        [Parameter(Mandatory)][string]$Path,
        [string]$Version = "0.1.0",
        [int]$ApiVersion = 1,
        [string]$Architecture = "x64",
        [string]$PeArchitecture = $Architecture,
        [switch]$CorruptExecutableHash,
        [switch]$CorruptLicenseHash
    )
    $staging = "$Path.staging"
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    try {
        $binary = Join-Path $staging "meowcal-core.exe"
        New-TestPe -Path $binary -Architecture $PeArchitecture
        $binaryHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $binary).Hash.ToLowerInvariant()
        if ($CorruptExecutableHash) { $binaryHash = "e" * 64 }
        $licensePath = Join-Path $staging "LICENSE"
        [IO.File]::WriteAllText($licensePath, "test license`n")
        $licenseHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $licensePath).Hash.ToLowerInvariant()
        if ($CorruptLicenseHash) { $licenseHash = "d" * 64 }
        $metadata = [ordered]@{
            schemaVersion = 1
            coreVersion = $Version
            apiVersion = $ApiVersion
            os = "windows"
            architecture = $Architecture
            executable = "meowcal-core.exe"
            executableSha256 = $binaryHash
            license = "LICENSE"
            licenseSha256 = $licenseHash
        }
        [IO.File]::WriteAllText(
            (Join-Path $staging "meowcal-core.json"),
            (($metadata | ConvertTo-Json) + "`n"),
            [Text.UTF8Encoding]::new($false)
        )
        Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $Path -Force
    } finally {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function New-CoreLock {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$X64Sha256,
        [string]$Version = "0.1.0",
        [string]$Arm64Sha256 = ("a" * 64)
    )
    $lock = [ordered]@{
        schemaVersion = 1
        repository = "PeterShanxin/Meowcal-Sub"
        tag = "core-v$Version"
        coreVersion = $Version
        apiVersion = 1
        architectures = [ordered]@{
            x64 = [ordered]@{
                asset = "meowcal-core-v$Version-windows-x64.zip"
                sha256 = $X64Sha256
            }
            arm64 = [ordered]@{
                asset = "meowcal-core-v$Version-windows-arm64.zip"
                sha256 = $Arm64Sha256
            }
        }
    }
    [IO.File]::WriteAllText(
        $Path,
        (($lock | ConvertTo-Json -Depth 5) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
}

New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
$incomingCoreArchive = $env:MEOWCAL_CORE_ARCHIVE
$incomingCoreLock = $env:MEOWCAL_CORE_LOCK
try {
    $env:MEOWCAL_CORE_ARCHIVE = $null
    $env:MEOWCAL_CORE_LOCK = $null
    $archive = Join-Path $temporaryDirectory "candidate.zip"
    New-CoreArchive -Path $archive
    $archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    $lockPath = Join-Path $temporaryDirectory "lock.json"
    $x64Checksum = Join-Path $temporaryDirectory "x64.sha256"
    $arm64Checksum = Join-Path $temporaryDirectory "arm64.sha256"
    [IO.File]::WriteAllText(
        $x64Checksum,
        "$archiveHash  meowcal-core-v0.1.0-windows-x64.zip`n"
    )
    [IO.File]::WriteAllText(
        $arm64Checksum,
        "$('a' * 64)  meowcal-core-v0.1.0-windows-arm64.zip`n"
    )
    & $writeLockScript -Version 0.1.0 -X64ChecksumPath $x64Checksum `
        -Arm64ChecksumPath $arm64Checksum -OutputPath $lockPath | Out-Null
    $destination = Join-Path $temporaryDirectory "installed\meowcal-core.exe"

    $previousArchive = $env:MEOWCAL_CORE_ARCHIVE
    $previousLock = $env:MEOWCAL_CORE_LOCK
    try {
        $env:MEOWCAL_CORE_ARCHIVE = $archive
        $env:MEOWCAL_CORE_LOCK = $lockPath
        $result = & $fetchScript -Architecture x64 -DestinationPath $destination -Offline
    } finally {
        $env:MEOWCAL_CORE_ARCHIVE = $previousArchive
        $env:MEOWCAL_CORE_LOCK = $previousLock
    }
    if ($result.ArchiveSha256 -ne $archiveHash -or
        -not (Test-Path -LiteralPath $destination -PathType Leaf)) {
        throw "Explicit local archive preparation did not install the validated Core executable."
    }
    $installedMetadataPath = Join-Path (Split-Path -Parent $destination) "meowcal-core.json"
    $installedLicensePath = Join-Path (Split-Path -Parent $destination) "LICENSE"
    if ($result.MetadataPath -ne $installedMetadataPath -or
        $result.LicensePath -ne $installedLicensePath -or
        -not (Test-Path -LiteralPath $installedMetadataPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $installedLicensePath -PathType Leaf)) {
        throw "Core preparation did not retain the validated metadata and license."
    }
    $installedMetadata = Get-Content -LiteralPath $installedMetadataPath -Raw | ConvertFrom-Json
    if ($installedMetadata.executableSha256 -ne
            (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant() -or
        $installedMetadata.licenseSha256 -ne
            (Get-FileHash -Algorithm SHA256 -LiteralPath $installedLicensePath).Hash.ToLowerInvariant()) {
        throw "Installed Core resource hashes do not match its retained metadata."
    }

    $wrongHashLock = Join-Path $temporaryDirectory "wrong-hash.json"
    New-CoreLock -Path $wrongHashLock -X64Sha256 ("b" * 64)
    Assert-Throws {
        & $fetchScript -Architecture x64 -LockPath $wrongHashLock `
            -ArchivePath $archive -DestinationPath $destination -Offline
    } "archive SHA-256 mismatch"

    $wrongVersionArchive = Join-Path $temporaryDirectory "wrong-version.zip"
    New-CoreArchive -Path $wrongVersionArchive -Version 0.2.0
    $wrongVersionLock = Join-Path $temporaryDirectory "wrong-version.json"
    New-CoreLock -Path $wrongVersionLock `
        -X64Sha256 (Get-FileHash -Algorithm SHA256 $wrongVersionArchive).Hash.ToLowerInvariant()
    Assert-Throws {
        & $fetchScript -Architecture x64 -LockPath $wrongVersionLock `
            -ArchivePath $wrongVersionArchive -DestinationPath $destination -Offline
    } "version does not match"

    $wrongArchitectureArchive = Join-Path $temporaryDirectory "wrong-architecture.zip"
    New-CoreArchive -Path $wrongArchitectureArchive -Architecture arm64
    $wrongArchitectureLock = Join-Path $temporaryDirectory "wrong-architecture.json"
    New-CoreLock -Path $wrongArchitectureLock `
        -X64Sha256 (Get-FileHash -Algorithm SHA256 $wrongArchitectureArchive).Hash.ToLowerInvariant()
    Assert-Throws {
        & $fetchScript -Architecture x64 -LockPath $wrongArchitectureLock `
            -ArchivePath $wrongArchitectureArchive -DestinationPath $destination -Offline
    } "architecture does not match"

    $corruptArchive = Join-Path $temporaryDirectory "corrupt.zip"
    New-CoreArchive -Path $corruptArchive -CorruptExecutableHash
    $corruptLock = Join-Path $temporaryDirectory "corrupt.json"
    New-CoreLock -Path $corruptLock `
        -X64Sha256 (Get-FileHash -Algorithm SHA256 $corruptArchive).Hash.ToLowerInvariant()
    Assert-Throws {
        & $fetchScript -Architecture x64 -LockPath $corruptLock `
            -ArchivePath $corruptArchive -DestinationPath $destination -Offline
    } "executable SHA-256 mismatch"

    $corruptLicenseArchive = Join-Path $temporaryDirectory "corrupt-license.zip"
    New-CoreArchive -Path $corruptLicenseArchive -CorruptLicenseHash
    $corruptLicenseLock = Join-Path $temporaryDirectory "corrupt-license.json"
    New-CoreLock -Path $corruptLicenseLock `
        -X64Sha256 (Get-FileHash -Algorithm SHA256 $corruptLicenseArchive).Hash.ToLowerInvariant()
    Assert-Throws {
        & $fetchScript -Architecture x64 -LockPath $corruptLicenseLock `
            -ArchivePath $corruptLicenseArchive -DestinationPath $destination -Offline
    } "license SHA-256 mismatch"

    $swappedMachineArchive = Join-Path $temporaryDirectory "swapped-machine.zip"
    New-CoreArchive -Path $swappedMachineArchive -PeArchitecture arm64
    $swappedMachineLock = Join-Path $temporaryDirectory "swapped-machine.json"
    New-CoreLock -Path $swappedMachineLock `
        -X64Sha256 (Get-FileHash -Algorithm SHA256 $swappedMachineArchive).Hash.ToLowerInvariant()
    Assert-Throws {
        & $fetchScript -Architecture x64 -LockPath $swappedMachineLock `
            -ArchivePath $swappedMachineArchive -DestinationPath $destination -Offline
    } "PE machine"

    $placeholderLock = Join-Path $temporaryDirectory "placeholder.json"
    New-CoreLock -Path $placeholderLock -X64Sha256 ("0" * 64)
    Assert-Throws {
        & $fetchScript -Architecture x64 -LockPath $placeholderLock `
            -ArchivePath $archive -DestinationPath $destination -Offline
    } "real lowercase digest"

    Assert-Throws {
        & $fetchScript -Architecture x64 -LockPath $lockPath `
            -ArchivePath (Join-Path $temporaryDirectory "missing.zip") `
            -DestinationPath $destination -Offline
    } "archive is missing"
    Assert-Throws {
        & $fetchScript -Architecture x64 -LockPath $lockPath `
            -DestinationPath $destination -Offline
    } "requires -ArchivePath or MEOWCAL_CORE_ARCHIVE"

    [IO.File]::WriteAllText(
        $x64Checksum,
        "$('0' * 64)  meowcal-core-v0.1.0-windows-x64.zip`n"
    )
    Assert-Throws {
        & $writeLockScript -Version 0.1.0 -X64ChecksumPath $x64Checksum `
            -Arm64ChecksumPath $arm64Checksum -OutputPath $lockPath
    } "real lowercase SHA-256"

    $tauriConfig = Get-Content -LiteralPath (Join-Path $repositoryRoot "src-tauri\tauri.conf.json") -Raw
    $tauriConfigObject = $tauriConfig | ConvertFrom-Json
    if ($tauriConfig -notmatch 'beforeBuildCommand[^\r\n]+fetch-meowcal-core\.ps1' -or
        $tauriConfigObject.bundle.resources.'resources/core/meowcal-core.exe' -ne
            'core/meowcal-core.exe' -or
        $tauriConfigObject.bundle.resources.'resources/core/meowcal-core.json' -ne
            'core/meowcal-core.json' -or
        $tauriConfigObject.bundle.resources.'resources/core/LICENSE' -ne 'core/LICENSE') {
        throw "Tauri build must prepare and bundle the verified Core executable, metadata, and license."
    }
    $launcher = Get-Content -LiteralPath (Join-Path $repositoryRoot "run_app.vbs") -Raw
    if ($launcher -notmatch 'fetch-meowcal-core\.ps1' -or
        $launcher -notmatch 'corePath, _' -or
        $launcher -notmatch 'MEOWCAL_CORE_PROFILE"\) = "development"') {
        throw "The supported development launcher must prepare Core under the development profile."
    }

    $shellSource = Get-Content -LiteralPath (Join-Path $repositoryRoot "src-tauri\src\backend_process.rs") -Raw
    if ($shellSource -notmatch 'resource_dir\(\)' -or
        $shellSource -notmatch 'directory\.join\("core"\)\.join\("meowcal-core\.exe"\)' -or
        $shellSource -notmatch 'command\.env\("MEOWCAL_CORE_EXE", core_executable\)') {
        throw "The packaged shell must pass its bundled Core resource path to the Python backend."
    }

    $verifySource = Get-Content -LiteralPath (Join-Path $repositoryRoot "scripts\verify.ps1") -Raw
    if ($verifySource -notmatch 'MEOWCAL_CORE_EXE = \$CoreResource' -or
        $verifySource -notmatch 'test_real_core_process_handshake_and_status') {
        throw "The Rust stage must execute the real pinned Core consumer handshake."
    }

    $ciSource = Get-Content -LiteralPath (Join-Path $repositoryRoot ".github\workflows\windows-ci.yml") -Raw
    if ($ciSource -notmatch '(?s)verify-arm64:.*?CARGO_BUILD_JOBS: 1') {
        throw "The ARM64 CI gate must serialize its cold Rust build."
    }

    Write-Host "Core consumer package contract tests passed." -ForegroundColor Green
} finally {
    $env:MEOWCAL_CORE_ARCHIVE = $incomingCoreArchive
    $env:MEOWCAL_CORE_LOCK = $incomingCoreLock
    Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
