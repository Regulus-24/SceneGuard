[CmdletBinding()]
param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

if (-not $SkipTests) {
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Unit tests failed." }
}

python scripts/verify_release_consistency.py --output reports/release-consistency.json
if ($LASTEXITCODE -ne 0) { throw "Cross-material consistency checks failed." }

python scripts/run_benchmark.py --target release --output reports/benchmark-latest.json
if ($LASTEXITCODE -eq 0) {
    Write-Host "SceneGuard P0 release gate: PASS"
    exit 0
}

Write-Host "SceneGuard engineering checks passed; inspect reports/benchmark-latest.json for truthful external blockers."
exit 2
