param(
    [switch]$StrictRealInputs,
    [string]$ExperimentDir,
    [string]$SampleManifestPath,
    [string]$SampleRawDir
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DefaultExperimentDir = Join-Path $ProjectRoot "experiments\templates"
if ([string]::IsNullOrWhiteSpace($ExperimentDir)) {
    $ExperimentDir = $DefaultExperimentDir
}
elseif (-not [System.IO.Path]::IsPathRooted($ExperimentDir)) {
    $ExperimentDir = Join-Path $ProjectRoot $ExperimentDir
}

if ([string]::IsNullOrWhiteSpace($SampleManifestPath)) {
    $SampleManifestPath = Join-Path $ProjectRoot "samples\sample-manifest.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($SampleManifestPath)) {
    $SampleManifestPath = Join-Path $ProjectRoot $SampleManifestPath
}

if ([string]::IsNullOrWhiteSpace($SampleRawDir)) {
    $SampleRawDir = Join-Path $ProjectRoot "samples\raw"
}
elseif (-not [System.IO.Path]::IsPathRooted($SampleRawDir)) {
    $SampleRawDir = Join-Path $ProjectRoot $SampleRawDir
}

$Checks = New-Object System.Collections.Generic.List[object]

function New-TextFromCodePoints {
    param([int[]]$CodePoints)

    return -join ($CodePoints | ForEach-Object { [char]$_ })
}

$PlaceholderTerms = @(
    (New-TextFromCodePoints @(0x5F85, 0x63D0, 0x4F9B)),
    (New-TextFromCodePoints @(0x5F85, 0x586B, 0x5199)),
    (New-TextFromCodePoints @(0x5F85, 0x786E, 0x8BA4)),
    (New-TextFromCodePoints @(0x5F85, 0x8BC4, 0x5206)),
    (New-TextFromCodePoints @(0x5F85, 0x5B9A)),
    "TBD",
    "TODO",
    "N/A",
    "placeholder"
)

$AffirmativeTerms = @(
    "1",
    "true",
    "yes",
    "y",
    "selected",
    "select",
    "ok",
    "pass",
    (New-TextFromCodePoints @(0x662F)),
    (New-TextFromCodePoints @(0x6709)),
    (New-TextFromCodePoints @(0x5DF2, 0x9009)),
    (New-TextFromCodePoints @(0x9009, 0x4E2D))
)

$PhaseBoundaryTerms = @(
    "AI Knowledge Foundation",
    "Context Pack",
    "Core",
    "local agent entry",
    "MCP is not the current product route"
)

$AcceptanceTerms = @(
    "Context Pack",
    "Phase 2",
    "graph",
    "review",
    "version"
)

function Add-Check {
    param(
        [ValidateSet("PASS", "WARN", "FAIL")]
        [string]$Status,
        [string]$Name,
        [string]$Detail
    )

    $Checks.Add([pscustomobject]@{
        Status = $Status
        Name = $Name
        Detail = $Detail
    }) | Out-Null
}

function Test-Placeholder {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $true
    }

    $trimmed = $Value.Trim()
    foreach ($term in $PlaceholderTerms) {
        if ($trimmed -eq $term) {
            return $true
        }
    }

    return $false
}

function Test-Affirmative {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $false
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    foreach ($term in $AffirmativeTerms) {
        if ($normalized -eq $term.ToLowerInvariant()) {
            return $true
        }
    }

    return $false
}

function Resolve-ProjectPath {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    return Join-Path $ProjectRoot $Value
}

function Resolve-ExperimentPath {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    return Join-Path $ExperimentDir $Value
}

function Get-FirstProjectMatch {
    param([string]$Pattern)

    $path = Join-Path $ProjectRoot $Pattern
    $items = @(Get-ChildItem -Path $path -Force -ErrorAction SilentlyContinue)
    if ($items.Count -eq 0) {
        return $null
    }

    return $items[0].FullName
}

function Import-CsvChecked {
    param(
        [string]$Path,
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        Add-Check "FAIL" $Name "Missing file: $Path"
        return @()
    }

    try {
        $rows = @(Import-Csv -LiteralPath $Path -Encoding UTF8)
        Add-Check "PASS" $Name "CSV parsed, rows: $($rows.Count)"
        return @($rows)
    }
    catch {
        Add-Check "FAIL" $Name "CSV parse failed: $($_.Exception.Message)"
        return @()
    }
}

function Test-TextContains {
    param(
        [string]$Path,
        [string[]]$Terms,
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        Add-Check "FAIL" $Name "Missing file: $Path"
        return
    }

    $content = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $missing = @($Terms | Where-Object { $content -notlike "*$_*" })
    if ($missing.Count -eq 0) {
        Add-Check "PASS" $Name "All required terms found."
    }
    else {
        Add-Check "FAIL" $Name "Missing terms: $($missing -join ', ')"
    }
}

