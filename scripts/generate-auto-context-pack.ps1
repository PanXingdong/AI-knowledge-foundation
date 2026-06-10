[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProcessedDir,

    [Parameter(Mandatory = $true)]
    [string]$QuestionPath,

    [string]$ReferenceContextPackPath,

    [string]$OutputDir,

    [int]$TopK = 8,
    [int]$PerDocumentLimit = 2
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$srcPath = Join-Path $projectRoot "src"

if (-not $OutputDir) {
    $OutputDir = Join-Path $projectRoot "data\context-pack-output"
}

$previousPythonPath = $env:PYTHONPATH
$previousPythonUtf8 = $env:PYTHONUTF8
$previousPythonIoEncoding = $env:PYTHONIOENCODING
if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
    $env:PYTHONPATH = $srcPath
} else {
    $env:PYTHONPATH = "$srcPath;$previousPythonPath"
}
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

try {
    $resolvedProcessedDir = (Resolve-Path -LiteralPath $ProcessedDir).Path
    $resolvedQuestionPath = (Resolve-Path -LiteralPath $QuestionPath).Path
    $resolvedOutputDir = [System.IO.Path]::GetFullPath($OutputDir)

    $contextPackArgs = @(
        "-m", "agent_knowledge_hub.cli",
        "context-pack",
        "--processed-dir", $resolvedProcessedDir,
        "--query-file", $resolvedQuestionPath,
        "--top-k", [string]$TopK,
        "--per-document-limit", [string]$PerDocumentLimit,
        "--output-dir", $resolvedOutputDir
    )

    & python @contextPackArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Context Pack generation failed with exit code $LASTEXITCODE."
    }

    if ($ReferenceContextPackPath) {
        $resolvedReferencePath = (Resolve-Path -LiteralPath $ReferenceContextPackPath).Path
        $gapOutputDir = Join-Path $resolvedOutputDir "gap-report"

        $gapArgs = @(
            "-m", "agent_knowledge_hub.cli",
            "gap-report",
            "--auto-context-pack-json", (Join-Path $resolvedOutputDir "context_pack.json"),
            "--reference-markdown", $resolvedReferencePath,
            "--output-dir", $gapOutputDir
        )

        & python @gapArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Gap report generation failed with exit code $LASTEXITCODE."
        }
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONUTF8 = $previousPythonUtf8
    $env:PYTHONIOENCODING = $previousPythonIoEncoding
}
