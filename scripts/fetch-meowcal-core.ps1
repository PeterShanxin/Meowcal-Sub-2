[CmdletBinding()]
param(
    [ValidateSet("auto", "x64", "arm64")]
    [string]$Architecture = "auto",
    [string]$LockPath,
    [string]$ArchivePath,
    [string]$DestinationPath,
    [switch]$Offline,
    [switch]$UsePrepared
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot

function Test-IsIntegerValue {
    param($Value, [Parameter(Mandatory)][long]$Expected)

    return ($Value -is [int] -or $Value -is [long]) -and $Value -eq $Expected
}

function Get-PeMachine {
    param([Parameter(Mandatory)][string]$Path)

    $stream = [IO.File]::OpenRead($Path)
    try {
        $reader = [IO.BinaryReader]::new($stream)
        try {
            if ($reader.ReadUInt16() -ne 0x5A4D -or $stream.Length -lt 0x40) {
                throw "Core executable is not a PE file."
            }
            $stream.Position = 0x3C
            $peOffset = $reader.ReadUInt32()
            if ($peOffset + 6 -gt $stream.Length) { throw "Core PE header is truncated." }
            $stream.Position = $peOffset
            if ($reader.ReadUInt32() -ne 0x00004550) { throw "Core PE signature is invalid." }
            return $reader.ReadUInt16()
        } finally { $reader.Dispose() }
    } finally { $stream.Dispose() }
}

if ($Architecture -eq "auto") {
    $Architecture = switch ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture) {
        "Arm64" { "arm64" }
        "X64" { "x64" }
        default { throw "Meowcal Core supports only Windows x64 and ARM64 hosts." }
    }
}
if (-not $LockPath) {
    $LockPath = if ($env:MEOWCAL_CORE_LOCK) {
        $env:MEOWCAL_CORE_LOCK
    } else {
        Join-Path $repositoryRoot "config\meowcal-core.lock.json"
    }
}
if (-not $DestinationPath) {
    $DestinationPath = Join-Path $repositoryRoot "src-tauri\resources\core\meowcal-core.exe"
}
if (-not $ArchivePath -and $env:MEOWCAL_CORE_ARCHIVE) {
    $ArchivePath = $env:MEOWCAL_CORE_ARCHIVE
}

if (-not (Test-Path -LiteralPath $LockPath -PathType Leaf)) {
    throw "Missing reviewed Core release lock: $LockPath"
}
$lock = Get-Content -LiteralPath $LockPath -Raw | ConvertFrom-Json
$expectedLockProperties = @(
    "schemaVersion", "repository", "tag", "coreVersion", "apiVersion", "architectures"
)
$lockProperties = @($lock.PSObject.Properties.Name)
if (@($lockProperties | Where-Object { $_ -notin $expectedLockProperties }).Count -ne 0 -or
    @($expectedLockProperties | Where-Object { $_ -notin $lockProperties }).Count -ne 0) {
    throw "Core release lock fields do not match schema 1."
}
if (-not (Test-IsIntegerValue -Value $lock.schemaVersion -Expected 1)) {
    throw "Unsupported Core release lock schema."
}
if ($lock.repository -ne "PeterShanxin/Meowcal-Sub") {
    throw "Core release lock must use PeterShanxin/Meowcal-Sub."
}
if ($lock.coreVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "Locked Core version must use major.minor.patch."
}
if (-not (Test-IsIntegerValue -Value $lock.apiVersion -Expected 1)) {
    throw "Locked Core API version must be 1."
}
if ($lock.tag -ne "core-v$($lock.coreVersion)") {
    throw "Core release tag must exactly match core-v$($lock.coreVersion)."
}

