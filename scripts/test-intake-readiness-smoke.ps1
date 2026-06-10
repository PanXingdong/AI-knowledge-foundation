param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ReadinessScript = Join-Path $PSScriptRoot "check-intake-readiness.ps1"

if (-not (Test-Path -LiteralPath $ReadinessScript)) {
    Write-Error "Missing readiness script: $ReadinessScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-intake-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$docRoot = Join-Path $smokeRoot "docs"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $docRoot -Force | Out-Null

    $slotTypes = @(
        "QNX platform guide",
        "QNX boot and service management",
        "QNX IPC",
        "QNX resource manager",
        "QNX networking",
        "QNX security",
        "QNX logging",
        "BSP release note",
        "Internal SDD",
        "Internal test spec"
    )

    $documentRows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 10; $i++) {
        $extension = if ($i -eq 10) { ".docx" } else { ".pdf" }
        $documentPath = Join-Path $docRoot (("sample-{0:00}" -f $i) + $extension)
        Set-Content -LiteralPath $documentPath -Value ("smoke placeholder document {0}" -f $i) -Encoding UTF8

        $documentRows.Add([pscustomobject]@{
            candidate_id = ("doc-smoke-{0:00}" -f $i)
            slot_type = $slotTypes[$i - 1]
            source_location = $documentPath
            document_title = ("Smoke Document {0:00}" -f $i)
            document_version = "v1.0"
            owner = "smoke-owner"
            is_scanned = if ($i -eq 3) { "yes" } else { "no" }
            has_tables = if ($i -eq 2 -or $i -eq 8) { "yes" } else { "no" }
            has_multicolumn = if ($i -eq 4) { "yes" } else { "no" }
            confidentiality = "internal"
            allowed_for_experiment = "yes"
            candidate_reason = "Covers QNX adaptation experiment smoke readiness."
            notes = "temporary smoke input"
        }) | Out-Null
    }

    $documentIntakePath = Join-Path $smokeRoot "document-intake-smoke.csv"
    $documentRows | Export-Csv -LiteralPath $documentIntakePath -NoTypeInformation -Encoding UTF8

    $taskRows = @(
        [pscustomobject]@{
            candidate_id = "task-smoke-001"
            task_type = "constraint_lookup"
            domain = "QNX adaptation"
            real_source = "historical review case"
            monthly_frequency = "8"
            task_description = "Find startup ordering constraints for a QNX service."
            allowed_documents = "doc-smoke-001;doc-smoke-002"
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
            candidate_id = "task-smoke-002"
            task_type = "interface_mechanism_lookup"
            domain = "QNX adaptation"
            real_source = "historical implementation task"
            monthly_frequency = "6"
            task_description = "Locate IPC mechanism constraints relevant to module integration."
            allowed_documents = "doc-smoke-001;doc-smoke-003"
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
            candidate_id = "task-smoke-003"
            task_type = "test_focus_generation"
            domain = "QNX adaptation"
            real_source = "historical test omission"
            monthly_frequency = "5"
            task_description = "Generate test focus points for startup and IPC changes."
            allowed_documents = "doc-smoke-002;doc-smoke-003;doc-smoke-010"
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

    $taskIntakePath = Join-Path $smokeRoot "task-intake-smoke.csv"
    $taskRows | Export-Csv -LiteralPath $taskIntakePath -NoTypeInformation -Encoding UTF8

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "DOCUMENT_INTAKE=$documentIntakePath"
    Write-Host "TASK_INTAKE=$taskIntakePath"

    & powershell -ExecutionPolicy Bypass -File $ReadinessScript -Strict -DocumentIntakePath $documentIntakePath -TaskIntakePath $taskIntakePath
    $readinessExitCode = $LASTEXITCODE

    if ($readinessExitCode -ne 0) {
        $failureMessage = "Readiness smoke failed with exit code $readinessExitCode."
    }
    else {
        Write-Host "INTAKE_READINESS_SMOKE=PASS"
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
    Write-Host "INTAKE_READINESS_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
