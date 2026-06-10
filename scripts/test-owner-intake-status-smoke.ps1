param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$StatusScript = Join-Path $PSScriptRoot "report-owner-intake-status.ps1"
if (-not (Test-Path -LiteralPath $StatusScript)) {
    Write-Error "Missing owner intake status script: $StatusScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-owner-intake-status-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$docRoot = Join-Path $smokeRoot "docs"
$documentIntakePath = Join-Path $smokeRoot "document-intake.csv"
$taskIntakePath = Join-Path $smokeRoot "task-intake.csv"
$ownerTrackerPath = Join-Path $smokeRoot "owner-response-tracker.csv"
$reportPath = Join-Path $smokeRoot "owner-intake-status.md"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $docRoot -Force | Out-Null

    $documentRows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 10; $i++) {
        $extension = if ($i -eq 10) { ".docx" } else { ".pdf" }
        $documentPath = Join-Path $docRoot (("doc-{0:00}" -f $i) + $extension)
        Set-Content -LiteralPath $documentPath -Value ("owner intake smoke document {0}" -f $i) -Encoding UTF8

        $documentRows.Add([pscustomobject]@{
            candidate_id = ("doc-smoke-{0:00}" -f $i)
            slot_type = "QNX adaptation smoke"
            source_location = $documentPath
            document_title = ("Smoke Document {0:00}" -f $i)
            document_version = "v1.0"
            owner = "smoke-owner"
            is_scanned = if ($i -eq 3) { "yes" } else { "no" }
            has_tables = if ($i -eq 2) { "yes" } else { "no" }
            has_multicolumn = if ($i -eq 4) { "yes" } else { "no" }
            confidentiality = "internal"
            allowed_for_experiment = "yes"
            candidate_reason = "Covers owner intake status smoke."
            notes = "temporary smoke input"
        }) | Out-Null
    }
    $documentRows | Export-Csv -LiteralPath $documentIntakePath -NoTypeInformation -Encoding UTF8

    @(
        [pscustomobject]@{ candidate_id = "task-smoke-001"; task_type = "constraint_lookup"; domain = "QNX adaptation"; real_source = "historical review"; monthly_frequency = "8"; task_description = "Find constraints."; allowed_documents = "doc-smoke-01"; gold_answer_points = "constraint"; required_constraints = "constraint"; expected_evidence = "page span"; owner = "owner"; scorer = "scorer"; needs_evidence = "yes"; selected = "yes"; notes = "smoke" },
        [pscustomobject]@{ candidate_id = "task-smoke-002"; task_type = "interface_lookup"; domain = "QNX adaptation"; real_source = "historical task"; monthly_frequency = "6"; task_description = "Find interface."; allowed_documents = "doc-smoke-02"; gold_answer_points = "interface"; required_constraints = "limit"; expected_evidence = "page span"; owner = "owner"; scorer = "scorer"; needs_evidence = "yes"; selected = "yes"; notes = "smoke" },
        [pscustomobject]@{ candidate_id = "task-smoke-003"; task_type = "test_focus"; domain = "QNX adaptation"; real_source = "historical omission"; monthly_frequency = "5"; task_description = "Find tests."; allowed_documents = "doc-smoke-03"; gold_answer_points = "tests"; required_constraints = "coverage"; expected_evidence = "page span"; owner = "owner"; scorer = "scorer"; needs_evidence = "yes"; selected = "yes"; notes = "smoke" }
    ) | Export-Csv -LiteralPath $taskIntakePath -NoTypeInformation -Encoding UTF8

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

    Write-Host "SMOKE_ROOT=$smokeRoot"
    & powershell -ExecutionPolicy Bypass -File $StatusScript `
        -Strict `
        -DocumentIntakePath $documentIntakePath `
        -TaskIntakePath $taskIntakePath `
        -OwnerTrackerPath $ownerTrackerPath `
        -ReportPath $reportPath

    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $failureMessage = "Owner intake status smoke failed with exit code $exitCode."
    }
    elseif (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        $failureMessage = "Missing status report: $reportPath"
    }
    else {
        $reportText = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8
        foreach ($term in @("READY_TO_CREATE_EXPERIMENT_RUN", "Ready documents", "Ready tasks")) {
            if ($reportText -notlike "*$term*") {
                $failureMessage = "Status report missing term: $term"
                break
            }
        }

        if ([string]::IsNullOrWhiteSpace($failureMessage)) {
            Write-Host "OWNER_INTAKE_STATUS_SMOKE=PASS"
        }
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
    Write-Host "OWNER_INTAKE_STATUS_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
