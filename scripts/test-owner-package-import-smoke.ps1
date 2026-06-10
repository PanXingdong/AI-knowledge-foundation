param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ImportScript = Join-Path $PSScriptRoot "import-owner-package.ps1"
$ReadinessScript = Join-Path $PSScriptRoot "check-intake-readiness.ps1"

if (-not (Test-Path -LiteralPath $ImportScript)) {
    Write-Error "Missing import script: $ImportScript"
}
if (-not (Test-Path -LiteralPath $ReadinessScript)) {
    Write-Error "Missing readiness script: $ReadinessScript"
}
if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-owner-import-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$packageRoot = Join-Path $smokeRoot "returned-package"
$packageZip = Join-Path $smokeRoot "returned-package.zip"
$targetDocumentIntake = Join-Path $smokeRoot "target-document-intake.csv"
$targetTaskIntake = Join-Path $smokeRoot "target-task-intake.csv"
$incomingDocsDir = Join-Path $smokeRoot "incoming-docs"
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

    $returnedDocRows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 10; $i++) {
        $extension = if ($i -eq 10) { ".docx" } else { ".pdf" }
        $relativeSource = "returned-docs\source-$i$extension"
        $sourcePath = Join-Path $packageRoot $relativeSource
        Set-Content -LiteralPath $sourcePath -Value ("returned document $i") -Encoding UTF8

        $returnedDocRows.Add([pscustomobject]@{
            candidate_id = ("doc-candidate-{0:000}" -f $i)
            slot_type = "QNX adaptation return smoke"
            source_location = $relativeSource
            document_title = ("Returned Smoke Document {0:00}" -f $i)
            document_version = "v1.0"
            owner = "smoke-owner"
            is_scanned = if ($i -eq 3) { "yes" } else { "no" }
            has_tables = if ($i -eq 2 -or $i -eq 8) { "yes" } else { "no" }
            has_multicolumn = if ($i -eq 4) { "yes" } else { "no" }
            confidentiality = "internal"
            allowed_for_experiment = "yes"
            candidate_reason = "Covers returned package import smoke."
            notes = "temporary smoke input"
        }) | Out-Null
    }
    $returnedDocRows | Export-Csv -LiteralPath (Join-Path $packageRoot "samples\document-intake-template.csv") -NoTypeInformation -Encoding UTF8

    $returnedTaskRows = @(
        [pscustomobject]@{
            candidate_id = "task-candidate-001"
            task_type = "constraint_lookup"
            domain = "QNX adaptation"
            real_source = "historical review case"
            monthly_frequency = "8"
            task_description = "Find startup ordering constraints for a QNX service."
            allowed_documents = "doc-candidate-001;doc-candidate-002"
            gold_answer_points = "must identify dependency ready state; timeout behavior"
            required_constraints = "cite service ordering and timeout constraints"
            expected_evidence = "document title and page/span placeholder"
            owner = "smoke-owner"
            scorer = "smoke-scorer"
            needs_evidence = "yes"
            selected = "yes"
            notes = "temporary smoke task"
        },
        [pscustomobject]@{
            candidate_id = "task-candidate-002"
            task_type = "interface_mechanism_lookup"
            domain = "QNX adaptation"
            real_source = "historical implementation task"
            monthly_frequency = "6"
            task_description = "Locate IPC mechanism constraints relevant to module integration."
            allowed_documents = "doc-candidate-003"
            gold_answer_points = "must identify IPC mechanism and limitation"
            required_constraints = "cite mechanism and limitation"
            expected_evidence = "document title and page/span placeholder"
            owner = "smoke-owner"
            scorer = "smoke-scorer"
            needs_evidence = "yes"
            selected = "yes"
            notes = "temporary smoke task"
        },
        [pscustomobject]@{
            candidate_id = "task-candidate-003"
            task_type = "test_focus_generation"
            domain = "QNX adaptation"
            real_source = "historical test omission"
            monthly_frequency = "5"
            task_description = "Generate test focus points for startup and IPC changes."
            allowed_documents = "doc-candidate-002;doc-candidate-010"
            gold_answer_points = "must include cold start; dependency delay; IPC failure"
            required_constraints = "cite constraints that drive tests"
            expected_evidence = "document title and page/span placeholder"
            owner = "smoke-owner"
            scorer = "smoke-scorer"
            needs_evidence = "yes"
            selected = "yes"
            notes = "temporary smoke task"
        }
    )
    $returnedTaskRows | Export-Csv -LiteralPath (Join-Path $packageRoot "experiments\templates\task-intake-template.csv") -NoTypeInformation -Encoding UTF8

    Compress-Archive -Path (Join-Path $packageRoot "*") -DestinationPath $packageZip -Force

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "PACKAGE_ZIP=$packageZip"
    Write-Host "TARGET_DOCUMENT_INTAKE=$targetDocumentIntake"
    Write-Host "TARGET_TASK_INTAKE=$targetTaskIntake"

    & powershell -ExecutionPolicy Bypass -File $ImportScript -PackagePath $packageZip -DocumentIntakePath $targetDocumentIntake -TaskIntakePath $targetTaskIntake -IncomingDocsDir $incomingDocsDir
    $dryRunExitCode = $LASTEXITCODE
    if ($dryRunExitCode -ne 0) {
        $failureMessage = "Owner package import dry run failed with exit code $dryRunExitCode."
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        & powershell -ExecutionPolicy Bypass -File $ImportScript -PackagePath $packageZip -DocumentIntakePath $targetDocumentIntake -TaskIntakePath $targetTaskIntake -IncomingDocsDir $incomingDocsDir -Apply
        $applyExitCode = $LASTEXITCODE
        if ($applyExitCode -ne 0) {
            $failureMessage = "Owner package import apply failed with exit code $applyExitCode."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        $appliedDocRows = @(Import-Csv -LiteralPath $targetDocumentIntake -Encoding UTF8)
        $appliedTaskRows = @(Import-Csv -LiteralPath $targetTaskIntake -Encoding UTF8)
        $importedDocs = @($appliedDocRows | Where-Object { $_.notes -like "*imported from owner package*" })
        $importedTasks = @($appliedTaskRows | Where-Object { $_.notes -like "*imported from owner package*" })
        $copiedDocs = @(Get-ChildItem -LiteralPath $incomingDocsDir -File -Recurse -ErrorAction SilentlyContinue)

        if ($importedDocs.Count -ne 10) {
            $failureMessage = "Expected 10 imported document rows, found $($importedDocs.Count)."
        }
        elseif ($importedTasks.Count -ne 3) {
            $failureMessage = "Expected 3 imported task rows, found $($importedTasks.Count)."
        }
        elseif ($copiedDocs.Count -ne 10) {
            $failureMessage = "Expected 10 copied returned document files, found $($copiedDocs.Count)."
        }
        elseif (@($importedTasks | Where-Object { $_.allowed_documents -like "*doc-candidate-001*" }).Count -gt 0) {
            $failureMessage = "Imported task allowed_documents still reference original package doc ids."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        & powershell -ExecutionPolicy Bypass -File $ReadinessScript -Strict -DocumentIntakePath $targetDocumentIntake -TaskIntakePath $targetTaskIntake
        $readinessExitCode = $LASTEXITCODE
        if ($readinessExitCode -ne 0) {
            $failureMessage = "Readiness after owner package import failed with exit code $readinessExitCode."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        Write-Host "OWNER_PACKAGE_IMPORT_SMOKE=PASS"
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
    Write-Host "OWNER_PACKAGE_IMPORT_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
