[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$')][string]$TaskId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$')][string]$JobId,
    [string]$Team = 'sceneguard-real',
    [string]$ManagerContainer = 'hiclaw-manager',
    [string]$SpecRelative = 'at\tasks\p0-autonomous-staged-repair.md'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Spec = Join-Path $ProjectRoot $SpecRelative
if (-not (Test-Path -LiteralPath $Spec)) { throw "Missing task spec: $Spec" }

docker version --format '{{.Server.Version}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker engine is unavailable.' }

$Teams = docker exec $ManagerContainer hiclaw get teams -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Unable to query HiClaw teams.' }
$SelectedTeam = $Teams.teams | Where-Object { $_.name -eq $Team }
if (-not $SelectedTeam -or $SelectedTeam.phase -ne 'Active' -or $SelectedTeam.readyWorkers -ne 4) {
    throw "Team $Team must be Active with exactly four ready business Workers."
}

$Workers = docker exec $ManagerContainer hiclaw get workers -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Unable to query HiClaw workers.' }
$Leader = $Workers.workers | Where-Object {
    $_.name -eq $SelectedTeam.leaderName -and $_.team -eq $Team -and $_.role -eq 'team_leader'
} | Select-Object -First 1
if (-not $Leader -or -not $Leader.roomID -or $Leader.containerState -ne 'running') {
    throw "TeamLeader for $Team is not ready."
}

$CreatedAt = Get-Date -Format o
$Meta = [ordered]@{
    task_id = $TaskId
    title = 'SceneGuard P0 zero-operator autonomous repair acceptance'
    type = 'finite'
    assigned_to = $Leader.name
    delegated_to_team = $Team
    job_id = $JobId
    status = 'assigned'
    created_at = $CreatedAt
    acceptance_contract = 'at/automation-contract.v0.1.json'
    pre_dispatch_storage = @("global-shared/tasks/$TaskId/")
}
$TempDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("sceneguard-dispatch-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $TempDirectory | Out-Null
try {
    $MetaPath = Join-Path $TempDirectory 'meta.json'
    $Meta | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $MetaPath -Encoding utf8
    docker cp $Spec "${ManagerContainer}:/tmp/sceneguard-p0-spec.md" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to stage task spec in Manager.' }
    docker cp $MetaPath "${ManagerContainer}:/tmp/sceneguard-p0-meta.json" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to stage task metadata in Manager.' }

    $Prepare = @"
set -eu
dir=/root/hiclaw-fs/shared/tasks/$TaskId
mkdir -p "`$dir"
cp /tmp/sceneguard-p0-spec.md "`$dir/spec.md"
cp /tmp/sceneguard-p0-meta.json "`$dir/meta.json"
mc mirror "`$dir/" "hiclaw/hiclaw-storage/shared/tasks/$TaskId/" --overwrite >/dev/null
mc stat "hiclaw/hiclaw-storage/shared/tasks/$TaskId/spec.md" >/dev/null
mc stat "hiclaw/hiclaw-storage/shared/tasks/$TaskId/meta.json" >/dev/null
"@
    $Prepare = $Prepare -replace "`r", ""
    docker exec $ManagerContainer sh -lc $Prepare
    if ($LASTEXITCODE -ne 0) { throw 'Pre-dispatch staging failed; no task message was sent.' }

    $TargetUser = "@$($Leader.name):matrix-local.hiclaw.io:18080"
    $Message = "$TargetUser New finite task ${TaskId}: SceneGuard P0 zero-operator autonomous repair acceptance. This is Manager/global input: first pull global-shared/tasks/${TaskId}/ using the current file-sharing contract, then read spec.md and meta.json. Use fixed job_id ${JobId}. Create a Project, decompose and assign to your 4 team Workers. No operator recovery is allowed after this dispatch. Write final result.md and mention Manager only on completion or blocker."
    docker exec $ManagerContainer /opt/copaw-venv/bin/copaw channels send --agent-id default --channel matrix --target-user $TargetUser --target-session $Leader.roomID --text $Message
    if ($LASTEXITCODE -ne 0) { throw 'Matrix dispatch failed.' }
    Write-Host "Dispatched $TaskId to $($Leader.name). Do not alter task inputs after this point."
} finally {
    $ResolvedTemp = [System.IO.Path]::GetFullPath($TempDirectory)
    $ResolvedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($ResolvedTemp.StartsWith($ResolvedTempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $ResolvedTemp).StartsWith('sceneguard-dispatch-')) {
        Remove-Item -LiteralPath $ResolvedTemp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
