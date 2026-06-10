param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$InitScript = Join-Path $PSScriptRoot "initialize-agent-prompts-from-tasks.ps1"
if (-not (Test-Path -LiteralPath $InitScript)) {
    Write-Error "Missing prompt initialization script: $InitScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-prompt-init-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$runDir = Join-Path $smokeRoot "run"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null

    @(
        [pscustomobject]@{ task_id = "task-smoke-001"; task_type = "constraint_lookup"; domain = "QNX adaptation"; task_description = "Find constraints."; allowed_documents = "doc-001;doc-002"; gold_answer_points = "secret-gold-constraint"; required_constraints = "secret-required-constraint"; expected_evidence = "secret-evidence"; scorer = "scorer"; owner = "owner"; status = "ready"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-002"; task_type = "interface_lookup"; domain = "QNX adaptation"; task_description = "Find interface."; allowed_documents = "doc-003"; gold_answer_points = "secret-gold-interface"; required_constraints = "secret-required-interface"; expected_evidence = "secret-evidence"; scorer = "scorer"; owner = "owner"; status = "ready"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-003"; task_type = "test_focus"; domain = "QNX adaptation"; task_description = "Find tests."; allowed_documents = "doc-002;doc-010"; gold_answer_points = "secret-gold-tests"; required_constraints = "secret-required-tests"; expected_evidence = "secret-evidence"; scorer = "scorer"; owner = "owner"; status = "ready"; notes = "smoke" }
    ) | Export-Csv -LiteralPath (Join-Path $runDir "agent-task-cases.csv") -NoTypeInformation -Encoding UTF8

    @(
        [pscustomobject]@{ task_id = "task-smoke-001"; task_type = "constraint_lookup"; real_source = "review"; monthly_frequency = "8"; has_gold_answer = "yes"; needs_evidence = "yes"; owner = "owner"; selected = "yes"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-002"; task_type = "interface_lookup"; real_source = "task"; monthly_frequency = "6"; has_gold_answer = "yes"; needs_evidence = "yes"; owner = "owner"; selected = "yes"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-003"; task_type = "test_focus"; real_source = "omission"; monthly_frequency = "5"; has_gold_answer = "yes"; needs_evidence = "yes"; owner = "owner"; selected = "yes"; notes = "smoke" }
    ) | Export-Csv -LiteralPath (Join-Path $runDir "scenario-selection-matrix.csv") -NoTypeInformation -Encoding UTF8

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "RUN_DIR=$runDir"

    & powershell -ExecutionPolicy Bypass -File $InitScript -ExperimentDir $runDir
    $dryRunExitCode = $LASTEXITCODE
    if ($dryRunExitCode -ne 0) {
        $failureMessage = "Prompt initialization dry run failed with exit code $dryRunExitCode."
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        & powershell -ExecutionPolicy Bypass -File $InitScript -ExperimentDir $runDir -Apply
        $applyExitCode = $LASTEXITCODE
        if ($applyExitCode -ne 0) {
            $failureMessage = "Prompt initialization apply failed with exit code $applyExitCode."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        $manifestPath = Join-Path $runDir "agent-prompt-manifest.csv"
        $manifestRows = @(Import-Csv -LiteralPath $manifestPath -Encoding UTF8)
        $promptFiles = @(Get-ChildItem -LiteralPath (Join-Path $runDir "prompts") -File -Recurse)
        if ($manifestRows.Count -ne 6) {
            $failureMessage = "Expected 6 prompt manifest rows, found $($manifestRows.Count)."
        }
        elseif ($promptFiles.Count -ne 6) {
            $failureMessage = "Expected 6 prompt files, found $($promptFiles.Count)."
        }
        else {
            foreach ($file in $promptFiles) {
                $text = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8
                foreach ($forbidden in @("secret-gold", "secret-required", "secret-evidence")) {
                    if ($text -like "*$forbidden*") {
                        $failureMessage = "Prompt leaked scorer-only field '$forbidden' in $($file.FullName)."
                        break
                    }
                }

                if (-not [string]::IsNullOrWhiteSpace($failureMessage)) {
                    break
                }
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        Write-Host "AGENT_PROMPT_INITIALIZATION_SMOKE=PASS"
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
    Write-Host "AGENT_PROMPT_INITIALIZATION_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
