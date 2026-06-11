import json
from pathlib import Path

from agent_knowledge_hub.cli import main
from agent_knowledge_hub.contract import validate_processed_dir
from agent_knowledge_hub.models import CANONICAL_DOCUMENT_SCHEMA_VERSION


def _write_manual_processed_sample(
    processed_root: Path,
    *,
    missing_evidence: bool = False,
    schema_version: str | None = CANONICAL_DOCUMENT_SCHEMA_VERSION,
) -> None:
    version_dir = processed_root / "demo-spec" / "docver_demo_v1"
    version_dir.mkdir(parents=True)

    canonical = {
        "document": {
            "document_id": "doc_demo",
            "title": "Demo SPEC",
            "source_type": "internal_spec",
            "owner": "checker",
            "project": "demo",
            "supplier": "internal",
            "created_at": "2026-06-10T00:00:00Z",
        },
        "document_version": {
            "document_version_id": "docver_demo_v1",
            "document_id": "doc_demo",
            "version": "v1",
            "file_path": "samples/golden/demo-spec.md",
            "file_hash": "sha256_demo",
            "created_at": "2026-06-10T00:00:00Z",
        },
        "sections": [
            {
                "section_id": "sec_demo_1",
                "document_version_id": "docver_demo_v1",
                "section_path": ["1"],
                "title": "Safety Constraint",
                "page_start": 1,
                "page_end": 1,
            }
        ],
        "blocks": [
            {
                "block_id": "blk_demo_1",
                "document_version_id": "docver_demo_v1",
                "block_type": "paragraph",
                "text": "Important data outbound transfer requires safety assessment.",
                "page_start": 1,
                "page_end": 1,
                "section_path": ["1"],
                "order": 1,
                "metadata": {},
            }
        ],
        "evidence_spans": [
            {
                "evidence_id": "span_demo_1",
                "document_version_id": "docver_demo_v1",
                "page": 1,
                "section_path": ["1"],
                "block_id": "blk_demo_1",
                "bbox": None,
                "text": "Important data outbound transfer requires safety assessment.",
                "text_hash": "sha256_text_demo",
            }
        ],
        "parse_report": {
            "parser_name": "manual-golden-sample",
            "source_format": "manual",
            "page_count": 1,
            "section_count": 1,
            "block_count": 1,
            "table_count": 0,
            "has_page_numbers": True,
            "warnings": [],
            "quality_report": {
                "status": "ok",
                "score": 100.0,
                "fallback_used": False,
                "fallback_parser": None,
                "reason_codes": [],
            },
        },
    }
    if schema_version is not None:
        canonical["schema_version"] = schema_version

    chunk = {
        "chunk_id": "chunk_demo_1",
        "document_version_id": "docver_demo_v1",
        "section_path": ["1"],
        "page_start": 1,
        "page_end": 1,
        "text": "Important data outbound transfer requires safety assessment.",
        "evidence_ids": ["span_missing"] if missing_evidence else ["span_demo_1"],
        "embedding_id": None,
        "metadata": {
            "document_id": "doc_demo",
            "document_title": "Demo SPEC",
            "source_type": "internal_spec",
        },
    }

    (version_dir / "canonical-document.json").write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (version_dir / "chunks.jsonl").write_text(
        json.dumps(chunk, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_validate_processed_dir_accepts_manual_contract_sample(tmp_path: Path):
    processed_root = tmp_path / "processed"
    _write_manual_processed_sample(processed_root)

    summary = validate_processed_dir(processed_root)

    assert summary.is_valid
    assert summary.document_count == 1
    assert summary.chunk_count == 1
    assert summary.error_count == 0
    assert "docver_demo_v1" in summary.markdown


def test_validate_processed_dir_rejects_missing_schema_version(tmp_path: Path):
    processed_root = tmp_path / "processed"
    _write_manual_processed_sample(processed_root, schema_version=None)

    summary = validate_processed_dir(processed_root)

    assert not summary.is_valid
    assert summary.error_count == 1
    assert summary.errors[0]["code"] == "missing_schema_version"


def test_validate_processed_dir_rejects_unsupported_schema_version(tmp_path: Path):
    processed_root = tmp_path / "processed"
    _write_manual_processed_sample(processed_root, schema_version="layer1.processed.v0")

    summary = validate_processed_dir(processed_root)

    assert not summary.is_valid
    assert summary.error_count == 1
    assert summary.errors[0]["code"] == "unsupported_schema_version"
    assert summary.errors[0]["schema_version"] == "layer1.processed.v0"


def test_validate_processed_dir_reports_missing_evidence_reference(tmp_path: Path):
    processed_root = tmp_path / "processed"
    _write_manual_processed_sample(processed_root, missing_evidence=True)

    summary = validate_processed_dir(processed_root)

    assert not summary.is_valid
    assert summary.error_count == 1
    assert summary.errors[0]["code"] == "unknown_evidence_id"
    assert summary.errors[0]["chunk_id"] == "chunk_demo_1"


def test_validate_processed_cli_returns_nonzero_when_required_and_invalid(
    tmp_path: Path,
    capsys,
):
    processed_root = tmp_path / "processed"
    _write_manual_processed_sample(processed_root, missing_evidence=True)

    exit_code = main(
        [
            "validate-processed",
            "--processed-dir",
            str(processed_root),
            "--require-valid",
        ]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "unknown_evidence_id" in captured.err
