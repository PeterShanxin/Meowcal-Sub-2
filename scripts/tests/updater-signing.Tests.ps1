[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$selectSigning = Join-Path $repositoryRoot 'scripts/select-updater-signing.ps1'

foreach ($privateKey in @($false, $true)) {
    foreach ($publicKey in @($false, $true)) {
        $arguments = @{ PrivateKeyConfigured = $privateKey; PublicKeyConfigured = $publicKey }
        $branchMode = & $selectSigning @arguments
        if ($branchMode -ne $false) { throw 'Non-tag builds must keep updater signing disabled.' }

        if ($privateKey -ne $publicKey) {
            $rejected = $false
            try { & $selectSigning @arguments -ReleaseTag | Out-Null }
            catch {
                if ($_.Exception.Message -notlike '*partially configured*') { throw }
                $rejected = $true
            }
            if (-not $rejected) { throw 'Partial signing configuration must fail rather than publish unsigned.' }
        } else {
            $tagMode = & $selectSigning @arguments -ReleaseTag
            if ($tagMode -ne $privateKey) { throw 'Tagged builds must sign exactly when both keys are configured.' }
        }
    }
}
Write-Host 'Updater signing: unsigned tags, signed tags, partial configuration and branch isolation pass.'
