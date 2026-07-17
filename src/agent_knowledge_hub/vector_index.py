from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from agent_knowledge_hub.release_manifest import (
    iter_release_documents,
    load_release_manifest,
)
from agent_knowledge_hub.utils import normalize_space, write_json


class VectorIndexError(Exception):
    """Raised when a vector index cannot be queried due to an incompatible format."""


# Module-level cache: str(index_path) →
#   (idf, [(chunk_id, idf_vector, doc_version_id, doc_title, src_type, project, supplier, doc_version), ...])
# Eliminates repeated JSON disk reads, IDF computation, and per-chunk vector weighting.
_VECTOR_INDEX_CACHE: dict[str, tuple] = {}
_BGE_VECTOR_INDEX_CACHE: dict[str, tuple] = {}
_BGE_MODEL_CACHE: dict[tuple[str, str | None], Any] = {}


def clear_vector_index_cache() -> None:
    """Invalidate the vector index cache (call after re-building the index)."""
    _VECTOR_INDEX_CACHE.clear()
    _BGE_VECTOR_INDEX_CACHE.clear()
    _BGE_MODEL_CACHE.clear()


def model_content_fingerprint(model_path: Path | str) -> str:
    """Hash a model file or a directory's sorted regular-file contents."""
    root = Path(model_path)
    if root.is_symlink():
        raise VectorIndexError("model_path_symlink_unsupported")
    if root.is_file():
        return _file_content_sha256(root)
    if not root.is_dir():
        raise FileNotFoundError(f"BGE-M3 model path does not exist: {root}")

    digest = hashlib.sha256(b"bge-model-directory-v1\0")
    entries = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    for path in entries:
        if path.is_symlink():
            raise VectorIndexError("model_path_symlink_unsupported")
        if not path.is_file():
            continue
        relative_bytes = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative_bytes).to_bytes(8, "big"))
        digest.update(relative_bytes)
        digest.update(bytes.fromhex(_file_content_sha256(path)))
    return digest.hexdigest()


def _file_content_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


EMBEDDING_STRATEGY = "local-hashed-token-v1"
BGE_M3_EMBEDDING_STRATEGY = "bge-m3-dense-v1"
BGE_M3_DEFAULT_MODEL_PATH = "models/bge-m3"
ASCII_TOKEN_RE = re.compile(r"[a-z0-9_./=-]+")
CJK_SEQUENCE_RE = re.compile(r"[\u4e00-\u9fff]+")
CJK_SYNONYM_GROUPS = (
    ("出境", "跨境", "境外", "海外"),
    ("审批", "评估", "审核", "批准"),
    ("限制", "约束", "要求", "规则"),
    ("风险", "隐患", "问题"),
)
CONCEPT_FEATURE_WEIGHT = 1.4
# Bilingual concept bridges: when either a Chinese term or an English term in a
# group is present, the same shared `concept:<id>` feature is emitted. This lets
# a Chinese query and an English document share vector dimensions so cross-lingual
# matches produce a non-zero cosine similarity.
BILINGUAL_CONCEPT_GROUPS = (
    ("partition", ("分区", "隔离", "划分"), ("partition", "partitioning", "isolation", "isolate")),
    ("scheduler", ("调度", "调度器", "调度程序"), ("schedule", "scheduler", "scheduling")),
    ("priority", ("优先级", "优先权"), ("priority", "priorities")),
    ("process", ("进程",), ("process", "processes")),
    ("thread", ("线程",), ("thread", "threads", "threading")),
    ("security", ("安全", "安全性"), ("security", "secure", "securing")),
    ("permission", ("权限", "许可"), ("permission", "permissions", "privilege", "privileges")),
    ("critical", ("关键", "关键任务", "临界"), ("critical", "criticality")),
    ("realtime", ("实时", "实时性"), ("realtime", "real-time")),
    ("kernel", ("内核", "微内核"), ("kernel", "microkernel")),
    ("resource", ("资源",), ("resource", "resources")),
    ("processor", ("处理器", "中央处理器"), ("processor", "cpu")),
    ("budget", ("份额", "预算", "配额", "百分比"), ("budget", "share", "percentage", "quota")),
    ("interrupt", ("中断",), ("interrupt", "interrupts")),
    ("memory", ("内存", "存储"), ("memory",)),
    ("architecture", ("架构", "体系结构"), ("architecture", "architectural")),
    ("task", ("任务",), ("task", "tasks")),
    ("ipc", ("进程间通信", "消息传递", "消息"), ("ipc", "message", "messaging", "messages")),
    ("fault", ("故障", "失效", "容错"), ("fault", "faults", "failure", "availability")),
    ("driver", ("驱动", "驱动程序"), ("driver", "drivers")),
    ("network", ("网络", "联网"), ("network", "networking")),
    ("filesystem", ("文件", "文件系统"), ("file", "files", "filesystem")),
    ("boot", ("启动", "引导"), ("boot", "booting", "bootup", "bootstrap")),
    ("configuration", ("配置",), ("config", "configuration", "configure")),
    ("policy", ("策略", "政策"), ("policy", "policies")),
    ("encryption", ("加密",), ("encrypt", "encryption", "crypto")),
    ("authentication", ("认证", "鉴权", "身份验证"), ("authentication", "authenticate")),
    ("scheduling_preempt", ("抢占", "抢占式"), ("preempt", "preemptive", "preemption")),
)


