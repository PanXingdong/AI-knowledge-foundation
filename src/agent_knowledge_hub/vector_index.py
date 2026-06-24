from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from agent_knowledge_hub.utils import normalize_space, write_json


class VectorIndexError(Exception):
    """Raised when a vector index cannot be queried due to an incompatible format."""


# Module-level cache: str(index_path) →
#   (idf, [(chunk_id, idf_vector, doc_version_id, doc_title, src_type, project, supplier, doc_version), ...])
# Eliminates repeated JSON disk reads, IDF computation, and per-chunk vector weighting.
_VECTOR_INDEX_CACHE: dict[str, tuple] = {}
_BGE_VECTOR_INDEX_CACHE: dict[str, tuple] = {}
_BGE_MODEL_CACHE: dict[str, Any] = {}


def clear_vector_index_cache() -> None:
    """Invalidate the vector index cache (call after re-building the index)."""
    _VECTOR_INDEX_CACHE.clear()
    _BGE_VECTOR_INDEX_CACHE.clear()


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

    def to_dict(self) -> dict[str, object]:
        return {
            "processed_dir": str(self.processed_dir),
            "index_path": str(self.index_path),
            "indexed_chunk_count": self.indexed_chunk_count,
            "indexed_document_count": self.indexed_document_count,
            "embedding_strategy": self.embedding_strategy,
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
) -> VectorIndexBuildSummary:
    processed_root = Path(processed_dir).resolve()
    resolved_index_path = Path(index_path).resolve()
    if not processed_root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {processed_root}")

    rows: list[dict[str, object]] = []
    document_version_ids: set[str] = set()
    document_frequency: Counter[str] = Counter()

    for chunks_path, document_payload in _iter_latest_processed_versions(processed_root):
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
) -> VectorIndexBuildSummary:
    processed_root = Path(processed_dir).resolve()
    resolved_index_path = Path(index_path).resolve()
    resolved_model_path = Path(model_path).resolve()
    if not processed_root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {processed_root}")
    if not resolved_model_path.exists():
        raise FileNotFoundError(f"BGE-M3 model path does not exist: {resolved_model_path}")
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    if max_length <= 0:
        raise ValueError("max_length must be > 0")

    rows, texts, document_version_ids = _collect_dense_index_rows(processed_root)
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
        "model_path": str(resolved_model_path),
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
) -> VectorIndexBuildSummary:
    processed_root = Path(processed_dir).resolve()
    resolved_index_path = Path(index_path).resolve()
    resolved_model_path = Path(model_path).resolve()
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

    rows, texts, document_version_ids = _collect_dense_index_rows(processed_root)
    if not rows:
        raise ValueError(f"No chunks found under processed directory: {processed_root}")

    import numpy as np

    resolved_work_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "bge-m3-vector-parts.v1",
        "processed_dir": str(processed_root),
        "index_path": str(resolved_index_path),
        "model_path": str(resolved_model_path),
        "batch_size": batch_size,
        "max_length": max_length,
        "chunk_count": len(rows),
    }
    write_json(resolved_work_dir / "manifest.json", manifest)

    model = _load_bge_m3_model(resolved_model_path)
    total = len(texts)
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

    parts = []
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        part_path = resolved_work_dir / f"part_{start:08d}_{end:08d}.npy"
        if not part_path.exists():
            raise FileNotFoundError(f"Missing BGE-M3 vector part: {part_path}")
        parts.append(np.load(part_path).astype("float32", copy=False))
    vectors = np.vstack(parts).astype("float32", copy=False)

    resolved_index_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(resolved_index_path, vectors=vectors)

    metadata_path = _bge_metadata_path(resolved_index_path)
    metadata = {
        "schema_version": "vector-index.v2",
        "embedding_strategy": BGE_M3_EMBEDDING_STRATEGY,
        "processed_dir": str(processed_root),
        "model_path": str(resolved_model_path),
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
    )
    write_json(resolved_index_path.with_suffix(".summary.json"), summary.to_dict())
    clear_vector_index_cache()
    return summary


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
    metadata_path = _bge_metadata_path(index_path)
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
    model = _load_bge_m3_model(model_path)
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


def _collect_dense_index_rows(processed_root: Path) -> tuple[list[dict[str, str]], list[str], set[str]]:
    rows: list[dict[str, str]] = []
    texts: list[str] = []
    document_version_ids: set[str] = set()

    for chunks_path, document_payload in _iter_latest_processed_versions(processed_root):
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


def _load_bge_m3_model(model_path: Path):
    cache_key = str(model_path.resolve())
    if cache_key not in _BGE_MODEL_CACHE:
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise VectorIndexError(
                "FlagEmbedding is required for BGE-M3 vector indexes. "
                "Install project dependencies first."
            ) from exc
        _BGE_MODEL_CACHE[cache_key] = BGEM3FlagModel(str(model_path), use_fp16=False, device="cpu")
    return _BGE_MODEL_CACHE[cache_key]


def _bge_metadata_path(index_path: Path) -> Path:
    return index_path.with_suffix(index_path.suffix + ".metadata.json")


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
