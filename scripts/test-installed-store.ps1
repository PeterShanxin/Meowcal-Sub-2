[CmdletBinding()]
param(
    [Parameter(Mandatory)][IO.FileInfo]$Package,
    [Parameter(Mandatory)][ValidateSet('x64','arm64')][string]$Architecture
)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'Store installation tests require a disposable hosted Windows runner.'
}
. "$PSScriptRoot/windows-sdk-tools.ps1"
$manifest = ([xml](Get-Content "$PSScriptRoot/../store/AppxManifest.xml" -Raw)).Package
$name = $manifest.Identity.Name
if (Get-AppxPackage -Name $name) { throw 'Runner already contains Sub 2 Store edition.' }
$work = New-Item -ItemType Directory (Join-Path $env:RUNNER_TEMP 'sub2-store-acceptance')
$testPackage = Join-Path $work.FullName 'local-test.msix'
Copy-Item -LiteralPath $Package.FullName -Destination $testPackage
$signTool = Get-WindowsSdkTool 'signtool.exe'
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $manifest.Identity.Publisher -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddDays(1)
$trusted = $null
$installed = $null
try {
    & $signTool sign /fd SHA256 /sha1 $cert.Thumbprint /s My $testPackage
    if ($LASTEXITCODE) { throw 'Test signing failed.' }
    $publicCert = Join-Path $work.FullName 'test.cer'
    Export-Certificate -Cert $cert -FilePath $publicCert | Out-Null
    $trusted = Import-Certificate -FilePath $publicCert -CertStoreLocation Cert:\LocalMachine\TrustedPeople
    $options = @{ Path = $testPackage }
    $framework = Get-AppxPackage Microsoft.VCLibs.140.00.UWPDesktop | Where-Object {
        $_.Architecture -eq $Architecture -and [version]$_.Version -ge [version]'14.0.33728.0'
    }
    if (-not $framework) {
        $zip = Join-Path $work.FullName 'dependencies.zip'
        Invoke-WebRequest 'https://github.com/microsoft/winget-cli/releases/download/v1.29.380/DesktopAppInstaller_Dependencies.zip' -OutFile $zip -UseBasicParsing
        if ((Get-FileHash $zip).Hash -ne 'BA875AFE9D190F61218985AC0292A99D1DB710BF93E13C68944CA9D89F0D82D1') { throw 'Unexpected Microsoft dependency archive.' }
        $dependencies = Join-Path $work.FullName 'dependencies'
        Expand-Archive $zip $dependencies
        $dependency = Get-ChildItem $dependencies -Recurse -Filter "Microsoft.VCLibs.140.00.UWPDesktop_14.0.33728.0_$Architecture.appx" | Select-Object -First 1
        if (-not $dependency) { throw 'Native Microsoft VC runtime is missing.' }
        $options.DependencyPath = $dependency.FullName
    }
    Add-AppxPackage @options
    $installed = Get-AppxPackage -Name $name
    if ($installed.PackageFamilyName -ne 'ShanxinLi.MeowcalSub2_hs4jcn39rmtjt' -or $installed.Architecture -ne $Architecture) {
        throw 'Installed Store identity or architecture mismatch.'
    }
    $root = Join-Path $env:LOCALAPPDATA "Packages\$($installed.PackageFamilyName)\LocalState"
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("2E941141-7F97-4756-BA1D-9DECDE894A3D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IApplicationActivationManager {
    void ActivateApplication([MarshalAs(UnmanagedType.LPWStr)]string id, [MarshalAs(UnmanagedType.LPWStr)]string args, uint options, out uint pid);
}
public static class StoreActivation {
    public static uint Start(string id) {
        var clsid = new Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C");
        var activator = (IApplicationActivationManager)Activator.CreateInstance(Type.GetTypeFromCLSID(clsid));
        uint pid;
        activator.ActivateApplication(id, null, 0, out pid);
        return pid;
    }
}
'@
    $appPid = [StoreActivation]::Start("$($installed.PackageFamilyName)!App")
    $deadline = (Get-Date).AddSeconds(90)
    $runtime = Join-Path $root 'meowcal-sub-2/runtime.json'
    while (-not (Test-Path -LiteralPath $runtime)) {
        if ((Get-Date) -gt $deadline -or -not (Get-Process -Id $appPid -ErrorAction SilentlyContinue)) {
            throw 'Store activation did not start the private Studio backend.'
        }
        Start-Sleep -Seconds 1
    }
    $connection = Get-Content $runtime -Raw | ConvertFrom-Json
    if ($connection.port -ne 8766) { throw 'Studio did not open the Store port.' }
    $headers = @{'x-meowcal-token' = $connection.token}
    $api = 'http://127.0.0.1:8766/api/config'
    $null = Invoke-RestMethod $api -Headers $headers -Method Put -ContentType 'application/json' -Body '{"sync":{"biasMs":300}}'
    $settings = Invoke-RestMethod $api -Headers $headers
    if ($settings.sync.biasMs -ne 300 -or -not (Test-Path "$root/meowcal-sub-2/config.toml")) {
        throw 'Studio settings were not saved in the private Store profile.'
    }
    $deadline = (Get-Date).AddSeconds(90)
    do {
        $rows = (& pwsh -NoProfile -File "$PSScriptRoot/inspect-installer-window.ps1" -WorkRoot $work.FullName -AppPid $appPid -Action Inspect -Store) | ConvertFrom-Json
        if ($rows | Where-Object { $_.type -eq 'ControlType.Document' -and $_.name -eq 'Meowcal Sub 2' -and -not $_.offscreen }) { break }
        if ((Get-Date) -gt $deadline) { throw 'The installed Studio window did not appear.' }
        Start-Sleep -Seconds 1
    } while ($true)
    Write-Host "Installed $Architecture Studio opened with private settings."
} finally {
    if ($installed) { Remove-AppxPackage $installed.PackageFullName }
    if ($trusted) { Remove-Item -LiteralPath "Cert:\LocalMachine\TrustedPeople\$($trusted.Thumbprint)" }
    Remove-Item -LiteralPath "Cert:\CurrentUser\My\$($cert.Thumbprint)"
}
