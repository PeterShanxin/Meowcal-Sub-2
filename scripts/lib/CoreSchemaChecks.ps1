function Test-IsIntegerValue {
    param($Value, [Parameter(Mandatory)][long]$Expected)

    return ($Value -is [int] -or $Value -is [long]) -and $Value -eq $Expected
}
