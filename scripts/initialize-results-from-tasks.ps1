param(
    [string]$RunId,
    [string]$ExperimentDir,
    [string]$ResultsPath,
    [switch]$Apply,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

if (-not [string]::IsNullOrWhiteSpace($RunId)) {
    if ($RunId -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]*$") {
        Write-Error "Invalid RunId. Use only letters, numbers, dot, underscore, and hyphen."
    }

    $ExperimentDir = Join-Path (Join-Path $ProjectRoot "experiments\runs") $RunId
}
elseif ([string]::IsNullOrWhiteSpace($ExperimentDir)) {
    $ExperimentDir = Join-Path $ProjectRoot "experiments\templates"
}
elseif (-not [System.IO.Path]::IsPathRooted($ExperimentDir)) {
    $ExperimentDir = Join-Path $ProjectRoot $ExperimentDir
}

if ([string]::IsNullOrWhiteSpace($ResultsPath)) {
    $ResultsPath = Join-Path $ExperimentDir "baseline-vs-contextpack-results.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($ResultsPath)) {
    $ResultsPath = Join-Path $ProjectRoot $ResultsPath
}

$taskCasesPath = Join-Path $ExperimentDir "agent-task-cases.csv"
$scenarioPath = Join-Path $ExperimentDir "scenario-selection-matrix.csv"

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
    "N/A"
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

function Test-ResultsHaveEnteredData {
    param([object[]]$Rows)

    foreach ($row in $Rows) {
        foreach ($field in @(
            "answer_correct",
            "missed_constraints",
            "wrong_claims",
            "citation_correct",
            "token_cost",
            "elapsed_minutes",
            "human_fix_count"
        )) {
            if (-not (Test-Placeholder $row.$field)) {
                return $true
            }
        }
    }

    return $false
}

if (-not (Test-Path -LiteralPath $taskCasesPath -PathType Leaf)) {
    Write-Error "Missing task cases file: $taskCasesPath"
}
if (-not (Test-Path -LiteralPath $scenarioPath -PathType Leaf)) {
    Write-Error "Missing scenario selection file: $scenarioPath"
}

$taskCaseRows = @(Import-Csv -LiteralPath $taskCasesPath -Encoding UTF8)
$scenarioRows = @(Import-Csv -LiteralPath $scenarioPath -Encoding UTF8)

Assert-RequiredColumns $taskCaseRows @(
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
) "Agent task cases"

Assert-RequiredColumns $scenarioRows @(
    "task_id",
    "task_type",
    "real_source",
    "monthly_frequency",
    "has_gold_answer",
    "needs_evidence",
    "owner",
    "selected",
    "notes"
) "Scenario selection matrix"

$completeTaskCasesById = @{}
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
        $completeTaskCasesById[$row.task_id] = $row
    }
}

$selectedScenarioRows = @($scenarioRows | Where-Object { Test-Affirmative $_.selected })
if ($selectedScenarioRows.Count -eq 0) {
    Write-Error "No selected tasks found in scenario-selection-matrix.csv."
}

$selectedTasks = New-Object System.Collections.Generic.List[object]
$badSelectedTasks = New-Object System.Collections.Generic.List[string]
foreach ($row in $selectedScenarioRows) {
    $missing = Get-MissingFields $row @("task_id", "task_type", "real_source", "monthly_frequency", "owner")
    if (-not (Test-Affirmative $row.has_gold_answer)) {
        $missing.Add("has_gold_answer") | Out-Null
    }
    if (-not (Test-Affirmative $row.needs_evidence)) {
        $missing.Add("needs_evidence") | Out-Null
    }
    if (-not $completeTaskCasesById.ContainsKey($row.task_id)) {
        $missing.Add("complete_task_case") | Out-Null
    }

    if ($missing.Count -eq 0) {
        $selectedTasks.Add($completeTaskCasesById[$row.task_id]) | Out-Null
    }
    else {
        $taskId = if (Test-Placeholder $row.task_id) { "<missing-task-id>" } else { $row.task_id }
        $badSelectedTasks.Add(("{0}: {1}" -f $taskId, ($missing -join ","))) | Out-Null
    }
}

