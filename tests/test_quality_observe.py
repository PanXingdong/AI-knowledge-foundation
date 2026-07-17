import json
import shutil
from pathlib import Path

import pytest

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.quality_observe import (
    evaluate_processed_dir_observe,
    write_quality_observation_bundle,
)


def _ingest(tmp_path: Path, name: str, text: str):
    source = tmp_path / f"{name}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=tmp_path / "processed",
        title=name,
        document_version="v1",
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            f"{json.dumps(row, ensure_ascii=False, sort_keys=True)}\n" for row in rows
        ),
        encoding="utf-8",
    )


def test_observe_keeps_all_chunks_but_records_would_exclude(tmp_path: Path):
    healthy = _ingest(tmp_path, "healthy", "# Healthy\n\nEnough healthy content.")
    broken = _ingest(tmp_path, "broken", "# Broken\n\nBroken evidence content.")
    rows = _read_jsonl(broken.chunks_jsonl_path)
    rows[0]["evidence_ids"] = ["span_missing"]
    _write_jsonl(broken.chunks_jsonl_path, rows)

    result = evaluate_processed_dir_observe(tmp_path / "processed")

    all_chunk_ids = {
        str(row["chunk_id"])
        for path in (healthy.chunks_jsonl_path, broken.chunks_jsonl_path)
        for row in _read_jsonl(path)
    }
    assert set(result.publication_preview.all_chunk_ids) == all_chunk_ids
    assert set(result.publication_preview.would_exclude_chunk_ids)
    assert all(
        decision.effective_action in {"allow", "warn"}
        for decision in result.report.decisions
    )


def test_observe_result_is_deterministic(tmp_path: Path):
    _ingest(tmp_path, "healthy", "# Healthy\n\nEnough healthy content.")

    first = evaluate_processed_dir_observe(tmp_path / "processed")
    second = evaluate_processed_dir_observe(tmp_path / "processed")

    assert first.report.to_dict() == second.report.to_dict()
    assert first.publication_preview.to_dict() == second.publication_preview.to_dict()
    assert first.quarantine_preview.to_dict() == second.quarantine_preview.to_dict()
    assert first.detector_errors == second.detector_errors
    assert first.markdown == second.markdown


def test_block_quarantine_propagates_to_every_referencing_chunk(tmp_path: Path):
    ingested = _ingest(tmp_path, "broken", "# Broken\n\nEvidence content.")
    canonical = json.loads(ingested.document_json_path.read_text(encoding="utf-8"))
    evidence = canonical["evidence_spans"][0]
    evidence["text_hash"] = "0" * 64
    ingested.document_json_path.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rows = _read_jsonl(ingested.chunks_jsonl_path)
    rows.append({**rows[0], "chunk_id": "chunk_second_reference"})
    _write_jsonl(ingested.chunks_jsonl_path, rows)

    observation = evaluate_processed_dir_observe(tmp_path / "processed")

    expected_chunk_ids = {str(row["chunk_id"]) for row in rows}
    assert expected_chunk_ids <= set(
        observation.publication_preview.would_exclude_chunk_ids
    )
    source = next(
        decision
        for decision in observation.report.decisions
        if "block.evidence.hash_mismatch" in decision.reason_codes
    )
    propagated = [
        item
        for item in observation.quarantine_preview.items
        if item["scope"] == "chunk"
        and item["object_id"] in expected_chunk_ids
        and item.get("propagated") is True
    ]
    assert {item["object_id"] for item in propagated} == expected_chunk_ids
    assert {item["source_decision_id"] for item in propagated} == {
        source.decision_id
    }


