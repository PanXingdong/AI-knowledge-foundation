param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$EvaluateScript = Join-Path $PSScriptRoot "evaluate-parser-results.ps1"
if (-not (Test-Path -LiteralPath $EvaluateScript)) {
    Write-Error "Missing parser evaluation script: $EvaluateScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-parser-eval-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$parserSheetPath = Join-Path $smokeRoot "parser-evaluation-sheet.csv"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null

    $rows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 10; $i++) {
        foreach ($parser in @("Docling", "MinerU", "Unstructured")) {
            $rows.Add([pscustomobject]@{
                document_id = ("sample-{0:000}" -f $i)
                file_path = ("samples/raw/sample-{0:000}.pdf" -f $i)
                parser = $parser
                page_metadata_rate = if ($parser -eq "Unstructured") { "93%" } else { "98%" }
                span_traceability_rate = if ($parser -eq "MinerU") { "89%" } else { "94%" }
                table_accuracy = if ($parser -eq "MinerU") { "78%" } else { "86%" }
                reading_order_accuracy = if ($parser -eq "Unstructured") { "88%" } else { "93%" }
                ocr_accuracy = if ($parser -eq "Docling") { "96%" } else { "94%" }
                parse_minutes = if ($parser -eq "Docling") { "1.8" } elseif ($parser -eq "MinerU") { "2.4" } else { "1.5" }
                critical_failures = if ($parser -eq "Docling") { "0" } else { "1" }
                notes = "temporary smoke row"
            }) | Out-Null
        }
    }
    $rows | Export-Csv -LiteralPath $parserSheetPath -NoTypeInformation -Encoding UTF8

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "PARSER_SHEET=$parserSheetPath"

    & powershell -ExecutionPolicy Bypass -File $EvaluateScript -Strict -ParserSheetPath $parserSheetPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $failureMessage = "Parser evaluation smoke failed with exit code $exitCode."
    }
    else {
        Write-Host "PARSER_EVALUATION_SMOKE=PASS"
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
    Write-Host "PARSER_EVALUATION_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
