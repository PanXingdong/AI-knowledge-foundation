param(
    [string]$DocumentIntakePath,
    [string]$TaskIntakePath,
    [string]$OwnerTrackerPath,
    [string]$ReportPath,
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Resolve-ProjectPath {
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

$DocumentIntakePath = Resolve-ProjectPath $DocumentIntakePath "samples\document-intake-template.csv"
$TaskIntakePath = Resolve-ProjectPath $TaskIntakePath "experiments\templates\task-intake-template.csv"
$OwnerTrackerPath = Resolve-ProjectPath $OwnerTrackerPath "samples\owner-response-tracker.csv"

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

function Test-ExternalSourceLocation {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $false
    }

    return $Value.Trim() -match '^(https?)://'
}

function Resolve-SourceLocation {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    return Join-Path $ProjectRoot $Value
}

function Convert-ToNumberMetric {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $null
    }

    $number = 0.0
    $ok = [double]::TryParse(
        $Value.Trim(),
        [System.Globalization.NumberStyles]::Float,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [ref]$number
    )

    if ($ok) {
        return $number
    }

    return $null
}

function Import-CsvOrEmpty {
    param(
        [string]$Path,
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Write-Error "Missing $Name file: $Path"
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

function Get-SumOrZero {
    param(
        [object[]]$Rows,
        [string]$Field
    )

    $sum = (($Rows | ForEach-Object { Convert-ToNumberMetric $_.$Field } | Where-Object { $null -ne $_ } | Measure-Object -Sum).Sum)
    if ($null -eq $sum) {
        return 0
    }

    return $sum
}

$documentRows = Import-CsvOrEmpty $DocumentIntakePath "document intake"
$taskRows = Import-CsvOrEmpty $TaskIntakePath "task intake"
$ownerRows = Import-CsvOrEmpty $OwnerTrackerPath "owner tracker"

$readyDocuments = New-Object System.Collections.Generic.List[object]
$externalDocuments = New-Object System.Collections.Generic.List[string]
$missingSourceDocuments = New-Object System.Collections.Generic.List[string]
$incompleteDocuments = New-Object System.Collections.Generic.List[string]

foreach ($row in $documentRows) {
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
            $externalDocuments.Add("$($row.candidate_id): $($row.source_location)") | Out-Null
            $missing += "source_location_local_file"
        }
        else {
            $resolvedSource = Resolve-SourceLocation $row.source_location
            if ($null -eq $resolvedSource -or -not (Test-Path -LiteralPath $resolvedSource -PathType Leaf)) {
                $missing += "source_location_exists"
                $missingSourceDocuments.Add("$($row.candidate_id): $($row.source_location)") | Out-Null
            }
        }
    }

    if ($missing.Count -eq 0) {
        $readyDocuments.Add($row) | Out-Null
    }
    else {
        $candidateId = if (Test-Placeholder $row.candidate_id) { "<missing-candidate-id>" } else { $row.candidate_id }
        $incompleteDocuments.Add(("{0}: {1}" -f $candidateId, ($missing -join ","))) | Out-Null
    }
}

$readyTasks = New-Object System.Collections.Generic.List[object]
$incompleteTasks = New-Object System.Collections.Generic.List[string]

foreach ($row in $taskRows) {
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
    if (-not (Test-Affirmative $row.selected)) {
        $missing += "selected"
    }

    if ($missing.Count -eq 0) {
        $readyTasks.Add($row) | Out-Null
    }
    else {
        $candidateId = if (Test-Placeholder $row.candidate_id) { "<missing-candidate-id>" } else { $row.candidate_id }
        $incompleteTasks.Add(("{0}: {1}" -f $candidateId, ($missing -join ","))) | Out-Null
    }
}

$readyTableDocs = @($readyDocuments | Where-Object { Test-Affirmative $_.has_tables })
$readyMulticolumnDocs = @($readyDocuments | Where-Object { Test-Affirmative $_.has_multicolumn })
$readyScannedDocs = @($readyDocuments | Where-Object { Test-Affirmative $_.is_scanned })
$readyTaskTypes = @($readyTasks | ForEach-Object { $_.task_type } | Where-Object { -not (Test-Placeholder $_) } | Select-Object -Unique)

$ownerSentOrLater = @($ownerRows | Where-Object { $_.current_status -in @("sent", "partial", "ready", "blocked") })
$ownerPartial = @($ownerRows | Where-Object { $_.current_status -eq "partial" })
$ownerReady = @($ownerRows | Where-Object { $_.current_status -eq "ready" })
$ownerBlocked = @($ownerRows | Where-Object { $_.current_status -eq "blocked" })
$ownerNotSent = @($ownerRows | Where-Object { $_.current_status -eq "not_sent" -or (Test-Placeholder $_.current_status) })
$ownerRowCount = @($ownerRows).Count

$providedDocuments = Get-SumOrZero $ownerRows "provided_documents"
$providedTasks = Get-SumOrZero $ownerRows "provided_tasks"

$missingReadyDocs = [Math]::Max(0, 10 - $readyDocuments.Count)
$missingReadyTasks = [Math]::Max(0, 3 - $readyTasks.Count)
$missingTaskTypes = [Math]::Max(0, 3 - $readyTaskTypes.Count)
$missingTableDocs = [Math]::Max(0, 1 - $readyTableDocs.Count)
$missingMulticolumnDocs = [Math]::Max(0, 1 - $readyMulticolumnDocs.Count)
$missingScannedDocs = [Math]::Max(0, 1 - $readyScannedDocs.Count)

