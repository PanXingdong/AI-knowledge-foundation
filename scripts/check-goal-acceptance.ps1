param(
    [string]$ExperimentDir,
    [string]$SampleManifestPath,
    [string]$SampleRawDir,
    [string]$ReportPath,
    [switch]$RequireRealInputs,
    [switch]$RequireExperimentResults
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Resolve-InputPath {
    param(
        [string]$Value,
        [string]$DefaultRelativePath
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return Join-Path $ProjectRoot $DefaultRelativePath
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    return Join-Path $ProjectRoot $Value
}

function New-TextFromCodePoints {
    param([int[]]$CodePoints)

    return -join ($CodePoints | ForEach-Object { [char]$_ })
}

$ExperimentDir = Resolve-InputPath $ExperimentDir "experiments\templates"
$SampleManifestPath = Resolve-InputPath $SampleManifestPath "samples\sample-manifest.csv"
$SampleRawDir = Resolve-InputPath $SampleRawDir "samples\raw"

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

$AffirmativeTerms = @(
    "1",
    "true",
    "yes",
    "y",
    "selected",
    "select",
    "ok",
    "pass",
    (New-TextFromCodePoints @(0x662F)),
    (New-TextFromCodePoints @(0x6709)),
    (New-TextFromCodePoints @(0x5DF2, 0x9009)),
    (New-TextFromCodePoints @(0x9009, 0x4E2D))
)

$SupportedDocExtensions = @(".pdf", ".docx", ".doc", ".html", ".htm")

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

function Test-Affirmative {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $false
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    foreach ($term in $AffirmativeTerms) {
        if ($normalized -eq $term.ToLowerInvariant()) {
            return $true
        }
    }

    return $false
}

function Resolve-ProjectPath {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    return Join-Path $ProjectRoot $Value
}

function Resolve-ExperimentPath {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    return Join-Path $ExperimentDir $Value
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

function Import-CsvOrEmpty {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }

    return @(Import-Csv -LiteralPath $Path -Encoding UTF8)
}

function Get-FirstProjectMatch {
    param([string]$Pattern)

    $path = Join-Path $ProjectRoot $Pattern
    $items = @(Get-ChildItem -Path $path -Force -ErrorAction SilentlyContinue)
    if ($items.Count -eq 0) {
        return $null
    }

    return $items[0].FullName
}

function Test-TextContainsAll {
    param(
        [string[]]$Paths,
        [string[]]$Terms
    )

    $texts = New-Object System.Collections.Generic.List[string]
    foreach ($path in $Paths) {
        if ($null -ne $path -and (Test-Path -LiteralPath $path)) {
            $texts.Add((Get-Content -LiteralPath $path -Raw -Encoding UTF8)) | Out-Null
        }
    }

    if ($texts.Count -eq 0) {
        return $false
    }

    foreach ($term in $Terms) {
        $found = $false
        foreach ($text in $texts) {
            if ($text -like "*$term*") {
                $found = $true
                break
            }
        }

        if (-not $found) {
            return $false
        }
    }

    return $true
}

function Test-ColumnsPresent {
    param(
        [object[]]$Rows,
        [string[]]$Columns
    )

    if ($Rows.Count -eq 0) {
        return $false
    }

    $actualColumns = @($Rows[0].PSObject.Properties.Name)
    foreach ($column in $Columns) {
        if ($column -notin $actualColumns) {
            return $false
        }
    }

    return $true
}

function Test-CompleteResultRow {
    param([pscustomobject]$Row)

    foreach ($field in @(
        "task_id",
        "group",
        "answer_correct",
        "missed_constraints",
        "wrong_claims",
        "citation_correct",
        "token_cost",
        "elapsed_minutes",
        "human_fix_count"
    )) {
        if (Test-Placeholder $Row.$field) {
            return $false
        }
    }

    return $true
}

function Test-CompleteAgentRunLogRow {
    param([pscustomobject]$Row)

    foreach ($field in @(
        "run_id",
        "task_id",
        "group",
        "attempt",
        "agent",
        "model",
        "context_source",
        "source_docs",
        "started_at",
        "ended_at",
        "raw_output_path",
        "scorer",
        "score_status"
    )) {
        if (Test-Placeholder $Row.$field) {
            return $false
        }
    }

    $rawOutputPath = Resolve-ExperimentPath $Row.raw_output_path
    if ($null -eq $rawOutputPath -or -not (Test-Path -LiteralPath $rawOutputPath -PathType Leaf)) {
        return $false
    }

    return $true
}

function New-Status {
    param([bool]$Ready)

    if ($Ready) {
        return "READY"
    }

    return "MISSING"
}

function New-VerificationStatus {
    param([bool]$Ready)

    if ($Ready) {
        return "VERIFIED"
    }

    return "PENDING"
}

function Add-AcceptanceCheck {
    param(
        [string]$Id,
        [string]$Criterion,
        [bool]$DefinitionReady,
        [bool]$VerificationReady,
        [string]$Evidence,
        [string]$Missing
    )

    $script:Checks.Add([pscustomobject]@{
        Id = $Id
        Criterion = $Criterion
        DefinitionStatus = New-Status $DefinitionReady
        VerificationStatus = New-VerificationStatus $VerificationReady
        Evidence = $Evidence
        Missing = $Missing
    }) | Out-Null
}

$manifestRows = Import-CsvOrEmpty $SampleManifestPath
$parserRows = Import-CsvOrEmpty (Join-Path $ExperimentDir "parser-evaluation-sheet.csv")
$resultRows = Import-CsvOrEmpty (Join-Path $ExperimentDir "baseline-vs-contextpack-results.csv")
$agentRunLogRows = Import-CsvOrEmpty (Join-Path $ExperimentDir "agent-run-log.csv")
$taskCaseRows = Import-CsvOrEmpty (Join-Path $ExperimentDir "agent-task-cases.csv")
$scenarioRows = Import-CsvOrEmpty (Join-Path $ExperimentDir "scenario-selection-matrix.csv")

$rawDocs = @()
if (Test-Path -LiteralPath $SampleRawDir) {
    $rawDocs = @(Get-ChildItem -LiteralPath $SampleRawDir -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $SupportedDocExtensions -contains $_.Extension.ToLowerInvariant() })
}

$manifestRealRows = @(
    foreach ($row in $manifestRows) {
        $path = Resolve-ProjectPath $row.file_path
        if (
            -not (Test-Placeholder $row.file_path) -and
            -not (Test-Placeholder $row.document_title) -and
            -not (Test-Placeholder $row.document_version) -and
            -not (Test-Placeholder $row.owner) -and
            $null -ne $path -and
            (Test-Path -LiteralPath $path -PathType Leaf)
        ) {
            $row
        }
    }
)

$completeTaskCaseIds = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)
foreach ($row in $taskCaseRows) {
    $complete = $true
    foreach ($field in @(
        "task_id",
        "task_type",
        "domain",
        "task_description",
        "allowed_documents",
        "gold_answer_points",
        "required_constraints",
        "expected_evidence",
        "scorer",
        "owner"
    )) {
        if (Test-Placeholder $row.$field) {
            $complete = $false
            break
        }
    }

    if ($complete) {
        [void]$completeTaskCaseIds.Add($row.task_id)
    }
}

