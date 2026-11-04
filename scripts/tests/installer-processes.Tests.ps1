$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\installer-processes.ps1')
function Process([int]$Id, [int]$Parent, [int]$Second, [string]$Path) {
    [pscustomobject]@{ProcessId=$Id;ParentProcessId=$Parent;CreationDate=([datetime]'2026-10-12T12:00:00Z').AddSeconds($Second);ExecutablePath=$Path}
}
$snapshot = @(
    (Process 10 1 10 'C:\test\owned\shell.exe'),
    # Parent PID 10 used to belong to a compiler. Its old child is not ours.
    (Process 20 10 2 'C:\compiler\VCTIP.EXE'),
    (Process 21 20 20 'C:\compiler\helper.exe'),
    (Process 30 10 11 'C:\webview\browser.exe'),
    (Process 31 30 12 'C:\webview\renderer.exe'),
    (Process 40 1 10 '\\?\C:\test\owned\core.exe'),
    (Process 50 1 10 'C:\test\owned-neighbor\other.exe')
)
$actual = @(Get-InstallerOwnedProcesses -Processes $snapshot -Root 'C:\test\owned\' | Sort-Object ProcessId | ForEach-Object ProcessId)
if (($actual -join ',') -ne '10,30,31,40') { throw "Wrong process ownership: $actual" }
'Owned descendants verified; reused parent PID and neighboring path rejected.'
