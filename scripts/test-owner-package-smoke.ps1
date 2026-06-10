param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ExportScript = Join-Path $PSScriptRoot "export-owner-package.ps1"
if (-not (Test-Path -LiteralPath $ExportScript)) {
    Write-Error "Missing export script: $ExportScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-owner-package-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$packageDir = Join-Path $smokeRoot "package"
$zipPath = Join-Path $smokeRoot "package.zip"
$trackerPath = Join-Path $smokeRoot "owner-response-tracker.csv"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null

    $trackerRows = @(
        [pscustomobject]@{
            owner = "placeholder"
            module = "QNX adaptation"
            request_sent_date = ""
            due_date = ""
            requested_documents = "0"
            provided_documents = "0"
            requested_tasks = "0"
            provided_tasks = "0"
            document_intake_updated = "no"
            task_intake_updated = "no"
            current_status = "not_sent"
            blocker = ""
            next_follow_up = ""
            notes = "smoke seed"
        }
    )
    $trackerRows | Export-Csv -LiteralPath $trackerPath -NoTypeInformation -Encoding UTF8

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "PACKAGE_DIR=$packageDir"
    Write-Host "ZIP_PATH=$zipPath"
    Write-Host "TRACKER_PATH=$trackerPath"

    & powershell -ExecutionPolicy Bypass -File $ExportScript -OutputDir $packageDir -CreateZip -ZipPath $zipPath -UpdateTracker -TrackerPath $trackerPath -Owner "smoke-owner" -Module "QNX adaptation"
    $exportExitCode = $LASTEXITCODE
    if ($exportExitCode -ne 0) {
        $failureMessage = "Owner package export failed with exit code $exportExitCode."
    }
    else {
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
            $path = Join-Path $packageDir $relativePath
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
                $failureMessage = "Missing package file: $relativePath"
                break
            }
        }

        if ([string]::IsNullOrWhiteSpace($failureMessage) -and -not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
            $failureMessage = "Missing package zip: $zipPath"
        }

        if ([string]::IsNullOrWhiteSpace($failureMessage)) {
            $docFiles = @(Get-ChildItem -LiteralPath (Join-Path $packageDir "docs") -File -ErrorAction SilentlyContinue)
            if ($docFiles.Count -lt 4) {
                $failureMessage = "Expected at least 4 packaged docs, found $($docFiles.Count)."
            }
        }

        if ([string]::IsNullOrWhiteSpace($failureMessage)) {
            $readme = Get-Content -LiteralPath (Join-Path $packageDir "OWNER_README.md") -Raw -Encoding UTF8
            foreach ($term in @("document-intake-template.csv", "task-intake-template.csv", "check-intake-readiness.ps1")) {
                if ($readme -notlike "*$term*") {
                    $failureMessage = "OWNER_README.md missing term: $term"
                    break
                }
            }
        }

        if ([string]::IsNullOrWhiteSpace($failureMessage)) {
            $readme = Get-Content -LiteralPath (Join-Path $packageDir "OWNER_README.md") -Raw -Encoding UTF8
            $expectedReadinessCommand = Join-Path $ProjectRoot "scripts\check-intake-readiness.ps1"
            if ($readme -notlike "*$expectedReadinessCommand*") {
                $failureMessage = "OWNER_README.md should include the project-local readiness command path."
            }
            elseif ($readme -like "*<legacy-project-root>*") {
                $failureMessage = "OWNER_README.md contains stale placeholder project path."
            }
        }

        if ([string]::IsNullOrWhiteSpace($failureMessage)) {
            $checklist = Get-Content -LiteralPath (Join-Path $packageDir "OWNER_CHECKLIST.md") -Raw -Encoding UTF8
            foreach ($term in @("gold_answer_points", "expected_evidence", "READY_TO_CREATE_EXPERIMENT_RUN", "check-intake-readiness.ps1")) {
                if ($checklist -notlike "*$term*") {
                    $failureMessage = "OWNER_CHECKLIST.md missing term: $term"
                    break
                }
            }
        }

        if ([string]::IsNullOrWhiteSpace($failureMessage)) {
            $manifestRows = @(Import-Csv -LiteralPath (Join-Path $packageDir "owner-package-manifest.csv") -Encoding UTF8)
            if ($manifestRows.Count -lt 12) {
                $failureMessage = "Expected at least 12 manifest rows, found $($manifestRows.Count)."
            }
        }

        if ([string]::IsNullOrWhiteSpace($failureMessage)) {
            $updatedTrackerRows = @(Import-Csv -LiteralPath $trackerPath -Encoding UTF8)
            $sentRows = @($updatedTrackerRows | Where-Object { $_.owner -eq "smoke-owner" -and $_.current_status -eq "sent" })
            if ($sentRows.Count -ne 1) {
                $failureMessage = "Expected one sent tracker row for smoke-owner, found $($sentRows.Count)."
            }
        }

        if ([string]::IsNullOrWhiteSpace($failureMessage)) {
            Write-Host "OWNER_PACKAGE_SMOKE=PASS"
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
    Write-Host "OWNER_PACKAGE_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
