function Get-InstallerOwnedProcesses {
    param([object[]]$Processes, [string]$Root)
    $owned = @($Processes | Where-Object {
        $path = $_.ExecutablePath
        if ($path -and $path.StartsWith('\\?\')) { $path = $path.Substring(4) }
        $path -and $path.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase)
    })
    do {
        $ids = @($owned.ProcessId)
        $children = @($Processes | Where-Object {
            $child = $_
            $child.ProcessId -notin $ids -and $null -ne $child.CreationDate -and
            @($owned | Where-Object {
                $_.ProcessId -eq $child.ParentProcessId -and $null -ne $_.CreationDate -and
                $child.CreationDate -ge $_.CreationDate
            }).Count -eq 1
        })
        $owned += $children
    } while ($children.Count -gt 0)
    $owned
}