function Test-RequiredExactPath {
    param([string]$RelativePath)

    $path = Join-Path $ProjectRoot $RelativePath
    if (Test-Path -LiteralPath $path) {
        Add-Check "PASS" "Required path: $RelativePath" "Found."
    }
    else {
        Add-Check "FAIL" "Required path: $RelativePath" "Missing."
    }
}

function Test-RequiredExperimentPath {
    param([string]$RelativePath)

    $path = Join-Path $ExperimentDir $RelativePath
    if (Test-Path -LiteralPath $path) {
        Add-Check "PASS" "Experiment path: $RelativePath" "Found: $path"
    }
    else {
        Add-Check "FAIL" "Experiment path: $RelativePath" "Missing: $path"
    }
}

function Test-RequiredPatternPath {
    param(
        [string]$Pattern,
        [string]$DisplayName
    )

    $match = Get-FirstProjectMatch $Pattern
    if ($null -ne $match) {
        Add-Check "PASS" "Required path: $DisplayName" "Found: $match"
    }
    else {
        Add-Check "FAIL" "Required path: $DisplayName" "Missing pattern: $Pattern"
    }
}

function Test-PowerShellSyntax {
    param(
        [string]$RelativePath
    )

    $path = Join-Path $ProjectRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path)) {
        return
    }

    try {
        $tokens = $null
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null
        if ($errors.Count -eq 0) {
            Add-Check "PASS" "PowerShell syntax: $RelativePath" "Parsed successfully."
        }
        else {
            $messages = @($errors | ForEach-Object { $_.Message })
            Add-Check "FAIL" "PowerShell syntax: $RelativePath" ($messages -join " | ")
        }
    }
    catch {
        Add-Check "FAIL" "PowerShell syntax: $RelativePath" "Parse check failed: $($_.Exception.Message)"
    }
}

Write-Host "Agent Knowledge Hub preflight"
Write-Host "Project root: $ProjectRoot"
Write-Host "Experiment dir: $ExperimentDir"
Write-Host "Sample manifest: $SampleManifestPath"
Write-Host "Sample raw dir: $SampleRawDir"
Write-Host "Mode: $(if ($StrictRealInputs) { 'strict real-input gate' } else { 'structure gate' })"
Write-Host ""

if (Test-Path -LiteralPath $ExperimentDir) {
    Add-Check "PASS" "Experiment directory" "Found: $ExperimentDir"
}
else {
    Add-Check "FAIL" "Experiment directory" "Missing: $ExperimentDir"
}

$requiredExactPaths = @(
    "README.md",
    "samples\README.md",
    "samples\sample-manifest.csv",
    "samples\document-intake-template.csv",
    "samples\document-intake-example.csv",
    "samples\owner-response-tracker.csv",
    "samples\raw",
    "scripts\preflight.ps1",
    "scripts\check-intake-readiness.ps1",
    "scripts\check-owner-package-readiness.ps1",
    "scripts\check-run-evidence-readiness.ps1",
    "scripts\export-owner-package.ps1",
    "scripts\import-owner-package.ps1",
    "scripts\prepare-experiment-run-from-owner-package.ps1",
    "scripts\report-owner-intake-status.ps1",
    "scripts\prepare-experiment-run-from-intake.ps1",
    "scripts\apply-document-intake-to-samples.ps1",
    "scripts\test-owner-package-smoke.ps1",
    "scripts\test-owner-package-readiness-smoke.ps1",
    "scripts\test-owner-package-import-smoke.ps1",
    "scripts\test-owner-package-to-run-smoke.ps1",
    "scripts\test-owner-intake-status-smoke.ps1",
    "scripts\test-prepare-experiment-run-smoke.ps1",
    "scripts\test-intake-readiness-smoke.ps1",
    "scripts\test-document-intake-to-samples-smoke.ps1",
    "scripts\apply-task-intake-to-run.ps1",
    "scripts\initialize-parser-evaluation-from-manifest.ps1",
    "scripts\initialize-results-from-tasks.ps1",
    "scripts\initialize-agent-prompts-from-tasks.ps1",
    "scripts\initialize-agent-run-log-from-tasks.ps1",
    "scripts\check-goal-acceptance.ps1",
    "scripts\evaluate-results.ps1",
    "scripts\evaluate-parser-results.ps1",
    "scripts\report-experiment-status.ps1",
    "scripts\test-goal-acceptance-smoke.ps1",
    "scripts\test-experiment-status-smoke.ps1",
    "scripts\test-parser-evaluation-smoke.ps1",
    "scripts\test-parser-evaluation-initialization-smoke.ps1",
    "scripts\test-result-initialization-smoke.ps1",
    "scripts\test-agent-prompt-initialization-smoke.ps1",
    "scripts\test-agent-run-log-initialization-smoke.ps1",
    "scripts\test-run-evidence-readiness-smoke.ps1",
    "scripts\new-experiment-run.ps1",
    "scripts\import-sample-docs.ps1",
    "experiments\runs\README.md",
    "experiments\templates\agent-task-cards.md",
    "experiments\templates\agent-task-cases.csv",
    "experiments\templates\parser-evaluation-sheet.csv",
    "experiments\templates\baseline-vs-contextpack-results.csv",
    "experiments\templates\agent-run-log.csv",
    "experiments\templates\agent-prompt-template.md",
    "experiments\templates\agent-prompt-manifest.csv",
    "experiments\templates\context-pack-template.json",
    "experiments\templates\scenario-selection-matrix.csv",
    "experiments\templates\scoring-rubric.md",
    "experiments\templates\task-intake-template.csv",
    "experiments\templates\task-intake-example.csv"
)

