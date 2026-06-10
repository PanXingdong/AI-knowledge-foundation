import csv
import json
from pathlib import Path

from agent_knowledge_hub.inventory import (
    build_document_inventory,
    write_document_inventory_bundle,
)


def test_document_inventory_discovers_supported_documents_and_writes_manifest(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "qualcomm-bsp.md").write_text(
        "# Qualcomm BSP\n\nInterface constraints must be traced.",
        encoding="utf-8",
    )
    (root / "bosch-diagnostic.txt").write_text(
        "Bosch diagnostic constraints require DTC synchronization.",
        encoding="utf-8",
    )
    (root / "notes.bin").write_bytes(b"ignored")
    excluded = root / ".git"
    excluded.mkdir()
    (excluded / "hidden.md").write_text("should not be discovered", encoding="utf-8")

    inventory = build_document_inventory(
        root_dirs=[root],
        max_files=10,
        max_file_mb=1,
    )
    paths = {Path(item.source_path).name for item in inventory.documents}

    assert inventory.document_count == 2
    assert paths == {"qualcomm-bsp.md", "bosch-diagnostic.txt"}
    assert inventory.documents[0].content_hash
    assert {item.supplier for item in inventory.documents} == {"Qualcomm", "Bosch"}
    assert any(skipped["reason"] == "unsupported_extension" for skipped in inventory.skipped)

    bundle = write_document_inventory_bundle(
        output_dir=tmp_path / "inventory-out",
        inventory=inventory,
        sample_size=2,
    )

    payload = json.loads(bundle["json_path"].read_text(encoding="utf-8"))
    assert payload["document_count"] == 2
    assert "Document Inventory" in bundle["markdown_path"].read_text(encoding="utf-8")

    with bundle["manifest_path"].open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 2
    assert rows[0]["sample_id"].startswith("doc-")
    assert rows[0]["file_path"]
    assert rows[0]["owner"] == "checker"


def test_document_inventory_limits_large_files(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    large = root / "large.md"
    large.write_text("x" * 2048, encoding="utf-8")

    inventory = build_document_inventory(
        root_dirs=[root],
        max_files=10,
        max_file_mb=0.001,
    )

    assert inventory.document_count == 0
    assert inventory.skipped[0]["reason"] == "file_too_large"


def test_document_inventory_supports_keywords_and_content_hash_dedup(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    gbt = root / "GBT-44464.md"
    gbt.write_text("# GBT\n\nImportant data constraints.", encoding="utf-8")
    account = root / "账号.txt"
    account.write_text("do not include account material", encoding="utf-8")
    duplicate = root / "copy-of-gbt.md"
    duplicate.write_text(gbt.read_text(encoding="utf-8"), encoding="utf-8")

    inventory = build_document_inventory(
        root_dirs=[root],
        include_keywords=["gbt"],
        exclude_keywords=["账号"],
        dedupe_content_hash=True,
        max_files=10,
        max_file_mb=1,
    )

    assert inventory.document_count == 1
    assert inventory.documents[0].file_name == "GBT-44464.md"
    reasons = {item["reason"] for item in inventory.skipped}
    assert "duplicate_content_hash" in reasons
    assert "excluded_by_keyword" in reasons or "not_matched_by_include_keyword" in reasons


def test_document_inventory_splits_keyword_arguments_from_shell_forms(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "internal-vehicle-data-spec.md").write_text("internal spec", encoding="utf-8")
    (root / "review-checklist.txt").write_text("review checklist", encoding="utf-8")
    (root / "vehicle-data-architecture.html").write_text(
        "<html><body>architecture</body></html>",
        encoding="utf-8",
    )
    (root / "account-password.txt").write_text("sensitive", encoding="utf-8")

    inventory = build_document_inventory(
        root_dirs=[root],
        include_keywords=["internal,review architecture"],
        exclude_keywords=["account password"],
        max_files=10,
        max_file_mb=1,
    )

    assert inventory.document_count == 3
    assert {document.file_name for document in inventory.documents} == {
        "internal-vehicle-data-spec.md",
        "review-checklist.txt",
        "vehicle-data-architecture.html",
    }
    assert any(item["reason"] == "excluded_by_keyword" for item in inventory.skipped)
