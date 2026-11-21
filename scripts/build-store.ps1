[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('x64','arm64')][string]$Architecture,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path $PSScriptRoot -Parent
if ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() -ne $Architecture) {
    throw "Build $Architecture Store packages on a native Windows $Architecture machine."
}
& "$PSScriptRoot/build-windows-release.ps1" -Architecture $Architecture -Python $Python -StoreLayout
$version = (Get-Content "$repo/src-tauri/tauri.conf.json" -Raw | ConvertFrom-Json).version
$layout = Join-Path $repo "dist/meowcal-sub-2-v$version-windows-$Architecture"
$manifest = (Get-Content "$repo/store/AppxManifest.xml" -Raw).Replace('@ARCHITECTURE@', $Architecture)
[IO.File]::WriteAllText("$layout/AppxManifest.xml", $manifest)
$assets = New-Item -ItemType Directory "$layout/Assets"
$catalog = Join-Path $repo 'dist/MeowcalSub2-StoreLogo-300.png'
& $Python "$PSScriptRoot/store_logos.py" "$repo/docs/assets/icon.png" $assets.FullName $catalog
if ($LASTEXITCODE) { throw 'Could not generate Store artwork.' }
. "$PSScriptRoot/windows-sdk-tools.ps1"
$makeAppx = Get-WindowsSdkTool 'makeappx.exe'
$packageVersion = ([xml]$manifest).Package.Identity.Version
$output = Join-Path $repo "dist/MeowcalSub2-$packageVersion-$Architecture.msix"
& $makeAppx pack /d $layout /p $output /h SHA256 /o
if ($LASTEXITCODE) { throw "MakeAppx failed validation for $Architecture." }
Get-FileHash -LiteralPath $output -Algorithm SHA256
