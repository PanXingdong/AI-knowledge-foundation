import json
import sqlite3
from pathlib import Path

import pytest

from agent_knowledge_hub import fts_index, vector_index
from agent_knowledge_hub.fts_index import build_fts_index
from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.release_manifest import create_candidate_release
from agent_knowledge_hub.vector_index import (
    build_bge_m3_vector_index,
    build_bge_m3_vector_index_resumable,
    build_vector_index,
)


def _ingest(processed: Path, source: Path, title: str, text: str):
    source.write_text(f"# {title}\n\n{text}", encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=processed,
        title=title,
        document_version="v1",
    )


def test_indexes_pin_release_and_ignore_later_ingest(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "first.md", "First", "alpha")
    release = create_candidate_release(processed, tmp_path / "releases")
    _ingest(processed, tmp_path / "second.md", "Second", "beta")

    fts_path = tmp_path / "indexes" / "chunks.db"
    vector_path = tmp_path / "indexes" / "chunks.json"
    fts = build_fts_index(
        processed_dir=processed,
        index_path=fts_path,
        release_manifest_path=release.manifest_path,
    )
    vector = build_vector_index(
        processed_dir=processed,
        index_path=vector_path,
        release_manifest_path=release.manifest_path,
    )

    assert fts.release_id == release.release_id
    assert vector.release_id == release.release_id
    assert fts.indexed_document_count == 1
    assert vector.indexed_document_count == 1
    assert fts_index.read_fts_release_id(fts_path) == release.release_id
    assert vector_index.read_vector_release_id(vector_path) == release.release_id


@pytest.mark.parametrize("builder", [build_fts_index, build_vector_index])
def test_release_bound_index_rejects_different_processed_directory(
    tmp_path: Path,
    builder,
):
    released_processed = tmp_path / "released-processed"
    _ingest(released_processed, tmp_path / "released.md", "Released", "alpha")
    release = create_candidate_release(released_processed, tmp_path / "releases")

    other_processed = tmp_path / "other-processed"
    _ingest(other_processed, tmp_path / "other.md", "Other", "beta")

    with pytest.raises(ValueError, match="^release_processed_dir_mismatch$"):
        builder(
            processed_dir=other_processed,
            index_path=tmp_path / "index",
            release_manifest_path=release.manifest_path,
        )


def test_legacy_indexes_have_no_release_id(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "legacy.md", "Legacy", "alpha")

    fts_path = tmp_path / "chunks.db"
    vector_path = tmp_path / "chunks.json"
    fts = build_fts_index(processed_dir=processed, index_path=fts_path)
    vector = build_vector_index(processed_dir=processed, index_path=vector_path)

    assert fts.release_id is None
    assert vector.release_id is None
    assert fts_index.read_fts_release_id(fts_path) is None
    assert vector_index.read_vector_release_id(vector_path) is None


def test_release_readers_support_indexes_without_release_metadata(tmp_path: Path):
    fts_path = tmp_path / "old.db"
    connection = sqlite3.connect(fts_path)
    try:
        connection.execute("CREATE TABLE old_index (value TEXT)")
        connection.commit()
    finally:
        connection.close()

    vector_path = tmp_path / "old.json"
    vector_path.write_text('{"schema_version": "vector-index.v1"}', encoding="utf-8")

    assert fts_index.read_fts_release_id(fts_path) is None
    assert vector_index.read_vector_release_id(vector_path) is None


def test_vector_release_reader_supports_legacy_bge_metadata_name(tmp_path: Path):
    index_path = tmp_path / "old.npz"
    legacy_metadata_path = index_path.with_suffix(
        index_path.suffix + ".metadata.json"
    )
    legacy_metadata_path.write_text(
        '{"schema_version": "vector-index.v2"}',
        encoding="utf-8",
    )

    assert vector_index.read_vector_release_id(index_path) is None


class _FakeBgeModel:
    def encode(self, texts, **_kwargs):
        import numpy as np

        return {
            "dense_vecs": np.asarray(
                [[float(index + 1), 1.0] for index, _text in enumerate(texts)],
                dtype="float32",
            )
        }


