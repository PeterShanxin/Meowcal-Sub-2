[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('x64', 'arm64')][string]$Architecture,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$lock = Get-Content (Join-Path $repositoryRoot 'config/python-runtime.lock.json') -Raw | ConvertFrom-Json
$entry = $lock.architectures.$Architecture
$outputRoot = Join-Path $repositoryRoot 'output/backend-build'
$destination = Join-Path $repositoryRoot 'src-tauri/resources/backend'
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$archive = Join-Path $outputRoot $entry.asset
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/$($lock.version)/$($entry.asset)" `
        -OutFile $archive -TimeoutSec 120
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
    throw 'Embedded Python archive does not match its release lock.'
}

# Only this generated directory may be replaced; never clear a caller-supplied path.
$expectedDestination = [IO.Path]::GetFullPath((Join-Path $repositoryRoot 'src-tauri/resources/backend'))
if ([IO.Path]::GetFullPath($destination) -cne $expectedDestination) { throw 'Unsafe backend destination.' }
if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Recurse -Force }
Expand-Archive -LiteralPath $archive -DestinationPath $destination
$platform = if ($Architecture -eq 'arm64') { 'win_arm64' } else { 'win_amd64' }
$sitePackages = Join-Path $destination 'Lib/site-packages'
& $Python -m pip install --disable-pip-version-check --ignore-installed --no-compile --require-hashes `
    --only-binary=:all: --platform $platform --python-version 3.14 --implementation cp --abi cp314 `
    --target $sitePackages -r (Join-Path $repositoryRoot 'config/backend-requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed: $LASTEXITCODE" }

$wheelDirectory = Join-Path $outputRoot ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $wheelDirectory | Out-Null
& $Python -m pip wheel --disable-pip-version-check --no-deps --wheel-dir $wheelDirectory $repositoryRoot
if ($LASTEXITCODE -ne 0) { throw "Backend wheel build failed: $LASTEXITCODE" }
$wheel = @(Get-ChildItem -LiteralPath $wheelDirectory -Filter '*.whl')
if ($wheel.Count -ne 1) { throw 'Expected exactly one backend wheel.' }
& $Python -m pip install --disable-pip-version-check --no-deps --no-compile --no-index `
    --find-links $wheelDirectory --target $sitePackages meowcal-sub-2
if ($LASTEXITCODE -ne 0) { throw "Backend wheel installation failed: $LASTEXITCODE" }

# The shell uses -m; pip's unused console launchers embed the build Python path.
foreach ($scriptsFolder in @('bin', 'Scripts')) {
    $consoleScripts = [IO.Path]::GetFullPath((Join-Path $sitePackages $scriptsFolder))
    if ($consoleScripts -cne (Join-Path $expectedDestination "Lib/site-packages/$scriptsFolder")) { throw 'Unsafe launcher destination.' }
    if (Test-Path -LiteralPath $consoleScripts) { Remove-Item -LiteralPath $consoleScripts -Recurse -Force }
}

# The embedded interpreter ignores registry, environment and user site packages.
@('python314.zip', '.', 'Lib/site-packages') | Set-Content (Join-Path $destination 'python314._pth') -Encoding ascii
Copy-Item -LiteralPath (Join-Path $repositoryRoot 'LICENSE') -Destination (Join-Path $destination 'MEOWCAL-LICENSE')
Copy-Item -LiteralPath (Join-Path $repositoryRoot 'config/backend-requirements.txt') -Destination $destination
if (Test-Path (Join-Path $sitePackages 'meocosub2/overlay/ui')) {
    throw 'The backend wheel must not include studio source or node_modules.'
}
Write-Host "Prepared isolated Python $($lock.version) backend for $Architecture."
