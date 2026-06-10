param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$IngestScript = Join-Path $PSScriptRoot "ingest-documents.ps1"
$QualityScript = Join-Path $PSScriptRoot "generate-parse-quality-summary.ps1"

if (-not (Test-Path -LiteralPath $IngestScript)) {
    Write-Error "Missing ingest script: $IngestScript"
}
if (-not (Test-Path -LiteralPath $QualityScript)) {
    Write-Error "Missing quality summary script: $QualityScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-parse-quality-summary-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$rawDir = Join-Path $smokeRoot "raw"
$processedDir = Join-Path $smokeRoot "processed"
$qualityDir = Join-Path $smokeRoot "quality"
$manifestPath = Join-Path $smokeRoot "manifest.csv"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $rawDir -Force | Out-Null

    $goodDoc = Join-Path $rawDir "architecture.md"
    Set-Content -LiteralPath $goodDoc -Encoding UTF8 -Value @"
# Architecture

The first phase uses a runtime adapter and keeps the main repository read only.
This document is intentionally long enough to pass parse quality gates and enter Context Pack retrieval.
"@

    $shortDoc = Join-Path $rawDir "short.txt"
    Set-Content -LiteralPath $shortDoc -Encoding UTF8 -Value "short"

    $legacyDoc = Join-Path $rawDir "legacy.doc"
    Set-Content -LiteralPath $legacyDoc -Encoding UTF8 -Value "legacy placeholder"

    Set-Content -LiteralPath $manifestPath -Encoding UTF8 -Value @"
sample_id,file_path,document_title,slot_type,owner,project,supplier,document_version
doc-001,$goodDoc,Architecture,internal design,smoke,quality-smoke,internal,v1
doc-002,$shortDoc,Short Note,internal note,smoke,quality-smoke,internal,v1
doc-003,$legacyDoc,Legacy Word,supplier doc,smoke,quality-smoke,unknown,legacy
"@

    & powershell -ExecutionPolicy Bypass -File $IngestScript `
        -ManifestPath $manifestPath `
        -OutDir $processedDir
    if ($LASTEXITCODE -ne 0) {
        throw "Ingest smoke failed with exit code $LASTEXITCODE."
    }

    & powershell -ExecutionPolicy Bypass -File $QualityScript `
        -ProcessedDir $processedDir `
        -OutputDir $qualityDir
    if ($LASTEXITCODE -ne 0) {
        throw "Parse quality summary smoke failed with exit code $LASTEXITCODE."
    }

    $jsonPath = Join-Path $qualityDir "parse-quality-summary.json"
    $markdownPath = Join-Path $qualityDir "parse-quality-summary.md"
    if (-not (Test-Path -LiteralPath $jsonPath)) {
        throw "Missing parse-quality-summary.json"
    }
    if (-not (Test-Path -LiteralPath $markdownPath)) {
        throw "Missing parse-quality-summary.md"
    }

    $summary = Get-Content -LiteralPath $jsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$summary.processed_document_count -ne 2) {
        throw "Expected processed_document_count=2, actual=$($summary.processed_document_count)"
    }
    if ([int]$summary.failed_input_count -ne 1) {
        throw "Expected failed_input_count=1, actual=$($summary.failed_input_count)"
    }
    if ([int]$summary.status_counts.ok -ne 1) {
        throw "Expected one ok document."
    }
    if ([int]$summary.status_counts.low_quality -ne 1) {
        throw "Expected one low_quality document."
    }
    if ([int]$summary.status_counts.unsupported -ne 1) {
        throw "Expected one unsupported input."
    }

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "QUALITY_DIR=$qualityDir"
    Write-Host "Parse quality summary smoke passed."
}
catch {
    $failureMessage = $_.Exception.Message
    throw
}
finally {
    if (-not $KeepArtifacts -and (Test-Path -LiteralPath $smokeRoot)) {
        Remove-Item -LiteralPath $smokeRoot -Recurse -Force
    }
    elseif ($failureMessage) {
        Write-Host "Artifacts kept for debugging: $smokeRoot"
    }
}
