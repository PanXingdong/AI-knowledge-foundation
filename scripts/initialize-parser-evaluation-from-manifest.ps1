param(
    [string]$RunId,
    [string]$ExperimentDir,
    [string]$SampleManifestPath,
    [string]$ParserSheetPath,
    [string[]]$Parsers = @("Docling", "MinerU", "Unstructured"),
    [int]$MinimumDocuments = 10,
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

if ([string]::IsNullOrWhiteSpace($SampleManifestPath)) {
    $SampleManifestPath = Join-Path $ProjectRoot "samples\sample-manifest.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($SampleManifestPath)) {
    $SampleManifestPath = Join-Path $ProjectRoot $SampleManifestPath
}

if ([string]::IsNullOrWhiteSpace($ParserSheetPath)) {
    $ParserSheetPath = Join-Path $ExperimentDir "parser-evaluation-sheet.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($ParserSheetPath)) {
    $ParserSheetPath = Join-Path $ExperimentDir $ParserSheetPath
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
    "N/A",
    "placeholder"
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

function Resolve-ProjectPath {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return [System.IO.Path]::GetFullPath($Value)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $Value))
}

function Test-ParserSheetHasEnteredMetrics {
    param([object[]]$Rows)

    foreach ($row in $Rows) {
        foreach ($field in @(
            "page_metadata_rate",
            "span_traceability_rate",
            "table_accuracy",
            "reading_order_accuracy",
            "ocr_accuracy",
            "parse_minutes",
            "critical_failures"
        )) {
            if (-not (Test-Placeholder $row.$field)) {
                return $true
            }
        }
    }

    return $false
}

if ($MinimumDocuments -lt 1) {
    Write-Error "MinimumDocuments must be at least 1."
}

$normalizedParsers = @(
    $Parsers |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_.Trim() } |
        Select-Object -Unique
)

if ($normalizedParsers.Count -lt 3) {
    Write-Error "Expected at least 3 parsers for comparison, found $($normalizedParsers.Count)."
}

if (-not (Test-Path -LiteralPath $SampleManifestPath -PathType Leaf)) {
    Write-Error "Missing sample manifest: $SampleManifestPath"
}

$manifestRows = @(Import-Csv -LiteralPath $SampleManifestPath -Encoding UTF8)

Assert-RequiredColumns $manifestRows @(
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
) "Sample manifest"

$readyRows = New-Object System.Collections.Generic.List[object]
$incompleteRows = New-Object System.Collections.Generic.List[string]
foreach ($row in $manifestRows) {
    $missing = Get-MissingFields $row @(
        "sample_id",
        "slot_type",
        "file_path",
        "document_title",
        "document_version",
        "owner",
        "status"
    )

    $resolvedPath = $null
    if (-not (Test-Placeholder $row.file_path)) {
        $resolvedPath = Resolve-ProjectPath $row.file_path
        if ($null -eq $resolvedPath -or -not (Test-Path -LiteralPath $resolvedPath -PathType Leaf)) {
            $missing += "file_path_exists"
        }
    }

    if ($missing.Count -eq 0) {
        $readyRows.Add([pscustomobject]@{
            Row = $row
            ResolvedPath = $resolvedPath
        }) | Out-Null
    }
    else {
        $sampleId = if (Test-Placeholder $row.sample_id) { "<missing-sample-id>" } else { $row.sample_id }
        $incompleteRows.Add(("{0}: {1}" -f $sampleId, ($missing -join ","))) | Out-Null
    }
}

if ($readyRows.Count -lt $MinimumDocuments) {
    Write-Error "Expected at least $MinimumDocuments ready sample documents, found $($readyRows.Count). Incomplete rows: $($incompleteRows -join '; ')"
}

$selectedRows = @($readyRows | Select-Object -First $MinimumDocuments)
$duplicateSampleIds = @(
    $selectedRows |
        ForEach-Object { $_.Row.sample_id } |
        Group-Object |
        Where-Object { $_.Count -gt 1 } |
        ForEach-Object { $_.Name }
)
if ($duplicateSampleIds.Count -gt 0) {
    Write-Error "Duplicate sample_id values among selected documents: $($duplicateSampleIds -join ', ')"
}

$parserColumns = @(
    "document_id",
    "file_path",
    "parser",
    "page_metadata_rate",
    "span_traceability_rate",
    "table_accuracy",
    "reading_order_accuracy",
    "ocr_accuracy",
    "parse_minutes",
    "critical_failures",
    "notes"
)

if ((Test-Path -LiteralPath $ParserSheetPath -PathType Leaf) -and -not $Force) {
    $existingRows = @(Import-Csv -LiteralPath $ParserSheetPath -Encoding UTF8)
    if ($existingRows.Count -gt 0) {
        Assert-RequiredColumns $existingRows $parserColumns "Existing parser evaluation sheet"
        if (Test-ParserSheetHasEnteredMetrics $existingRows) {
            Write-Error "Refusing to overwrite parser evaluation rows with entered metrics without -Force: $ParserSheetPath"
        }
    }
}

$parserRows = @()
foreach ($sample in $selectedRows) {
    foreach ($parser in $normalizedParsers) {
        $parserRows += [pscustomobject]@{
            document_id = $sample.Row.sample_id
            file_path = $sample.Row.file_path
            parser = $parser
            page_metadata_rate = "TBD"
            span_traceability_rate = "TBD"
            table_accuracy = "TBD"
            reading_order_accuracy = "TBD"
            ocr_accuracy = "TBD"
            parse_minutes = "TBD"
            critical_failures = "TBD"
            notes = "initialized from sample manifest; title=$($sample.Row.document_title); version=$($sample.Row.document_version); scanned=$($sample.Row.is_scanned); tables=$($sample.Row.has_tables); multicolumn=$($sample.Row.has_multicolumn)"
        }
    }
}

Write-Host "Agent Knowledge Hub parser evaluation initialization"
Write-Host "Experiment dir: $ExperimentDir"
Write-Host "Sample manifest: $SampleManifestPath"
Write-Host "Parser sheet: $ParserSheetPath"
Write-Host "Parsers: $($normalizedParsers -join ', ')"
Write-Host "Mode: $(if ($Apply) { 'apply' } else { 'dry run' })"
Write-Host ""
Write-Host "Ready sample documents: $($readyRows.Count)"
Write-Host "Selected sample documents: $($selectedRows.Count)"
Write-Host "Rows to write: $($parserRows.Count)"

if (-not $Apply) {
    Write-Host ""
    Write-Host "Dry run only. Use -Apply to write parser/document placeholder rows."
    Write-Host "PARSER_EVALUATION_INIT_DRY_RUN=PASS"
    exit 0
}

$parserSheetParent = Split-Path -Parent $ParserSheetPath
if (-not [string]::IsNullOrWhiteSpace($parserSheetParent) -and -not (Test-Path -LiteralPath $parserSheetParent)) {
    New-Item -ItemType Directory -Path $parserSheetParent -Force | Out-Null
}

if (Test-Path -LiteralPath $ParserSheetPath -PathType Leaf) {
    $backupPath = Join-Path $parserSheetParent ("parser-evaluation-sheet.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".csv")
    Copy-Item -LiteralPath $ParserSheetPath -Destination $backupPath
    Write-Host "Backup written: $backupPath"
}

$parserRows |
    Select-Object $parserColumns |
    Export-Csv -LiteralPath $ParserSheetPath -NoTypeInformation -Encoding UTF8

Write-Host "Parser evaluation sheet initialized: $ParserSheetPath"
Write-Host "PARSER_EVALUATION_INIT_APPLY=PASS"

exit 0
