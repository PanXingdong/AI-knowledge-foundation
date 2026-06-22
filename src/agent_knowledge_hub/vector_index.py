from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from agent_knowledge_hub.utils import normalize_space, write_json


class VectorIndexError(Exception):
    """Raised when a vector index cannot be queried due to an incompatible format."""


EMBEDDING_STRATEGY = "local-hashed-token-v1"
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

    index_payload = json.loads(resolved_index_path.read_text(encoding="utf-8"))
    if index_payload.get("embedding_strategy") != EMBEDDING_STRATEGY:
        raise VectorIndexError(
            "Unsupported vector index embedding strategy: "
            f"{index_payload.get('embedding_strategy')}"
        )

    chunk_rows = list(index_payload.get("chunks") or [])
    if not chunk_rows:
        return []

    query_vector = _build_sparse_vector(query)
    if not query_vector:
        return []

    idf = _build_idf(
        document_frequency={
            str(key): int(value)
            for key, value in (index_payload.get("document_frequency") or {}).items()
        },
        document_count=len(chunk_rows),
    )
    weighted_query = _apply_idf(query_vector, idf)
    ranked: list[tuple[float, dict[str, object]]] = []
    for row in chunk_rows:
        vector = {
            str(key): float(value)
            for key, value in (row.get("vector") or {}).items()
        }
        similarity = _cosine_similarity(weighted_query, _apply_idf(vector, idf))
        if similarity <= 0.0:
            continue
        ranked.append((similarity, row))

    ranked.sort(
        key=lambda item: (
            -item[0],
            normalize_space(str(item[1].get("document_title") or "")),
            str(item[1].get("chunk_id") or ""),
        )
    )
    return [
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
        for similarity, row in ranked[:limit]
    ]


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
