[CmdletBinding()]
param(
    [string[]]$RootDir,
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [string]$PythonExe = "",
    [int]$MaxFiles = 30,
    [double]$MaxFileMb = 100,
    [int]$SampleSize = 8,
    [string[]]$IncludeKeyword = @(),
    [string[]]$ExcludeKeyword = @(),
    [switch]$AllowDuplicateHash,
    [switch]$UseSyntheticFallback,
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$srcPath = Join-Path $projectRoot "src"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runRoot = Join-Path $ArtifactRoot "knowledge-hub-overnight-$timestamp"
$dependencyDir = Join-Path $runRoot "dependencies"
$inventoryDir = Join-Path $runRoot "inventory"
$processedDir = Join-Path $runRoot "processed"
$qualityDir = Join-Path $runRoot "quality"
$contextDir = Join-Path $runRoot "context-packs"
$traceDir = Join-Path $runRoot "traces"
$evalDir = Join-Path $runRoot "eval"
$evalRunDir = Join-Path $runRoot "eval-run"
$evalScoreDir = Join-Path $runRoot "eval-score"
$syntheticDir = Join-Path $runRoot "synthetic-raw"
$summaryPath = Join-Path $runRoot "overnight-summary.json"
$reportPath = Join-Path $runRoot "overnight-report.md"

function Invoke-AkhPython {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $commandOutput = & $script:PythonExeResolved @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($exitCode -ne 0) {
        $tail = [string]::Join([Environment]::NewLine, @($commandOutput | Select-Object -Last 20))
        throw "Python command failed with exit code $exitCode`: $($Arguments -join ' ')`n$tail"
    }
}

function Resolve-PythonExecutable {
    param([string]$RequestedPythonExe)

    if (-not [string]::IsNullOrWhiteSpace($RequestedPythonExe)) {
        $command = Get-Command $RequestedPythonExe -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Definition
        }
        return $RequestedPythonExe
    }

    if (-not [string]::IsNullOrWhiteSpace($env:AKH_PYTHON_EXE)) {
        return Resolve-PythonExecutable -RequestedPythonExe $env:AKH_PYTHON_EXE
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $resolved = & py -3.12 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1
        if (-not [string]::IsNullOrWhiteSpace($resolved)) {
            return $resolved
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Definition
    }

    throw "No Python executable found. Pass -PythonExe explicitly."
}

function Add-StageResult {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Detail = ""
    )
    $script:StageResults += [ordered]@{
        name = $Name
        status = $Status
        detail = $Detail
    }
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}
New-Item -ItemType Directory -Path $runRoot,$dependencyDir,$inventoryDir,$processedDir,$qualityDir,$contextDir,$traceDir,$evalDir,$evalRunDir,$evalScoreDir -Force | Out-Null

$script:PythonExeResolved = Resolve-PythonExecutable -RequestedPythonExe $PythonExe

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

$StageResults = @()
$scenarioIds = @("constraint-query", "impact-analysis", "test-review-checklist")

