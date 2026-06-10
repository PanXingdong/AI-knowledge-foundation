param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$InitScript = Join-Path $PSScriptRoot "initialize-agent-run-log-from-tasks.ps1"
if (-not (Test-Path -LiteralPath $InitScript)) {
    Write-Error "Missing agent run-log initialization script: $InitScript"
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

$smokeRoot = Join-Path $ArtifactRoot ("akh-run-log-init-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$runDir = Join-Path $smokeRoot "run"
$failureMessage = $null

try {
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null

    @(
        [pscustomobject]@{ task_id = "task-smoke-001"; task_type = "constraint_lookup"; domain = "QNX adaptation"; task_description = "Find constraints."; allowed_documents = "doc-001;doc-002"; gold_answer_points = "constraint"; required_constraints = "constraint"; expected_evidence = "page span"; scorer = "scorer-a"; owner = "owner"; status = "ready"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-002"; task_type = "interface_lookup"; domain = "QNX adaptation"; task_description = "Find interface."; allowed_documents = "doc-003"; gold_answer_points = "interface"; required_constraints = "limit"; expected_evidence = "page span"; scorer = "scorer-b"; owner = "owner"; status = "ready"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-003"; task_type = "test_focus"; domain = "QNX adaptation"; task_description = "Find tests."; allowed_documents = "doc-002;doc-010"; gold_answer_points = "tests"; required_constraints = "coverage"; expected_evidence = "page span"; scorer = "scorer-c"; owner = "owner"; status = "ready"; notes = "smoke" }
    ) | Export-Csv -LiteralPath (Join-Path $runDir "agent-task-cases.csv") -NoTypeInformation -Encoding UTF8

    @(
        [pscustomobject]@{ task_id = "task-smoke-001"; task_type = "constraint_lookup"; real_source = "review"; monthly_frequency = "8"; has_gold_answer = "yes"; needs_evidence = "yes"; owner = "owner"; selected = "yes"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-002"; task_type = "interface_lookup"; real_source = "task"; monthly_frequency = "6"; has_gold_answer = "yes"; needs_evidence = "yes"; owner = "owner"; selected = "yes"; notes = "smoke" },
        [pscustomobject]@{ task_id = "task-smoke-003"; task_type = "test_focus"; real_source = "omission"; monthly_frequency = "5"; has_gold_answer = "yes"; needs_evidence = "yes"; owner = "owner"; selected = "yes"; notes = "smoke" }
    ) | Export-Csv -LiteralPath (Join-Path $runDir "scenario-selection-matrix.csv") -NoTypeInformation -Encoding UTF8

    $promptRows = New-Object System.Collections.Generic.List[object]
    foreach ($taskId in @("task-smoke-001", "task-smoke-002", "task-smoke-003")) {
        $promptRows.Add([pscustomobject]@{
            task_id = $taskId
            group = "baseline"
            prompt_path = "prompts\baseline\$taskId.md"
            context_source = "raw_files"
            source_docs = "doc-001;doc-002"
            notes = "smoke"
        }) | Out-Null
        $promptRows.Add([pscustomobject]@{
            task_id = $taskId
            group = "context_pack"
            prompt_path = "prompts\context_pack\$taskId.md"
            context_source = "context_pack"
            source_docs = "context_pack"
            notes = "smoke"
        }) | Out-Null
    }
    $promptRows | Export-Csv -LiteralPath (Join-Path $runDir "agent-prompt-manifest.csv") -NoTypeInformation -Encoding UTF8

    @(
        [pscustomobject]@{
            run_id = "placeholder"
            task_id = "placeholder"
            group = "baseline"
            attempt = "1"
            agent = "TBD"
            model = "TBD"
            context_source = "raw_files"
            source_docs = "TBD"
            context_pack_id = "N/A"
            prompt_path = "TBD"
            started_at = "TBD"
            ended_at = "TBD"
            token_input = "TBD"
            token_output = "TBD"
            elapsed_minutes = "TBD"
            raw_output_path = "TBD"
            scorer = "TBD"
            score_status = "pending"
            notes = "placeholder"
        }
    ) | Export-Csv -LiteralPath (Join-Path $runDir "agent-run-log.csv") -NoTypeInformation -Encoding UTF8

    Write-Host "SMOKE_ROOT=$smokeRoot"
    Write-Host "RUN_DIR=$runDir"

    & powershell -ExecutionPolicy Bypass -File $InitScript -ExperimentDir $runDir
    $dryRunExitCode = $LASTEXITCODE
    if ($dryRunExitCode -ne 0) {
        $failureMessage = "Agent run-log initialization dry run failed with exit code $dryRunExitCode."
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        & powershell -ExecutionPolicy Bypass -File $InitScript -ExperimentDir $runDir -Apply
        $applyExitCode = $LASTEXITCODE
        if ($applyExitCode -ne 0) {
            $failureMessage = "Agent run-log initialization apply failed with exit code $applyExitCode."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        $runLogPath = Join-Path $runDir "agent-run-log.csv"
        $rawOutputDir = Join-Path $runDir "raw-outputs"
        $rows = @(Import-Csv -LiteralPath $runLogPath -Encoding UTF8)
        $baselineRows = @($rows | Where-Object { $_.group -eq "baseline" })
        $contextRows = @($rows | Where-Object { $_.group -eq "context_pack" })
        $rawOutputFiles = @()
        if (Test-Path -LiteralPath $rawOutputDir) {
            $rawOutputFiles = @(Get-ChildItem -LiteralPath $rawOutputDir -File -Recurse -ErrorAction SilentlyContinue)
        }

        if ($rows.Count -ne 6) {
            $failureMessage = "Expected 6 initialized run-log rows, found $($rows.Count)."
        }
        elseif ($baselineRows.Count -ne 3 -or $contextRows.Count -ne 3) {
            $failureMessage = "Expected 3 baseline and 3 context_pack run-log rows, found baseline=$($baselineRows.Count), context_pack=$($contextRows.Count)."
        }
        elseif (-not (Test-Path -LiteralPath $rawOutputDir -PathType Container)) {
            $failureMessage = "Expected raw-outputs directory to be created."
        }
        elseif ($rawOutputFiles.Count -ne 0) {
            $failureMessage = "Run-log initialization must not create fake raw Agent outputs."
        }
        elseif (@($rows | Where-Object { $_.score_status -ne "pending" }).Count -gt 0) {
            $failureMessage = "Initialized run-log rows should be pending."
        }
        elseif (@($rows | Where-Object { $_.raw_output_path -notlike "raw-outputs\*.md" }).Count -gt 0) {
            $failureMessage = "Initialized run-log rows should point to planned raw-outputs/*.md paths."
        }
        elseif (@($rows | Where-Object { $_.started_at -ne "TBD" -or $_.model -ne "TBD" }).Count -gt 0) {
            $failureMessage = "Initialized run-log rows should not contain real execution metadata."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        $rawOutputDir = Join-Path $runDir "raw-outputs"
        $realOutput = Join-Path $rawOutputDir "task-smoke-001-baseline.md"
        Set-Content -LiteralPath $realOutput -Value "real smoke output" -Encoding UTF8

        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & powershell -ExecutionPolicy Bypass -File $InitScript -ExperimentDir $runDir -Apply *> $null
            $overwriteExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($overwriteExitCode -eq 0) {
            $failureMessage = "Agent run-log initialization should refuse to overwrite when raw execution output exists without -Force."
        }
    }

    if ([string]::IsNullOrWhiteSpace($failureMessage)) {
        Write-Host "AGENT_RUN_LOG_INITIALIZATION_SMOKE=PASS"
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
    Write-Host "AGENT_RUN_LOG_INITIALIZATION_SMOKE=FAIL"
    Write-Host "ERROR=$failureMessage"
    exit 1
}

exit 0