def test_page_quarantine_propagates_by_evidence_reference(tmp_path: Path):
    ingested = _ingest(tmp_path, "paged", "# Paged\n\nEvidence content.")
    canonical = json.loads(ingested.document_json_path.read_text(encoding="utf-8"))
    canonical["parse_report"]["page_count"] = 1
    canonical["evidence_spans"][0]["page"] = 2
    ingested.document_json_path.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    chunk_id = str(_read_jsonl(ingested.chunks_jsonl_path)[0]["chunk_id"])

    observation = evaluate_processed_dir_observe(tmp_path / "processed")

    source = next(
        decision
        for decision in observation.report.decisions
        if "page.integrity.reference_out_of_range" in decision.reason_codes
    )
    assert chunk_id in observation.publication_preview.would_exclude_chunk_ids
    assert any(
        item["scope"] == "chunk"
        and item["object_id"] == chunk_id
        and item.get("source_decision_id") == source.decision_id
        for item in observation.quarantine_preview.items
    )


def test_document_block_propagates_to_all_document_chunks(tmp_path: Path):
    ingested = _ingest(tmp_path, "broken", "# Broken\n\nEvidence content.")
    rows = _read_jsonl(ingested.chunks_jsonl_path)
    rows.append({**rows[0], "chunk_id": "chunk_second"})
    _write_jsonl(ingested.chunks_jsonl_path, rows)
    ingested.processing_record_path.unlink()

    observation = evaluate_processed_dir_observe(tmp_path / "processed")

    document_decision = next(
        decision
        for decision in observation.report.decisions
        if "document.integrity.processing_record_missing" in decision.reason_codes
    )
    assert {str(row["chunk_id"]) for row in rows} <= set(
        observation.publication_preview.would_exclude_chunk_ids
    )
    assert {
        item["source_decision_id"]
        for item in observation.quarantine_preview.items
        if item.get("propagated") is True
        and item["object_id"] in {str(row["chunk_id"]) for row in rows}
    } >= {document_decision.decision_id}


def test_quarantine_items_are_stably_sorted_and_reference_sources(tmp_path: Path):
    ingested = _ingest(tmp_path, "broken", "# Broken\n\nEvidence content.")
    canonical = json.loads(ingested.document_json_path.read_text(encoding="utf-8"))
    canonical["evidence_spans"][0]["text_hash"] = "0" * 64
    ingested.document_json_path.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    observation = evaluate_processed_dir_observe(tmp_path / "processed")
    items = observation.quarantine_preview.items

    assert list(items) == sorted(
        items,
        key=lambda item: (
            item["scope"],
            item["object_id"],
            item.get("source_decision_id", item["decision_id"]),
            item["decision_id"],
        ),
    )
    decision_ids = {item.decision_id for item in observation.report.decisions}
    assert all(
        item.get("source_decision_id", item["decision_id"]) in decision_ids
        for item in items
    )


def test_empty_processed_tree_records_would_block_release(tmp_path: Path):
    result = evaluate_processed_dir_observe(tmp_path)

    assert result.report.summary["signal_count"] == 1
    assert result.report.decisions[0].recommended_action == "block_release"
    assert result.report.decisions[0].effective_action == "allow"
    assert result.publication_preview.all_chunk_ids == ()


