[CmdletBinding()]
param(
    [string]$MaterialsRoot,
    [string]$NodeExecutable,
    [string]$NodeModules
)

$ErrorActionPreference = "Stop"
trap {
    Write-Error $_
    exit 2
}
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $MaterialsRoot) {
    $MaterialsRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot "..\..\初赛交付_20260816"))
}
$Confirmation = Join-Path $MaterialsRoot "TEAM_CONFIRMATION.json"
$DraftMarker = [string]([char]0x5F85) + [char]0x56E2 + [char]0x961F + [char]0x786E + [char]0x8BA4
$FormalMarker = [string]([char]0x6B63) + [char]0x5F0F + [char]0x7248
$Draft = Get-ChildItem -LiteralPath $MaterialsRoot -Filter "SceneGuard_*v3_*.pptx" | Where-Object { $_.Name.Contains($DraftMarker) } | Select-Object -First 1 -ExpandProperty FullName

if (-not (Test-Path -LiteralPath $Confirmation -PathType Leaf)) {
    throw "TEAM_CONFIRMATION.json is missing. Copy the template only after all three members respond."
}
if (-not $Draft -or -not (Test-Path -LiteralPath $Draft -PathType Leaf)) {
    throw "The reviewed V3 draft PPTX is missing."
}

$NamePrefix = [System.IO.Path]::GetFileNameWithoutExtension($Draft)
$FormalPptx = Join-Path $MaterialsRoot (($NamePrefix.Substring(0, $NamePrefix.Length - $DraftMarker.Length)) + $FormalMarker + ".pptx")
$FormalPdf = [System.IO.Path]::ChangeExtension($FormalPptx, ".pdf")
$FormalZipName = "SceneGuard_" + [string]([char]0x521D) + [char]0x8D5B + [char]0x6B63 + [char]0x5F0F + [char]0x63D0 + [char]0x4EA4 + [char]0x5305 + ".zip"
$FormalZip = Join-Path $MaterialsRoot $FormalZipName

if (-not $NodeExecutable) {
    $UserProfilePath = [Environment]::GetFolderPath("UserProfile")
    $BundledNode = Join-Path $UserProfilePath ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
    $NodeExecutable = if (Test-Path -LiteralPath $BundledNode) { $BundledNode } else { (Get-Command node -ErrorAction Stop).Source }
}
if (-not $NodeModules) {
    $UserProfilePath = [Environment]::GetFolderPath("UserProfile")
    $BundledModules = Join-Path $UserProfilePath ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules"
    $WorkspaceModules = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot "..\..\..\tmp\initial-delivery-audit\v3-build\node_modules"))
    if (Test-Path -LiteralPath (Join-Path $WorkspaceModules "@oai\artifact-tool") -PathType Container) {
        $NodeModules = $WorkspaceModules
    } elseif (Test-Path -LiteralPath (Join-Path $BundledModules "@oai\artifact-tool") -PathType Container) {
        $NodeModules = $BundledModules
    } else {
        throw "Bundled artifact-tool modules were not found; pass -NodeModules explicitly."
    }
}
$ArtifactTool = Join-Path $NodeModules "@oai\artifact-tool\dist\artifact_tool.mjs"
if (-not (Test-Path -LiteralPath $ArtifactTool -PathType Leaf)) {
    throw "artifact-tool entrypoint was not found under NodeModules."
}

Push-Location -LiteralPath $ProjectRoot
try {
    python scripts/initial_submission_check.py --materials $MaterialsRoot --team-only
    if ($LASTEXITCODE -ne 0) { throw "Team confirmation validation failed." }

    & $NodeExecutable scripts/finalize_initial_deck.mjs --input $Draft --confirmation $Confirmation --output $FormalPptx --artifact-tool $ArtifactTool
    if ($LASTEXITCODE -ne 0) { throw "Formal PPTX generation failed." }
    $InspectReceipt = "$FormalPptx.inspect.ndjson"
    if (Test-Path -LiteralPath $InspectReceipt -PathType Leaf) {
        Remove-Item -LiteralPath $InspectReceipt
    }

    $PowerPoint = New-Object -ComObject PowerPoint.Application
    try {
        $Presentation = $PowerPoint.Presentations.Open($FormalPptx, $true, $false, $false)
        try {
            $Presentation.SaveAs($FormalPdf, 32)
        } finally {
            $Presentation.Close()
        }
    } finally {
        $PowerPoint.Quit()
    }

    python scripts/initial_submission_check.py --materials $MaterialsRoot
    if ($LASTEXITCODE -ne 0) { throw "Strict initial submission check failed." }
    python scripts/build_initial_materials_package.py --materials $MaterialsRoot --output $FormalZip
    if ($LASTEXITCODE -ne 0) { throw "Formal package generation failed." }
    python scripts/build_initial_materials_package.py --verify $FormalZip
    if ($LASTEXITCODE -ne 0) { throw "Formal package verification failed." }
    Write-Host "SceneGuard formal initial package is ready: $FormalZip"
} finally {
    Pop-Location
}
