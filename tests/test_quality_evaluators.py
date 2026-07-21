import json
import shutil
from pathlib import Path

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.processing_record import (
    build_processing_record,
    write_processing_record,
)
from agent_knowledge_hub.quality_contracts import (
    build_quality_record,
    write_quality_record,
)
from agent_knowledge_hub.quality_evaluators import (
    SOFT_MAX_BLOCK_CHARS,
    SOFT_MIN_CHUNK_CHARS,
    SOFT_MIN_PAGE_CHARS,
    SOFT_WARNING_COUNT,
    artifact_fingerprint,
    evaluate_document_version,
    load_document_artifacts,
)
from agent_knowledge_hub.quality_registry import REASON_CODE_REGISTRY
from agent_knowledge_hub.utils import (
    file_sha256,
    sha256_text,
    stable_id,
    write_json,
)


def _ingest(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "healthy.md"
    source.write_text("# API\n\nMsgSend sends a message.", encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=tmp_path / "processed",
        title="Healthy API",
        document_version="v1",
    )


def _reason_codes(version_dir: Path) -> set[str]:
    return {item.reason_code for item in evaluate_document_version(version_dir)}


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


def _refresh_case_sidecars(result, canonical, chunks) -> None:
    write_processing_record(
        result.processing_record_path,
        build_processing_record(
            document_version_id=canonical["document_version"][
                "document_version_id"
            ],
            source_file_hash=canonical["document_version"]["file_hash"],
            parser_name=canonical["parse_report"]["parser_name"],
            canonical_path=result.document_json_path,
            chunks_path=result.chunks_jsonl_path,
        ),
    )
    write_quality_record(
        result.quality_record_path,
        build_quality_record(canonical, chunks),
    )


def _build_case(root: Path, case: dict[str, object]) -> Path:
    root.mkdir(parents=True)
    source = root / "synthetic-public.md"
    source.write_text(
        "# Public API\n\n"
        "This synthetic public fixture describes message delivery behavior "
        "without containing supplier documentation or confidential data.",
        encoding="utf-8",
    )
    result = ingest_file(
        file_path=source,
        out_dir=root / "processed",
        title=f"Golden {case['case_id']}",
        document_version="v1",
    )
    canonical = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    chunks = _read_jsonl(result.chunks_jsonl_path)
    canonical["document"]["supplier"] = case["supplier"]
    canonical["parse_report"]["source_format"] = "pdf"
    canonical["parse_report"]["has_page_numbers"] = True
    canonical["parse_report"]["page_count"] = 1
    for block in canonical["blocks"]:
        block["page_start"] = 1
        block["page_end"] = 1
    for evidence in canonical["evidence_spans"]:
        evidence["page"] = 1
    for section in canonical["sections"]:
        section["page_start"] = 1
        section["page_end"] = 1
    for chunk in chunks:
        chunk["page_start"] = 1
        chunk["page_end"] = 1
    defect = case["defect"]
    if defect == "missing_chunk_evidence":
        chunks[0]["evidence_ids"] = ["span_missing"]
    elif defect == "page_out_of_range":
        canonical["blocks"][0]["page_start"] = 2
        canonical["blocks"][0]["page_end"] = 1
    elif defect == "duplicate_chunk":
        chunks.append({**chunks[0], "chunk_id": "chunk_z_duplicate"})
    elif defect != "none":
        raise AssertionError(f"unknown golden defect: {defect}")
    write_json(result.document_json_path, canonical)
    _write_jsonl(result.chunks_jsonl_path, chunks)
    _refresh_case_sidecars(result, canonical, chunks)
    return result.output_dir


def test_golden_cases_match_expected_signals(tmp_path: Path):
    cases = json.loads(
        (Path(__file__).parent / "fixtures" / "quality" / "cases.json").read_text(
            encoding="utf-8"
        )
    )
    for case in cases:
        version_dir = _build_case(tmp_path / case["case_id"], case)
        signals = evaluate_document_version(version_dir)
        actual_codes = sorted({item.reason_code for item in signals})
        hard_count = sum(
            1 for item in signals if item.severity in {"error", "fatal"}
        )
        for expected in case["expected_reason_codes"]:
            assert expected in actual_codes, case["case_id"]
        assert hard_count == case["expected_hard_count"], case["case_id"]


def test_healthy_document_has_no_hard_integrity_signal(tmp_path: Path):
    result = _ingest(tmp_path)

    signals = evaluate_document_version(result.output_dir)

    assert not {
        item.reason_code
        for item in signals
        if item.severity in {"error", "fatal"}
    }


def test_missing_chunks_is_document_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    result.chunks_jsonl_path.unlink()

    assert "document.integrity.chunks_missing" in _reason_codes(result.output_dir)


def test_invalid_canonical_json_is_safe_document_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    result.document_json_path.write_text("{", encoding="utf-8")

    artifacts = load_document_artifacts(result.output_dir)

    assert artifacts.load_errors == ("canonical_invalid_json",)
    assert "document.integrity.canonical_invalid" in _reason_codes(
        result.output_dir
    )
    assert "document.integrity.canonical_missing" not in _reason_codes(
        result.output_dir
    )


def test_invalid_chunks_json_is_safe_document_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    result.chunks_jsonl_path.write_text("{not-json}\n", encoding="utf-8")

    artifacts = load_document_artifacts(result.output_dir)

    assert artifacts.load_errors == ("chunks_invalid_json",)
    assert "document.integrity.chunks_invalid" in _reason_codes(result.output_dir)
    assert "document.integrity.no_chunks" not in _reason_codes(result.output_dir)


def test_partially_invalid_chunks_preserve_valid_rows_and_signal_invalid(
    tmp_path: Path,
):
    result = _ingest(tmp_path)
    original = result.chunks_jsonl_path.read_text(encoding="utf-8")
    result.chunks_jsonl_path.write_text(
        original + "{not-json}\n",
        encoding="utf-8",
    )

    artifacts = load_document_artifacts(result.output_dir)
    codes = _reason_codes(result.output_dir)

    assert len(artifacts.chunks) == 1
    assert artifacts.load_errors == ("chunks_invalid_json",)
    assert "document.integrity.chunks_invalid" in codes
    assert "document.integrity.no_chunks" not in codes


def test_invalid_processing_record_is_document_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    result.processing_record_path.write_text("{", encoding="utf-8")

    artifacts = load_document_artifacts(result.output_dir)

    assert artifacts.load_errors == ("processing_record_invalid_json",)
    assert (
        "document.integrity.processing_record_invalid"
        in _reason_codes(result.output_dir)
    )
    assert (
        "document.integrity.processing_record_missing"
        not in _reason_codes(result.output_dir)
    )


def test_invalid_quality_record_is_document_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    result.quality_record_path.write_text("[]", encoding="utf-8")

    artifacts = load_document_artifacts(result.output_dir)

    assert artifacts.load_errors == ("quality_record_invalid_json",)
    assert (
        "document.integrity.quality_record_invalid"
        in _reason_codes(result.output_dir)
    )
    assert (
        "document.integrity.quality_record_missing"
        not in _reason_codes(result.output_dir)
    )


def test_unknown_chunk_evidence_is_hard_signal_with_reference_id(tmp_path: Path):
    result = _ingest(tmp_path)
    rows = _read_jsonl(result.chunks_jsonl_path)
    rows[0]["evidence_ids"] = ["span_missing"]
    _write_jsonl(result.chunks_jsonl_path, rows)

    signals = evaluate_document_version(result.output_dir)
    signal = next(
        item
        for item in signals
        if item.reason_code == "chunk.evidence.reference_missing"
    )

    assert signal.evidence_ids == ("span_missing",)
    assert signal.chunk_id == rows[0]["chunk_id"]


def test_chunk_without_evidence_is_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    rows = _read_jsonl(result.chunks_jsonl_path)
    rows[0]["evidence_ids"] = []
    _write_jsonl(result.chunks_jsonl_path, rows)

    assert "chunk.evidence.missing" in _reason_codes(result.output_dir)


def test_empty_chunk_is_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    rows = _read_jsonl(result.chunks_jsonl_path)
    rows[0]["text"] = ""
    _write_jsonl(result.chunks_jsonl_path, rows)

    assert "chunk.integrity.empty" in _reason_codes(result.output_dir)


def test_chunk_document_version_mismatch_is_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    rows = _read_jsonl(result.chunks_jsonl_path)
    rows[0]["document_version_id"] = "docver_other"
    _write_jsonl(result.chunks_jsonl_path, rows)

    assert (
        "chunk.integrity.document_version_mismatch"
        in _reason_codes(result.output_dir)
    )


def test_quality_sidecar_version_mismatch_is_document_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.quality_record_path.read_text(encoding="utf-8"))
    payload["document_version_id"] = "docver_other"
    write_json(result.quality_record_path, payload)

    assert (
        "document.integrity.document_version_mismatch"
        in _reason_codes(result.output_dir)
    )