@dataclass(frozen=True)
class VectorIndexBuildSummary:
    processed_dir: Path
    index_path: Path
    indexed_chunk_count: int
    indexed_document_count: int
    embedding_strategy: str
    release_id: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "processed_dir": str(self.processed_dir),
            "index_path": str(self.index_path),
            "indexed_chunk_count": self.indexed_chunk_count,
            "indexed_document_count": self.indexed_document_count,
            "embedding_strategy": self.embedding_strategy,
            "release_id": self.release_id,
        }


@dataclass(frozen=True)
class VectorSearchHit:
    chunk_id: str
    document_version_id: str
    document_title: str
    source_type: str
    project: str
    supplier: str
    document_version: str
    similarity_score: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_vector_index(
    *,
    processed_dir: Path | str,
    index_path: Path | str,
    release_manifest_path: Path | str | None = None,
) -> VectorIndexBuildSummary:
    processed_root = Path(processed_dir).resolve()
    resolved_index_path = Path(index_path).resolve()
    if not processed_root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {processed_root}")

    processed_versions, release_id = _resolve_processed_versions(
        processed_root,
        release_manifest_path,
    )
    rows: list[dict[str, object]] = []
    document_version_ids: set[str] = set()
    document_frequency: Counter[str] = Counter()

    for chunks_path, document_payload in processed_versions:
        document_info = document_payload.get("document") or {}
        version_info = document_payload.get("document_version") or {}
        document_title = normalize_space(str(document_info.get("title") or "unknown"))
        source_type = normalize_space(str(document_info.get("source_type") or "unknown"))
        project = normalize_space(str(document_info.get("project") or "unknown"))
        supplier = normalize_space(str(document_info.get("supplier") or "unknown"))
        document_version = normalize_space(str(version_info.get("version") or "unknown"))
        document_version_id = str(version_info.get("document_version_id") or "")
        if document_version_id:
            document_version_ids.add(document_version_id)

        section_titles_by_path = _build_section_title_map(document_payload)
        for line in chunks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            section_path = [str(part) for part in (payload.get("section_path") or [])]
            section_titles = _derive_section_titles(
                section_path=section_path,
                section_titles_by_path=section_titles_by_path,
            )
            chunk_text = str(payload.get("text") or "")
            vector = _build_sparse_vector(
                "\n".join((document_title, " > ".join(section_titles), chunk_text))
            )
            if not vector:
                continue
            for feature in vector:
                document_frequency[feature] += 1
            rows.append(
                {
                    "chunk_id": str(payload.get("chunk_id") or ""),
                    "document_version_id": str(payload.get("document_version_id") or ""),
                    "document_title": document_title,
                    "source_type": source_type,
                    "project": project,
                    "supplier": supplier,
                    "document_version": document_version,
                    "vector": dict(vector),
                }
            )

    payload = {
        "schema_version": "vector-index.v1",
        "embedding_strategy": EMBEDDING_STRATEGY,
        "processed_dir": str(processed_root),
        "release_id": release_id,
        "document_count": len(document_version_ids),
        "chunk_count": len(rows),
        "document_frequency": dict(sorted(document_frequency.items())),
        "chunks": rows,
    }
    write_json(resolved_index_path, payload)

    summary = VectorIndexBuildSummary(
        processed_dir=processed_root,
        index_path=resolved_index_path,
        indexed_chunk_count=len(rows),
        indexed_document_count=len(document_version_ids),
        embedding_strategy=EMBEDDING_STRATEGY,
        release_id=release_id,
    )
    write_json(resolved_index_path.with_suffix(".summary.json"), summary.to_dict())
    return summary


