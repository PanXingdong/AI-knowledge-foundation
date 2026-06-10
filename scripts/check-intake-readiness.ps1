param(
    [switch]$Strict,
    [string]$DocumentIntakePath,
    [string]$TaskIntakePath
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($DocumentIntakePath)) {
    $DocumentIntakePath = Join-Path $ProjectRoot "samples\document-intake-template.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($DocumentIntakePath)) {
    $DocumentIntakePath = Join-Path $ProjectRoot $DocumentIntakePath
}

if ([string]::IsNullOrWhiteSpace($TaskIntakePath)) {
    $TaskIntakePath = Join-Path $ProjectRoot "experiments\templates\task-intake-template.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($TaskIntakePath)) {
    $TaskIntakePath = Join-Path $ProjectRoot $TaskIntakePath
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

function Get-ReadinessStatus {
    if ($Strict) {
        return "FAIL"
    }

    return "WARN"
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
        $rows = Import-Csv -LiteralPath $Path -Encoding UTF8
        Add-Check "PASS" $Name "CSV parsed, rows: $($rows.Count)"
        return @($rows)
    }
    catch {
        Add-Check "FAIL" $Name "CSV parse failed: $($_.Exception.Message)"
        return @()
    }
}

function Test-RequiredColumns {
    param(
        [object[]]$Rows,
        [string[]]$RequiredColumns,
        [string]$Name
    )

    if ($Rows.Count -eq 0) {
        Add-Check "FAIL" $Name "No rows available for column validation."
        return $false
    }

    $columns = @($Rows[0].PSObject.Properties.Name)
    $missing = @($RequiredColumns | Where-Object { $_ -notin $columns })
    if ($missing.Count -eq 0) {
        Add-Check "PASS" $Name "All required columns found."
        return $true
    }

    Add-Check "FAIL" $Name "Missing columns: $($missing -join ', ')"
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

    $trimmed = $Value.Trim()
    if ([System.IO.Path]::IsPathRooted($trimmed)) {
        return $trimmed
    }

    return Join-Path $ProjectRoot $trimmed
}

Write-Host "Agent Knowledge Hub intake readiness"
Write-Host "Document intake: $DocumentIntakePath"
Write-Host "Task intake: $TaskIntakePath"
Write-Host "Mode: $(if ($Strict) { 'strict readiness gate' } else { 'advisory readiness check' })"
Write-Host ""

$documentRows = Import-CsvChecked $DocumentIntakePath "Document intake"
$taskRows = Import-CsvChecked $TaskIntakePath "Task intake"

$requiredDocumentColumns = @(
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

$requiredTaskColumns = @(
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

$documentColumnsOk = Test-RequiredColumns $documentRows $requiredDocumentColumns "Document intake columns"
$taskColumnsOk = Test-RequiredColumns $taskRows $requiredTaskColumns "Task intake columns"

$readyDocumentRows = New-Object System.Collections.Generic.List[object]
$incompleteDocuments = New-Object System.Collections.Generic.List[string]
$missingSourceLocations = New-Object System.Collections.Generic.List[string]
$externalSourceLocations = New-Object System.Collections.Generic.List[string]
$verifiedSourceLocations = New-Object System.Collections.Generic.List[string]

if ($documentColumnsOk) {
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
                $externalSourceLocations.Add("$($row.candidate_id): $($row.source_location)") | Out-Null
                if ($Strict) {
                    $missing += "source_location_local_verification"
                }
            }
            else {
                $resolvedSourceLocation = Resolve-SourceLocation $row.source_location
                if ($null -ne $resolvedSourceLocation -and (Test-Path -LiteralPath $resolvedSourceLocation)) {
                    $verifiedSourceLocations.Add("$($row.candidate_id): $($row.source_location)") | Out-Null
                }
                else {
                    $missing += "source_location_exists"
                    $missingSourceLocations.Add("$($row.candidate_id): $($row.source_location)") | Out-Null
                }
            }
        }

        if ($missing.Count -eq 0) {
            $readyDocumentRows.Add($row) | Out-Null
        }
        else {
            $candidateId = if (Test-Placeholder $row.candidate_id) { "<missing-candidate-id>" } else { $row.candidate_id }
            $incompleteDocuments.Add(("{0}: {1}" -f $candidateId, ($missing -join ","))) | Out-Null
        }
    }

    if ($readyDocumentRows.Count -ge 10) {
        Add-Check "PASS" "Ready document candidates" "Ready documents: $($readyDocumentRows.Count)"
    }
    else {
        Add-Check (Get-ReadinessStatus) "Ready document candidates" "Expected at least 10 ready documents, found $($readyDocumentRows.Count)."
    }

    if ($missingSourceLocations.Count -eq 0) {
        Add-Check "PASS" "Document source path verification" "No missing local/shared source paths among document candidates."
    }
    else {
        Add-Check (Get-ReadinessStatus) "Document source path verification" "Missing local/shared source paths: $($missingSourceLocations -join '; ')"
    }

    if ($externalSourceLocations.Count -eq 0) {
        Add-Check "PASS" "External document source locations" "No HTTP/HTTPS source locations requiring manual confirmation."
    }
    else {
        Add-Check (Get-ReadinessStatus) "External document source locations" "External source locations require manual confirmation: $($externalSourceLocations -join '; ')"
    }

    if ($verifiedSourceLocations.Count -gt 0) {
        Add-Check "PASS" "Verified document source locations" "Verified local/shared source paths: $($verifiedSourceLocations.Count)"
    }
    else {
        Add-Check (Get-ReadinessStatus) "Verified document source locations" "No ready document candidates have verified local/shared source paths."
    }

    $tableDocs = @($readyDocumentRows | Where-Object { Test-Affirmative $_.has_tables })
    if ($tableDocs.Count -gt 0) {
        Add-Check "PASS" "Document table coverage" "Ready table documents: $($tableDocs.Count)"
    }
    else {
        Add-Check (Get-ReadinessStatus) "Document table coverage" "Expected at least one ready document with tables."
    }

    $multicolumnDocs = @($readyDocumentRows | Where-Object { Test-Affirmative $_.has_multicolumn })
    if ($multicolumnDocs.Count -gt 0) {
        Add-Check "PASS" "Document multicolumn coverage" "Ready multicolumn documents: $($multicolumnDocs.Count)"
    }
    else {
        Add-Check (Get-ReadinessStatus) "Document multicolumn coverage" "Expected at least one ready multicolumn document."
    }

    $scannedDocs = @($readyDocumentRows | Where-Object { Test-Affirmative $_.is_scanned })
    if ($scannedDocs.Count -gt 0) {
        Add-Check "PASS" "Document OCR coverage" "Ready scanned/OCR-risk documents: $($scannedDocs.Count)"
    }
    else {
        Add-Check (Get-ReadinessStatus) "Document OCR coverage" "Expected at least one ready scanned/OCR-risk document."
    }

    if ($incompleteDocuments.Count -eq 0) {
        Add-Check "PASS" "Incomplete document candidates" "No incomplete document candidates."
    }
    else {
        Add-Check "WARN" "Incomplete document candidates" "Incomplete candidates: $($incompleteDocuments -join '; ')"
    }
}