def test_block_page_outside_declared_count_is_one_hard_signal_with_evidence(
    tmp_path: Path,
):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["parse_report"]["page_count"] = 1
    payload["blocks"][0]["page_start"] = 2
    payload["blocks"][0]["page_end"] = 2
    payload["evidence_spans"][0]["page"] = 2
    write_json(result.document_json_path, payload)

    matching = [
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "page.integrity.reference_out_of_range"
        and item.page == 2
    ]

    assert len(matching) == 1
    assert matching[0].evidence_ids == (
        payload["evidence_spans"][0]["evidence_id"],
    )


def test_markdown_without_page_count_has_no_source_location_signal(tmp_path: Path):
    result = _ingest(tmp_path)

    assert (
        "page.integrity.source_location_missing"
        not in _reason_codes(result.output_dir)
    )


def test_known_page_count_without_resolvable_location_is_hard_signal(
    tmp_path: Path,
):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["parse_report"]["page_count"] = 1
    payload["blocks"][0]["page_start"] = None
    payload["blocks"][0]["page_end"] = None
    payload["evidence_spans"] = [
        item
        for item in payload["evidence_spans"]
        if item["block_id"] != payload["blocks"][0]["block_id"]
    ]
    write_json(result.document_json_path, payload)

    assert (
        "page.integrity.source_location_missing"
        in _reason_codes(result.output_dir)
    )


