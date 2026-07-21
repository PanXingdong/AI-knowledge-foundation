from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Generator

from agent_knowledge_hub.pipeline import _infer_supplier, _optional, _resolve_manifest_path, ingest_file
from agent_knowledge_hub.parsers import DocumentParseError
from agent_knowledge_hub.utils import file_sha256, is_placeholder, utc_now_iso, write_json

logger = logging.getLogger(__name__)

# In-process reentrant lock protecting concurrent state-file reads/writes.
# RLock allows the same thread to re-enter the lock (needed when _load_state
# is called from within a _state_file_lock context during the commit phase).
_STATE_FILE_LOCK = threading.RLock()


def _acquire_cross_process_lock(fd: Any) -> None:
    """Acquire an exclusive cross-process file lock.

    Uses ``fcntl.flock`` on POSIX and ``msvcrt.locking`` on Windows.
    Falls back to no-op if neither is available (in-process RLock still
    protects same-process concurrency).
    """
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)
        return
    except ImportError:
        pass
    try:
        import msvcrt
        fd.seek(0)
        msvcrt.locking(fd.fileno(), msvcrt.LK_LOCK, 1)
    except (ImportError, OSError):
        pass


def _release_cross_process_lock(fd: Any) -> None:
    """Release the cross-process file lock acquired by ``_acquire_cross_process_lock``."""
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
        return
    except ImportError:
        pass
    try:
        import msvcrt
        fd.seek(0)
        msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
    except (ImportError, OSError):
        pass


@contextmanager
def _state_file_lock(state_path: Path) -> Generator[None, None, None]:
    """Acquire the in-process RLock then an exclusive cross-process file lock.

    Both locks are held for the caller's entire ``with`` block, which allows
    a read-modify-write transaction that is safe across threads *and* processes:

    1. In-process RLock: prevents two threads in the same process from racing.
       Using RLock so the same thread can re-enter (e.g. when _load_state_raw
       is called inside a commit block that already holds the lock).
    2. Cross-process file lock (fcntl on POSIX, msvcrt on Windows): prevents
       two separate processes from interleaving their writes.
    """
    lock_path = state_path.with_suffix(".lock")
    with _STATE_FILE_LOCK:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = open(lock_path, "w")  # noqa: WPS515
        try:
            _acquire_cross_process_lock(lock_fd)
            yield
        finally:
            _release_cross_process_lock(lock_fd)
            lock_fd.close()


def _write_state_atomic(state_path: Path, payload: dict) -> None:
    """Write *payload* to *state_path* atomically via tmp-file + rename.

    Guarantees:
    - Readers never see a partial / truncated JSON file.
    - ``os.fsync`` is called before rename so data survives a crash.
    - Works on the same filesystem (rename is atomic on POSIX; on Windows
      ``Path.replace`` is as close to atomic as the OS allows).
    """
    parent = state_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(dir=parent, suffix=".tmp", prefix=".state-")
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        tmp_path.replace(state_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class IncrementalIngestDocument:
    sample_id: str
    status: str
    source_path: str
    content_hash: str | None
    previous_hash: str | None
    output_dir: str | None
    document_json_path: str | None
    chunks_jsonl_path: str | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IncrementalIngestSummary:
    manifest_path: Path
    output_dir: Path
    generated_at: str
    processed_count: int
    unchanged_count: int
    changed_count: int
    skipped_count: int
    failed_count: int
    documents: list[IncrementalIngestDocument]
    skipped: list[dict[str, str]]
    failed: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": str(self.manifest_path),
            "output_dir": str(self.output_dir),
            "generated_at": self.generated_at,
            "processed_count": self.processed_count,
            "unchanged_count": self.unchanged_count,
            "changed_count": self.changed_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "documents": [document.to_dict() for document in self.documents],
            "skipped": list(self.skipped),
            "failed": list(self.failed),
        }


