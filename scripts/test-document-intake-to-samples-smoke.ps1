param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ApplyScript = Join-Path $PSScriptRoot "apply-document-intake-to-samples.ps1"

if (-not (Test-Path -LiteralPath $ApplyScript)) {
    Write-Error "Missing apply script: $ApplyScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-document-apply-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$sourceRoot = Join-Path $smokeRoot "source"
$rawDir = Join-Path $smokeRoot "raw"
$manifestPath = Join-Path $smokeRoot "sample-manifest.csv"
$documentIntakePath = Join-Path $smokeRoot "document-intake.csv"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $sourceRoot -Force | Out-Null

    $manifestRows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 10; $i++) {
        $manifestRows.Add([pscustomobject]@{
            sample_id = ("sample-{0:000}" -f $i)
            slot_type = "TBD"
            file_path = "TBD"
            document_title = "TBD"
            document_version = "TBD"
            owner = "TBD"
            is_scanned = "TBD"
            has_tables = "TBD"
            has_multicolumn = "TBD"
            confidentiality = "TBD"
            status = "TBD"
            notes = "TBD"
        }) | Out-Null
    }
    $manifestRows | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding UTF8

    $documentRows = New-Object System.Collections.Generic.List[object]
    for ($i = 1; $i -le 10; $i++) {
        $extension = if ($i -eq 10) { ".docx" } else { ".pdf" }
        $sourcePath = Join-Path $sourceRoot (("source-{0:00}" -f $i) + $extension)
        Set-Content -LiteralPath $sourcePath -Value ("smoke source document {0}" -f $i) -Encoding UTF8

        $documentRows.Add([pscustomobject]@{
            candidate_id = ("doc-smoke-{0:00}" -f $i)
            slot_type = "QNX adaptation smoke"
            source_location = $sourcePath
            document_title = ("Smoke Document {0:00}" -f $i)
            document_version = "v1.0"
            owner = "smoke-owner"
            is_scanned = if ($i -eq 3) { "yes" } else { "no" }
            has_tables = if ($i -eq 2 -or $i -eq 8) { "yes" } else { "no" }
            has_multicolumn = if ($i -eq 4) { "yes" } else { "no" }
            confidentiality = "internal"
            allowed_for_experiment = "yes"
            candidate_reason = "Covers document apply smoke readiness."
            notes = "temporary smoke input"
        }) | Out-Null
    }
    $documentRows | Export-Csv -LiteralPath $documentIntakePath -NoTypeInformation -Encoding UTF8

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "DOCUMENT_INTAKE=$documentIntakePath"
    Write-Host "RAW_DIR=$rawDir"
    Write-Host "MANIFEST=$manifestPath"

    & powershell -ExecutionPolicy Bypass -File $ApplyScript -Apply -Force -DocumentIntakePath $documentIntakePath -RawDir $rawDir -ManifestPath $manifestPath
    $applyExitCode = $LASTEXITCODE
    if ($applyExitCode -ne 0) {
        $failureMessage = "Document intake apply smoke failed with exit code $applyExitCode."
    }
    else {
        $copiedDocs = @(Get-ChildItem -LiteralPath $rawDir -File -Recurse | Where-Object { @(".pdf", ".docx", ".doc", ".html", ".htm") -contains $_.Extension.ToLowerInvariant() })
        $appliedManifestRows = @(Import-Csv -LiteralPath $manifestPath -Encoding UTF8)
        $readyManifestRows = @($appliedManifestRows | Where-Object { $_.status -eq "ready" -and $_.file_path -ne "TBD" })

        if ($copiedDocs.Count -ne 10) {
            $failureMessage = "Expected 10 copied sample documents, found $($copiedDocs.Count)."
        }
        elseif ($readyManifestRows.Count -ne 10) {
            $failureMessage = "Expected 10 ready manifest rows, found $($readyManifestRows.Count)."
        }
        else {
            Write-Host "DOCUMENT_INTAKE_TO_SAMPLES_SMOKE=PASS"
        }
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
    Write-Host "DOCUMENT_INTAKE_TO_SAMPLES_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
