$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $scriptDir "run_app.vbs"

if (-not (Test-Path $launcher)) {
  throw "Missing launcher at $launcher"
}

Start-Process -FilePath "wscript.exe" -ArgumentList @("//nologo", $launcher) -WorkingDirectory $scriptDir | Out-Null
