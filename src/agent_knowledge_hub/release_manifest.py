from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from agent_knowledge_hub.processing_record import (
    CHUNKER_VERSION,
    PROCESSING_RECORD_SCHEMA_VERSION,
    QUALITY_RULES_VERSION,
    load_or_infer_processing_record,
    processing_run_id,
)
from agent_knowledge_hub.quality_contracts import build_quality_record
from agent_knowledge_hub.utils import (
    file_sha256,
    normalize_space,
    sha256_bytes,
    stable_id,
    utc_now_iso,
    write_json,
)

RELEASE_MANIFEST_SCHEMA_VERSION = "knowledge-release.v1"


@dataclass(frozen=True)
class ReleaseDocument:
    document_id: str
    document_version_id: str
    canonical_path: str
    chunks_path: str
    processing_record_path: str
    quality_record_path: str
    canonical_sha256: str
    chunks_sha256: str
    quality_record_sha256: str
    processing_record_sha256: str
    processing_run_id: str
    quality_status: str
    quality_score: float | None


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: str
    release_id: str
    status: str
    created_at: str
    processed_dir: str
    quality_rules_version: str
    documents: tuple[ReleaseDocument, ...]
    indexes: dict[str, dict[str, str]]
    baseline: dict[str, str] | None
    manifest_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "release_id": self.release_id,
            "status": self.status,
            "created_at": self.created_at,
            "processed_dir": self.processed_dir,
            "quality_rules_version": self.quality_rules_version,
            "documents": [asdict(item) for item in self.documents],
            "indexes": self.indexes,
            "baseline": self.baseline,
        }

    def resolve_artifact(self, name: str) -> Path:
        relative_path = self.indexes[name]["path"]
        release_root = self.manifest_path.parent.resolve()
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError(f"release_artifact_path_escape:{name}")
        resolved = (release_root / candidate).resolve()
        try:
            resolved.relative_to(release_root)
        except ValueError as error:
            raise ValueError(f"release_artifact_path_escape:{name}") from error
        return resolved


def create_candidate_release(
    processed_dir: Path,
    releases_dir: Path,
) -> ReleaseManifest:
    processed_root = processed_dir.resolve()
    releases_root = releases_dir.resolve()
    selected = _select_latest_processed_versions(processed_root)
    drafts = [
        _release_document(processed_root, chunks_path, canonical)
        for chunks_path, canonical in selected
    ]
    drafts.sort(key=lambda item: (item[0].document_id, item[0].document_version_id))
    if not drafts:
        raise ValueError("Cannot create a release without documents")

    documents = tuple(item[0] for item in drafts)
    release_id = _compute_release_id(documents, QUALITY_RULES_VERSION)
    manifest_path = releases_root / release_id / "release-manifest.json"
    if manifest_path.exists():
        return _load_matching_existing_release(
            manifest_path,
            release_id,
            documents,
        )

    for document, derived_quality, derived_processing in drafts:
        if derived_quality is not None:
            write_json(
                manifest_path.parent / document.quality_record_path,
                derived_quality,
            )
        if derived_processing is not None:
            write_json(
                manifest_path.parent / document.processing_record_path,
                derived_processing,
            )

    manifest = ReleaseManifest(
        schema_version=RELEASE_MANIFEST_SCHEMA_VERSION,
        release_id=release_id,
        status="candidate",
        created_at=utc_now_iso(),
        processed_dir=str(processed_root),
        quality_rules_version=QUALITY_RULES_VERSION,
        documents=documents,
        indexes={},
        baseline=None,
        manifest_path=manifest_path,
    )
    write_json(manifest_path, manifest.to_dict())
    return manifest


def load_release_manifest(path: Path) -> ReleaseManifest:
    manifest_path = path.resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = tuple(ReleaseDocument(**item) for item in payload["documents"])
    return ReleaseManifest(
        schema_version=payload["schema_version"],
        release_id=payload["release_id"],
        status=payload["status"],
        created_at=payload["created_at"],
        processed_dir=payload["processed_dir"],
        quality_rules_version=payload["quality_rules_version"],
        documents=documents,
        indexes=payload["indexes"],
        baseline=payload["baseline"],
        manifest_path=manifest_path,
    )


