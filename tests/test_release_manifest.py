import json
import sqlite3
from pathlib import Path

import pytest

from agent_knowledge_hub.fts_index import build_fts_index
from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.processing_record import processing_run_id
from agent_knowledge_hub.quality_baseline import build_quality_baseline
from agent_knowledge_hub.release_manifest import (
    activate_release,
    create_candidate_release,
    finalize_release,
    iter_release_documents,
    load_active_release,
    load_release_manifest,
    validate_release_artifacts,
)
from agent_knowledge_hub.utils import file_sha256, write_json
from agent_knowledge_hub.vector_index import (
    build_bge_m3_vector_index,
    build_vector_index,
)


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


def _build_release_artifacts(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest_version(
        processed,
        tmp_path / "one.md",
        "v1",
        "# One\n\nOne evidence",
    )
    _ingest_version(
        processed,
        tmp_path / "two.md",
        "v1",
        "# Two\n\nTwo evidence",
    )
    release = create_candidate_release(processed, tmp_path / "releases")
    release_dir = release.manifest_path.parent
    fts_path = release_dir / "indexes" / "chunks.db"
    vector_path = release_dir / "indexes" / "chunks.json"
    baseline_path = release_dir / "quality-baseline.json"
    build_fts_index(
        processed_dir=processed,
        index_path=fts_path,
        release_manifest_path=release.manifest_path,
    )
    build_vector_index(
        processed_dir=processed,
        index_path=vector_path,
        release_manifest_path=release.manifest_path,
    )
    write_json(
        baseline_path,
        build_quality_baseline(release.manifest_path).to_dict(),
    )
    return release, fts_path, vector_path, baseline_path


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


def test_candidate_release_rejects_invalid_processing_run_identity(tmp_path: Path):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    processing = json.loads(result.processing_record_path.read_text(encoding="utf-8"))
    processing["processing_run_id"] = "run_tampered"
    write_json(result.processing_record_path, processing)

    with pytest.raises(
        ValueError,
        match=rf"^processing_record_run_id_mismatch:{result.document_version_id}$",
    ):
        create_candidate_release(processed, tmp_path / "releases")


@pytest.mark.parametrize("entrypoint", ["create", "validate"])
@pytest.mark.parametrize(
    ("field", "fake_value", "error_code"),
    [
        (
            "source_file_hash",
            "f" * 64,
            "processing_record_source_file_hash_mismatch",
        ),
        (
            "parser_name",
            "forged-parser",
            "processing_record_parser_name_mismatch",
        ),
        (
            "chunker_version",
            "forged-chunker",
            "processing_record_chunker_version_mismatch",
        ),
    ],
)
def test_release_rejects_forged_processing_provenance_with_recomputed_run(
    tmp_path: Path,
    entrypoint: str,
    field: str,
    fake_value: str,
    error_code: str,
):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    manifest = (
        create_candidate_release(processed, tmp_path / "releases")
        if entrypoint == "validate"
        else None
    )
    payload = json.loads(result.processing_record_path.read_text(encoding="utf-8"))
    payload[field] = fake_value
    payload["processing_run_id"] = processing_run_id(
        document_version_id=payload["document_version_id"],
        source_file_hash=payload["source_file_hash"],
        parser_name=payload["parser_name"],
        chunker_version=payload["chunker_version"],
        quality_rules_version=payload["quality_rules_version"],
        canonical_sha256=payload["canonical_sha256"],
        chunks_sha256=payload["chunks_sha256"],
    )
    write_json(result.processing_record_path, payload)

    if entrypoint == "create":
        with pytest.raises(
            ValueError,
            match=rf"^{error_code}:{result.document_version_id}$",
        ):
            create_candidate_release(processed, tmp_path / "releases")
        return

    manifest_payload = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))
    manifest_payload["documents"][0]["processing_record_sha256"] = file_sha256(
        result.processing_record_path
    )
    manifest_payload["documents"][0]["processing_run_id"] = payload[
        "processing_run_id"
    ]
    write_json(manifest.manifest_path, manifest_payload)
    assert validate_release_artifacts(manifest.manifest_path) == [
        f"{error_code}:{result.document_version_id}"
    ]


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
        f"processing_record_canonical_mismatch:{result.document_version_id}",
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
    assert document.processing_record_path == (
        f"derived-processing/{result.document_version_id}.json"
    )
    derived_processing = (
        manifest.manifest_path.parent / document.processing_record_path
    )
    assert derived_processing.is_file()
    assert file_sha256(derived_processing) == document.processing_record_sha256
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


