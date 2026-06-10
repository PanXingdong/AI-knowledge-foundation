param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$ReadinessScript = Join-Path $PSScriptRoot "check-run-evidence-readiness.ps1"
if (-not (Test-Path -LiteralPath $ReadinessScript)) {
    Write-Error "Missing run evidence readiness script: $ReadinessScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-run-evidence-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$runDir = Join-Path $smokeRoot "run"
$promptBaselineDir = Join-Path $runDir "prompts\baseline"
$promptContextPackDir = Join-Path $runDir "prompts\context_pack"
$rawOutputDir = Join-Path $runDir "raw-outputs"
$reportPath = Join-Path $smokeRoot "readiness-report.md"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $promptBaselineDir -Force | Out-Null
    New-Item -ItemType Directory -Path $promptContextPackDir -Force | Out-Null
    New-Item -ItemType Directory -Path $rawOutputDir -Force | Out-Null

    $taskIds = @("task-smoke-001", "task-smoke-002", "task-smoke-003")

    @(
        [pscustomobject]@{ task_id = "task-smoke-001"; task_type = "constraint_lookup"; domain = "QNX adaptation"; task_description = "Find startup ordering constraints for a QNX service."; allowed_documents = "doc-smoke-001;doc-smoke-002"; gold_answer_points = "identify dependency ready state and timeout behavior"; required_constraints = "cite service ordering and timeout constraints"; expected_evidence = "document title and page span"; scorer = "smoke-scorer"; owner = "smoke-owner"; status = "ready"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-002"; task_type = "interface_mechanism_lookup"; domain = "QNX adaptation"; task_description = "Locate IPC mechanism constraints relevant to module integration."; allowed_documents = "doc-smoke-001;doc-smoke-003"; gold_answer_points = "identify IPC mechanism and limitation"; required_constraints = "cite mechanism and limitation"; expected_evidence = "document title and page span"; scorer = "smoke-scorer"; owner = "smoke-owner"; status = "ready"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-003"; task_type = "test_focus_generation"; domain = "QNX adaptation"; task_description = "Generate test focus points for startup and IPC changes."; allowed_documents = "doc-smoke-002;doc-smoke-003;doc-smoke-010"; gold_answer_points = "include cold start dependency delay and IPC failure"; required_constraints = "cite constraints that drive tests"; expected_evidence = "document title and page span"; scorer = "smoke-scorer"; owner = "smoke-owner"; status = "ready"; notes = "smoke" }
    ) | Export-Csv -LiteralPath (Join-Path $runDir "agent-task-cases.csv") -NoTypeInformation -Encoding UTF8

    @(
        [pscustomobject]@{ task_id = "task-smoke-001"; task_type = "constraint_lookup"; real_source = "historical review case"; monthly_frequency = "8"; has_gold_answer = "yes"; needs_evidence = "yes"; owner = "smoke-owner"; selected = "yes"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-002"; task_type = "interface_mechanism_lookup"; real_source = "historical implementation task"; monthly_frequency = "6"; has_gold_answer = "yes"; needs_evidence = "yes"; owner = "smoke-owner"; selected = "yes"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-003"; task_type = "test_focus_generation"; real_source = "historical test omission"; monthly_frequency = "5"; has_gold_answer = "yes"; needs_evidence = "yes"; owner = "smoke-owner"; selected = "yes"; notes = "smoke" }
    ) | Export-Csv -LiteralPath (Join-Path $runDir "scenario-selection-matrix.csv") -NoTypeInformation -Encoding UTF8

    $parserRows = New-Object System.Collections.Generic.List[object]
    foreach ($parser in @("Docling", "MinerU", "Unstructured")) {
        for ($i = 1; $i -le 10; $i++) {
            $documentId = "sample-{0:000}" -f $i
            $parserRows.Add([pscustomobject]@{
                document_id = $documentId
                file_path = "sample-raw\$documentId.pdf"
                parser = $parser
                page_metadata_rate = "0.98"
                span_traceability_rate = "0.97"
                table_accuracy = "0.91"
                reading_order_accuracy = "0.94"
                ocr_accuracy = "0.93"
                parse_minutes = "1.2"
                critical_failures = "0"
                notes = "smoke scored parser row"
            }) | Out-Null
        }
    }
    $parserRows | Export-Csv -LiteralPath (Join-Path $runDir "parser-evaluation-sheet.csv") -NoTypeInformation -Encoding UTF8

    $promptRows = New-Object System.Collections.Generic.List[object]
    $runLogRows = New-Object System.Collections.Generic.List[object]
    $resultRows = New-Object System.Collections.Generic.List[object]

    foreach ($taskId in $taskIds) {
        foreach ($group in @("baseline", "context_pack")) {
            $contextSource = if ($group -eq "baseline") { "raw_files" } else { "context_pack" }
            $promptPath = "prompts\$group\$taskId.md"
            $rawOutputPath = "raw-outputs\$taskId-$group.md"
            $promptFullPath = Join-Path $runDir $promptPath
            $rawOutputFullPath = Join-Path $runDir $rawOutputPath

            Set-Content -LiteralPath $promptFullPath -Value "# Smoke Prompt`n`nTask: $taskId`nContext source: $contextSource" -Encoding UTF8
            Set-Content -LiteralPath $rawOutputFullPath -Value "# Smoke Agent Output`n`nAnswer for $taskId / $group with evidence." -Encoding UTF8

            $promptRows.Add([pscustomobject]@{
                task_id = $taskId
                group = $group
                prompt_path = $promptPath
                context_source = $contextSource
                source_docs = if ($group -eq "baseline") { "doc-smoke-001;doc-smoke-002" } else { "context-pack-$taskId" }
                notes = "smoke"
            }) | Out-Null

            $runLogRows.Add([pscustomobject]@{
                run_id = "run-smoke-001"
                task_id = $taskId
                group = $group
                attempt = "1"
                agent = "Codex"
                model = "gpt-5.4"
                context_source = $contextSource
                source_docs = if ($group -eq "baseline") { "doc-smoke-001;doc-smoke-002" } else { "context-pack-$taskId" }
                context_pack_id = if ($group -eq "baseline") { "N/A" } else { "context-pack-$taskId" }
                prompt_path = $promptPath
                started_at = "2026-05-31T10:00:00+08:00"
                ended_at = "2026-05-31T10:04:00+08:00"
                token_input = "1200"
                token_output = "360"
                elapsed_minutes = "4"
                raw_output_path = $rawOutputPath
                scorer = "smoke-scorer"
                score_status = "scored"
                notes = "smoke"
            }) | Out-Null

            $resultRows.Add([pscustomobject]@{
                task_id = $taskId
                group = $group
                agent = "Codex"
                source_docs = if ($group -eq "baseline") { "doc-smoke-001;doc-smoke-002" } else { "context-pack-$taskId" }
                answer_correct = "true"
                missed_constraints = "0"
                wrong_claims = "0"
                citation_correct = "true"
                token_cost = if ($group -eq "baseline") { "4200" } else { "1800" }
                elapsed_minutes = if ($group -eq "baseline") { "8" } else { "4" }
                human_fix_count = "0"
                context_pack_tokens = if ($group -eq "baseline") { "N/A" } else { "1300" }
                retrieved_span_count = if ($group -eq "baseline") { "N/A" } else { "12" }
                useful_span_count = if ($group -eq "baseline") { "N/A" } else { "9" }
                irrelevant_span_count = if ($group -eq "baseline") { "N/A" } else { "3" }
                retrieval_failure = if ($group -eq "baseline") { "N/A" } else { "no" }
                notes = "smoke scored result"
            }) | Out-Null
        }
    }

    $promptRows | Export-Csv -LiteralPath (Join-Path $runDir "agent-prompt-manifest.csv") -NoTypeInformation -Encoding UTF8
    $runLogRows | Export-Csv -LiteralPath (Join-Path $runDir "agent-run-log.csv") -NoTypeInformation -Encoding UTF8
    $resultRows | Export-Csv -LiteralPath (Join-Path $runDir "baseline-vs-contextpack-results.csv") -NoTypeInformation -Encoding UTF8

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "RUN_DIR=$runDir"

    $completeOutputPath = Join-Path $smokeRoot "complete-output.txt"
    & powershell -ExecutionPolicy Bypass -File $ReadinessScript -ExperimentDir $runDir -ReportPath $reportPath -Strict *> $completeOutputPath
    $completeExitCode = $LASTEXITCODE
    $completeOutput = Get-Content -LiteralPath $completeOutputPath -Raw -Encoding UTF8

    if ($completeExitCode -ne 0) {
        $failureMessage = "Complete evidence readiness check failed with exit code $completeExitCode."
    }
    elseif ($completeOutput -notlike "*Overall: READY_FOR_EVALUATION*") {
        $failureMessage = "Complete evidence readiness check did not report READY_FOR_EVALUATION."
    }
    elseif (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        $failureMessage = "Readiness report was not written."
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        Remove-Item -LiteralPath (Join-Path $runDir "raw-outputs\task-smoke-003-context_pack.md") -Force

        $incompleteOutputPath = Join-Path $smokeRoot "incomplete-output.txt"
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & powershell -ExecutionPolicy Bypass -File $ReadinessScript -ExperimentDir $runDir -Strict *> $incompleteOutputPath
            $incompleteExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }

        $incompleteOutput = Get-Content -LiteralPath $incompleteOutputPath -Raw -Encoding UTF8
        if ($incompleteExitCode -eq 0) {
            $failureMessage = "Incomplete evidence readiness check should fail in strict mode."
        }
        elseif ($incompleteOutput -notlike "*Overall: INCOMPLETE_EVIDENCE*") {
            $failureMessage = "Incomplete evidence readiness check did not report INCOMPLETE_EVIDENCE."
        }
        elseif ($incompleteOutput -notlike "*raw_output_path_exists*") {
            $failureMessage = "Incomplete evidence readiness check did not identify the missing raw output."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        Write-Host "RUN_EVIDENCE_READINESS_SMOKE=PASS"
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
    Write-Host "RUN_EVIDENCE_READINESS_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
