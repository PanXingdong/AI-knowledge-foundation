import json
from pathlib import Path

import pytest

from agent_knowledge_hub.cli import main
from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.release_manifest import load_release_manifest
from agent_knowledge_hub.release_pipeline import build_release_bundle
from agent_knowledge_hub.retrieval import build_context_pack_for_processed_dir


def _ingest(processed: Path, source: Path, title: str, text: str):
    source.write_text(f"# {title}\n\n{text}", encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=processed,
        title=title,
        document_version="v1",
    )


def test_build_release_bundle_produces_ready_consistent_unactivated_release(
    tmp_path: Path,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One", "alpha API " * 20)
    _ingest(processed, tmp_path / "two.md", "Two", "beta API " * 20)
    releases = tmp_path / "releases"
    active_pointer = releases / "active-release.json"

    ready = build_release_bundle(processed, releases)

    assert ready.status == "ready"
    assert ready.indexes["fts"]["sha256"]
    assert ready.indexes["vector"]["sha256"]
    assert ready.baseline and ready.baseline["sha256"]
    assert not active_pointer.exists()
    result = build_context_pack_for_processed_dir(
        processed_dir=processed,
        release_manifest_path=ready.manifest_path,
        fts_index_path=ready.resolve_artifact("fts"),
        vector_index_path=ready.resolve_artifact("vector"),
        query="alpha",
    )
    assert result.selected_chunks


def test_build_and_activate_release_cli_requires_explicit_activation(
    tmp_path: Path,
    capsys,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One", "alpha")
    releases = tmp_path / "releases"
    active_pointer = releases / "active-release.json"

    assert main(
        [
            "build-release",
            "--processed-dir",
            str(processed),
            "--releases-dir",
            str(releases),
        ]
    ) == 0
    build_payload = json.loads(capsys.readouterr().out)
    assert build_payload["status"] == "ready"
    assert build_payload["release_id"]
    assert build_payload["manifest_path"]
    assert not active_pointer.exists()

    assert main(
        [
            "activate-release",
            "--manifest-path",
            build_payload["manifest_path"],
            "--active-pointer",
            str(active_pointer),
        ]
    ) == 0
    activate_payload = json.loads(capsys.readouterr().out)
    assert activate_payload == {
        "active_pointer": str(active_pointer.resolve()),
        "manifest_path": build_payload["manifest_path"],
        "release_id": build_payload["release_id"],
        "status": "ready",
    }
    assert json.loads(active_pointer.read_text(encoding="utf-8"))["release_id"] == (
        build_payload["release_id"]
    )


def test_context_pack_cli_uses_ready_release_manifest_and_bound_indexes(
    tmp_path: Path,
    capsys,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One", "alpha API " * 20)
    releases = tmp_path / "releases"
    assert main(
        [
            "build-release",
            "--processed-dir",
            str(processed),
            "--releases-dir",
            str(releases),
        ]
    ) == 0
    build_payload = json.loads(capsys.readouterr().out)
    ready = load_release_manifest(Path(build_payload["manifest_path"]))

    assert main(
        [
            "context-pack",
            "--processed-dir",
            str(processed),
            "--release-manifest-path",
            str(ready.manifest_path),
            "--fts-index-path",
            str(ready.resolve_artifact("fts")),
            "--vector-index-path",
            str(ready.resolve_artifact("vector")),
            "--query",
            "alpha",
            "--output-dir",
            str(tmp_path / "context-pack"),
        ]
    ) == 0

    context_payload = json.loads(capsys.readouterr().out)
    assert context_payload["release_id"] == ready.release_id


def test_context_pack_cli_rejects_mismatched_release_indexes(
    tmp_path: Path,
    capsys,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One", "alpha API " * 20)
    releases = tmp_path / "releases"
    assert main(
        [
            "build-release",
            "--processed-dir",
            str(processed),
            "--releases-dir",
            str(releases),
        ]
    ) == 0
    first_payload = json.loads(capsys.readouterr().out)
    first = load_release_manifest(Path(first_payload["manifest_path"]))
    _ingest(processed, tmp_path / "two.md", "Two", "beta API " * 20)
    assert main(
        [
            "build-release",
            "--processed-dir",
            str(processed),
            "--releases-dir",
            str(releases),
        ]
    ) == 0
    second_payload = json.loads(capsys.readouterr().out)

    assert main(
        [
            "context-pack",
            "--processed-dir",
            str(processed),
            "--release-manifest-path",
            second_payload["manifest_path"],
            "--fts-index-path",
            str(first.resolve_artifact("fts")),
            "--vector-index-path",
            str(first.resolve_artifact("vector")),
            "--query",
            "alpha",
            "--output-dir",
            str(tmp_path / "mismatched-context-pack"),
        ]
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ERROR: fts_release_mismatch:" in captured.err


def test_index_failure_preserves_candidate_diagnostics_without_activation(
    tmp_path: Path,
    monkeypatch,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One", "alpha")
    releases = tmp_path / "releases"

    def fail_vector_index(**_kwargs):
        raise RuntimeError("vector build failed")

    monkeypatch.setattr(
        "agent_knowledge_hub.release_pipeline.build_vector_index",
        fail_vector_index,
    )

    with pytest.raises(RuntimeError, match="vector build failed"):
        build_release_bundle(processed, releases)

    manifests = list(releases.glob("*/release-manifest.json"))
    assert len(manifests) == 1
    candidate = load_release_manifest(manifests[0])
    assert candidate.status == "candidate"
    assert (candidate.manifest_path.parent / "indexes" / "chunks.fts.sqlite").is_file()
    assert not (releases / "active-release.json").exists()


def test_repeated_build_of_ready_release_is_idempotent(
    tmp_path: Path,
    monkeypatch,
):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One", "alpha")
    releases = tmp_path / "releases"
    first = build_release_bundle(processed, releases)
    tracked_paths = [
        first.manifest_path,
        first.resolve_artifact("fts"),
        first.resolve_artifact("vector"),
        first.manifest_path.parent / first.baseline["path"],
    ]
    before = {path: path.read_bytes() for path in tracked_paths}

    def unexpected_rebuild(**_kwargs):
        raise AssertionError("ready release artifacts must not be rebuilt")

    monkeypatch.setattr(
        "agent_knowledge_hub.release_pipeline.build_fts_index",
        unexpected_rebuild,
    )
    monkeypatch.setattr(
        "agent_knowledge_hub.release_pipeline.build_vector_index",
        unexpected_rebuild,
    )

    second = build_release_bundle(processed, releases)

    assert second == first
    assert {path: path.read_bytes() for path in tracked_paths} == before


def test_legacy_direct_index_cli_remains_supported(tmp_path: Path, capsys):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One", "alpha")
    index_path = tmp_path / "legacy" / "chunks.vector.json"

    assert main(
        [
            "build-vector-index",
            "--processed-dir",
            str(processed),
            "--index-path",
            str(index_path),
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["index_path"] == str(index_path.resolve())
    assert payload["release_id"] is None