def test_activation_requires_ready_release(tmp_path: Path):
    release, _, _, _ = _build_release_artifacts(tmp_path)
    pointer = tmp_path / "active" / "active-release.json"

    with pytest.raises(ValueError, match="^release_not_ready$"):
        activate_release(release.manifest_path, pointer)

    assert not pointer.exists()
    assert not pointer.with_suffix(pointer.suffix + ".tmp").exists()


@pytest.mark.parametrize(
    ("artifact", "error_code"),
    [
        ("fts", "fts_release_mismatch"),
        ("vector", "vector_release_mismatch"),
        ("baseline", "baseline_release_mismatch"),
    ],
)
def test_finalize_rejects_release_id_mismatch(
    tmp_path: Path,
    artifact: str,
    error_code: str,
):
    release, fts_path, vector_path, baseline_path = _build_release_artifacts(
        tmp_path
    )
    if artifact == "fts":
        connection = sqlite3.connect(fts_path)
        try:
            connection.execute(
                "UPDATE release_metadata SET value = 'release_other' "
                "WHERE key = 'release_id'"
            )
            connection.commit()
        finally:
            connection.close()
    else:
        path = vector_path if artifact == "vector" else baseline_path
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["release_id"] = "release_other"
        write_json(path, payload)

    with pytest.raises(ValueError, match=f"^{error_code}$"):
        finalize_release(
            release.manifest_path,
            fts_index_path=fts_path,
            vector_index_path=vector_path,
            baseline_path=baseline_path,
        )

    assert load_release_manifest(release.manifest_path).status == "candidate"
    assert not release.manifest_path.with_suffix(
        release.manifest_path.suffix + ".tmp"
    ).exists()


@pytest.mark.parametrize(
    ("artifact", "error_prefix"),
    [
        ("canonical", "canonical_hash_mismatch"),
        ("chunks", "chunks_hash_mismatch"),
        ("quality", "quality_record_hash_mismatch"),
    ],
)
def test_finalize_rejects_mutated_source_artifact(
    tmp_path: Path,
    artifact: str,
    error_prefix: str,
):
    release, fts_path, vector_path, baseline_path = _build_release_artifacts(
        tmp_path
    )
    document = release.documents[0]
    if artifact == "canonical":
        path = Path(release.processed_dir) / document.canonical_path
    elif artifact == "chunks":
        path = Path(release.processed_dir) / document.chunks_path
    else:
        path = Path(release.processed_dir) / document.quality_record_path
    path.write_bytes(path.read_bytes() + b" ")

    with pytest.raises(ValueError, match=f"^{error_prefix}:"):
        finalize_release(
            release.manifest_path,
            fts_index_path=fts_path,
            vector_index_path=vector_path,
            baseline_path=baseline_path,
        )


def test_finalize_binds_relative_paths_and_hashes_then_activates_atomically(
    tmp_path: Path,
):
    release, fts_path, vector_path, baseline_path = _build_release_artifacts(
        tmp_path
    )

    ready = finalize_release(
        release.manifest_path,
        fts_index_path=fts_path,
        vector_index_path=vector_path,
        baseline_path=baseline_path,
    )

    assert ready.status == "ready"
    assert ready.indexes == {
        "fts": {
            "path": "indexes/chunks.db",
            "sha256": file_sha256(fts_path),
        },
        "vector": {
            "path": "indexes/chunks.json",
            "sha256": file_sha256(vector_path),
        },
    }
    assert ready.baseline == {
        "path": "quality-baseline.json",
        "sha256": file_sha256(baseline_path),
    }
    assert not ready.manifest_path.with_suffix(
        ready.manifest_path.suffix + ".tmp"
    ).exists()

    pointer = tmp_path / "runtime" / "nested" / "active-release.json"
    activate_release(ready.manifest_path, pointer)

    assert load_active_release(pointer) == ready
    assert not pointer.with_suffix(pointer.suffix + ".tmp").exists()


def test_ready_release_rejects_different_same_id_artifacts_without_mutation(
    tmp_path: Path,
):
    release, fts_path, vector_path, baseline_path = _build_release_artifacts(tmp_path)
    ready = finalize_release(
        release.manifest_path,
        fts_index_path=fts_path,
        vector_index_path=vector_path,
        baseline_path=baseline_path,
    )
    pointer = tmp_path / "active-release.json"
    activate_release(ready.manifest_path, pointer)
    manifest_before = ready.manifest_path.read_bytes()
    pointer_before = pointer.read_bytes()

    alternate_fts = ready.manifest_path.parent / "indexes" / "alternate.db"
    alternate_vector = ready.manifest_path.parent / "indexes" / "alternate.json"
    alternate_baseline = ready.manifest_path.parent / "alternate-baseline.json"
    build_fts_index(
        processed_dir=ready.processed_dir,
        index_path=alternate_fts,
        release_manifest_path=ready.manifest_path,
    )
    build_vector_index(
        processed_dir=ready.processed_dir,
        index_path=alternate_vector,
        release_manifest_path=ready.manifest_path,
    )
    write_json(
        alternate_baseline,
        build_quality_baseline(ready.manifest_path).to_dict(),
    )

    with pytest.raises(ValueError, match="^release_already_ready$"):
        finalize_release(
            ready.manifest_path,
            fts_index_path=alternate_fts,
            vector_index_path=alternate_vector,
            baseline_path=alternate_baseline,
        )

    assert ready.manifest_path.read_bytes() == manifest_before
    assert pointer.read_bytes() == pointer_before
    assert load_active_release(pointer).resolve_artifact("fts") == fts_path.resolve()


