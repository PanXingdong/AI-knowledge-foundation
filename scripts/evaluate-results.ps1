param(
    [string]$ResultsPath,
    [string]$ReportPath,
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ResultsPath)) {
    $ResultsPath = Join-Path $ProjectRoot "experiments\templates\baseline-vs-contextpack-results.csv"
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
    "TBD",
    "TODO",
    "N/A"
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

function Convert-RowMetrics {
    param([pscustomobject]$Row)

    $answerCorrect = Convert-ToBoolMetric $Row.answer_correct
    $citationCorrect = Convert-ToBoolMetric $Row.citation_correct
    $missedConstraints = Convert-ToNumberMetric $Row.missed_constraints
    $wrongClaims = Convert-ToNumberMetric $Row.wrong_claims
    $tokenCost = Convert-ToNumberMetric $Row.token_cost
    $elapsedMinutes = Convert-ToNumberMetric $Row.elapsed_minutes
    $humanFixCount = Convert-ToNumberMetric $Row.human_fix_count

    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($pair in @(
        @{ Name = "answer_correct"; Value = $answerCorrect },
        @{ Name = "citation_correct"; Value = $citationCorrect },
        @{ Name = "missed_constraints"; Value = $missedConstraints },
        @{ Name = "wrong_claims"; Value = $wrongClaims },
        @{ Name = "token_cost"; Value = $tokenCost },
        @{ Name = "elapsed_minutes"; Value = $elapsedMinutes },
        @{ Name = "human_fix_count"; Value = $humanFixCount }
    )) {
        if ($null -eq $pair.Value) {
            $missing.Add($pair.Name) | Out-Null
        }
    }

    return [pscustomobject]@{
        TaskId = $Row.task_id
        Group = $Row.group
        AnswerCorrect = $answerCorrect
        CitationCorrect = $citationCorrect
        MissedConstraints = $missedConstraints
        WrongClaims = $wrongClaims
        TokenCost = $tokenCost
        ElapsedMinutes = $elapsedMinutes
        HumanFixCount = $humanFixCount
        MissingFields = @($missing)
        IsComplete = ($missing.Count -eq 0)
    }
}

function New-Stats {
    param([object[]]$Rows)

    if ($Rows.Count -eq 0) {
        return [pscustomobject]@{
            Count = 0
            AnswerAccuracy = $null
            CitationAccuracy = $null
            AvgMissedConstraints = $null
            AvgTokenCost = $null
            AvgElapsedMinutes = $null
            AvgHumanFixCount = $null
        }
    }

    return [pscustomobject]@{
        Count = $Rows.Count
        AnswerAccuracy = (@($Rows | Where-Object { $_.AnswerCorrect }).Count / $Rows.Count)
        CitationAccuracy = (@($Rows | Where-Object { $_.CitationCorrect }).Count / $Rows.Count)
        AvgMissedConstraints = (($Rows | Measure-Object -Property MissedConstraints -Average).Average)
        AvgTokenCost = (($Rows | Measure-Object -Property TokenCost -Average).Average)
        AvgElapsedMinutes = (($Rows | Measure-Object -Property ElapsedMinutes -Average).Average)
        AvgHumanFixCount = (($Rows | Measure-Object -Property HumanFixCount -Average).Average)
    }
}

function Get-Reduction {
    param(
        $Baseline,
        $Experiment
    )

    if ($null -eq $Baseline -or $null -eq $Experiment -or $Baseline -le 0) {
        return $null
    }

    return ($Baseline - $Experiment) / $Baseline
}

function Format-Percent {
    param($Value)

    if ($null -eq $Value) {
        return "N/A"
    }

    return ("{0:P1}" -f $Value)
}

if (-not (Test-Path -LiteralPath $ResultsPath)) {
    Write-Error "Results file not found: $ResultsPath"
}

$rows = @(Import-Csv -LiteralPath $ResultsPath -Encoding UTF8)
$requiredColumns = @(
    "task_id",
    "group",
    "answer_correct",
    "missed_constraints",
    "wrong_claims",
    "citation_correct",
    "token_cost",
    "elapsed_minutes",
    "human_fix_count"
)

if ($rows.Count -eq 0) {
    Write-Error "Results file has no rows: $ResultsPath"
}

$columns = @($rows[0].PSObject.Properties.Name)
$missingColumns = @($requiredColumns | Where-Object { $_ -notin $columns })
if ($missingColumns.Count -gt 0) {
    Write-Error "Missing required columns: $($missingColumns -join ', ')"
}

$metrics = @($rows | ForEach-Object { Convert-RowMetrics $_ })
$incompleteRows = @($metrics | Where-Object { -not $_.IsComplete })

$completeTaskPairs = New-Object System.Collections.Generic.List[object]
$taskGroups = $metrics | Group-Object -Property TaskId
foreach ($taskGroup in $taskGroups) {
    $baseline = @($taskGroup.Group | Where-Object { $_.Group -eq "baseline" -and $_.IsComplete })
    $contextPack = @($taskGroup.Group | Where-Object { $_.Group -eq "context_pack" -and $_.IsComplete })
    if ($baseline.Count -ge 1 -and $contextPack.Count -ge 1) {
        $completeTaskPairs.Add([pscustomobject]@{
            TaskId = $taskGroup.Name
            Baseline = $baseline[0]
            ContextPack = $contextPack[0]
        }) | Out-Null
    }
}

$baselineRows = @($completeTaskPairs | ForEach-Object { $_.Baseline })
$contextRows = @($completeTaskPairs | ForEach-Object { $_.ContextPack })

Write-Host "Agent Knowledge Hub result evaluation"
Write-Host "Results file: $ResultsPath"
Write-Host "Complete paired tasks: $($completeTaskPairs.Count)"
Write-Host ""

if ($incompleteRows.Count -gt 0) {
    Write-Host "Incomplete rows:"
    $incompleteRows |
        Select-Object TaskId, Group, @{ Name = "MissingFields"; Expression = { $_.MissingFields -join "," } } |
        Format-Table -AutoSize
}

if ($completeTaskPairs.Count -eq 0) {
    Write-Host "No complete baseline/context_pack task pairs are available yet."
    if ($Strict) {
        exit 1
    }
    exit 0
}

$baselineStats = New-Stats $baselineRows
$contextStats = New-Stats $contextRows

$accuracyDelta = $contextStats.AnswerAccuracy - $baselineStats.AnswerAccuracy
$missedReduction = Get-Reduction $baselineStats.AvgMissedConstraints $contextStats.AvgMissedConstraints
$tokenReduction = Get-Reduction $baselineStats.AvgTokenCost $contextStats.AvgTokenCost
$elapsedReduction = Get-Reduction $baselineStats.AvgElapsedMinutes $contextStats.AvgElapsedMinutes

$dimensionResults = @(
    [pscustomobject]@{
        Dimension = "answer_accuracy"
        Threshold = "+30 percentage points"
        Actual = Format-Percent $accuracyDelta
        Passed = ($accuracyDelta -ge 0.30)
    },
    [pscustomobject]@{
        Dimension = "missed_constraints"
        Threshold = ">=30% reduction"
        Actual = Format-Percent $missedReduction
        Passed = ($null -ne $missedReduction -and $missedReduction -ge 0.30)
    },
    [pscustomobject]@{
        Dimension = "token_cost"
        Threshold = ">=50% reduction"
        Actual = Format-Percent $tokenReduction
        Passed = ($null -ne $tokenReduction -and $tokenReduction -ge 0.50)
    },
    [pscustomobject]@{
        Dimension = "elapsed_minutes"
        Threshold = ">=30% reduction"
        Actual = Format-Percent $elapsedReduction
        Passed = ($null -ne $elapsedReduction -and $elapsedReduction -ge 0.30)
    }
)

$passedDimensions = @($dimensionResults | Where-Object { $_.Passed }).Count
$evidenceGatePassed = ($contextStats.CitationAccuracy -ge 0.90)
$readyForPhase2 = ($passedDimensions -ge 2 -and $evidenceGatePassed)

$summary = [pscustomobject]@{
    BaselineTasks = $baselineStats.Count
    ContextPackTasks = $contextStats.Count
    BaselineAccuracy = Format-Percent $baselineStats.AnswerAccuracy
    ContextPackAccuracy = Format-Percent $contextStats.AnswerAccuracy
    BaselineEvidenceAccuracy = Format-Percent $baselineStats.CitationAccuracy
    ContextPackEvidenceAccuracy = Format-Percent $contextStats.CitationAccuracy
    BaselineAvgMissed = "{0:N2}" -f $baselineStats.AvgMissedConstraints
    ContextPackAvgMissed = "{0:N2}" -f $contextStats.AvgMissedConstraints
    BaselineAvgTokens = "{0:N0}" -f $baselineStats.AvgTokenCost
    ContextPackAvgTokens = "{0:N0}" -f $contextStats.AvgTokenCost
    BaselineAvgMinutes = "{0:N2}" -f $baselineStats.AvgElapsedMinutes
    ContextPackAvgMinutes = "{0:N2}" -f $contextStats.AvgElapsedMinutes
}

Write-Host "Summary:"
$summary | Format-List

Write-Host "Decision dimensions:"
$dimensionResults | Format-Table -AutoSize

Write-Host ""
Write-Host "Evidence gate: Context Pack citation accuracy >= 90% => $evidenceGatePassed"
Write-Host "Passed dimensions: $passedDimensions / 4"
Write-Host "Recommendation: $(if ($readyForPhase2) { 'READY_FOR_PHASE_2_REVIEW' } else { 'STAY_IN_PHASE_1' })"

if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
    $report = @()
    $report += "# Result Evaluation"
    $report += ""
    $report += ('- Results file: `{0}`' -f $ResultsPath)
    $report += "- Complete paired tasks: $($completeTaskPairs.Count)"
    $report += "- Baseline accuracy: $(Format-Percent $baselineStats.AnswerAccuracy)"
    $report += "- Context Pack accuracy: $(Format-Percent $contextStats.AnswerAccuracy)"
    $report += "- Context Pack evidence accuracy: $(Format-Percent $contextStats.CitationAccuracy)"
    $report += "- Passed dimensions: $passedDimensions / 4"
    $report += "- Recommendation: $(if ($readyForPhase2) { 'READY_FOR_PHASE_2_REVIEW' } else { 'STAY_IN_PHASE_1' })"
    $report += ""
    $report += "## Decision Dimensions"
    foreach ($dimension in $dimensionResults) {
        $report += "- $($dimension.Dimension): $($dimension.Actual), threshold: $($dimension.Threshold), passed: $($dimension.Passed)"
    }

    $reportDir = Split-Path -Parent $ReportPath
    if (-not [string]::IsNullOrWhiteSpace($reportDir) -and -not (Test-Path -LiteralPath $reportDir)) {
        New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
    }
    Set-Content -LiteralPath $ReportPath -Value $report -Encoding UTF8
    Write-Host "Report written: $ReportPath"
}

exit 0