foreach ($relativePath in $requiredExactPaths) {
    Test-RequiredExactPath $relativePath
}

Test-PowerShellSyntax "scripts\preflight.ps1"
Test-PowerShellSyntax "scripts\check-intake-readiness.ps1"
Test-PowerShellSyntax "scripts\check-owner-package-readiness.ps1"
Test-PowerShellSyntax "scripts\check-run-evidence-readiness.ps1"
Test-PowerShellSyntax "scripts\export-owner-package.ps1"
Test-PowerShellSyntax "scripts\import-owner-package.ps1"
Test-PowerShellSyntax "scripts\prepare-experiment-run-from-owner-package.ps1"
Test-PowerShellSyntax "scripts\report-owner-intake-status.ps1"
Test-PowerShellSyntax "scripts\prepare-experiment-run-from-intake.ps1"
Test-PowerShellSyntax "scripts\apply-document-intake-to-samples.ps1"
Test-PowerShellSyntax "scripts\test-owner-package-smoke.ps1"
Test-PowerShellSyntax "scripts\test-owner-package-import-smoke.ps1"
Test-PowerShellSyntax "scripts\test-owner-package-to-run-smoke.ps1"
Test-PowerShellSyntax "scripts\test-owner-intake-status-smoke.ps1"
Test-PowerShellSyntax "scripts\test-prepare-experiment-run-smoke.ps1"
Test-PowerShellSyntax "scripts\test-intake-readiness-smoke.ps1"
Test-PowerShellSyntax "scripts\test-document-intake-to-samples-smoke.ps1"
Test-PowerShellSyntax "scripts\apply-task-intake-to-run.ps1"
Test-PowerShellSyntax "scripts\initialize-parser-evaluation-from-manifest.ps1"
Test-PowerShellSyntax "scripts\initialize-results-from-tasks.ps1"
Test-PowerShellSyntax "scripts\initialize-agent-prompts-from-tasks.ps1"
Test-PowerShellSyntax "scripts\initialize-agent-run-log-from-tasks.ps1"
Test-PowerShellSyntax "scripts\check-goal-acceptance.ps1"
Test-PowerShellSyntax "scripts\evaluate-results.ps1"
Test-PowerShellSyntax "scripts\evaluate-parser-results.ps1"
Test-PowerShellSyntax "scripts\report-experiment-status.ps1"
Test-PowerShellSyntax "scripts\test-goal-acceptance-smoke.ps1"
Test-PowerShellSyntax "scripts\test-experiment-status-smoke.ps1"
Test-PowerShellSyntax "scripts\test-parser-evaluation-smoke.ps1"
Test-PowerShellSyntax "scripts\test-parser-evaluation-initialization-smoke.ps1"
Test-PowerShellSyntax "scripts\test-result-initialization-smoke.ps1"
Test-PowerShellSyntax "scripts\test-agent-prompt-initialization-smoke.ps1"
Test-PowerShellSyntax "scripts\test-agent-run-log-initialization-smoke.ps1"
Test-PowerShellSyntax "scripts\test-run-evidence-readiness-smoke.ps1"
Test-PowerShellSyntax "scripts\test-owner-package-readiness-smoke.ps1"
Test-PowerShellSyntax "scripts\new-experiment-run.ps1"
Test-PowerShellSyntax "scripts\import-sample-docs.ps1"

foreach ($relativePath in @(
    "agent-task-cards.md",
    "agent-task-cases.csv",
    "parser-evaluation-sheet.csv",
    "baseline-vs-contextpack-results.csv",
    "agent-run-log.csv",
    "agent-prompt-template.md",
    "agent-prompt-manifest.csv",
    "context-pack-template.json",
    "scoring-rubric.md",
    "scenario-selection-matrix.csv"
)) {
    Test-RequiredExperimentPath $relativePath
}

$requiredDocs = @(
    "docs\README.md",
    "docs\overview.md",
    "docs\architecture.md",
    "docs\detailed-design.md",
    "docs\api-contract.md",
    "docs\development.md",
    "docs\evaluation.md",
    "docs\operations.md",
    "docs\archive\00-overview\direction-freeze-and-stage-gates.md",
    "docs\archive\05-evaluation\goal-acceptance-evidence-matrix.md",
    "docs\archive\06-operations\owner-collection-package.md",
    "docs\archive\06-operations\owner-response-tracking.md",
    "docs\archive\06-operations\owner-return-checklist.md"
)

