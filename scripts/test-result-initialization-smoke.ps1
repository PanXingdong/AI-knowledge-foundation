param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$InitScript = Join-Path $PSScriptRoot "initialize-results-from-tasks.ps1"
if (-not (Test-Path -LiteralPath $InitScript)) {
    Write-Error "Missing result initialization script: $InitScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-result-init-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$runDir = Join-Path $smokeRoot "run"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null

    @(
        [pscustomobject]@{ task_id = "task-smoke-001"; task_type = "constraint_lookup"; domain = "QNX adaptation"; task_description = "Find constraints."; allowed_documents = "doc-001;doc-002"; gold_answer_points = "constraint"; required_constraints = "constraint"; expected_evidence = "page span"; scorer = "scorer"; owner = "owner"; status = "ready"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-002"; task_type = "interface_lookup"; domain = "QNX adaptation"; task_description = "Find interface."; allowed_documents = "doc-003"; gold_answer_points = "interface"; required_constraints = "limit"; expected_evidence = "page span"; scorer = "scorer"; owner = "owner"; status = "ready"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-003"; task_type = "test_focus"; domain = "QNX adaptation"; task_description = "Find tests."; allowed_documents = "doc-002;doc-010"; gold_answer_points = "tests"; required_constraints = "coverage"; expected_evidence = "page span"; scorer = "scorer"; owner = "owner"; status = "ready"; notes = "smoke" }
    ) | Export-Csv -LiteralPath (Join-Path $runDir "agent-task-cases.csv") -NoTypeInformation -Encoding UTF8

    @(
        [pscustomobject]@{ task_id = "task-smoke-001"; task_type = "constraint_lookup"; real_source = "review"; monthly_frequency = "8"; has_gold_answer = "yes"; needs_evidence = "yes"; owner = "owner"; selected = "yes"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-002"; task_type = "interface_lookup"; real_source = "task"; monthly_frequency = "6"; has_gold_answer = "yes"; needs_evidence = "yes"; owner = "owner"; selected = "yes"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-003"; task_type = "test_focus"; real_source = "omission"; monthly_frequency = "5"; has_gold_answer = "yes"; needs_evidence = "yes"; owner = "owner"; selected = "yes"; notes = "smoke" }
    ) | Export-Csv -LiteralPath (Join-Path $runDir "scenario-selection-matrix.csv") -NoTypeInformation -Encoding UTF8

    $resultPath = Join-Path $runDir "baseline-vs-contextpack-results.csv"
    @(
        [pscustomobject]@{
            task_id = "placeholder"
            group = "baseline"
            agent = "TBD"
            source_docs = "TBD"
            answer_correct = "TBD"
            missed_constraints = "TBD"
            wrong_claims = "TBD"
            citation_correct = "TBD"
            token_cost = "TBD"
            elapsed_minutes = "TBD"
            human_fix_count = "TBD"
            context_pack_tokens = "N/A"
            retrieved_span_count = "N/A"
            useful_span_count = "N/A"
            irrelevant_span_count = "N/A"
            retrieval_failure = "N/A"
            notes = "placeholder"
        }
    ) | Export-Csv -LiteralPath $resultPath -NoTypeInformation -Encoding UTF8

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "RUN_DIR=$runDir"

    & powershell -ExecutionPolicy Bypass -File $InitScript -ExperimentDir $runDir
    $dryRunExitCode = $LASTEXITCODE
    if ($dryRunExitCode -ne 0) {
        $failureMessage = "Result initialization dry run failed with exit code $dryRunExitCode."
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        & powershell -ExecutionPolicy Bypass -File $InitScript -ExperimentDir $runDir -Apply
        $applyExitCode = $LASTEXITCODE
        if ($applyExitCode -ne 0) {
            $failureMessage = "Result initialization apply failed with exit code $applyExitCode."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        $rows = @(Import-Csv -LiteralPath $resultPath -Encoding UTF8)
        $baselineRows = @($rows | Where-Object { $_.group -eq "baseline" })
        $contextRows = @($rows | Where-Object { $_.group -eq "context_pack" })
        if ($rows.Count -ne 6) {
            $failureMessage = "Expected 6 result rows, found $($rows.Count)."
        }
        elseif ($baselineRows.Count -ne 3 -or $contextRows.Count -ne 3) {
            $failureMessage = "Expected 3 baseline and 3 context_pack rows, found baseline=$($baselineRows.Count), context_pack=$($contextRows.Count)."
        }
        elseif (@($rows | Where-Object { $_.answer_correct -ne "TBD" }).Count -gt 0) {
            $failureMessage = "Initialized rows should not contain scored results."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        Write-Host "RESULT_INITIALIZATION_SMOKE=PASS"
    }
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
    Write-Host "RESULT_INITIALIZATION_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
