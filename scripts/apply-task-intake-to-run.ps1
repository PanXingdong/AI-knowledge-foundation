param(
    [string]$RunId,
    [string]$ExperimentDir,
    [string]$TaskIntakePath,
    [int]$MinimumTasks = 3,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($TaskIntakePath)) {
    $TaskIntakePath = Join-Path $ProjectRoot "experiments\templates\task-intake-template.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($TaskIntakePath)) {
    $TaskIntakePath = Join-Path $ProjectRoot $TaskIntakePath
}

if (-not [string]::IsNullOrWhiteSpace($RunId)) {
    if ($RunId -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]*$") {
        Write-Error "Invalid RunId. Use only letters, numbers, dot, underscore, and hyphen."
    }

    $ExperimentDir = Join-Path (Join-Path $ProjectRoot "experiments\runs") $RunId
}
elseif ([string]::IsNullOrWhiteSpace($ExperimentDir)) {
    Write-Error "Provide -RunId or -ExperimentDir."
}
elseif (-not [System.IO.Path]::IsPathRooted($ExperimentDir)) {
    $ExperimentDir = Join-Path $ProjectRoot $ExperimentDir
}

if (-not (Test-Path -LiteralPath $ExperimentDir)) {
    Write-Error "Experiment directory does not exist. Create it first with new-experiment-run.ps1: $ExperimentDir"
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

function Test-SafeToOverwrite {
    param([string]$Path)

    if ($Force -or -not (Test-Path -LiteralPath $Path)) {
        return $true
    }

    $content = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    foreach ($term in $PlaceholderTerms) {
        if ($content -like "*$term*") {
            return $true
        }
    }

    return $false
}

function ConvertTo-MarkdownCell {
    param([string]$Value)

    if ($null -eq $Value) {
        return ""
    }

    $singleLine = $Value -replace "\r?\n", "<br>"
    $escapedPipes = $singleLine -replace "\|", "/"
    return $escapedPipes.Trim()
}

if (-not (Test-Path -LiteralPath $TaskIntakePath)) {
    Write-Error "Task intake file not found: $TaskIntakePath"
}

$rows = @(Import-Csv -LiteralPath $TaskIntakePath -Encoding UTF8)
if ($rows.Count -eq 0) {
    Write-Error "Task intake file has no rows: $TaskIntakePath"
}

$requiredColumns = @(
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

$columns = @($rows[0].PSObject.Properties.Name)
$missingColumns = @($requiredColumns | Where-Object { $_ -notin $columns })
if ($missingColumns.Count -gt 0) {
    Write-Error "Task intake file is missing columns: $($missingColumns -join ', ')"
}

$readyRows = New-Object System.Collections.Generic.List[object]
$incompleteSelectedRows = New-Object System.Collections.Generic.List[string]

foreach ($row in $rows) {
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
        $readyRows.Add($row) | Out-Null
    }
    else {
        $candidateId = if (Test-Placeholder $row.candidate_id) { "<missing-candidate-id>" } else { $row.candidate_id }
        $incompleteSelectedRows.Add(("{0}: {1}" -f $candidateId, ($missing -join ","))) | Out-Null
    }
}

if ($incompleteSelectedRows.Count -gt 0) {
    Write-Error "Selected task candidates are incomplete: $($incompleteSelectedRows -join '; ')"
}

if ($readyRows.Count -lt $MinimumTasks) {
    Write-Error "Expected at least $MinimumTasks ready selected task candidates, found $($readyRows.Count)."
}

$duplicateIds = @(
    $readyRows |
        Group-Object candidate_id |
        Where-Object { $_.Count -gt 1 } |
        ForEach-Object { $_.Name }
)
if ($duplicateIds.Count -gt 0) {
    Write-Error "Duplicate candidate_id values among selected tasks: $($duplicateIds -join ', ')"
}

$taskCasesPath = Join-Path $ExperimentDir "agent-task-cases.csv"
$scenarioPath = Join-Path $ExperimentDir "scenario-selection-matrix.csv"
$taskCardsPath = Join-Path $ExperimentDir "agent-task-cards.md"

foreach ($target in @($taskCasesPath, $scenarioPath, $taskCardsPath)) {
    if (-not (Test-SafeToOverwrite $target)) {
        Write-Error "Refusing to overwrite non-placeholder file without -Force: $target"
    }
}

$taskCaseRows = @(
    foreach ($row in $readyRows) {
        [pscustomobject]@{
            task_id = $row.candidate_id
            task_type = $row.task_type
            domain = $row.domain
            task_description = $row.task_description
            allowed_documents = $row.allowed_documents
            gold_answer_points = $row.gold_answer_points
            required_constraints = $row.required_constraints
            expected_evidence = $row.expected_evidence
            scorer = $row.scorer
            owner = $row.owner
            status = "ready"
            notes = $row.notes
        }
    }
)

$scenarioRows = @(
    foreach ($row in $readyRows) {
        [pscustomobject]@{
            task_id = $row.candidate_id
            task_type = $row.task_type
            real_source = $row.real_source
            monthly_frequency = $row.monthly_frequency
            has_gold_answer = "yes"
            needs_evidence = "yes"
            owner = $row.owner
            selected = "yes"
            notes = $row.notes
        }
    }
)

$taskCards = @(
    "# Agent Task Cards",
    "",
    "Each task must be executed twice with the same task intent:",
    "",
    '```text',
    "baseline: Agent reads the original files directly.",
    "context_pack: Agent uses the generated Context Pack.",
    '```',
    ""
)

$index = 1
foreach ($row in $readyRows) {
    $candidateId = ConvertTo-MarkdownCell $row.candidate_id
    $taskType = ConvertTo-MarkdownCell $row.task_type
    $domain = ConvertTo-MarkdownCell $row.domain
    $realSource = ConvertTo-MarkdownCell $row.real_source
    $monthlyFrequency = ConvertTo-MarkdownCell $row.monthly_frequency
    $taskDescription = ConvertTo-MarkdownCell $row.task_description
    $allowedDocuments = ConvertTo-MarkdownCell $row.allowed_documents
    $goldAnswerPoints = ConvertTo-MarkdownCell $row.gold_answer_points
    $requiredConstraints = ConvertTo-MarkdownCell $row.required_constraints
    $expectedEvidence = ConvertTo-MarkdownCell $row.expected_evidence
    $scorer = ConvertTo-MarkdownCell $row.scorer
    $owner = ConvertTo-MarkdownCell $row.owner
    $notes = ConvertTo-MarkdownCell $row.notes

    $heading = "## Task {0}: {1}" -f $index, $taskType
    $taskCards += $heading
    $taskCards += ""
    $taskCards += "| Field | Value |"
    $taskCards += "|---|---|"
    $taskCards += "| task_id | $candidateId |"
    $taskCards += "| task_type | $taskType |"
    $taskCards += "| domain | $domain |"
    $taskCards += "| real_source | $realSource |"
    $taskCards += "| monthly_frequency | $monthlyFrequency |"
    $taskCards += "| task_description | $taskDescription |"
    $taskCards += "| allowed_documents | $allowedDocuments |"
    $taskCards += "| gold_answer_points | $goldAnswerPoints |"
    $taskCards += "| required_constraints | $requiredConstraints |"
    $taskCards += "| expected_evidence | $expectedEvidence |"
    $taskCards += "| scorer | $scorer |"
    $taskCards += "| owner | $owner |"
    $taskCards += "| notes | $notes |"
    $taskCards += ""
    $index++
}

$taskCaseRows | Export-Csv -LiteralPath $taskCasesPath -NoTypeInformation -Encoding UTF8
$scenarioRows | Export-Csv -LiteralPath $scenarioPath -NoTypeInformation -Encoding UTF8
Set-Content -LiteralPath $taskCardsPath -Value $taskCards -Encoding UTF8

Write-Host "Applied selected task intake to run: $ExperimentDir"
Write-Host "Generated: $taskCasesPath"
Write-Host "Generated: $scenarioPath"
Write-Host "Generated: $taskCardsPath"
Write-Host "Ready selected tasks: $($readyRows.Count)"
