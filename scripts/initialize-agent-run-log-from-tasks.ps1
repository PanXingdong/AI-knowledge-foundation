param(
    [string]$RunId,
    [string]$ExperimentDir,
    [string]$RunLogPath,
    [string]$RawOutputDir,
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

$EffectiveRunId = if (-not [string]::IsNullOrWhiteSpace($RunId)) {
    $RunId
}
else {
    Split-Path -Leaf ([System.IO.Path]::GetFullPath($ExperimentDir))
}

if ([string]::IsNullOrWhiteSpace($EffectiveRunId)) {
    $EffectiveRunId = "run"
}

if ([string]::IsNullOrWhiteSpace($RunLogPath)) {
    $RunLogPath = Join-Path $ExperimentDir "agent-run-log.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($RunLogPath)) {
    $RunLogPath = Join-Path $ExperimentDir $RunLogPath
}

if ([string]::IsNullOrWhiteSpace($RawOutputDir)) {
    $RawOutputDir = Join-Path $ExperimentDir "raw-outputs"
}
elseif (-not [System.IO.Path]::IsPathRooted($RawOutputDir)) {
    $RawOutputDir = Join-Path $ExperimentDir $RawOutputDir
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

function Resolve-ExperimentPath {
    param([string]$Path)

    if (Test-Placeholder $Path) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return $Path
    }

    return Join-Path $ExperimentDir $Path
}

function Test-RunLogHasEnteredExecutionData {
    param([object[]]$Rows)

    foreach ($row in $Rows) {
        foreach ($field in @(
            "agent",
            "model",
            "started_at",
            "ended_at",
            "token_input",
            "token_output",
            "elapsed_minutes"
        )) {
            if (-not (Test-Placeholder $row.$field)) {
                return $true
            }
        }

        if (-not (Test-Placeholder $row.score_status)) {
            $status = $row.score_status.Trim().ToLowerInvariant()
            if ($status -ne "pending") {
                return $true
            }
        }

        if (-not (Test-Placeholder $row.raw_output_path)) {
            $rawOutputPath = Resolve-ExperimentPath $row.raw_output_path
            if ($null -ne $rawOutputPath -and (Test-Path -LiteralPath $rawOutputPath -PathType Leaf)) {
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
if (-not (Test-Path -LiteralPath $PromptManifestPath -PathType Leaf)) {
    Write-Error "Missing prompt manifest file. Run initialize-agent-prompts-from-tasks.ps1 first: $PromptManifestPath"
}

$taskCaseRows = @(Import-Csv -LiteralPath $taskCasesPath -Encoding UTF8)
$scenarioRows = @(Import-Csv -LiteralPath $scenarioPath -Encoding UTF8)
$promptManifestRows = @(Import-Csv -LiteralPath $PromptManifestPath -Encoding UTF8)

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

Assert-RequiredColumns $promptManifestRows @(
    "task_id",
    "group",
    "prompt_path",
    "context_source",
    "source_docs",
    "notes"
) "Agent prompt manifest"

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
    Write-Error "Selected tasks are not ready for run-log initialization: $($badSelectedTasks -join '; ')"
}

if ($selectedTasks.Count -lt 3) {
    Write-Error "Expected at least 3 selected complete tasks, found $($selectedTasks.Count)."
}

$promptRowsByKey = @{}
$duplicatePromptKeys = New-Object System.Collections.Generic.List[string]
foreach ($row in $promptManifestRows) {
    if ((Test-Placeholder $row.task_id) -or (Test-Placeholder $row.group)) {
        continue
    }

    $key = ("{0}|{1}" -f $row.task_id, $row.group).ToLowerInvariant()
    if ($promptRowsByKey.ContainsKey($key)) {
        $duplicatePromptKeys.Add($key) | Out-Null
        continue
    }

    $promptRowsByKey[$key] = $row
}

if ($duplicatePromptKeys.Count -gt 0) {
    Write-Error "Duplicate prompt manifest rows found: $($duplicatePromptKeys -join ', ')"
}

$runLogColumns = @(
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

if ((Test-Path -LiteralPath $RunLogPath -PathType Leaf) -and -not $Force) {
    $existingRows = @(Import-Csv -LiteralPath $RunLogPath -Encoding UTF8)
    if ($existingRows.Count -gt 0) {
        Assert-RequiredColumns $existingRows $runLogColumns "Existing agent run log"
        if (Test-RunLogHasEnteredExecutionData $existingRows) {
            Write-Error "Refusing to overwrite agent run log with entered execution data without -Force: $RunLogPath"
        }
    }
}

$runLogRows = @()
$missingPromptRows = New-Object System.Collections.Generic.List[string]
foreach ($task in $selectedTasks) {
    $safeTaskId = ConvertTo-SafeFileStem $task.task_id "task"
    foreach ($group in @("baseline", "context_pack")) {
        $promptKey = ("{0}|{1}" -f $task.task_id, $group).ToLowerInvariant()
        if (-not $promptRowsByKey.ContainsKey($promptKey)) {
            $missingPromptRows.Add($promptKey) | Out-Null
            continue
        }

        $prompt = $promptRowsByKey[$promptKey]
        $missingPromptFields = Get-MissingFields $prompt @("prompt_path", "context_source", "source_docs")
        if ($missingPromptFields.Count -gt 0) {
            $missingPromptRows.Add(("{0}: {1}" -f $promptKey, ($missingPromptFields -join ","))) | Out-Null
            continue
        }

        $rawOutputPath = Join-Path $RawOutputDir ("{0}-{1}.md" -f $safeTaskId, $group)
        $runLogRows += [pscustomobject]@{
            run_id = $EffectiveRunId
            task_id = $task.task_id
            group = $group
            attempt = "1"
            agent = "TBD"
            model = "TBD"
            context_source = $prompt.context_source
            source_docs = $prompt.source_docs
            context_pack_id = $(if ($group -eq "baseline") { "N/A" } else { "pending" })
            prompt_path = $prompt.prompt_path
            started_at = "TBD"
            ended_at = "TBD"
            token_input = "TBD"
            token_output = "TBD"
            elapsed_minutes = "TBD"
            raw_output_path = Get-RelativeExperimentPath $rawOutputPath
            scorer = $task.scorer
            score_status = "pending"
            notes = "initialized from selected task; fill after real Agent execution"
        }
    }
}

if ($missingPromptRows.Count -gt 0) {
    Write-Error "Prompt manifest is missing selected task/group rows: $($missingPromptRows -join '; ')"
}

Write-Host "Agent Knowledge Hub run-log initialization"
Write-Host "Experiment dir: $ExperimentDir"
Write-Host "Run id: $EffectiveRunId"
Write-Host "Task cases: $taskCasesPath"
Write-Host "Scenario selection: $scenarioPath"
Write-Host "Prompt manifest: $PromptManifestPath"
Write-Host "Run log path: $RunLogPath"
Write-Host "Raw output dir: $RawOutputDir"
Write-Host "Mode: $(if ($Apply) { 'apply' } else { 'dry run' })"
Write-Host ""
Write-Host "Selected complete tasks: $($selectedTasks.Count)"
Write-Host "Run-log rows to write: $($runLogRows.Count)"

if (-not $Apply) {
    Write-Host ""
    Write-Host "Dry run only. Use -Apply to write baseline/context_pack pending run-log rows."
    Write-Host "AGENT_RUN_LOG_INIT_DRY_RUN=PASS"
    exit 0
}

$runLogParent = Split-Path -Parent $RunLogPath
if (-not [string]::IsNullOrWhiteSpace($runLogParent) -and -not (Test-Path -LiteralPath $runLogParent)) {
    New-Item -ItemType Directory -Path $runLogParent -Force | Out-Null
}

if (-not (Test-Path -LiteralPath $RawOutputDir)) {
    New-Item -ItemType Directory -Path $RawOutputDir -Force | Out-Null
}

if (Test-Path -LiteralPath $RunLogPath -PathType Leaf) {
    $backupPath = Join-Path $runLogParent ("agent-run-log.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".csv")
    Copy-Item -LiteralPath $RunLogPath -Destination $backupPath
    Write-Host "Backup written: $backupPath"
}

$runLogRows |
    Select-Object $runLogColumns |
    Export-Csv -LiteralPath $RunLogPath -NoTypeInformation -Encoding UTF8

Write-Host "Run log initialized: $RunLogPath"
Write-Host "Raw output directory ready: $RawOutputDir"
Write-Host "AGENT_RUN_LOG_INIT_APPLY=PASS"

exit 0