@pytest.mark.parametrize(
    "builder",
    [build_bge_m3_vector_index, build_bge_m3_vector_index_resumable],
)
def test_bge_builders_write_release_metadata(
    tmp_path: Path,
    monkeypatch,
    builder,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "first.md", "First", "alpha")
    release = create_candidate_release(processed, tmp_path / "releases")
    _ingest(processed, tmp_path / "second.md", "Second", "beta")
    model_path = tmp_path / "model"
    model_path.mkdir()
    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: _FakeBgeModel(),
    )

    index_path = tmp_path / f"{builder.__name__}.npz"
    summary = builder(
        processed_dir=processed,
        index_path=index_path,
        model_path=model_path,
        release_manifest_path=release.manifest_path,
    )

    metadata_path = Path(str(index_path) + ".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert not index_path.with_suffix(".metadata.json").exists()
    assert summary.release_id == release.release_id
    assert summary.indexed_document_count == 1
    assert metadata["release_id"] == release.release_id
    assert metadata["model_fingerprint"] == (
        vector_index.model_content_fingerprint(model_path)
    )
    assert vector_index.read_vector_release_id(index_path) == release.release_id


def test_model_content_fingerprint_is_stable_across_equivalent_directories(
    tmp_path: Path,
):
    import hashlib

    model_file = tmp_path / "model.bin"
    model_file.write_bytes(b"single model file")
    assert vector_index.model_content_fingerprint(model_file) == hashlib.sha256(
        b"single model file"
    ).hexdigest()

    first = tmp_path / "first-model"
    second = tmp_path / "second-model"
    for root in (first, second):
        (root / "nested").mkdir(parents=True)
        (root / "config.json").write_text('{"model":"bge"}', encoding="utf-8")
        (root / "nested" / "weights.bin").write_bytes(b"\x00\x01weights")

    first_fingerprint = vector_index.model_content_fingerprint(first)
    assert first_fingerprint == vector_index.model_content_fingerprint(second)

    (second / "nested" / "weights.bin").write_bytes(b"\x00\x02weights")
    assert first_fingerprint != vector_index.model_content_fingerprint(second)


def test_model_content_fingerprint_rejects_symlink(tmp_path: Path):
    model_path = tmp_path / "model"
    model_path.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    link = model_path / "linked.bin"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")

    with pytest.raises(
        vector_index.VectorIndexError,
        match="^model_path_symlink_unsupported$",
    ):
        vector_index.model_content_fingerprint(model_path)


def test_standard_bge_metadata_records_model_content_fingerprint(
    tmp_path: Path,
    monkeypatch,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "legacy.md", "Legacy", "alpha")
    model_path = tmp_path / "model"
    model_path.mkdir()
    (model_path / "weights.bin").write_bytes(b"stable model bytes")
    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: _FakeBgeModel(),
    )
    index_path = tmp_path / "standard.npz"

    build_bge_m3_vector_index(
        processed_dir=processed,
        index_path=index_path,
        model_path=model_path,
    )

    metadata = json.loads(
        Path(str(index_path) + ".metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["model_fingerprint"] == (
        vector_index.model_content_fingerprint(model_path)
    )


def test_resumable_rejects_same_model_path_content_replacement_before_reuse(
    tmp_path: Path,
    monkeypatch,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "legacy.md", "Legacy", "alpha")
    model_path = tmp_path / "model"
    model_path.mkdir()
    weights_path = model_path / "weights.bin"
    weights_path.write_bytes(b"model-v1")
    work_dir = tmp_path / "work"
    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: _FakeBgeModel(),
    )
    build_bge_m3_vector_index_resumable(
        processed_dir=processed,
        index_path=tmp_path / "first.npz",
        model_path=model_path,
        work_dir=work_dir,
    )
    manifest_path = work_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["model_fingerprint"] == vector_index.model_content_fingerprint(
        model_path
    )
    manifest_before = manifest_path.read_bytes()
    part_paths = sorted(work_dir.glob("part_*.npy"))
    part_bytes_before = {path: path.read_bytes() for path in part_paths}
    weights_path.write_bytes(b"model-v2")
    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: pytest.fail("changed model must fail before model loading"),
    )

    with pytest.raises(
        vector_index.VectorIndexError,
        match="^resumable_work_dir_input_mismatch$",
    ):
        build_bge_m3_vector_index_resumable(
            processed_dir=processed,
            index_path=tmp_path / "second.npz",
            model_path=model_path,
            work_dir=work_dir,
        )

    assert manifest_path.read_bytes() == manifest_before
    assert {path: path.read_bytes() for path in part_paths} == part_bytes_before


def test_resumable_rejects_different_release_before_loading_model(
    tmp_path: Path,
    monkeypatch,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "first.md", "First", "alpha")
    release = create_candidate_release(processed, tmp_path / "releases")
    model_path = tmp_path / "model"
    model_path.mkdir()
    work_dir = tmp_path / "work"
    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: _FakeBgeModel(),
    )
    build_bge_m3_vector_index_resumable(
        processed_dir=processed,
        index_path=tmp_path / "first.npz",
        model_path=model_path,
        work_dir=work_dir,
        release_manifest_path=release.manifest_path,
    )

    manifest_path = work_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["release_id"] == release.release_id
    assert manifest["input_fingerprint"]
    manifest["release_id"] = "release_other"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_before = manifest_path.read_bytes()
    part_paths = list(work_dir.glob("part_*.npy"))
    assert part_paths
    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: pytest.fail("model must not load for mismatched work_dir"),
    )

    with pytest.raises(
        vector_index.VectorIndexError,
        match="^resumable_work_dir_input_mismatch$",
    ):
        build_bge_m3_vector_index_resumable(
            processed_dir=processed,
            index_path=tmp_path / "second.npz",
            model_path=model_path,
            work_dir=work_dir,
            release_manifest_path=release.manifest_path,
        )

    assert manifest_path.read_bytes() == manifest_before
    assert all(path.exists() for path in part_paths)


