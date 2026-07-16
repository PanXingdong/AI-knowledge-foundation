import json
from pathlib import Path

import pytest

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.release_manifest import (
    create_candidate_release,
    iter_release_documents,
    load_release_manifest,
    validate_release_artifacts,
)
from agent_knowledge_hub.utils import file_sha256


def _ingest_version(root: Path, source: Path, version: str, text: str):
    source.write_text(text, encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=root,
        title="Demo",
        document_version=version,
    )


def _write_json(path: Path, payload: dict):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def test_candidate_release_pins_one_explicit_version(tmp_path: Path):
    processed = tmp_path / "processed"
    source = tmp_path / "demo.md"
    old = _ingest_version(processed, source, "v1", "# V1\n\nold")
    new = _ingest_version(processed, source, "v2", "# V2\n\nnew")

    manifest = create_candidate_release(processed, tmp_path / "releases")
    selected = iter_release_documents(manifest.manifest_path)

    assert manifest.status == "candidate"
    assert manifest.release_id.startswith("release_")
    assert [item.document_version_id for item in manifest.documents] == [
        new.document_version_id
    ]
    assert old.document_version_id not in [
        item.document_version_id for item in manifest.documents
    ]
    assert len(selected) == 1


def test_release_validation_detects_mutated_chunks(tmp_path: Path):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    manifest = create_candidate_release(processed, tmp_path / "releases")
    result.chunks_jsonl_path.write_text('{"chunk_id":"mutated"}\n', encoding="utf-8")

    errors = validate_release_artifacts(manifest.manifest_path)

    assert errors == [f"chunks_hash_mismatch:{result.document_version_id}"]
    with pytest.raises(ValueError, match="chunks_hash_mismatch"):
        iter_release_documents(manifest.manifest_path)


def test_release_validation_detects_mutated_canonical_and_quality(tmp_path: Path):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    manifest = create_candidate_release(processed, tmp_path / "releases")

    result.document_json_path.write_text('{"tampered":true}', encoding="utf-8")
    result.quality_record_path.write_text('{"tampered":true}', encoding="utf-8")

    assert validate_release_artifacts(manifest.manifest_path) == [
        f"canonical_hash_mismatch:{result.document_version_id}",
        f"quality_record_hash_mismatch:{result.document_version_id}",
    ]


def test_candidate_release_rejects_quality_record_from_other_version(tmp_path: Path):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    quality = json.loads(result.quality_record_path.read_text(encoding="utf-8"))
    quality["document_version_id"] = "docver_other"
    _write_json(result.quality_record_path, quality)

    with pytest.raises(
        ValueError,
        match=(
            rf"^quality_record_document_version_mismatch:"
            rf"{result.document_version_id}$"
        ),
    ):
        create_candidate_release(processed, tmp_path / "releases")


def test_candidate_release_rejects_processing_record_from_other_version(
    tmp_path: Path,
):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    processing = json.loads(result.processing_record_path.read_text(encoding="utf-8"))
    processing["document_version_id"] = "docver_other"
    _write_json(result.processing_record_path, processing)

    with pytest.raises(
        ValueError,
        match=(
            rf"^processing_record_document_version_mismatch:"
            rf"{result.document_version_id}$"
        ),
    ):
        create_candidate_release(processed, tmp_path / "releases")


def test_release_validation_rejects_rehashed_canonical_from_other_version(
    tmp_path: Path,
):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    manifest = create_candidate_release(processed, tmp_path / "releases")
    canonical = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    canonical["document_version"]["document_version_id"] = "docver_other"
    _write_json(result.document_json_path, canonical)
    payload = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))
    payload["documents"][0]["canonical_sha256"] = file_sha256(
        result.document_json_path
    )
    _write_json(manifest.manifest_path, payload)

    assert validate_release_artifacts(manifest.manifest_path) == [
        f"canonical_document_version_mismatch:{result.document_version_id}"
    ]


