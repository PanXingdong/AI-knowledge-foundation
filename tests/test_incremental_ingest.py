import csv
import json
from pathlib import Path

from agent_knowledge_hub.incremental import ingest_manifest_incremental


def _write_manifest(path: Path, source: Path) -> None:
    rows = [
        {
            "sample_id": "sample-001",
            "file_path": str(source),
            "document_title": "Incremental SPEC",
            "slot_type": "internal spec",
            "owner": "checker",
            "project": "vehicle-data",
            "supplier": "internal",
            "document_version": "v1",
        }
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_incremental_ingest_skips_unchanged_documents_and_reprocesses_changed(tmp_path: Path):
    source = tmp_path / "spec.md"
    source.write_text(
        "# SPEC\n\nImportant data storage requires permission control.",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    processed = tmp_path / "processed"
    _write_manifest(manifest, source)

    first = ingest_manifest_incremental(
        manifest_path=manifest,
        out_dir=processed,
        project_root=tmp_path,
    )

    assert first.processed_count == 1
    assert first.unchanged_count == 0
    assert first.failed_count == 0
    assert (processed / "ingest-run-summary.json").exists()
    assert (processed / "ingest-state.json").exists()

    second = ingest_manifest_incremental(
        manifest_path=manifest,
        out_dir=processed,
        project_root=tmp_path,
    )

    assert second.processed_count == 0
    assert second.unchanged_count == 1

    source.write_text(
        "# SPEC\n\nImportant data storage requires permission control and encryption.",
        encoding="utf-8",
    )
    third = ingest_manifest_incremental(
        manifest_path=manifest,
        out_dir=processed,
        project_root=tmp_path,
    )

    assert third.processed_count == 1
    assert third.unchanged_count == 0
    assert third.changed_count == 1

    summary = json.loads((processed / "ingest-run-summary.json").read_text(encoding="utf-8"))
    assert summary["processed_count"] == 1
    assert summary["changed_count"] == 1
    assert summary["documents"][0]["content_hash"]


def test_incremental_ingest_records_missing_inputs_without_failing(tmp_path: Path):
    manifest = tmp_path / "manifest.csv"
    missing = tmp_path / "missing.md"
    _write_manifest(manifest, missing)

    summary = ingest_manifest_incremental(
        manifest_path=manifest,
        out_dir=tmp_path / "processed",
        project_root=tmp_path,
    )

    assert summary.processed_count == 0
    assert summary.skipped_count == 1
    assert summary.skipped[0]["reason"] == "missing_or_placeholder_path"
