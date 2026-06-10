param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$ExportScript = Join-Path $PSScriptRoot "export-owner-package.ps1"
$ReadinessScript = Join-Path $PSScriptRoot "check-owner-package-readiness.ps1"

if (-not (Test-Path -LiteralPath $ExportScript -PathType Leaf)) {
    Write-Error "Missing owner package export script: $ExportScript"
}
if (-not (Test-Path -LiteralPath $ReadinessScript -PathType Leaf)) {
    Write-Error "Missing owner package readiness script: $ReadinessScript"
}
if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-owner-package-readiness-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$packageDir = Join-Path $smokeRoot "package"
$zipPath = Join-Path $smokeRoot "package.zip"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "PACKAGE_DIR=$packageDir"
    Write-Host "ZIP_PATH=$zipPath"

    & powershell -ExecutionPolicy Bypass -File $ExportScript -OutputDir $packageDir -CreateZip -ZipPath $zipPath -Force
    $exportExitCode = $LASTEXITCODE
    if ($exportExitCode -ne 0) {
        $failureMessage = "Owner package export failed with exit code $exportExitCode."
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        & powershell -ExecutionPolicy Bypass -File $ReadinessScript -PackagePath $packageDir -Strict
        $dirReadinessExitCode = $LASTEXITCODE
        if ($dirReadinessExitCode -ne 0) {
            $failureMessage = "Owner package directory readiness failed with exit code $dirReadinessExitCode."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        & powershell -ExecutionPolicy Bypass -File $ReadinessScript -PackagePath $zipPath -Strict
        $zipReadinessExitCode = $LASTEXITCODE
        if ($zipReadinessExitCode -ne 0) {
            $failureMessage = "Owner package zip readiness failed with exit code $zipReadinessExitCode."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        Remove-Item -LiteralPath (Join-Path $packageDir "OWNER_MESSAGE.txt") -Force

        $brokenOutputPath = Join-Path $smokeRoot "broken-readiness-output.txt"
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & powershell -ExecutionPolicy Bypass -File $ReadinessScript -PackagePath $packageDir -Strict *> $brokenOutputPath
            $brokenExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }

        $brokenOutput = Get-Content -LiteralPath $brokenOutputPath -Raw -Encoding UTF8
        if ($brokenExitCode -eq 0) {
            $failureMessage = "Broken owner package readiness should fail in strict mode."
        }
        elseif ($brokenOutput -notlike "*OWNER_PACKAGE_INCOMPLETE*") {
            $failureMessage = "Broken owner package readiness did not report OWNER_PACKAGE_INCOMPLETE."
        }
        elseif ($brokenOutput -notlike "*OWNER_MESSAGE.txt*") {
            $failureMessage = "Broken owner package readiness did not identify the missing OWNER_MESSAGE.txt."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        Write-Host "OWNER_PACKAGE_READINESS_SMOKE=PASS"
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
    Write-Host "OWNER_PACKAGE_READINESS_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
