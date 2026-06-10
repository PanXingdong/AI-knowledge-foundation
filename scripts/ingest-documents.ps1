[CmdletBinding(DefaultParameterSetName = "Manifest")]
param(
    [Parameter(ParameterSetName = "File", Mandatory = $true)]
    [string]$FilePath,

    [Parameter(ParameterSetName = "Manifest")]
    [string]$ManifestPath,

    [string]$OutDir,

    [Parameter(ParameterSetName = "File")]
    [string]$Title,

    [Parameter(ParameterSetName = "File")]
    [string]$SourceType = "unknown",

    [Parameter(ParameterSetName = "File")]
    [string]$Owner = "unknown",

    [Parameter(ParameterSetName = "File")]
    [string]$Project = "unknown",

    [Parameter(ParameterSetName = "File")]
    [string]$Supplier = "unknown",

    [Parameter(ParameterSetName = "File")]
    [string]$DocumentVersion = "unknown",

    [Parameter(ParameterSetName = "File")]
    [string]$SampleId,

    [int]$MaxChunkChars = 1600,
    [int]$OverlapChars = 160,

    [Parameter(ParameterSetName = "Manifest")]
    [switch]$FailFast
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$srcPath = Join-Path $projectRoot "src"

if (-not $OutDir) {
    $OutDir = Join-Path $projectRoot "data\processed"
}

if ($PSCmdlet.ParameterSetName -eq "Manifest" -and -not $ManifestPath) {
    $ManifestPath = Join-Path $projectRoot "samples\sample-manifest.csv"
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
    $argsList = @("-m", "agent_knowledge_hub.cli")

    if ($PSCmdlet.ParameterSetName -eq "File") {
        $argsList += @(
            "file",
            "--file-path", $FilePath,
            "--out-dir", $OutDir,
            "--source-type", $SourceType,
            "--owner", $Owner,
            "--project", $Project,
            "--supplier", $Supplier,
            "--document-version", $DocumentVersion,
            "--max-chunk-chars", [string]$MaxChunkChars,
            "--overlap-chars", [string]$OverlapChars
        )
        if ($Title) {
            $argsList += @("--title", $Title)
        }
        if ($SampleId) {
            $argsList += @("--sample-id", $SampleId)
        }
    } else {
        $argsList += @(
            "manifest",
            "--manifest-path", $ManifestPath,
            "--out-dir", $OutDir,
            "--project-root", $projectRoot,
            "--max-chunk-chars", [string]$MaxChunkChars,
            "--overlap-chars", [string]$OverlapChars
        )
        if ($FailFast) {
            $argsList += "--fail-fast"
        }
    }

    & python @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "Document ingestion failed with exit code $LASTEXITCODE."
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONUTF8 = $previousPythonUtf8
    $env:PYTHONIOENCODING = $previousPythonIoEncoding
}