foreach ($relativePath in $requiredDocs) {
    Test-RequiredExactPath $relativePath
}

$manifestRows = Import-CsvChecked $SampleManifestPath "Sample manifest"

$documentIntakeRows = Import-CsvChecked (Join-Path $ProjectRoot "samples\document-intake-template.csv") "Document intake template"
$documentIntakeExampleRows = Import-CsvChecked (Join-Path $ProjectRoot "samples\document-intake-example.csv") "Document intake example"
$ownerTrackerRows = Import-CsvChecked (Join-Path $ProjectRoot "samples\owner-response-tracker.csv") "Owner response tracker"
$requiredOwnerTrackerColumns = @(
    "owner",
    "module",
    "request_sent_date",
    "due_date",
    "requested_documents",
    "provided_documents",
    "requested_tasks",
    "provided_tasks",
    "document_intake_updated",
    "task_intake_updated",
    "current_status",
    "blocker",
    "next_follow_up",
    "notes"
)

if ($ownerTrackerRows.Count -gt 0) {
    $ownerTrackerColumns = @($ownerTrackerRows[0].PSObject.Properties.Name)
    $missingOwnerTrackerColumns = @($requiredOwnerTrackerColumns | Where-Object { $_ -notin $ownerTrackerColumns })
    if ($missingOwnerTrackerColumns.Count -eq 0) {
        Add-Check "PASS" "Owner response tracker columns" "All required columns found."
    }
    else {
        Add-Check "FAIL" "Owner response tracker columns" "Missing columns: $($missingOwnerTrackerColumns -join ', ')"
    }
}

$requiredDocumentIntakeColumns = @(
    "candidate_id",
    "slot_type",
    "source_location",
    "document_title",
    "document_version",
    "owner",
    "is_scanned",
    "has_tables",
    "has_multicolumn",
    "confidentiality",
    "allowed_for_experiment",
    "candidate_reason",
    "notes"
)

if ($documentIntakeRows.Count -gt 0) {
    $documentIntakeColumns = @($documentIntakeRows[0].PSObject.Properties.Name)
    $missingDocumentIntakeColumns = @($requiredDocumentIntakeColumns | Where-Object { $_ -notin $documentIntakeColumns })
    if ($missingDocumentIntakeColumns.Count -eq 0) {
        Add-Check "PASS" "Document intake columns" "All required columns found."
    }
    else {
        Add-Check "FAIL" "Document intake columns" "Missing columns: $($missingDocumentIntakeColumns -join ', ')"
    }

    if ($documentIntakeRows.Count -ge 10) {
        Add-Check "PASS" "Document intake row count" "Rows: $($documentIntakeRows.Count)"
    }
    else {
        Add-Check "FAIL" "Document intake row count" "Expected at least 10 candidate rows, got $($documentIntakeRows.Count)."
    }
}

if ($documentIntakeExampleRows.Count -gt 0) {
    $documentIntakeExampleColumns = @($documentIntakeExampleRows[0].PSObject.Properties.Name)
    $missingDocumentIntakeExampleColumns = @($requiredDocumentIntakeColumns | Where-Object { $_ -notin $documentIntakeExampleColumns })
    if ($missingDocumentIntakeExampleColumns.Count -eq 0) {
        Add-Check "PASS" "Document intake example columns" "All required columns found."
    }
    else {
        Add-Check "FAIL" "Document intake example columns" "Missing columns: $($missingDocumentIntakeExampleColumns -join ', ')"
    }
}

$requiredManifestColumns = @(
    "sample_id",
    "slot_type",
    "file_path",
    "document_title",
    "document_version",
    "owner",
    "is_scanned",
    "has_tables",
    "has_multicolumn",
    "confidentiality",
    "status",
    "notes"
)

