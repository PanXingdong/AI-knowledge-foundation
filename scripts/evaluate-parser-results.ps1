param(
    [string]$ParserSheetPath,
    [string]$ReportPath,
    [switch]$Strict,
    [int]$MinimumDocuments = 10,
    [int]$MinimumParsers = 3
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ParserSheetPath)) {
    $ParserSheetPath = Join-Path $ProjectRoot "experiments\templates\parser-evaluation-sheet.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($ParserSheetPath)) {
    $ParserSheetPath = Join-Path $ProjectRoot $ParserSheetPath
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

function Format-Percent {
    param($Value)

    if ($null -eq $Value) {
        return "N/A"
    }

    return ("{0:P1}" -f $Value)
}

function Convert-RowMetrics {
    param([pscustomobject]$Row)

    $pageMetadataRate = Convert-ToNumberMetric $Row.page_metadata_rate
    $spanTraceabilityRate = Convert-ToNumberMetric $Row.span_traceability_rate
    $tableAccuracy = Convert-ToNumberMetric $Row.table_accuracy
    $readingOrderAccuracy = Convert-ToNumberMetric $Row.reading_order_accuracy
    $ocrAccuracy = Convert-ToNumberMetric $Row.ocr_accuracy
    $parseMinutes = Convert-ToNumberMetric $Row.parse_minutes
    $criticalFailures = Convert-ToNumberMetric $Row.critical_failures

    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($pair in @(
        @{ Name = "document_id"; Value = $Row.document_id },
        @{ Name = "file_path"; Value = $Row.file_path },
        @{ Name = "parser"; Value = $Row.parser }
    )) {
        if (Test-Placeholder $pair.Value) {
            $missing.Add($pair.Name) | Out-Null
        }
    }

    foreach ($pair in @(
        @{ Name = "page_metadata_rate"; Value = $pageMetadataRate },
        @{ Name = "span_traceability_rate"; Value = $spanTraceabilityRate },
        @{ Name = "table_accuracy"; Value = $tableAccuracy },
        @{ Name = "reading_order_accuracy"; Value = $readingOrderAccuracy },
        @{ Name = "ocr_accuracy"; Value = $ocrAccuracy },
        @{ Name = "parse_minutes"; Value = $parseMinutes },
        @{ Name = "critical_failures"; Value = $criticalFailures }
    )) {
        if ($null -eq $pair.Value) {
            $missing.Add($pair.Name) | Out-Null
        }
    }

    return [pscustomobject]@{
        DocumentId = $Row.document_id
        FilePath = $Row.file_path
        Parser = $Row.parser
        PageMetadataRate = $pageMetadataRate
        SpanTraceabilityRate = $spanTraceabilityRate
        TableAccuracy = $tableAccuracy
        ReadingOrderAccuracy = $readingOrderAccuracy
        OcrAccuracy = $ocrAccuracy
        ParseMinutes = $parseMinutes
        CriticalFailures = $criticalFailures
        MissingFields = @($missing)
        IsComplete = ($missing.Count -eq 0)
    }
}

function Get-Average {
    param(
        [object[]]$Rows,
        [string]$Property
    )

    if ($Rows.Count -eq 0) {
        return $null
    }

    return (($Rows | Measure-Object -Property $Property -Average).Average)
}

if (-not (Test-Path -LiteralPath $ParserSheetPath)) {
    Write-Error "Parser evaluation file not found: $ParserSheetPath"
}

$rows = @(Import-Csv -LiteralPath $ParserSheetPath -Encoding UTF8)
$requiredColumns = @(
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

if ($rows.Count -eq 0) {
    Write-Error "Parser evaluation file has no rows: $ParserSheetPath"
}

$columns = @($rows[0].PSObject.Properties.Name)
$missingColumns = @($requiredColumns | Where-Object { $_ -notin $columns })
if ($missingColumns.Count -gt 0) {
    Write-Error "Missing required columns: $($missingColumns -join ', ')"
}

$metrics = @($rows | ForEach-Object { Convert-RowMetrics $_ })
$completeRows = @($metrics | Where-Object { $_.IsComplete })
$incompleteRows = @($metrics | Where-Object { -not $_.IsComplete })

$parserStats = @(
    $completeRows |
        Group-Object -Property Parser |
        ForEach-Object {
            $parserRows = @($_.Group)
            $avgPage = Get-Average $parserRows "PageMetadataRate"
            $avgSpan = Get-Average $parserRows "SpanTraceabilityRate"
            $avgTable = Get-Average $parserRows "TableAccuracy"
            $avgReading = Get-Average $parserRows "ReadingOrderAccuracy"
            $avgOcr = Get-Average $parserRows "OcrAccuracy"
            $avgParseMinutes = Get-Average $parserRows "ParseMinutes"
            $totalFailures = (($parserRows | Measure-Object -Property CriticalFailures -Sum).Sum)
            $qualityScore = ($avgPage + $avgSpan + $avgTable + $avgReading + $avgOcr) / 5.0

            [pscustomobject]@{
                Parser = $_.Name
                CompleteRows = $parserRows.Count
                DistinctDocuments = @($parserRows | ForEach-Object { $_.DocumentId } | Select-Object -Unique).Count
                AvgPageMetadata = $avgPage
                AvgSpanTraceability = $avgSpan
                AvgTableAccuracy = $avgTable
                AvgReadingOrder = $avgReading
                AvgOcrAccuracy = $avgOcr
                AvgParseMinutes = $avgParseMinutes
                TotalCriticalFailures = $totalFailures
                QualityScore = $qualityScore
                PassesQualityGate = (
                    $parserRows.Count -gt 0 -and
                    @($parserRows | ForEach-Object { $_.DocumentId } | Select-Object -Unique).Count -ge $MinimumDocuments -and
                    $avgPage -ge 0.95 -and
                    $avgSpan -ge 0.90 -and
                    $avgTable -ge 0.80 -and
                    $avgReading -ge 0.90 -and
                    $avgOcr -ge 0.95 -and
                    $totalFailures -eq 0
                )
            }
        }
)

$coveredParsers = @($parserStats | Where-Object { $_.DistinctDocuments -ge $MinimumDocuments })
$eligibleParsers = @($parserStats | Where-Object { $_.PassesQualityGate })
$coverageGatePassed = ($coveredParsers.Count -ge $MinimumParsers)
$readyParser = $null
if ($coverageGatePassed -and $eligibleParsers.Count -gt 0) {
    $readyParser = @(
        $eligibleParsers |
            Sort-Object `
                @{ Expression = "QualityScore"; Descending = $true },
                @{ Expression = "AvgParseMinutes"; Ascending = $true },
                @{ Expression = "Parser"; Ascending = $true }
    )[0]
}

Write-Host "Agent Knowledge Hub parser evaluation"
Write-Host "Parser sheet: $ParserSheetPath"
Write-Host "Complete rows: $($completeRows.Count)"
Write-Host "Incomplete rows: $($incompleteRows.Count)"
Write-Host "Minimum documents per parser: $MinimumDocuments"
Write-Host "Minimum parsers compared: $MinimumParsers"
Write-Host ""

if ($incompleteRows.Count -gt 0) {
    Write-Host "Incomplete rows:"
    $incompleteRows |
        Select-Object DocumentId, Parser, @{ Name = "MissingFields"; Expression = { $_.MissingFields -join "," } } |
        Format-Table -AutoSize
}

if ($parserStats.Count -eq 0) {
    Write-Host "No complete parser rows are available yet."
    if ($Strict) {
        exit 1
    }
    exit 0
}

Write-Host "Parser summary:"
$parserStats |
    Select-Object `
        Parser,
        CompleteRows,
        DistinctDocuments,
        @{ Name = "Page"; Expression = { Format-Percent $_.AvgPageMetadata } },
        @{ Name = "Span"; Expression = { Format-Percent $_.AvgSpanTraceability } },
        @{ Name = "Table"; Expression = { Format-Percent $_.AvgTableAccuracy } },
        @{ Name = "Reading"; Expression = { Format-Percent $_.AvgReadingOrder } },
        @{ Name = "OCR"; Expression = { Format-Percent $_.AvgOcrAccuracy } },
        @{ Name = "Minutes"; Expression = { "{0:N2}" -f $_.AvgParseMinutes } },
        TotalCriticalFailures,
        PassesQualityGate |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Coverage gate: parsers with >= $MinimumDocuments documents >= $MinimumParsers => $coverageGatePassed"
Write-Host "Eligible parsers: $($eligibleParsers.Count)"

if ($null -ne $readyParser) {
    Write-Host "Recommendation: PARSER_READY"
    Write-Host "Selected parser: $($readyParser.Parser)"
}
else {
    Write-Host "Recommendation: PARSER_EVALUATION_INCOMPLETE_OR_FAILED"
}

if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
    $report = @()
    $report += "# Parser Evaluation"
    $report += ""
    $report += ('- Parser sheet: `{0}`' -f $ParserSheetPath)
    $report += "- Complete rows: $($completeRows.Count)"
    $report += "- Incomplete rows: $($incompleteRows.Count)"
    $report += "- Coverage gate: $coverageGatePassed"
    $report += "- Eligible parsers: $($eligibleParsers.Count)"
    $report += "- Recommendation: $(if ($null -ne $readyParser) { 'PARSER_READY' } else { 'PARSER_EVALUATION_INCOMPLETE_OR_FAILED' })"
    if ($null -ne $readyParser) {
        $report += "- Selected parser: $($readyParser.Parser)"
    }
    $report += ""
    $report += "## Parser Summary"
    foreach ($parser in $parserStats) {
        $report += "- $($parser.Parser): docs=$($parser.DistinctDocuments), page=$(Format-Percent $parser.AvgPageMetadata), span=$(Format-Percent $parser.AvgSpanTraceability), table=$(Format-Percent $parser.AvgTableAccuracy), reading=$(Format-Percent $parser.AvgReadingOrder), ocr=$(Format-Percent $parser.AvgOcrAccuracy), failures=$($parser.TotalCriticalFailures), passed=$($parser.PassesQualityGate)"
    }

    $reportDir = Split-Path -Parent $ReportPath
    if (-not [string]::IsNullOrWhiteSpace($reportDir) -and -not (Test-Path -LiteralPath $reportDir)) {
        New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
    }
    Set-Content -LiteralPath $ReportPath -Value $report -Encoding UTF8
    Write-Host "Report written: $ReportPath"
}

if ($Strict -and $null -eq $readyParser) {
    exit 1
}

exit 0
