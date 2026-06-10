param(
    [string]$RunId
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "run-" + (Get-Date -Format "yyyyMMdd-HHmmss")
}

if ($RunId -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]*$") {
    Write-Error "Invalid RunId. Use only letters, numbers, dot, underscore, and hyphen."
}

$runsRoot = Join-Path $ProjectRoot "experiments\runs"
$runDir = Join-Path $runsRoot $RunId

if (Test-Path -LiteralPath $runDir) {
    Write-Error "Run directory already exists: $runDir"
}

New-Item -ItemType Directory -Path $runDir -Force | Out-Null

$templatesRoot = Join-Path $ProjectRoot "experiments\templates"
$copies = @(
    @{ Source = "agent-task-cards.md"; Target = "agent-task-cards.md" },
    @{ Source = "agent-task-cases.csv"; Target = "agent-task-cases.csv" },
    @{ Source = "parser-evaluation-sheet.csv"; Target = "parser-evaluation-sheet.csv" },
    @{ Source = "baseline-vs-contextpack-results.csv"; Target = "baseline-vs-contextpack-results.csv" },
    @{ Source = "agent-run-log.csv"; Target = "agent-run-log.csv" },
    @{ Source = "agent-prompt-template.md"; Target = "agent-prompt-template.md" },
    @{ Source = "agent-prompt-manifest.csv"; Target = "agent-prompt-manifest.csv" },
    @{ Source = "context-pack-template.json"; Target = "context-pack-template.json" },
    @{ Source = "scenario-selection-matrix.csv"; Target = "scenario-selection-matrix.csv" },
    @{ Source = "scoring-rubric.md"; Target = "scoring-rubric.md" },
    @{ Source = "experiment-summary-template.md"; Target = "experiment-summary.md" }
)

foreach ($copy in $copies) {
    $source = Join-Path $templatesRoot $copy.Source
    $target = Join-Path $runDir $copy.Target
    if (-not (Test-Path -LiteralPath $source)) {
        Write-Error "Missing template: $source"
    }

    Copy-Item -LiteralPath $source -Destination $target
}

$readme = @(
    "# $RunId",
    "",
    "This directory stores one real Agent Knowledge Hub experiment run.",
    "",
    "Fill these files with real experiment data:",
    "",
    "- agent-task-cards.md",
    "- agent-task-cases.csv",
    "- scenario-selection-matrix.csv",
    "- parser-evaluation-sheet.csv",
    "- baseline-vs-contextpack-results.csv",
    "- agent-run-log.csv",
    "- agent-prompt-template.md",
    "- agent-prompt-manifest.csv",
    "- scoring-rubric.md",
    "- experiment-summary.md",
    "",
    "Preflight this run before execution:",
    "",
    '```powershell',
    ('powershell -ExecutionPolicy Bypass -File "{0}" -StrictRealInputs -ExperimentDir "{1}"' -f
        (Join-Path $ProjectRoot "scripts\preflight.ps1"),
        $runDir),
    '```',
    "",
    "Evaluate this run with:",
    "",
    '```powershell',
    ('powershell -ExecutionPolicy Bypass -File "{0}" -ResultsPath "{1}"' -f
        (Join-Path $ProjectRoot "scripts\evaluate-results.ps1"),
        (Join-Path $runDir "baseline-vs-contextpack-results.csv")),
    '```'
)

Set-Content -LiteralPath (Join-Path $runDir "README.md") -Value $readme -Encoding UTF8

Write-Host "Experiment run created: $runDir"
Write-Host "Next: fill real task cards and baseline/context_pack results, then run evaluate-results.ps1."