def test_ready_release_finalize_is_idempotent_only_for_bound_artifacts(tmp_path: Path):
    release, fts_path, vector_path, baseline_path = _build_release_artifacts(tmp_path)
    ready = finalize_release(
        release.manifest_path,
        fts_index_path=fts_path,
        vector_index_path=vector_path,
        baseline_path=baseline_path,
    )
    before = ready.manifest_path.read_bytes()

    repeated = finalize_release(
        ready.manifest_path,
        fts_index_path=fts_path,
        vector_index_path=vector_path,
        baseline_path=baseline_path,
    )

    assert repeated == ready
    assert ready.manifest_path.read_bytes() == before


def test_finalize_binds_bge_matrix_and_metadata_and_activation_checks_both(
    tmp_path: Path,
    monkeypatch,
):
    release, fts_path, _, baseline_path = _build_release_artifacts(tmp_path)
    model_path = tmp_path / "model"
    model_path.mkdir()

    class FakeModel:
        def encode(self, texts, **_kwargs):
            import numpy as np

            return {"dense_vecs": np.ones((len(texts), 2), dtype="float32")}

    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: FakeModel(),
    )
    vector_path = release.manifest_path.parent / "indexes" / "chunks.npz"
    build_bge_m3_vector_index(
        processed_dir=release.processed_dir,
        index_path=vector_path,
        model_path=model_path,
        release_manifest_path=release.manifest_path,
    )

    ready = finalize_release(
        release.manifest_path,
        fts_index_path=fts_path,
        vector_index_path=vector_path,
        baseline_path=baseline_path,
    )
    metadata_path = Path(str(vector_path) + ".metadata.json")
    assert ready.indexes["vector"]["metadata_path"] == (
        "indexes/chunks.npz.metadata.json"
    )
    assert ready.indexes["vector"]["metadata_sha256"] == file_sha256(metadata_path)

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["model_name"] = "tampered-but-same-release"
    write_json(metadata_path, metadata)
    with pytest.raises(ValueError, match="^vector_metadata_hash_mismatch$"):
        activate_release(ready.manifest_path, tmp_path / "active.json")


def test_release_validation_rejects_rehashed_processing_record_semantic_tamper(
    tmp_path: Path,
):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    release = create_candidate_release(processed, tmp_path / "releases")
    processing = json.loads(result.processing_record_path.read_text(encoding="utf-8"))
    processing["quality_rules_version"] = "tampered-rules"
    write_json(result.processing_record_path, processing)
    payload = json.loads(release.manifest_path.read_text(encoding="utf-8"))
    payload["documents"][0]["processing_record_sha256"] = file_sha256(
        result.processing_record_path
    )
    write_json(release.manifest_path, payload)

    assert validate_release_artifacts(release.manifest_path) == [
        f"processing_record_quality_rules_mismatch:{result.document_version_id}"
    ]


@pytest.mark.parametrize(
    "artifact",
    ["canonical", "chunks", "quality", "fts", "vector", "baseline"],
)
def test_activation_rejects_tampered_ready_release_artifact(
    tmp_path: Path,
    artifact: str,
):
    release, fts_path, vector_path, baseline_path = _build_release_artifacts(
        tmp_path
    )
    ready = finalize_release(
        release.manifest_path,
        fts_index_path=fts_path,
        vector_index_path=vector_path,
        baseline_path=baseline_path,
    )
    document = ready.documents[0]
    paths = {
        "canonical": Path(ready.processed_dir) / document.canonical_path,
        "chunks": Path(ready.processed_dir) / document.chunks_path,
        "quality": Path(ready.processed_dir) / document.quality_record_path,
        "fts": fts_path,
        "vector": vector_path,
        "baseline": baseline_path,
    }
    paths[artifact].write_bytes(paths[artifact].read_bytes() + b" ")
    pointer = tmp_path / "active-release.json"

    with pytest.raises(ValueError, match="hash_mismatch"):
        activate_release(ready.manifest_path, pointer)

    assert not pointer.exists()
    assert not pointer.with_suffix(pointer.suffix + ".tmp").exists()
