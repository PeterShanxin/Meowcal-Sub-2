function Stop-CoreProcessTree {
    param([Parameter(Mandatory)][Diagnostics.Process]$Process)

    if ($Process.HasExited) { return }

    $taskkillPath = Join-Path $env:SystemRoot "System32\taskkill.exe"
    if (-not (Test-Path -LiteralPath $taskkillPath -PathType Leaf)) {
        throw "Windows taskkill.exe is required to terminate the Core process tree."
    }

    & $taskkillPath /PID $Process.Id /T /F 2>&1 | Out-Null
    if (-not $Process.WaitForExit(5000)) {
        try {
            $Process.Kill()
            $Process.WaitForExit()
        } catch {
            Write-Verbose "Direct Core process cleanup also failed: $_"
        }
        throw "Core process tree did not terminate after taskkill.exe."
    }
}

function Invoke-CoreProcessText {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Arguments,
        [Parameter(Mandatory)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory)][string]$Subject
    )

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Path
    $startInfo.Arguments = $Arguments
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($tokenName in @("GITHUB_TOKEN", "GH_TOKEN", "CORE_UPGRADE_TOKEN")) {
        [void]$startInfo.Environment.Remove($tokenName)
    }

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $started = $false
    try {
        $started = $process.Start()
        if (-not $started) { throw "$Subject did not start." }
        $process.StandardInput.Close()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutMilliseconds)) {
            Stop-CoreProcessTree -Process $process
            throw "$Subject timed out after $TimeoutMilliseconds ms."
        }

        [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdoutTask.GetAwaiter().GetResult().Trim()
            Stderr = $stderrTask.GetAwaiter().GetResult().Trim()
        }
    } finally {
        if ($started -and -not $process.HasExited) {
            Stop-CoreProcessTree -Process $process
        }
        $process.Dispose()
    }
}

function Invoke-CoreVersionJson {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Subject,
        [Parameter(Mandatory)][int]$TimeoutMilliseconds
    )

    $probeSubject = "$Subject --version-json"
    $result = Invoke-CoreProcessText -Path $Path -Arguments "--version-json" `
        -TimeoutMilliseconds $TimeoutMilliseconds -Subject $probeSubject
    if ($result.ExitCode -ne 0) {
        throw "$probeSubject failed with exit code $($result.ExitCode): $($result.Stderr)"
    }
    return $result.Stdout
}
