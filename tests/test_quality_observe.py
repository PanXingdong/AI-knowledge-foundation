import json
import shutil
from pathlib import Path

import pytest

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.quality_models import ObservedQualitySignal
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
        and item["decision_id"] == source.decision_id
    ]
    assert {item["object_id"] for item in propagated} == expected_chunk_ids


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
        and item["decision_id"] == source.decision_id
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
        item["decision_id"]
        for item in observation.quarantine_preview.items
        if item["scope"] == "chunk"
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
            item["decision_id"],
        ),
    )
    decision_ids = {item.decision_id for item in observation.report.decisions}
    assert all(item["decision_id"] in decision_ids for item in items)


def test_direct_chunk_quarantine_is_not_duplicated_by_self_propagation(
    tmp_path: Path,
):
    ingested = _ingest(tmp_path, "broken", "# Broken\n\nEvidence content.")
    canonical = json.loads(ingested.document_json_path.read_text(encoding="utf-8"))
    canonical["evidence_spans"][0]["text_hash"] = "0" * 64
    ingested.document_json_path.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rows = _read_jsonl(ingested.chunks_jsonl_path)
    rows[0]["text"] = ""
    _write_jsonl(ingested.chunks_jsonl_path, rows)

    observation = evaluate_processed_dir_observe(tmp_path / "processed")
    chunk_id = str(rows[0]["chunk_id"])
    chunk_items = [
        item
        for item in observation.quarantine_preview.items
        if item["scope"] == "chunk" and item["object_id"] == chunk_id
    ]
    keys = [
        (item["scope"], item["object_id"], item["decision_id"])
        for item in observation.quarantine_preview.items
    ]
    direct = next(
        decision
        for decision in observation.report.decisions
        if decision.scope == "chunk"
        and "chunk.integrity.empty" in decision.reason_codes
    )
    block_source = next(
        decision
        for decision in observation.report.decisions
        if "block.evidence.hash_mismatch" in decision.reason_codes
    )

    assert len(keys) == len(set(keys))
    assert [
        item
        for item in chunk_items
        if item["decision_id"] == direct.decision_id
    ] == [
        {
            "decision_id": direct.decision_id,
            "object_id": chunk_id,
            "reason_codes": ["chunk.integrity.empty"],
            "recommended_action": "quarantine",
            "scope": "chunk",
        }
    ]
    assert any(
        item["decision_id"] == block_source.decision_id
        for item in chunk_items
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


def test_failed_input_identity_cannot_block_real_document_with_same_raw_id(
    tmp_path: Path,
):
    healthy = _ingest(tmp_path, "healthy", "# Healthy\n\nHealthy content.")
    (tmp_path / "processed" / "ingest-summary.json").write_text(
        json.dumps(
            {
                "failed": [
                    {
                        "sample_id": healthy.document_version_id,
                        "file_path": "failed.pdf",
                        "reason": "OCR parse failed",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    chunk_ids = {
        str(row["chunk_id"]) for row in _read_jsonl(healthy.chunks_jsonl_path)
    }

    result = evaluate_processed_dir_observe(tmp_path / "processed")
    parse_signal = next(
        signal
        for signal in result.report.signals
        if signal.reason_code == "document.parse.failed"
    )

    assert parse_signal.object_id.startswith("failed-input:")
    assert parse_signal.object_id != healthy.document_version_id
    assert not (
        chunk_ids & set(result.publication_preview.would_exclude_chunk_ids)
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


@pytest.mark.parametrize(
    ("sidecar_name", "reason_code"),
    [
        (
            "processing-record.json",
            "document.integrity.processing_record_invalid",
        ),
        ("quality-record.json", "document.integrity.quality_record_invalid"),
    ],
)
def test_sidecar_only_directory_is_evaluated_as_document(
    tmp_path: Path,
    sidecar_name: str,
    reason_code: str,
):
    version_dir = tmp_path / "processed" / "sidecar-only" / "version"
    version_dir.mkdir(parents=True)
    (version_dir / sidecar_name).write_text("{invalid", encoding="utf-8")

    result = evaluate_processed_dir_observe(tmp_path / "processed")

    assert reason_code in {signal.reason_code for signal in result.report.signals}
    assert "document.integrity.canonical_missing" in {
        signal.reason_code for signal in result.report.signals
    }
    assert "release.integrity.no_documents" not in {
        signal.reason_code for signal in result.report.signals
    }
    assert len(result.report.document_version_ids) == 1


def test_duplicate_sidecar_only_artifacts_are_one_deterministic_logical_document(
    tmp_path: Path,
):
    processed = tmp_path / "processed"
    first_dir = processed / "first-name" / "version"
    first_dir.mkdir(parents=True)
    (first_dir / "processing-record.json").write_text(
        "{invalid",
        encoding="utf-8",
    )
    single = evaluate_processed_dir_observe(processed)
    second_dir = processed / "different-name" / "version"
    second_dir.mkdir(parents=True)
    (second_dir / "processing-record.json").write_text(
        "{invalid",
        encoding="utf-8",
    )

    duplicated = evaluate_processed_dir_observe(processed)
    repeated = evaluate_processed_dir_observe(processed)

    assert duplicated.report.to_dict() == single.report.to_dict()
    assert duplicated.report.to_dict() == repeated.report.to_dict()
    assert (
        duplicated.publication_preview.to_dict()
        == repeated.publication_preview.to_dict()
    )
    assert (
        duplicated.quarantine_preview.to_dict()
        == repeated.quarantine_preview.to_dict()
    )
    assert len(duplicated.report.document_version_ids) == 1
    assert len(duplicated.report.signals) == len(
        {item.signal_id for item in duplicated.report.signals}
    )
    assert len(duplicated.report.decisions) == len(
        {item.decision_id for item in duplicated.report.decisions}
    )
    assert len(duplicated.publication_preview.decision_ids) == len(
        set(duplicated.publication_preview.decision_ids)
    )
    assert len(duplicated.publication_preview.all_chunk_ids) == len(
        set(duplicated.publication_preview.all_chunk_ids)
    )

    paths = write_quality_observation_bundle(tmp_path / "bundle", duplicated)
    jsonschema = pytest.importorskip("jsonschema")
    schema_root = (
        Path(__file__).parents[1] / "schemas" / "knowledge-quality.v1"
    )
    for path_key, schema_name in (
        ("report_json", "quality-report.schema.json"),
        ("publication_preview", "publication-preview.schema.json"),
        ("quarantine_preview", "quarantine-preview.schema.json"),
    ):
        payload = json.loads(paths[path_key].read_text(encoding="utf-8"))
        schema = json.loads((schema_root / schema_name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(payload)


def test_unresolved_fallback_identity_uses_content_not_directory_names(
    tmp_path: Path,
):
    import agent_knowledge_hub.quality_observe as observe

    first = tmp_path / "first-name"
    same = tmp_path / "different-name"
    changed = tmp_path / "third-name"
    for root, content in (
        (first, "{invalid"),
        (same, "{invalid"),
        (changed, "{different"),
    ):
        root.mkdir()
        (root / "processing-record.json").write_text(content, encoding="utf-8")

    first_id = observe._unresolved_document_identity(first)

    assert first_id == observe._unresolved_document_identity(same)
    assert first_id != observe._unresolved_document_identity(changed)


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
    signal = next(
        signal
        for signal in result.report.signals
        if signal.reason_code == "document.evaluator.detector_error"
    )
    decision = next(
        decision
        for decision in result.report.decisions
        if decision.signal_ids == (signal.signal_id,)
    )

    assert signal.object_id == broken.document_version_id
    assert signal.document_version_id == broken.document_version_id
    assert signal.actual_value == "RuntimeError"
    assert decision.recommended_action == "block_document"
    assert decision.effective_action == "allow"
    assert broken.document_version_id in (
        result.publication_preview.would_exclude_document_version_ids
    )


def test_bundle_contains_all_four_json_ready_files(tmp_path: Path):
    ingested = _ingest(tmp_path, "broken", "# Broken\n\nEvidence content.")
    canonical = json.loads(ingested.document_json_path.read_text(encoding="utf-8"))
    canonical["evidence_spans"][0]["text_hash"] = "0" * 64
    ingested.document_json_path.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result = evaluate_processed_dir_observe(tmp_path / "processed")

    paths = write_quality_observation_bundle(tmp_path / "report", result)

    assert set(paths) == {
        "report_json",
        "report_markdown",
        "publication_preview",
        "quarantine_preview",
    }
    assert all(path.is_file() for path in paths.values())
    report_payload = json.loads(paths["report_json"].read_text(encoding="utf-8"))
    assert report_payload == result.report.to_dict()
    jsonschema = pytest.importorskip("jsonschema")
    schema_root = (
        Path(__file__).parents[1] / "schemas" / "knowledge-quality.v1"
    )
    for path_key, schema_name in (
        ("report_json", "quality-report.schema.json"),
        ("publication_preview", "publication-preview.schema.json"),
        ("quarantine_preview", "quarantine-preview.schema.json"),
    ):
        payload = json.loads(paths[path_key].read_text(encoding="utf-8"))
        schema = json.loads((schema_root / schema_name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(payload)


def test_synthetic_empty_and_failed_reports_validate_schema(tmp_path: Path):
    failed_root = tmp_path / "failed"
    failed_root.mkdir()
    (failed_root / "ingest-summary.json").write_text(
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
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = (
        Path(__file__).parents[1]
        / "schemas"
        / "knowledge-quality.v1"
        / "quality-report.schema.json"
    )
    validator = jsonschema.Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8"))
    )

    validator.validate(evaluate_processed_dir_observe(tmp_path).report.to_dict())
    validator.validate(
        evaluate_processed_dir_observe(failed_root).report.to_dict()
    )


def test_bundle_writes_each_file_through_same_directory_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _ingest(tmp_path, "healthy", "# Healthy\n\nEnough healthy content.")
    result = evaluate_processed_dir_observe(tmp_path / "processed")
    output_dir = (tmp_path / "report").resolve()
    replacements: list[tuple[Path, Path]] = []
    real_replace = Path.replace

    def recording_replace(source: Path, target: Path):
        replacements.append((source, target))
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", recording_replace)

    paths = write_quality_observation_bundle(output_dir, result)

    assert {target for _, target in replacements} == set(paths.values())
    assert all(source.parent == target.parent for source, target in replacements)
    assert all(source.name.endswith(".tmp") for source, _ in replacements)
    assert not list(output_dir.glob("*.tmp"))


def test_determinism_fingerprint_covers_propagated_previews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    ingested = _ingest(tmp_path, "healthy", "# Healthy\n\nEnough healthy content.")
    canonical = json.loads(ingested.document_json_path.read_text(encoding="utf-8"))
    evidence_id = str(canonical["evidence_spans"][0]["evidence_id"])
    block_id = str(canonical["evidence_spans"][0]["block_id"])
    rows = _read_jsonl(ingested.chunks_jsonl_path)
    rows[0]["evidence_ids"] = []
    _write_jsonl(ingested.chunks_jsonl_path, rows)
    import agent_knowledge_hub.quality_observe as observe

    signal = ObservedQualitySignal.create(
        reason_code="block.evidence.hash_mismatch",
        scope="block",
        object_id=block_id,
        detector="fixed-test-detector",
        detector_version="1",
        metric_name="fixed",
        actual_value=False,
        threshold=True,
        confidence=1.0,
        severity="error",
        document_version_id=ingested.document_version_id,
        block_id=block_id,
        evidence_ids=(evidence_id,),
    )
    monkeypatch.setattr(observe, "artifact_fingerprint", lambda artifacts: "fixed")
    monkeypatch.setattr(
        observe,
        "evaluate_document_version",
        lambda version_dir: (signal,),
    )

    without_propagation = evaluate_processed_dir_observe(tmp_path / "processed")
    rows[0]["evidence_ids"] = [evidence_id]
    _write_jsonl(ingested.chunks_jsonl_path, rows)
    with_propagation = evaluate_processed_dir_observe(tmp_path / "processed")

    assert (
        without_propagation.report.signals == with_propagation.report.signals
    )
    assert (
        without_propagation.report.decisions == with_propagation.report.decisions
    )
    assert (
        without_propagation.publication_preview.to_dict()
        != with_propagation.publication_preview.to_dict()
    )
    assert (
        without_propagation.report.determinism_fingerprint
        != with_propagation.report.determinism_fingerprint
    )


def test_determinism_fingerprint_covers_all_bundle_schema_versions():
    import agent_knowledge_hub.quality_observe as observe

    payload = {"stable": "payload"}
    current = observe._determinism_fingerprint(payload)

    assert current != observe._determinism_fingerprint(
        payload,
        quality_report_schema_version="knowledge-quality-report.v2",
    )
    assert current != observe._determinism_fingerprint(
        payload,
        publication_preview_schema_version="knowledge-publication-preview.v2",
    )
    assert current != observe._determinism_fingerprint(
        payload,
        quarantine_preview_schema_version="knowledge-quarantine-preview.v2",
    )


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
