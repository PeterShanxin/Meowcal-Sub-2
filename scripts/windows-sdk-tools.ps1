function Get-WindowsSdkTool([string]$Name) {
    $root = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots').KitsRoot10
    $arch = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
    foreach ($version in (Get-ChildItem "$root/bin" -Directory |
            Where-Object Name -Match '^10\.0\.\d+\.0$' | Sort-Object { [version]$_.Name } -Descending)) {
        $path = Join-Path $version.FullName "$arch/$Name"
        if (Test-Path -LiteralPath $path -PathType Leaf) { return $path }
    }
    throw "Install the Windows SDK to use $Name."
}
