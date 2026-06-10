[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProcessedDir,

    [string]$OutputDir
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$srcPath = Join-Path $projectRoot "src"

if (-not $OutputDir) {
    $OutputDir = Join-Path $projectRoot "data\parse-quality-summary"
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
    $resolvedOutputDir = [System.IO.Path]::GetFullPath($OutputDir)

    $argsList = @(
        "-m", "agent_knowledge_hub.cli",
        "parse-quality-summary",
        "--processed-dir", $resolvedProcessedDir,
        "--output-dir", $resolvedOutputDir
    )

    & python @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "Parse quality summary generation failed with exit code $LASTEXITCODE."
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONUTF8 = $previousPythonUtf8
    $env:PYTHONIOENCODING = $previousPythonIoEncoding
}