foreach ($lockedArchitecture in @("x64", "arm64")) {
    $entry = $lock.architectures.$lockedArchitecture
    if ($null -eq $entry) { throw "Core release lock is missing $lockedArchitecture." }
    $entryProperties = @($entry.PSObject.Properties.Name)
    if ($entryProperties.Count -ne 2 -or "asset" -notin $entryProperties -or
        "sha256" -notin $entryProperties) {
        throw "Core $lockedArchitecture lock must contain only asset and sha256."
    }
    $expectedAsset = "meowcal-core-v$($lock.coreVersion)-windows-$lockedArchitecture.zip"
    if ($entry.asset -ne $expectedAsset) {
        throw "Core $lockedArchitecture asset must be $expectedAsset."
    }
    if ($entry.sha256 -notmatch '^[0-9a-f]{64}$' -or $entry.sha256 -eq ("0" * 64)) {
        throw "Core $lockedArchitecture SHA-256 must be a real lowercase digest."
    }
}
$lockedArchitectures = @($lock.architectures.PSObject.Properties.Name)
if ($lockedArchitectures.Count -ne 2 -or
    @($lockedArchitectures | Where-Object { $_ -notin @("x64", "arm64") }).Count -ne 0) {
    throw "Core release lock architectures must contain only x64 and arm64."
}