def finalize_release(
    manifest_path: Path,
    fts_index_path: Path,
    vector_index_path: Path,
    baseline_path: Path,
) -> ReleaseManifest:
    manifest = load_release_manifest(manifest_path)
    if manifest.status == "ready":
        return _finalize_ready_idempotently(
            manifest,
            fts_index_path=fts_index_path,
            vector_index_path=vector_index_path,
            baseline_path=baseline_path,
        )
    if manifest.status != "candidate":
        raise ValueError("release_not_candidate")
    errors = validate_release_artifacts(manifest.manifest_path)
    if errors:
        raise ValueError(";".join(errors))

    release_root = manifest.manifest_path.parent.resolve()
    fts_path, fts_relative = _release_relative_artifact(
        release_root,
        fts_index_path,
        "fts",
    )
    vector_path, vector_relative = _release_relative_artifact(
        release_root,
        vector_index_path,
        "vector",
    )
    baseline_file, baseline_relative = _release_relative_artifact(
        release_root,
        baseline_path,
        "baseline",
    )
    for name, path in (
        ("fts", fts_path),
        ("vector", vector_path),
        ("baseline", baseline_file),
    ):
        if not path.is_file():
            raise ValueError(f"{name}_artifact_missing")

    from agent_knowledge_hub.fts_index import read_fts_release_id
    from agent_knowledge_hub.vector_index import read_vector_release_id

    if read_fts_release_id(fts_path) != manifest.release_id:
        raise ValueError("fts_release_mismatch")
    if read_vector_release_id(vector_path) != manifest.release_id:
        raise ValueError("vector_release_mismatch")
    baseline_payload = json.loads(baseline_file.read_text(encoding="utf-8"))
    if baseline_payload.get("release_id") != manifest.release_id:
        raise ValueError("baseline_release_mismatch")

    vector_binding = {
        "path": vector_relative,
        "sha256": file_sha256(vector_path),
    }
    if vector_path.suffix.lower() == ".npz":
        from agent_knowledge_hub.vector_index import bge_metadata_path

        metadata_path, metadata_relative = _release_relative_artifact(
            release_root,
            bge_metadata_path(vector_path),
            "vector_metadata",
        )
        if not metadata_path.is_file():
            raise ValueError("vector_metadata_artifact_missing")
        vector_binding.update(
            {
                "metadata_path": metadata_relative,
                "metadata_sha256": file_sha256(metadata_path),
            }
        )

    ready = replace(
        manifest,
        status="ready",
        indexes={
            "fts": {
                "path": fts_relative,
                "sha256": file_sha256(fts_path),
            },
            "vector": vector_binding,
        },
        baseline={
            "path": baseline_relative,
            "sha256": file_sha256(baseline_file),
        },
    )
    _atomic_write_json(ready.manifest_path, ready.to_dict())
    return ready


def activate_release(
    manifest_path: Path,
    active_pointer_path: Path,
) -> None:
    manifest = load_release_manifest(manifest_path)
    if manifest.status != "ready":
        raise ValueError("release_not_ready")
    _validate_bound_release(manifest)

    pointer_path = active_pointer_path.resolve()
    _atomic_write_json(
        pointer_path,
        {
            "schema_version": "active-knowledge-release.v1",
            "release_id": manifest.release_id,
            "manifest_path": str(manifest.manifest_path.resolve()),
        },
    )


def load_active_release(active_pointer_path: Path) -> ReleaseManifest:
    payload = json.loads(
        active_pointer_path.resolve().read_text(encoding="utf-8")
    )
    manifest = load_release_manifest(Path(str(payload["manifest_path"])))
    if manifest.release_id != payload.get("release_id"):
        raise ValueError("active_release_mismatch")
    return manifest


def _load_matching_existing_release(
    manifest_path: Path,
    release_id: str,
    documents: tuple[ReleaseDocument, ...],
) -> ReleaseManifest:
    error_message = f"existing_release_manifest_mismatch:{release_id}"
    try:
        existing = load_release_manifest(manifest_path)
        if (
            existing.release_id != release_id
            or existing.documents != documents
            or validate_release_artifacts(manifest_path)
        ):
            raise ValueError(error_message)
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(error_message) from error
    return existing


