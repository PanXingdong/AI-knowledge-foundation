param(
    [Parameter(Mandatory = $true)]
    [string]$PackagePath,
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$Strict,
    [switch]$KeepExtracted
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Resolve-ProjectPath {
    param([string]$Value)

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    return Join-Path $ProjectRoot $Value
}

function Add-Check {
    param(
        [System.Collections.Generic.List[object]]$Checks,
        [ValidateSet("PASS", "FAIL")]
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

function Test-File {
    param(
        [System.Collections.Generic.List[object]]$Checks,
        [string]$PackageRoot,
        [string]$RelativePath
    )

    $path = Join-Path $PackageRoot $RelativePath
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Add-Check $Checks "PASS" "Required file: $RelativePath" "Found."
        return $true
    }

    Add-Check $Checks "FAIL" "Required file: $RelativePath" "Missing."
    return $false
}

function Import-CsvChecked {
    param(
        [System.Collections.Generic.List[object]]$Checks,
        [string]$Path,
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Add-Check $Checks "FAIL" $Name "Missing file: $Path"
        return @()
    }

    try {
        $rows = @(Import-Csv -LiteralPath $Path -Encoding UTF8)
        Add-Check $Checks "PASS" $Name "CSV parsed, rows: $($rows.Count)"
        return @($rows)
    }
    catch {
        Add-Check $Checks "FAIL" $Name "CSV parse failed: $($_.Exception.Message)"
        return @()
    }
}

function Test-Columns {
    param(
        [System.Collections.Generic.List[object]]$Checks,
        [object[]]$Rows,
        [string[]]$RequiredColumns,
        [string]$Name
    )

    if ($Rows.Count -eq 0) {
        Add-Check $Checks "FAIL" $Name "No rows to inspect."
        return
    }

    $columns = @($Rows[0].PSObject.Properties.Name)
    $missing = @($RequiredColumns | Where-Object { $_ -notin $columns })
    if ($missing.Count -eq 0) {
        Add-Check $Checks "PASS" $Name "All required columns found."
    }
    else {
        Add-Check $Checks "FAIL" $Name "Missing columns: $($missing -join ', ')"
    }
}

function Test-TextTerms {
    param(
        [System.Collections.Generic.List[object]]$Checks,
        [string]$Path,
        [string[]]$RequiredTerms,
        [string[]]$ForbiddenTerms,
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Add-Check $Checks "FAIL" $Name "Missing file: $Path"
        return
    }

    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $missing = @($RequiredTerms | Where-Object { $text -notlike "*$_*" })
    $forbidden = @($ForbiddenTerms | Where-Object { $text -like "*$_*" })

    if ($missing.Count -eq 0 -and $forbidden.Count -eq 0) {
        Add-Check $Checks "PASS" $Name "Required terms present and forbidden terms absent."
    }
    else {
        $details = @()
        if ($missing.Count -gt 0) {
            $details += "missing: $($missing -join ', ')"
        }
        if ($forbidden.Count -gt 0) {
            $details += "forbidden: $($forbidden -join ', ')"
        }
        Add-Check $Checks "FAIL" $Name ($details -join '; ')
    }
}

$PackagePath = Resolve-ProjectPath $PackagePath
if (-not (Test-Path -LiteralPath $PackagePath)) {
    Write-Error "Owner package path not found: $PackagePath"
}

$extractedRoot = $null
$packageRoot = $PackagePath
if ((Test-Path -LiteralPath $PackagePath -PathType Leaf) -and ([System.IO.Path]::GetExtension($PackagePath).ToLowerInvariant() -eq ".zip")) {
    if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
        New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
    }

    $extractedRoot = Join-Path $ArtifactRoot ("akh-owner-package-check-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff") + "-" + ([System.Guid]::NewGuid().ToString("N")))
    New-Item -ItemType Directory -Path $extractedRoot -Force | Out-Null
    Expand-Archive -LiteralPath $PackagePath -DestinationPath $extractedRoot -Force
    $packageRoot = $extractedRoot
}
elseif (-not (Test-Path -LiteralPath $PackagePath -PathType Container)) {
    Write-Error "PackagePath must be a directory or .zip file: $PackagePath"
}