def test_ingest_failure_becomes_document_would_block_and_no_documents(tmp_path: Path):
    (tmp_path / "ingest-summary.json").write_text(
        json.dumps(
            {
                "failed": [
                    {
                        "sample_id": "bad-pdf",
                        "file_path": "bad.pdf",
                        "reason": "OCR parse failed",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_processed_dir_observe(tmp_path)

    assert {
        decision.reason_codes[0] for decision in result.report.decisions
    } == {"document.parse.failed", "release.integrity.no_documents"}
    assert {
        decision.recommended_action for decision in result.report.decisions
    } == {"block_document", "block_release"}
    assert all(
        decision.effective_action == "allow" for decision in result.report.decisions
    )


def test_ingest_failure_fingerprint_ignores_absolute_file_path(tmp_path: Path):
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        root.mkdir()
        (root / "ingest-summary.json").write_text(
            json.dumps(
                {
                    "failed": [
                        {
                            "sample_id": "bad-pdf",
                            "file_path": str(root.resolve() / "bad.pdf"),
                            "reason": "OCR parse failed",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    first = evaluate_processed_dir_observe(roots[0])
    second = evaluate_processed_dir_observe(roots[1])

    assert first.report.artifact_fingerprint == second.report.artifact_fingerprint
    assert (
        first.report.determinism_fingerprint
        == second.report.determinism_fingerprint
    )


def test_copied_processed_tree_has_path_independent_fingerprints(tmp_path: Path):
    ingested = _ingest(tmp_path / "source", "healthy", "# Healthy\n\nContent.")
    copied_root = tmp_path / "elsewhere" / "processed"
    shutil.copytree(ingested.output_dir.parents[1], copied_root)

    first = evaluate_processed_dir_observe(ingested.output_dir.parents[1])
    second = evaluate_processed_dir_observe(copied_root)

    assert first.report.artifact_fingerprint == second.report.artifact_fingerprint
    assert (
        first.report.determinism_fingerprint
        == second.report.determinism_fingerprint
    )


def test_malformed_document_does_not_block_other_document_report(tmp_path: Path):
    malformed = _ingest(tmp_path, "malformed", "# Bad\n\nMalformed content.")
    healthy = _ingest(tmp_path, "healthy", "# Good\n\nHealthy content.")
    malformed.document_json_path.write_text("{invalid", encoding="utf-8")

    result = evaluate_processed_dir_observe(tmp_path / "processed")

    assert healthy.document_version_id in result.report.document_version_ids
    assert malformed.document_version_id not in result.report.document_version_ids
    assert len(result.report.document_version_ids) == 2
    assert "document.integrity.canonical_invalid" in {
        signal.reason_code for signal in result.report.signals
    }


def test_evaluator_error_is_recorded_without_interrupting_other_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    broken = _ingest(tmp_path, "broken", "# Bad\n\nBroken evaluator.")
    healthy = _ingest(tmp_path, "healthy", "# Good\n\nHealthy evaluator.")
    import agent_knowledge_hub.quality_observe as observe

    real_evaluate = observe.evaluate_document_version

    def fail_one(version_dir: Path):
        if version_dir == broken.output_dir:
            raise RuntimeError("unstable detector detail")
        return real_evaluate(version_dir)

    monkeypatch.setattr(observe, "evaluate_document_version", fail_one)

    result = evaluate_processed_dir_observe(tmp_path / "processed")

    assert healthy.document_version_id in result.report.document_version_ids
    assert result.report.summary["detector_error"] == 1
    assert result.detector_errors == (
        {
            "error_type": "RuntimeError",
            "object_id": broken.document_version_id,
            "scope": "document",
        },
    )
    assert "unstable detector detail" not in result.markdown
    assert "RuntimeError" in result.markdown
    assert broken.document_version_id in result.markdown


def test_bundle_contains_all_four_json_ready_files(tmp_path: Path):
    _ingest(tmp_path, "healthy", "# Healthy\n\nEnough healthy content.")
    result = evaluate_processed_dir_observe(tmp_path / "processed")

    paths = write_quality_observation_bundle(tmp_path / "report", result)

    assert set(paths) == {
        "report_json",
        "report_markdown",
        "publication_preview",
        "quarantine_preview",
    }
    assert all(path.is_file() for path in paths.values())
    assert json.loads(paths["report_json"].read_text(encoding="utf-8"))[
        "determinism_fingerprint"
    ] == result.report.determinism_fingerprint
    assert json.loads(paths["publication_preview"].read_text(encoding="utf-8"))
    assert json.loads(paths["quarantine_preview"].read_text(encoding="utf-8"))


def test_markdown_decision_lines_are_sorted(tmp_path: Path):
    ingested = _ingest(tmp_path, "broken", "# Broken\n\nEvidence content.")
    rows = _read_jsonl(ingested.chunks_jsonl_path)
    rows[0]["evidence_ids"] = ["span_missing"]
    _write_jsonl(ingested.chunks_jsonl_path, rows)

    result = evaluate_processed_dir_observe(tmp_path / "processed")
    decision_lines = [
        line for line in result.markdown.splitlines() if line.startswith("- `decision_")
    ]

    assert decision_lines == sorted(decision_lines)