def iter_release_documents(
    manifest_path: Path,
) -> list[tuple[Path, dict[str, Any]]]:
    errors = validate_release_artifacts(manifest_path)
    if errors:
        raise ValueError(errors[0])

    manifest = load_release_manifest(manifest_path)
    processed_root = Path(manifest.processed_dir).resolve()
    selected: list[tuple[Path, dict[str, Any]]] = []
    for document in manifest.documents:
        canonical_path = _resolve_relative(
            processed_root,
            document.canonical_path,
            "canonical_path_outside_processed_dir",
            document.document_version_id,
        )
        chunks_path = _resolve_relative(
            processed_root,
            document.chunks_path,
            "chunks_path_outside_processed_dir",
            document.document_version_id,
        )
        selected.append(
            (
                chunks_path,
                json.loads(canonical_path.read_text(encoding="utf-8")),
            )
        )
    return selected


def validate_release_artifacts(manifest_path: Path) -> list[str]:
    manifest = load_release_manifest(manifest_path)
    processed_root = Path(manifest.processed_dir).resolve()
    release_root = manifest.manifest_path.parent.resolve()
    errors: list[str] = []
    for document in manifest.documents:
        canonical_payload: dict[str, Any] | None = None
        try:
            provenance_canonical_path = _resolve_relative(
                processed_root,
                document.canonical_path,
                "canonical_path_outside_processed_dir",
                document.document_version_id,
            )
        except ValueError:
            pass
        else:
            if (
                provenance_canonical_path.is_file()
                and file_sha256(provenance_canonical_path)
                == document.canonical_sha256
            ):
                canonical_payload = json.loads(
                    provenance_canonical_path.read_text(encoding="utf-8")
                )
        processing_is_derived = _is_derived_processing_path(
            document.processing_record_path,
            document.document_version_id,
        )
        try:
            processing_path = _resolve_relative(
                release_root if processing_is_derived else processed_root,
                document.processing_record_path,
                "processing_record_path_outside_"
                + ("release_dir" if processing_is_derived else "processed_dir"),
                document.document_version_id,
            )
        except ValueError as error:
            errors.append(str(error))
        else:
            if not processing_path.is_file():
                errors.append(
                    "processing_record_artifact_missing:"
                    f"{document.document_version_id}"
                )
            else:
                processing_payload = json.loads(
                    processing_path.read_text(encoding="utf-8")
                )
                processing_error: str | None = None
                if canonical_payload is not None:
                    processing_error = _validate_processing_payload(
                        processing_payload,
                        document,
                        canonical_payload,
                    )
                if processing_error:
                    errors.append(processing_error)
                elif file_sha256(processing_path) != document.processing_record_sha256:
                    errors.append(
                        f"processing_record_hash_mismatch:{document.document_version_id}"
                    )
        quality_is_derived = _is_derived_quality_path(
            document.quality_record_path,
            document.document_version_id,
        )
        artifact_specs = (
            (
                "canonical",
                processed_root,
                document.canonical_path,
                document.canonical_sha256,
                "processed_dir",
            ),
            (
                "chunks",
                processed_root,
                document.chunks_path,
                document.chunks_sha256,
                "processed_dir",
            ),
            (
                "quality_record",
                release_root if quality_is_derived else processed_root,
                document.quality_record_path,
                document.quality_record_sha256,
                "release_dir" if quality_is_derived else "processed_dir",
            ),
        )
        for name, root, relative_path, expected_hash, root_name in artifact_specs:
            try:
                artifact_path = _resolve_relative(
                    root,
                    relative_path,
                    f"{name}_path_outside_{root_name}",
                    document.document_version_id,
                )
            except ValueError as error:
                errors.append(str(error))
                continue
            if not artifact_path.is_file():
                errors.append(
                    f"{name}_artifact_missing:{document.document_version_id}"
                )
            elif file_sha256(artifact_path) != expected_hash:
                errors.append(f"{name}_hash_mismatch:{document.document_version_id}")
            elif name == "canonical":
                canonical_payload = json.loads(
                    artifact_path.read_text(encoding="utf-8")
                )
                if (
                    _canonical_document_version_id(canonical_payload)
                    != document.document_version_id
                ):
                    errors.append(
                        "canonical_document_version_mismatch:"
                        f"{document.document_version_id}"
                    )
            elif name == "quality_record":
                quality_payload = json.loads(
                    artifact_path.read_text(encoding="utf-8")
                )
                if (
                    str(quality_payload.get("document_version_id") or "")
                    != document.document_version_id
                ):
                    errors.append(
                        "quality_record_document_version_mismatch:"
                        f"{document.document_version_id}"
                    )
    if (
        not errors
        and _compute_release_id(manifest.documents, manifest.quality_rules_version)
        != manifest.release_id
    ):
        errors.append("release_id_mismatch")
    return errors