if ($manifestRows.Count -gt 0) {
    $columns = @($manifestRows[0].PSObject.Properties.Name)
    $missingColumns = @($requiredManifestColumns | Where-Object { $_ -notin $columns })
    if ($missingColumns.Count -eq 0) {
        Add-Check "PASS" "Sample manifest columns" "All required columns found."
    }
    else {
        Add-Check "FAIL" "Sample manifest columns" "Missing columns: $($missingColumns -join ', ')"
    }

    if ($manifestRows.Count -ge 10) {
        Add-Check "PASS" "Sample manifest row count" "Rows: $($manifestRows.Count)"
    }
    else {
        Add-Check "FAIL" "Sample manifest row count" "Expected at least 10 rows, got $($manifestRows.Count)."
    }

    $placeholderRows = @($manifestRows | Where-Object { Test-Placeholder $_.file_path })
    if ($placeholderRows.Count -eq 0) {
        Add-Check "PASS" "Real sample paths in manifest" "All manifest rows have file paths."
    }
    else {
        $status = if ($StrictRealInputs) { "FAIL" } else { "WARN" }
        Add-Check $status "Real sample paths in manifest" "$($placeholderRows.Count) rows still have placeholder file_path."
    }

    $missingFiles = New-Object System.Collections.Generic.List[string]
    foreach ($row in $manifestRows) {
        $resolvedPath = Resolve-ProjectPath $row.file_path
        if ($null -ne $resolvedPath -and -not (Test-Path -LiteralPath $resolvedPath)) {
            $missingFiles.Add("$($row.sample_id): $($row.file_path)") | Out-Null
        }
    }

    if ($missingFiles.Count -eq 0) {
        Add-Check "PASS" "Manifest referenced files" "No missing referenced files."
    }
    else {
        Add-Check "FAIL" "Manifest referenced files" "Missing files: $($missingFiles -join '; ')"
    }
}

if (Test-Path -LiteralPath $SampleRawDir) {
    $supportedDocExtensions = @(".pdf", ".docx", ".doc", ".html", ".htm")
    $realDocs = @(Get-ChildItem -LiteralPath $SampleRawDir -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $supportedDocExtensions -contains $_.Extension.ToLowerInvariant() })
    if ($realDocs.Count -ge 10) {
        Add-Check "PASS" "Raw sample document count" "Documents found: $($realDocs.Count)"
    }
    elseif ($realDocs.Count -gt 0) {
        $status = if ($StrictRealInputs) { "FAIL" } else { "WARN" }
        Add-Check $status "Raw sample document count" "Expected 10 real documents, found $($realDocs.Count)."
    }
    else {
        $status = if ($StrictRealInputs) { "FAIL" } else { "WARN" }
        Add-Check $status "Raw sample document count" "No PDF/Word/HTML sample documents found."
    }
}
else {
    Add-Check "FAIL" "Raw sample document directory" "Missing: $SampleRawDir"
}

[void](Import-CsvChecked (Join-Path $ExperimentDir "parser-evaluation-sheet.csv") "Parser evaluation sheet")
[void](Import-CsvChecked (Join-Path $ExperimentDir "baseline-vs-contextpack-results.csv") "Baseline vs Context Pack sheet")
$agentRunLogRows = Import-CsvChecked (Join-Path $ExperimentDir "agent-run-log.csv") "Agent run log"
$promptManifestRows = Import-CsvChecked (Join-Path $ExperimentDir "agent-prompt-manifest.csv") "Agent prompt manifest"
$taskCaseRows = Import-CsvChecked (Join-Path $ExperimentDir "agent-task-cases.csv") "Agent task cases"
$scenarioRows = Import-CsvChecked (Join-Path $ExperimentDir "scenario-selection-matrix.csv") "Scenario selection matrix"
$taskIntakeRows = Import-CsvChecked (Join-Path $ProjectRoot "experiments\templates\task-intake-template.csv") "Task intake template"
$taskIntakeExampleRows = Import-CsvChecked (Join-Path $ProjectRoot "experiments\templates\task-intake-example.csv") "Task intake example"

$requiredTaskIntakeColumns = @(
    "candidate_id",
    "task_type",
    "domain",
    "real_source",
    "monthly_frequency",
    "task_description",
    "allowed_documents",
    "gold_answer_points",
    "required_constraints",
    "expected_evidence",
    "owner",
    "scorer",
    "needs_evidence",
    "selected",
    "notes"
)

if ($taskIntakeRows.Count -gt 0) {
    $taskIntakeColumns = @($taskIntakeRows[0].PSObject.Properties.Name)
    $missingTaskIntakeColumns = @($requiredTaskIntakeColumns | Where-Object { $_ -notin $taskIntakeColumns })
    if ($missingTaskIntakeColumns.Count -eq 0) {
        Add-Check "PASS" "Task intake columns" "All required columns found."
    }
    else {
        Add-Check "FAIL" "Task intake columns" "Missing columns: $($missingTaskIntakeColumns -join ', ')"
    }

    if ($taskIntakeRows.Count -ge 3) {
        Add-Check "PASS" "Task intake row count" "Rows: $($taskIntakeRows.Count)"
    }
    else {
        Add-Check "FAIL" "Task intake row count" "Expected at least 3 candidate rows, got $($taskIntakeRows.Count)."
    }
}

if ($taskIntakeExampleRows.Count -gt 0) {
    $taskIntakeExampleColumns = @($taskIntakeExampleRows[0].PSObject.Properties.Name)
    $missingTaskIntakeExampleColumns = @($requiredTaskIntakeColumns | Where-Object { $_ -notin $taskIntakeExampleColumns })
    if ($missingTaskIntakeExampleColumns.Count -eq 0) {
        Add-Check "PASS" "Task intake example columns" "All required columns found."
    }
    else {
        Add-Check "FAIL" "Task intake example columns" "Missing columns: $($missingTaskIntakeExampleColumns -join ', ')"
    }
}

