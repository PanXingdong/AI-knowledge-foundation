from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from agent_knowledge_hub.parsers import SUPPORTED_EXTENSIONS
from agent_knowledge_hub.utils import file_sha256, normalize_space, slugify, utc_now_iso, write_json


DEFAULT_EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "AppData",
    "$Recycle.Bin",
    "Windows",
    "Program Files",
    "Program Files (x86)",
}


@dataclass(frozen=True)
class InventoryDocument:
    sample_id: str
    source_path: str
    relative_path: str
    file_name: str
    extension: str
    size_bytes: int
    content_hash: str
    title: str
    source_type: str
    owner: str
    project: str
    supplier: str
    document_version: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentInventory:
    root_dirs: list[str]
    generated_at: str
    document_count: int
    skipped_count: int
    extension_counts: dict[str, int]
    supplier_counts: dict[str, int]
    documents: list[InventoryDocument]
    skipped: list[dict[str, str]]
    markdown: str

    def to_dict(self) -> dict[str, object]:
        return {
            "root_dirs": list(self.root_dirs),
            "generated_at": self.generated_at,
            "document_count": self.document_count,
            "skipped_count": self.skipped_count,
            "extension_counts": dict(self.extension_counts),
            "supplier_counts": dict(self.supplier_counts),
            "documents": [document.to_dict() for document in self.documents],
            "skipped": list(self.skipped),
        }


def build_document_inventory(
    *,
    root_dirs: list[Path | str],
    max_files: int = 200,
    max_file_mb: float = 100.0,
    owner: str = "checker",
    project: str = "unknown",
    document_version: str = "unknown",
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    dedupe_content_hash: bool = True,
) -> DocumentInventory:
    if max_files <= 0:
        raise ValueError("max_files must be > 0")
    if max_file_mb <= 0:
        raise ValueError("max_file_mb must be > 0")

    roots = [Path(root).resolve() for root in root_dirs]
    existing_roots = [root for root in roots if root.exists()]
    skipped: list[dict[str, str]] = []
    for root in roots:
        if not root.exists():
            skipped.append({"path": str(root), "reason": "root_not_found"})

    documents: list[InventoryDocument] = []
    max_size_bytes = int(max_file_mb * 1024 * 1024)
    seen_paths: set[Path] = set()
    seen_hashes: set[str] = set()
    normalized_include_keywords = _normalize_keywords(include_keywords)
    normalized_exclude_keywords = _normalize_keywords(exclude_keywords)

    for root in existing_roots:
        for path in sorted(
            _iter_candidate_files(root),
            key=lambda item: _candidate_sort_key(item, normalized_include_keywords),
        ):
            if len(documents) >= max_files:
                skipped.append({"path": str(path), "reason": "max_files_reached"})
                continue
            if path in seen_paths:
                continue
            seen_paths.add(path)

            suffix = path.suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS:
                skipped.append({"path": str(path), "reason": "unsupported_extension"})
                continue
            keyword_text = _keyword_match_text(path)
            if normalized_exclude_keywords and _matches_any_keyword(
                keyword_text,
                normalized_exclude_keywords,
            ):
                skipped.append({"path": str(path), "reason": "excluded_by_keyword"})
                continue
            if normalized_include_keywords and not _matches_any_keyword(
                keyword_text,
                normalized_include_keywords,
            ):
                skipped.append({"path": str(path), "reason": "not_matched_by_include_keyword"})
                continue

            try:
                size_bytes = path.stat().st_size
            except OSError as exc:
                skipped.append({"path": str(path), "reason": f"stat_failed: {exc}"})
                continue
            if size_bytes > max_size_bytes:
                skipped.append({"path": str(path), "reason": "file_too_large"})
                continue

            try:
                content_hash = file_sha256(path)
            except OSError as exc:
                skipped.append({"path": str(path), "reason": f"hash_failed: {exc}"})
                continue
            if dedupe_content_hash and content_hash in seen_hashes:
                skipped.append({"path": str(path), "reason": "duplicate_content_hash"})
                continue
            seen_hashes.add(content_hash)

            supplier = _infer_supplier_from_path(path)
            source_type = _infer_source_type(path)
            relative_path = _safe_relative_path(path, root)
            documents.append(
                InventoryDocument(
                    sample_id=_build_sample_id(len(documents) + 1, path),
                    source_path=str(path),
                    relative_path=relative_path,
                    file_name=path.name,
                    extension=suffix.lstrip("."),
                    size_bytes=size_bytes,
                    content_hash=content_hash,
                    title=_infer_title(path),
                    source_type=source_type,
                    owner=owner,
                    project=project,
                    supplier=supplier,
                    document_version=document_version,
                )
            )

    documents = sorted(documents, key=lambda item: (item.extension, item.source_path.lower()))
    extension_counts = Counter(document.extension for document in documents)
    supplier_counts = Counter(document.supplier for document in documents)
    generated_at = utc_now_iso()
    inventory_without_markdown = DocumentInventory(
        root_dirs=[str(root) for root in roots],
        generated_at=generated_at,
        document_count=len(documents),
        skipped_count=len(skipped),
        extension_counts=dict(sorted(extension_counts.items())),
        supplier_counts=dict(sorted(supplier_counts.items())),
        documents=documents,
        skipped=skipped,
        markdown="",
    )
    return DocumentInventory(
        root_dirs=inventory_without_markdown.root_dirs,
        generated_at=inventory_without_markdown.generated_at,
        document_count=inventory_without_markdown.document_count,
        skipped_count=inventory_without_markdown.skipped_count,
        extension_counts=inventory_without_markdown.extension_counts,
        supplier_counts=inventory_without_markdown.supplier_counts,
        documents=inventory_without_markdown.documents,
        skipped=inventory_without_markdown.skipped,
        markdown=_render_inventory_markdown(inventory_without_markdown),
    )


