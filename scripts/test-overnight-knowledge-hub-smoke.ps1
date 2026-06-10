[CmdletBinding()]
param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts")
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$overnightScript = Join-Path $scriptDir "run-overnight-knowledge-hub.ps1"
$pythonExe = ""
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $pythonExe = & py -3.12 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1
}
if ([string]::IsNullOrWhiteSpace($pythonExe)) {
    $pythonExe = (Get-Command python).Definition
}

$output = & powershell -ExecutionPolicy Bypass -File $overnightScript `
    -ArtifactRoot $ArtifactRoot `
    -PythonExe $pythonExe `
    -MaxFiles 5 `
    -SampleSize 3 `
    -MaxFileMb 5 `
    -IncludeKeyword "internal","review","architecture" `
    -ExcludeKeyword "account","password" `
    -UseSyntheticFallback
if ($LASTEXITCODE -ne 0) {
    throw "Overnight smoke failed with exit code $LASTEXITCODE."
}

$summaryLine = $output | Where-Object { $_ -like "{*" } | Select-Object -Last 1
if (-not $summaryLine) {
    throw "Overnight smoke did not emit a JSON summary."
}
$summary = $summaryLine | ConvertFrom-Json
$requiredPaths = @(
    (Join-Path $summary.dependency_dir "runtime-dependencies.json"),
    (Join-Path $summary.dependency_dir "runtime-dependencies.md"),
    (Join-Path $summary.inventory_dir "document-inventory.json"),
    (Join-Path $summary.inventory_dir "raw-docs-sample-manifest.csv"),
    (Join-Path $summary.processed_dir "ingest-run-summary.json"),
    (Join-Path $summary.quality_dir "parse-quality-summary.json"),
    (Join-Path $summary.context_dir "constraint-query\context_pack.json"),
    (Join-Path $summary.trace_dir "first-evidence-trace.json"),
    (Join-Path $summary.eval_dir "eval-report.json"),
    (Join-Path $summary.eval_dir "eval_cases.jsonl"),
    (Join-Path $summary.eval_run_dir "agent-prompt-manifest.csv"),
    (Join-Path $summary.eval_run_dir "agent-run-log.csv"),
    (Join-Path $summary.eval_run_dir "real-agent-execution-plan.json"),
    (Join-Path $summary.eval_run_dir "real-agent-execution-guide.md"),
    (Join-Path $summary.eval_run_dir "baseline-vs-contextpack-results.csv"),
    (Join-Path $summary.eval_run_dir "eval-score-summary.json"),
    (Join-Path $summary.eval_run_dir "eval-score-details.jsonl"),
    (Join-Path $summary.eval_score_dir "eval-score-summary.json"),
    (Join-Path $summary.eval_score_dir "eval-score-summary.md"),
    (Join-Path $summary.eval_score_dir "eval-score-details.jsonl"),
    (Join-Path $summary.eval_run_dir "prompts\constraint-query-baseline.md"),
    (Join-Path $summary.eval_run_dir "prompts\constraint-query-context_pack.md")
)

if ([string]::IsNullOrWhiteSpace($summary.python_exe)) {
    throw "Overnight smoke summary did not record python_exe."
}

foreach ($path in $requiredPaths) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing expected artifact: $path"
    }
}

$eval = Get-Content -LiteralPath (Join-Path $summary.eval_dir "eval-report.json") -Raw | ConvertFrom-Json
if ($eval.context_pack_cases_with_evidence -lt 1) {
    throw "Expected at least one Context Pack case with evidence."
}

$score = Get-Content -LiteralPath (Join-Path $summary.eval_score_dir "eval-score-summary.json") -Raw | ConvertFrom-Json
if ($score.context_pack_win_count -lt 1) {
    throw "Expected at least one simulated Context Pack scoring win."
}
if ($score.simulated_output_count -lt 1 -or -not $score.uses_simulated_outputs) {
    throw "Expected overnight scoring to mark simulated smoke outputs explicitly."
}
$scoreDetails = Get-Content -LiteralPath (Join-Path $summary.eval_score_dir "eval-score-details.jsonl") -Raw
if ($scoreDetails -notmatch '"simulated_output": true') {
    throw "Expected score details to include simulated_output=true."
}

$runLogText = Get-Content -LiteralPath (Join-Path $summary.eval_run_dir "agent-run-log.csv") -Raw
if ($runLogText -notmatch "simulated_smoke_output") {
    throw "Expected agent-run-log.csv to mark simulated_smoke_output rows."
}

$executionGuide = Get-Content -LiteralPath (Join-Path $summary.eval_run_dir "real-agent-execution-guide.md") -Raw
if ($executionGuide -notmatch "--require-business-evidence") {
    throw "Expected real Agent execution guide to include strict business-evidence scoring command."
}

Write-Output "overnight knowledge hub smoke passed"
