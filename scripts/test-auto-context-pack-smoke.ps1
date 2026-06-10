param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$IngestScript = Join-Path $PSScriptRoot "ingest-documents.ps1"
$GenerateScript = Join-Path $PSScriptRoot "generate-auto-context-pack.ps1"

if (-not (Test-Path -LiteralPath $IngestScript)) {
    Write-Error "Missing ingest script: $IngestScript"
}
if (-not (Test-Path -LiteralPath $GenerateScript)) {
    Write-Error "Missing Context Pack script: $GenerateScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-auto-context-pack-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$rawDir = Join-Path $smokeRoot "raw"
$processedDir = Join-Path $smokeRoot "processed"
$outputDir = Join-Path $smokeRoot "auto-bundle"
$questionPath = Join-Path $smokeRoot "question.md"
$referencePath = Join-Path $smokeRoot "reference-context-pack.md"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $rawDir -Force | Out-Null

    $documents = @(
        @{
            FileName = "01-skill-mcp-runtime-architecture.md"
            Title = "01-skill-mcp-runtime-architecture"
            Content = @"
# Runtime Architecture

Phase-1 must use the third runtime option instead of skill/mcp or source embed.
skill/mcp is only acceptable for short PoC work.
source embed has high maintenance cost.
The runtime adapter abstraction hosts claude_code under a unified runtime layer.
"@
        },
        @{
            FileName = "02-backend-router-and-adapter.md"
            Title = "02-backend-router-and-adapter"
            Content = @"
# Backend Execution Chain

The runtime router dispatches each run to the correct runtime adapter.
The adapter prepares repo and worktree, builds execution args, receives the event stream, and writes back results.
Every failed run must keep run_id, error summary, status writeback, and manual retry support.
"@
        },
        @{
            FileName = "03-api-and-event-protocol.md"
            Title = "03-api-and-event-protocol"
            Content = @"
# API And Event Protocol

POST /runtime-profiles
GET /runtime-profiles
GET /runtime-runs/{run_id}/events
GET /runtime-runs/{run_id}/artifacts
websocket events include runtime_status, runtime_chunk, runtime_tool, runtime_artifact, runtime_requires_approval, runtime_done, and runtime_error.
"@
        },
        @{
            FileName = "04-governance-and-safety.md"
            Title = "04-governance-and-safety"
            Content = @"
# Governance And Safety

The default policy keeps the main repository read only.
Each run uses an isolated worktree.
Credentials are injected only by the backend and the runtime receives the minimum required token set.
The platform must forbid dangerously-skip-permissions and forbid background execution without run_id.
"@
        },
        @{
            FileName = "05-rollout-and-rollback.md"
            Title = "05-rollout-and-rollback"
            Content = @"
# Rollout And Rollback

Step one enables only one internal tenant.
Acceptance requires twenty stable executions plus correct failure writeback.
Rollback uses ENABLE_CLAUDE_CODE_RUNTIME=false.
Rollback disables new claude_code agents and stops router dispatch.
"@
        }
    )

    foreach ($document in $documents) {
        $filePath = Join-Path $rawDir $document.FileName
        Set-Content -LiteralPath $filePath -Value $document.Content -Encoding UTF8

        & powershell -ExecutionPolicy Bypass -File $IngestScript `
            -FilePath $filePath `
            -OutDir $processedDir `
            -Title $document.Title `
            -SourceType "internal design doc" `
            -Owner "smoke-checker" `
            -DocumentVersion "v1"
        if ($LASTEXITCODE -ne 0) {
            throw "Ingest smoke failed for $filePath with exit code $LASTEXITCODE."
        }
    }

    Set-Content -LiteralPath $questionPath -Encoding UTF8 -Value @"
# Question

If Claude Code runtime phase-1 only opens to one internal tenant, answer:

1. Why the final choice is the third runtime option instead of skill/mcp or source embed.
2. Which backend, api/event, test, and rollback capabilities are required in the minimum phase-1 scope.
3. Which isolation, approval, credential, audit, and governance rules must stay enabled by default.
4. What the rollout gate and rollback condition are.

Requirements:

- Answer only from the provided material.
- Keep architecture, scope, governance, rollout gate, and rollback strategy separate.
- Do not mix suggestions with hard phase-1 requirements.
"@

    Set-Content -LiteralPath $referencePath -Encoding UTF8 -Value @"
# Context Pack

- third runtime option is the phase-1 architecture choice
- runtime adapter and router are required
- GET /runtime-runs/{run_id}/events
- runtime_requires_approval
- main repository stays read only
- credentials come from backend injection
- ENABLE_CLAUDE_CODE_RUNTIME=false
"@

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "PROCESSED_DIR=$processedDir"
    Write-Host "OUTPUT_DIR=$outputDir"

    & powershell -ExecutionPolicy Bypass -File $GenerateScript `
        -ProcessedDir $processedDir `
        -QuestionPath $questionPath `
        -ReferenceContextPackPath $referencePath `
        -OutputDir $outputDir `
        -TopK 10 `
        -PerDocumentLimit 3
    $generateExitCode = $LASTEXITCODE
    if ($generateExitCode -ne 0) {
        throw "Auto Context Pack smoke failed with exit code $generateExitCode."
    }

    $requiredFiles = @(
        (Join-Path $outputDir "context_pack.md"),
        (Join-Path $outputDir "context_pack.json"),
        (Join-Path $outputDir "context_pack-summary.json"),
        (Join-Path $outputDir "gap-report\context_pack_gap_report.md"),
        (Join-Path $outputDir "gap-report\context_pack_gap_report.json")
    )
    foreach ($requiredFile in $requiredFiles) {
        if (-not (Test-Path -LiteralPath $requiredFile)) {
            throw "Missing expected output file: $requiredFile"
        }
    }

    $summary = Get-Content -LiteralPath (Join-Path $outputDir "context_pack-summary.json") -Raw | ConvertFrom-Json
    $gapReport = Get-Content -LiteralPath (Join-Path $outputDir "gap-report\context_pack_gap_report.json") -Raw | ConvertFrom-Json
    $markdown = Get-Content -LiteralPath (Join-Path $outputDir "context_pack.md") -Raw

    if ([int]$summary.document_count -lt 5) {
        throw "Expected document_count >= 5, actual=$($summary.document_count)"
    }
    if ([int]$gapReport.missing_reference_item_count -ne 0) {
        $missingItems = ($gapReport.missing_reference_items -join "; ")
        throw "Expected no missing reference items, actual=$($gapReport.missing_reference_item_count): $missingItems"
    }
    if ($markdown -notmatch "03-api-and-event-protocol") {
        throw "Context Pack markdown did not include API evidence."
    }
    if ($markdown -notmatch "runtime_requires_approval") {
        throw "Context Pack markdown did not include runtime event evidence."
    }
    if ($markdown -notmatch "04-governance-and-safety") {
        throw "Context Pack markdown did not include governance evidence."
    }

    Write-Host "AUTO_CONTEXT_PACK_SMOKE=PASS"
}
catch {
    $failureMessage = $_.Exception.Message
}
finally {
    if ($KeepArtifacts) {
        Write-Host "SMOKE_ARTIFACTS_KEPT=$smokeRoot"
    }
    elseif (Test-Path -LiteralPath $smokeRoot) {
        Remove-Item -LiteralPath $smokeRoot -Recurse -Force
        Write-Host "SMOKE_ARTIFACTS_CLEANED=$smokeRoot"
    }
}

if (-not [string]::IsNullOrWhiteSpace($failureMessage)) {
    Write-Host "AUTO_CONTEXT_PACK_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
