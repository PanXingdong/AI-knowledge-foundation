param(
    [Parameter(Mandatory = $true)]
    [string]$PackagePath,
    [string]$RunId,
    [string]$DocumentIntakePath,
    [string]$TaskIntakePath,
    [string]$IncomingDocsDir,
    [string]$RawDir,
    [string]$ManifestPath,
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [string]$Owner,
    [switch]$Apply,
    [switch]$Force,
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Resolve-ProjectPath {
    param(
        [string]$Value,
        [string]$DefaultRelativePath
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        if ([string]::IsNullOrWhiteSpace($DefaultRelativePath)) {
            return $null
        }

        return Join-Path $ProjectRoot $DefaultRelativePath
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    return Join-Path $ProjectRoot $Value
}

function Invoke-ProjectScript {
    param(
        [string]$ScriptName,
        [string[]]$Arguments
    )

    $scriptPath = Join-Path $PSScriptRoot $ScriptName
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        Write-Error "Missing script: $scriptPath"
    }

    & powershell -ExecutionPolicy Bypass -File $scriptPath @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Error "$ScriptName failed with exit code $exitCode."
    }
}

if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "run-" + (Get-Date -Format "yyyyMMdd-HHmmss")
}

if ($RunId -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]*$") {
    Write-Error "Invalid RunId. Use only letters, numbers, dot, underscore, and hyphen."
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$PackagePath = Resolve-ProjectPath $PackagePath $null
$DocumentIntakePath = Resolve-ProjectPath $DocumentIntakePath "samples\document-intake-template.csv"
$TaskIntakePath = Resolve-ProjectPath $TaskIntakePath "experiments\templates\task-intake-template.csv"
$ManifestPath = Resolve-ProjectPath $ManifestPath "samples\sample-manifest.csv"
$RawDir = Resolve-ProjectPath $RawDir "samples\raw"

$RunDir = Join-Path (Join-Path $ProjectRoot "experiments\runs") $RunId
$workRoot = $null

try {
    if ($Apply) {
        $workDocumentIntakePath = $DocumentIntakePath
        $workTaskIntakePath = $TaskIntakePath
        $workManifestPath = $ManifestPath
        $workRawDir = $RawDir
        $workIncomingDocsDir = Resolve-ProjectPath $IncomingDocsDir $null
    }
    else {
        $workRoot = Join-Path $ArtifactRoot ("akh-owner-package-to-run-dry-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
        New-Item -ItemType Directory -Path $workRoot -Force | Out-Null

        $workDocumentIntakePath = Join-Path $workRoot "document-intake.csv"
        $workTaskIntakePath = Join-Path $workRoot "task-intake.csv"
        $workManifestPath = Join-Path $workRoot "sample-manifest.csv"
        $workRawDir = Join-Path $workRoot "raw"
        $workIncomingDocsDir = Join-Path $workRoot "incoming-docs"

        Copy-Item -LiteralPath $DocumentIntakePath -Destination $workDocumentIntakePath -Force
        Copy-Item -LiteralPath $TaskIntakePath -Destination $workTaskIntakePath -Force
        Copy-Item -LiteralPath $ManifestPath -Destination $workManifestPath -Force
    }

    Write-Host "Agent Knowledge Hub owner package to experiment run"
    Write-Host "Project root: $ProjectRoot"
    Write-Host "Package path: $PackagePath"
    Write-Host "RunId: $RunId"
    Write-Host "Run dir: $RunDir"
    Write-Host "Document intake: $workDocumentIntakePath"
    Write-Host "Task intake: $workTaskIntakePath"
    Write-Host "Incoming docs dir: $(if ([string]::IsNullOrWhiteSpace($workIncomingDocsDir)) { '<import-script-default>' } else { $workIncomingDocsDir })"
    Write-Host "Raw dir: $workRawDir"
    Write-Host "Manifest: $workManifestPath"
    Write-Host "Mode: $(if ($Apply) { 'apply' } else { 'dry run' })"
    Write-Host ""

    $importArgs = @(
        "-PackagePath", $PackagePath,
        "-DocumentIntakePath", $workDocumentIntakePath,
        "-TaskIntakePath", $workTaskIntakePath,
        "-Apply"
    )
    if (-not [string]::IsNullOrWhiteSpace($workIncomingDocsDir)) {
        $importArgs += @("-IncomingDocsDir", $workIncomingDocsDir)
    }
    if (-not [string]::IsNullOrWhiteSpace($Owner)) {
        $importArgs += @("-Owner", $Owner)
    }
    if ($Force) {
        $importArgs += "-Force"
    }
    if ($KeepArtifacts) {
        $importArgs += "-KeepExtracted"
    }

    Invoke-ProjectScript "import-owner-package.ps1" $importArgs

    $prepareArgs = @(
        "-RunId", $RunId,
        "-DocumentIntakePath", $workDocumentIntakePath,
        "-TaskIntakePath", $workTaskIntakePath,
        "-RawDir", $workRawDir,
        "-ManifestPath", $workManifestPath
    )
    if ($Apply) {
        $prepareArgs += "-Apply"
    }
    if ($Force) {
        $prepareArgs += "-Force"
    }

    Invoke-ProjectScript "prepare-experiment-run-from-intake.ps1" $prepareArgs

    Write-Host ""
    if ($Apply) {
        Write-Host "OWNER_PACKAGE_TO_RUN_APPLY=PASS"
        Write-Host "READY_TO_RUN_BASELINE_AND_CONTEXT_PACK"
    }
    else {
        Write-Host "OWNER_PACKAGE_TO_RUN_DRY_RUN=PASS"
        Write-Host "Dry run used temporary intake files only. Re-run with -Apply to update project intake files and create the experiment run."
    }
}
finally {
    if (-not $Apply -and -not $KeepArtifacts -and $null -ne $workRoot -and (Test-Path -LiteralPath $workRoot)) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force
        Write-Host "DRY_RUN_ARTIFACTS_CLEANED=$workRoot"
    }
    elseif (-not $Apply -and $KeepArtifacts -and $null -ne $workRoot) {
        Write-Host "DRY_RUN_ARTIFACTS_KEPT=$workRoot"
    }
}

exit 0
