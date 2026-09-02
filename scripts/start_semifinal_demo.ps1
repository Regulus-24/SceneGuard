[CmdletBinding()]
param(
    [ValidateSet("Quick", "AgentTeams")]
    [string]$Mode = "Quick",
    [int]$Port = 18096,
    [string]$RunId,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = (Get-Command python -ErrorAction Stop).Source
$GatewayProcess = $null
$TokenInstalled = $false
$AgentContainers = @(
    "hiclaw-worker-sceneguard-auto-v1-leader",
    "hiclaw-worker-sgauto-asset-auditor",
    "hiclaw-worker-sgauto-repair-planner",
    "hiclaw-worker-sgauto-repair-executor",
    "hiclaw-worker-sgauto-regression-verifier"
)

function Wait-SceneGuardHealth {
    param([string]$Url, [System.Diagnostics.Process]$Process)
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        Start-Sleep -Milliseconds 250
        if ($Process.HasExited) {
            throw "SceneGuard exited before becoming healthy (exit code $($Process.ExitCode))."
        }
        try {
            $Response = Invoke-RestMethod -Uri "$Url/health" -TimeoutSec 2
            if ($Response.ok) { return }
        } catch {
            # The server may still be binding its port.
        }
    }
    throw "SceneGuard did not become healthy within 10 seconds."
}

function Assert-PortAvailable {
    param([int]$LocalPort)
    if (Get-NetTCPConnection -State Listen -LocalPort $LocalPort -ErrorAction SilentlyContinue) {
        throw "Port $LocalPort is already in use. Stop the existing service or select another Quick-mode port."
    }
}

function Remove-AgentTokenFiles {
    foreach ($Container in $AgentContainers) {
        & docker exec $Container sh -c 'rm -f /opt/sceneguard-tools/.gateway-token' 2>$null | Out-Null
    }
}

Set-Location -LiteralPath $ProjectRoot

if ($Mode -eq "Quick") {
    Assert-PortAvailable -LocalPort $Port
    $GatewayArguments = @(
        "scripts/run_cli.py", "serve",
        "--host", "127.0.0.1",
        "--port", $Port,
        "--asset-root", "samples",
        "--profile-root", "profiles",
        "--jobs-root", ".semifinal-demo-jobs"
    )
    $GatewayProcess = Start-Process -FilePath $Python -ArgumentList $GatewayArguments -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
    Wait-SceneGuardHealth -Url "http://127.0.0.1:$Port" -Process $GatewayProcess

    $Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $SmokeReport = "reports/semifinal-demo-smoke-$Timestamp.json"
    & $Python scripts/run_demo_smoke.py --base-url "http://127.0.0.1:$Port" --output $SmokeReport
    Copy-Item -LiteralPath $SmokeReport -Destination "reports/semifinal-demo-smoke-latest.json" -Force
    if ($LASTEXITCODE -ne 0) {
        Stop-Process -Id $GatewayProcess.Id -ErrorAction SilentlyContinue
        throw "Quick Demo smoke test failed. See $SmokeReport"
    }

    Write-Host ""
    Write-Host "SceneGuard Quick Demo is ready: http://127.0.0.1:$Port/"
    Write-Host "Smoke evidence: $SmokeReport"
    Write-Host "Stable evidence: reports/semifinal-demo-smoke-latest.json"
    Write-Host "Gateway PID: $($GatewayProcess.Id)"
    Write-Host "Stop after the rehearsal with: Stop-Process -Id $($GatewayProcess.Id)"
    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:$Port/"
    }
    exit 0
}

if ($PSBoundParameters.ContainsKey("Port") -and $Port -ne 18091) {
    throw "AgentTeams mode requires port 18091 because the validated container bridge is frozen to that endpoint."
}
$Port = 18091
Assert-PortAvailable -LocalPort $Port
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "semifinal-live-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
}
if ($RunId -notmatch '^[A-Za-z0-9_-]+$') {
    throw "RunId must match [A-Za-z0-9_-]+."
}
if (Test-Path -LiteralPath "jobs/.agentteams-native/$RunId") {
    throw "RunId already exists and is immutable: $RunId"
}

try {
    & docker version --format '{{.Server.Version}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Docker Engine is unavailable." }

    $TokenBytes = New-Object byte[] 32
    $Random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $Random.GetBytes($TokenBytes) } finally { $Random.Dispose() }
    $Token = ([BitConverter]::ToString($TokenBytes)).Replace("-", "")
    foreach ($Container in $AgentContainers) {
        & docker exec $Container mkdir -p /opt/sceneguard-tools | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Agent container is unavailable: $Container" }
        $Token | & docker exec -i $Container sh -c 'umask 077; tr -d "\r\n" > /opt/sceneguard-tools/.gateway-token'
        if ($LASTEXITCODE -ne 0) { throw "Cannot install the temporary gateway token in $Container" }
    }
    $TokenInstalled = $true

    $PreviousToken = $env:SCENEGUARD_DEMO_TOKEN
    $env:SCENEGUARD_DEMO_TOKEN = $Token
    $GatewayArguments = @(
        "scripts/run_cli.py", "serve",
        "--host", "0.0.0.0",
        "--port", 18091,
        "--asset-root", "samples",
        "--profile-root", "profiles",
        "--jobs-root", "jobs",
        "--api-token-env", "SCENEGUARD_DEMO_TOKEN"
    )
    $GatewayProcess = Start-Process -FilePath $Python -ArgumentList $GatewayArguments -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
    if ($null -eq $PreviousToken) {
        Remove-Item Env:SCENEGUARD_DEMO_TOKEN -ErrorAction SilentlyContinue
    } else {
        $env:SCENEGUARD_DEMO_TOKEN = $PreviousToken
    }
    Wait-SceneGuardHealth -Url "http://127.0.0.1:18091" -Process $GatewayProcess

    Write-Host "Running the validated 1 TeamLeader + 4 Worker chain: $RunId"
    & $Python scripts/run_agentteams_native_supervisor.py --run-id $RunId --job-id $RunId --project-id $RunId
    if ($LASTEXITCODE -ne 0) { throw "AgentTeams Demo failed. The immutable evidence remains under jobs/.agentteams-native/$RunId" }

    Write-Host ""
    Write-Host "SceneGuard AgentTeams Demo completed."
    Write-Host "Agent evidence: jobs/.agentteams-native/$RunId/run-result.json"
    Write-Host "Business evidence: jobs/$RunId/artifacts/"
} finally {
    if ($GatewayProcess -and -not $GatewayProcess.HasExited) {
        Stop-Process -Id $GatewayProcess.Id -ErrorAction SilentlyContinue
    }
    if ($TokenInstalled) { Remove-AgentTokenFiles }
}
