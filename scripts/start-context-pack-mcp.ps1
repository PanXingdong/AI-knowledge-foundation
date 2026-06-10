[CmdletBinding()]
param(
    [ValidateSet("streamable-http", "stdio", "sse")]
    [string]$Transport = "streamable-http",

    [string]$BindHost = "127.0.0.1",

    [int]$Port = 8788,

    [string]$StreamableHttpPath = "/mcp"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$srcPath = Join-Path $projectRoot "src"

function Resolve-PythonCommand {
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        try {
            & $pyCommand.Source -3.12 -c "import sys; import mcp; import pydantic" *> $null
            if ($LASTEXITCODE -eq 0) {
                return @{
                    FilePath = $pyCommand.Source
                    PrefixArgs = @("-3.12")
                }
            }
        } catch {
        }
    }

    $pythonCommand = Get-Command python -ErrorAction Stop
    return @{
        FilePath = $pythonCommand.Definition
        PrefixArgs = @()
    }
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
    $pythonSpec = Resolve-PythonCommand
    $argsList = @(
        "-m", "agent_knowledge_hub.mcp_server",
        "--transport", $Transport,
        "--host", $BindHost,
        "--port", [string]$Port,
        "--streamable-http-path", $StreamableHttpPath
    )

    & $pythonSpec.FilePath @($pythonSpec.PrefixArgs + $argsList)
    if ($LASTEXITCODE -ne 0) {
        throw "Context Pack MCP server failed with exit code $LASTEXITCODE."
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONUTF8 = $previousPythonUtf8
    $env:PYTHONIOENCODING = $previousPythonIoEncoding
}
