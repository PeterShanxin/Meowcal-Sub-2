[CmdletBinding()]
param(
    [string]$SourcePath,
    [string]$ConfigPath,
    [string]$DestinationPath,
    [switch]$ResolveCommit
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repositoryRoot "config\meowcal-core.candidate.json"
}
if (-not $DestinationPath) {
    $DestinationPath = Join-Path $repositoryRoot "src-tauri\resources\core\meowcal-core.exe"
}

. (Join-Path $PSScriptRoot "lib\CoreSchemaChecks.ps1")
. (Join-Path $PSScriptRoot "lib\CoreProcess.ps1")

function Invoke-GitText {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & git -C $sourceRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Core candidate git check failed: $(@($output) -join ' ')"
    }
    return (@($output) -join "`n").Trim()
}

function Get-PeMachine {
    param([Parameter(Mandatory)][string]$Path)

    $stream = [IO.File]::OpenRead($Path)
    try {
        $reader = [IO.BinaryReader]::new($stream)
        try {
            if ($stream.Length -lt 0x40 -or $reader.ReadUInt16() -ne 0x5A4D) {
                throw "Core candidate executable is not a PE file."
            }
            $stream.Position = 0x3C
            $peOffset = $reader.ReadUInt32()
            if ($peOffset + 6 -gt $stream.Length) {
                throw "Core candidate PE header is truncated."
            }
            $stream.Position = $peOffset
            if ($reader.ReadUInt32() -ne 0x00004550) {
                throw "Core candidate PE signature is invalid."
            }
            return $reader.ReadUInt16()
        } finally {
            $reader.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Core candidate pin is missing: $ConfigPath"
}
$pin = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$expectedPinProperties = @("schemaVersion", "repository", "commit", "coreVersion", "apiVersion")
$pinProperties = @($pin.PSObject.Properties.Name)
if (@($pinProperties | Where-Object { $_ -notin $expectedPinProperties }).Count -ne 0 -or
    @($expectedPinProperties | Where-Object { $_ -notin $pinProperties }).Count -ne 0) {
    throw "Core candidate pin fields do not match schema 1."
}
if (-not (Test-IsIntegerValue -Value $pin.schemaVersion -Expected 1)) {
    throw "Unsupported Core candidate pin schema."
}
if ($pin.repository -ne "PeterShanxin/Meowcal-Sub") {
    throw "Core candidate pin must use PeterShanxin/Meowcal-Sub."
}
if ($pin.commit -isnot [string] -or $pin.commit -notmatch '^[0-9a-f]{40}$') {
    throw "Core candidate commit must be an exact 40-character lowercase Git SHA."
}
if ($pin.coreVersion -isnot [string] -or $pin.coreVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "Core candidate version must use major.minor.patch."
}
if (-not (Test-IsIntegerValue -Value $pin.apiVersion -Expected 1)) {
    throw "Core candidate API version must be 1."
}
if ($ResolveCommit) {
    Write-Output $pin.commit
    return
}
if (-not $SourcePath -or -not (Test-Path -LiteralPath $SourcePath -PathType Container)) {
    throw "Core candidate source checkout is missing: $SourcePath"
}

$sourceRoot = (Resolve-Path -LiteralPath $SourcePath).Path
$head = Invoke-GitText -Arguments @("rev-parse", "HEAD")
if ($head -cne $pin.commit) {
    throw "Core candidate checkout HEAD '$head' does not match pinned commit '$($pin.commit)'."
}
$status = Invoke-GitText -Arguments @("status", "--porcelain=v1", "--untracked-files=all")
if ($status) {
    throw "Core candidate source checkout must be clean."
}

$coreRoot = Join-Path $sourceRoot "core"
$manifestPath = Join-Path $coreRoot "Cargo.toml"
$lockPath = Join-Path $coreRoot "Cargo.lock"
$licensePath = Join-Path $sourceRoot "LICENSE"
foreach ($requiredPath in @($manifestPath, $lockPath, $licensePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Core candidate source file is missing: $requiredPath"
    }
}
$manifestVersionMatch = [regex]::Match(
    (Get-Content -LiteralPath $manifestPath -Raw),
    '(?ms)^\[package\].*?^version\s*=\s*"(?<version>\d+\.\d+\.\d+)"'
)
if (-not $manifestVersionMatch.Success -or
    $manifestVersionMatch.Groups["version"].Value -ne $pin.coreVersion) {
    throw "Core candidate Cargo version does not match the pin."
}

$architecture = switch ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture) {
    "Arm64" { "arm64" }
    "X64" { "x64" }
    default { throw "Meowcal Core candidates support only Windows x64 and ARM64 hosts." }
}
$target = if ($architecture -eq "arm64") {
    "aarch64-pc-windows-msvc"
} else {
    "x86_64-pc-windows-msvc"
}
$targetDirectory = Join-Path $coreRoot "target"

Push-Location $coreRoot
$previousCargoBuildJobs = $env:CARGO_BUILD_JOBS
try {
    if ($architecture -eq "arm64" -and -not $env:CARGO_BUILD_JOBS) {
        $env:CARGO_BUILD_JOBS = "1"
    }
    & cargo build --locked --manifest-path Cargo.toml --target $target `
        --target-dir $targetDirectory --bin meowcal-core --release
    if ($LASTEXITCODE -ne 0) {
        throw "Core candidate build failed with exit code $LASTEXITCODE."
    }
} finally {
    $env:CARGO_BUILD_JOBS = $previousCargoBuildJobs
    Pop-Location
}

$binaryPath = Join-Path $targetDirectory "$target\release\meowcal-core.exe"
if (-not (Test-Path -LiteralPath $binaryPath -PathType Leaf)) {
    throw "Core candidate build did not produce $binaryPath."
}
$expectedMachine = if ($architecture -eq "arm64") { 0xAA64 } else { 0x8664 }
$actualMachine = Get-PeMachine -Path $binaryPath
if ($actualMachine -ne $expectedMachine) {
    throw ("Core candidate PE machine 0x{0:X4} does not match {1}." -f $actualMachine, $architecture)
}
$versionJson = Invoke-CoreVersionJson -Path $binaryPath -Subject "Core candidate executable" `
    -TimeoutMilliseconds 10000
try {
    $versionInfo = $versionJson | ConvertFrom-Json
} catch {
    throw "Core candidate executable returned invalid --version-json output: $_"
}
$requiredCapabilities = @(
    "status", "install", "ready", "complete", "shutdown", "ocrInitialize",
    "ocrLanguages", "ocrRecognizeBgra"
)
$capabilities = @($versionInfo.capabilities)
if ($versionInfo.version -isnot [string] -or
    $versionInfo.version -ne $pin.coreVersion -or
    -not (Test-IsIntegerValue -Value $versionInfo.api -Expected $pin.apiVersion) -or
    @($capabilities | Where-Object { $_ -isnot [string] }).Count -ne 0 -or
    $capabilities.Count -ne $requiredCapabilities.Count -or
    (Compare-Object -ReferenceObject $requiredCapabilities -DifferenceObject $capabilities -CaseSensitive)) {
    throw "Core candidate version, API, or capabilities do not match the pinned v1 contract."
}

$destinationDirectory = Split-Path -Parent $DestinationPath
New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
$metadataDestination = Join-Path $destinationDirectory "meowcal-core.json"
$licenseDestination = Join-Path $destinationDirectory "LICENSE"
$temporaryPrefix = Join-Path $destinationDirectory (
    ".meowcal-core-candidate-" + [guid]::NewGuid().ToString("N")
)
try {
    Copy-Item -LiteralPath $binaryPath -Destination "$temporaryPrefix.exe"
    Copy-Item -LiteralPath $licensePath -Destination "$temporaryPrefix.LICENSE"
    Copy-Item -LiteralPath $ConfigPath -Destination "$temporaryPrefix.json"
    Move-Item -LiteralPath "$temporaryPrefix.LICENSE" -Destination $licenseDestination -Force
    Move-Item -LiteralPath "$temporaryPrefix.json" -Destination $metadataDestination -Force
    Move-Item -LiteralPath "$temporaryPrefix.exe" -Destination $DestinationPath -Force
} finally {
    Remove-Item -LiteralPath "$temporaryPrefix.exe" -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "$temporaryPrefix.json" -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "$temporaryPrefix.LICENSE" -Force -ErrorAction SilentlyContinue
}

Write-Host "Prepared Core source candidate $($pin.commit) $architecture at $DestinationPath."
[pscustomobject]@{
    Commit = $pin.commit
    Version = $pin.coreVersion
    ApiVersion = $pin.apiVersion
    Architecture = $architecture
    DestinationPath = $DestinationPath
}
