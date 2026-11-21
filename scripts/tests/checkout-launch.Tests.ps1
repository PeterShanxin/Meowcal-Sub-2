$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\prepare-checkout-launch.ps1')

function TestProcess([string]$Path) {
    $process = [pscustomobject]@{
        Handle = 1
        MainModule = [pscustomobject]@{ FileName = $Path }
        HasExited = $false
    }
    $process | Add-Member ScriptMethod Kill { $this.HasExited = $true }
    $process | Add-Member ScriptMethod WaitForExit { param($Timeout) $this.HasExited }
    return $process
}

$target = 'C:\fixture\repo\src-tauri\target\debug\meowcal-sub-2-shell.exe'
$ours = TestProcess $target.ToUpperInvariant()
$installed = TestProcess 'C:\fixture\installed\meowcal-sub-2-shell.exe'
$neighbor = TestProcess 'C:\fixture\repo2\src-tauri\target\debug\meowcal-sub-2-shell.exe'
$unknown = TestProcess ''
Stop-CheckoutShell @($installed, $neighbor, $unknown, $ours) $target
if (-not $ours.HasExited -or $installed.HasExited -or $neighbor.HasExited -or $unknown.HasExited) {
    throw 'Only the exact checkout shell should have been stopped.'
}
