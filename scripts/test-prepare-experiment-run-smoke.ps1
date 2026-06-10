param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PrepareScript = Join-Path $PSScriptRoot "prepare-experiment-run-from-intake.ps1"

if (-not (Test-Path -LiteralPath $PrepareScript)) {
    Write-Error "Missing prepare script: $PrepareScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$smokeRoot = Join-Path $ArtifactRoot ("akh-prepare-run-smoke-" + $timestamp)
$sourceRoot = Join-Path $smokeRoot "source"
$rawDir = Join-Path $smokeRoot "raw"
$manifestPath = Join-Path $smokeRoot "sample-manifest.csv"
$documentIntakePath = Join-Path $smokeRoot "document-intake.csv"
$taskIntakePath = Join-Path $smokeRoot "task-intake.csv"
$runId = "smoke-prepare-" + $timestamp
$runDir = Join-Path (Join-Path $ProjectRoot "experiments\runs") $runId
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $sourceRoot -Force | Out-Null

    $manifestRows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 10; $i++) {
        $manifestRows.Add([pscustomobject]@{
            sample_id = ("sample-{0:000}" -f $i)
            slot_type = "TBD"
            file_path = "TBD"
            document_title = "TBD"
            document_version = "TBD"
            owner = "TBD"
            is_scanned = "TBD"
            has_tables = "TBD"
            has_multicolumn = "TBD"
            confidentiality = "TBD"
            status = "TBD"
            notes = "TBD"
        }) | Out-Null
    }
    $manifestRows | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding UTF8

    $documentRows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 10; $i++) {
        $extension = if ($i -eq 10) { ".docx" } else { ".pdf" }
        $sourcePath = Join-Path $sourceRoot (("source-{0:00}" -f $i) + $extension)
        Set-Content -LiteralPath $sourcePath -Value ("smoke source document {0}" -f $i) -Encoding UTF8

        $documentRows.Add([pscustomobject]@{
            candidate_id = ("doc-smoke-{0:00}" -f $i)
            slot_type = "QNX adaptation smoke"
            source_location = $sourcePath
            document_title = ("Smoke Document {0:00}" -f $i)
            document_version = "v1.0"
            owner = "smoke-owner"
            is_scanned = if ($i -eq 3) { "yes" } else { "no" }
            has_tables = if ($i -eq 2 -or $i -eq 8) { "yes" } else { "no" }
            has_multicolumn = if ($i -eq 4) { "yes" } else { "no" }
            confidentiality = "internal"
            allowed_for_experiment = "yes"
            candidate_reason = "Covers full prepare run smoke."
            notes = "temporary smoke input"
        }) | Out-Null
    }
    $documentRows | Export-Csv -LiteralPath $documentIntakePath -NoTypeInformation -Encoding UTF8

    $taskRows = @(
        [pscustomobject]@{
            candidate_id = "task-smoke-001"
            task_type = "constraint_lookup"
            domain = "QNX adaptation"
            real_source = "historical review case"
            monthly_frequency = "8"
            task_description = "Find startup ordering constraints for a QNX service."
            allowed_documents = "doc-smoke-01;doc-smoke-02"
            gold_answer_points = "identify dependency ready state and timeout behavior"
            required_constraints = "cite service ordering and timeout constraints"
            expected_evidence = "document title and page span"
            owner = "smoke-owner"
            scorer = "smoke-scorer"
            needs_evidence = "yes"
            selected = "yes"
            notes = "temporary smoke task"
        },
        [pscustomobject]@{
            candidate_id = "task-smoke-002"
            task_type = "interface_mechanism_lookup"
            domain = "QNX adaptation"
            real_source = "historical implementation task"
            monthly_frequency = "6"
            task_description = "Locate IPC mechanism constraints relevant to module integration."
            allowed_documents = "doc-smoke-01;doc-smoke-03"
            gold_answer_points = "identify IPC mechanism and limitation"
            required_constraints = "cite mechanism and limitation"
            expected_evidence = "document title and page span"
            owner = "smoke-owner"
            scorer = "smoke-scorer"
            needs_evidence = "yes"
            selected = "yes"
            notes = "temporary smoke task"
        },
        [pscustomobject]@{
            candidate_id = "task-smoke-003"
            task_type = "test_focus_generation"
            domain = "QNX adaptation"
            real_source = "historical test omission"
            monthly_frequency = "5"
            task_description = "Generate test focus points for startup and IPC changes."
            allowed_documents = "doc-smoke-02;doc-smoke-03;doc-smoke-10"
            gold_answer_points = "include cold start dependency delay and IPC failure"
            required_constraints = "cite constraints that drive tests"
            expected_evidence = "document title and page span"
            owner = "smoke-owner"
            scorer = "smoke-scorer"
            needs_evidence = "yes"
            selected = "yes"
            notes = "temporary smoke task"
        }
    )
    $taskRows | Export-Csv -LiteralPath $taskIntakePath -NoTypeInformation -Encoding UTF8

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "RUN_ID=$runId"
    Write-Host "RUN_DIR=$runDir"
    Write-Host "DOCUMENT_INTAKE=$documentIntakePath"
    Write-Host "TASK_INTAKE=$taskIntakePath"
    Write-Host "RAW_DIR=$rawDir"
    Write-Host "MANIFEST=$manifestPath"

    & powershell -ExecutionPolicy Bypass -File $PrepareScript `
        -RunId $runId `
        -DocumentIntakePath $documentIntakePath `
        -TaskIntakePath $taskIntakePath `
        -RawDir $rawDir `
        -ManifestPath $manifestPath `
        -Apply `
        -Force

    $prepareExitCode = $LASTEXITCODE
    if ($prepareExitCode -ne 0) {
        $failureMessage = "Prepare experiment run smoke failed with exit code $prepareExitCode."
    }
    elseif (-not (Test-Path -LiteralPath (Join-Path $runDir "agent-task-cases.csv"))) {
        $failureMessage = "Prepared run is missing agent-task-cases.csv."
    }
    elseif (-not (Test-Path -LiteralPath (Join-Path $runDir "agent-task-cards.md"))) {
        $failureMessage = "Prepared run is missing agent-task-cards.md."
    }
    elseif (-not (Test-Path -LiteralPath (Join-Path $runDir "raw-outputs") -PathType Container)) {
        $failureMessage = "Prepared run is missing raw-outputs directory."
    }
    else {
        $parserRows = @(Import-Csv -LiteralPath (Join-Path $runDir "parser-evaluation-sheet.csv") -Encoding UTF8)
        $resultRows = @(Import-Csv -LiteralPath (Join-Path $runDir "baseline-vs-contextpack-results.csv") -Encoding UTF8)
        $runLogRows = @(Import-Csv -LiteralPath (Join-Path $runDir "agent-run-log.csv") -Encoding UTF8)
        $parserDocIds = @($parserRows | ForEach-Object { $_.document_id } | Select-Object -Unique)
        $parserNames = @($parserRows | ForEach-Object { $_.parser } | Select-Object -Unique)
        $enteredParserMetricRows = @(
            $parserRows | Where-Object {
                $_.page_metadata_rate -ne "TBD" -or
                $_.span_traceability_rate -ne "TBD" -or
                $_.table_accuracy -ne "TBD" -or
                $_.reading_order_accuracy -ne "TBD" -or
                $_.ocr_accuracy -ne "TBD" -or
                $_.parse_minutes -ne "TBD" -or
                $_.critical_failures -ne "TBD"
            }
        )
        $baselineRows = @($resultRows | Where-Object { $_.group -eq "baseline" })
        $contextRows = @($resultRows | Where-Object { $_.group -eq "context_pack" })
        $baselineRunLogRows = @($runLogRows | Where-Object { $_.group -eq "baseline" })
        $contextRunLogRows = @($runLogRows | Where-Object { $_.group -eq "context_pack" })
        $rawOutputFiles = @(Get-ChildItem -LiteralPath (Join-Path $runDir "raw-outputs") -File -Recurse -ErrorAction SilentlyContinue)
        if ($parserRows.Count -ne 30) {
            $failureMessage = "Expected 30 initialized parser evaluation rows, found $($parserRows.Count)."
        }
        elseif ($parserDocIds.Count -ne 10 -or $parserNames.Count -ne 3) {
            $failureMessage = "Expected parser sheet to cover 10 documents and 3 parsers, found documents=$($parserDocIds.Count), parsers=$($parserNames.Count)."
        }
        elseif ($enteredParserMetricRows.Count -ne 0) {
            $failureMessage = "Initialized parser rows should not contain scored parser metrics."
        }
        elseif ($resultRows.Count -ne 6) {
            $failureMessage = "Expected 6 initialized result rows, found $($resultRows.Count)."
        }
        elseif ($baselineRows.Count -ne 3 -or $contextRows.Count -ne 3) {
            $failureMessage = "Expected 3 baseline and 3 context_pack result rows, found baseline=$($baselineRows.Count), context_pack=$($contextRows.Count)."
        }
        elseif ($runLogRows.Count -ne 6) {
            $failureMessage = "Expected 6 initialized run-log rows, found $($runLogRows.Count)."
        }
        elseif ($baselineRunLogRows.Count -ne 3 -or $contextRunLogRows.Count -ne 3) {
            $failureMessage = "Expected 3 baseline and 3 context_pack run-log rows, found baseline=$($baselineRunLogRows.Count), context_pack=$($contextRunLogRows.Count)."
        }
        elseif ($rawOutputFiles.Count -ne 0) {
            $failureMessage = "Prepare flow must not create fake raw Agent output files."
        }
        elseif (@($runLogRows | Where-Object { $_.score_status -ne "pending" }).Count -gt 0) {
            $failureMessage = "Initialized run-log rows should be pending."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        Write-Host "PREPARE_EXPERIMENT_RUN_SMOKE=PASS"
    }
}
catch {
    $failureMessage = $_.Exception.Message
}
finally {
    if ($KeepArtifacts) {
        Write-Host "SMOKE_ARTIFACTS_KEPT=$smokeRoot"
        if (Test-Path -LiteralPath $runDir) {
            Write-Host "SMOKE_RUN_KEPT=$runDir"
        }
    }
    else {
        if (Test-Path -LiteralPath $runDir) {
            Remove-Item -LiteralPath $runDir -Recurse -Force
            Write-Host "SMOKE_RUN_CLEANED=$runDir"
        }
        if (Test-Path -LiteralPath $smokeRoot) {
            Remove-Item -LiteralPath $smokeRoot -Recurse -Force
            Write-Host "SMOKE_ARTIFACTS_CLEANED=$smokeRoot"
        }
    }
}

if (-not [string]::IsNullOrWhiteSpace($failureMessage)) {
    Write-Host "PREPARE_EXPERIMENT_RUN_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