def test_resumable_rejects_changed_legacy_text_before_loading_model(
    tmp_path: Path,
    monkeypatch,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "legacy.md", "Legacy", "alpha")
    model_path = tmp_path / "model"
    model_path.mkdir()
    work_dir = tmp_path / "work"
    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: _FakeBgeModel(),
    )
    build_bge_m3_vector_index_resumable(
        processed_dir=processed,
        index_path=tmp_path / "first.npz",
        model_path=model_path,
        work_dir=work_dir,
    )

    manifest_path = work_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["release_id"] is None
    assert manifest["input_fingerprint"]
    manifest_before = manifest_path.read_bytes()

    chunks_path = next(processed.rglob("chunks.jsonl"))
    chunks = [
        json.loads(line)
        for line in chunks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    original_chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    chunks[0]["text"] = "changed text with the same chunk id"
    chunks_path.write_text(
        "\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in chunks) + "\n",
        encoding="utf-8",
    )
    assert [
        json.loads(line)["chunk_id"]
        for line in chunks_path.read_text(encoding="utf-8").splitlines()
    ] == original_chunk_ids
    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: pytest.fail("model must not load for mismatched work_dir"),
    )

    with pytest.raises(
        vector_index.VectorIndexError,
        match="^resumable_work_dir_input_mismatch$",
    ):
        build_bge_m3_vector_index_resumable(
            processed_dir=processed,
            index_path=tmp_path / "second.npz",
            model_path=model_path,
            work_dir=work_dir,
        )

    assert manifest_path.read_bytes() == manifest_before


@pytest.mark.parametrize(
    ("changed_argument", "changed_value"),
    [
        ("model_path", "other-model"),
        ("max_length", 128),
        ("batch_size", 1),
    ],
)
def test_resumable_rejects_changed_build_identity_before_loading_model(
    tmp_path: Path,
    monkeypatch,
    changed_argument: str,
    changed_value,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "legacy.md", "Legacy", "alpha beta")
    model_path = tmp_path / "model"
    model_path.mkdir()
    work_dir = tmp_path / "work"
    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: _FakeBgeModel(),
    )
    build_bge_m3_vector_index_resumable(
        processed_dir=processed,
        index_path=tmp_path / "first.npz",
        model_path=model_path,
        work_dir=work_dir,
        batch_size=2,
        max_length=256,
    )
    kwargs = {
        "processed_dir": processed,
        "index_path": tmp_path / "second.npz",
        "model_path": model_path,
        "work_dir": work_dir,
        "batch_size": 2,
        "max_length": 256,
    }
    if changed_argument == "model_path":
        other_model = tmp_path / str(changed_value)
        other_model.mkdir()
        kwargs[changed_argument] = other_model
    else:
        kwargs[changed_argument] = changed_value
    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: pytest.fail("model must not load for mismatched work_dir"),
    )

    with pytest.raises(
        vector_index.VectorIndexError,
        match="^resumable_work_dir_input_mismatch$",
    ):
        build_bge_m3_vector_index_resumable(**kwargs)


@pytest.mark.parametrize("corruption", ["rows", "dimension"])
def test_resumable_rejects_corrupt_part_shape(tmp_path: Path, monkeypatch, corruption: str):
    import numpy as np

    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "legacy.md", "Legacy", "alpha beta")
    model_path = tmp_path / "model"
    model_path.mkdir()
    work_dir = tmp_path / "work"
    monkeypatch.setattr(
        "agent_knowledge_hub.vector_index._load_bge_m3_model",
        lambda _path: _FakeBgeModel(),
    )
    build_bge_m3_vector_index_resumable(
        processed_dir=processed,
        index_path=tmp_path / "first.npz",
        model_path=model_path,
        work_dir=work_dir,
        batch_size=1,
    )
    parts = sorted(work_dir.glob("part_*.npy"))
    assert parts
    matrix = np.load(parts[0])
    if corruption == "rows":
        matrix = np.vstack([matrix, matrix])
    else:
        matrix = np.pad(matrix, ((0, 0), (0, 1)))
    np.save(parts[0], matrix)

    with pytest.raises(
        vector_index.VectorIndexError,
        match="^resumable_part_invalid$",
    ):
        build_bge_m3_vector_index_resumable(
            processed_dir=processed,
            index_path=tmp_path / "second.npz",
            model_path=model_path,
            work_dir=work_dir,
            batch_size=1,
        )
