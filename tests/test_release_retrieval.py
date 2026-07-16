import json
from pathlib import Path

import pytest

from agent_knowledge_hub.fts_index import build_fts_index
from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.processing_record import (
    build_processing_record,
    write_processing_record,
)
from agent_knowledge_hub.quality_baseline import build_quality_baseline
from agent_knowledge_hub.release_manifest import (
    create_candidate_release,
    finalize_release,
)
from agent_knowledge_hub.retrieval import (
    build_context_pack_for_processed_dir,
    clear_retrieval_caches,
    trace_evidence_in_processed_dir,
)
from agent_knowledge_hub.utils import write_json
from agent_knowledge_hub.vector_index import (
    VectorIndexError,
    build_bge_m3_vector_index,
    build_vector_index,
    clear_vector_index_cache,
)


def _ingest(processed: Path, source: Path, title: str, text: str):
    source.write_text(f"# {title}\n\n{text}", encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=processed,
        title=title,
        document_version="v1",
    )


def test_release_retrieval_excludes_post_release_documents_and_serializes_release_id(
    tmp_path: Path,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "old.md", "Old", "release_only_token")
    release = create_candidate_release(processed, tmp_path / "releases")
    _ingest(processed, tmp_path / "new.md", "New", "later_only_token")

    result = build_context_pack_for_processed_dir(
        processed_dir=processed,
        release_manifest_path=release.manifest_path,
        query="later_only_token",
        top_k=5,
    )

    assert all(chunk.document_title != "New" for chunk in result.selected_chunks)
    assert result.release_id == release.release_id
    assert result.to_json_dict()["release_id"] == release.release_id
    assert result.to_summary_dict()["release_id"] == release.release_id