$selectedScenarioRows = @($scenarioRows | Where-Object { Test-Affirmative $_.selected })
$selectedCompleteTasks = @(
    foreach ($row in $selectedScenarioRows) {
        if ($completeTaskCaseIds.Contains($row.task_id)) {
            $row
        }
    }
)

$completeParserRows = @(
    foreach ($row in $parserRows) {
        $numericFields = @(
            (Convert-ToNumberMetric $row.page_metadata_rate),
            (Convert-ToNumberMetric $row.span_traceability_rate),
            (Convert-ToNumberMetric $row.table_accuracy),
            (Convert-ToNumberMetric $row.reading_order_accuracy),
            (Convert-ToNumberMetric $row.ocr_accuracy),
            (Convert-ToNumberMetric $row.parse_minutes),
            (Convert-ToNumberMetric $row.critical_failures)
        )

        $complete = $true
        foreach ($value in $numericFields) {
            if ($null -eq $value) {
                $complete = $false
                break
            }
        }

        if (
            $complete -and
            -not (Test-Placeholder $row.document_id) -and
            -not (Test-Placeholder $row.file_path) -and
            -not (Test-Placeholder $row.parser)
        ) {
            $row
        }
    }
)

$parserCoverage = @(
    $completeParserRows |
        Group-Object parser |
        ForEach-Object {
            [pscustomobject]@{
                Parser = $_.Name
                DistinctDocuments = @($_.Group | ForEach-Object { $_.document_id } | Select-Object -Unique).Count
            }
        }
)
$parsersCoveringTenDocs = @($parserCoverage | Where-Object { $_.DistinctDocuments -ge 10 }).Count

