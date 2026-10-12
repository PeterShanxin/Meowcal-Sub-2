param(
    [Parameter(Mandatory)][string]$WorkRoot,
    [int]$AppPid,
    [ValidateSet('Inspect','Settings','Cancel','Yes','Close','Processes','Remaining','Cleanup','Installations','RemoveProfiles','ProfileLinks')]
    [string]$Action = 'Inspect',
    [string]$Tracked
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'Only disposable hosted Windows runners may perform native acceptance.'
}
$root = [IO.Path]::GetFullPath($WorkRoot).TrimEnd('\') + '\'
$temporary = [IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd('\') + '\'
if (-not $root.StartsWith($temporary, [StringComparison]::OrdinalIgnoreCase) -or $root -eq $temporary) {
    throw 'Work root must be strictly inside RUNNER_TEMP.'
}
$aliases = @(
    (Join-Path $env:APPDATA 'meowcal-sub-2'),
    (Join-Path $env:LOCALAPPDATA 'com.meowcal.sub2'),
    (Join-Path $env:USERPROFILE '.cache\meowcal-sub-2')
)
if ($Action -in @('ProfileLinks','RemoveProfiles')) {
    # RunAsUser rebuilds the user's environment on restart. Route only these
    # absent app-specific directories into this disposable job's fixture.
    $record = Join-Path $root 'profile-links.json'
    $saved = if (Test-Path -LiteralPath $record) { @(Get-Content -LiteralPath $record -Raw | ConvertFrom-Json) } else { @() }
    foreach ($link in $saved) {
        if ($link.alias -notin $aliases -or -not [IO.Path]::GetFullPath($link.target).StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid recorded profile alias.' }
        $item = Get-Item -LiteralPath $link.alias -Force -ErrorAction SilentlyContinue
        if ($item) {
            if ($item.LinkType -ne 'Junction' -or @($item.Target).Count -ne 1 -or @($item.Target)[0] -ne $link.target) { throw 'Profile alias no longer belongs to this job.' }
            [IO.Directory]::Delete($link.alias)
        }
    }
    if ($Action -eq 'ProfileLinks') {
        foreach ($alias in $aliases) {
            if (Get-Item -LiteralPath $alias -Force -ErrorAction SilentlyContinue) { throw 'Runner already has Sub 2 data; refusing to replace it.' }
        }
        $phase = Get-Content -LiteralPath (Join-Path $root 'active-profile.txt') -Raw
        if ($phase -notin @('formal','upgrade')) { throw 'Invalid profile phase.' }
        $targets = @('meowcal-sub-2','local\com.meowcal.sub2','home\.cache\meowcal-sub-2')
        $links = @(for ($i=0; $i -lt $aliases.Count; $i++) { @{alias=$aliases[$i];target=(Join-Path $root "$phase\$($targets[$i])")} })
        ConvertTo-Json -InputObject $links | Set-Content -LiteralPath $record
        foreach ($link in $links) {
            New-Item -ItemType Directory -Path $link.target -Force | Out-Null
            New-Item -ItemType Directory -Path (Split-Path $link.alias) -Force | Out-Null
            New-Item -ItemType Junction -Path $link.alias -Target $link.target | Out-Null
        }
        '{}' ; exit
    }
}
if ($Action -eq 'RemoveProfiles') {
    foreach ($name in @('formal', 'upgrade', 'installed app')) {
        $target = Join-Path $root $name
        if (-not (Test-Path -LiteralPath $target)) { continue }
        $resolved = (Resolve-Path -LiteralPath $target).Path
        if ($resolved -ne $target -or -not $resolved.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { throw 'Cleanup target changed.' }
        $entries = @(Get-Item -LiteralPath $target -Force; Get-ChildItem -LiteralPath $target -Force -Recurse)
        foreach ($link in @($entries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })) {
            if ($link.LinkType -ne 'Junction' -or -not $link.FullName.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected profile reparse point.' }
            foreach ($destination in @($link.Target)) {
                if (-not [IO.Path]::GetFullPath($destination).StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Profile junction escapes owned directory.' }
            }
            [IO.Directory]::Delete($link.FullName)
        }
        Remove-Item -LiteralPath $target -Recurse -Force
        if (Test-Path -LiteralPath $target) { throw 'Owned profile remains.' }
    }
    '{}' ; exit
}
if ($Action -eq 'Installations') {
    $entries = @()
    foreach ($hive in @('HKCU:', 'HKLM:')) {
        foreach ($view in @('Software', 'Software\WOW6432Node')) {
            $key = "$hive\$view\Microsoft\Windows\CurrentVersion\Uninstall"
            if (Test-Path -LiteralPath $key) {
                $entries += @(Get-ChildItem -LiteralPath $key | Get-ItemProperty | Where-Object DisplayName -eq 'Meowcal Sub 2' | Select-Object InstallLocation,DisplayVersion)
            }
        }
    }
    ConvertTo-Json -InputObject @($entries | Sort-Object InstallLocation,DisplayVersion -Unique) -Compress
    exit
}
if ($Action -in @('Processes','Remaining','Cleanup')) {
    $all = @(Get-CimInstance Win32_Process)
    if ($Action -eq 'Processes') {
        . (Join-Path $PSScriptRoot 'installer-processes.ps1')
        $owned = @(Get-InstallerOwnedProcesses -Processes $all -Root $root)
    } else {
        if (-not [IO.Path]::GetFullPath($Tracked).StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { throw 'Tracked file outside work root.' }
        $saved = @(Get-Content -LiteralPath $Tracked -Raw | ConvertFrom-Json)
        $owned = @($all | Where-Object {
            $process = $_
            @($saved | Where-Object { $_.pid -eq $process.ProcessId -and $_.created -eq $process.CreationDate.ToUniversalTime().ToString('o') }).Count -eq 1
        })
        if ($Action -eq 'Cleanup') { $owned | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue } }
    }
    ConvertTo-Json -InputObject @($owned | ForEach-Object { @{pid=$_.ProcessId; created=$_.CreationDate.ToUniversalTime().ToString('o'); path=$_.ExecutablePath} }) -Compress
    exit
}
$app = Get-Process -Id $AppPid
if (-not $app.Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { throw 'Window process is not owned by this test.' }
if ($Action -eq 'Close') {
    if (-not $app.CloseMainWindow()) { throw 'Owned app has no closeable main window.' }
    '{}' ; exit
}
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$condition = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $AppPid)
function Read-OwnedControls {
    $windows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $condition)
    foreach ($window in $windows) {
        $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    }
}
$controls = @(Read-OwnedControls)
if ($Action -ne 'Inspect') {
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $buttons = @($controls | Where-Object {
            $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
            $_.Current.Name.Replace('&','') -eq $Action -and $_.Current.IsEnabled -and -not $_.Current.IsOffscreen
        })
        if ($buttons.Count -eq 1) { break }
        Start-Sleep -Milliseconds 250
        $controls = @(Read-OwnedControls)
    } while ([DateTime]::UtcNow -lt $deadline)
}
$rows = @($controls | ForEach-Object { @{type=$_.Current.ControlType.ProgrammaticName; name=$_.Current.Name; offscreen=$_.Current.IsOffscreen; enabled=$_.Current.IsEnabled} })
if ($Action -ne 'Inspect') {
    if ($buttons.Count -ne 1) { throw "Expected one enabled owned $Action button, found $($buttons.Count). Controls: $($rows | ConvertTo-Json -Compress)" }
    $buttons[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject $rows -Compress -EscapeHandling EscapeNonAscii))