def test_empty_block_is_hard_signal_with_block_evidence(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    block = payload["blocks"][0]
    evidence_id = next(
        item["evidence_id"]
        for item in payload["evidence_spans"]
        if item["block_id"] == block["block_id"]
    )
    block["text"] = ""
    write_json(result.document_json_path, payload)

    signal = next(
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "block.integrity.empty"
        and item.block_id == block["block_id"]
    )

    assert signal.evidence_ids == (evidence_id,)


def test_invalid_block_type_is_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["blocks"][0]["block_type"] = "image"
    write_json(result.document_json_path, payload)

    assert "block.integrity.type_invalid" in _reason_codes(result.output_dir)


def test_invalid_block_page_range_is_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["blocks"][0]["page_start"] = 2
    payload["blocks"][0]["page_end"] = 1
    write_json(result.document_json_path, payload)

    assert "block.integrity.page_range_invalid" in _reason_codes(result.output_dir)


def test_block_document_version_mismatch_is_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["blocks"][0]["document_version_id"] = "docver_other"
    write_json(result.document_json_path, payload)

    assert (
        "block.integrity.document_version_mismatch"
        in _reason_codes(result.output_dir)
    )


def test_block_without_evidence_is_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    block_id = payload["blocks"][0]["block_id"]
    payload["evidence_spans"] = [
        item
        for item in payload["evidence_spans"]
        if item["block_id"] != block_id
    ]
    write_json(result.document_json_path, payload)

    assert "block.evidence.missing" in _reason_codes(result.output_dir)


def test_evidence_hash_mismatch_is_hard_signal_with_evidence_id(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    evidence = payload["evidence_spans"][0]
    evidence["text_hash"] = "0" * 64
    write_json(result.document_json_path, payload)

    signal = next(
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "block.evidence.hash_mismatch"
    )

    assert signal.evidence_ids == (evidence["evidence_id"],)
    assert signal.block_id == evidence["block_id"]


def test_evidence_document_version_mismatch_is_page_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    evidence = payload["evidence_spans"][0]
    evidence["document_version_id"] = "docver_other"
    write_json(result.document_json_path, payload)

    signal = next(
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "page.integrity.document_version_mismatch"
    )

    assert signal.evidence_ids == (evidence["evidence_id"],)


def test_duplicate_block_marks_only_second_sorted_id_with_evidence(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    source_block = payload["blocks"][0]
    source_evidence = next(
        item
        for item in payload["evidence_spans"]
        if item["block_id"] == source_block["block_id"]
    )
    source_block["block_id"] = "block_z"
    source_evidence["block_id"] = "block_z"
    source_evidence["evidence_id"] = "span_z"
    duplicate_block = {**source_block, "block_id": "block_a"}
    duplicate_evidence = {
        **source_evidence,
        "block_id": "block_a",
        "evidence_id": "span_a",
    }
    payload["blocks"].append(duplicate_block)
    payload["evidence_spans"].append(duplicate_evidence)
    write_json(result.document_json_path, payload)

    matching = [
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "block.content.duplicate"
    ]

    assert [(item.block_id, item.evidence_ids) for item in matching] == [
        ("block_z", ("span_z",))
    ]


def test_repeated_evaluation_is_dictionary_identical(tmp_path: Path):
    result = _ingest(tmp_path)

    first = evaluate_document_version(result.output_dir)
    second = evaluate_document_version(result.output_dir)

    assert [item.to_dict() for item in first] == [
        item.to_dict() for item in second
    ]


def test_same_defect_has_same_reason_for_different_suppliers(tmp_path: Path):
    first = _ingest(tmp_path / "qnx")
    second = _ingest(tmp_path / "qualcomm")
    for result, supplier in ((first, "QNX"), (second, "Qualcomm")):
        payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
        payload["document"]["supplier"] = supplier
        payload["evidence_spans"][0]["text_hash"] = "0" * 64
        write_json(result.document_json_path, payload)

    first_codes = _reason_codes(first.output_dir)
    second_codes = _reason_codes(second.output_dir)

    assert "block.evidence.hash_mismatch" in first_codes
    assert first_codes == second_codes


def test_all_signal_scope_and_severity_come_from_registry(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["blocks"][0]["text"] = ""
    payload["blocks"][0]["block_type"] = "invalid"
    write_json(result.document_json_path, payload)

    signals = evaluate_document_version(result.output_dir)

    assert signals
    assert all(
        (item.scope, item.severity)
        == (
            REASON_CODE_REGISTRY[item.reason_code].scope,
            REASON_CODE_REGISTRY[item.reason_code].severity,
        )
        for item in signals
    )


def test_evaluation_does_not_modify_artifacts(tmp_path: Path):
    result = _ingest(tmp_path)
    paths = (
        result.document_json_path,
        result.chunks_jsonl_path,
        result.processing_record_path,
        result.quality_record_path,
    )
    before = {path: path.read_bytes() for path in paths}

    evaluate_document_version(result.output_dir)

    assert {path: path.read_bytes() for path in paths} == before


def test_duplicate_chunk_marks_only_second_sorted_id_with_evidence(tmp_path: Path):
    result = _ingest(tmp_path)
    rows = _read_jsonl(result.chunks_jsonl_path)
    rows[0]["chunk_id"] = "chunk_z"
    duplicate = {**rows[0], "chunk_id": "chunk_a"}
    rows.append(duplicate)
    _write_jsonl(result.chunks_jsonl_path, rows)

    matching = [
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "chunk.content.duplicate"
    ]

    assert [(item.chunk_id, item.evidence_ids) for item in matching] == [
        ("chunk_z", tuple(sorted(rows[0]["evidence_ids"])))
    ]


def test_soft_chunk_threshold_uses_brief_constant(tmp_path: Path):
    result = _ingest(tmp_path)
    rows = _read_jsonl(result.chunks_jsonl_path)
    rows[0]["text"] = "x" * (SOFT_MIN_CHUNK_CHARS - 1)
    _write_jsonl(result.chunks_jsonl_path, rows)

    signal = next(
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "chunk.content.too_short"
    )

    assert signal.threshold == SOFT_MIN_CHUNK_CHARS


def test_soft_block_threshold_uses_brief_constant(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["blocks"][0]["text"] = "x" * (SOFT_MAX_BLOCK_CHARS + 1)
    write_json(result.document_json_path, payload)

    signal = next(
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "block.content.too_long"
    )

    assert signal.threshold == SOFT_MAX_BLOCK_CHARS


def test_soft_page_threshold_uses_brief_constant(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["parse_report"]["page_count"] = 1
    for block in payload["blocks"]:
        block["page_start"] = 1
        block["page_end"] = 1
        block["text"] = ""
    for evidence in payload["evidence_spans"]:
        evidence["page"] = 1
    write_json(result.document_json_path, payload)

    signal = next(
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "page.content.text_too_short"
    )

    assert signal.threshold == SOFT_MIN_PAGE_CHARS


def test_warning_count_high_uses_brief_constant(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["parse_report"]["warnings"] = [
        f"warning-{index}" for index in range(SOFT_WARNING_COUNT + 1)
    ]
    write_json(result.document_json_path, payload)

    signal = next(
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "document.parse.warning_count_high"
    )

    assert signal.threshold == SOFT_WARNING_COUNT


def test_parse_fallback_used_is_document_soft_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["parse_report"]["quality_report"] = {"fallback_used": True}
    write_json(result.document_json_path, payload)

    assert "document.parse.fallback_used" in _reason_codes(result.output_dir)


def test_evidence_version_relation_is_validated_for_referenced_chunk(
    tmp_path: Path,
):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    evidence = payload["evidence_spans"][0]
    evidence["document_version_id"] = "docver_other"
    write_json(result.document_json_path, payload)

    signals = evaluate_document_version(result.output_dir)
    mismatch = next(
        item
        for item in signals
        if item.reason_code == "page.integrity.document_version_mismatch"
    )

    assert evidence["evidence_id"] in mismatch.evidence_ids


def test_zero_page_count_is_known_for_page_hard_signals(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["parse_report"]["page_count"] = 0
    payload["blocks"][0]["page_start"] = 1
    payload["blocks"][0]["page_end"] = 1
    payload["evidence_spans"][0]["page"] = 1
    write_json(result.document_json_path, payload)

    assert "page.integrity.reference_out_of_range" in _reason_codes(
        result.output_dir
    )


def test_duplicate_chunks_without_ids_do_not_abort_evaluation(tmp_path: Path):
    result = _ingest(tmp_path)
    rows = _read_jsonl(result.chunks_jsonl_path)
    rows[0].pop("chunk_id")
    rows.append(dict(rows[0]))
    _write_jsonl(result.chunks_jsonl_path, rows)

    signals = evaluate_document_version(result.output_dir)

    assert any(
        item.reason_code == "chunk.content.duplicate"
        and item.chunk_id == "chunk_1"
        for item in signals
    )


def test_evidence_text_and_hash_coordinated_change_is_rejected(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    evidence = payload["evidence_spans"][0]
    evidence["text"] = "coordinated tamper"
    evidence["text_hash"] = sha256_text(evidence["text"])
    write_json(result.document_json_path, payload)

    signal = next(
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "block.evidence.hash_mismatch"
        and item.metric_name == "evidence_text_matches_block"
    )

    assert signal.object_id == evidence["block_id"]
    assert signal.evidence_ids == (evidence["evidence_id"],)


def test_orphan_evidence_is_block_reference_missing_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    evidence = payload["evidence_spans"][0]
    evidence["block_id"] = "block_missing"
    write_json(result.document_json_path, payload)

    signal = next(
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "block.evidence.block_reference_missing"
    )

    assert signal.object_id == "block_missing"
    assert signal.block_id == "block_missing"
    assert signal.evidence_ids == (evidence["evidence_id"],)


def test_orphan_evidence_without_block_id_gets_stable_nonempty_object(
    tmp_path: Path,
):
    result = _ingest(tmp_path / "source")
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    evidence = payload["evidence_spans"][0]
    evidence["block_id"] = ""
    write_json(result.document_json_path, payload)
    copied_dir = tmp_path / "copied" / "different-name"
    shutil.copytree(result.output_dir, copied_dir)

    first = next(
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "block.evidence.block_reference_missing"
    )
    second = next(
        item
        for item in evaluate_document_version(copied_dir)
        if item.reason_code == "block.evidence.block_reference_missing"
    )

    assert first.object_id
    assert first.block_id is None
    assert first.object_id == second.object_id
    assert first.signal_id == second.signal_id


def test_duplicate_evidence_id_is_one_document_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    duplicate_id = payload["evidence_spans"][0]["evidence_id"]
    payload["evidence_spans"].extend(
        [dict(payload["evidence_spans"][0]), dict(payload["evidence_spans"][0])]
    )
    write_json(result.document_json_path, payload)

    matching = [
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "document.integrity.duplicate_evidence_id"
    ]

    assert len(matching) == 1
    assert matching[0].object_id == result.document_version_id
    assert matching[0].evidence_ids == (duplicate_id,)
    assert matching[0].severity == "error"


def test_out_of_range_block_propagates_evidence_from_another_page(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    block = payload["blocks"][0]
    evidence = next(
        item
        for item in payload["evidence_spans"]
        if item["block_id"] == block["block_id"]
    )
    payload["parse_report"]["page_count"] = 1
    block["page_start"] = 2
    block["page_end"] = 2
    evidence["page"] = 1
    write_json(result.document_json_path, payload)

    signal = next(
        item
        for item in evaluate_document_version(result.output_dir)
        if item.reason_code == "page.integrity.reference_out_of_range"
        and item.page == 2
    )

    assert evidence["evidence_id"] in signal.evidence_ids


def test_artifact_fingerprint_ignores_version_dir_path_and_mtime(tmp_path: Path):
    result = _ingest(tmp_path / "original")
    copied_dir = tmp_path / "copied" / "different-name"
    shutil.copytree(result.output_dir, copied_dir)
    for path in copied_dir.iterdir():
        path.touch()

    original = artifact_fingerprint(load_document_artifacts(result.output_dir))
    copied = artifact_fingerprint(load_document_artifacts(copied_dir))

    assert original == copied


def test_artifact_fingerprint_uses_semantic_payload_not_run_metadata(
    tmp_path: Path,
):
    result = _ingest(tmp_path / "original")
    copied_dir = tmp_path / "copied" / "different-name"
    shutil.copytree(result.output_dir, copied_dir)
    excluded_fields = {
        "file_path",
        "source_path",
        "processed_dir",
        "output_dir",
        "manifest_path",
        "document_json_path",
        "chunks_jsonl_path",
        "created_at",
        "updated_at",
        "generated_at",
    }

    def replace_run_metadata(value, marker):
        if isinstance(value, dict):
            return {
                key: (
                    f"{marker}:{key}"
                    if key in excluded_fields
                    else replace_run_metadata(item, marker)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [replace_run_metadata(item, marker) for item in value]
        return value

    for filename in (
        "canonical-document.json",
        "processing-record.json",
        "quality-record.json",
    ):
        path = copied_dir / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload = replace_run_metadata(payload, "different-machine")
        if filename == "processing-record.json":
            payload["processing_run_id"] = "different-run"
            payload["canonical_sha256"] = "1" * 64
            payload["chunks_sha256"] = "2" * 64
        write_json(path, payload)

    original = artifact_fingerprint(load_document_artifacts(result.output_dir))
    copied = artifact_fingerprint(load_document_artifacts(copied_dir))
    assert original == copied

    canonical_path = copied_dir / "canonical-document.json"
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    canonical["blocks"][0]["text"] += " semantic change"
    write_json(canonical_path, canonical)

    assert artifact_fingerprint(load_document_artifacts(copied_dir)) != original


def test_invalid_canonical_identity_and_signals_are_path_independent(
    tmp_path: Path,
):
    result = _ingest(tmp_path / "source")
    result.document_json_path.write_text("{invalid", encoding="utf-8")
    first_dir = tmp_path / "copies" / "first-name"
    second_dir = tmp_path / "copies" / "second-name"
    shutil.copytree(result.output_dir, first_dir)
    shutil.copytree(result.output_dir, second_dir)

    first = load_document_artifacts(first_dir)
    second = load_document_artifacts(second_dir)
    expected_id = stable_id(
        "unresolved-docver",
        file_sha256(first.canonical_path),
        file_sha256(first.chunks_path),
        file_sha256(first.processing_record_path),
        file_sha256(first.quality_record_path),
    )

    assert first.document_version_id == second.document_version_id == expected_id
    assert artifact_fingerprint(first) == artifact_fingerprint(second)
    assert [
        item.signal_id for item in evaluate_document_version(first_dir)
    ] == [
        item.signal_id for item in evaluate_document_version(second_dir)
    ]


def test_missing_canonical_identity_and_signals_are_path_independent(
    tmp_path: Path,
):
    result = _ingest(tmp_path / "source")
    result.document_json_path.unlink()
    first_dir = tmp_path / "copies" / "first-name"
    second_dir = tmp_path / "copies" / "second-name"
    shutil.copytree(result.output_dir, first_dir)
    shutil.copytree(result.output_dir, second_dir)

    first = load_document_artifacts(first_dir)
    second = load_document_artifacts(second_dir)
    expected_id = stable_id(
        "unresolved-docver",
        "missing",
        file_sha256(first.chunks_path),
        file_sha256(first.processing_record_path),
        file_sha256(first.quality_record_path),
    )

    assert first.document_version_id == second.document_version_id == expected_id
    assert artifact_fingerprint(first) == artifact_fingerprint(second)
    assert [
        item.signal_id for item in evaluate_document_version(first_dir)
    ] == [
        item.signal_id for item in evaluate_document_version(second_dir)
    ]