$requiredAgentRunLogColumns = @(
    "run_id",
    "task_id",
    "group",
    "attempt",
    "agent",
    "model",
    "context_source",
    "source_docs",
    "context_pack_id",
    "prompt_path",
    "started_at",
    "ended_at",
    "token_input",
    "token_output",
    "elapsed_minutes",
    "raw_output_path",
    "scorer",
    "score_status",
    "notes"
)

if ($agentRunLogRows.Count -gt 0) {
    $agentRunLogColumns = @($agentRunLogRows[0].PSObject.Properties.Name)
    $missingAgentRunLogColumns = @($requiredAgentRunLogColumns | Where-Object { $_ -notin $agentRunLogColumns })
    if ($missingAgentRunLogColumns.Count -eq 0) {
        Add-Check "PASS" "Agent run log columns" "All required columns found."
    }
    else {
        Add-Check "FAIL" "Agent run log columns" "Missing columns: $($missingAgentRunLogColumns -join ', ')"
    }
}

$requiredPromptManifestColumns = @(
    "task_id",
    "group",
    "prompt_path",
    "context_source",
    "source_docs",
    "notes"
)

$promptManifestColumnsOk = $false
if ($promptManifestRows.Count -gt 0) {
    $promptManifestColumns = @($promptManifestRows[0].PSObject.Properties.Name)
    $missingPromptManifestColumns = @($requiredPromptManifestColumns | Where-Object { $_ -notin $promptManifestColumns })
    if ($missingPromptManifestColumns.Count -eq 0) {
        Add-Check "PASS" "Agent prompt manifest columns" "All required columns found."
        $promptManifestColumnsOk = $true
    }
    else {
        Add-Check "FAIL" "Agent prompt manifest columns" "Missing columns: $($missingPromptManifestColumns -join ', ')"
    }
}

$completeTaskCaseIds = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)
$completeTaskCasesById = @{}
if ($taskCaseRows.Count -gt 0) {
    $requiredTaskCaseColumns = @(
        "task_id",
        "task_type",
        "domain",
        "task_description",
        "allowed_documents",
        "gold_answer_points",
        "required_constraints",
        "expected_evidence",
        "scorer",
        "owner",
        "status",
        "notes"
    )

    $taskCaseColumns = @($taskCaseRows[0].PSObject.Properties.Name)
    $missingTaskCaseColumns = @($requiredTaskCaseColumns | Where-Object { $_ -notin $taskCaseColumns })
    if ($missingTaskCaseColumns.Count -eq 0) {
        Add-Check "PASS" "Agent task case columns" "All required columns found."
    }
    else {
        Add-Check "FAIL" "Agent task case columns" "Missing columns: $($missingTaskCaseColumns -join ', ')"
    }

    $incompleteTaskCases = New-Object System.Collections.Generic.List[string]
    foreach ($row in $taskCaseRows) {
        $missing = New-Object System.Collections.Generic.List[string]
        foreach ($field in @(
            "task_id",
            "task_type",
            "domain",
            "task_description",
            "allowed_documents",
            "gold_answer_points",
            "required_constraints",
            "expected_evidence",
            "scorer",
            "owner"
        )) {
            if (Test-Placeholder $row.$field) {
                $missing.Add($field) | Out-Null
            }
        }

        if ($missing.Count -eq 0) {
            [void]$completeTaskCaseIds.Add($row.task_id)
            $completeTaskCasesById[$row.task_id] = $row
        }
        else {
            $caseId = if (Test-Placeholder $row.task_id) { "<missing-task-id>" } else { $row.task_id }
            $incompleteTaskCases.Add(("{0}: {1}" -f $caseId, ($missing -join ","))) | Out-Null
        }
    }

    if ($completeTaskCaseIds.Count -ge 3) {
        Add-Check "PASS" "Complete Agent task cases" "Complete task cases: $($completeTaskCaseIds.Count)"
    }
    else {
        $status = if ($StrictRealInputs) { "FAIL" } else { "WARN" }
        Add-Check $status "Complete Agent task cases" "Expected at least 3 complete task cases, found $($completeTaskCaseIds.Count)."
    }

    if ($incompleteTaskCases.Count -eq 0) {
        Add-Check "PASS" "Agent task case readiness" "All task cases are complete."
    }
    else {
        $status = if ($StrictRealInputs) { "FAIL" } else { "WARN" }
        Add-Check $status "Agent task case readiness" "Incomplete task cases: $($incompleteTaskCases -join '; ')"
    }
}

