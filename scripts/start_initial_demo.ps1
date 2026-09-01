[CmdletBinding()]
param(
    [int]$Port = 18096,
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = (Get-Command python -ErrorAction Stop).Source
$Health = "http://127.0.0.1:$Port/health"
$Existing = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue

if ($Existing) {
    try {
        $Response = Invoke-RestMethod -Uri $Health -TimeoutSec 3
        if ($Response.ok) {
            Write-Host "SceneGuard is already healthy at http://127.0.0.1:$Port/"
            exit 0
        }
    } catch {
        throw "Port $Port is in use by another process. Choose another port."
    }
}

$Arguments = @(
    "scripts/run_cli.py", "serve",
    "--host", "127.0.0.1",
    "--port", $Port,
    "--asset-root", "samples",
    "--profile-root", "profiles",
    "--jobs-root", "jobs"
)

if ($Foreground) {
    Set-Location -LiteralPath $ProjectRoot
    & $Python @Arguments
    exit $LASTEXITCODE
}

$Process = Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
    Start-Sleep -Milliseconds 250
    if ($Process.HasExited) {
        throw "SceneGuard exited before becoming healthy (exit code $($Process.ExitCode))."
    }
    try {
        $Response = Invoke-RestMethod -Uri $Health -TimeoutSec 2
        if ($Response.ok) {
            Write-Host "SceneGuard started: http://127.0.0.1:$Port/"
            Write-Host "Process ID: $($Process.Id)"
            exit 0
        }
    } catch {
        # The server may still be binding the loopback port.
    }
}

Stop-Process -Id $Process.Id -ErrorAction SilentlyContinue
throw "SceneGuard did not become healthy within 7.5 seconds."
