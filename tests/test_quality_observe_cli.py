import json
from pathlib import Path

import pytest

from agent_knowledge_hub.cli import main
from agent_knowledge_hub.pipeline import ingest_file


def _ingest(tmp_path: Path, text: str = "# Healthy\n\nEnough healthy content."):
    source = tmp_path / "source.md"
    source.write_text(text, encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=tmp_path / "processed",
        title="Source",
        document_version="v1",
    )


def test_evaluate_quality_cli_writes_observe_bundle_from_real_result(
    tmp_path: Path,
    capsys,
):
    _ingest(tmp_path)
    output_dir = tmp_path / "quality"

    exit_code = main(
        [
            "evaluate-quality",
            "--processed-dir",
            str(tmp_path / "processed"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    report = json.loads((output_dir / "quality-report.json").read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": report["schema_version"],
        "policy_id": report["policy_id"],
        "policy_version": report["policy_version"],
        "mode": report["mode"],
        "determinism_fingerprint": report["determinism_fingerprint"],
        "report_json": str(output_dir.resolve() / "quality-report.json"),
        "report_markdown": str(output_dir.resolve() / "quality-report.md"),
        "publication_preview": str(output_dir.resolve() / "publication-preview.json"),
        "quarantine_preview": str(output_dir.resolve() / "quarantine-preview.json"),
    }
    assert payload["mode"] == "observe"
    assert set(path.name for path in output_dir.iterdir()) == {
        "quality-report.json",
        "quality-report.md",
        "publication-preview.json",
        "quarantine-preview.json",
    }
    assert "Enough healthy content." not in stdout


def test_evaluate_quality_cli_returns_zero_for_hard_recommendations(
    tmp_path: Path,
    capsys,
):
    ingested = _ingest(tmp_path, "# Broken\n\nEvidence content.")
    canonical = json.loads(ingested.document_json_path.read_text(encoding="utf-8"))
    canonical["evidence_spans"][0]["text_hash"] = "0" * 64
    ingested.document_json_path.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_dir = tmp_path / "quality"

    exit_code = main(
        [
            "evaluate-quality",
            "--processed-dir",
            str(tmp_path / "processed"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    capsys.readouterr()
    report = json.loads((output_dir / "quality-report.json").read_text(encoding="utf-8"))
    assert any(
        decision["recommended_action"] in {
            "quarantine",
            "block_document",
            "block_release",
        }
        for decision in report["decisions"]
    )
    assert all(
        decision["effective_action"] in {"allow", "warn"}
        for decision in report["decisions"]
    )


def test_evaluate_quality_cli_does_not_mutate_inputs_or_publication_state(
    tmp_path: Path,
    capsys,
):
    _ingest(tmp_path)
    protected = {
        tmp_path / "releases" / "release-manifest.json": "release",
        tmp_path / "indexes" / "chunks.fts.sqlite": "index",
        tmp_path / "active-release.json": "active",
        tmp_path / "retrieval-state.json": "retrieval",
    }
    for path, content in protected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    processed = tmp_path / "processed"
    before = {
        path.relative_to(processed): path.read_bytes()
        for path in processed.rglob("*")
        if path.is_file()
    }

    exit_code = main(
        [
            "evaluate-quality",
            "--processed-dir",
            str(processed),
            "--output-dir",
            str(tmp_path / "quality"),
        ]
    )

    assert exit_code == 0
    capsys.readouterr()
    assert {
        path.relative_to(processed): path.read_bytes()
        for path in processed.rglob("*")
        if path.is_file()
    } == before
    assert {path: path.read_text(encoding="utf-8") for path in protected} == protected


def test_evaluate_quality_cli_rejects_missing_processed_dir(
    tmp_path: Path,
    capsys,
):
    exit_code = main(
        [
            "evaluate-quality",
            "--processed-dir",
            str(tmp_path / "missing"),
            "--output-dir",
            str(tmp_path / "quality"),
        ]
    )

    assert exit_code == 2
    assert "Processed directory does not exist" in capsys.readouterr().err


def test_evaluate_quality_cli_rejects_invalid_policy(tmp_path: Path, capsys):
    _ingest(tmp_path)
    policy_path = tmp_path / "invalid-policy.json"
    policy_path.write_text("{}", encoding="utf-8")

    exit_code = main(
        [
            "evaluate-quality",
            "--processed-dir",
            str(tmp_path / "processed"),
            "--output-dir",
            str(tmp_path / "quality"),
            "--policy-path",
            str(policy_path),
        ]
    )

    assert exit_code == 2
    assert "unsupported_quality_policy_schema" in capsys.readouterr().err


@pytest.mark.parametrize(
    "raw_policy",
    [
        b"[]",
        b"\xff",
    ],
    ids=["array", "invalid_utf8"],
)
def test_evaluate_quality_cli_normalizes_unreadable_policy(
    tmp_path: Path,
    capsys,
    raw_policy: bytes,
):
    _ingest(tmp_path)
    policy_path = tmp_path / "invalid-policy.json"
    policy_path.write_bytes(raw_policy)

    exit_code = main(
        [
            "evaluate-quality",
            "--processed-dir",
            str(tmp_path / "processed"),
            "--output-dir",
            str(tmp_path / "quality"),
            "--policy-path",
            str(policy_path),
        ]
    )

    assert exit_code == 2
    assert "invalid_quality_policy" in capsys.readouterr().err


def test_legacy_parse_quality_summary_cli_remains_compatible(
    tmp_path: Path,
    capsys,
):
    _ingest(tmp_path)
    output_dir = tmp_path / "legacy-quality"

    exit_code = main(
        [
            "parse-quality-summary",
            "--processed-dir",
            str(tmp_path / "processed"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["processed_document_count"] == 1
    assert payload["json_path"] == str(output_dir.resolve() / "parse-quality-summary.json")
    assert payload["markdown_path"] == str(
        output_dir.resolve() / "parse-quality-summary.md"
    )
    assert (output_dir / "parse-quality-summary.json").is_file()
    assert (output_dir / "parse-quality-summary.md").is_file()