try {
    Invoke-AkhPython -Arguments @(
        "-m", "agent_knowledge_hub.cli",
        "dependency-check",
        "--output-dir", $dependencyDir
    )
    Add-StageResult -Name "dependency-check" -Status "ok" -Detail $dependencyDir

    if (-not $RootDir -or $RootDir.Count -eq 0) {
        $downloads = Join-Path $env:USERPROFILE "Downloads"
        $projectSamples = Join-Path $projectRoot "samples"
        $RootDir = @($downloads, $projectSamples)
    }

    if ($UseSyntheticFallback) {
        New-Item -ItemType Directory -Path $syntheticDir -Force | Out-Null
        $env:AKH_SYNTHETIC_DIR = $syntheticDir
        @'
import os
from pathlib import Path

root = Path(os.environ["AKH_SYNTHETIC_DIR"])
root.mkdir(parents=True, exist_ok=True)
(root / "internal-vehicle-data-spec.md").write_text(
    "\n".join(
        [
            "# \u5185\u90e8\u6c7d\u8f66\u6570\u636e SPEC",
            "",
            "\u91cd\u8981\u6570\u636e\u5b58\u50a8\u5fc5\u987b\u6709\u8bbf\u95ee\u63a7\u5236\u548c\u52a0\u5bc6\u4fdd\u62a4\u3002",
            "\u91cd\u8981\u6570\u636e\u4f20\u8f93\u5fc5\u987b\u6709\u4fdd\u5bc6\u6027\u4fdd\u62a4\u3002",
            "\u91cd\u8981\u6570\u636e\u5220\u9664\u540e\u5fc5\u987b\u4e0d\u53ef\u68c0\u7d22\u4e14\u4e0d\u53ef\u8bbf\u95ee\u3002",
            "\u51fa\u5883\u94fe\u8def\u4e0d\u5141\u8bb8\u8f66\u8f86\u76f4\u63a5\u5411\u5883\u5916\u4f20\u8f93\u91cd\u8981\u6570\u636e\u3002",
            "",
        ]
    ),
    encoding="utf-8",
)
(root / "vehicle-data-architecture.html").write_text(
    "\n".join(
        [
            "<html><body><h1>\u6c7d\u8f66\u6570\u636e\u67b6\u6784</h1>",
            "<p>\u53d8\u66f4 GB/T \u91cd\u8981\u6570\u636e\u8981\u6c42\u4f1a\u5f71\u54cd\u8f66\u7aef\u5b58\u50a8\u6a21\u5757\u3001\u4e91\u7aef\u540c\u6b65\u6a21\u5757\u3001\u5220\u9664\u670d\u52a1\u548c\u5408\u89c4\u5ba1\u8ba1\u3002</p>",
            "</body></html>",
        ]
    ),
    encoding="utf-8",
)
(root / "review-checklist.txt").write_text(
    "\n".join(
        [
            "\u8bc4\u5ba1 checklist\uff1a",
            "\u68c0\u67e5\u8bbf\u95ee\u63a7\u5236\u3001\u52a0\u5bc6\u3001\u4fdd\u5bc6\u6027\u3001\u5220\u9664\u4e0d\u53ef\u6062\u590d\u3001\u51fa\u5883\u963b\u65ad\u548c\u5ba1\u8ba1\u8bb0\u5f55\u3002",
        ]
    ),
    encoding="utf-8",
)
'@ | & $script:PythonExeResolved -
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create synthetic fallback documents."
        }
        $RootDir = @($syntheticDir) + $RootDir
    }

    $inventoryArgs = @(
        "-m", "agent_knowledge_hub.cli",
        "inventory",
        "--output-dir", $inventoryDir,
        "--max-files", [string]$MaxFiles,
        "--max-file-mb", [string]$MaxFileMb,
        "--sample-size", [string]$SampleSize,
        "--owner", "checker",
        "--project", "overnight"
    )
    foreach ($root in $RootDir) {
        $inventoryArgs += @("--root-dir", $root)
    }
    foreach ($keyword in $IncludeKeyword) {
        if (-not [string]::IsNullOrWhiteSpace($keyword)) {
            $inventoryArgs += @("--include-keyword", $keyword)
        }
    }
    foreach ($keyword in $ExcludeKeyword) {
        if (-not [string]::IsNullOrWhiteSpace($keyword)) {
            $inventoryArgs += @("--exclude-keyword", $keyword)
        }
    }
    if ($AllowDuplicateHash) {
        $inventoryArgs += "--allow-duplicate-hash"
    }
    Invoke-AkhPython -Arguments $inventoryArgs
    $inventoryJsonPath = Join-Path $inventoryDir "document-inventory.json"
    $inventoryPayload = Get-Content -LiteralPath $inventoryJsonPath -Raw | ConvertFrom-Json
    if ($inventoryPayload.document_count -lt 1) {
        throw "Document inventory is empty. Relax -IncludeKeyword or check -RootDir."
    }
    Add-StageResult -Name "inventory" -Status "ok" -Detail $inventoryDir

    $manifestPath = Join-Path $inventoryDir "raw-docs-sample-manifest.csv"
    Invoke-AkhPython -Arguments @(
        "-m", "agent_knowledge_hub.cli",
        "manifest",
        "--manifest-path", $manifestPath,
        "--out-dir", $processedDir,
        "--project-root", $projectRoot,
        "--incremental"
    )
    Add-StageResult -Name "incremental-ingest" -Status "ok" -Detail $processedDir

    Invoke-AkhPython -Arguments @(
        "-m", "agent_knowledge_hub.cli",
        "parse-quality-summary",
        "--processed-dir", $processedDir,
        "--output-dir", $qualityDir
    )
    Add-StageResult -Name "quality-summary" -Status "ok" -Detail $qualityDir

    $queries = [ordered]@{
        "constraint-query" = "\u91cd\u8981\u6570\u636e\u5b58\u50a8\u3001\u4f20\u8f93\u3001\u5220\u9664\u548c\u51fa\u5883\u6709\u54ea\u4e9b\u7ea6\u675f\uff1f"
        "impact-analysis" = "\u5982\u679c\u91cd\u8981\u6570\u636e\u4f20\u8f93\u6216\u51fa\u5883\u8981\u6c42\u53d8\u5316\uff0c\u4f1a\u5f71\u54cd\u54ea\u4e9b\u6a21\u5757\u548c\u6d4b\u8bd5\uff1f"
        "test-review-checklist" = "\u91cd\u8981\u6570\u636e\u5904\u7406\u53d8\u66f4\u7684\u6d4b\u8bd5\u548c\u8bc4\u5ba1 checklist \u8981\u8986\u76d6\u54ea\u4e9b\u70b9\uff1f"
    }
    foreach ($scenarioId in $scenarioIds) {
        $scenarioDir = Join-Path $contextDir $scenarioId
        New-Item -ItemType Directory -Path $scenarioDir -Force | Out-Null
        Invoke-AkhPython -Arguments @(
            "-m", "agent_knowledge_hub.cli",
            "context-pack",
            "--processed-dir", $processedDir,
            "--query", $queries[$scenarioId],
            "--top-k", "8",
            "--per-document-limit", "2",
            "--output-dir", $scenarioDir
        )
    }
    Add-StageResult -Name "context-pack" -Status "ok" -Detail $contextDir

    $firstContextJson = Join-Path (Join-Path $contextDir $scenarioIds[0]) "context_pack.json"
    $traceOutput = Join-Path $traceDir "first-evidence-trace.json"
    $env:AKH_FIRST_CONTEXT_JSON = $firstContextJson
    $env:AKH_PROCESSED_DIR = $processedDir
    $env:AKH_TRACE_OUTPUT = $traceOutput
    @'
