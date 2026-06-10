param(
    [string]$ExperimentDir,
    [string]$ReportPath,
    [int]$MinimumTaskPairs = 3,
    [int]$MinimumDocuments = 10,
    [int]$MinimumParsers = 3,
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($ExperimentDir)) {
    $ExperimentDir = Join-Path $ProjectRoot "experiments\templates"
}
elseif (-not [System.IO.Path]::IsPathRooted($ExperimentDir)) {
    $ExperimentDir = Join-Path $ProjectRoot $ExperimentDir
}

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
    "placeholder"
)

$TrueTerms = @(
    "1",
    "true",
    "yes",
    "y",
    "pass",
    "passed",
    "correct",
    (New-TextFromCodePoints @(0x662F)),
    (New-TextFromCodePoints @(0x6B63, 0x786E)),
    (New-TextFromCodePoints @(0x901A, 0x8FC7))
)

$FalseTerms = @(
    "0",
    "false",
    "no",
    "n",
    "fail",
    "failed",
    "incorrect",
    "wrong",
    (New-TextFromCodePoints @(0x5426)),
    (New-TextFromCodePoints @(0x9519, 0x8BEF)),
    (New-TextFromCodePoints @(0x5931, 0x8D25))
)

$ScoredStatusTerms = @("scored", "score_done", "reviewed", "complete", "completed", "done", "ready")

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

function Convert-ToBoolMetric {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $null
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    if ($TrueTerms -contains $normalized) {
        return $true
    }
    if ($FalseTerms -contains $normalized) {
        return $false
    }

    return $null
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

function Import-CsvOrFail {
    param(
        [string]$Path,
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Write-Error "Missing $Name file: $Path"
    }

    return @(Import-Csv -LiteralPath $Path -Encoding UTF8)
}

function Assert-RequiredColumns {
    param(
        [object[]]$Rows,
        [string[]]$RequiredColumns,
        [string]$Name
    )

    if ($Rows.Count -eq 0) {
        Write-Error "$Name has no rows."
    }

    $columns = @($Rows[0].PSObject.Properties.Name)
    $missing = @($RequiredColumns | Where-Object { $_ -notin $columns })
    if ($missing.Count -gt 0) {
        Write-Error "$Name is missing columns: $($missing -join ', ')"
    }
}

function Resolve-ExperimentPath {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return [System.IO.Path]::GetFullPath($Value)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $ExperimentDir $Value))
}

