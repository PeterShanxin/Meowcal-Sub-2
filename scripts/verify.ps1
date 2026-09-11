<#
.SYNOPSIS
    Answers one question: is this checkout ready for review?

.DESCRIPTION
    Every gate this repository enforces, in one place, so CI and a developer run
    the same checks rather than two drifting lists. CI calls this script; it does
    not restate the policy in YAML.

    Needs no credentials, no private paths, and no state from an earlier run. A
    clean checkout plus the prerequisites in docs/AGENT_GUIDE.md is enough.

    What this cannot prove: OCR, WebView2 rendering, the capture selector, and
    the overlay plate. Those need a real Windows run of the app.

.PARAMETER Stage
    Run only these stages. Omit to run all of them, which is the authoritative
    result. Order is fixed regardless of how they are listed.

.PARAMETER List
    Print the stages and exit.

.PARAMETER CoreCandidateSource
    Use the exact source candidate pinned in config/meowcal-core.candidate.json
    for development verification. Omit to require the reviewed release lock.

.EXAMPLE
    .\scripts\verify.ps1
    .\scripts\verify.ps1 -Stage python, ratchets
#>
[CmdletBinding()]
param(
    [ValidateSet('setup', 'format', 'python', 'typescript', 'rust', 'smoke', 'ratchets')]
    [string[]]$Stage,
    [switch]$List,
    [string]$CoreCandidateSource
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$UiDir = Join-Path $RepoRoot 'src/meocosub2/overlay/ui'
$Biome = Join-Path $UiDir 'node_modules/.bin/biome.cmd'
$ReportPath = Join-Path $RepoRoot '.verify-report.json'
$CorePackageTest = Join-Path $RepoRoot 'scripts/tests/core-package.Tests.ps1'
$CoreCandidateTest = Join-Path $RepoRoot 'scripts/tests/core-candidate.Tests.ps1'
$CoreFetch = Join-Path $RepoRoot 'scripts/fetch-meowcal-core.ps1'
$CoreCandidatePrepare = Join-Path $RepoRoot 'scripts/prepare-core-candidate.ps1'
$CoreCandidateConfig = Join-Path $RepoRoot 'config/meowcal-core.candidate.json'
$CoreResource = Join-Path $RepoRoot 'src-tauri/resources/core/meowcal-core.exe'
$AllStages = @('setup', 'format', 'python', 'typescript', 'rust', 'smoke', 'ratchets')

if ($List) {
    $AllStages | ForEach-Object { Write-Host $_ }
    exit 0
}

$Wanted = if ($Stage) { $AllStages | Where-Object { $Stage -contains $_ } } else { $AllStages }
$Failures = [System.Collections.Generic.List[string]]::new()
$Report = @{}
$LintCounts = @{}

function Start-Stage([string]$Name) {
    Write-Host ''
    Write-Host "== $Name " -NoNewline
    Write-Host ('=' * [Math]::Max(0, 60 - $Name.Length))
}

function Invoke-Check([string]$Label, [scriptblock]$Body) {
    Write-Host "-- $Label"
    try {
        $global:LASTEXITCODE = 0
        & $Body
        if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
    }
    catch {
        $Failures.Add("$Label`: $_")
        Write-Host "   FAILED: $_" -ForegroundColor Red
    }
}

Push-Location $RepoRoot
try {
    Invoke-Check 'Core package contract' { & $CorePackageTest }
    Invoke-Check 'Core source candidate contract' { & $CoreCandidateTest }

    if ($Wanted -contains 'setup') {
        Start-Stage 'setup'
        if (-not (Test-Path $Biome)) {
            $Failures.Add('setup: studio dependencies are missing. Run: npm --prefix src\meocosub2\overlay\ui install')
            Write-Host '   FAILED: studio dependencies are missing' -ForegroundColor Red
        }
        Invoke-Check 'python imports the package' { python -c "import meocosub2" }
    }

    if ($Wanted -contains 'format') {
        Start-Stage 'format'
        Invoke-Check 'ruff format' { python -m ruff format --check src tests scripts }
        Invoke-Check 'biome format' { & $Biome format }
        Invoke-Check 'cargo fmt' { cargo fmt --manifest-path src-tauri\Cargo.toml -- --check }
    }

    if ($Wanted -contains 'python') {
        Start-Stage 'python'
        # Ruff is gated at zero, so passing is the count the ratchet records.
        Invoke-Check 'ruff lint' { python -m ruff check src tests scripts }
        if ($Failures.Count -eq 0) { $LintCounts['ruff'] = 0 }
        Invoke-Check 'pytest' {
            python -m pytest -q --cov=src/meocosub2 --cov-report=json:.coverage.json
        }
        if (Test-Path '.coverage.json') {
            # -AsHashtable because the report carries a property with an empty
            # name, which ConvertFrom-Json refuses to turn into an object.
            $Coverage = Get-Content '.coverage.json' -Raw | ConvertFrom-Json -AsHashtable
            $Report['pythonCoverage'] = $Coverage['totals']['percent_covered']
            Remove-Item '.coverage.json' -ErrorAction SilentlyContinue
        }
    }

    if ($Wanted -contains 'typescript') {
        Start-Stage 'typescript'
        Invoke-Check 'tsc' { npx --prefix $UiDir tsc -b $UiDir }
        # Biome carries a budget of pre-existing findings rather than a zero
        # gate, so its count goes to the ratchet instead of failing here.
        $BiomeSummary = (& $Biome lint --reporter=json 2>$null | ConvertFrom-Json).summary
        $LintCounts['biome'] = $BiomeSummary.errors + $BiomeSummary.warnings
        Write-Host "-- biome lint ($($LintCounts['biome']) findings, budgeted)"
        Invoke-Check 'vitest' {
            npm --prefix $UiDir test --silent -- --coverage --coverage.reporter=json-summary
        }
        $Summary = Join-Path $UiDir 'coverage/coverage-summary.json'
        if (Test-Path $Summary) {
            # Handed over whole. Which modules the floors describe, and how their
            # figures combine, is the ratchet's business - the baseline names the
            # scope, so the aggregation belongs next to it.
            $Report['frontendCoverageSummary'] =
            Get-Content $Summary -Raw | ConvertFrom-Json -AsHashtable
        }
    }

    if ($Wanted -contains 'rust') {
        Start-Stage 'rust'
        if ($CoreCandidateSource) {
            Invoke-Check 'prepare pinned Core source candidate' {
                & $CoreCandidatePrepare -SourcePath $CoreCandidateSource `
                    -ConfigPath $CoreCandidateConfig | Out-Null
            }
        }
        else {
            Invoke-Check 'prepare pinned Core release resource' { & $CoreFetch | Out-Null }
        }
        Invoke-Check 'real Core consumer handshake' {
            if (-not (Test-Path -LiteralPath $CoreResource -PathType Leaf)) {
                throw "Pinned Core resource is missing: $CoreResource"
            }
            $PreviousCoreExe = $env:MEOWCAL_CORE_EXE
            $PreviousPythonPath = $env:PYTHONPATH
            try {
                $env:MEOWCAL_CORE_EXE = $CoreResource
                $env:PYTHONPATH = Join-Path $RepoRoot 'src'
                python -m pytest -q `
                    tests/test_core_client.py::test_real_core_process_handshake_and_status
            }
            finally {
                $env:MEOWCAL_CORE_EXE = $PreviousCoreExe
                $env:PYTHONPATH = $PreviousPythonPath
            }
        }
        Invoke-Check 'cargo clippy' {
            cargo clippy --manifest-path src-tauri\Cargo.toml --all-targets -- -D warnings
        }
        if ($Failures.Count -eq 0) { $LintCounts['clippy'] = 0 }
        Invoke-Check 'cargo test' { cargo test --manifest-path src-tauri\Cargo.toml }
    }

    if ($Wanted -contains 'smoke') {
        Start-Stage 'smoke'
        Invoke-Check 'served dashboard' { python scripts\run_dashboard_smoke.py }
    }

    if ($Wanted -contains 'ratchets') {
        Start-Stage 'ratchets'
        # Only the tools that actually ran this time; a budget cannot be judged
        # from a stage that was skipped.
        if ($LintCounts.Count -gt 0) { $Report['lint'] = $LintCounts }
        $Report | ConvertTo-Json -Depth 5 | Set-Content $ReportPath -Encoding utf8
        Invoke-Check 'maintainability' {
            python scripts\check_maintainability.py --report $ReportPath
        }
        Remove-Item $ReportPath -ErrorAction SilentlyContinue
    }

    Write-Host ''
    if ($Failures.Count -gt 0) {
        Write-Host "$($Failures.Count) check(s) failed:" -ForegroundColor Red
        $Failures | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        exit 1
    }
    if ($Stage) {
        Write-Host "Stages passed: $($Wanted -join ', '). A full run is the authoritative result."
    }
    else {
        Write-Host 'Ready for review.' -ForegroundColor Green
    }
    exit 0
}
finally {
    Pop-Location
}