$selected = $lock.architectures.$Architecture
$receiptPath = "$DestinationPath.receipt"
function Get-PreparedIdentity {
    $directory = Split-Path -Parent $DestinationPath
    $paths = @($LockPath, $DestinationPath, (Join-Path $directory "meowcal-core.json"),
        (Join-Path $directory "LICENSE"))
    $hashes = @($paths | ForEach-Object {
        (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant()
    })
    return (@($Architecture) + $hashes) -join "`n"
}
if ($UsePrepared -and (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
    try {
        if ([IO.File]::ReadAllText($receiptPath) -ceq (Get-PreparedIdentity)) {
            Write-Host "Using verified prepared Meowcal Core at $DestinationPath."
            return
        }
    } catch {
        Write-Verbose "Prepared Core resources need verification: $_"
    }
}
$temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) (
    "meowcal-core-fetch-" + [guid]::NewGuid().ToString("N")
)

try {
    New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
    if (-not $ArchivePath) {
        if ($Offline) {
            throw "Offline Core preparation requires -ArchivePath or MEOWCAL_CORE_ARCHIVE."
        }
        $ArchivePath = Join-Path $temporaryDirectory $selected.asset
        $uri = "https://github.com/$($lock.repository)/releases/download/$($lock.tag)/$($selected.asset)"
        Invoke-WebRequest -Uri $uri -OutFile $ArchivePath -TimeoutSec 120
    }
    if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
        throw "Core archive is missing: $ArchivePath"
    }

    $archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ArchivePath).Hash.ToLowerInvariant()
    if ($archiveHash -ne $selected.sha256) {
        throw "Core archive SHA-256 mismatch. Expected $($selected.sha256), got $archiveHash."
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $ArchivePath))
    try {
        $entries = @($zip.Entries)
        $entryNames = @($entries | ForEach-Object FullName)
        $expectedEntries = @("LICENSE", "meowcal-core.exe", "meowcal-core.json")
        $maxEntryBytes = 256MB
        $maxTotalBytes = 512MB
        [long]$totalUncompressedBytes = 0
        if ($entries.Count -ne $expectedEntries.Count -or
            @($entryNames | Where-Object { $_ -notin $expectedEntries }).Count -ne 0 -or
            @($expectedEntries | Where-Object { $_ -notin $entryNames }).Count -ne 0) {
            throw "Core archive must contain only LICENSE, meowcal-core.exe, and meowcal-core.json at its root."
        }
        foreach ($entry in $entries) {
            if ($entry.FullName -ne $entry.Name -or $entry.FullName.Contains("..")) {
                throw "Core archive contains an unsafe path: $($entry.FullName)"
            }
            if ($entry.Length -gt $maxEntryBytes) {
                throw "Core archive entry $($entry.Name) exceeds the 256 MiB extraction limit."
            }
            $totalUncompressedBytes += [long]$entry.Length
            if ($totalUncompressedBytes -gt $maxTotalBytes) {
                throw "Core archive exceeds the 512 MiB extraction limit."
            }
            if ($entry.Name -eq "meowcal-core.json" -and $entry.Length -gt 64KB) {
                throw "Core package metadata exceeds the 64 KiB runtime limit."
            }
        }
    } finally {
        $zip.Dispose()
    }

    [IO.Compression.ZipFile]::ExtractToDirectory(
        (Resolve-Path -LiteralPath $ArchivePath),
        $temporaryDirectory
    )
    $metadataPath = Join-Path $temporaryDirectory "meowcal-core.json"
    $binaryPath = Join-Path $temporaryDirectory "meowcal-core.exe"
    $licensePath = Join-Path $temporaryDirectory "LICENSE"
    $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
    $expectedMetadataProperties = @(
        "schemaVersion", "coreVersion", "apiVersion", "os", "architecture",
        "executable", "executableSha256", "license", "licenseSha256"
    )
    $metadataProperties = @($metadata.PSObject.Properties.Name)
    if (@($metadataProperties | Where-Object { $_ -notin $expectedMetadataProperties }).Count -ne 0 -or
        @($expectedMetadataProperties | Where-Object { $_ -notin $metadataProperties }).Count -ne 0) {
        throw "Core package metadata fields do not match schema 1."
    }
    if (-not (Test-IsIntegerValue -Value $metadata.schemaVersion -Expected 1)) {
        throw "Unsupported Core package metadata schema."
    }
    if ($metadata.coreVersion -ne $lock.coreVersion) { throw "Core package version does not match the lock." }
    if (-not (Test-IsIntegerValue -Value $metadata.apiVersion -Expected $lock.apiVersion)) {
        throw "Core package API version does not match the lock."
    }
    if ($metadata.os -ne "windows") { throw "Core package OS must be windows." }
    if ($metadata.architecture -ne $Architecture) { throw "Core package architecture does not match $Architecture." }
    if ($metadata.executable -ne "meowcal-core.exe") { throw "Core package executable name is invalid." }
    if ($metadata.executableSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Core executable SHA-256 must be lowercase hexadecimal."
    }
    if ($metadata.license -ne "LICENSE" -or $metadata.licenseSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Core package license metadata is invalid."
    }
    $binaryHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $binaryPath).Hash.ToLowerInvariant()
    if ($binaryHash -ne $metadata.executableSha256) {
        throw "Core executable SHA-256 mismatch. Expected $($metadata.executableSha256), got $binaryHash."
    }
    $licenseHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $licensePath).Hash.ToLowerInvariant()
    if ($licenseHash -ne $metadata.licenseSha256) {
        throw "Core license SHA-256 mismatch. Expected $($metadata.licenseSha256), got $licenseHash."
    }
    $expectedMachine = if ($Architecture -eq "arm64") { 0xAA64 } else { 0x8664 }
    $actualMachine = Get-PeMachine -Path $binaryPath
    if ($actualMachine -ne $expectedMachine) {
        throw ("Core executable PE machine 0x{0:X4} does not match {1}." -f $actualMachine, $Architecture)
    }

    $destinationDirectory = Split-Path -Parent $DestinationPath
    if ($destinationDirectory) {
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
    }
    $temporaryDestination = Join-Path $destinationDirectory (
        ".meowcal-core-" + [guid]::NewGuid().ToString("N") + ".exe"
    )
    $temporaryMetadata = "$temporaryDestination.json"
    $temporaryLicense = "$temporaryDestination.LICENSE"
    $metadataDestination = Join-Path $destinationDirectory "meowcal-core.json"
    $licenseDestination = Join-Path $destinationDirectory "LICENSE"
    try {
        Copy-Item -LiteralPath $binaryPath -Destination $temporaryDestination
        Copy-Item -LiteralPath $metadataPath -Destination $temporaryMetadata
        Copy-Item -LiteralPath $licensePath -Destination $temporaryLicense
        Move-Item -LiteralPath $temporaryLicense -Destination $licenseDestination -Force
        Move-Item -LiteralPath $temporaryMetadata -Destination $metadataDestination -Force
        Move-Item -LiteralPath $temporaryDestination -Destination $DestinationPath -Force
        [IO.File]::WriteAllText($receiptPath, (Get-PreparedIdentity))
    } finally {
        Remove-Item -LiteralPath $temporaryDestination -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $temporaryMetadata -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $temporaryLicense -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Prepared Meowcal Core $($lock.coreVersion) $Architecture at $DestinationPath."
    [pscustomobject]@{
        Version = $lock.coreVersion
        ApiVersion = $lock.apiVersion
        Architecture = $Architecture
        ArchiveSha256 = $archiveHash
        ExecutableSha256 = $binaryHash
        DestinationPath = $DestinationPath
        MetadataPath = $metadataDestination
        LicensePath = $licenseDestination
    }
} finally {
    Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