if ($badSelectedTasks.Count -gt 0) {
    Write-Error "Selected tasks are not ready for result initialization: $($badSelectedTasks -join '; ')"
}

if ($selectedTasks.Count -lt 3) {
    Write-Error "Expected at least 3 selected complete tasks, found $($selectedTasks.Count)."
}

$resultColumns = @(
    "task_id",
    "group",
    "agent",
    "source_docs",
    "answer_correct",
    "missed_constraints",
    "wrong_claims",
    "citation_correct",
    "token_cost",
    "elapsed_minutes",
    "human_fix_count",
    "context_pack_tokens",
    "retrieved_span_count",
    "useful_span_count",
    "irrelevant_span_count",
    "retrieval_failure",
    "notes"
)

if ((Test-Path -LiteralPath $ResultsPath -PathType Leaf) -and -not $Force) {
    $existingRows = @(Import-Csv -LiteralPath $ResultsPath -Encoding UTF8)
    if ($existingRows.Count -gt 0) {
        Assert-RequiredColumns $existingRows $resultColumns "Existing baseline/context_pack results"
        if (Test-ResultsHaveEnteredData $existingRows) {
            Write-Error "Refusing to overwrite results with entered metrics without -Force: $ResultsPath"
        }
    }
}

$resultRows = @()
foreach ($task in $selectedTasks) {
    $resultRows += [pscustomobject]@{
        task_id = $task.task_id
        group = "baseline"
        agent = "TBD"
        source_docs = $task.allowed_documents
        answer_correct = "TBD"
        missed_constraints = "TBD"
        wrong_claims = "TBD"
        citation_correct = "TBD"
        token_cost = "TBD"
        elapsed_minutes = "TBD"
        human_fix_count = "TBD"
        context_pack_tokens = "N/A"
        retrieved_span_count = "N/A"
        useful_span_count = "N/A"
        irrelevant_span_count = "N/A"
        retrieval_failure = "N/A"
        notes = "initialized from selected task"
    }
    $resultRows += [pscustomobject]@{
        task_id = $task.task_id
        group = "context_pack"
        agent = "TBD"
        source_docs = "context_pack"
        answer_correct = "TBD"
        missed_constraints = "TBD"
        wrong_claims = "TBD"
        citation_correct = "TBD"
        token_cost = "TBD"
        elapsed_minutes = "TBD"
        human_fix_count = "TBD"
        context_pack_tokens = "TBD"
        retrieved_span_count = "TBD"
        useful_span_count = "TBD"
        irrelevant_span_count = "TBD"
        retrieval_failure = "TBD"
        notes = "initialized from selected task"
    }
}

Write-Host "Agent Knowledge Hub result sheet initialization"
Write-Host "Experiment dir: $ExperimentDir"
Write-Host "Task cases: $taskCasesPath"
Write-Host "Scenario selection: $scenarioPath"
Write-Host "Results path: $ResultsPath"
Write-Host "Mode: $(if ($Apply) { 'apply' } else { 'dry run' })"
Write-Host ""
Write-Host "Selected complete tasks: $($selectedTasks.Count)"
Write-Host "Rows to write: $($resultRows.Count)"

if (-not $Apply) {
    Write-Host ""
    Write-Host "Dry run only. Use -Apply to write baseline/context_pack placeholder rows."
    Write-Host "RESULT_SHEET_INIT_DRY_RUN=PASS"
    exit 0
}

$resultsParent = Split-Path -Parent $ResultsPath
if (-not [string]::IsNullOrWhiteSpace($resultsParent) -and -not (Test-Path -LiteralPath $resultsParent)) {
    New-Item -ItemType Directory -Path $resultsParent -Force | Out-Null
}

if (Test-Path -LiteralPath $ResultsPath -PathType Leaf) {
    $backupPath = Join-Path $resultsParent ("baseline-vs-contextpack-results.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".csv")
    Copy-Item -LiteralPath $ResultsPath -Destination $backupPath
    Write-Host "Backup written: $backupPath"
}

$resultRows |
    Select-Object $resultColumns |
    Export-Csv -LiteralPath $ResultsPath -NoTypeInformation -Encoding UTF8

Write-Host "Results initialized: $ResultsPath"
Write-Host "RESULT_SHEET_INIT_APPLY=PASS"

exit 0
