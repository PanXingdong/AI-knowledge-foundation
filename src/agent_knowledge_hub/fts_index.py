from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from agent_knowledge_hub.utils import normalize_space, write_json


@dataclass(frozen=True)
class FtsIndexBuildSummary:
    processed_dir: Path
    index_path: Path
    indexed_chunk_count: int
    indexed_document_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "processed_dir": str(self.processed_dir),
            "index_path": str(self.index_path),
            "indexed_chunk_count": self.indexed_chunk_count,
            "indexed_document_count": self.indexed_document_count,
        }


@dataclass(frozen=True)
class FtsSearchHit:
    chunk_id: str
    document_version_id: str
    document_title: str
    source_type: str
    project: str
    supplier: str
    document_version: str
    bm25_score: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_fts_index(
    *,
    processed_dir: Path | str,
    index_path: Path | str,
) -> FtsIndexBuildSummary:
    processed_root = Path(processed_dir).resolve()
    resolved_index_path = Path(index_path).resolve()
    if not processed_root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {processed_root}")

    rows: list[dict[str, object]] = []
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
                    "section_titles": " > ".join(section_titles),
                    "chunk_text": chunk_text,
                }
            )

    resolved_index_path.parent.mkdir(parents=True, exist_ok=True)
    if resolved_index_path.exists():
        resolved_index_path.unlink()

    connection = sqlite3.connect(resolved_index_path)
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE fts_chunks USING fts5(
              chunk_id UNINDEXED,
              document_version_id UNINDEXED,
              document_title,
              source_type UNINDEXED,
              project UNINDEXED,
              supplier UNINDEXED,
              document_version UNINDEXED,
              section_titles,
              chunk_text
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO fts_chunks (
              chunk_id,
              document_version_id,
              document_title,
              source_type,
              project,
              supplier,
              document_version,
              section_titles,
              chunk_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["chunk_id"],
                    row["document_version_id"],
                    row["document_title"],
                    row["source_type"],
                    row["project"],
                    row["supplier"],
                    row["document_version"],
                    row["section_titles"],
                    row["chunk_text"],
                )
                for row in rows
            ],
        )
        connection.commit()
    finally:
        connection.close()

    summary = FtsIndexBuildSummary(
        processed_dir=processed_root,
        index_path=resolved_index_path,
        indexed_chunk_count=len(rows),
        indexed_document_count=len(document_version_ids),
    )
    write_json(resolved_index_path.with_suffix(".summary.json"), summary.to_dict())
    return summary


def query_fts_index(
    *,
    index_path: Path | str,
    query: str,
    limit: int = 20,
) -> list[FtsSearchHit]:
    resolved_index_path = Path(index_path).resolve()
    if not resolved_index_path.exists():
        raise FileNotFoundError(f"FTS index does not exist: {resolved_index_path}")
    if limit <= 0:
        raise ValueError("limit must be > 0")

    match_query = _build_fts_match_query(query)
    if not match_query:
        return []

    connection = sqlite3.connect(resolved_index_path)
    try:
        rows = connection.execute(
            """
            SELECT
              chunk_id,
              document_version_id,
              document_title,
              source_type,
              project,
              supplier,
              document_version,
              bm25(fts_chunks) AS score
            FROM fts_chunks
            WHERE fts_chunks MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (match_query, limit),
        ).fetchall()
    finally:
        connection.close()

    return [
        FtsSearchHit(
            chunk_id=str(row[0] or ""),
            document_version_id=str(row[1] or ""),
            document_title=normalize_space(str(row[2] or "")),
            source_type=normalize_space(str(row[3] or "")),
            project=normalize_space(str(row[4] or "")),
            supplier=normalize_space(str(row[5] or "")),
            document_version=normalize_space(str(row[6] or "")),
            bm25_score=float(row[7] or 0.0),
        )
        for row in rows
    ]


def _build_fts_match_query(query: str) -> str | None:
    normalized = normalize_space(query).lower()
    if not normalized:
        return None

    def _has_cjk(value: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in value)

    tokens: list[str] = []
    for raw in normalized.replace("\n", " ").split(" "):
        token = raw.strip()
        if not token:
            continue
        if (
            any("a" <= char <= "z" or char.isdigit() or char == "_" for char in token)
            or _has_cjk(token)
        ):
            cleaned = "".join(
                char for char in token if char.isalnum() or char in {"_", ".", "/", "-"}
            )
            if len(cleaned) >= 2:
                # Tokens that contain dots but no letters (e.g. "7.1", "3.2.1") are
                # version numbers. FTS5 treats "." as a separator, so prefix queries
                # like "7.1"* only match the leading "7" part. Use an exact match
                # instead so "7.1" in document text is found correctly.
                has_letter = any("a" <= char <= "z" for char in cleaned)
                has_dot = "." in cleaned
                has_cjk = _has_cjk(cleaned)
                if has_dot and not has_letter:
                    tokens.append(_escape_fts_token(cleaned))
                elif has_cjk and not has_letter:
                    tokens.append(_escape_fts_token(cleaned))
                else:
                    tokens.append(f"{_escape_fts_token(cleaned)}*")

    if not tokens:
        return None
    return " AND ".join(dict.fromkeys(tokens))


def _escape_fts_token(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


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
        ((chunks_path, document_payload) for _, chunks_path, document_payload in latest_by_document.values()),
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