import json
import os
from pathlib import Path

from agent_knowledge_hub.retrieval import trace_evidence_in_processed_dir
from agent_knowledge_hub.utils import write_json

context_path = Path(os.environ["AKH_FIRST_CONTEXT_JSON"])
processed_dir = Path(os.environ["AKH_PROCESSED_DIR"])
trace_output = Path(os.environ["AKH_TRACE_OUTPUT"])
payload = json.loads(context_path.read_text(encoding="utf-8"))
selected = payload.get("selected_chunks") or []
evidence_ids = selected[0].get("evidence_ids") if selected else []
if evidence_ids:
    trace = trace_evidence_in_processed_dir(
        processed_dir=processed_dir,
        evidence_id=evidence_ids[0],
    )
    write_json(trace_output, trace.to_dict())
else:
    write_json(trace_output, {"error": "no_evidence_selected"})
'@ | & $script:PythonExeResolved -
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to trace first evidence."
    }
    Add-StageResult -Name "trace-evidence" -Status "ok" -Detail $traceOutput

    $env:AKH_RUN_ROOT = $runRoot
    $env:AKH_INVENTORY_DIR = $inventoryDir
    $env:AKH_PROCESSED_DIR = $processedDir
    $env:AKH_QUALITY_DIR = $qualityDir
    $env:AKH_CONTEXT_DIR = $contextDir
    $env:AKH_EVAL_DIR = $evalDir
    @'
import json
import os
from pathlib import Path

from agent_knowledge_hub.utils import write_json

run_root = Path(os.environ["AKH_RUN_ROOT"])
inventory = json.loads((Path(os.environ["AKH_INVENTORY_DIR"]) / "document-inventory.json").read_text(encoding="utf-8"))
ingest = json.loads((Path(os.environ["AKH_PROCESSED_DIR"]) / "ingest-run-summary.json").read_text(encoding="utf-8"))
quality = json.loads((Path(os.environ["AKH_QUALITY_DIR"]) / "parse-quality-summary.json").read_text(encoding="utf-8"))
context_dir = Path(os.environ["AKH_CONTEXT_DIR"])
eval_dir = Path(os.environ["AKH_EVAL_DIR"])

