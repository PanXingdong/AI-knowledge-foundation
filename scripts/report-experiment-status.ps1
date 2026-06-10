param(
    [string]$ExperimentDir,
    [string]$SampleManifestPath,
    [string]$SampleRawDir,
    [string]$DocumentIntakePath,
    [string]$TaskIntakePath,
    [string]$OwnerTrackerPath,
    [string]$ReportPath,
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Resolve-InputPath {
    param(
        [string]$Value,
        [string]$DefaultRelativePath
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return Join-Path $ProjectRoot $DefaultRelativePath
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    return Join-Path $ProjectRoot $Value
}

$ExperimentDir = Resolve-InputPath $ExperimentDir "experiments\templates"
$SampleManifestPath = Resolve-InputPath $SampleManifestPath "samples\sample-manifest.csv"
$SampleRawDir = Resolve-InputPath $SampleRawDir "samples\raw"
$DocumentIntakePath = Resolve-InputPath $DocumentIntakePath "samples\document-intake-template.csv"
$TaskIntakePath = Resolve-InputPath $TaskIntakePath "experiments\templates\task-intake-template.csv"
$OwnerTrackerPath = Resolve-InputPath $OwnerTrackerPath "samples\owner-response-tracker.csv"

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

$SupportedDocExtensions = @(".pdf", ".docx", ".doc", ".html", ".htm")

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

function Test-ExternalSourceLocation {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $false
    }

    return $Value.Trim() -match '^(https?)://'
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

function Convert-ToNumberMetric {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $null
    }

    $text = $Value.Trim()
    $isPercent = $text.EndsWith("%")
    if ($isPercent) {
        $text = $text.Substring(0, $text.Length - 1).Trim()
    }

    $number = 0.0
    $ok = [double]::TryParse(
        $text,
        [System.Globalization.NumberStyles]::Float,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [ref]$number
    )

    if (-not $ok) {
        return $null
    }

    if ($isPercent) {
        return $number / 100.0
    }

    return $number
}

function Import-CsvOrEmpty {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }

    return @(Import-Csv -LiteralPath $Path -Encoding UTF8)
}

function Get-MissingFields {
    param(
        [object]$Row,
        [string[]]$Fields
    )

    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($field in $Fields) {
        if (Test-Placeholder $Row.$field) {
            $missing.Add($field) | Out-Null
        }
    }

    return @($missing)
}

function New-SectionStatus {
    param(
        [string]$Section,
        [ValidateSet("READY", "BLOCKED", "INCOMPLETE", "INFO")]
        [string]$Status,
        [string]$Evidence,
        [string]$NextAction
    )

    return [pscustomobject]@{
        Section = $Section
        Status = $Status
        Evidence = $Evidence
        NextAction = $NextAction
    }
}

$manifestRows = Import-CsvOrEmpty $SampleManifestPath
$documentIntakeRows = Import-CsvOrEmpty $DocumentIntakePath
$taskIntakeRows = Import-CsvOrEmpty $TaskIntakePath
$ownerTrackerRows = Import-CsvOrEmpty $OwnerTrackerPath
$taskCaseRows = Import-CsvOrEmpty (Join-Path $ExperimentDir "agent-task-cases.csv")
$scenarioRows = Import-CsvOrEmpty (Join-Path $ExperimentDir "scenario-selection-matrix.csv")
$parserRows = Import-CsvOrEmpty (Join-Path $ExperimentDir "parser-evaluation-sheet.csv")
$resultRows = Import-CsvOrEmpty (Join-Path $ExperimentDir "baseline-vs-contextpack-results.csv")
$agentRunLogRows = Import-CsvOrEmpty (Join-Path $ExperimentDir "agent-run-log.csv")
$taskCardsPath = Join-Path $ExperimentDir "agent-task-cards.md"

$rawDocs = @()
if (Test-Path -LiteralPath $SampleRawDir) {
    $rawDocs = @(Get-ChildItem -LiteralPath $SampleRawDir -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $SupportedDocExtensions -contains $_.Extension.ToLowerInvariant() })
}

$manifestReadyRows = @(
    $manifestRows | Where-Object {
        $path = Resolve-ProjectPath $_.file_path
        (-not (Test-Placeholder $_.file_path)) -and
            $null -ne $path -and
            (Test-Path -LiteralPath $path)
    }
)

$readyDocumentCandidates = @(
    foreach ($row in $documentIntakeRows) {
        $missing = Get-MissingFields $row @(
            "candidate_id",
            "slot_type",
            "source_location",
            "document_title",
            "document_version",
            "owner",
            "candidate_reason"
        )

        if (-not (Test-Affirmative $row.allowed_for_experiment)) {
            $missing += "allowed_for_experiment"
        }

        if (-not (Test-Placeholder $row.source_location)) {
            if (Test-ExternalSourceLocation $row.source_location) {
                $missing += "source_location_local_file"
            }
            else {
                $resolved = Resolve-ProjectPath $row.source_location
                if ($null -eq $resolved -or -not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
                    $missing += "source_location_exists"
                }
            }
        }

        if ($missing.Count -eq 0) {
            $row
        }
    }
)

