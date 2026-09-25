function Test-IsIntegerValue {
    param($Value, [Parameter(Mandatory)][long]$Expected)

    return ($Value -is [int] -or $Value -is [long]) -and $Value -eq $Expected
}

# Core API 1 may advertise capabilities beyond its required base, so a release
# satisfies the contract when every required capability is present.
function Test-HasRequiredCapabilities {
    param($Capabilities, [Parameter(Mandatory)][string[]]$Required)

    $advertised = @($Capabilities)
    if (@($advertised | Where-Object { $_ -isnot [string] }).Count -ne 0) {
        return $false
    }
    return @($Required | Where-Object { $advertised -cnotcontains $_ }).Count -eq 0
}
