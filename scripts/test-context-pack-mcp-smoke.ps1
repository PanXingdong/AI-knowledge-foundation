[CmdletBinding()]
param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8791,
    [string]$StreamableHttpPath = "/mcp"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$srcPath = Join-Path $projectRoot "src"
$artifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts")
$smokeRoot = Join-Path $artifactRoot ("akh-mcp-smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$rawRoot = Join-Path $smokeRoot "raw"
$processedRoot = Join-Path $smokeRoot "processed"
$stdoutPath = Join-Path $smokeRoot "mcp-server-stdout.log"
$stderrPath = Join-Path $smokeRoot "mcp-server-stderr.log"
$resultPath = Join-Path $smokeRoot "mcp-client-result.json"

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

New-Item -ItemType Directory -Force -Path $smokeRoot | Out-Null

$previousPythonPath = $env:PYTHONPATH
if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
    $env:PYTHONPATH = $srcPath
} else {
    $env:PYTHONPATH = "$srcPath;$previousPythonPath"
}
$previousSmokeRoot = $env:AKH_SMOKE_ROOT
$previousProcessedRoot = $env:AKH_PROCESSED_ROOT
$previousResultPath = $env:AKH_MCP_RESULT_PATH
$previousMcpUrl = $env:AKH_MCP_URL

$env:AKH_SMOKE_ROOT = $smokeRoot
$env:AKH_PROCESSED_ROOT = $processedRoot
$env:AKH_MCP_RESULT_PATH = $resultPath
$env:AKH_MCP_URL = "http://$BindHost`:$Port$StreamableHttpPath"

$pythonSpec = Resolve-PythonCommand
$serverProcess = $null

try {
    New-Item -ItemType Directory -Force -Path $rawRoot | Out-Null

    $docs = @(
        @{
            FileName = "architecture.md"
            Title = "architecture"
            Content = @(
                "# Architecture",
                "",
                "Phase-1 uses the third runtime option.",
                "Skill/MCP is only acceptable for short PoC work."
            ) -join "`n"
        },
        @{
            FileName = "governance.md"
            Title = "governance"
            Content = @(
                "# Governance",
                "",
                "The default policy keeps the main repository read only.",
                "The default policy does not allow unrestricted network access.",
                "High-risk actions require approval by default."
            ) -join "`n"
        },
        @{
            FileName = "api.md"
            Title = "api"
            Content = @(
                "# API",
                "",
                "GET /runtime-runs/{run_id}/events provides event stream lookup.",
                "runtime_requires_approval is used for approval events."
            ) -join "`n"
        }
    )

    foreach ($doc in $docs) {
        $filePath = Join-Path $rawRoot $doc.FileName
        Set-Content -LiteralPath $filePath -Value $doc.Content -Encoding UTF8
        & powershell -ExecutionPolicy Bypass -File (Join-Path $scriptDir "ingest-documents.ps1") `
            -FilePath $filePath `
            -Title $doc.Title `
            -SourceType "internal design doc" `
            -Owner "checker" `
            -DocumentVersion "v1" `
            -OutDir $processedRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to ingest smoke document: $($doc.FileName)"
        }
    }

    $serverArgs = @(
        "-m", "agent_knowledge_hub.mcp_server",
        "--transport", "streamable-http",
        "--host", $BindHost,
        "--port", [string]$Port,
        "--streamable-http-path", $StreamableHttpPath
    )

    $serverProcess = Start-Process `
        -FilePath $pythonSpec.FilePath `
        -ArgumentList ($pythonSpec.PrefixArgs + $serverArgs) `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath

    Start-Sleep -Seconds 3

    if ($serverProcess.HasExited) {
        throw "MCP server exited early. See $stderrPath"
    }

    $clientScript = @'
import json
import anyio
import os
from pathlib import Path
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession

processed_dir = Path(os.environ["AKH_PROCESSED_ROOT"])
result_path = Path(os.environ["AKH_MCP_RESULT_PATH"])
url = os.environ["AKH_MCP_URL"]

async def main():
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            pack = await session.call_tool(
                "get_context_pack",
                {
                    "processed_dir": str(processed_dir),
                    "query": "Why choose the third runtime option, and what are the default governance rules and API event capabilities?",
                    "top_k": 4,
                    "per_document_limit": 2,
                },
            )
            search = await session.call_tool(
                "search_knowledge",
                {
                    "processed_dir": str(processed_dir),
                    "query": "What are the default governance rules?",
                    "top_k": 2,
                    "per_document_limit": 1,
                },
            )
            pack_payload = json.loads(getattr(pack.content[0], "text", "{}")) if pack.content else {}
            first_evidence_id = (
                (((pack_payload.get("selected_chunks") or [{}])[0].get("evidence_ids") or [None])[0])
                if pack_payload.get("selected_chunks")
                else None
            )
            trace = None
            if first_evidence_id:
                trace = await session.call_tool(
                    "trace_evidence",
                    {
                        "processed_dir": str(processed_dir),
                        "evidence_id": first_evidence_id,
                    },
                )
            trace_payload = json.loads(getattr(trace.content[0], "text", "{}")) if trace and trace.content else {}

            payload = {
                "tool_names": [tool.name for tool in tools.tools],
                "context_pack_is_error": pack.isError,
                "search_is_error": search.isError,
                "trace_is_error": trace.isError if trace else None,
                "trace_evidence_id": first_evidence_id,
                "context_pack_preview": getattr(pack.content[0], "text", "")[:800] if pack.content else "",
                "search_preview": getattr(search.content[0], "text", "")[:800] if search.content else "",
                "trace_preview": json.dumps(trace_payload, ensure_ascii=True)[:800] if trace_payload else "",
            }
            result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(payload, ensure_ascii=True))

anyio.run(main)
'@

    $clientScript | & $pythonSpec.FilePath @($pythonSpec.PrefixArgs + @("-"))
    if ($LASTEXITCODE -ne 0) {
        throw "MCP client smoke failed."
    }

    Write-Output "Smoke artifacts: $smokeRoot"
} finally {
    if ($serverProcess -and -not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -Force
    }
    $env:PYTHONPATH = $previousPythonPath
    $env:AKH_SMOKE_ROOT = $previousSmokeRoot
    $env:AKH_PROCESSED_ROOT = $previousProcessedRoot
    $env:AKH_MCP_RESULT_PATH = $previousResultPath
    $env:AKH_MCP_URL = $previousMcpUrl
}