cases = []
for path in sorted(context_dir.glob("*/context_pack.json")):
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases.append(
        {
            "scenario_id": path.parent.name,
            "chunk_count": payload.get("chunk_count", 0),
            "document_count": payload.get("document_count", 0),
            "evidence_traceable": bool(payload.get("selected_chunks")),
        }
    )

report = {
    "inventory_document_count": inventory.get("document_count", 0),
    "ingest_processed_count": ingest.get("processed_count", 0),
    "ingest_unchanged_count": ingest.get("unchanged_count", 0),
    "ingest_failed_count": ingest.get("failed_count", 0),
    "quality_status_counts": quality.get("status_counts", {}),
    "allowed_document_count": quality.get("allowed_document_count", 0),
    "blocked_document_count": quality.get("blocked_document_count", 0),
    "cases": cases,
    "context_pack_cases_with_evidence": sum(1 for case in cases if case["chunk_count"] > 0),
}
write_json(eval_dir / "eval-report.json", report)
(eval_dir / "eval-report.md").write_text(
    "\n".join(
        [
            "# Overnight Eval Report",
            "",
            f"- Inventory documents: {report['inventory_document_count']}",
            f"- Ingest processed: {report['ingest_processed_count']}",
            f"- Ingest unchanged: {report['ingest_unchanged_count']}",
            f"- Ingest failed: {report['ingest_failed_count']}",
            f"- Allowed documents: {report['allowed_document_count']}",
            f"- Blocked documents: {report['blocked_document_count']}",
            f"- Context Pack cases with evidence: {report['context_pack_cases_with_evidence']}/{len(cases)}",
            "",
            "## Cases",
            "",
            *[
                f"- `{case['scenario_id']}`: chunks={case['chunk_count']}, documents={case['document_count']}"
                for case in cases
            ],
            "",
        ]
    ),
    encoding="utf-8",
)
'@ | & $script:PythonExeResolved -
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to build eval report."
    }
    Add-StageResult -Name "eval" -Status "ok" -Detail $evalDir

    $evalCasesPath = Join-Path $evalDir "eval_cases.jsonl"
    $env:AKH_EVAL_CASES_PATH = $evalCasesPath
    @'
import json
import os
from pathlib import Path

cases = [
    {
        "task_id": "constraint-query",
        "task_type": "constraint-query",
        "question": "\u91cd\u8981\u6570\u636e\u5b58\u50a8\u3001\u4f20\u8f93\u3001\u5220\u9664\u548c\u51fa\u5883\u6709\u54ea\u4e9b\u7ea6\u675f\uff1f",
        "gold_answer_points": ["\u5b58\u50a8\u7ea6\u675f", "\u4f20\u8f93\u7ea6\u675f", "\u5220\u9664\u7ea6\u675f", "\u51fa\u5883\u7ea6\u675f"],
        "required_constraints": ["\u8bbf\u95ee\u63a7\u5236", "\u52a0\u5bc6", "\u4fdd\u5bc6\u6027", "\u4e0d\u53ef\u68c0\u7d22", "\u51fa\u5883\u9650\u5236"],
        "expected_evidence": ["SPEC", "architecture", "checklist"],
        "allowed_documents": ["processed engineering documents"],
        "scorer": "checker",
    },
    {
        "task_id": "impact-analysis",
        "task_type": "impact-analysis",
        "question": "\u5982\u679c\u91cd\u8981\u6570\u636e\u4f20\u8f93\u6216\u51fa\u5883\u8981\u6c42\u53d8\u5316\uff0c\u4f1a\u5f71\u54cd\u54ea\u4e9b\u6a21\u5757\u548c\u6d4b\u8bd5\uff1f",
        "gold_answer_points": ["\u5b58\u50a8\u6a21\u5757", "\u540c\u6b65\u6a21\u5757", "\u5220\u9664\u670d\u52a1", "\u5ba1\u8ba1", "\u6d4b\u8bd5"],
        "required_constraints": ["\u5f71\u54cd\u8303\u56f4", "\u6d4b\u8bd5\u8986\u76d6", "\u8bc1\u636e\u6765\u6e90"],
        "expected_evidence": ["architecture", "SPEC"],
        "allowed_documents": ["processed engineering documents"],
        "scorer": "checker",
    },
    {
        "task_id": "test-review-checklist",
        "task_type": "test-review-checklist",
        "question": "\u91cd\u8981\u6570\u636e\u5904\u7406\u53d8\u66f4\u7684\u6d4b\u8bd5\u548c\u8bc4\u5ba1 checklist \u8981\u8986\u76d6\u54ea\u4e9b\u70b9\uff1f",
        "gold_answer_points": ["\u8bbf\u95ee\u63a7\u5236", "\u52a0\u5bc6", "\u4fdd\u5bc6\u6027", "\u5220\u9664\u4e0d\u53ef\u6062\u590d", "\u51fa\u5883\u963b\u65ad", "\u5ba1\u8ba1"],
        "required_constraints": ["\u6d4b\u8bd5\u70b9", "\u8bc4\u5ba1\u70b9", "\u8bc1\u636e\u6765\u6e90"],
        "expected_evidence": ["checklist", "SPEC"],
        "allowed_documents": ["processed engineering documents"],
        "scorer": "checker",
    },
]
path = Path(os.environ["AKH_EVAL_CASES_PATH"])
path.write_text("\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n", encoding="utf-8")
'@ | & $script:PythonExeResolved -
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to write eval cases."
    }
    Invoke-AkhPython -Arguments @(
        "-m", "agent_knowledge_hub.cli",
        "prepare-eval-run",
        "--eval-cases", $evalCasesPath,
        "--processed-dir", $processedDir,
        "--output-dir", $evalRunDir,
        "--run-id", "overnight-eval",
        "--top-k", "8",
        "--per-document-limit", "2"
    )
    Add-StageResult -Name "eval-run-setup" -Status "ok" -Detail $evalRunDir

    Invoke-AkhPython -Arguments @(
        "-m", "agent_knowledge_hub.cli",
        "prepare-eval-execution-pack",
        "--eval-run-dir", $evalRunDir,
        "--eval-cases", $evalCasesPath
    )
    Add-StageResult -Name "eval-execution-pack" -Status "ok" -Detail (Join-Path $evalRunDir "real-agent-execution-guide.md")

    $env:AKH_EVAL_RUN_DIR = $evalRunDir
    @'