def _release_document(
    processed_root: Path,
    chunks_path: Path,
    canonical: dict[str, Any],
) -> tuple[ReleaseDocument, dict[str, Any] | None, dict[str, Any] | None]:
    version_dir = chunks_path.parent
    canonical_path = version_dir / "canonical-document.json"
    document_version_id = _canonical_document_version_id(canonical)
    processing_record = load_or_infer_processing_record(version_dir)
    if processing_record.document_version_id != document_version_id:
        raise ValueError(
            "processing_record_document_version_mismatch:"
            f"{document_version_id}"
        )
    quality_path = version_dir / "quality-record.json"
    derived_quality: dict[str, Any] | None = None
    if quality_path.exists():
        quality_payload = json.loads(quality_path.read_text(encoding="utf-8"))
        if (
            str(quality_payload.get("document_version_id") or "")
            != document_version_id
        ):
            raise ValueError(
                "quality_record_document_version_mismatch:"
                f"{document_version_id}"
            )
        quality_record_path = quality_path.relative_to(processed_root).as_posix()
        quality_hash = file_sha256(quality_path)
    else:
        chunks = _read_jsonl(chunks_path)
        derived_quality = build_quality_record(canonical, chunks).to_dict()
        quality_record_path = (
            f"derived-quality/{processing_record.document_version_id}.json"
        )
        quality_hash = sha256_bytes(_json_content(derived_quality))

    document = canonical.get("document") or {}
    signals = (
        quality_payload["signals"]
        if quality_path.exists()
        else derived_quality["signals"]
    )
    status = signals["parse_quality_status"]["value"]
    raw_score = signals["parse_quality_score"]["value"]
    quality_score = (
        float(raw_score)
        if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool)
        else None
    )
    processing_path = version_dir / "processing-record.json"
    derived_processing: dict[str, Any] | None = None
    if processing_path.exists():
        processing_record_path = processing_path.relative_to(processed_root).as_posix()
        processing_record_hash = file_sha256(processing_path)
    else:
        derived_processing = processing_record.to_dict()
        processing_record_path = (
            f"derived-processing/{processing_record.document_version_id}.json"
        )
        processing_record_hash = sha256_bytes(_json_content(derived_processing))
    return (
        ReleaseDocument(
            document_id=str(document.get("document_id") or ""),
            document_version_id=document_version_id,
            canonical_path=canonical_path.relative_to(processed_root).as_posix(),
            chunks_path=chunks_path.relative_to(processed_root).as_posix(),
            processing_record_path=processing_record_path,
            quality_record_path=quality_record_path,
            canonical_sha256=processing_record.canonical_sha256,
            chunks_sha256=processing_record.chunks_sha256,
            quality_record_sha256=quality_hash,
            processing_record_sha256=processing_record_hash,
            processing_run_id=processing_record.processing_run_id,
            quality_status=str(status),
            quality_score=quality_score,
        ),
        derived_quality,
        derived_processing,
    )


def _select_latest_processed_versions(
    processed_dir: Path,
) -> list[tuple[Path, dict[str, Any]]]:
    latest_by_document: dict[
        str, tuple[tuple[int, str, int, str], Path, dict[str, Any]]
    ] = {}
    for chunks_path in sorted(processed_dir.rglob("chunks.jsonl")):
        canonical_path = chunks_path.with_name("canonical-document.json")
        canonical = (
            json.loads(canonical_path.read_text(encoding="utf-8"))
            if canonical_path.exists()
            else {}
        )
        document_key = _processed_document_key(chunks_path, canonical)
        version_key = _processed_version_sort_key(chunks_path, canonical)
        current = latest_by_document.get(document_key)
        if current is None or version_key > current[0]:
            latest_by_document[document_key] = (version_key, chunks_path, canonical)
    return sorted(
        (
            (chunks_path, canonical)
            for _, chunks_path, canonical in latest_by_document.values()
        ),
        key=lambda item: str(item[0]),
    )