$completeResultRows = @($resultRows | Where-Object { Test-CompleteResultRow $_ })
$completeResultPairs = New-Object System.Collections.Generic.List[string]
foreach ($taskGroup in ($completeResultRows | Group-Object task_id)) {
    $baseline = @($taskGroup.Group | Where-Object { $_.group -eq "baseline" })
    $contextPack = @($taskGroup.Group | Where-Object { $_.group -eq "context_pack" })
    if ($baseline.Count -gt 0 -and $contextPack.Count -gt 0) {
        $completeResultPairs.Add($taskGroup.Name) | Out-Null
    }
}

$completeAgentRunLogRows = @($agentRunLogRows | Where-Object { Test-CompleteAgentRunLogRow $_ })
$completeAgentRunLogPairs = New-Object System.Collections.Generic.List[string]
foreach ($taskGroup in ($completeAgentRunLogRows | Group-Object task_id)) {
    $baseline = @($taskGroup.Group | Where-Object { $_.group -eq "baseline" })
    $contextPack = @($taskGroup.Group | Where-Object { $_.group -eq "context_pack" })
    if ($baseline.Count -gt 0 -and $contextPack.Count -gt 0) {
        $completeAgentRunLogPairs.Add($taskGroup.Name) | Out-Null
    }
}

$traceableResultPairs = @($completeResultPairs | Where-Object { $completeAgentRunLogPairs -contains $_ })

$readmePath = Join-Path $ProjectRoot "README.md"
$domainDocPath = Join-Path $ProjectRoot "docs\overview.md"
$agentAccessDocPath = Join-Path $ProjectRoot "docs\api-contract.md"
$experimentDocPath = Join-Path $ProjectRoot "docs\evaluation.md"
$metricsDocPath = Join-Path $ProjectRoot "docs\evaluation.md"
$runbookDocPath = Join-Path $ProjectRoot "docs\operations.md"
$phaseGateDocPath = Join-Path $ProjectRoot "docs\overview.md"
$goalEvidenceDocPath = Join-Path $ProjectRoot "docs\archive\05-evaluation\goal-acceptance-evidence-matrix.md"
$contextPackTemplatePath = Join-Path $ExperimentDir "context-pack-template.json"
$mixedEngineeringSampleTerm = New-TextFromCodePoints @(0x6DF7, 0x5408, 0x5DE5, 0x7A0B, 0x6587, 0x6863, 0x6837, 0x672C)

$sampleSlotsDefined = (
    $manifestRows.Count -ge 10 -and
    @($manifestRows | Where-Object { -not (Test-Placeholder $_.slot_type) }).Count -ge 10 -and
    (Test-TextContainsAll @($readmePath, $domainDocPath) @($mixedEngineeringSampleTerm))
)
$sampleDocsVerified = ($manifestRealRows.Count -ge 10 -and $rawDocs.Count -ge 10)

$baselineDefinitionReady = (
    (Test-TextContainsAll @($experimentDocPath, $metricsDocPath, $runbookDocPath) @("baseline")) -and
    (Test-ColumnsPresent $resultRows @(
        "task_id",
        "group",
        "answer_correct",
        "missed_constraints",
        "wrong_claims",
        "citation_correct",
        "token_cost",
        "elapsed_minutes"
    )) -and
    @($resultRows | Where-Object { $_.group -eq "baseline" }).Count -gt 0
)

$contextPackDefinitionReady = (
    (Test-TextContainsAll @($agentAccessDocPath, $experimentDocPath, $runbookDocPath) @("Context Pack")) -and
    (Test-Path -LiteralPath $contextPackTemplatePath) -and
    (Test-ColumnsPresent $resultRows @("task_id", "group", "context_pack_tokens", "retrieved_span_count")) -and
    @($resultRows | Where-Object { $_.group -eq "context_pack" }).Count -gt 0
)