function Get-MissingTextFields {
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

function Get-ResultReadiness {
    param([object]$Row)

    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($field in @("task_id", "group", "agent", "source_docs")) {
        if (Test-Placeholder $Row.$field) {
            $missing.Add($field) | Out-Null
        }
    }

    foreach ($pair in @(
        @{ Name = "answer_correct"; Value = (Convert-ToBoolMetric $Row.answer_correct) },
        @{ Name = "citation_correct"; Value = (Convert-ToBoolMetric $Row.citation_correct) },
        @{ Name = "missed_constraints"; Value = (Convert-ToNumberMetric $Row.missed_constraints) },
        @{ Name = "wrong_claims"; Value = (Convert-ToNumberMetric $Row.wrong_claims) },
        @{ Name = "token_cost"; Value = (Convert-ToNumberMetric $Row.token_cost) },
        @{ Name = "elapsed_minutes"; Value = (Convert-ToNumberMetric $Row.elapsed_minutes) },
        @{ Name = "human_fix_count"; Value = (Convert-ToNumberMetric $Row.human_fix_count) }
    )) {
        if ($null -eq $pair.Value) {
            $missing.Add($pair.Name) | Out-Null
        }
    }

    if ($Row.group -eq "context_pack") {
        foreach ($pair in @(
            @{ Name = "context_pack_tokens"; Value = (Convert-ToNumberMetric $Row.context_pack_tokens) },
            @{ Name = "retrieved_span_count"; Value = (Convert-ToNumberMetric $Row.retrieved_span_count) },
            @{ Name = "useful_span_count"; Value = (Convert-ToNumberMetric $Row.useful_span_count) },
            @{ Name = "irrelevant_span_count"; Value = (Convert-ToNumberMetric $Row.irrelevant_span_count) }
        )) {
            if ($null -eq $pair.Value) {
                $missing.Add($pair.Name) | Out-Null
            }
        }

        if (Test-Placeholder $Row.retrieval_failure) {
            $missing.Add("retrieval_failure") | Out-Null
        }
    }

    return [pscustomobject]@{
        TaskId = $Row.task_id
        Group = $Row.group
        MissingFields = @($missing)
        IsComplete = ($missing.Count -eq 0)
    }
}

function Get-RunLogReadiness {
    param([object]$Row)

    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($field in @(
        "run_id",
        "task_id",
        "group",
        "attempt",
        "agent",
        "model",
        "context_source",
        "source_docs",
        "prompt_path",
        "started_at",
        "ended_at",
        "raw_output_path",
        "scorer",
        "score_status"
    )) {
        if (Test-Placeholder $Row.$field) {
            $missing.Add($field) | Out-Null
        }
    }

    foreach ($pair in @(
        @{ Name = "attempt"; Value = (Convert-ToNumberMetric $Row.attempt) },
        @{ Name = "token_input"; Value = (Convert-ToNumberMetric $Row.token_input) },
        @{ Name = "token_output"; Value = (Convert-ToNumberMetric $Row.token_output) },
        @{ Name = "elapsed_minutes"; Value = (Convert-ToNumberMetric $Row.elapsed_minutes) }
    )) {
        if ($null -eq $pair.Value) {
            $missing.Add($pair.Name) | Out-Null
        }
    }

    if ($Row.group -eq "baseline" -and $Row.context_source -ne "raw_files") {
        $missing.Add("context_source_raw_files") | Out-Null
    }
    if ($Row.group -eq "context_pack" -and $Row.context_source -ne "context_pack") {
        $missing.Add("context_source_context_pack") | Out-Null
    }

    $promptPath = Resolve-ExperimentPath $Row.prompt_path
    if ($null -eq $promptPath -or -not (Test-Path -LiteralPath $promptPath -PathType Leaf)) {
        $missing.Add("prompt_path_exists") | Out-Null
    }

    $rawOutputPath = Resolve-ExperimentPath $Row.raw_output_path
    if ($null -eq $rawOutputPath -or -not (Test-Path -LiteralPath $rawOutputPath -PathType Leaf)) {
        $missing.Add("raw_output_path_exists") | Out-Null
    }
    else {
        $rawOutput = Get-Item -LiteralPath $rawOutputPath
        if ($rawOutput.Length -le 0) {
            $missing.Add("raw_output_nonempty") | Out-Null
        }
    }

    if (-not (Test-Placeholder $Row.score_status)) {
        $normalizedStatus = $Row.score_status.Trim().ToLowerInvariant()
        if ($ScoredStatusTerms -notcontains $normalizedStatus) {
            $missing.Add("score_status_scored") | Out-Null
        }
    }

    return [pscustomobject]@{
        TaskId = $Row.task_id
        Group = $Row.group
        MissingFields = @($missing)
        IsComplete = ($missing.Count -eq 0)
    }
}

function Get-ParserReadiness {
    param([object]$Row)

    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($field in @("document_id", "file_path", "parser")) {
        if (Test-Placeholder $Row.$field) {
            $missing.Add($field) | Out-Null
        }
    }

    foreach ($pair in @(
        @{ Name = "page_metadata_rate"; Value = (Convert-ToNumberMetric $Row.page_metadata_rate) },
        @{ Name = "span_traceability_rate"; Value = (Convert-ToNumberMetric $Row.span_traceability_rate) },
        @{ Name = "table_accuracy"; Value = (Convert-ToNumberMetric $Row.table_accuracy) },
        @{ Name = "reading_order_accuracy"; Value = (Convert-ToNumberMetric $Row.reading_order_accuracy) },
        @{ Name = "ocr_accuracy"; Value = (Convert-ToNumberMetric $Row.ocr_accuracy) },
        @{ Name = "parse_minutes"; Value = (Convert-ToNumberMetric $Row.parse_minutes) },
        @{ Name = "critical_failures"; Value = (Convert-ToNumberMetric $Row.critical_failures) }
    )) {
        if ($null -eq $pair.Value) {
            $missing.Add($pair.Name) | Out-Null
        }
    }

    return [pscustomobject]@{
        DocumentId = $Row.document_id
        Parser = $Row.parser
        MissingFields = @($missing)
        IsComplete = ($missing.Count -eq 0)
    }
}

function Get-PairedTaskIds {
    param(
        [object[]]$Rows,
        [string]$TaskProperty,
        [string]$GroupProperty
    )

    $pairs = New-Object System.Collections.Generic.List[string]
    foreach ($taskGroup in ($Rows | Group-Object -Property $TaskProperty)) {
        $baseline = @($taskGroup.Group | Where-Object { $_.$GroupProperty -eq "baseline" })
        $contextPack = @($taskGroup.Group | Where-Object { $_.$GroupProperty -eq "context_pack" })
        if ($baseline.Count -gt 0 -and $contextPack.Count -gt 0) {
            $pairs.Add($taskGroup.Name) | Out-Null
        }
    }

    return @($pairs)
}

function New-SectionStatus {
    param(
        [string]$Section,
        [ValidateSet("READY", "INCOMPLETE", "BLOCKED")]
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

$taskCaseRows = Import-CsvOrFail (Join-Path $ExperimentDir "agent-task-cases.csv") "agent task cases"
$scenarioRows = Import-CsvOrFail (Join-Path $ExperimentDir "scenario-selection-matrix.csv") "scenario selection"
$parserRows = Import-CsvOrFail (Join-Path $ExperimentDir "parser-evaluation-sheet.csv") "parser evaluation"
$resultRows = Import-CsvOrFail (Join-Path $ExperimentDir "baseline-vs-contextpack-results.csv") "baseline/context_pack results"
$runLogRows = Import-CsvOrFail (Join-Path $ExperimentDir "agent-run-log.csv") "agent run log"
$promptManifestRows = Import-CsvOrFail (Join-Path $ExperimentDir "agent-prompt-manifest.csv") "agent prompt manifest"

Assert-RequiredColumns $taskCaseRows @("task_id", "task_type", "domain", "task_description", "allowed_documents", "gold_answer_points", "required_constraints", "expected_evidence", "scorer", "owner") "Agent task cases"
Assert-RequiredColumns $scenarioRows @("task_id", "task_type", "real_source", "monthly_frequency", "has_gold_answer", "needs_evidence", "owner", "selected") "Scenario selection"
Assert-RequiredColumns $parserRows @("document_id", "file_path", "parser", "page_metadata_rate", "span_traceability_rate", "table_accuracy", "reading_order_accuracy", "ocr_accuracy", "parse_minutes", "critical_failures") "Parser evaluation"
Assert-RequiredColumns $resultRows @("task_id", "group", "agent", "source_docs", "answer_correct", "missed_constraints", "wrong_claims", "citation_correct", "token_cost", "elapsed_minutes", "human_fix_count", "context_pack_tokens", "retrieved_span_count", "useful_span_count", "irrelevant_span_count", "retrieval_failure") "Baseline/context_pack results"
Assert-RequiredColumns $runLogRows @("run_id", "task_id", "group", "attempt", "agent", "model", "context_source", "source_docs", "context_pack_id", "prompt_path", "started_at", "ended_at", "token_input", "token_output", "elapsed_minutes", "raw_output_path", "scorer", "score_status") "Agent run log"
Assert-RequiredColumns $promptManifestRows @("task_id", "group", "prompt_path", "context_source", "source_docs") "Agent prompt manifest"

$completeTaskCaseIds = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)
foreach ($row in $taskCaseRows) {
    $missing = Get-MissingTextFields $row @("task_id", "task_type", "domain", "task_description", "allowed_documents", "gold_answer_points", "required_constraints", "expected_evidence", "scorer", "owner")
    if ($missing.Count -eq 0) {
        [void]$completeTaskCaseIds.Add($row.task_id)
    }
}

$selectedCompleteTasks = @(
    foreach ($row in ($scenarioRows | Where-Object { $_.selected -in @("yes", "true", "1", "selected") })) {
        if ($completeTaskCaseIds.Contains($row.task_id)) {
            $row
        }
    }
)

$promptRowsWithFiles = @(
    foreach ($row in $promptManifestRows) {
        $promptPath = Resolve-ExperimentPath $row.prompt_path
        if (
            -not (Test-Placeholder $row.task_id) -and
            -not (Test-Placeholder $row.group) -and
            $null -ne $promptPath -and
            (Test-Path -LiteralPath $promptPath -PathType Leaf)
        ) {
            $row
        }
    }
)
$promptPairs = Get-PairedTaskIds $promptRowsWithFiles "task_id" "group"

$parserReadinessRows = @($parserRows | ForEach-Object { Get-ParserReadiness $_ })
$completeParserRows = @($parserReadinessRows | Where-Object { $_.IsComplete })
$parserCoverage = @(
    $completeParserRows |
        Group-Object Parser |
        ForEach-Object {
            [pscustomobject]@{
                Parser = $_.Name
                DistinctDocuments = @($_.Group | ForEach-Object { $_.DocumentId } | Select-Object -Unique).Count
            }
        }
)
$coveredParserCount = @($parserCoverage | Where-Object { $_.DistinctDocuments -ge $MinimumDocuments }).Count

$runLogReadinessRows = @($runLogRows | ForEach-Object { Get-RunLogReadiness $_ })
$completeRunLogRows = @($runLogReadinessRows | Where-Object { $_.IsComplete })
$runLogPairs = Get-PairedTaskIds $completeRunLogRows "TaskId" "Group"

$resultReadinessRows = @($resultRows | ForEach-Object { Get-ResultReadiness $_ })
$completeResultRows = @($resultReadinessRows | Where-Object { $_.IsComplete })
$resultPairs = Get-PairedTaskIds $completeResultRows "TaskId" "Group"

$selectedTaskIds = @($selectedCompleteTasks | ForEach-Object { $_.task_id })
$traceablePairs = @(
    $resultPairs |
        Where-Object {
            $runLogPairs -contains $_ -and
            $promptPairs -contains $_ -and
            $selectedTaskIds -contains $_
        }
)

$statuses = New-Object System.Collections.Generic.List[object]

$runSetupReady = ($selectedCompleteTasks.Count -ge $MinimumTaskPairs)
$statuses.Add((New-SectionStatus `
    "Selected task setup" `
    $(if ($runSetupReady) { "READY" } else { "BLOCKED" }) `
    "selected_complete_tasks=$($selectedCompleteTasks.Count)/$MinimumTaskPairs" `
    $(if ($runSetupReady) { "Proceed with parser and Agent evidence checks." } else { "Complete selected scenario rows and agent-task-cases.csv." }))) | Out-Null

$parserReady = ($coveredParserCount -ge $MinimumParsers)
$statuses.Add((New-SectionStatus `
    "Parser scoring evidence" `
    $(if ($parserReady) { "READY" } else { "INCOMPLETE" }) `
    "complete_rows=$($completeParserRows.Count); parsers_covering_$MinimumDocuments`_docs=$coveredParserCount/$MinimumParsers" `
    $(if ($parserReady) { "Parser evidence is ready for evaluate-parser-results.ps1." } else { "Fill parser-evaluation-sheet.csv with real parser metrics." }))) | Out-Null

$promptReady = ($promptPairs.Count -ge $MinimumTaskPairs)
$statuses.Add((New-SectionStatus `
    "Prompt evidence" `
    $(if ($promptReady) { "READY" } else { "INCOMPLETE" }) `
    "prompt_pairs_with_files=$($promptPairs.Count)/$MinimumTaskPairs" `
    $(if ($promptReady) { "Prompt evidence is ready." } else { "Generate prompts and keep prompt files referenced by agent-prompt-manifest.csv." }))) | Out-Null

$runLogReady = ($runLogPairs.Count -ge $MinimumTaskPairs)
$statuses.Add((New-SectionStatus `
    "Run-log raw-output evidence" `
    $(if ($runLogReady) { "READY" } else { "INCOMPLETE" }) `
    "complete_run_log_pairs=$($runLogPairs.Count)/$MinimumTaskPairs" `
    $(if ($runLogReady) { "Raw output evidence is ready." } else { "Fill agent-run-log.csv and preserve non-empty raw Agent outputs." }))) | Out-Null

$resultReady = ($resultPairs.Count -ge $MinimumTaskPairs)
$statuses.Add((New-SectionStatus `
    "Result scoring evidence" `
    $(if ($resultReady) { "READY" } else { "INCOMPLETE" }) `
    "complete_result_pairs=$($resultPairs.Count)/$MinimumTaskPairs" `
    $(if ($resultReady) { "Result scoring evidence is ready." } else { "Fill baseline-vs-contextpack-results.csv with real scoring metrics." }))) | Out-Null

$traceabilityReady = ($traceablePairs.Count -ge $MinimumTaskPairs)
$statuses.Add((New-SectionStatus `
    "End-to-end traceability" `
    $(if ($traceabilityReady) { "READY" } else { "INCOMPLETE" }) `
    "traceable_scored_pairs=$($traceablePairs.Count)/$MinimumTaskPairs" `
    $(if ($traceabilityReady) { "Run evaluate-results.ps1 and check-goal-acceptance.ps1." } else { "Make selected tasks, prompts, run-log rows, raw outputs, and result rows agree on task_id/group." }))) | Out-Null

$blocked = @($statuses | Where-Object { $_.Status -eq "BLOCKED" })
$incomplete = @($statuses | Where-Object { $_.Status -eq "INCOMPLETE" })
$overall = if ($blocked.Count -gt 0) {
    "BLOCKED_ON_RUN_SETUP"
}
elseif ($incomplete.Count -gt 0) {
    "INCOMPLETE_EVIDENCE"
}
else {
    "READY_FOR_EVALUATION"
}

Write-Host "Agent Knowledge Hub run evidence readiness"
Write-Host "Experiment dir: $ExperimentDir"
Write-Host "Minimum task pairs: $MinimumTaskPairs"
Write-Host "Minimum documents per parser: $MinimumDocuments"
Write-Host "Minimum parsers: $MinimumParsers"
Write-Host ""
$statuses | Format-Table -AutoSize
Write-Host ""
Write-Host "Overall: $overall"

$incompleteRunLogRows = @($runLogReadinessRows | Where-Object { -not $_.IsComplete } | Select-Object -First 5)
if ($incompleteRunLogRows.Count -gt 0) {
    Write-Host ""
    Write-Host "Top incomplete run-log rows:"
    foreach ($row in $incompleteRunLogRows) {
        Write-Host ("- {0}/{1}: {2}" -f $row.TaskId, $row.Group, ($row.MissingFields -join ","))
    }
}

$incompleteResultRows = @($resultReadinessRows | Where-Object { -not $_.IsComplete } | Select-Object -First 5)
if ($incompleteResultRows.Count -gt 0) {
    Write-Host ""
    Write-Host "Top incomplete result rows:"
    foreach ($row in $incompleteResultRows) {
        Write-Host ("- {0}/{1}: {2}" -f $row.TaskId, $row.Group, ($row.MissingFields -join ","))
    }
}

$incompleteParserRows = @($parserReadinessRows | Where-Object { -not $_.IsComplete } | Select-Object -First 5)
if ($incompleteParserRows.Count -gt 0) {
    Write-Host ""
    Write-Host "Top incomplete parser rows:"
    foreach ($row in $incompleteParserRows) {
        Write-Host ("- {0}/{1}: {2}" -f $row.DocumentId, $row.Parser, ($row.MissingFields -join ","))
    }
}

if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
    $report = @()
    $report += "# Run Evidence Readiness"
    $report += ""
    $report += "- Overall: $overall"
    $report += ('- Experiment dir: `{0}`' -f $ExperimentDir)
    $report += "- Traceable scored pairs: $($traceablePairs.Count)/$MinimumTaskPairs"
    $report += "- Complete parser rows: $($completeParserRows.Count)"
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

if ($Strict -and $overall -ne "READY_FOR_EVALUATION") {
    exit 1
}

exit 0