def _processed_document_key(
    chunks_path: Path,
    canonical: dict[str, Any],
) -> str:
    file_path = normalize_space(
        str((canonical.get("document_version") or {}).get("file_path") or "")
    )
    if file_path:
        return file_path.lower()
    document_id = normalize_space(
        str((canonical.get("document") or {}).get("document_id") or "")
    )
    if document_id:
        return document_id
    return str(chunks_path.parent.parent)


def _processed_version_sort_key(
    chunks_path: Path,
    canonical: dict[str, Any],
) -> tuple[int, str, int, str]:
    version = canonical.get("document_version") or {}
    created_at = normalize_space(str(version.get("created_at") or ""))
    document_version_id = normalize_space(
        str(version.get("document_version_id") or chunks_path.parent.name)
    )
    try:
        modified_ns = chunks_path.stat().st_mtime_ns
    except OSError:
        modified_ns = 0
    return (
        1 if created_at else 0,
        created_at,
        modified_ns,
        document_version_id,
    )


def _resolve_relative(
    root: Path,
    relative_path: str,
    error_code: str,
    document_version_id: str,
) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{error_code}:{document_version_id}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{error_code}:{document_version_id}") from error
    return resolved


def _release_relative_artifact(
    release_root: Path,
    path: Path,
    name: str,
) -> tuple[Path, str]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(release_root.resolve())
    except ValueError as error:
        raise ValueError(f"release_artifact_path_escape:{name}") from error
    return resolved, relative.as_posix()


def _validate_bound_release(manifest: ReleaseManifest) -> None:
    errors = validate_release_artifacts(manifest.manifest_path)
    if errors:
        raise ValueError(";".join(errors))

    try:
        fts_path = manifest.resolve_artifact("fts")
        vector_path = manifest.resolve_artifact("vector")
        baseline_binding = manifest.baseline or {}
        baseline_path, _ = _release_relative_artifact(
            manifest.manifest_path.parent.resolve(),
            manifest.manifest_path.parent / baseline_binding["path"],
            "baseline",
        )
    except KeyError as error:
        raise ValueError("release_artifact_binding_missing") from error

    bindings = (
        ("fts", fts_path, manifest.indexes["fts"]),
        ("vector", vector_path, manifest.indexes["vector"]),
        ("baseline", baseline_path, baseline_binding),
    )
    for name, path, binding in bindings:
        if not path.is_file():
            raise ValueError(f"{name}_artifact_missing")
        if file_sha256(path) != binding.get("sha256"):
            raise ValueError(f"{name}_hash_mismatch")

    vector_binding = manifest.indexes["vector"]
    if vector_path.suffix.lower() == ".npz":
        try:
            metadata_path = _resolve_release_binding_path(
                manifest, vector_binding["metadata_path"], "vector_metadata"
            )
        except KeyError as error:
            raise ValueError("release_artifact_binding_missing") from error
        if not metadata_path.is_file():
            raise ValueError("vector_metadata_artifact_missing")
        if file_sha256(metadata_path) != vector_binding.get("metadata_sha256"):
            raise ValueError("vector_metadata_hash_mismatch")

    from agent_knowledge_hub.fts_index import read_fts_release_id
    from agent_knowledge_hub.vector_index import read_vector_release_id

    if read_fts_release_id(fts_path) != manifest.release_id:
        raise ValueError("fts_release_mismatch")
    if read_vector_release_id(vector_path) != manifest.release_id:
        raise ValueError("vector_release_mismatch")
    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline_payload.get("release_id") != manifest.release_id:
        raise ValueError("baseline_release_mismatch")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        write_json(temp_path, payload)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _is_derived_quality_path(path: str, document_version_id: str) -> bool:
    return Path(path).parts == (
        "derived-quality",
        f"{document_version_id}.json",
    )


