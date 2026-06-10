param(
    [string]$RunId,
    [string]$ExperimentDir,
    [string]$PromptDir,
    [string]$PromptManifestPath,
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

if ([string]::IsNullOrWhiteSpace($PromptDir)) {
    $PromptDir = Join-Path $ExperimentDir "prompts"
}
elseif (-not [System.IO.Path]::IsPathRooted($PromptDir)) {
    $PromptDir = Join-Path $ExperimentDir $PromptDir
}

if ([string]::IsNullOrWhiteSpace($PromptManifestPath)) {
    $PromptManifestPath = Join-Path $ExperimentDir "agent-prompt-manifest.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($PromptManifestPath)) {
    $PromptManifestPath = Join-Path $ExperimentDir $PromptManifestPath
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

function ConvertTo-SafeFileStem {
    param(
        [string]$Value,
        [string]$Fallback
    )

    $source = if (Test-Placeholder $Value) { $Fallback } else { $Value.Trim() }
    foreach ($char in [System.IO.Path]::GetInvalidFileNameChars()) {
        $source = $source.Replace([string]$char, "-")
    }

    $source = [regex]::Replace($source, "\s+", "-")
    $source = [regex]::Replace($source, "-+", "-").Trim(".-")
    if ([string]::IsNullOrWhiteSpace($source)) {
        return $Fallback
    }

    return $source
}

function Get-RelativeExperimentPath {
    param([string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $rootPath = [System.IO.Path]::GetFullPath($ExperimentDir)
    $prefix = $rootPath.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar

    if ($fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $fullPath.Substring($prefix.Length)
    }

    return $fullPath
}

function New-AgentPrompt {
    param(
        [object]$Task,
        [ValidateSet("baseline", "context_pack")]
        [string]$Group
    )

    $contextInstruction = if ($Group -eq "baseline") {
        @(
            "Use only the original document files provided for this task.",
            "Do not use a Context Pack.",
            "If an allowed document is unavailable, state that the context is insufficient instead of guessing."
        )
    }
    else {
        @(
            "Use only the Context Pack provided for this task.",
            "Do not inspect original files unless their content is included in the Context Pack.",
            "If the Context Pack lacks evidence, state that the context is insufficient instead of guessing."
        )
    }

    $lines = @(
        "# Agent Experiment Prompt",
        "",
        "## Experiment Metadata",
        "",
        "- task_id: $($Task.task_id)",
        "- group: $Group",
        "- task_type: $($Task.task_type)",
        "- domain: $($Task.domain)",
        "- context_source: $(if ($Group -eq 'baseline') { 'raw_files' } else { 'context_pack' })",
        "",
        "## Context Rule",
        ""
    )

    foreach ($line in $contextInstruction) {
        $lines += "- $line"
    }

    $lines += @(
        "",
        "## Task",
        "",
        $Task.task_description,
        "",
        "## Allowed Documents",
        "",
        $Task.allowed_documents,
        "",
        "## Required Output",
        "",
        "Return the answer in this exact structure:",
        "",
        '```text',
        "## Answer",
        "",
        "## Evidence",
        "| Claim | Source document | Version/scope | Page/section/span | Support |",
        "|---|---|---|---|---|",
        "",
        "## Gaps Or Assumptions",
        "",
        "## Follow-up Needed",
        '```',
        "",
        "## Execution Rules",
        "",
        "- Cite document name, version/scope, and page/section/span when available.",
        "- Separate confirmed facts from assumptions.",
        "- Do not invent evidence.",
        "- Keep the answer focused on the task.",
        "- Do not use scorer-only fields such as gold answers, required constraints, or expected evidence locations."
    )

    return $lines
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
    Write-Error "Selected tasks are not ready for prompt initialization: $($badSelectedTasks -join '; ')"
}

if ($selectedTasks.Count -lt 3) {
    Write-Error "Expected at least 3 selected complete tasks, found $($selectedTasks.Count)."
}

$promptPlans = @()
foreach ($task in $selectedTasks) {
    $safeTaskId = ConvertTo-SafeFileStem $task.task_id "task"
    foreach ($group in @("baseline", "context_pack")) {
        $promptPath = Join-Path (Join-Path $PromptDir $group) "$safeTaskId.md"
        $relativePromptPath = Get-RelativeExperimentPath $promptPath
        $promptPlans += [pscustomobject]@{
            task_id = $task.task_id
            group = $group
            prompt_path = $relativePromptPath
            context_source = $(if ($group -eq "baseline") { "raw_files" } else { "context_pack" })
            source_docs = $(if ($group -eq "baseline") { $task.allowed_documents } else { "context_pack" })
            notes = "initialized from selected task"
            full_path = $promptPath
            task = $task
        }
    }
}

Write-Host "Agent Knowledge Hub prompt initialization"
Write-Host "Experiment dir: $ExperimentDir"
Write-Host "Task cases: $taskCasesPath"
Write-Host "Scenario selection: $scenarioPath"
Write-Host "Prompt dir: $PromptDir"
Write-Host "Prompt manifest: $PromptManifestPath"
Write-Host "Mode: $(if ($Apply) { 'apply' } else { 'dry run' })"
Write-Host ""
Write-Host "Selected complete tasks: $($selectedTasks.Count)"
Write-Host "Prompts to write: $($promptPlans.Count)"

if (-not $Apply) {
    Write-Host ""
    Write-Host "Dry run only. Use -Apply to write baseline/context_pack prompt files."
    Write-Host "AGENT_PROMPT_INIT_DRY_RUN=PASS"
    exit 0
}

foreach ($plan in $promptPlans) {
    if ((Test-Path -LiteralPath $plan.full_path -PathType Leaf) -and -not $Force) {
        Write-Error "Refusing to overwrite prompt without -Force: $($plan.full_path)"
    }
}

if ((Test-Path -LiteralPath $PromptManifestPath -PathType Leaf) -and -not $Force) {
    $existingManifestRows = @(Import-Csv -LiteralPath $PromptManifestPath -Encoding UTF8)
    $hasEnteredManifest = @($existingManifestRows | Where-Object { -not (Test-Placeholder $_.prompt_path) }).Count -gt 0
    if ($hasEnteredManifest) {
        Write-Error "Refusing to overwrite prompt manifest without -Force: $PromptManifestPath"
    }
}

foreach ($plan in $promptPlans) {
    $parent = Split-Path -Parent $plan.full_path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $prompt = New-AgentPrompt -Task $plan.task -Group $plan.group
    Set-Content -LiteralPath $plan.full_path -Value $prompt -Encoding UTF8
}

$manifestParent = Split-Path -Parent $PromptManifestPath
if (-not [string]::IsNullOrWhiteSpace($manifestParent) -and -not (Test-Path -LiteralPath $manifestParent)) {
    New-Item -ItemType Directory -Path $manifestParent -Force | Out-Null
}

$promptPlans |
    Select-Object task_id, group, prompt_path, context_source, source_docs, notes |
    Export-Csv -LiteralPath $PromptManifestPath -NoTypeInformation -Encoding UTF8

Write-Host "Prompts initialized: $PromptDir"
Write-Host "Prompt manifest written: $PromptManifestPath"
Write-Host "AGENT_PROMPT_INIT_APPLY=PASS"

exit 0