$selectedScenarioRows = @()
if ($scenarioRows.Count -gt 0) {
    $selectedScenarioRows = @($scenarioRows | Where-Object { Test-Affirmative $_.selected })
    if ($selectedScenarioRows.Count -ge 3) {
        Add-Check "PASS" "Selected real Agent tasks" "Selected tasks: $($selectedScenarioRows.Count)"
    }
    else {
        $status = if ($StrictRealInputs) { "FAIL" } else { "WARN" }
        Add-Check $status "Selected real Agent tasks" "Expected at least 3 selected tasks, found $($selectedScenarioRows.Count)."
    }

    $incompleteSelectedTasks = New-Object System.Collections.Generic.List[string]
    foreach ($row in $selectedScenarioRows) {
        $missing = New-Object System.Collections.Generic.List[string]
        foreach ($field in @("task_id", "task_type", "real_source", "monthly_frequency", "owner")) {
            if (Test-Placeholder $row.$field) {
                $missing.Add($field) | Out-Null
            }
        }

        if (-not (Test-Affirmative $row.has_gold_answer)) {
            $missing.Add("has_gold_answer") | Out-Null
        }
        if (-not (Test-Affirmative $row.needs_evidence)) {
            $missing.Add("needs_evidence") | Out-Null
        }
        if (-not $completeTaskCaseIds.Contains($row.task_id)) {
            $missing.Add("complete_task_case") | Out-Null
        }

        if ($missing.Count -gt 0) {
            $incompleteSelectedTasks.Add("$($row.task_id): $($missing -join ',')") | Out-Null
        }
    }

    if ($selectedScenarioRows.Count -eq 0) {
        $status = if ($StrictRealInputs) { "FAIL" } else { "WARN" }
        Add-Check $status "Selected task readiness" "No selected tasks to validate."
    }
    elseif ($incompleteSelectedTasks.Count -eq 0) {
        Add-Check "PASS" "Selected task readiness" "Selected tasks have owner, source, gold answer, and evidence requirements."
    }
    else {
        $status = if ($StrictRealInputs) { "FAIL" } else { "WARN" }
        Add-Check $status "Selected task readiness" "Incomplete selected tasks: $($incompleteSelectedTasks -join '; ')"
    }
}

if ($promptManifestColumnsOk -and $selectedScenarioRows.Count -gt 0) {
    $promptIssues = New-Object System.Collections.Generic.List[string]
    $promptPairsReady = 0

    foreach ($scenarioRow in $selectedScenarioRows) {
        if (-not $completeTaskCasesById.ContainsKey($scenarioRow.task_id)) {
            continue
        }

        $taskCase = $completeTaskCasesById[$scenarioRow.task_id]
        $taskPromptRows = @($promptManifestRows | Where-Object { $_.task_id -eq $taskCase.task_id })
        $taskPairReady = $true

        foreach ($group in @("baseline", "context_pack")) {
            $groupRows = @($taskPromptRows | Where-Object { $_.group -eq $group })
            if ($groupRows.Count -eq 0) {
                $promptIssues.Add(("{0}/{1}: missing prompt manifest row" -f $taskCase.task_id, $group)) | Out-Null
                $taskPairReady = $false
                continue
            }

            $promptRow = $groupRows[0]
            if (Test-Placeholder $promptRow.prompt_path) {
                $promptIssues.Add(("{0}/{1}: missing prompt_path" -f $taskCase.task_id, $group)) | Out-Null
                $taskPairReady = $false
                continue
            }

            $expectedContextSource = if ($group -eq "baseline") { "raw_files" } else { "context_pack" }
            if ($promptRow.context_source -ne $expectedContextSource) {
                $promptIssues.Add(("{0}/{1}: expected context_source={2}, got {3}" -f $taskCase.task_id, $group, $expectedContextSource, $promptRow.context_source)) | Out-Null
                $taskPairReady = $false
            }

            if (Test-Placeholder $promptRow.source_docs) {
                $promptIssues.Add(("{0}/{1}: missing source_docs" -f $taskCase.task_id, $group)) | Out-Null
                $taskPairReady = $false
            }

            $promptPath = Resolve-ExperimentPath $promptRow.prompt_path
            if ($null -eq $promptPath -or -not (Test-Path -LiteralPath $promptPath -PathType Leaf)) {
                $promptIssues.Add(("{0}/{1}: prompt file not found: {2}" -f $taskCase.task_id, $group, $promptRow.prompt_path)) | Out-Null
                $taskPairReady = $false
                continue
            }

            $promptText = Get-Content -LiteralPath $promptPath -Raw -Encoding UTF8
            foreach ($requiredTerm in @("## Answer", "## Evidence", "## Gaps Or Assumptions", "## Follow-up Needed")) {
                if ($promptText -notlike "*$requiredTerm*") {
                    $promptIssues.Add(("{0}/{1}: prompt missing output section {2}" -f $taskCase.task_id, $group, $requiredTerm)) | Out-Null
                    $taskPairReady = $false
                }
            }

            if (-not (Test-Placeholder $taskCase.task_description) -and $promptText -notlike "*$($taskCase.task_description)*") {
                $promptIssues.Add(("{0}/{1}: prompt missing task_description" -f $taskCase.task_id, $group)) | Out-Null
                $taskPairReady = $false
            }

            foreach ($field in @("gold_answer_points", "required_constraints", "expected_evidence")) {
                $value = [string]$taskCase.$field
                if (-not (Test-Placeholder $value) -and $value.Trim().Length -ge 12 -and $promptText -like "*$($value.Trim())*") {
                    $promptIssues.Add(("{0}/{1}: prompt leaks scorer-only field {2}" -f $taskCase.task_id, $group, $field)) | Out-Null
                    $taskPairReady = $false
                }
            }
        }

        if ($taskPairReady) {
            $promptPairsReady++
        }
    }

    if ($promptIssues.Count -eq 0 -and $promptPairsReady -ge 3) {
        Add-Check "PASS" "Agent prompt readiness" "Prompt pairs ready: $promptPairsReady"
    }
    else {
        $status = if ($StrictRealInputs) { "FAIL" } else { "WARN" }
        $topIssues = @($promptIssues | Select-Object -First 5)
        Add-Check $status "Agent prompt readiness" "Prompt pairs ready: $promptPairsReady; issues: $($topIssues -join '; ')"
    }
}

