[CmdletBinding()]
param(
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [string]$GbtPdfPath,
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$srcPath = Join-Path $projectRoot "src"
$isolatedPythonPackages = Join-Path $ArtifactRoot "python-pkgs"
$pythonLauncher = "py"
$pythonArgsPrefix = @("-3.12")

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $pythonLauncher @($pythonArgsPrefix + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE`: $($Arguments -join ' ')"
    }
}

if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
}

if (-not $GbtPdfPath) {
    $gbtCandidate = Get-ChildItem -Path (Join-Path $env:USERPROFILE "Downloads") -File -Filter "*44464*.pdf" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($gbtCandidate) {
        $GbtPdfPath = $gbtCandidate.FullName
    }
}
if (-not $GbtPdfPath -or -not (Test-Path -LiteralPath $GbtPdfPath)) {
    throw "Missing GBT 44464 PDF. Pass -GbtPdfPath or place *44464*.pdf under Downloads."
}

$runRoot = Join-Path $ArtifactRoot "knowledge-hub-multidoc-mvp"
$rawDir = Join-Path $runRoot "raw"
$processedDir = Join-Path $runRoot "processed"
$qualityDir = Join-Path $runRoot "quality"
$scenariosDir = Join-Path $runRoot "scenarios"
$traceDir = Join-Path $runRoot "traces"
$manifestPath = Join-Path $runRoot "manifest.csv"
$runSummaryPath = Join-Path $runRoot "mvp-e2e-summary.json"

if (Test-Path -LiteralPath $runRoot) {
    Remove-Item -LiteralPath $runRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $rawDir,$scenariosDir,$traceDir -Force | Out-Null

$gbtTarget = Join-Path $rawDir "GBT-44464-2024-vehicle-data.pdf"
Copy-Item -LiteralPath $GbtPdfPath -Destination $gbtTarget -Force

$previousPythonPath = $env:PYTHONPATH
$previousPythonUtf8 = $env:PYTHONUTF8
$previousPythonIoEncoding = $env:PYTHONIOENCODING
if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
    $env:PYTHONPATH = $srcPath
} else {
    $env:PYTHONPATH = "$srcPath;$previousPythonPath"
}
if (Test-Path -LiteralPath $isolatedPythonPackages) {
    $env:PYTHONPATH = "$isolatedPythonPackages;$env:PYTHONPATH"
}
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

try {
    $env:AKH_MVP_RUN_ROOT = $runRoot
    $env:AKH_MVP_RAW_DIR = $rawDir
    $env:AKH_MVP_GBT_TARGET = $gbtTarget
    $env:AKH_MVP_MANIFEST_PATH = $manifestPath
    $env:AKH_MVP_SCENARIOS_DIR = $scenariosDir

    @'
import csv
import os
from pathlib import Path

from docx import Document

raw_dir = Path(os.environ["AKH_MVP_RAW_DIR"])
gbt_target = Path(os.environ["AKH_MVP_GBT_TARGET"])
manifest_path = Path(os.environ["AKH_MVP_MANIFEST_PATH"])
scenarios_dir = Path(os.environ["AKH_MVP_SCENARIOS_DIR"])

internal_spec = raw_dir / "internal-vehicle-data-spec.md"
internal_spec.write_text(
    "\n".join(
        [
            "# \u5185\u90e8\u6c7d\u8f66\u6570\u636e\u5904\u7406 SPEC",
            "",
            "## \u76ee\u6807",
            "",
            "\u672c SPEC \u5f15\u7528 GB/T 44464-2024 \u4f5c\u4e3a\u91cd\u8981\u6570\u636e\u5904\u7406\u7684\u5408\u89c4\u4f9d\u636e\u3002",
            "",
            "## \u7ea6\u675f",
            "",
            "\u5185\u90e8\u7cfb\u7edf\u5904\u7406\u91cd\u8981\u6570\u636e\u65f6\uff0c\u5fc5\u987b\u7ee7\u627f GB/T 44464-2024 \u4e2d\u5173\u4e8e\u91cd\u8981\u6570\u636e\u5b58\u50a8\u3001\u4f7f\u7528\u3001\u4f20\u8f93\u3001\u5220\u9664\u548c\u51fa\u5883\u7684\u8981\u6c42\u3002",
            "\u8f66\u8f86\u7aef\u91cd\u8981\u6570\u636e\u5b58\u50a8\u9700\u8981\u5b89\u5168\u8bbf\u95ee\u63a7\u5236\u548c\u52a0\u5bc6\u4fdd\u62a4\uff0c\u4e91\u7aef\u540c\u6b65\u94fe\u8def\u9700\u8981\u4fdd\u5bc6\u6027\u4fdd\u62a4\u3002",
            "\u91cd\u8981\u6570\u636e\u5220\u9664\u540e\u5fc5\u987b\u4e0d\u53ef\u68c0\u7d22\u4e14\u4e0d\u53ef\u8bbf\u95ee\uff0c\u51fa\u5883\u94fe\u8def\u4e0d\u5141\u8bb8\u8f66\u8f86\u76f4\u63a5\u5411\u5883\u5916\u4f20\u8f93\u91cd\u8981\u6570\u636e\u3002",
            "",
            "## \u6d4b\u8bd5",
            "",
            "\u6d4b\u8bd5\u8bbe\u8ba1\u5fc5\u987b\u8986\u76d6\u91cd\u8981\u6570\u636e\u5b58\u50a8\u8bbf\u95ee\u63a7\u5236\u3001\u4f20\u8f93\u4fdd\u5bc6\u6027\u3001\u5220\u9664\u4e0d\u53ef\u6062\u590d\u3001\u51fa\u5883\u9650\u5236\u548c\u5ba1\u8ba1\u8bb0\u5f55\u3002",
            "",
        ]
    ),
    encoding="utf-8",
)

architecture_doc = raw_dir / "vehicle-data-architecture.html"
architecture_doc.write_text(
    "\n".join(
        [
            "<!doctype html>",
            "<html><body>",
            "<h1>\u6c7d\u8f66\u6570\u636e\u67b6\u6784\u8bbe\u8ba1</h1>",
            "<p>\u6570\u636e\u91c7\u96c6\u6a21\u5757\u3001\u8f66\u7aef\u5b58\u50a8\u6a21\u5757\u3001\u4e91\u7aef\u540c\u6b65\u6a21\u5757\u548c\u5220\u9664\u670d\u52a1\u5171\u540c\u5b9e\u73b0\u91cd\u8981\u6570\u636e\u5904\u7406\u94fe\u8def\u3002</p>",
            "<p>\u5982\u679c GB/T 44464-2024 \u7684\u91cd\u8981\u6570\u636e\u4f20\u8f93\u6216\u51fa\u5883\u8981\u6c42\u53d8\u5316\uff0c\u5f71\u54cd\u8303\u56f4\u5305\u62ec\u8f66\u7aef\u5b58\u50a8\u6a21\u5757\u3001\u4e91\u7aef\u540c\u6b65\u6a21\u5757\u3001\u5220\u9664\u670d\u52a1\u3001\u5408\u89c4\u5ba1\u8ba1\u548c\u6d4b\u8bd5\u7528\u4f8b\u3002</p>",
            "<p>\u67b6\u6784\u5c42\u5fc5\u987b\u4fdd\u7559\u6765\u6e90\u6587\u6863\u3001\u7248\u672c\u3001\u7ae0\u8282\u548c\u9875\u7801\uff0c\u4f9b Agent \u8ffd\u6eaf\u8bc1\u636e\u3002</p>",
            "</body></html>",
            "",
        ]
    ),
    encoding="utf-8",
)

review_checklist = raw_dir / "review-checklist.txt"
review_checklist.write_text(
    "\n".join(
        [
            "\u91cd\u8981\u6570\u636e\u4ee3\u7801\u8bc4\u5ba1 checklist\uff1a",
            "1. \u68c0\u67e5\u91cd\u8981\u6570\u636e\u5b58\u50a8\u662f\u5426\u6709\u5b89\u5168\u8bbf\u95ee\u63a7\u5236\u548c\u52a0\u5bc6\u4fdd\u62a4\u3002",
            "2. \u68c0\u67e5\u91cd\u8981\u6570\u636e\u4f20\u8f93\u662f\u5426\u6709\u4fdd\u5bc6\u6027\u4fdd\u62a4\u63aa\u65bd\u3002",
            "3. \u68c0\u67e5\u5220\u9664\u903b\u8f91\u662f\u5426\u4fdd\u8bc1\u4e0d\u53ef\u68c0\u7d22\u4e14\u4e0d\u53ef\u8bbf\u95ee\u3002",
            "4. \u68c0\u67e5\u51fa\u5883\u94fe\u8def\u662f\u5426\u963b\u65ad\u8f66\u8f86\u76f4\u63a5\u5411\u5883\u5916\u4f20\u8f93\u91cd\u8981\u6570\u636e\u3002",
            "5. \u68c0\u67e5\u6d4b\u8bd5\u9879\u662f\u5426\u8986\u76d6\u5b58\u50a8\u3001\u4f20\u8f93\u3001\u5220\u9664\u3001\u51fa\u5883\u548c\u5ba1\u8ba1\u3002",
            "",
        ]
    ),
    encoding="utf-8",
)

docx_fixture = raw_dir / "supplier-interface.docx"
doc = Document()
doc.add_heading("Supplier Vehicle Data Interface", level=1)
doc.add_paragraph("Supplier interface SHALL preserve source document version and evidence id when returning vehicle data constraints.")
doc.add_paragraph("The interface SHALL expose storage, transmission, deletion, and cross-border transfer control points for downstream test design.")
doc.add_paragraph("Reviewers SHALL check permission control, encryption, confidentiality protection, deletion irrecoverability, outbound transfer blocking, and audit logging.")
doc.save(str(docx_fixture))

legacy_unsupported = raw_dir / "legacy-supplier-note.doc"
legacy_unsupported.write_text("legacy doc should be rejected as unsupported", encoding="utf-8")

rows = [
    ["sample_id", "file_path", "document_title", "slot_type", "owner", "project", "supplier", "document_version"],
    ["gbt-44464", str(gbt_target), "GBT 44464-2024 vehicle data requirements", "national standard", "checker", "vehicle-data", "GB", "v2024"],
    ["internal-spec", str(internal_spec), "Internal vehicle data SPEC", "internal spec", "checker", "vehicle-data", "internal", "v1"],
    ["architecture", str(architecture_doc), "Vehicle data architecture", "architecture", "checker", "vehicle-data", "internal", "v1"],
    ["review-checklist", str(review_checklist), "Important data review checklist", "review checklist", "checker", "vehicle-data", "internal", "v1"],
    ["supplier-docx", str(docx_fixture), "Supplier vehicle data interface", "supplier doc", "checker", "vehicle-data", "supplier", "v1"],
    ["legacy-doc", str(legacy_unsupported), "Legacy supplier DOC", "supplier doc", "checker", "vehicle-data", "supplier", "legacy"],
]
with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerows(rows)

scenarios = {
    "constraint-query": {
        "question": "\u91cd\u8981\u6570\u636e\u5b58\u50a8\u3001\u4f20\u8f93\u3001\u5220\u9664\u548c\u51fa\u5883\u6709\u54ea\u4e9b\u7ea6\u675f\uff1f\u53ea\u57fa\u4e8e\u6750\u6599\u56de\u7b54\uff0c\u5e76\u7ed9\u51fa\u8bc1\u636e\u6765\u6e90\u3002",
        "reference": ["\u91cd\u8981\u6570\u636e\u5b58\u50a8", "\u91cd\u8981\u6570\u636e\u4f20\u8f93", "\u91cd\u8981\u6570\u636e\u5220\u9664", "\u91cd\u8981\u6570\u636e\u51fa\u5883"],
    },
    "impact-analysis": {
        "question": "\u5982\u679c GB/T 44464-2024 \u91cd\u8981\u6570\u636e\u4f20\u8f93\u6216\u51fa\u5883\u8981\u6c42\u53d8\u5316\uff0c\u4f1a\u5f71\u54cd\u54ea\u4e9b\u5185\u90e8\u6a21\u5757\u3001SPEC \u548c\u6d4b\u8bd5\uff1f",
        "reference": ["\u8f66\u7aef\u5b58\u50a8\u6a21\u5757", "\u4e91\u7aef\u540c\u6b65\u6a21\u5757", "\u5220\u9664\u670d\u52a1", "\u5408\u89c4\u5ba1\u8ba1", "\u6d4b\u8bd5\u7528\u4f8b"],
    },
    "test-review-checklist": {
        "question": "\u9488\u5bf9\u91cd\u8981\u6570\u636e\u5904\u7406\u53d8\u66f4\uff0c\u6d4b\u8bd5\u548c\u8bc4\u5ba1 checklist \u5e94\u8986\u76d6\u54ea\u4e9b\u70b9\uff1f",
        "reference": ["\u5b89\u5168\u8bbf\u95ee\u63a7\u5236", "\u4fdd\u5bc6\u6027\u4fdd\u62a4", "\u4e0d\u53ef\u68c0\u7d22\u4e14\u4e0d\u53ef\u8bbf\u95ee", "\u963b\u65ad\u8f66\u8f86\u76f4\u63a5\u5411\u5883\u5916\u4f20\u8f93\u91cd\u8981\u6570\u636e", "\u5ba1\u8ba1"],
    },
}
for scenario_id, scenario in scenarios.items():
    scenario_dir = scenarios_dir / scenario_id
    scenario_dir.mkdir(parents=True, exist_ok=True)
    (scenario_dir / "question.md").write_text(scenario["question"], encoding="utf-8")
    reference = "# Context Pack\n\n" + "\n".join(f"- {item}" for item in scenario["reference"]) + "\n"
    (scenario_dir / "reference-context-pack.md").write_text(reference, encoding="utf-8")
'@ | & $pythonLauncher @($pythonArgsPrefix + @("-"))
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to prepare multi-document MVP fixtures."
    }

    Invoke-Python -Arguments @(
        "-m", "agent_knowledge_hub.cli",
        "manifest",
        "--manifest-path", $manifestPath,
        "--out-dir", $processedDir,
        "--project-root", $projectRoot
    )

    Invoke-Python -Arguments @(
        "-m", "agent_knowledge_hub.cli",
        "parse-quality-summary",
        "--processed-dir", $processedDir,
        "--output-dir", $qualityDir
    )

    foreach ($scenarioDir in Get-ChildItem -LiteralPath $scenariosDir -Directory) {
        Invoke-Python -Arguments @(
            "-m", "agent_knowledge_hub.cli",
            "context-pack",
            "--processed-dir", $processedDir,
            "--query-file", (Join-Path $scenarioDir.FullName "question.md"),
            "--top-k", "8",
            "--per-document-limit", "3",
            "--output-dir", $scenarioDir.FullName
        )
        Invoke-Python -Arguments @(
            "-m", "agent_knowledge_hub.cli",
            "gap-report",
            "--auto-context-pack-json", (Join-Path $scenarioDir.FullName "context_pack.json"),
            "--reference-markdown", (Join-Path $scenarioDir.FullName "reference-context-pack.md"),
            "--output-dir", (Join-Path $scenarioDir.FullName "gap-report")
        )
    }

    $env:AKH_MVP_RUN_ROOT = $runRoot
    $env:AKH_MVP_PROCESSED_DIR = $processedDir
    $env:AKH_MVP_TRACE_DIR = $traceDir
    $env:AKH_MVP_SUMMARY_PATH = $runSummaryPath
    @'
import json
import os
from pathlib import Path

from agent_knowledge_hub.retrieval import trace_evidence_in_processed_dir

run_root = Path(os.environ["AKH_MVP_RUN_ROOT"])
processed_dir = Path(os.environ["AKH_MVP_PROCESSED_DIR"])
trace_dir = Path(os.environ["AKH_MVP_TRACE_DIR"])
summary_path = Path(os.environ["AKH_MVP_SUMMARY_PATH"])
quality_path = run_root / "quality" / "parse-quality-summary.json"
ingest_summary_path = processed_dir / "ingest-summary.json"

quality = json.loads(quality_path.read_text(encoding="utf-8"))
ingest = json.loads(ingest_summary_path.read_text(encoding="utf-8"))

assert quality["processed_document_count"] >= 5, quality["processed_document_count"]
assert quality["failed_input_count"] >= 1, quality["failed_input_count"]
assert quality["allowed_document_count"] >= 4, quality["allowed_document_count"]
statuses = quality["status_counts"]
assert statuses.get("ok", 0) >= 4, statuses
assert statuses.get("unsupported", 0) >= 1, statuses
formats = {item.get("source_format") for item in quality.get("documents", [])}
for required_format in {"pdf", "markdown", "html", "text", "docx"}:
    assert required_format in formats, (required_format, formats)

scenario_results = []
for scenario_dir in sorted((run_root / "scenarios").iterdir()):
    if not scenario_dir.is_dir():
        continue
    context_pack_path = scenario_dir / "context_pack.json"
    gap_report_path = scenario_dir / "gap-report" / "context_pack_gap_report.json"
    markdown_path = scenario_dir / "context_pack.md"
    assert context_pack_path.exists(), context_pack_path
    assert gap_report_path.exists(), gap_report_path
    assert markdown_path.exists(), markdown_path

    context_pack = json.loads(context_pack_path.read_text(encoding="utf-8"))
    gap_report = json.loads(gap_report_path.read_text(encoding="utf-8"))
    selected_chunks = context_pack.get("selected_chunks") or []
    assert selected_chunks, scenario_dir.name
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Quality:" in markdown, scenario_dir.name
    assert any(item.get("quality_status") in {"ok", "recovered_by_fallback"} for item in selected_chunks), scenario_dir.name

    first_evidence_id = (selected_chunks[0].get("evidence_ids") or [None])[0]
    assert first_evidence_id, scenario_dir.name
    trace = trace_evidence_in_processed_dir(
        processed_dir=processed_dir,
        evidence_id=first_evidence_id,
    )
    trace_payload = trace.to_dict()
    trace_path = trace_dir / f"{scenario_dir.name}-trace.json"
    trace_path.write_text(
        json.dumps(trace_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    scenario_results.append(
        {
            "scenario_id": scenario_dir.name,
            "context_pack_json": str(context_pack_path),
            "context_pack_markdown": str(markdown_path),
            "gap_report_json": str(gap_report_path),
            "selected_chunk_count": len(selected_chunks),
            "selected_document_count": context_pack.get("document_count"),
            "missing_reference_item_count": gap_report.get("missing_reference_item_count"),
            "first_evidence_id": first_evidence_id,
            "first_trace_json": str(trace_path),
            "first_trace_document_title": trace_payload.get("document_title"),
            "first_trace_page": trace_payload.get("page"),
            "first_trace_source_path": trace_payload.get("source_path"),
        }
    )

summary = {
    "run_root": str(run_root),
    "raw_dir": str(run_root / "raw"),
    "manifest_path": str(run_root / "manifest.csv"),
    "processed_dir": str(processed_dir),
    "quality_summary_json": str(quality_path),
    "quality_summary_markdown": str(run_root / "quality" / "parse-quality-summary.md"),
    "ingest_summary_json": str(ingest_summary_path),
    "processed_count": ingest.get("processed_count"),
    "failed_count": ingest.get("failed_count"),
    "quality_status_counts": statuses,
    "allowed_document_count": quality.get("allowed_document_count"),
    "blocked_document_count": quality.get("blocked_document_count"),
    "documents": [
        {
            "title": item.get("title"),
            "source_format": item.get("source_format"),
            "parser_name": item.get("parser_name"),
            "quality_status": item.get("quality_status"),
            "quality_score": item.get("quality_score"),
            "allowed_for_context_pack": item.get("allowed_for_context_pack"),
            "warning_count": item.get("warning_count"),
            "source_path": item.get("source_path"),
        }
        for item in quality.get("documents", [])
    ],
    "failed_inputs": quality.get("failed_inputs", []),
    "scenarios": scenario_results,
}
summary_path.write_text(
    json.dumps(summary, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
'@ | & $pythonLauncher @($pythonArgsPrefix + @("-"))
    if ($LASTEXITCODE -ne 0) {
        throw "Multi-document E2E assertion failed with exit code $LASTEXITCODE."
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONUTF8 = $previousPythonUtf8
    $env:PYTHONIOENCODING = $previousPythonIoEncoding
    Remove-Item Env:\AKH_MVP_RUN_ROOT -ErrorAction SilentlyContinue
    Remove-Item Env:\AKH_MVP_RAW_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:\AKH_MVP_GBT_TARGET -ErrorAction SilentlyContinue
    Remove-Item Env:\AKH_MVP_MANIFEST_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:\AKH_MVP_SCENARIOS_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:\AKH_MVP_PROCESSED_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:\AKH_MVP_TRACE_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:\AKH_MVP_SUMMARY_PATH -ErrorAction SilentlyContinue
}

Write-Host "MULTIDOC_MVP_E2E=PASS"
Write-Host "RUN_ROOT=$runRoot"
Write-Host "SUMMARY=$runSummaryPath"
if (-not $KeepArtifacts) {
    Write-Host "Artifacts kept because this E2E is the MVP acceptance evidence."
}
