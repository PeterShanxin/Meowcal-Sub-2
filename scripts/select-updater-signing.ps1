[CmdletBinding()]
param(
    [switch]$ReleaseTag,
    [switch]$PrivateKeyConfigured,
    [switch]$PublicKeyConfigured
)

$ErrorActionPreference = 'Stop'
if (-not $ReleaseTag) { return $false }
if ($PrivateKeyConfigured.IsPresent -ne $PublicKeyConfigured.IsPresent) {
    throw 'Updater signing is partially configured; configure both keys or neither.'
}
return [bool]$PrivateKeyConfigured