$jsonPath = Join-Path $ExperimentDir "context-pack-template.json"
if (Test-Path -LiteralPath $jsonPath) {
    try {
        Get-Content -LiteralPath $jsonPath -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null
        Add-Check "PASS" "Context Pack JSON template" "JSON parsed."
    }
    catch {
        Add-Check "FAIL" "Context Pack JSON template" "JSON parse failed: $($_.Exception.Message)"
    }
}

$taskCardPath = Join-Path $ExperimentDir "agent-task-cards.md"
if (Test-Path -LiteralPath $taskCardPath) {
    $taskCard = Get-Content -LiteralPath $taskCardPath -Raw -Encoding UTF8
    $hasPlaceholder = $false
    foreach ($term in $PlaceholderTerms) {
        if ($taskCard -like "*$term*") {
            $hasPlaceholder = $true
            break
        }
    }

    if ($hasPlaceholder) {
        $status = if ($StrictRealInputs) { "FAIL" } else { "WARN" }
        Add-Check $status "Agent task cards" "Task cards still contain placeholders."
    }
    else {
        Add-Check "PASS" "Agent task cards" "No placeholders found."
    }
}

Test-TextContains `
    -Path (Join-Path $ProjectRoot "README.md") `
    -Terms $PhaseBoundaryTerms `
    -Name "README phase boundary"

Test-TextContains `
    -Path (Join-Path $ProjectRoot "docs\api-contract.md") `
    -Terms @("/api/context-pack", "/api/search", "/api/evidence", "agent-knowledge", "Context Pack") `
    -Name "Agent API/Core contract"

Test-TextContains `
    -Path (Join-Path $ProjectRoot "docs\evaluation.md") `
    -Terms $AcceptanceTerms `
    -Name "Evaluation phase boundary"

Test-TextContains `
    -Path (Join-Path $ProjectRoot "docs\overview.md") `
    -Terms @("AI Knowledge Foundation", "Context Pack", "local agent entry", "MCP is not the current product route") `
    -Name "Direction terms"

Test-TextContains `
    -Path (Join-Path $ProjectRoot "docs\archive\06-operations\owner-collection-package.md") `
    -Terms @("document-intake-template.csv", "task-intake-template.csv", "Context Pack") `
    -Name "Owner intake terms"

Test-TextContains `
    -Path (Join-Path $ProjectRoot "docs\archive\06-operations\owner-return-checklist.md") `
    -Terms @("document-intake-template.csv", "task-intake-template.csv", "gold_answer_points", "expected_evidence", "READY_TO_CREATE_EXPERIMENT_RUN") `
    -Name "Owner return checklist terms"

Test-TextContains `
    -Path (Join-Path $ProjectRoot "docs\archive\05-evaluation\goal-acceptance-evidence-matrix.md") `
    -Terms @("Context Pack", "Core API", "READY_TO_CREATE_EXPERIMENT_RUN", "baseline/context_pack", "Run evidence readiness", "Experiment result gate") `
    -Name "Goal evidence matrix terms"

Write-Host ""
$Checks | Sort-Object @{Expression = {
    switch ($_.Status) {
        "FAIL" { 0 }
        "WARN" { 1 }
        "PASS" { 2 }
    }
}}, Name | Format-Table -AutoSize

$failCount = @($Checks | Where-Object { $_.Status -eq "FAIL" }).Count
$warnCount = @($Checks | Where-Object { $_.Status -eq "WARN" }).Count
$passCount = @($Checks | Where-Object { $_.Status -eq "PASS" }).Count

Write-Host ""
Write-Host "Summary: PASS=$passCount WARN=$warnCount FAIL=$failCount"

if ($failCount -gt 0) {
    exit 1
}

exit 0