$readyTaskRows = New-Object System.Collections.Generic.List[object]
$incompleteTasks = New-Object System.Collections.Generic.List[string]

if ($taskColumnsOk) {
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
            $readyTaskRows.Add($row) | Out-Null
        }
        else {
            $candidateId = if (Test-Placeholder $row.candidate_id) { "<missing-candidate-id>" } else { $row.candidate_id }
            $incompleteTasks.Add(("{0}: {1}" -f $candidateId, ($missing -join ","))) | Out-Null
        }
    }

    if ($readyTaskRows.Count -ge 3) {
        Add-Check "PASS" "Ready task candidates" "Ready selected tasks: $($readyTaskRows.Count)"
    }
    else {
        Add-Check (Get-ReadinessStatus) "Ready task candidates" "Expected at least 3 ready selected tasks, found $($readyTaskRows.Count)."
    }

    $taskTypes = @($readyTaskRows | ForEach-Object { $_.task_type } | Where-Object { -not (Test-Placeholder $_) } | Select-Object -Unique)
    if ($taskTypes.Count -ge 3) {
        Add-Check "PASS" "Task type coverage" "Distinct ready task types: $($taskTypes.Count)"
    }
    else {
        Add-Check (Get-ReadinessStatus) "Task type coverage" "Expected at least 3 distinct ready task types, found $($taskTypes.Count)."
    }

    if ($incompleteTasks.Count -eq 0) {
        Add-Check "PASS" "Incomplete task candidates" "No incomplete task candidates."
    }
    else {
        Add-Check "WARN" "Incomplete task candidates" "Incomplete candidates: $($incompleteTasks -join '; ')"
    }
}

$readyForExperimentIntake = (
    $readyDocumentRows.Count -ge 10 -and
    @($readyDocumentRows | Where-Object { Test-Affirmative $_.has_tables }).Count -gt 0 -and
    @($readyDocumentRows | Where-Object { Test-Affirmative $_.has_multicolumn }).Count -gt 0 -and
    @($readyDocumentRows | Where-Object { Test-Affirmative $_.is_scanned }).Count -gt 0 -and
    $readyTaskRows.Count -ge 3 -and
    @($readyTaskRows | ForEach-Object { $_.task_type } | Where-Object { -not (Test-Placeholder $_) } | Select-Object -Unique).Count -ge 3
)

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
Write-Host "Recommendation: $(if ($readyForExperimentIntake) { 'READY_TO_CREATE_EXPERIMENT_RUN' } else { 'INTAKE_INCOMPLETE' })"

if ($failCount -gt 0) {
    exit 1
}

if ($Strict -and -not $readyForExperimentIntake) {
    exit 1
}

exit 0
