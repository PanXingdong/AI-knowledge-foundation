import json
from pathlib import Path

import pytest

from agent_knowledge_hub.fts_index import build_fts_index
from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.release_manifest import create_candidate_release
from agent_knowledge_hub.retrieval import (
    build_context_pack_for_processed_dir,
    clear_retrieval_caches,
    trace_evidence_in_processed_dir,
)
from agent_knowledge_hub.vector_index import build_vector_index


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
