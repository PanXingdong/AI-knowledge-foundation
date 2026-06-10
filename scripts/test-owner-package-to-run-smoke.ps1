param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ScriptUnderTest = Join-Path $PSScriptRoot "prepare-experiment-run-from-owner-package.ps1"

if (-not (Test-Path -LiteralPath $ScriptUnderTest -PathType Leaf)) {
    Write-Error "Missing script: $ScriptUnderTest"
}
if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$smokeRoot = Join-Path $ArtifactRoot ("akh-owner-package-to-run-smoke-" + $timestamp)
$packageRoot = Join-Path $smokeRoot "returned-package"
$packageZip = Join-Path $smokeRoot "returned-package.zip"
$targetDocumentIntake = Join-Path $smokeRoot "target-document-intake.csv"
$targetTaskIntake = Join-Path $smokeRoot "target-task-intake.csv"
$manifestPath = Join-Path $smokeRoot "sample-manifest.csv"
$incomingDocsDir = Join-Path $smokeRoot "incoming-docs"
$rawDir = Join-Path $smokeRoot "raw"
$runId = "smoke-owner-package-to-run-" + $timestamp
$runDir = Join-Path (Join-Path $ProjectRoot "experiments\runs") $runId
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path (Join-Path $packageRoot "samples") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $packageRoot "experiments\templates") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $packageRoot "returned-docs") -Force | Out-Null

    $targetDocRows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 10; $i++) {
        $targetDocRows.Add([pscustomobject]@{
            candidate_id = ("doc-candidate-{0:000}" -f $i)
            slot_type = "TBD"
            source_location = "TBD"
            document_title = "TBD"
            document_version = "TBD"
            owner = "TBD"
            is_scanned = "TBD"
            has_tables = "TBD"
            has_multicolumn = "TBD"
            confidentiality = "TBD"
            allowed_for_experiment = "TBD"
            candidate_reason = "TBD"
            notes = "TBD"
        }) | Out-Null
    }
    $targetDocRows | Export-Csv -LiteralPath $targetDocumentIntake -NoTypeInformation -Encoding UTF8

    $targetTaskRows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 5; $i++) {
        $targetTaskRows.Add([pscustomobject]@{
            candidate_id = ("task-candidate-{0:000}" -f $i)
            task_type = "TBD"
            domain = "TBD"
            real_source = "TBD"
            monthly_frequency = "TBD"
            task_description = "TBD"
            allowed_documents = "TBD"
            gold_answer_points = "TBD"
            required_constraints = "TBD"
            expected_evidence = "TBD"
            owner = "TBD"
            scorer = "TBD"
            needs_evidence = "TBD"
            selected = "TBD"
            notes = "TBD"
        }) | Out-Null
    }
    $targetTaskRows | Export-Csv -LiteralPath $targetTaskIntake -NoTypeInformation -Encoding UTF8

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

    $returnedDocRows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 10; $i++) {
        $extension = if ($i -eq 10) { ".docx" } else { ".pdf" }
        $relativeSource = "returned-docs\source-$i$extension"
        $sourcePath = Join-Path $packageRoot $relativeSource
        Set-Content -LiteralPath $sourcePath -Value ("returned document $i") -Encoding UTF8

        $returnedDocRows.Add([pscustomobject]@{
            candidate_id = ("doc-candidate-{0:000}" -f $i)
            slot_type = "QNX adaptation owner package to run smoke"
            source_location = $relativeSource
            document_title = ("Returned Smoke Document {0:00}" -f $i)
            document_version = "v1.0"
            owner = "smoke-owner"
            is_scanned = if ($i -eq 3) { "yes" } else { "no" }
            has_tables = if ($i -eq 2 -or $i -eq 8) { "yes" } else { "no" }
            has_multicolumn = if ($i -eq 4) { "yes" } else { "no" }
            confidentiality = "internal"
            allowed_for_experiment = "yes"
            candidate_reason = "Covers owner package to run smoke."
            notes = "temporary smoke input"
        }) | Out-Null
    }
    $returnedDocRows | Export-Csv -LiteralPath (Join-Path $packageRoot "samples\document-intake-template.csv") -NoTypeInformation -Encoding UTF8

    @(
        [pscustomobject]@{ candidate_id = "task-candidate-001"; task_type = "constraint_lookup"; domain = "QNX adaptation"; real_source = "historical review case"; monthly_frequency = "8"; task_description = "Find startup ordering constraints for a QNX service."; allowed_documents = "doc-candidate-001;doc-candidate-002"; gold_answer_points = "identify dependency ready state and timeout behavior"; required_constraints = "cite service ordering and timeout constraints"; expected_evidence = "document title and page span"; owner = "smoke-owner"; scorer = "smoke-scorer"; needs_evidence = "yes"; selected = "yes"; notes = "temporary smoke task" },
        [pscustomobject]@{ candidate_id = "task-candidate-002"; task_type = "interface_mechanism_lookup"; domain = "QNX adaptation"; real_source = "historical implementation task"; monthly_frequency = "6"; task_description = "Locate IPC mechanism constraints relevant to module integration."; allowed_documents = "doc-candidate-003"; gold_answer_points = "identify IPC mechanism and limitation"; required_constraints = "cite mechanism and limitation"; expected_evidence = "document title and page span"; owner = "smoke-owner"; scorer = "smoke-scorer"; needs_evidence = "yes"; selected = "yes"; notes = "temporary smoke task" },
        [pscustomobject]@{ candidate_id = "task-candidate-003"; task_type = "test_focus_generation"; domain = "QNX adaptation"; real_source = "historical test omission"; monthly_frequency = "5"; task_description = "Generate test focus points for startup and IPC changes."; allowed_documents = "doc-candidate-002;doc-candidate-010"; gold_answer_points = "include cold start dependency delay and IPC failure"; required_constraints = "cite constraints that drive tests"; expected_evidence = "document title and page span"; owner = "smoke-owner"; scorer = "smoke-scorer"; needs_evidence = "yes"; selected = "yes"; notes = "temporary smoke task" }
    ) | Export-Csv -LiteralPath (Join-Path $packageRoot "experiments\templates\task-intake-template.csv") -NoTypeInformation -Encoding UTF8

    Compress-Archive -Path (Join-Path $packageRoot "*") -DestinationPath $packageZip -Force

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "PACKAGE_ZIP=$packageZip"
    Write-Host "RUN_ID=$runId"
    Write-Host "RUN_DIR=$runDir"

    & powershell -ExecutionPolicy Bypass -File $ScriptUnderTest `
        -PackagePath $packageZip `
        -RunId $runId `
        -DocumentIntakePath $targetDocumentIntake `
        -TaskIntakePath $targetTaskIntake `
        -IncomingDocsDir $incomingDocsDir `
        -RawDir $rawDir `
        -ManifestPath $manifestPath

    $dryRunExitCode = $LASTEXITCODE
    if ($dryRunExitCode -ne 0) {
        $failureMessage = "Owner package to run dry run failed with exit code $dryRunExitCode."
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        & powershell -ExecutionPolicy Bypass -File $ScriptUnderTest `
            -PackagePath $packageZip `
            -RunId $runId `
            -DocumentIntakePath $targetDocumentIntake `
            -TaskIntakePath $targetTaskIntake `
            -IncomingDocsDir $incomingDocsDir `
            -RawDir $rawDir `
            -ManifestPath $manifestPath `
            -Apply `
            -Force

        $applyExitCode = $LASTEXITCODE
        if ($applyExitCode -ne 0) {
            $failureMessage = "Owner package to run apply failed with exit code $applyExitCode."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        foreach ($relativePath in @(
            "agent-task-cases.csv",
            "scenario-selection-matrix.csv",
            "agent-task-cards.md",
            "agent-prompt-manifest.csv",
            "prompts\baseline",
            "prompts\context_pack",
            "raw-outputs"
        )) {
            $path = Join-Path $runDir $relativePath
            if (-not (Test-Path -LiteralPath $path)) {
                $failureMessage = "Prepared run missing expected path: $relativePath"
                break
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        $parserRows = @(Import-Csv -LiteralPath (Join-Path $runDir "parser-evaluation-sheet.csv") -Encoding UTF8)
        $promptManifestRows = @(Import-Csv -LiteralPath (Join-Path $runDir "agent-prompt-manifest.csv") -Encoding UTF8)
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
        $rawDocs = @(Get-ChildItem -LiteralPath $rawDir -File -Recurse -ErrorAction SilentlyContinue)
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
        elseif ($promptManifestRows.Count -ne 6) {
            $failureMessage = "Expected 6 prompt manifest rows, found $($promptManifestRows.Count)."
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
        elseif ($rawDocs.Count -ne 10) {
            $failureMessage = "Expected 10 raw docs copied for run, found $($rawDocs.Count)."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        Write-Host "OWNER_PACKAGE_TO_RUN_SMOKE=PASS"
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
    Write-Host "OWNER_PACKAGE_TO_RUN_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
