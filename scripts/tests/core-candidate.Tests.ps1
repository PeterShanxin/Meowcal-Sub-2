[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$candidateScript = Join-Path $repositoryRoot "scripts\prepare-core-candidate.ps1"
$checkedInPin = Join-Path $repositoryRoot "config\meowcal-core.candidate.json"
$temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) (
    "meowcal-core-candidate-tests-" + [guid]::NewGuid().ToString("N")
)

function Assert-Throws {
    param([scriptblock]$Action, [string]$ExpectedSubstring)

    try {
        & $Action
    } catch {
        if ($_.Exception.Message -notlike "*$ExpectedSubstring*") {
            throw "Expected an error containing '$ExpectedSubstring', got '$($_.Exception.Message)'."
        }
        return
    }
    throw "Expected an error containing '$ExpectedSubstring', but the action succeeded."
}

function Write-CorePin {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Commit,
        [string]$Repository = "PeterShanxin/Meowcal-Sub",
        [string]$Version = "0.1.0",
        [int]$ApiVersion = 1,
        [int]$SchemaVersion = 1
    )

    $pin = [ordered]@{
        schemaVersion = $SchemaVersion
        repository = $Repository
        commit = $Commit
        coreVersion = $Version
        apiVersion = $ApiVersion
    }
    [IO.File]::WriteAllText(
        $Path,
        (($pin | ConvertTo-Json) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
}

function Invoke-Git {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & git @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

function New-TestPe {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][uint16]$Machine)

    $bytes = [byte[]]::new(512)
    $bytes[0] = 0x4D
    $bytes[1] = 0x5A
    [BitConverter]::GetBytes([uint32]0x80).CopyTo($bytes, 0x3C)
    [BitConverter]::GetBytes([uint32]0x00004550).CopyTo($bytes, 0x80)
    [BitConverter]::GetBytes($Machine).CopyTo($bytes, 0x84)
    [IO.File]::WriteAllBytes($Path, $bytes)
}

New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
$source = Join-Path $temporaryDirectory "source"
$shimDirectory = Join-Path $temporaryDirectory "bin"
$cargoLog = Join-Path $temporaryDirectory "cargo.log"
$pinPath = Join-Path $temporaryDirectory "pin.json"
$fakeBinary = Join-Path $temporaryDirectory "fake-core.exe"
$incomingPath = $env:PATH
$incomingCargoLog = $env:FAKE_CARGO_LOG
$incomingCoreSource = $env:FAKE_CORE_SOURCE
$incomingCoreTarget = $env:FAKE_CORE_TARGET
$incomingCoreBinary = $env:FAKE_CORE_BINARY
$incomingCargoExit = $env:FAKE_CARGO_EXIT