def test_release_validation_rejects_processing_record_from_other_version(
    tmp_path: Path,
):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    manifest = create_candidate_release(processed, tmp_path / "releases")
    processing = json.loads(result.processing_record_path.read_text(encoding="utf-8"))
    processing["document_version_id"] = "docver_other"
    _write_json(result.processing_record_path, processing)

    assert validate_release_artifacts(manifest.manifest_path) == [
        f"processing_record_document_version_mismatch:{result.document_version_id}"
    ]


def test_release_validation_rejects_rehashed_quality_from_other_version(
    tmp_path: Path,
):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    manifest = create_candidate_release(processed, tmp_path / "releases")
    quality = json.loads(result.quality_record_path.read_text(encoding="utf-8"))
    quality["document_version_id"] = "docver_other"
    _write_json(result.quality_record_path, quality)
    payload = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))
    payload["documents"][0]["quality_record_sha256"] = file_sha256(
        result.quality_record_path
    )
    _write_json(manifest.manifest_path, payload)

    assert validate_release_artifacts(manifest.manifest_path) == [
        f"quality_record_document_version_mismatch:{result.document_version_id}"
    ]


def test_release_rejects_processing_record_path_traversal(tmp_path: Path):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    manifest = create_candidate_release(processed, tmp_path / "releases")
    payload = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))
    payload["documents"][0]["processing_record_path"] = "../processing-record.json"
    manifest.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    assert validate_release_artifacts(manifest.manifest_path) == [
        f"processing_record_path_outside_processed_dir:{result.document_version_id}"
    ]
    with pytest.raises(ValueError, match="processing_record_path_outside_processed_dir"):
        iter_release_documents(manifest.manifest_path)


def test_release_rejects_canonical_path_traversal(tmp_path: Path):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    manifest = create_candidate_release(processed, tmp_path / "releases")
    payload = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))
    payload["documents"][0]["canonical_path"] = "../canonical-document.json"
    manifest.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    assert validate_release_artifacts(manifest.manifest_path) == [
        f"canonical_path_outside_processed_dir:{result.document_version_id}"
    ]


def test_release_iteration_does_not_rescan_for_newer_versions(tmp_path: Path):
    processed = tmp_path / "processed"
    source = tmp_path / "demo.md"
    pinned = _ingest_version(processed, source, "v1", "# V1\n\npinned")
    manifest = create_candidate_release(processed, tmp_path / "releases")
    _ingest_version(processed, source, "v2", "# V2\n\nnot selected")

    selected = iter_release_documents(manifest.manifest_path)

    assert len(selected) == 1
    chunks_path, canonical = selected[0]
    assert chunks_path == pinned.chunks_jsonl_path.resolve()
    assert canonical["document_version"]["document_version_id"] == pinned.document_version_id