$readyToCreateRun = (
    $missingReadyDocs -eq 0 -and
    $missingReadyTasks -eq 0 -and
    $missingTaskTypes -eq 0 -and
    $missingTableDocs -eq 0 -and
    $missingMulticolumnDocs -eq 0 -and
    $missingScannedDocs -eq 0
)

$overall = if ($readyToCreateRun) {
    "READY_TO_CREATE_EXPERIMENT_RUN"
}
elseif ($ownerSentOrLater.Count -eq 0) {
    "OWNER_REQUEST_NOT_SENT"
}
else {
    "WAITING_FOR_OWNER_INPUT"
}

$nextAction = if ($readyToCreateRun) {
    'Run prepare-experiment-run-from-intake.ps1 -RunId "run-001" -Apply.'
}
elseif ($ownerSentOrLater.Count -eq 0) {
    'Export and send owner package: export-owner-package.ps1 -CreateZip -UpdateTracker -Owner "<owner-name>".'
}
else {
    'Follow up owner rows, import returned packages, then run check-intake-readiness.ps1 -Strict.'
}

$summaryRows = @(
    [pscustomobject]@{ Area = "Owner tracking"; Ready = $ownerSentOrLater.Count; Required = ">=1 sent"; Missing = if ($ownerSentOrLater.Count -gt 0) { 0 } else { 1 }; Detail = "rows=$ownerRowCount; not_sent=$($ownerNotSent.Count); sent_or_later=$($ownerSentOrLater.Count); partial=$($ownerPartial.Count); ready=$($ownerReady.Count); blocked=$($ownerBlocked.Count); provided_docs=$providedDocuments; provided_tasks=$providedTasks" },
    [pscustomobject]@{ Area = "Ready documents"; Ready = $readyDocuments.Count; Required = 10; Missing = $missingReadyDocs; Detail = "external=$($externalDocuments.Count); missing_source=$($missingSourceDocuments.Count)" },
    [pscustomobject]@{ Area = "Table documents"; Ready = $readyTableDocs.Count; Required = 1; Missing = $missingTableDocs; Detail = "needed for parser evaluation" },
    [pscustomobject]@{ Area = "Multicolumn documents"; Ready = $readyMulticolumnDocs.Count; Required = 1; Missing = $missingMulticolumnDocs; Detail = "needed for reading-order evaluation" },
    [pscustomobject]@{ Area = "Scanned/OCR-risk documents"; Ready = $readyScannedDocs.Count; Required = 1; Missing = $missingScannedDocs; Detail = "needed for OCR evaluation" },
    [pscustomobject]@{ Area = "Ready tasks"; Ready = $readyTasks.Count; Required = 3; Missing = $missingReadyTasks; Detail = "must be selected and scorable" },
    [pscustomobject]@{ Area = "Task types"; Ready = $readyTaskTypes.Count; Required = 3; Missing = $missingTaskTypes; Detail = ($readyTaskTypes -join ";") }
)

Write-Host "Agent Knowledge Hub owner intake status"
Write-Host "Project root: $ProjectRoot"
Write-Host "Document intake: $DocumentIntakePath"
Write-Host "Task intake: $TaskIntakePath"
Write-Host "Owner tracker: $OwnerTrackerPath"
Write-Host ""
$summaryRows | Format-Table -AutoSize
Write-Host ""
Write-Host "Overall: $overall"
Write-Host "Next action: $nextAction"

if ($incompleteDocuments.Count -gt 0) {
    Write-Host ""
    Write-Host "Top incomplete documents:"
    $incompleteDocuments | Select-Object -First 5 | ForEach-Object { Write-Host "- $_" }
}

if ($incompleteTasks.Count -gt 0) {
    Write-Host ""
    Write-Host "Top incomplete tasks:"
    $incompleteTasks | Select-Object -First 5 | ForEach-Object { Write-Host "- $_" }
}

if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
    if (-not [System.IO.Path]::IsPathRooted($ReportPath)) {
        $ReportPath = Join-Path $ProjectRoot $ReportPath
    }

    $report = @()
    $report += "# Owner Intake Status"
    $report += ""
    $report += "- Overall: $overall"
    $report += "- Next action: $nextAction"
    $report += ('- Document intake: `{0}`' -f $DocumentIntakePath)
    $report += ('- Task intake: `{0}`' -f $TaskIntakePath)
    $report += ('- Owner tracker: `{0}`' -f $OwnerTrackerPath)
    $report += ""
    $report += "## Summary"
    foreach ($row in $summaryRows) {
        $report += "- $($row.Area): ready=$($row.Ready); required=$($row.Required); missing=$($row.Missing); $($row.Detail)"
    }

    if ($incompleteDocuments.Count -gt 0) {
        $report += ""
        $report += "## Top Incomplete Documents"
        foreach ($item in ($incompleteDocuments | Select-Object -First 10)) {
            $report += "- $item"
        }
    }

    if ($incompleteTasks.Count -gt 0) {
        $report += ""
        $report += "## Top Incomplete Tasks"
        foreach ($item in ($incompleteTasks | Select-Object -First 10)) {
            $report += "- $item"
        }
    }

    $reportDir = Split-Path -Parent $ReportPath
    if (-not [string]::IsNullOrWhiteSpace($reportDir) -and -not (Test-Path -LiteralPath $reportDir)) {
        New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
    }
    Set-Content -LiteralPath $ReportPath -Value $report -Encoding UTF8
    Write-Host "Report written: $ReportPath"
}

if ($Strict -and -not $readyToCreateRun) {
    exit 1
}

exit 0