def ingest_manifest_incremental(
    *,
    manifest_path: Path | str,
    out_dir: Path | str,
    project_root: Path | str | None = None,
    max_chunk_chars: int = 1600,
    max_tokens: int = 512,
    overlap_chars: int = 160,
    fail_fast: bool = False,
) -> IncrementalIngestSummary:
    manifest = Path(manifest_path).resolve()
    output_root = Path(out_dir).resolve()
    root = Path(project_root).resolve() if project_root else manifest.parent
    if not manifest.exists():
        raise FileNotFoundError(f"Manifest does not exist: {manifest}")

    state_path = output_root / "ingest-state.json"
    state = _load_state(state_path)
    updated_entries: dict[str, dict[str, Any]] = {}
    documents: list[IncrementalIngestDocument] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    processed_count = 0
    unchanged_count = 0
    changed_count = 0

    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            sample_id = _get(row, "sample_id") or f"row-{row_number}"
            raw_path = _get(row, "file_path")
            if is_placeholder(raw_path):
                skipped.append(
                    {
                        "sample_id": sample_id,
                        "row_number": str(row_number),
                        "reason": "missing_or_placeholder_path",
                    }
                )
                continue

            source_path = _resolve_manifest_path(raw_path, root, manifest.parent)
            if not source_path.exists():
                skipped.append(
                    {
                        "sample_id": sample_id,
                        "row_number": str(row_number),
                        "reason": "missing_or_placeholder_path",
                        "file_path": str(source_path),
                    }
                )
                continue

            try:
                content_hash = file_sha256(source_path)
            except OSError as exc:
                failure = _build_failure(row, sample_id, row_number, source_path, str(exc))
                failed.append(failure)
                if fail_fast:
                    raise
                continue

            state_key = str(source_path.resolve())
            previous = state.get(state_key) or {}
            previous_hash = previous.get("content_hash")
            if previous_hash == content_hash:
                unchanged_count += 1
                documents.append(
                    IncrementalIngestDocument(
                        sample_id=sample_id,
                        status="unchanged",
                        source_path=str(source_path),
                        content_hash=content_hash,
                        previous_hash=previous_hash,
                        output_dir=previous.get("output_dir"),
                        document_json_path=previous.get("document_json_path"),
                        chunks_jsonl_path=previous.get("chunks_jsonl_path"),
                    )
                )
                continue

            try:
                result = ingest_file(
                    file_path=source_path,
                    out_dir=output_root,
                    title=_optional(row, "document_title") or source_path.stem,
                    source_type=_optional(row, "slot_type") or "unknown",
                    owner=_optional(row, "owner") or "unknown",
                    project=_optional(row, "project") or "unknown",
                    supplier=_infer_supplier(row),
                    document_version=_optional(row, "document_version") or "unknown",
                    sample_id=sample_id,
                    max_chunk_chars=max_chunk_chars,
                    max_tokens=max_tokens,
                    overlap_chars=overlap_chars,
                )
                processed_count += 1
                if previous_hash is not None:
                    changed_count += 1
                document = IncrementalIngestDocument(
                    sample_id=sample_id,
                    status="processed",
                    source_path=str(source_path),
                    content_hash=content_hash,
                    previous_hash=previous_hash,
                    output_dir=str(result.output_dir),
                    document_json_path=str(result.document_json_path),
                    chunks_jsonl_path=str(result.chunks_jsonl_path),
                )
                documents.append(document)
                updated_entries[state_key] = {
                    **document.to_dict(),
                    "updated_at": utc_now_iso(),
                }
            except (DocumentParseError, OSError, ValueError) as exc:
                failure = _build_failure(row, sample_id, row_number, source_path, str(exc))
                failed.append(failure)
                documents.append(
                    IncrementalIngestDocument(
                        sample_id=sample_id,
                        status="failed",
                        source_path=str(source_path),
                        content_hash=content_hash,
                        previous_hash=previous_hash,
                        output_dir=None,
                        document_json_path=None,
                        chunks_jsonl_path=None,
                        reason=str(exc),
                    )
                )
                if fail_fast:
                    raise

    summary = IncrementalIngestSummary(
        manifest_path=manifest,
        output_dir=output_root,
        generated_at=utc_now_iso(),
        processed_count=processed_count,
        unchanged_count=unchanged_count,
        changed_count=changed_count,
        skipped_count=len(skipped),
        failed_count=len(failed),
        documents=documents,
        skipped=skipped,
        failed=failed,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    write_json(output_root / "ingest-run-summary.json", summary.to_dict())
    # Commit phase: manifest ingest has no deletions, only additions/updates.
    _commit_state(output_root / "ingest-state.json", set(), updated_entries)
    _write_legacy_ingest_summary(output_root / "ingest-summary.json", summary)
    return summary


def _load_state_raw(path: Path) -> dict[str, dict[str, Any]]:
    """Read and parse state from *path* **without** acquiring any lock.

    Must only be called from within a ``_state_file_lock`` context so that
    the on-disk file cannot change between this read and the subsequent write.
    """
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Truncated/corrupted state file (e.g. power-loss before the old
        # non-atomic write finished).  Log a warning and start clean rather
        # than crashing.  The atomic-write guarantee prevents this from
        # happening to files we create, but external tools could still corrupt.
        logger.warning("状态文件损坏或不可读，将视为空状态重新开始：%s", path)
        return {}
    documents = payload.get("documents") or {}
    return {
        str(key): dict(value)
        for key, value in documents.items()
        if isinstance(value, dict)
    }


def _load_state(path: Path) -> dict[str, dict[str, Any]]:
    """Read state from *path* under the full state-file lock.

    Use this for the initial snapshot read in an incremental ingest.  The
    lock is released before the expensive per-file processing begins.  A
    second locked read is performed at commit time (see ``_commit_state``) to
    capture any interleaved writes from concurrent processes.
    """
    with _state_file_lock(path):
        return _load_state_raw(path)


def _commit_state(
    state_path: Path,
    deleted_keys: set[str],
    updated_entries: dict[str, dict[str, Any]],
) -> None:
    """Merge and persist state changes atomically.

    This is the *commit phase* of the read-modify-write cycle.  The full
    cross-process lock is held for the entire merge+write, so:

    - Deletions performed by this run are applied to the *current* on-disk
      state (not our stale snapshot), preserving concurrent writes from other
      processes.
    - Our new/updated entries overwrite any stale versions for the same keys.
    - Entries we never touched are left as-is (other processes may have
      updated them while we were ingesting).

    Parameters
    ----------
    state_path:
        Path to the ``ingest-state.json`` file.
    deleted_keys:
        State keys (resolved file path strings) whose artifacts were
        tombstoned during this run and must be removed from state.
    updated_entries:
        State entries produced or updated during this run.
    """
    with _state_file_lock(state_path):
        current = _load_state_raw(state_path)
        for key in deleted_keys:
            current.pop(key, None)
        current.update(updated_entries)
        _write_state_atomic(state_path, {"documents": current})


def _write_legacy_ingest_summary(path: Path, summary: IncrementalIngestSummary) -> None:
    processed = [
        {
            "sample_id": document.sample_id,
            "status": document.status,
            "source_path": document.source_path,
            "output_dir": document.output_dir,
            "document_json_path": document.document_json_path,
            "chunks_jsonl_path": document.chunks_jsonl_path,
        }
        for document in summary.documents
        if document.status == "processed"
    ]
    write_json(
        path,
        {
            "manifest_path": str(summary.manifest_path),
            "output_dir": str(summary.output_dir),
            "processed_count": summary.processed_count,
            "skipped_count": summary.skipped_count,
            "failed_count": summary.failed_count,
            "results": processed,
            "skipped": summary.skipped,
            "failed": summary.failed,
        },
    )


def _make_sample_id_from_rel(rel: Path) -> str:
    """Derive a stable sample_id from a relative path (mirrors code_manifest)."""
    import hashlib
    digest = hashlib.sha256(rel.as_posix().encode()).hexdigest()[:8]
    return f"code-{digest}"


def ingest_paths_incremental(
    *,
    paths: set[Path] | list[Path],
    out_dir: Path | str,
    project: str = "unknown",
    owner: str = "unknown",
    supplier: str = "unknown",
    source_type: str = "source_code",
    document_version: str = "unknown",
    max_chunk_chars: int = 1600,
    max_tokens: int = 512,
    overlap_chars: int = 160,
    deleted_paths: set[Path] | list[Path] | None = None,
    watch_dir: Path | str | None = None,
) -> IncrementalIngestSummary:
    """
    对一组文件路径做增量入库：哈希未变则跳过，已变则重新入库；
    deleted_paths 中的路径会从状态和产物中清除（tombstone）。

    Parameters
    ----------
    paths:
        需要检查并按需重新入库的文件路径集合。
    out_dir:
        知识库产物输出目录（processed/）。
    deleted_paths:
        已从代码仓删除/移走的路径集合；状态条目和产物文件会被清理。
    watch_dir:
        代码仓根目录；用于计算相对路径以生成与 manifest 一致的 sample_id。
        不提供时 sample_id 回退到文件 stem。
    project / owner / supplier / source_type / document_version:
        写入 chunk 元数据的字段，可按需覆盖。
    """
    output_root = Path(out_dir).resolve()
    watch_root = Path(watch_dir).resolve() if watch_dir else None
    state_path = output_root / "ingest-state.json"

    # Snapshot read: short-lived lock, released before expensive processing.
    state = _load_state(state_path)

    # Track what we change so the commit phase can merge correctly.
    deleted_keys: set[str] = set()
    updated_entries: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Phase 0: tombstone deleted / moved-away paths
    # ------------------------------------------------------------------
    for del_path in sorted(deleted_paths or []):
        del_path = del_path.resolve()
        state_key = str(del_path)
        prev = state.get(state_key)
        if prev:
            # Prefer removing the whole version output directory so that
            # canonical doc, chunks, processing-record, and quality sidecar
            # are all cleaned up in one shot.  Fall back to individual files
            # when output_dir is not recorded.
            output_dir = prev.get("output_dir")
            if output_dir:
                out_path = Path(output_dir)
                if out_path.is_dir():
                    try:
                        shutil.rmtree(out_path)
                    except OSError as exc:
                        logger.warning("清除产物目录失败（将跳过）：%s — %s", out_path, exc)
                else:
                    logger.warning("产物目录不存在，跳过清除：%s", out_path)
            else:
                # Fallback: delete individual files if output_dir not recorded.
                for field in ("document_json_path", "chunks_jsonl_path"):
                    artefact = prev.get(field)
                    if artefact:
                        try:
                            Path(artefact).unlink(missing_ok=True)
                        except OSError:
                            pass
            logger.info("已清除已删除文件的知识库产物：%s → %s", del_path, output_dir or "(artifact files)")
        deleted_keys.add(state_key)

    documents: list[IncrementalIngestDocument] = []
    failed: list[dict[str, str]] = []
    processed_count = 0
    unchanged_count = 0
    changed_count = 0

    for source_path in sorted(paths):
        source_path = source_path.resolve()
        # Reject symlinks whose resolved target lies outside the watch root.
        if source_path.is_symlink():
            real = source_path.resolve()
            if watch_root and not _is_within(real, watch_root):
                logger.warning(
                    "跳过仓库外 symlink：%s -> %s", source_path, real
                )
                continue
        if not source_path.is_file():
            continue

        try:
            content_hash = file_sha256(source_path)
        except OSError as exc:
            failed.append({"file_path": str(source_path), "reason": str(exc)})
            continue

        state_key = str(source_path)
        previous = state.get(state_key) or {}
        previous_hash = previous.get("content_hash")

        if previous_hash == content_hash:
            unchanged_count += 1
            # Preserve the previously-computed sample_id; fall back to the
            # full-path hash (not stem) to avoid cross-directory collisions.
            fallback_id = _make_sample_id_from_rel(source_path)
            documents.append(
                IncrementalIngestDocument(
                    sample_id=previous.get("sample_id") or fallback_id,
                    status="unchanged",
                    source_path=str(source_path),
                    content_hash=content_hash,
                    previous_hash=previous_hash,
                    output_dir=previous.get("output_dir"),
                    document_json_path=previous.get("document_json_path"),
                    chunks_jsonl_path=previous.get("chunks_jsonl_path"),
                )
            )
            continue

        # Derive sample_id from the repo-relative path when watch_root is
        # available (mirrors code_manifest identity).  Fall back to a hash of
        # the *full* absolute path — not just the stem — so that two files
        # with the same name in different directories never share an identity
        # and inadvertently overwrite each other's output artifacts.
        if watch_root:
            try:
                rel = source_path.relative_to(watch_root)
                sample_id = _make_sample_id_from_rel(rel)
            except ValueError:
                sample_id = _make_sample_id_from_rel(source_path)
        else:
            sample_id = _make_sample_id_from_rel(source_path)

        try:
            result = ingest_file(
                file_path=source_path,
                out_dir=output_root,
                title=source_path.stem,
                source_type=source_type,
                owner=owner,
                project=project,
                supplier=supplier,
                document_version=document_version,
                sample_id=sample_id,
                max_chunk_chars=max_chunk_chars,
                max_tokens=max_tokens,
                overlap_chars=overlap_chars,
            )
            processed_count += 1
            if previous_hash is not None:
                changed_count += 1
            document = IncrementalIngestDocument(
                sample_id=sample_id,
                status="processed",
                source_path=str(source_path),
                content_hash=content_hash,
                previous_hash=previous_hash,
                output_dir=str(result.output_dir),
                document_json_path=str(result.document_json_path),
                chunks_jsonl_path=str(result.chunks_jsonl_path),
            )
            documents.append(document)
            updated_entries[state_key] = {
                **document.to_dict(),
                "updated_at": utc_now_iso(),
            }
        except (DocumentParseError, OSError, ValueError) as exc:
            failed.append({"file_path": str(source_path), "reason": str(exc)})
            documents.append(
                IncrementalIngestDocument(
                    sample_id=sample_id,
                    status="failed",
                    source_path=str(source_path),
                    content_hash=content_hash,
                    previous_hash=previous_hash,
                    output_dir=None,
                    document_json_path=None,
                    chunks_jsonl_path=None,
                    reason=str(exc),
                )
            )

    summary = IncrementalIngestSummary(
        manifest_path=output_root / "ingest-state.json",
        output_dir=output_root,
        generated_at=utc_now_iso(),
        processed_count=processed_count,
        unchanged_count=unchanged_count,
        changed_count=changed_count,
        skipped_count=0,
        failed_count=len(failed),
        documents=documents,
        skipped=[],
        failed=failed,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    state_path = output_root / "ingest-state.json"
    # Commit phase: lock → re-read current on-disk state → merge → write.
    # Re-reading inside the lock captures any changes made by concurrent
    # processes while we were ingesting, so we never silently overwrite them.
    _commit_state(state_path, deleted_keys, updated_entries)
    write_json(output_root / "ingest-run-summary.json", summary.to_dict())
    return summary


def _is_within(child: Path, parent: Path) -> bool:
    """Return True if *child* is inside *parent* (both must be resolved)."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _get(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def _build_failure(
    row: dict[str, str],
    sample_id: str,
    row_number: int,
    source_path: Path,
    reason: str,
) -> dict[str, str]:
    return {
        "sample_id": sample_id,
        "row_number": str(row_number),
        "file_path": str(source_path),
        "document_title": _optional(row, "document_title") or source_path.stem,
        "source_type": _optional(row, "slot_type") or "unknown",
        "owner": _optional(row, "owner") or "unknown",
        "project": _optional(row, "project") or "unknown",
        "supplier": _infer_supplier(row),
        "document_version": _optional(row, "document_version") or "unknown",
        "reason": reason,
    }