$parserMetricsDefinitionReady = (
    (Test-ColumnsPresent $parserRows @(
        "page_metadata_rate",
        "span_traceability_rate",
        "table_accuracy",
        "reading_order_accuracy",
        "ocr_accuracy"
    )) -and
    (Test-TextContainsAll @($metricsDocPath) @(
        "page_metadata_rate",
        "span_traceability_rate",
        "table_accuracy",
        "reading_order_accuracy",
        "ocr_accuracy"
    ))
)

$agentMetricsDefinitionReady = (
    (Test-ColumnsPresent $resultRows @(
        "answer_correct",
        "missed_constraints",
        "token_cost",
        "elapsed_minutes",
        "citation_correct"
    )) -and
    (Test-TextContainsAll @($metricsDocPath) @(
        "answer_correct",
        "missed_constraints",
        "token_cost",
        "elapsed_minutes",
        "citation_correct"
    ))
)

$phaseBoundaryReady = (
    (Test-TextContainsAll @($readmePath, $phaseGateDocPath, $goalEvidenceDocPath) @(
        "Context Pack",
        "Core API",
        "local agent entry",
        (New-TextFromCodePoints @(0x77E5, 0x8BC6, 0x56FE, 0x8C31)),
        (New-TextFromCodePoints @(0x4EBA, 0x5DE5, 0x5BA1, 0x6838)),
        (New-TextFromCodePoints @(0x7248, 0x672C, 0x5931, 0x6548))
    ))
)

$Checks = New-Object System.Collections.Generic.List[object]

Add-AcceptanceCheck `
    -Id "1" `
    -Criterion "first_sample_scope_and_10_sample_documents" `
    -DefinitionReady $sampleSlotsDefined `
    -VerificationReady $sampleDocsVerified `
    -Evidence "scope=mixed_engineering_documents; manifest_rows=$($manifestRows.Count); defined_slots=$(@($manifestRows | Where-Object { -not (Test-Placeholder $_.slot_type) }).Count); real_manifest_rows=$($manifestRealRows.Count); raw_docs=$($rawDocs.Count)" `
    -Missing $(if ($sampleDocsVerified) { "" } else { "Need 10 reachable real documents with title, version, and owner." })

Add-AcceptanceCheck `
    -Id "2" `
    -Criterion "direct_file_baseline_test_defined" `
    -DefinitionReady $baselineDefinitionReady `
    -VerificationReady ($traceableResultPairs.Count -ge 3) `
    -Evidence "baseline_rows=$(@($resultRows | Where-Object { $_.group -eq 'baseline' }).Count); complete_pairs=$($completeResultPairs.Count)/3; traceable_pairs=$($traceableResultPairs.Count)/3" `
    -Missing $(if ($traceableResultPairs.Count -ge 3) { "" } else { "Need at least 3 real paired baseline/context_pack task results traceable to raw Agent outputs." })

Add-AcceptanceCheck `
    -Id "3" `
    -Criterion "context_pack_experiment_defined" `
    -DefinitionReady $contextPackDefinitionReady `
    -VerificationReady ($traceableResultPairs.Count -ge 3) `
    -Evidence "context_pack_template_exists=$(Test-Path -LiteralPath $contextPackTemplatePath); context_pack_rows=$(@($resultRows | Where-Object { $_.group -eq 'context_pack' }).Count); complete_pairs=$($completeResultPairs.Count)/3; traceable_pairs=$($traceableResultPairs.Count)/3" `
    -Missing $(if ($traceableResultPairs.Count -ge 3) { "" } else { "Need real Context Packs and at least 3 paired task results traceable to raw Agent outputs." })

Add-AcceptanceCheck `
    -Id "4" `
    -Criterion "parser_metrics_page_span_table_order_ocr_defined" `
    -DefinitionReady $parserMetricsDefinitionReady `
    -VerificationReady ($parsersCoveringTenDocs -ge 3) `
    -Evidence "complete_parser_rows=$($completeParserRows.Count); parsers_covering_10_docs=$parsersCoveringTenDocs/3" `
    -Missing $(if ($parsersCoveringTenDocs -ge 3) { "" } else { "Need Docling/MinerU/Unstructured scores over the same 10 real documents." })