def build_bge_m3_vector_index(
    *,
    processed_dir: Path | str,
    index_path: Path | str,
    model_path: Path | str = BGE_M3_DEFAULT_MODEL_PATH,
    batch_size: int = 8,
    max_length: int = 1024,
    progress_callback: Callable[[int, int], None] | None = None,
    release_manifest_path: Path | str | None = None,
) -> VectorIndexBuildSummary:
    processed_root = Path(processed_dir).resolve()
    resolved_index_path = Path(index_path).resolve()
    raw_model_path = Path(model_path)
    if raw_model_path.is_symlink():
        raise VectorIndexError("model_path_symlink_unsupported")
    resolved_model_path = raw_model_path.resolve()
    if not processed_root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {processed_root}")
    if not resolved_model_path.exists():
        raise FileNotFoundError(f"BGE-M3 model path does not exist: {resolved_model_path}")
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    if max_length <= 0:
        raise ValueError("max_length must be > 0")
    model_fingerprint = model_content_fingerprint(resolved_model_path)

    processed_versions, release_id = _resolve_processed_versions(
        processed_root,
        release_manifest_path,
    )
    rows, texts, document_version_ids = _collect_dense_index_rows(processed_versions)
    if not rows:
        raise ValueError(f"No chunks found under processed directory: {processed_root}")

    model = _load_bge_m3_model(resolved_model_path)
    dense_vectors = []
    total = len(texts)
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        encoded = model.encode(
            batch,
            batch_size=len(batch),
            max_length=max_length,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        dense_vectors.append(encoded["dense_vecs"])
        if progress_callback is not None:
            progress_callback(min(start + len(batch), total), total)

    import numpy as np

    vectors = np.vstack(dense_vectors).astype("float32", copy=False)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / np.maximum(norms, 1e-12)

    resolved_index_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(resolved_index_path, vectors=vectors)

    metadata_path = _bge_metadata_path(resolved_index_path)
    metadata = {
        "schema_version": "vector-index.v2",
        "embedding_strategy": BGE_M3_EMBEDDING_STRATEGY,
        "processed_dir": str(processed_root),
        "release_id": release_id,
        "model_path": str(resolved_model_path),
        "model_fingerprint": model_fingerprint,
        "model_name": "BAAI/bge-m3",
        "dimension": int(vectors.shape[1]),
        "max_length": max_length,
        "document_count": len(document_version_ids),
        "chunk_count": len(rows),
        "chunks": rows,
    }
    write_json(metadata_path, metadata)

    summary = VectorIndexBuildSummary(
        processed_dir=processed_root,
        index_path=resolved_index_path,
        indexed_chunk_count=len(rows),
        indexed_document_count=len(document_version_ids),
        embedding_strategy=BGE_M3_EMBEDDING_STRATEGY,
        release_id=release_id,
    )
    write_json(resolved_index_path.with_suffix(".summary.json"), summary.to_dict())
    clear_vector_index_cache()
    return summary


def build_bge_m3_vector_index_resumable(
    *,
    processed_dir: Path | str,
    index_path: Path | str,
    model_path: Path | str = BGE_M3_DEFAULT_MODEL_PATH,
    batch_size: int = 16,
    max_length: int = 512,
    work_dir: Path | str | None = None,
    progress_callback: Callable[[int, int, bool], None] | None = None,
    release_manifest_path: Path | str | None = None,
) -> VectorIndexBuildSummary:
    processed_root = Path(processed_dir).resolve()
    resolved_index_path = Path(index_path).resolve()
    raw_model_path = Path(model_path)
    if raw_model_path.is_symlink():
        raise VectorIndexError("model_path_symlink_unsupported")
    resolved_model_path = raw_model_path.resolve()
    resolved_work_dir = (
        Path(work_dir).resolve()
        if work_dir is not None
        else resolved_index_path.with_suffix(resolved_index_path.suffix + ".parts")
    )
    if not processed_root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {processed_root}")
    if not resolved_model_path.exists():
        raise FileNotFoundError(f"BGE-M3 model path does not exist: {resolved_model_path}")
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    if max_length <= 0:
        raise ValueError("max_length must be > 0")
    model_fingerprint = model_content_fingerprint(resolved_model_path)

    processed_versions, release_id = _resolve_processed_versions(
        processed_root,
        release_manifest_path,
    )
    rows, texts, document_version_ids = _collect_dense_index_rows(processed_versions)
    if not rows:
        raise ValueError(f"No chunks found under processed directory: {processed_root}")
    input_fingerprint = _dense_input_fingerprint(rows, texts)

    import numpy as np

    resolved_work_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = resolved_work_dir / "manifest.json"
    manifest = {
        "schema_version": "bge-m3-vector-parts.v1",
        "embedding_strategy": BGE_M3_EMBEDDING_STRATEGY,
        "processed_dir": str(processed_root),
        "index_path": str(resolved_index_path),
        "model_path": str(resolved_model_path),
        "model_fingerprint": model_fingerprint,
        "batch_size": batch_size,
        "max_length": max_length,
        "chunk_count": len(rows),
        "release_id": release_id,
        "input_fingerprint": input_fingerprint,
    }
    expected_part_dimension: int | None = None
    if manifest_path.exists():
        try:
            existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, json.JSONDecodeError) as error:
            raise VectorIndexError("resumable_work_dir_input_mismatch") from error
        identity_fields = (
            "embedding_strategy",
            "model_path",
            "model_fingerprint",
            "max_length",
            "batch_size",
            "release_id",
            "input_fingerprint",
        )
        if any(
            existing_manifest.get(field) != manifest.get(field)
            for field in identity_fields
        ):
            raise VectorIndexError("resumable_work_dir_input_mismatch")
        raw_dimension = existing_manifest.get("dimension")
        expected_part_dimension = int(raw_dimension) if raw_dimension is not None else None
    else:
        write_json(manifest_path, manifest)

    total = len(texts)
    _validate_resumable_parts(
        work_dir=resolved_work_dir,
        total=total,
        batch_size=batch_size,
        require_all=False,
        expected_dimension=expected_part_dimension,
    )
    model = _load_bge_m3_model(resolved_model_path)
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        part_path = resolved_work_dir / f"part_{start:08d}_{end:08d}.npy"
        skipped = part_path.exists()
        if not skipped:
            encoded = model.encode(
                texts[start:end],
                batch_size=end - start,
                max_length=max_length,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            batch_vectors = np.asarray(encoded["dense_vecs"], dtype="float32")
            norms = np.linalg.norm(batch_vectors, axis=1, keepdims=True)
            batch_vectors = batch_vectors / np.maximum(norms, 1e-12)
            temp_path = part_path.with_suffix(".tmp.npy")
            np.save(temp_path, batch_vectors)
            temp_path.replace(part_path)
        if progress_callback is not None:
            progress_callback(end, total, skipped)

    parts = _validate_resumable_parts(
        work_dir=resolved_work_dir,
        total=total,
        batch_size=batch_size,
        require_all=True,
        expected_dimension=expected_part_dimension,
    )
    actual_dimension = int(parts[0].shape[1])
    if expected_part_dimension is None:
        write_json(manifest_path, {**manifest, "dimension": actual_dimension})
    vectors = np.vstack(parts).astype("float32", copy=False)

    resolved_index_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(resolved_index_path, vectors=vectors)

    metadata_path = _bge_metadata_path(resolved_index_path)
    metadata = {
        "schema_version": "vector-index.v2",
        "embedding_strategy": BGE_M3_EMBEDDING_STRATEGY,
        "processed_dir": str(processed_root),
        "release_id": release_id,
        "model_path": str(resolved_model_path),
        "model_fingerprint": model_fingerprint,
        "model_name": "BAAI/bge-m3",
        "dimension": int(vectors.shape[1]),
        "max_length": max_length,
        "document_count": len(document_version_ids),
        "chunk_count": len(rows),
        "chunks": rows,
    }
    write_json(metadata_path, metadata)

    summary = VectorIndexBuildSummary(
        processed_dir=processed_root,
        index_path=resolved_index_path,
        indexed_chunk_count=len(rows),
        indexed_document_count=len(document_version_ids),
        embedding_strategy=BGE_M3_EMBEDDING_STRATEGY,
        release_id=release_id,
    )
    write_json(resolved_index_path.with_suffix(".summary.json"), summary.to_dict())
    clear_vector_index_cache()
    return summary


def _validate_resumable_parts(
    *,
    work_dir: Path,
    total: int,
    batch_size: int,
    require_all: bool,
    expected_dimension: int | None = None,
) -> list[Any]:
    import numpy as np

    parts = []
    resolved_dimension = expected_dimension
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        part_path = work_dir / f"part_{start:08d}_{end:08d}.npy"
        if not part_path.exists():
            if require_all:
                raise VectorIndexError("resumable_part_invalid")
            continue
        try:
            part = np.load(part_path).astype("float32", copy=False)
        except (OSError, TypeError, ValueError) as error:
            raise VectorIndexError("resumable_part_invalid") from error
        if (
            part.ndim != 2
            or int(part.shape[0]) != end - start
            or int(part.shape[1]) <= 0
        ):
            raise VectorIndexError("resumable_part_invalid")
        if resolved_dimension is None:
            resolved_dimension = int(part.shape[1])
        elif int(part.shape[1]) != resolved_dimension:
            raise VectorIndexError("resumable_part_invalid")
        parts.append(part)
    return parts


def read_vector_release_id(index_path: Path | str) -> str | None:
    resolved = Path(index_path).resolve()
    payload_path = (
        _existing_bge_metadata_path(resolved)
        if resolved.suffix == ".npz"
        else resolved
    )
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    value = payload.get("release_id")
    return str(value) if value else None


def bge_metadata_path(index_path: Path | str) -> Path:
    """Return the canonical metadata sidecar path for a BGE matrix."""
    return _bge_metadata_path(Path(index_path).resolve())


def query_vector_index(
    *,
    index_path: Path | str,
    query: str,
    limit: int = 20,
) -> list[VectorSearchHit]:
    resolved_index_path = Path(index_path).resolve()
    if not resolved_index_path.exists():
        raise FileNotFoundError(f"Vector index does not exist: {resolved_index_path}")
    if limit <= 0:
        raise ValueError("limit must be > 0")
    if resolved_index_path.suffix.lower() == ".npz":
        return _query_bge_m3_vector_index(
            index_path=resolved_index_path,
            query=query,
            limit=limit,
        )

    cache_key = str(resolved_index_path)
    if cache_key not in _VECTOR_INDEX_CACHE:
        # Cold path: parse JSON, build IDF, pre-weight all chunk vectors.
        index_payload = json.loads(resolved_index_path.read_text(encoding="utf-8"))
        if index_payload.get("embedding_strategy") != EMBEDDING_STRATEGY:
            raise VectorIndexError(
                "Unsupported vector index embedding strategy: "
                f"{index_payload.get('embedding_strategy')}"
            )
        chunk_rows = list(index_payload.get("chunks") or [])
        idf = _build_idf(
            document_frequency={
                str(key): int(value)
                for key, value in (index_payload.get("document_frequency") or {}).items()
            },
            document_count=len(chunk_rows),
        )
        # Pre-apply IDF weighting to every chunk vector (query-independent).
        chunk_idf_vectors: list[tuple] = []
        for row in chunk_rows:
            raw_vector = {
                str(key): float(value)
                for key, value in (row.get("vector") or {}).items()
            }
            idf_vector = _apply_idf(raw_vector, idf)
            chunk_idf_vectors.append((
                str(row.get("chunk_id") or ""),
                idf_vector,
                str(row.get("document_version_id") or ""),
                normalize_space(str(row.get("document_title") or "")),
                normalize_space(str(row.get("source_type") or "")),
                normalize_space(str(row.get("project") or "")),
                normalize_space(str(row.get("supplier") or "")),
                normalize_space(str(row.get("document_version") or "")),
            ))
        _VECTOR_INDEX_CACHE[cache_key] = (idf, chunk_idf_vectors)

    idf, chunk_idf_vectors = _VECTOR_INDEX_CACHE[cache_key]

    if not chunk_idf_vectors:
        return []

    query_vector = _build_sparse_vector(query)
    if not query_vector:
        return []

    weighted_query = _apply_idf(query_vector, idf)
    ranked: list[tuple[float, tuple]] = []
    for entry in chunk_idf_vectors:
        chunk_id, idf_vector, doc_version_id, doc_title, src_type, project, supplier, doc_version = entry
        similarity = _cosine_similarity(weighted_query, idf_vector)
        if similarity <= 0.0:
            continue
        ranked.append((similarity, entry))

    ranked.sort(key=lambda item: (-item[0], item[1][3], item[1][0]))
    return [
        VectorSearchHit(
            chunk_id=entry[0],
            document_version_id=entry[2],
            document_title=entry[3],
            source_type=entry[4],
            project=entry[5],
            supplier=entry[6],
            document_version=entry[7],
            similarity_score=round(similarity, 8),
        )
        for similarity, entry in ranked[:limit]
    ]


def _query_bge_m3_vector_index(
    *,
    index_path: Path,
    query: str,
    limit: int,
) -> list[VectorSearchHit]:
    metadata_path = _existing_bge_metadata_path(index_path)
    if not metadata_path.exists():
        raise FileNotFoundError(f"BGE-M3 vector metadata does not exist: {metadata_path}")

    cache_key = str(index_path)
    if cache_key not in _BGE_VECTOR_INDEX_CACHE:
        import numpy as np

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("embedding_strategy") != BGE_M3_EMBEDDING_STRATEGY:
            raise VectorIndexError(
                "Unsupported vector index embedding strategy: "
                f"{metadata.get('embedding_strategy')}"
            )
        vectors = np.load(index_path)["vectors"].astype("float32", copy=False)
        rows = list(metadata.get("chunks") or [])
        if len(rows) != int(vectors.shape[0]):
            raise VectorIndexError(
                "BGE-M3 vector index metadata and matrix row counts do not match"
            )
        _BGE_VECTOR_INDEX_CACHE[cache_key] = (vectors, rows, metadata)

    vectors, rows, metadata = _BGE_VECTOR_INDEX_CACHE[cache_key]
    model_path = Path(str(metadata.get("model_path") or BGE_M3_DEFAULT_MODEL_PATH)).resolve()
    expected_fingerprint = metadata.get("model_fingerprint")
    if expected_fingerprint is not None:
        actual_fingerprint = model_content_fingerprint(model_path)
        if actual_fingerprint != str(expected_fingerprint):
            raise VectorIndexError("bge_model_fingerprint_mismatch")
    model = _load_bge_m3_model(
        model_path,
        expected_fingerprint=(
            str(expected_fingerprint) if expected_fingerprint is not None else None
        ),
    )
    encoded = model.encode(
        [query],
        batch_size=1,
        max_length=int(metadata.get("max_length") or 1024),
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )

    import numpy as np

    query_vector = np.asarray(encoded["dense_vecs"][0], dtype="float32")
    query_norm = float(np.linalg.norm(query_vector))
    if query_norm == 0.0:
        return []
    query_vector = query_vector / query_norm
    scores = vectors @ query_vector
    if scores.size == 0:
        return []

    candidate_count = min(limit, int(scores.size))
    top_indices = np.argpartition(-scores, candidate_count - 1)[:candidate_count]
    ranked_indices = sorted(top_indices.tolist(), key=lambda index: (-float(scores[index]), index))
    hits: list[VectorSearchHit] = []
    for index in ranked_indices:
        row = rows[index]
        similarity = float(scores[index])
        hits.append(
            VectorSearchHit(
                chunk_id=str(row.get("chunk_id") or ""),
                document_version_id=str(row.get("document_version_id") or ""),
                document_title=normalize_space(str(row.get("document_title") or "")),
                source_type=normalize_space(str(row.get("source_type") or "")),
                project=normalize_space(str(row.get("project") or "")),
                supplier=normalize_space(str(row.get("supplier") or "")),
                document_version=normalize_space(str(row.get("document_version") or "")),
                similarity_score=round(similarity, 8),
            )
        )
    return hits


def _collect_dense_index_rows(
    processed_versions: list[tuple[Path, dict[str, Any]]],
) -> tuple[list[dict[str, str]], list[str], set[str]]:
    rows: list[dict[str, str]] = []
    texts: list[str] = []
    document_version_ids: set[str] = set()

    for chunks_path, document_payload in processed_versions:
        document_info = document_payload.get("document") or {}
        version_info = document_payload.get("document_version") or {}
        document_title = normalize_space(str(document_info.get("title") or "unknown"))
        source_type = normalize_space(str(document_info.get("source_type") or "unknown"))
        project = normalize_space(str(document_info.get("project") or "unknown"))
        supplier = normalize_space(str(document_info.get("supplier") or "unknown"))
        document_version = normalize_space(str(version_info.get("version") or "unknown"))
        document_version_id = str(version_info.get("document_version_id") or "")
        if document_version_id:
            document_version_ids.add(document_version_id)

        section_titles_by_path = _build_section_title_map(document_payload)
        for line in chunks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            section_path = [str(part) for part in (payload.get("section_path") or [])]
            section_titles = _derive_section_titles(
                section_path=section_path,
                section_titles_by_path=section_titles_by_path,
            )
            chunk_text = str(payload.get("text") or "")
            rows.append(
                {
                    "chunk_id": str(payload.get("chunk_id") or ""),
                    "document_version_id": str(payload.get("document_version_id") or ""),
                    "document_title": document_title,
                    "source_type": source_type,
                    "project": project,
                    "supplier": supplier,
                    "document_version": document_version,
                }
            )
            texts.append("\n".join((document_title, " > ".join(section_titles), chunk_text)))

    return rows, texts, document_version_ids


def _dense_input_fingerprint(
    rows: list[dict[str, str]],
    texts: list[str],
) -> str:
    inputs = [
        {
            "chunk_id": row["chunk_id"],
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        for row, text in zip(rows, texts, strict=True)
    ]
    content = json.dumps(
        inputs,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _resolve_processed_versions(
    processed_root: Path,
    release_manifest_path: Path | str | None,
) -> tuple[list[tuple[Path, dict[str, Any]]], str | None]:
    if release_manifest_path is None:
        return _iter_latest_processed_versions(processed_root), None

    manifest = load_release_manifest(Path(release_manifest_path))
    if Path(manifest.processed_dir).resolve() != processed_root:
        raise ValueError("release_processed_dir_mismatch")
    return iter_release_documents(manifest.manifest_path), manifest.release_id


def _load_bge_m3_model(
    model_path: Path,
    *,
    expected_fingerprint: str | None = None,
):
    resolved_path = model_path.resolve()
    if expected_fingerprint is not None:
        actual_fingerprint = model_content_fingerprint(resolved_path)
        if actual_fingerprint != expected_fingerprint:
            raise VectorIndexError("bge_model_fingerprint_mismatch")
    cache_key = (str(resolved_path), expected_fingerprint)
    if cache_key not in _BGE_MODEL_CACHE:
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise VectorIndexError(
                "FlagEmbedding is required for BGE-M3 vector indexes. "
                "Install project dependencies first."
            ) from exc
        device = _select_bge_m3_device()
        _BGE_MODEL_CACHE[cache_key] = BGEM3FlagModel(
            str(resolved_path),
            use_fp16=device.startswith("cuda"),
            device=device,
        )
    return _BGE_MODEL_CACHE[cache_key]


def _select_bge_m3_device() -> str:
    requested_device = os.environ.get("AKF_BGE_M3_DEVICE", "").strip()
    if requested_device:
        return requested_device
    try:
        import torch
    except ImportError:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _bge_metadata_path(index_path: Path) -> Path:
    return Path(str(index_path) + ".metadata.json")


def _existing_bge_metadata_path(index_path: Path) -> Path:
    metadata_path = _bge_metadata_path(index_path)
    transitional_path = index_path.with_suffix(".metadata.json")
    if not metadata_path.exists() and transitional_path.exists():
        return transitional_path
    return metadata_path


def _build_sparse_vector(text: str) -> Counter[str]:
    normalized = normalize_space(text).lower()
    vector: Counter[str] = Counter()

    for token in ASCII_TOKEN_RE.findall(normalized):
        if len(token) < 2:
            continue
        vector[f"ascii:{token}"] += _feature_weight(token)
        if "_" in token:
            for part in token.split("_"):
                if len(part) >= 2:
                    vector[f"ascii:{part}"] += 0.7

    for sequence in CJK_SEQUENCE_RE.findall(normalized):
        if len(sequence) < 2:
            continue
        max_ngram = min(4, len(sequence))
        for size in range(2, max_ngram + 1):
            for index in range(0, len(sequence) - size + 1):
                token = sequence[index : index + size]
                vector[f"cjk:{token}"] += _feature_weight(token)
        if len(sequence) <= 8:
            vector[f"cjk:{sequence}"] += _feature_weight(sequence) + 0.4

    for feature in _synonym_features(normalized):
        vector[feature] += 1.2

    for feature in _concept_features(normalized):
        vector[feature] += CONCEPT_FEATURE_WEIGHT

    return vector


def _feature_weight(token: str) -> float:
    if re.fullmatch(r"[a-z0-9_./=-]+", token):
        if len(token) >= 12:
            return 2.4
        if len(token) >= 6:
            return 1.8
        return 1.2
    if len(token) >= 4:
        return 1.6
    if len(token) == 3:
        return 1.25
    return 1.0


def _synonym_features(normalized_text: str) -> list[str]:
    features: list[str] = []
    for group in CJK_SYNONYM_GROUPS:
        if any(term in normalized_text for term in group):
            features.append("syn:" + "|".join(group))
    return features


def _concept_features(normalized_text: str) -> list[str]:
    features: list[str] = []
    for canonical, cjk_terms, ascii_terms in BILINGUAL_CONCEPT_GROUPS:
        if any(term in normalized_text for term in cjk_terms) or any(
            _ascii_term_present(term, normalized_text) for term in ascii_terms
        ):
            features.append(f"concept:{canonical}")
    return features


def _ascii_term_present(term: str, normalized_text: str) -> bool:
    # Word-start prefix match so "partition" matches "partitioning"/"partitions"
    # but not the tail of an unrelated word (e.g. "repartition").
    return re.search(r"(?<![a-z0-9])" + re.escape(term), normalized_text) is not None


def _build_idf(*, document_frequency: dict[str, int], document_count: int) -> dict[str, float]:
    if document_count <= 0:
        return {}
    return {
        feature: math.log(1.0 + (document_count + 1.0) / (frequency + 1.0))
        for feature, frequency in document_frequency.items()
    }


def _apply_idf(vector: dict[str, float] | Counter[str], idf: dict[str, float]) -> dict[str, float]:
    return {
        feature: float(value) * idf.get(feature, 1.0)
        for feature, value in vector.items()
        if float(value) != 0.0
    }


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0

    if len(left) > len(right):
        left, right = right, left
    dot_product = sum(value * right.get(feature, 0.0) for feature, value in left.items())
    if dot_product <= 0.0:
        return 0.0

    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot_product / (left_norm * right_norm)


def _iter_latest_processed_versions(processed_dir: Path) -> list[tuple[Path, dict]]:
    latest_by_document: dict[str, tuple[tuple[int, str, int, str], Path, dict]] = {}
    for chunks_path in sorted(processed_dir.rglob("chunks.jsonl")):
        document_json_path = chunks_path.with_name("canonical-document.json")
        document_payload = _read_json(document_json_path) if document_json_path.exists() else {}
        document_key = _processed_document_key(chunks_path, document_payload)
        version_key = _processed_version_sort_key(chunks_path, document_payload)
        current = latest_by_document.get(document_key)
        if current is None or version_key > current[0]:
            latest_by_document[document_key] = (version_key, chunks_path, document_payload)

    return sorted(
        (
            (chunks_path, document_payload)
            for _, chunks_path, document_payload in latest_by_document.values()
        ),
        key=lambda item: str(item[0]),
    )


def _processed_document_key(chunks_path: Path, document_payload: dict) -> str:
    file_path = normalize_space(
        str((document_payload.get("document_version") or {}).get("file_path") or "")
    )
    if file_path:
        return file_path.lower()

    document_id = normalize_space(
        str((document_payload.get("document") or {}).get("document_id") or "")
    )
    if document_id:
        return document_id

    return str(chunks_path.parent.parent)


def _processed_version_sort_key(chunks_path: Path, document_payload: dict) -> tuple[int, str, int, str]:
    version_payload = document_payload.get("document_version") or {}
    created_at = normalize_space(str(version_payload.get("created_at") or ""))
    document_version_id = normalize_space(
        str(version_payload.get("document_version_id") or chunks_path.parent.name)
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


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_section_title_map(document_payload: dict) -> dict[tuple[str, ...], str]:
    mapping: dict[tuple[str, ...], str] = {}
    for section in document_payload.get("sections") or []:
        path = tuple(str(part) for part in (section.get("section_path") or []))
        title = normalize_space(str(section.get("title") or ""))
        if path and title:
            mapping[path] = title
    return mapping


def _derive_section_titles(
    *,
    section_path: list[str],
    section_titles_by_path: dict[tuple[str, ...], str],
) -> list[str]:
    titles: list[str] = []
    for index in range(1, len(section_path) + 1):
        title = section_titles_by_path.get(tuple(section_path[:index]))
        if title:
            titles.append(title)
    return titles