$readyTaskCandidates = @(
    foreach ($row in $taskIntakeRows) {
        if (-not (Test-Affirmative $row.selected)) {
            continue
        }

        $missing = Get-MissingFields $row @(
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
            "scorer"
        )

        if (-not (Test-Affirmative $row.needs_evidence)) {
            $missing += "needs_evidence"
        }

        if ($missing.Count -eq 0) {
            $row
        }
    }
)

$completeTaskCases = @(
    foreach ($row in $taskCaseRows) {
        $missing = Get-MissingFields $row @(
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
        )

        if ($missing.Count -eq 0) {
            $row
        }
    }
)

$selectedScenarioRows = @($scenarioRows | Where-Object { Test-Affirmative $_.selected })

$taskCardsReady = $false
if (Test-Path -LiteralPath $taskCardsPath) {
    $taskCardText = Get-Content -LiteralPath $taskCardsPath -Raw -Encoding UTF8
    $hasPlaceholder = $false
    foreach ($term in $PlaceholderTerms) {
        if ($taskCardText -like "*$term*") {
            $hasPlaceholder = $true
            break
        }
    }
    $taskCardsReady = -not $hasPlaceholder
}

$completeParserRows = @(
    foreach ($row in $parserRows) {
        $metricValues = @(
            (Convert-ToNumberMetric $row.page_metadata_rate),
            (Convert-ToNumberMetric $row.span_traceability_rate),
            (Convert-ToNumberMetric $row.table_accuracy),
            (Convert-ToNumberMetric $row.reading_order_accuracy),
            (Convert-ToNumberMetric $row.ocr_accuracy),
            (Convert-ToNumberMetric $row.parse_minutes),
            (Convert-ToNumberMetric $row.critical_failures)
        )
        $missingMetric = $false
        foreach ($value in $metricValues) {
            if ($null -eq $value) {
                $missingMetric = $true
                break
            }
        }

        if (
            -not $missingMetric -and
            -not (Test-Placeholder $row.document_id) -and
            -not (Test-Placeholder $row.file_path) -and
            -not (Test-Placeholder $row.parser)
        ) {
            $row
        }
    }
)

$parserCoverage = @(
    $completeParserRows |
        Group-Object parser |
        ForEach-Object {
            [pscustomobject]@{
                Parser = $_.Name
                DistinctDocuments = @($_.Group | ForEach-Object { $_.document_id } | Select-Object -Unique).Count
            }
        }
)
$coveredParserCount = @($parserCoverage | Where-Object { $_.DistinctDocuments -ge 10 }).Count

function Test-CompleteResultRow {
    param([pscustomobject]$Row)

    foreach ($field in @(
        "task_id",
        "group",
        "answer_correct",
        "missed_constraints",
        "wrong_claims",
        "citation_correct",
        "token_cost",
        "elapsed_minutes",
        "human_fix_count"
    )) {
        if (Test-Placeholder $Row.$field) {
            return $false
        }
    }

    return $true
}

function Test-CompleteAgentRunLogRow {
    param([pscustomobject]$Row)

    foreach ($field in @(
        "run_id",
        "task_id",
        "group",
        "attempt",
        "agent",
        "model",
        "context_source",
        "source_docs",
        "started_at",
        "ended_at",
        "raw_output_path",
        "scorer",
        "score_status"
    )) {
        if (Test-Placeholder $Row.$field) {
            return $false
        }
    }

    $rawOutputPath = Resolve-ExperimentPath $Row.raw_output_path
    if ($null -eq $rawOutputPath -or -not (Test-Path -LiteralPath $rawOutputPath -PathType Leaf)) {
        return $false
    }

    return $true
}

$completeResultRows = @($resultRows | Where-Object { Test-CompleteResultRow $_ })
$completeResultPairs = New-Object System.Collections.Generic.List[object]
foreach ($taskGroup in ($completeResultRows | Group-Object task_id)) {
    $baseline = @($taskGroup.Group | Where-Object { $_.group -eq "baseline" })
    $contextPack = @($taskGroup.Group | Where-Object { $_.group -eq "context_pack" })
    if ($baseline.Count -gt 0 -and $contextPack.Count -gt 0) {
        $completeResultPairs.Add($taskGroup.Name) | Out-Null
    }
}