try {
    $checks = New-Object System.Collections.Generic.List[object]

    $requiredFiles = @(
        "OWNER_README.md",
        "OWNER_MESSAGE.txt",
        "OWNER_CHECKLIST.md",
        "owner-package-manifest.csv",
        "samples\document-intake-template.csv",
        "samples\document-intake-example.csv",
        "samples\owner-response-tracker.csv",
        "experiments\templates\task-intake-template.csv",
        "experiments\templates\task-intake-example.csv"
    )

    foreach ($relativePath in $requiredFiles) {
        [void](Test-File $checks $packageRoot $relativePath)
    }

    $docsPath = Join-Path $packageRoot "docs"
    $docFiles = @()
    if (Test-Path -LiteralPath $docsPath -PathType Container) {
        $docFiles = @(Get-ChildItem -LiteralPath $docsPath -File -ErrorAction SilentlyContinue)
    }
    if ($docFiles.Count -ge 5) {
        Add-Check $checks "PASS" "Packaged docs" "Docs found: $($docFiles.Count)"
    }
    else {
        Add-Check $checks "FAIL" "Packaged docs" "Expected at least 5 docs, found $($docFiles.Count)."
    }

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

    $requiredTrackerColumns = @(
        "owner",
        "module",
        "request_sent_date",
        "due_date",
        "requested_documents",
        "provided_documents",
        "requested_tasks",
        "provided_tasks",
        "document_intake_updated",
        "task_intake_updated",
        "current_status",
        "blocker",
        "next_follow_up",
        "notes"
    )

    $documentRows = Import-CsvChecked $checks (Join-Path $packageRoot "samples\document-intake-template.csv") "Document intake template"
    $documentExampleRows = Import-CsvChecked $checks (Join-Path $packageRoot "samples\document-intake-example.csv") "Document intake example"
    $trackerRows = Import-CsvChecked $checks (Join-Path $packageRoot "samples\owner-response-tracker.csv") "Owner response tracker"
    $taskRows = Import-CsvChecked $checks (Join-Path $packageRoot "experiments\templates\task-intake-template.csv") "Task intake template"
    $taskExampleRows = Import-CsvChecked $checks (Join-Path $packageRoot "experiments\templates\task-intake-example.csv") "Task intake example"
    $manifestRows = Import-CsvChecked $checks (Join-Path $packageRoot "owner-package-manifest.csv") "Owner package manifest"

    Test-Columns $checks $documentRows $requiredDocumentColumns "Document intake columns"
    Test-Columns $checks $documentExampleRows $requiredDocumentColumns "Document intake example columns"
    Test-Columns $checks $trackerRows $requiredTrackerColumns "Owner tracker columns"
    Test-Columns $checks $taskRows $requiredTaskColumns "Task intake columns"
    Test-Columns $checks $taskExampleRows $requiredTaskColumns "Task intake example columns"
    Test-Columns $checks $manifestRows @("source", "package_path") "Owner package manifest columns"

    if ($manifestRows.Count -gt 0) {
        $missingManifestTargets = @()
        foreach ($row in $manifestRows) {
            $manifestPackagePath = [string]$row.package_path
            if ([string]::IsNullOrWhiteSpace($manifestPackagePath)) {
                continue
            }

            if (-not (Test-Path -LiteralPath (Join-Path $packageRoot $manifestPackagePath) -PathType Leaf)) {
                $missingManifestTargets += $manifestPackagePath
            }
        }

        if ($missingManifestTargets.Count -eq 0) {
            Add-Check $checks "PASS" "Owner package manifest targets" "All manifest package_path files exist."
        }
        else {
            Add-Check $checks "FAIL" "Owner package manifest targets" "Missing package_path files: $($missingManifestTargets -join ', ')"
        }
    }

    $readinessPath = Join-Path $ProjectRoot "scripts\check-intake-readiness.ps1"
    Test-TextTerms `
        -Checks $checks `
        -Path (Join-Path $packageRoot "OWNER_README.md") `
        -RequiredTerms @("document-intake-template.csv", "task-intake-template.csv", "check-intake-readiness.ps1", $readinessPath) `
        -ForbiddenTerms @("<legacy-project-root>") `
        -Name "OWNER_README content"

    Test-TextTerms `
        -Checks $checks `
        -Path (Join-Path $packageRoot "OWNER_MESSAGE.txt") `
        -RequiredTerms @("structured document retrieval plus Context Pack", "document-intake-template.csv", "task-intake-template.csv", "Do not design graph schema") `
        -ForbiddenTerms @("<legacy-project-root>") `
        -Name "OWNER_MESSAGE content"

    Test-TextTerms `
        -Checks $checks `
        -Path (Join-Path $packageRoot "OWNER_CHECKLIST.md") `
        -RequiredTerms @("gold_answer_points", "expected_evidence", "READY_TO_CREATE_EXPERIMENT_RUN", "check-intake-readiness.ps1") `
        -ForbiddenTerms @("<legacy-project-root>") `
        -Name "OWNER_CHECKLIST content"

    Write-Host "Agent Knowledge Hub owner package readiness"
    Write-Host "Package path: $PackagePath"
    Write-Host "Package root: $packageRoot"
    Write-Host ""

    $checks | Sort-Object @{Expression = {
        switch ($_.Status) {
            "FAIL" { 0 }
            "PASS" { 1 }
        }
    }}, Name | Format-Table -AutoSize

    $failCount = @($checks | Where-Object { $_.Status -eq "FAIL" }).Count
    $passCount = @($checks | Where-Object { $_.Status -eq "PASS" }).Count
    $overall = if ($failCount -eq 0) { "OWNER_PACKAGE_READY" } else { "OWNER_PACKAGE_INCOMPLETE" }

    Write-Host ""
    Write-Host "Summary: PASS=$passCount FAIL=$failCount"
    Write-Host "Overall: $overall"

    if ($Strict -and $overall -ne "OWNER_PACKAGE_READY") {
        exit 1
    }
}
finally {
    if ($null -ne $extractedRoot -and -not $KeepExtracted -and (Test-Path -LiteralPath $extractedRoot)) {
        Remove-Item -LiteralPath $extractedRoot -Recurse -Force
        Write-Host "EXTRACTED_PACKAGE_CLEANED=$extractedRoot"
    }
    elseif ($null -ne $extractedRoot -and $KeepExtracted) {
        Write-Host "EXTRACTED_PACKAGE_KEPT=$extractedRoot"
    }
}

exit 0