def _is_derived_processing_path(path: str, document_version_id: str) -> bool:
    return Path(path).parts == (
        "derived-processing",
        f"{document_version_id}.json",
    )


def _validate_processing_payload(
    payload: dict[str, Any],
    document: ReleaseDocument,
    canonical_payload: dict[str, Any],
) -> str | None:
    document_version_id = document.document_version_id
    canonical_version = canonical_payload.get("document_version") or {}
    canonical_report = canonical_payload.get("parse_report") or {}
    checks = (
        ("schema", payload.get("schema_version"), PROCESSING_RECORD_SCHEMA_VERSION),
        (
            "source_file_hash",
            payload.get("source_file_hash"),
            str(canonical_version.get("file_hash") or ""),
        ),
        (
            "parser_name",
            payload.get("parser_name"),
            str(canonical_report.get("parser_name") or ""),
        ),
        ("chunker_version", payload.get("chunker_version"), CHUNKER_VERSION),
        ("quality_rules", payload.get("quality_rules_version"), QUALITY_RULES_VERSION),
        ("document_version", payload.get("document_version_id"), document_version_id),
        ("run_id", payload.get("processing_run_id"), document.processing_run_id),
        ("canonical", payload.get("canonical_sha256"), document.canonical_sha256),
        ("chunks", payload.get("chunks_sha256"), document.chunks_sha256),
    )
    for name, actual, expected in checks:
        if str(actual or "") != expected:
            return f"processing_record_{name}_mismatch:{document_version_id}"
    expected_run_id = processing_run_id(
        document_version_id=str(payload.get("document_version_id") or ""),
        source_file_hash=str(payload.get("source_file_hash") or ""),
        parser_name=str(payload.get("parser_name") or ""),
        chunker_version=str(payload.get("chunker_version") or ""),
        quality_rules_version=str(payload.get("quality_rules_version") or ""),
        canonical_sha256=str(payload.get("canonical_sha256") or ""),
        chunks_sha256=str(payload.get("chunks_sha256") or ""),
    )
    if expected_run_id != document.processing_run_id:
        return f"processing_record_run_id_mismatch:{document_version_id}"
    return None


def _resolve_release_binding_path(
    manifest: ReleaseManifest,
    relative_path: str,
    name: str,
) -> Path:
    resolved, _ = _release_relative_artifact(
        manifest.manifest_path.parent.resolve(),
        manifest.manifest_path.parent / relative_path,
        name,
    )
    return resolved


def _finalize_ready_idempotently(
    manifest: ReleaseManifest,
    *,
    fts_index_path: Path,
    vector_index_path: Path,
    baseline_path: Path,
) -> ReleaseManifest:
    try:
        expected_paths = (
            manifest.resolve_artifact("fts"),
            manifest.resolve_artifact("vector"),
            _resolve_release_binding_path(
                manifest, (manifest.baseline or {})["path"], "baseline"
            ),
        )
        requested_paths = tuple(
            Path(path).resolve()
            for path in (fts_index_path, vector_index_path, baseline_path)
        )
        if requested_paths != expected_paths:
            raise ValueError("release_already_ready")
        _validate_bound_release(manifest)
    except ValueError as error:
        if str(error) == "release_already_ready":
            raise
        raise ValueError("release_already_ready") from error
    return manifest


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _canonical_document_version_id(payload: dict[str, Any]) -> str:
    return str(
        (payload.get("document_version") or {}).get("document_version_id") or ""
    )


def _json_content(payload: dict[str, Any]) -> bytes:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return text.replace("\n", os.linesep).encode("utf-8")


def _compute_release_id(
    documents: tuple[ReleaseDocument, ...],
    quality_rules_version: str,
) -> str:
    return stable_id(
        "release",
        RELEASE_MANIFEST_SCHEMA_VERSION,
        quality_rules_version,
        *[
            f"{item.document_version_id}:{item.canonical_sha256}:"
            f"{item.chunks_sha256}:{item.quality_record_sha256}:"
            f"{item.processing_run_id}:{item.processing_record_sha256}"
            for item in documents
        ],
    )