$completeAgentRunLogRows = @($agentRunLogRows | Where-Object { Test-CompleteAgentRunLogRow $_ })
$completeAgentRunLogPairs = New-Object System.Collections.Generic.List[object]
foreach ($taskGroup in ($completeAgentRunLogRows | Group-Object task_id)) {
    $baseline = @($taskGroup.Group | Where-Object { $_.group -eq "baseline" })
    $contextPack = @($taskGroup.Group | Where-Object { $_.group -eq "context_pack" })
    if ($baseline.Count -gt 0 -and $contextPack.Count -gt 0) {
        $completeAgentRunLogPairs.Add($taskGroup.Name) | Out-Null
    }
}

$traceableResultPairs = @($completeResultPairs | Where-Object { $completeAgentRunLogPairs -contains $_ })

$statuses = New-Object System.Collections.Generic.List[object]

$ownerTrackerRowCount = @($ownerTrackerRows).Count
$trackerSentCount = @($ownerTrackerRows | Where-Object { $_.current_status -in @("sent", "partial", "ready", "blocked") }).Count
$trackerPartialCount = @($ownerTrackerRows | Where-Object { $_.current_status -eq "partial" }).Count
$trackerReadyCount = @($ownerTrackerRows | Where-Object { $_.current_status -eq "ready" }).Count
$trackerBlockedCount = @($ownerTrackerRows | Where-Object { $_.current_status -eq "blocked" }).Count
$trackerProvidedDocuments = (($ownerTrackerRows | ForEach-Object { Convert-ToNumberMetric $_.provided_documents } | Where-Object { $null -ne $_ } | Measure-Object -Sum).Sum)
$trackerProvidedTasks = (($ownerTrackerRows | ForEach-Object { Convert-ToNumberMetric $_.provided_tasks } | Where-Object { $null -ne $_ } | Measure-Object -Sum).Sum)
if ($null -eq $trackerProvidedDocuments) {
    $trackerProvidedDocuments = 0
}
if ($null -eq $trackerProvidedTasks) {
    $trackerProvidedTasks = 0
}

$trackerStarted = ($trackerSentCount -gt 0 -or $trackerProvidedDocuments -gt 0 -or $trackerProvidedTasks -gt 0)
$statuses.Add((New-SectionStatus `
    "Owner response tracking" `
    "INFO" `
    "rows=$ownerTrackerRowCount; sent_or_later=$trackerSentCount; partial=$trackerPartialCount; ready=$trackerReadyCount; blocked=$trackerBlockedCount; provided_docs=$trackerProvidedDocuments; provided_tasks=$trackerProvidedTasks" `
    $(if ($trackerStarted) { "Follow up owner rows until intake tables are ready." } else { "Send docs/archive/06-operations/owner-collection-package.md and update owner-response-tracker.csv." }))) | Out-Null

$docsReady = ($manifestReadyRows.Count -ge 10 -and $rawDocs.Count -ge 10)
$statuses.Add((New-SectionStatus `
    "Sample documents" `
    $(if ($docsReady) { "READY" } else { "BLOCKED" }) `
    "manifest_ready=$($manifestReadyRows.Count)/10; raw_docs=$($rawDocs.Count)/10" `
    $(if ($docsReady) { "Proceed to run preparation." } else { "Fill document intake and run prepare-experiment-run-from-intake.ps1 -Apply." }))) | Out-Null

$docIntakeReady = (
    $readyDocumentCandidates.Count -ge 10 -and
    @($readyDocumentCandidates | Where-Object { Test-Affirmative $_.has_tables }).Count -gt 0 -and
    @($readyDocumentCandidates | Where-Object { Test-Affirmative $_.has_multicolumn }).Count -gt 0 -and
    @($readyDocumentCandidates | Where-Object { Test-Affirmative $_.is_scanned }).Count -gt 0
)
$taskTypes = @($readyTaskCandidates | ForEach-Object { $_.task_type } | Select-Object -Unique)
$taskIntakeReady = ($readyTaskCandidates.Count -ge 3 -and $taskTypes.Count -ge 3)
$ownerReady = ($docIntakeReady -and $taskIntakeReady)
$statuses.Add((New-SectionStatus `
    "Owner intake" `
    $(if ($ownerReady) { "READY" } else { "BLOCKED" }) `
    "ready_docs=$($readyDocumentCandidates.Count)/10; ready_tasks=$($readyTaskCandidates.Count)/3; task_types=$($taskTypes.Count)/3" `
    $(if ($ownerReady) { "Run prepare-experiment-run-from-intake.ps1 -Apply." } else { "Complete document-intake-template.csv and task-intake-template.csv." }))) | Out-Null

$runReady = ($completeTaskCases.Count -ge 3 -and $selectedScenarioRows.Count -ge 3 -and $taskCardsReady)
$statuses.Add((New-SectionStatus `
    "Experiment run" `
    $(if ($runReady) { "READY" } else { "BLOCKED" }) `
    "complete_task_cases=$($completeTaskCases.Count)/3; selected_tasks=$($selectedScenarioRows.Count)/3; task_cards_ready=$taskCardsReady" `
    $(if ($runReady) { "Run parser comparison and baseline/context_pack tasks." } else { "Create run and apply selected task intake." }))) | Out-Null