import csv
import json
import os
from pathlib import Path

run_dir = Path(os.environ["AKH_EVAL_RUN_DIR"])
raw_output_dir = run_dir / "raw-outputs"
raw_output_dir.mkdir(parents=True, exist_ok=True)
case_answers = json.loads(r'''
{
  "constraint-query": {
    "baseline": "\u91cd\u8981\u6570\u636e\u5b58\u50a8\u9700\u8981\u8bbf\u95ee\u63a7\u5236\u3002Evidence: SPEC\u3002",
    "context_pack": "\u91cd\u8981\u6570\u636e\u5b58\u50a8\u9700\u8981\u8bbf\u95ee\u63a7\u5236\u548c\u52a0\u5bc6\uff1b\u91cd\u8981\u6570\u636e\u4f20\u8f93\u9700\u8981\u4fdd\u5bc6\u6027\u4fdd\u62a4\uff1b\u5220\u9664\u540e\u5e94\u4e0d\u53ef\u68c0\u7d22\u4e14\u4e0d\u53ef\u8bbf\u95ee\uff1b\u8f66\u8f86\u4e0d\u5e94\u76f4\u63a5\u5411\u5883\u5916\u4f20\u8f93\u91cd\u8981\u6570\u636e\u3002Evidence: GBT 44464 2024 \u6c7d\u8f66\u6570\u636e\u901a\u7528\u8981\u6c42\u3002"
  },
  "impact-analysis": {
    "baseline": "\u4f1a\u5f71\u54cd\u5b58\u50a8\u6a21\u5757\u548c\u6d4b\u8bd5\u3002Evidence: architecture\u3002",
    "context_pack": "\u4f1a\u5f71\u54cd\u5b58\u50a8\u6a21\u5757\u3001\u540c\u6b65\u6a21\u5757\u3001\u5220\u9664\u670d\u52a1\u3001\u5ba1\u8ba1\u4ee5\u53ca\u6d4b\u8bd5\u8986\u76d6\u3002Evidence: architecture; SPEC\u3002"
  },
  "test-review-checklist": {
    "baseline": "\u68c0\u67e5\u8bbf\u95ee\u63a7\u5236\u548c\u52a0\u5bc6\u3002Evidence: checklist\u3002",
    "context_pack": "\u6d4b\u8bd5\u548c\u8bc4\u5ba1 checklist \u5e94\u8986\u76d6\u8bbf\u95ee\u63a7\u5236\u3001\u52a0\u5bc6\u3001\u4fdd\u5bc6\u6027\u3001\u5220\u9664\u4e0d\u53ef\u6062\u590d\u3001\u51fa\u5883\u963b\u65ad\u548c\u5ba1\u8ba1\u3002Evidence: checklist; SPEC\u3002"
  }
}
''')
run_log_path = run_dir / "agent-run-log.csv"
with run_log_path.open("r", encoding="utf-8-sig", newline="") as handle:
    rows = list(csv.DictReader(handle))
