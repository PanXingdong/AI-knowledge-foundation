param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$InitScript = Join-Path $PSScriptRoot "initialize-parser-evaluation-from-manifest.ps1"
if (-not (Test-Path -LiteralPath $InitScript)) {
    Write-Error "Missing parser evaluation initialization script: $InitScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-parser-init-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$runDir = Join-Path $smokeRoot "run"
$rawDir = Join-Path $smokeRoot "raw"
$manifestPath = Join-Path $smokeRoot "sample-manifest.csv"
$parserSheetPath = Join-Path $runDir "parser-evaluation-sheet.csv"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null
    New-Item -ItemType Directory -Path $rawDir -Force | Out-Null

    $manifestRows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 10; $i++) {
        $extension = if ($i -eq 10) { ".docx" } else { ".pdf" }
        $sampleId = ("sample-{0:000}" -f $i)
        $sourcePath = Join-Path $rawDir ($sampleId + $extension)
        Set-Content -LiteralPath $sourcePath -Value ("parser init smoke source {0}" -f $i) -Encoding UTF8

        $manifestRows.Add([pscustomobject]@{
            sample_id = $sampleId
            slot_type = "QNX adaptation smoke"
            file_path = $sourcePath
            document_title = ("Smoke Document {0:00}" -f $i)
            document_version = "v1.0"
            owner = "smoke-owner"
            is_scanned = if ($i -eq 3) { "yes" } else { "no" }
            has_tables = if ($i -eq 2 -or $i -eq 8) { "yes" } else { "no" }
            has_multicolumn = if ($i -eq 4) { "yes" } else { "no" }
            confidentiality = "internal"
            status = "ready"
            notes = "temporary smoke input"
        }) | Out-Null
    }
    $manifestRows | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding UTF8

    @(
        [pscustomobject]@{
            document_id = "sample-001"
            file_path = "TBD"
            parser = "Docling"
            page_metadata_rate = "TBD"
            span_traceability_rate = "TBD"
            table_accuracy = "TBD"
            reading_order_accuracy = "TBD"
            ocr_accuracy = "TBD"
            parse_minutes = "TBD"
            critical_failures = "TBD"
            notes = "placeholder"
        }
    ) | Export-Csv -LiteralPath $parserSheetPath -NoTypeInformation -Encoding UTF8

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "RUN_DIR=$runDir"
    Write-Host "MANIFEST=$manifestPath"
    Write-Host "PARSER_SHEET=$parserSheetPath"

    & powershell -ExecutionPolicy Bypass -File $InitScript `
        -ExperimentDir $runDir `
        -SampleManifestPath $manifestPath
    $dryRunExitCode = $LASTEXITCODE
    if ($dryRunExitCode -ne 0) {
        $failureMessage = "Parser evaluation initialization dry run failed with exit code $dryRunExitCode."
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        & powershell -ExecutionPolicy Bypass -File $InitScript `
            -ExperimentDir $runDir `
            -SampleManifestPath $manifestPath `
            -Apply
        $applyExitCode = $LASTEXITCODE
        if ($applyExitCode -ne 0) {
            $failureMessage = "Parser evaluation initialization apply failed with exit code $applyExitCode."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        $rows = @(Import-Csv -LiteralPath $parserSheetPath -Encoding UTF8)
        $docIds = @($rows | ForEach-Object { $_.document_id } | Select-Object -Unique)
        $parserNames = @($rows | ForEach-Object { $_.parser } | Select-Object -Unique)
        $enteredMetricRows = @(
            $rows | Where-Object {
                $_.page_metadata_rate -ne "TBD" -or
                $_.span_traceability_rate -ne "TBD" -or
                $_.table_accuracy -ne "TBD" -or
                $_.reading_order_accuracy -ne "TBD" -or
                $_.ocr_accuracy -ne "TBD" -or
                $_.parse_minutes -ne "TBD" -or
                $_.critical_failures -ne "TBD"
            }
        )

        if ($rows.Count -ne 30) {
            $failureMessage = "Expected 30 parser placeholder rows, found $($rows.Count)."
        }
        elseif ($docIds.Count -ne 10) {
            $failureMessage = "Expected 10 distinct documents, found $($docIds.Count)."
        }
        elseif ($parserNames.Count -ne 3) {
            $failureMessage = "Expected 3 parser names, found $($parserNames.Count)."
        }
        elseif ($enteredMetricRows.Count -ne 0) {
            $failureMessage = "Parser initialization must not fill real metrics."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        $rows = @(Import-Csv -LiteralPath $parserSheetPath -Encoding UTF8)
        $rows[0].page_metadata_rate = "98%"
        $rows | Export-Csv -LiteralPath $parserSheetPath -NoTypeInformation -Encoding UTF8

        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & powershell -ExecutionPolicy Bypass -File $InitScript `
                -ExperimentDir $runDir `
                -SampleManifestPath $manifestPath `
                -Apply *> $null
            $overwriteExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }

        if ($overwriteExitCode -eq 0) {
            $failureMessage = "Parser initialization should refuse to overwrite entered metrics without -Force."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        Write-Host "PARSER_EVALUATION_INITIALIZATION_SMOKE=PASS"
    }
}
catch {
    $failureMessage = $_.Exception.Message
}
finally {
    if ($KeepArtifacts) {
        Write-Host "SMOKE_ARTIFACTS_KEPT=$smokeRoot"
    }
    elseif (Test-Path -LiteralPath $smokeRoot) {
        Remove-Item -LiteralPath $smokeRoot -Recurse -Force
        Write-Host "SMOKE_ARTIFACTS_CLEANED=$smokeRoot"
    }
}

if (-not [string]::IsNullOrWhiteSpace($failureMessage)) {
    Write-Host "PARSER_EVALUATION_INITIALIZATION_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
