param(
    [string]$RunId,
    [string]$DocumentIntakePath,
    [string]$TaskIntakePath,
    [string]$RawDir,
    [string]$ManifestPath,
    [switch]$Apply,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "run-" + (Get-Date -Format "yyyyMMdd-HHmmss")
}

if ($RunId -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]*$") {
    Write-Error "Invalid RunId. Use only letters, numbers, dot, underscore, and hyphen."
}

if ([string]::IsNullOrWhiteSpace($DocumentIntakePath)) {
    $DocumentIntakePath = Join-Path $ProjectRoot "samples\document-intake-template.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($DocumentIntakePath)) {
    $DocumentIntakePath = Join-Path $ProjectRoot $DocumentIntakePath
}

if ([string]::IsNullOrWhiteSpace($TaskIntakePath)) {
    $TaskIntakePath = Join-Path $ProjectRoot "experiments\templates\task-intake-template.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($TaskIntakePath)) {
    $TaskIntakePath = Join-Path $ProjectRoot $TaskIntakePath
}

if ([string]::IsNullOrWhiteSpace($RawDir)) {
    $RawDir = Join-Path $ProjectRoot "samples\raw"
}
elseif (-not [System.IO.Path]::IsPathRooted($RawDir)) {
    $RawDir = Join-Path $ProjectRoot $RawDir
}

if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $ProjectRoot "samples\sample-manifest.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($ManifestPath)) {
    $ManifestPath = Join-Path $ProjectRoot $ManifestPath
}

$RunDir = Join-Path (Join-Path $ProjectRoot "experiments\runs") $RunId

function Invoke-ProjectScript {
    param(
        [string]$ScriptName,
        [string[]]$Arguments
    )

    $scriptPath = Join-Path $PSScriptRoot $ScriptName
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        Write-Error "Missing script: $scriptPath"
    }

    & powershell -ExecutionPolicy Bypass -File $scriptPath @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Error "$ScriptName failed with exit code $exitCode."
    }
}

Write-Host "Agent Knowledge Hub experiment run preparation"
Write-Host "Project root: $ProjectRoot"
Write-Host "RunId: $RunId"
Write-Host "Run dir: $RunDir"
Write-Host "Document intake: $DocumentIntakePath"
Write-Host "Task intake: $TaskIntakePath"
Write-Host "Raw dir: $RawDir"
Write-Host "Manifest: $ManifestPath"
Write-Host "Mode: $(if ($Apply) { 'apply' } else { 'dry run' })"
Write-Host ""

Invoke-ProjectScript "check-intake-readiness.ps1" @(
    "-Strict",
    "-DocumentIntakePath", $DocumentIntakePath,
    "-TaskIntakePath", $TaskIntakePath
)

if (-not $Apply) {
    Write-Host ""
    Write-Host "PREPARE_EXPERIMENT_RUN_DRY_RUN=PASS"
    Write-Host "Readiness passed. Re-run with -Apply to copy documents, create/reuse the run, apply tasks, and run strict preflight."
    exit 0
}

$documentApplyArgs = @(
    "-Apply",
    "-DocumentIntakePath", $DocumentIntakePath,
    "-RawDir", $RawDir,
    "-ManifestPath", $ManifestPath
)
if ($Force) {
    $documentApplyArgs += "-Force"
}
Invoke-ProjectScript "apply-document-intake-to-samples.ps1" $documentApplyArgs

if (Test-Path -LiteralPath $RunDir) {
    if (-not $Force) {
        Write-Error "Run directory already exists. Use -Force to reuse and overwrite placeholder task files: $RunDir"
    }

    Write-Host "Run directory already exists; reusing because -Force was provided: $RunDir"
}
else {
    Invoke-ProjectScript "new-experiment-run.ps1" @("-RunId", $RunId)
}

$parserInitArgs = @(
    "-RunId", $RunId,
    "-SampleManifestPath", $ManifestPath,
    "-Apply"
)
if ($Force) {
    $parserInitArgs += "-Force"
}
Invoke-ProjectScript "initialize-parser-evaluation-from-manifest.ps1" $parserInitArgs

$taskApplyArgs = @(
    "-RunId", $RunId,
    "-TaskIntakePath", $TaskIntakePath
)
if ($Force) {
    $taskApplyArgs += "-Force"
}
Invoke-ProjectScript "apply-task-intake-to-run.ps1" $taskApplyArgs

$resultInitArgs = @(
    "-RunId", $RunId,
    "-Apply"
)
Invoke-ProjectScript "initialize-results-from-tasks.ps1" $resultInitArgs

$promptInitArgs = @(
    "-RunId", $RunId,
    "-Apply"
)
if ($Force) {
    $promptInitArgs += "-Force"
}
Invoke-ProjectScript "initialize-agent-prompts-from-tasks.ps1" $promptInitArgs

$runLogInitArgs = @(
    "-RunId", $RunId,
    "-Apply"
)
if ($Force) {
    $runLogInitArgs += "-Force"
}
Invoke-ProjectScript "initialize-agent-run-log-from-tasks.ps1" $runLogInitArgs

Invoke-ProjectScript "preflight.ps1" @(
    "-StrictRealInputs",
    "-ExperimentDir", $RunDir,
    "-SampleManifestPath", $ManifestPath,
    "-SampleRawDir", $RawDir
)

Write-Host ""
Write-Host "PREPARE_EXPERIMENT_RUN_APPLY=PASS"
Write-Host "READY_TO_RUN_BASELINE_AND_CONTEXT_PACK"

exit 0