fieldnames = list(rows[0].keys()) if rows else []
for row in rows:
    task_id = row["task_id"]
    group = row["group"]
    output_path = Path(row["raw_output_path"])
    if not output_path.is_absolute():
        output_path = run_dir / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(case_answers.get(task_id, {}).get(group, ""), encoding="utf-8")
    row["agent"] = "simulated-smoke-agent"
    row["model"] = "simulated-smoke-model"
    row["score_status"] = "ready_to_score"
    notes = row.get("notes", "").strip()
    marker = "simulated_smoke_output; generated_by_overnight_pipeline_smoke"
    row["notes"] = marker if not notes or notes == "\u5f85\u586b\u5199" else f"{notes}; {marker}"
with run_log_path.open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
'@ | & $script:PythonExeResolved -
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to write simulated eval raw outputs."
    }

    Invoke-AkhPython -Arguments @(
        "-m", "agent_knowledge_hub.cli",
        "score-eval-run",
        "--eval-cases", $evalCasesPath,
        "--eval-run-dir", $evalRunDir
    )
    Copy-Item -LiteralPath (Join-Path $evalRunDir "eval-score-summary.json") -Destination (Join-Path $evalScoreDir "eval-score-summary.json") -Force
    Copy-Item -LiteralPath (Join-Path $evalRunDir "eval-score-summary.md") -Destination (Join-Path $evalScoreDir "eval-score-summary.md") -Force
    Copy-Item -LiteralPath (Join-Path $evalRunDir "eval-score-details.jsonl") -Destination (Join-Path $evalScoreDir "eval-score-details.jsonl") -Force
    Add-StageResult -Name "eval-score" -Status "ok" -Detail $evalScoreDir
} catch {
    Add-StageResult -Name "pipeline" -Status "failed" -Detail $_.Exception.Message
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONUTF8 = $previousPythonUtf8
    $env:PYTHONIOENCODING = $previousPythonIoEncoding
}

$summary = [ordered]@{
    run_root = $runRoot
    python_exe = $script:PythonExeResolved
    dependency_dir = $dependencyDir
    inventory_dir = $inventoryDir
    processed_dir = $processedDir
    quality_dir = $qualityDir
    context_dir = $contextDir
    trace_dir = $traceDir
    eval_dir = $evalDir
    eval_run_dir = $evalRunDir
    eval_score_dir = $evalScoreDir
    stages = $StageResults
}
$summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

$reportLines = @(
    "# Agent Knowledge Hub Overnight Report",
    "",
    "Run Root: ``$runRoot``",
    "Python: ``$script:PythonExeResolved``",
    "",
    "## Stages",
    ""
)
foreach ($stage in $StageResults) {
    $reportLines += "- ``$($stage.name)``: $($stage.status) $($stage.detail)"
}
$reportLines += ""
$reportLines += "## Artifacts"
$reportLines += ""
$reportLines += "- Dependencies: ``$dependencyDir``"
$reportLines += "- Inventory: ``$inventoryDir``"
$reportLines += "- Processed: ``$processedDir``"
$reportLines += "- Quality: ``$qualityDir``"
$reportLines += "- Context Packs: ``$contextDir``"
$reportLines += "- Evidence Trace: ``$traceDir``"
$reportLines += "- Eval: ``$evalDir``"
$reportLines += "- Eval Run: ``$evalRunDir``"
$reportLines += "- Eval Score: ``$evalScoreDir``"
$reportLines | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Output ($summary | ConvertTo-Json -Depth 10 -Compress)

$failed = $StageResults | Where-Object { $_.status -eq "failed" }
if ($failed) {
    exit 1
}
