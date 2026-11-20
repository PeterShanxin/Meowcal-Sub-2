[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Stop-CheckoutShell($Processes, [string]$ShellPath) {
    foreach ($process in $Processes) {
        # Read the image path and kill through the same Process handle. A PID or a
        # basename can belong to another checkout or to an installed copy.
        try {
            $null = $process.Handle
            $image = $process.MainModule.FileName
        } catch {
            continue
        }
        if ($image -and [string]::Equals($image, $ShellPath, [StringComparison]::OrdinalIgnoreCase)) {
            if (-not $process.HasExited) {
                $process.Kill()
                if (-not $process.WaitForExit(5000)) { throw 'The previous checkout shell is still closing.' }
            }
        }
    }
}

if ($MyInvocation.InvocationName -eq '.') { return }
$repo = (Get-Item -LiteralPath (Join-Path $PSScriptRoot '..')).FullName
$shellPath = Join-Path $repo 'src-tauri\target\debug\meowcal-sub-2-shell.exe'
Stop-CheckoutShell @(Get-Process -Name 'meowcal-sub-2-shell' -ErrorAction SilentlyContinue) $shellPath