try {
    $checkedInCommit = & $candidateScript -ConfigPath $checkedInPin -ResolveCommit
    if ($checkedInCommit -notmatch '^[0-9a-f]{40}$') {
        throw "The checked-in Core candidate pin must resolve to one exact lowercase commit."
    }

    Invoke-Git -Arguments @("init", "--quiet", "--initial-branch", "main", $source)
    Invoke-Git -Arguments @("-C", $source, "config", "user.email", "core-candidate@test.invalid")
    Invoke-Git -Arguments @("-C", $source, "config", "user.name", "Core Candidate Test")
    Invoke-Git -Arguments @("-C", $source, "config", "core.autocrlf", "false")
    New-Item -ItemType Directory -Path (Join-Path $source "core\src") -Force | Out-Null
    [IO.File]::WriteAllText(
        (Join-Path $source "core\Cargo.toml"),
        "[package]`nname = `"meowcal-core`"`nversion = `"0.1.0`"`n"
    )
    [IO.File]::WriteAllText((Join-Path $source "core\Cargo.lock"), "# test lock`n")
    [IO.File]::WriteAllText((Join-Path $source "LICENSE"), "test license`n")
    [IO.File]::WriteAllText((Join-Path $source ".gitignore"), "core/target/`n")
    Invoke-Git -Arguments @("-C", $source, "add", ".")
    Invoke-Git -Arguments @("-C", $source, "commit", "--quiet", "-m", "fixture")
    $head = (& git -C $source rev-parse HEAD).Trim()
    Write-CorePin -Path $pinPath -Commit $head

    New-Item -ItemType Directory -Path $shimDirectory | Out-Null
    @'
@echo off
echo %*>>"%FAKE_CARGO_LOG%"
if not "%FAKE_CARGO_EXIT%"=="0" exit /b %FAKE_CARGO_EXIT%
set "destination=%FAKE_CORE_SOURCE%\core\target\%FAKE_CORE_TARGET%\release"
if not exist "%destination%" mkdir "%destination%"
copy /y "%FAKE_CORE_BINARY%" "%destination%\meowcal-core.exe" >nul
exit /b %errorlevel%
'@ | Set-Content -LiteralPath (Join-Path $shimDirectory "cargo.cmd") -Encoding ascii

    $target = if ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture -eq "Arm64") {
        "aarch64-pc-windows-msvc"
    } else {
        "x86_64-pc-windows-msvc"
    }
    $env:PATH = "$shimDirectory;$incomingPath"
    $env:FAKE_CARGO_LOG = $cargoLog
    $env:FAKE_CORE_SOURCE = $source
    $env:FAKE_CORE_TARGET = $target
    $env:FAKE_CORE_BINARY = Join-Path $env:SystemRoot "System32\cmd.exe"
    $env:FAKE_CARGO_EXIT = "23"

    Assert-Throws {
        & $candidateScript -SourcePath $source -ConfigPath $pinPath `
            -DestinationPath (Join-Path $temporaryDirectory "resource\meowcal-core.exe")
    } "build failed with exit code 23"
    $cargoCommand = Get-Content -LiteralPath $cargoLog -Raw
    $expectedCommand = ("build --locked --manifest-path Cargo.toml --target $target " +
        "--target-dir $(Join-Path $source 'core\target') --bin meowcal-core --release")
    if ($cargoCommand.Trim() -ne $expectedCommand) {
        throw "Candidate preparation must use the locked native release build. Got '$($cargoCommand.Trim())'."
    }

    Write-CorePin -Path $pinPath -Commit "main"
    Assert-Throws {
        & $candidateScript -SourcePath $source -ConfigPath $pinPath
    } "exact 40-character lowercase Git SHA"

    Write-CorePin -Path $pinPath -Commit ("a" * 40)
    Assert-Throws {
        & $candidateScript -SourcePath $source -ConfigPath $pinPath
    } "does not match pinned commit"

    Write-CorePin -Path $pinPath -Commit $head -Repository "example/Core"
    Assert-Throws {
        & $candidateScript -SourcePath $source -ConfigPath $pinPath
    } "must use PeterShanxin/Meowcal-Sub"

    Write-CorePin -Path $pinPath -Commit $head -Version "0.2.0"
    Assert-Throws {
        & $candidateScript -SourcePath $source -ConfigPath $pinPath
    } "Cargo version does not match"

    Write-CorePin -Path $pinPath -Commit $head
    [IO.File]::WriteAllText((Join-Path $source "untracked.txt"), "dirty`n")
    Assert-Throws {
        & $candidateScript -SourcePath $source -ConfigPath $pinPath
    } "source checkout must be clean"
    Remove-Item -LiteralPath (Join-Path $source "untracked.txt")

    $env:FAKE_CARGO_EXIT = "0"
    $wrongMachine = if ($target -eq "aarch64-pc-windows-msvc") {
        [uint16]0x8664
    } else {
        [uint16]0xAA64
    }
    New-TestPe -Path $fakeBinary -Machine $wrongMachine
    $env:FAKE_CORE_BINARY = $fakeBinary
    Assert-Throws {
        & $candidateScript -SourcePath $source -ConfigPath $pinPath
    } "PE machine"

    # Execute the fixture last so no later case replaces a recently mapped image.
    $env:FAKE_CORE_BINARY = Join-Path $env:SystemRoot "System32\cmd.exe"
    Assert-Throws {
        & $candidateScript -SourcePath $source -ConfigPath $pinPath
    } "invalid --version-json output"

    $candidateSource = Get-Content -LiteralPath $candidateScript -Raw
    if ($candidateSource -notmatch '\$startInfo\.Arguments\s*=\s*"--version-json"' -or
        $candidateSource -match '\.ArgumentList' -or
        $candidateSource -match '\.Kill\(\$true\)') {
        throw "Core candidate probing must use ProcessStartInfo APIs supported by Windows PowerShell 5.1."
    }

    $verifySource = Get-Content -LiteralPath (Join-Path $repositoryRoot "scripts\verify.ps1") -Raw
    if ($verifySource -notmatch '(?s)if \(\$CoreCandidateSource\).*?& \$CoreCandidatePrepare' -or
        $verifySource -notmatch '(?s)else\s*\{.*?& \$CoreFetch') {
        throw "verify.ps1 must use candidates only when explicitly requested and keep release fetch as its default."
    }

    $workflowSource = Get-Content -LiteralPath (
        Join-Path $repositoryRoot ".github\workflows\windows-ci.yml"
    ) -Raw
    $workflowRequirements = @(
        'prepare-core-candidate\.ps1 -ResolveCommit',
        'repository: PeterShanxin/Meowcal-Sub',
        'ref: \$\{\{ steps\.core-candidate\.outputs\.commit \}\}',
        'verify\.ps1 -CoreCandidateSource'
    )
    foreach ($requirement in $workflowRequirements) {
        if ([regex]::Matches($workflowSource, $requirement).Count -ne 2) {
            throw "Both Windows CI architectures must resolve, check out, and verify the exact canonical Core source pin."
        }
    }
    $candidateOnlyCondition = [regex]::Escape(
        "if: `${{ hashFiles('config/meowcal-core.lock.json') == '' }}"
    )
    if ([regex]::Matches($workflowSource, $candidateOnlyCondition).Count -ne 4 -or
        [regex]::Matches(
            $workflowSource,
            '(?m)^\s*if \(Test-Path -LiteralPath \.\\config\\meowcal-core\.lock\.json\) \{$'
        ).Count -ne 2 -or
        [regex]::Matches($workflowSource, '(?m)^\s*\.\\scripts\\verify\.ps1\s*$').Count -ne 2) {
        throw "Windows CI must prefer normal release verification whenever the reviewed Core lock exists."
    }

    Write-Host "Core source candidate contract tests passed." -ForegroundColor Green
} finally {
    $env:PATH = $incomingPath
    $env:FAKE_CARGO_LOG = $incomingCargoLog
    $env:FAKE_CORE_SOURCE = $incomingCoreSource
    $env:FAKE_CORE_TARGET = $incomingCoreTarget
    $env:FAKE_CORE_BINARY = $incomingCoreBinary
    $env:FAKE_CARGO_EXIT = $incomingCargoExit
    Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
