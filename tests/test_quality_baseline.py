import json
from pathlib import Path

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.quality_baseline import build_quality_baseline
from agent_knowledge_hub.release_manifest import create_candidate_release
from agent_knowledge_hub.utils import file_sha256, write_json


def _ingest(processed: Path, source: Path, title: str):
    source.write_text(f"# {title}\n\n{title} evidence", encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=processed,
        title=title,
        document_version="v1",
    )


def _build_candidate_with_two_documents(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One")
    _ingest(processed, tmp_path / "two.md", "Two")
    return create_candidate_release(processed, tmp_path / "releases")


def test_baseline_is_deterministic_and_does_not_write_files(tmp_path: Path):
    release = _build_candidate_with_two_documents(tmp_path)
    before = sorted(
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file()
    )

    first = build_quality_baseline(release.manifest_path)
    second = build_quality_baseline(release.manifest_path)

    after = sorted(
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert first.to_dict() == second.to_dict()
    assert before == after
    assert first.release_id == release.release_id
    assert first.document_count == 2
    assert first.chunk_count >= 2
    assert first.evidence_count >= 2
    assert first.traceable_chunk_count == first.chunk_count
    assert first.traceable_chunk_ratio == 1.0
    assert first.quality_status_counts == {"low_quality": 2}
    assert first.parser_counts == {"stdlib-markdown-block-parser": 2}
    assert first.source_format_counts == {"markdown": 2}
    assert first.warning_count == 0
    assert "created_at" not in first.to_dict()
    assert not any(
        str(tmp_path.resolve()) in str(value) for value in first.to_dict().values()
    )


def test_baseline_counts_chunk_only_when_all_evidence_references_exist(
    tmp_path: Path,
):
    release = _build_candidate_with_two_documents(tmp_path)
    document = release.documents[0]
    chunks_path = Path(release.processed_dir) / document.chunks_path
    rows = [
        json.loads(line)
        for line in chunks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows[0]["evidence_ids"].append("span_missing")
    chunks_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    manifest_payload = json.loads(
        release.manifest_path.read_text(encoding="utf-8")
    )
    manifest_payload["documents"][0]["chunks_sha256"] = file_sha256(chunks_path)
    write_json(release.manifest_path, manifest_payload)

    baseline = build_quality_baseline(release.manifest_path)

    assert baseline.traceable_chunk_count == baseline.chunk_count - 1
    assert baseline.traceable_chunk_ratio == round(
        (baseline.chunk_count - 1) / baseline.chunk_count,
        8,
    )


def test_baseline_quality_status_comes_from_pinned_canonical(
    tmp_path: Path,
):
    release = _build_candidate_with_two_documents(tmp_path)
    payload = json.loads(release.manifest_path.read_text(encoding="utf-8"))
    payload["documents"][0]["quality_status"] = "manifest_override"
    payload["documents"][1]["quality_status"] = "manifest_override"
    write_json(release.manifest_path, payload)

    baseline = build_quality_baseline(release.manifest_path)

    assert baseline.quality_status_counts == {"low_quality": 2}