def write_document_inventory_bundle(
    *,
    output_dir: Path | str,
    inventory: DocumentInventory,
    sample_size: int | None = None,
) -> dict[str, Path]:
    bundle_dir = Path(output_dir).resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    json_path = bundle_dir / "document-inventory.json"
    markdown_path = bundle_dir / "document-inventory.md"
    manifest_path = bundle_dir / "raw-docs-sample-manifest.csv"

    write_json(json_path, inventory.to_dict())
    markdown_path.write_text(inventory.markdown, encoding="utf-8")
    _write_sample_manifest(
        manifest_path=manifest_path,
        documents=inventory.documents[:sample_size] if sample_size else inventory.documents,
    )
    return {
        "json_path": json_path,
        "markdown_path": markdown_path,
        "manifest_path": manifest_path,
    }


def _iter_candidate_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if child.name in DEFAULT_EXCLUDED_DIR_NAMES:
                    continue
                stack.insert(0, child)
            elif child.is_file():
                candidates.append(child.resolve())
    return candidates


def _safe_relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def _build_sample_id(index: int, path: Path) -> str:
    return f"doc-{index:04d}-{slugify(path.stem, fallback='document')[:40]}"


def _infer_title(path: Path) -> str:
    return normalize_space(path.stem.replace("_", " ").replace("-", " ")) or path.name


def _infer_supplier_from_path(path: Path) -> str:
    text = str(path).lower()
    if "qualcomm" in text or "高通" in text:
        return "Qualcomm"
    if "bosch" in text or "博世" in text:
        return "Bosch"
    if "qnx" in text:
        return "QNX"
    if "gbt" in text or "gb/t" in text or "44464" in text:
        return "GB"
    return "unknown"


def _infer_source_type(path: Path) -> str:
    text = str(path).lower()
    if "spec" in text:
        return "internal spec"
    if "architecture" in text or "架构" in text:
        return "architecture"
    if "checklist" in text or "review" in text:
        return "review checklist"
    if _infer_supplier_from_path(path) != "unknown":
        return "supplier document"
    return "engineering document"


def _normalize_keywords(keywords: list[str] | None) -> list[str]:
    if not keywords:
        return []
    normalized: list[str] = []
    for keyword in keywords:
        for part in re.split(r"[,;\s]+", keyword):
            value = part.strip().lower()
            if value:
                normalized.append(value)
    return normalized


def _keyword_match_text(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


def _matches_any_keyword(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _candidate_sort_key(path: Path, include_keywords: list[str]) -> tuple[int, int, str]:
    file_name = path.name.lower()
    if not include_keywords:
        return (0, 0, str(path).lower())

    positions = [file_name.find(keyword) for keyword in include_keywords if keyword in file_name]
    if not positions:
        return (2, 999999, str(path).lower())
    best_position = min(positions)
    starts_with_keyword = any(file_name.startswith(keyword) for keyword in include_keywords)
    return (0 if starts_with_keyword else 1, best_position, str(path).lower())


def _write_sample_manifest(*, manifest_path: Path, documents: list[InventoryDocument]) -> None:
    fieldnames = [
        "sample_id",
        "file_path",
        "document_title",
        "slot_type",
        "owner",
        "project",
        "supplier",
        "document_version",
        "content_hash",
    ]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for document in documents:
            writer.writerow(
                {
                    "sample_id": document.sample_id,
                    "file_path": document.source_path,
                    "document_title": document.title,
                    "slot_type": document.source_type,
                    "owner": document.owner,
                    "project": document.project,
                    "supplier": document.supplier,
                    "document_version": document.document_version,
                    "content_hash": document.content_hash,
                }
            )


def _render_inventory_markdown(inventory: DocumentInventory) -> str:
    lines = [
        "# Document Inventory",
        "",
        f"Generated At: `{inventory.generated_at}`",
        "",
        "## Totals",
        "",
        f"- Documents: {inventory.document_count}",
        f"- Skipped: {inventory.skipped_count}",
        "",
        "## Extension Counts",
        "",
    ]
    if inventory.extension_counts:
        lines.extend(
            f"- `{extension}`: {count}"
            for extension, count in sorted(inventory.extension_counts.items())
        )
    else:
        lines.append("- None")

    lines.extend(["", "## Documents", ""])
    if inventory.documents:
        lines.extend(
            [
                "| Sample | Title | Type | Supplier | Size | Path |",
                "| --- | --- | --- | --- | ---: | --- |",
            ]
        )
        for document in inventory.documents:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_table_cell(document.sample_id),
                        _escape_table_cell(document.title),
                        _escape_table_cell(document.source_type),
                        _escape_table_cell(document.supplier),
                        str(document.size_bytes),
                        _escape_table_cell(document.source_path),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Skipped", ""])
    if inventory.skipped:
        for skipped in inventory.skipped[:50]:
            lines.append(f"- `{skipped.get('reason', 'unknown')}`: `{skipped.get('path', '')}`")
    else:
        lines.append("- None")

    return "\n".join(lines).strip() + "\n"


def _escape_table_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