$parserReady = ($coveredParserCount -ge 3)
$statuses.Add((New-SectionStatus `
    "Parser evaluation" `
    $(if ($parserReady) { "READY" } else { "INCOMPLETE" }) `
    "complete_rows=$($completeParserRows.Count); parsers_covering_10_docs=$coveredParserCount/3" `
    $(if ($parserReady) { "Run evaluate-parser-results.ps1 for parser choice." } else { "Fill parser-evaluation-sheet.csv after parsing 10 docs with 3 parsers." }))) | Out-Null

$resultsReady = ($completeResultPairs.Count -ge 3)
$statuses.Add((New-SectionStatus `
    "Baseline vs Context Pack" `
    $(if ($resultsReady) { "READY" } else { "INCOMPLETE" }) `
    "complete_task_pairs=$($completeResultPairs.Count)/3" `
    $(if ($resultsReady) { "Run evaluate-results.ps1 for phase 2 recommendation." } else { "Run baseline and context_pack tasks, then fill baseline-vs-contextpack-results.csv." }))) | Out-Null

$traceabilityReady = ($traceableResultPairs.Count -ge 3)
$statuses.Add((New-SectionStatus `
    "Execution traceability" `
    $(if ($traceabilityReady) { "READY" } else { "INCOMPLETE" }) `
    "traceable_task_pairs=$($traceableResultPairs.Count)/3; complete_run_log_pairs=$($completeAgentRunLogPairs.Count)/3" `
    $(if ($traceabilityReady) { "Result pairs can be traced to raw Agent outputs." } else { "Fill agent-run-log.csv and keep raw Agent outputs for each baseline/context_pack pair." }))) | Out-Null

$blocked = @($statuses | Where-Object { $_.Status -eq "BLOCKED" })
$incomplete = @($statuses | Where-Object { $_.Status -eq "INCOMPLETE" })

$overall = if ($blocked.Count -gt 0) {
    "BLOCKED_ON_REAL_INPUTS"
}
elseif ($incomplete.Count -gt 0) {
    "READY_FOR_EXPERIMENT_EXECUTION"
}
else {
    "READY_FOR_PHASE_2_DECISION"
}

$nextAction = if (-not $ownerReady) {
    "Complete owner document/task intake, then run check-intake-readiness.ps1 -Strict."
}
elseif (-not $docsReady -or -not $runReady) {
    "Run prepare-experiment-run-from-intake.ps1 -RunId run-001 -Apply."
}
elseif (-not $parserReady) {
    "Run parser comparison and fill parser-evaluation-sheet.csv."
}
elseif (-not $resultsReady) {
    "Run baseline/context_pack tasks and fill baseline-vs-contextpack-results.csv."
}
elseif (-not $traceabilityReady) {
    "Fill agent-run-log.csv and preserve raw Agent output files for all result pairs."
}
else {
    "Run evaluate-parser-results.ps1 and evaluate-results.ps1, then hold phase 2 review."
}

Write-Host "Agent Knowledge Hub experiment status"
Write-Host "Project root: $ProjectRoot"
Write-Host "Experiment dir: $ExperimentDir"
Write-Host "Sample manifest: $SampleManifestPath"
Write-Host "Sample raw dir: $SampleRawDir"
Write-Host "Owner tracker: $OwnerTrackerPath"
Write-Host ""
$statuses | Format-Table -AutoSize
Write-Host ""
Write-Host "Overall: $overall"
Write-Host "Next action: $nextAction"

if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
    $report = @()
    $report += "# Agent Knowledge Hub Experiment Status"
    $report += ""
    $report += "- Overall: $overall"
    $report += "- Next action: $nextAction"
    $report += ('- Experiment dir: `{0}`' -f $ExperimentDir)
    $report += ('- Sample manifest: `{0}`' -f $SampleManifestPath)
    $report += ('- Sample raw dir: `{0}`' -f $SampleRawDir)
    $report += ('- Owner tracker: `{0}`' -f $OwnerTrackerPath)
    $report += ""
    $report += "## Sections"
    foreach ($status in $statuses) {
        $report += "- $($status.Section): $($status.Status); $($status.Evidence); next: $($status.NextAction)"
    }

    $reportDir = Split-Path -Parent $ReportPath
    if (-not [string]::IsNullOrWhiteSpace($reportDir) -and -not (Test-Path -LiteralPath $reportDir)) {
        New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
    }
    Set-Content -LiteralPath $ReportPath -Value $report -Encoding UTF8
    Write-Host "Report written: $ReportPath"
}

if ($Strict -and $overall -ne "READY_FOR_PHASE_2_DECISION") {
    exit 1
}

exit 0
