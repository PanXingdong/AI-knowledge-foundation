param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$StatusScript = Join-Path $PSScriptRoot "report-experiment-status.ps1"
if (-not (Test-Path -LiteralPath $StatusScript)) {
    Write-Error "Missing status script: $StatusScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$smokeRoot = Join-Path $ArtifactRoot ("akh-status-smoke-" + $timestamp)
$sourceRoot = Join-Path $smokeRoot "source"
$rawDir = Join-Path $smokeRoot "raw"
$manifestPath = Join-Path $smokeRoot "sample-manifest.csv"
$documentIntakePath = Join-Path $smokeRoot "document-intake.csv"
$taskIntakePath = Join-Path $smokeRoot "task-intake.csv"
$ownerTrackerPath = Join-Path $smokeRoot "owner-response-tracker.csv"
$experimentDir = Join-Path $smokeRoot "run"
$outputDir = Join-Path $experimentDir "raw-outputs"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $sourceRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $rawDir -Force | Out-Null
    New-Item -ItemType Directory -Path $experimentDir -Force | Out-Null
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

    $manifestRows = New-Object System.Collections.Generic.List[object]
    $documentRows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 10; $i++) {
        $rawPath = Join-Path $rawDir ("doc-smoke-{0:00}.pdf" -f $i)
        $sourcePath = Join-Path $sourceRoot ("source-{0:00}.pdf" -f $i)
        Set-Content -LiteralPath $rawPath -Value ("raw smoke document {0}" -f $i) -Encoding UTF8
        Set-Content -LiteralPath $sourcePath -Value ("source smoke document {0}" -f $i) -Encoding UTF8

        $manifestRows.Add([pscustomobject]@{
            sample_id = ("sample-{0:000}" -f $i)
            slot_type = "QNX adaptation smoke"
            file_path = $rawPath
            document_title = ("Smoke Document {0:00}" -f $i)
            document_version = "v1.0"
            owner = "smoke-owner"
            is_scanned = if ($i -eq 3) { "yes" } else { "no" }
            has_tables = if ($i -eq 2) { "yes" } else { "no" }
            has_multicolumn = if ($i -eq 4) { "yes" } else { "no" }
            confidentiality = "internal"
            status = "ready"
            notes = "temporary smoke input"
        }) | Out-Null

        $documentRows.Add([pscustomobject]@{
            candidate_id = ("doc-smoke-{0:00}" -f $i)
            slot_type = "QNX adaptation smoke"
            source_location = $sourcePath
            document_title = ("Smoke Document {0:00}" -f $i)
            document_version = "v1.0"
            owner = "smoke-owner"
            is_scanned = if ($i -eq 3) { "yes" } else { "no" }
            has_tables = if ($i -eq 2) { "yes" } else { "no" }
            has_multicolumn = if ($i -eq 4) { "yes" } else { "no" }
            confidentiality = "internal"
            allowed_for_experiment = "yes"
            candidate_reason = "Covers status smoke."
            notes = "temporary smoke input"
        }) | Out-Null
    }
    $manifestRows | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding UTF8
    $documentRows | Export-Csv -LiteralPath $documentIntakePath -NoTypeInformation -Encoding UTF8

    @(
        [pscustomobject]@{
            owner = "smoke-owner"
            module = "QNX adaptation"
            request_sent_date = "2026-05-31"
            due_date = "2026-06-07"
            requested_documents = "10"
            provided_documents = "10"
            requested_tasks = "3"
            provided_tasks = "3"
            document_intake_updated = "yes"
            task_intake_updated = "yes"
            current_status = "ready"
            blocker = ""
            next_follow_up = "none"
            notes = "temporary smoke tracker"
        }
    ) | Export-Csv -LiteralPath $ownerTrackerPath -NoTypeInformation -Encoding UTF8

    $taskRows = @(
        [pscustomobject]@{ candidate_id = "task-smoke-001"; task_type = "constraint_lookup"; domain = "QNX adaptation"; real_source = "historical review"; monthly_frequency = "8"; task_description = "Find constraints."; allowed_documents = "doc-smoke-01"; gold_answer_points = "constraint"; required_constraints = "constraint"; expected_evidence = "page span"; owner = "owner"; scorer = "scorer"; needs_evidence = "yes"; selected = "yes"; notes = "smoke" },
        [pscustomobject]@{ candidate_id = "task-smoke-002"; task_type = "interface_lookup"; domain = "QNX adaptation"; real_source = "historical task"; monthly_frequency = "6"; task_description = "Find interface."; allowed_documents = "doc-smoke-02"; gold_answer_points = "interface"; required_constraints = "limit"; expected_evidence = "page span"; owner = "owner"; scorer = "scorer"; needs_evidence = "yes"; selected = "yes"; notes = "smoke" },
        [pscustomobject]@{ candidate_id = "task-smoke-003"; task_type = "test_focus"; domain = "QNX adaptation"; real_source = "historical omission"; monthly_frequency = "5"; task_description = "Find tests."; allowed_documents = "doc-smoke-03"; gold_answer_points = "tests"; required_constraints = "coverage"; expected_evidence = "page span"; owner = "owner"; scorer = "scorer"; needs_evidence = "yes"; selected = "yes"; notes = "smoke" }
    )
    $taskRows | Export-Csv -LiteralPath $taskIntakePath -NoTypeInformation -Encoding UTF8

    $taskRows | ForEach-Object {
        [pscustomobject]@{
            task_id = $_.candidate_id
            task_type = $_.task_type
            domain = $_.domain
            task_description = $_.task_description
            allowed_documents = $_.allowed_documents
            gold_answer_points = $_.gold_answer_points
            required_constraints = $_.required_constraints
            expected_evidence = $_.expected_evidence
            scorer = $_.scorer
            owner = $_.owner
            status = "ready"
            notes = $_.notes
        }
    } | Export-Csv -LiteralPath (Join-Path $experimentDir "agent-task-cases.csv") -NoTypeInformation -Encoding UTF8

    $taskRows | ForEach-Object {
        [pscustomobject]@{
            task_id = $_.candidate_id
            task_type = $_.task_type
            real_source = $_.real_source
            monthly_frequency = $_.monthly_frequency
            has_gold_answer = "yes"
            needs_evidence = "yes"
            owner = $_.owner
            selected = "yes"
            notes = $_.notes
        }
    } | Export-Csv -LiteralPath (Join-Path $experimentDir "scenario-selection-matrix.csv") -NoTypeInformation -Encoding UTF8

    Set-Content -LiteralPath (Join-Path $experimentDir "agent-task-cards.md") -Value @("# Agent Task Cards", "", "All smoke task cards are ready.") -Encoding UTF8

    $parserRows = New-Object System.Collections.Generic.List[object]
    foreach ($parser in @("Docling", "MinerU", "Unstructured")) {
        for ($i = 1; $i -le 10; $i++) {
            $parserRows.Add([pscustomobject]@{
                document_id = ("sample-{0:000}" -f $i)
                file_path = ("doc-smoke-{0:00}.pdf" -f $i)
                parser = $parser
                page_metadata_rate = "98%"
                span_traceability_rate = "94%"
                table_accuracy = "86%"
                reading_order_accuracy = "93%"
                ocr_accuracy = "96%"
                parse_minutes = "1.8"
                critical_failures = "0"
                notes = "smoke"
            }) | Out-Null
        }
    }
    $parserRows | Export-Csv -LiteralPath (Join-Path $experimentDir "parser-evaluation-sheet.csv") -NoTypeInformation -Encoding UTF8

    $resultRows = @()
    foreach ($task in @("task-smoke-001", "task-smoke-002", "task-smoke-003")) {
        $resultRows += [pscustomobject]@{ task_id = $task; group = "baseline"; agent = "smoke"; source_docs = "raw"; answer_correct = "no"; missed_constraints = "2"; wrong_claims = "1"; citation_correct = "no"; token_cost = "10000"; elapsed_minutes = "20"; human_fix_count = "2"; context_pack_tokens = "N/A"; retrieved_span_count = "N/A"; useful_span_count = "N/A"; irrelevant_span_count = "N/A"; retrieval_failure = "N/A"; notes = "smoke" }
        $resultRows += [pscustomobject]@{ task_id = $task; group = "context_pack"; agent = "smoke"; source_docs = "context"; answer_correct = "yes"; missed_constraints = "0"; wrong_claims = "0"; citation_correct = "yes"; token_cost = "3000"; elapsed_minutes = "8"; human_fix_count = "0"; context_pack_tokens = "2500"; retrieved_span_count = "8"; useful_span_count = "6"; irrelevant_span_count = "2"; retrieval_failure = "no"; notes = "smoke" }
    }
    $resultRows | Export-Csv -LiteralPath (Join-Path $experimentDir "baseline-vs-contextpack-results.csv") -NoTypeInformation -Encoding UTF8

    $runLogRows = @()
    foreach ($task in @("task-smoke-001", "task-smoke-002", "task-smoke-003")) {
        foreach ($group in @("baseline", "context_pack")) {
            $rawOutputFileName = "$task-$group.md"
            $rawOutputPath = Join-Path $outputDir $rawOutputFileName
            Set-Content -LiteralPath $rawOutputPath -Value @(
                "# Smoke Agent Output",
                "",
                "task_id: $task",
                "group: $group",
                "",
                "This is a traceable smoke output used to verify run log wiring."
            ) -Encoding UTF8

            $runLogRows += [pscustomobject]@{
                run_id = "smoke"
                task_id = $task
                group = $group
                attempt = "1"
                agent = "smoke"
                model = "smoke-model"
                context_source = $(if ($group -eq "baseline") { "raw_files" } else { "context_pack" })
                source_docs = $(if ($group -eq "baseline") { "raw" } else { "context" })
                context_pack_id = $(if ($group -eq "baseline") { "N/A" } else { "cp-$task" })
                prompt_path = "N/A"
                started_at = "2026-05-31T00:00:00Z"
                ended_at = "2026-05-31T00:20:00Z"
                token_input = $(if ($group -eq "baseline") { "9000" } else { "2500" })
                token_output = "1000"
                elapsed_minutes = $(if ($group -eq "baseline") { "20" } else { "8" })
                raw_output_path = "raw-outputs\$rawOutputFileName"
                scorer = "scorer"
                score_status = "scored"
                notes = "smoke"
            }
        }
    }
    $runLogRows | Export-Csv -LiteralPath (Join-Path $experimentDir "agent-run-log.csv") -NoTypeInformation -Encoding UTF8

    Write-Host "SMOKE_ROOT=$smokeRoot"
    & powershell -ExecutionPolicy Bypass -File $StatusScript `
        -Strict `
        -ExperimentDir $experimentDir `
        -SampleManifestPath $manifestPath `
        -SampleRawDir $rawDir `
        -DocumentIntakePath $documentIntakePath `
        -TaskIntakePath $taskIntakePath `
        -OwnerTrackerPath $ownerTrackerPath

    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $failureMessage = "Experiment status smoke failed with exit code $exitCode."
    }
    else {
        Write-Host "EXPERIMENT_STATUS_SMOKE=PASS"
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
    Write-Host "EXPERIMENT_STATUS_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