Add-AcceptanceCheck `
    -Id "5" `
    -Criterion "agent_effect_metrics_accuracy_miss_token_time_evidence_defined" `
    -DefinitionReady $agentMetricsDefinitionReady `
    -VerificationReady ($traceableResultPairs.Count -ge 3) `
    -Evidence "complete_result_pairs=$($completeResultPairs.Count)/3; traceable_pairs=$($traceableResultPairs.Count)/3; selected_complete_tasks=$($selectedCompleteTasks.Count)/3" `
    -Missing $(if ($traceableResultPairs.Count -ge 3) { "" } else { "Need real accuracy, missed-constraints, token, elapsed-time, and evidence-correctness results traceable to raw Agent outputs." })

Add-AcceptanceCheck `
    -Id "6" `
    -Criterion "graph_review_versioning_are_phase_2" `
    -DefinitionReady $phaseBoundaryReady `
    -VerificationReady $phaseBoundaryReady `
    -Evidence "phase_gate_doc=$phaseGateDocPath; goal_evidence_doc=$goalEvidenceDocPath" `
    -Missing $(if ($phaseBoundaryReady) { "" } else { "Need phase 1/phase 2 boundary and READY_FOR_PHASE_2_REVIEW gate." })

$definitionFailures = @($Checks | Where-Object { $_.DefinitionStatus -ne "READY" })
$verificationPending = @($Checks | Where-Object { $_.VerificationStatus -ne "VERIFIED" })
$realInputReady = ($sampleDocsVerified -and $selectedCompleteTasks.Count -ge 3)
$experimentResultReady = ($parsersCoveringTenDocs -ge 3 -and $traceableResultPairs.Count -ge 3)

$overall = if ($definitionFailures.Count -gt 0) {
    "GOAL_DEFINITION_INCOMPLETE"
}
elseif (-not $realInputReady) {
    "BLOCKED_ON_REAL_INPUTS"
}
elseif (-not $experimentResultReady) {
    "READY_FOR_EXPERIMENT_EXECUTION"
}
else {
    "READY_FOR_PHASE_2_DECISION"
}

Write-Host "Agent Knowledge Hub goal acceptance gate"
Write-Host "Project root: $ProjectRoot"
Write-Host "Experiment dir: $ExperimentDir"
Write-Host "Sample manifest: $SampleManifestPath"
Write-Host "Sample raw dir: $SampleRawDir"
Write-Host ""
$Checks | Format-Table -AutoSize
Write-Host ""
Write-Host "Definitions ready: $(6 - $definitionFailures.Count)/6"
Write-Host "Verifications ready: $(6 - $verificationPending.Count)/6"
Write-Host "Real input gate: $realInputReady"
Write-Host "Experiment result gate: $experimentResultReady"
Write-Host "Overall: $overall"

if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
    $report = @()
    $report += "# Goal Acceptance Gate"
    $report += ""
    $report += "- Overall: $overall"
    $report += "- Definitions ready: $(6 - $definitionFailures.Count)/6"
    $report += "- Verifications ready: $(6 - $verificationPending.Count)/6"
    $report += "- Real input gate: $realInputReady"
    $report += "- Experiment result gate: $experimentResultReady"
    $report += ""
    $report += "## Checks"
    foreach ($check in $Checks) {
        $report += "- $($check.Id). $($check.Criterion): definition=$($check.DefinitionStatus); verification=$($check.VerificationStatus); evidence=$($check.Evidence); missing=$($check.Missing)"
    }

    $reportDir = Split-Path -Parent $ReportPath
    if (-not [string]::IsNullOrWhiteSpace($reportDir) -and -not (Test-Path -LiteralPath $reportDir)) {
        New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
    }
    Set-Content -LiteralPath $ReportPath -Value $report -Encoding UTF8
    Write-Host "Report written: $ReportPath"
}

if ($definitionFailures.Count -gt 0) {
    exit 1
}

if ($RequireRealInputs -and -not $realInputReady) {
    exit 1
}

if ($RequireExperimentResults -and -not $experimentResultReady) {
    exit 1
}

exit 0