def test_release_id_excludes_time_and_release_directory(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest_version(processed, tmp_path / "demo.md", "v1", "# V1\n\nsame")

    first = create_candidate_release(processed, tmp_path / "releases-a")
    second = create_candidate_release(processed, tmp_path / "releases-b")

    assert first.release_id == second.release_id
    assert first.created_at != ""
    assert second.created_at != ""


def test_repeated_candidate_creation_keeps_manifest_bytes_unchanged(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest_version(processed, tmp_path / "demo.md", "v1", "# V1\n\nsame")
    first = create_candidate_release(processed, tmp_path / "releases")
    before = first.manifest_path.read_bytes()

    second = create_candidate_release(processed, tmp_path / "releases")

    assert second == first
    assert second.manifest_path.read_bytes() == before


def test_repeated_creation_preserves_existing_ready_manifest(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest_version(processed, tmp_path / "demo.md", "v1", "# V1\n\nsame")
    candidate = create_candidate_release(processed, tmp_path / "releases")
    payload = json.loads(candidate.manifest_path.read_text(encoding="utf-8"))
    payload["status"] = "ready"
    payload["indexes"] = {
        "fts": {
            "path": "indexes/fts.db",
            "sha256": "a" * 64,
        }
    }
    payload["baseline"] = {"release_id": "release_baseline"}
    _write_json(candidate.manifest_path, payload)
    before = candidate.manifest_path.read_bytes()

    existing = create_candidate_release(processed, tmp_path / "releases")

    assert existing.status == "ready"
    assert existing.indexes == payload["indexes"]
    assert existing.baseline == payload["baseline"]
    assert existing.manifest_path.read_bytes() == before


def test_repeated_creation_rejects_inconsistent_existing_manifest(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest_version(processed, tmp_path / "demo.md", "v1", "# V1\n\nsame")
    candidate = create_candidate_release(processed, tmp_path / "releases")
    payload = json.loads(candidate.manifest_path.read_text(encoding="utf-8"))
    payload["documents"][0]["quality_record_sha256"] = "0" * 64
    _write_json(candidate.manifest_path, payload)

    with pytest.raises(
        ValueError,
        match=rf"^existing_release_manifest_mismatch:{candidate.release_id}$",
    ):
        create_candidate_release(processed, tmp_path / "releases")


def test_legacy_release_derives_quality_without_mutating_version_dir(tmp_path: Path):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\nlegacy"
    )
    result.processing_record_path.unlink()
    result.quality_record_path.unlink()
    before = {
        path.name: file_sha256(path)
        for path in result.output_dir.iterdir()
        if path.is_file()
    }

    manifest = create_candidate_release(processed, tmp_path / "releases")

    after = {
        path.name: file_sha256(path)
        for path in result.output_dir.iterdir()
        if path.is_file()
    }
    document = manifest.documents[0]
    derived = manifest.manifest_path.parent / document.quality_record_path
    assert before == after
    assert document.processing_record_path is None
    assert document.quality_record_path == (
        f"derived-quality/{result.document_version_id}.json"
    )
    assert derived.is_file()
    assert file_sha256(derived) == document.quality_record_sha256
    assert validate_release_artifacts(manifest.manifest_path) == []


def test_processed_quality_path_named_derived_quality_stays_under_processed_root(
    tmp_path: Path,
):
    source = tmp_path / "demo.md"
    source.write_text("# V1\n\nnew ingest", encoding="utf-8")
    result = ingest_file(
        file_path=source,
        out_dir=tmp_path / "processed",
        title="derived-quality",
        document_version="v1",
    )

    manifest = create_candidate_release(
        tmp_path / "processed",
        tmp_path / "releases",
    )

    assert manifest.documents[0].quality_record_path == (
        result.quality_record_path.relative_to(tmp_path / "processed").as_posix()
    )
    assert validate_release_artifacts(manifest.manifest_path) == []


def test_load_release_manifest_round_trips_candidate(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest_version(processed, tmp_path / "demo.md", "v1", "# V1\n\nsame")
    created = create_candidate_release(processed, tmp_path / "releases")

    loaded = load_release_manifest(created.manifest_path)

    assert loaded == created


def test_resolve_artifact_rejects_absolute_path(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest_version(processed, tmp_path / "demo.md", "v1", "# V1\n\nsame")
    manifest = create_candidate_release(processed, tmp_path / "releases")
    manifest.indexes["fts"] = {"path": str((tmp_path / "outside.db").resolve())}

    with pytest.raises(
        ValueError,
        match="^release_artifact_path_escape:fts$",
    ):
        manifest.resolve_artifact("fts")


def test_resolve_artifact_rejects_parent_traversal(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest_version(processed, tmp_path / "demo.md", "v1", "# V1\n\nsame")
    manifest = create_candidate_release(processed, tmp_path / "releases")
    manifest.indexes["fts"] = {"path": "../../outside.db"}

    with pytest.raises(
        ValueError,
        match="^release_artifact_path_escape:fts$",
    ):
        manifest.resolve_artifact("fts")


def test_candidate_release_requires_at_least_one_document(tmp_path: Path):
    with pytest.raises(
        ValueError,
        match="^Cannot create a release without documents$",
    ):
        create_candidate_release(tmp_path / "empty", tmp_path / "releases")