@pytest.mark.parametrize(
    ("builder", "index_name", "error_name"),
    [
        (build_fts_index, "chunks.db", "fts_release_mismatch"),
        (build_vector_index, "chunks.json", "vector_release_mismatch"),
    ],
)
def test_release_retrieval_rejects_index_from_different_release(
    tmp_path: Path,
    builder,
    index_name: str,
    error_name: str,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One", "alpha")
    first = create_candidate_release(processed, tmp_path / "releases")
    index_path = tmp_path / index_name
    builder(
        processed_dir=processed,
        index_path=index_path,
        release_manifest_path=first.manifest_path,
    )
    _ingest(processed, tmp_path / "two.md", "Two", "beta")
    second = create_candidate_release(processed, tmp_path / "releases")

    with pytest.raises(ValueError, match=error_name):
        build_context_pack_for_processed_dir(
            processed_dir=processed,
            release_manifest_path=second.manifest_path,
            **{f"{'fts' if index_name.endswith('.db') else 'vector'}_index_path": index_path},
            query="alpha",
        )


@pytest.mark.parametrize(
    ("builder", "index_name", "index_argument", "error_name"),
    [
        (build_fts_index, "legacy.db", "fts_index_path", "fts_release_mismatch"),
        (
            build_vector_index,
            "legacy.json",
            "vector_index_path",
            "vector_release_mismatch",
        ),
    ],
)
def test_release_retrieval_rejects_legacy_index_without_release_id(
    tmp_path: Path,
    builder,
    index_name: str,
    index_argument: str,
    error_name: str,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One", "alpha")
    release = create_candidate_release(processed, tmp_path / "releases")
    index_path = tmp_path / index_name
    builder(processed_dir=processed, index_path=index_path)

    with pytest.raises(ValueError, match=rf"{error_name}:.*actual=None"):
        build_context_pack_for_processed_dir(
            processed_dir=processed,
            release_manifest_path=release.manifest_path,
            **{index_argument: index_path},
            query="alpha",
        )


def test_release_retrieval_rejects_manifest_for_different_processed_dir(
    tmp_path: Path,
):
    released_processed = tmp_path / "released"
    _ingest(released_processed, tmp_path / "released.md", "Released", "alpha")
    release = create_candidate_release(released_processed, tmp_path / "releases")
    other_processed = tmp_path / "other"
    _ingest(other_processed, tmp_path / "other.md", "Other", "beta")

    with pytest.raises(ValueError, match="^release_processed_dir_mismatch$"):
        build_context_pack_for_processed_dir(
            processed_dir=other_processed,
            release_manifest_path=release.manifest_path,
            query="beta",
        )


def test_different_releases_do_not_reuse_processed_dir_chunk_cache(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "old.md", "Old", "release_only_token")
    first = create_candidate_release(processed, tmp_path / "releases")
    clear_retrieval_caches()
    first_result = build_context_pack_for_processed_dir(
        processed_dir=processed,
        release_manifest_path=first.manifest_path,
        query="release_only_token",
    )
    assert {chunk.document_title for chunk in first_result.selected_chunks} == {"Old"}

    _ingest(processed, tmp_path / "new.md", "New", "second_release_token")
    second = create_candidate_release(processed, tmp_path / "releases")
    second_result = build_context_pack_for_processed_dir(
        processed_dir=processed,
        release_manifest_path=second.manifest_path,
        query="second_release_token",
    )

    assert "New" in {chunk.document_title for chunk in second_result.selected_chunks}


def test_release_evidence_trace_does_not_scan_post_release_documents(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "old.md", "Old", "release evidence")
    release = create_candidate_release(processed, tmp_path / "releases")
    later = _ingest(processed, tmp_path / "new.md", "New", "post release evidence")
    payload = json.loads(later.document_json_path.read_text(encoding="utf-8"))
    later_evidence_id = payload["evidence_spans"][0]["evidence_id"]

    with pytest.raises(ValueError, match=rf"Evidence not found: {later_evidence_id}"):
        trace_evidence_in_processed_dir(
            processed_dir=processed,
            release_manifest_path=release.manifest_path,
            evidence_id=later_evidence_id,
        )


def test_legacy_retrieval_keeps_release_id_none(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "legacy.md", "Legacy", "legacy_token")

    result = build_context_pack_for_processed_dir(
        processed_dir=processed,
        query="legacy_token",
    )

    assert result.release_id is None


def _finalize(tmp_path: Path, release):
    release_root = release.manifest_path.parent
    fts_path = release_root / "indexes" / "chunks.db"
    vector_path = release_root / "indexes" / "chunks.json"
    baseline_path = release_root / "quality-baseline.json"
    build_fts_index(
        processed_dir=release.processed_dir,
        index_path=fts_path,
        release_manifest_path=release.manifest_path,
    )
    build_vector_index(
        processed_dir=release.processed_dir,
        index_path=vector_path,
        release_manifest_path=release.manifest_path,
    )
    write_json(
        baseline_path,
        build_quality_baseline(release.manifest_path).to_dict(),
    )
    return finalize_release(
        release.manifest_path,
        fts_index_path=fts_path,
        vector_index_path=vector_path,
        baseline_path=baseline_path,
    )


def test_ready_retrieval_auto_resolves_bound_indexes(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "ready.md", "Ready", "bound_index_token")
    ready = _finalize(
        tmp_path,
        create_candidate_release(processed, tmp_path / "releases"),
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed,
        release_manifest_path=ready.manifest_path,
        query="bound_index_token",
    )

    assert result.selected_chunks
    assert {"fts", "vector"} <= set(result.selected_chunks[0].retrieval_signals)


def test_ready_retrieval_rejects_external_copy_with_same_release_id(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "ready.md", "Ready", "alpha")
    ready = _finalize(
        tmp_path,
        create_candidate_release(processed, tmp_path / "releases"),
    )
    copied = tmp_path / "copied.db"
    copied.write_bytes(ready.resolve_artifact("fts").read_bytes())

    with pytest.raises(ValueError, match="^ready_fts_path_mismatch$"):
        build_context_pack_for_processed_dir(
            processed_dir=processed,
            release_manifest_path=ready.manifest_path,
            fts_index_path=copied,
            query="alpha",
        )


def test_candidate_without_indexes_allows_shadow_lexical_retrieval(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "candidate.md", "Candidate", "shadow_token")
    candidate = create_candidate_release(processed, tmp_path / "releases")

    result = build_context_pack_for_processed_dir(
        processed_dir=processed,
        release_manifest_path=candidate.manifest_path,
        query="shadow_token",
    )

    assert result.selected_chunks
    assert "lexical" in result.selected_chunks[0].retrieval_signals


def test_release_cache_namespace_isolates_same_chunk_id_metadata(tmp_path: Path):
    processed = tmp_path / "processed"
    result = _ingest(
        processed,
        tmp_path / "same.md",
        "OldMarker",
        "shared body",
    )
    first = create_candidate_release(processed, tmp_path / "releases")
    clear_retrieval_caches()
    old_result = build_context_pack_for_processed_dir(
        processed_dir=processed,
        release_manifest_path=first.manifest_path,
        query="oldmarker",
    )
    assert "lexical" in old_result.selected_chunks[0].retrieval_signals

    canonical = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    canonical["document"]["title"] = "NewMarker"
    write_json(result.document_json_path, canonical)
    chunks = [
        json.loads(line)
        for line in result.chunks_jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    original_chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    for chunk in chunks:
        chunk["metadata"]["document_title"] = "NewMarker"
    result.chunks_jsonl_path.write_text(
        "\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in chunks) + "\n",
        encoding="utf-8",
    )
    processing = build_processing_record(
        document_version_id=result.document_version_id,
        source_file_hash=canonical["document_version"]["file_hash"],
        parser_name=canonical["parse_report"]["parser_name"],
        canonical_path=result.document_json_path,
        chunks_path=result.chunks_jsonl_path,
    )
    write_processing_record(result.processing_record_path, processing)
    second = create_candidate_release(processed, tmp_path / "releases")

    new_result = build_context_pack_for_processed_dir(
        processed_dir=processed,
        release_manifest_path=second.manifest_path,
        query="newmarker",
    )

    assert [chunk["chunk_id"] for chunk in chunks] == original_chunk_ids
    assert second.release_id != first.release_id
    assert "lexical" in new_result.selected_chunks[0].retrieval_signals
    assert new_result.selected_chunks[0].document_title == "NewMarker"


def test_ready_retrieval_rejects_tampered_bge_metadata_with_same_release_id(
    tmp_path: Path,
    monkeypatch,
):
    import numpy as np

    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "bge.md", "BGE", "alpha")
    release = create_candidate_release(processed, tmp_path / "releases")
    release_root = release.manifest_path.parent
    fts_path = release_root / "indexes" / "chunks.db"
    vector_path = release_root / "indexes" / "chunks.npz"
    baseline_path = release_root / "quality-baseline.json"
    model_path = tmp_path / "model"
    model_path.mkdir()

    class FakeModel:
        def encode(self, texts, **_kwargs):
            return {"dense_vecs": np.ones((len(texts), 2), dtype="float32")}

    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: FakeModel(),
    )
    build_fts_index(
        processed_dir=processed,
        index_path=fts_path,
        release_manifest_path=release.manifest_path,
    )
    build_bge_m3_vector_index(
        processed_dir=processed,
        index_path=vector_path,
        model_path=model_path,
        release_manifest_path=release.manifest_path,
    )
    write_json(
        baseline_path,
        build_quality_baseline(release.manifest_path).to_dict(),
    )
    ready = finalize_release(
        release.manifest_path,
        fts_index_path=fts_path,
        vector_index_path=vector_path,
        baseline_path=baseline_path,
    )
    metadata_path = Path(str(vector_path) + ".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["model_name"] = "tampered"
    write_json(metadata_path, metadata)

    with pytest.raises(ValueError, match="^vector_metadata_hash_mismatch$"):
        build_context_pack_for_processed_dir(
            processed_dir=processed,
            release_manifest_path=ready.manifest_path,
            query="alpha",
        )


def test_ready_retrieval_rejects_replaced_bge_model_content(
    tmp_path: Path,
    monkeypatch,
):
    import numpy as np

    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "bge.md", "BGE", "alpha")
    release = create_candidate_release(processed, tmp_path / "releases")
    release_root = release.manifest_path.parent
    fts_path = release_root / "indexes" / "chunks.db"
    vector_path = release_root / "indexes" / "chunks.npz"
    baseline_path = release_root / "quality-baseline.json"
    model_path = tmp_path / "model"
    model_path.mkdir()
    weights_path = model_path / "weights.bin"
    weights_path.write_bytes(b"model-v1")

    class FakeModel:
        def encode(self, texts, **_kwargs):
            return {"dense_vecs": np.ones((len(texts), 2), dtype="float32")}

    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: FakeModel(),
    )
    build_fts_index(
        processed_dir=processed,
        index_path=fts_path,
        release_manifest_path=release.manifest_path,
    )
    build_bge_m3_vector_index(
        processed_dir=processed,
        index_path=vector_path,
        model_path=model_path,
        release_manifest_path=release.manifest_path,
    )
    write_json(
        baseline_path,
        build_quality_baseline(release.manifest_path).to_dict(),
    )
    ready = finalize_release(
        release.manifest_path,
        fts_index_path=fts_path,
        vector_index_path=vector_path,
        baseline_path=baseline_path,
    )
    clear_vector_index_cache()
    weights_path.write_bytes(b"model-v2")
    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: pytest.fail("fingerprint mismatch must precede model use"),
    )

    with pytest.raises(VectorIndexError, match="^bge_model_fingerprint_mismatch$"):
        build_context_pack_for_processed_dir(
            processed_dir=processed,
            release_manifest_path=ready.manifest_path,
            query="alpha",
        )
