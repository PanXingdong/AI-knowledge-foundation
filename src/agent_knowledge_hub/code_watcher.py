"""
code_watcher.py — 代码仓文件监听与实时增量入库服务

监听指定目录的源码文件变更，防抖后自动触发增量入库，并重建检索索引。

用法（CLI）：
    python -m agent_knowledge_hub.cli watch-repo \
        --watch-dir /path/to/ClusterHMI \
        --out-dir /path/to/processed \
        --fts-index-path /path/to/chunks.fts.sqlite \
        --vector-index-path /path/to/chunks.vector.json \
        --exclude-dir KanziEngine --exclude-dir someip --exclude-dir ClusterHMIPrebuilts
"""
from __future__ import annotations

import logging
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# 默认监听的文件扩展名（与 parsers.py 的 _CODE_EXTENSIONS 对齐）
WATCHABLE_EXTENSIONS: frozenset[str] = frozenset({
    ".c", ".cc", ".cpp", ".cxx",
    ".h", ".hh", ".hpp", ".hxx", ".inl",
    ".py", ".sh", ".cmake", ".mk",
    ".java", ".js", ".ts", ".rs", ".proto",
    ".json", ".yaml", ".yml", ".xml",
    ".md", ".txt",
})

# 默认排除的目录名，与 code_manifest.DEFAULT_EXCLUDE_DIRS 保持一致
from agent_knowledge_hub.code_manifest import DEFAULT_EXCLUDE_DIRS  # noqa: E402

# 失败后最大重试次数（超过则记录警告并放弃）
_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# 内部：防抖缓冲（区分 changed / deleted）
# ---------------------------------------------------------------------------

@dataclass
class _PendingChange:
    changed: set[Path] = field(default_factory=set)
    deleted: set[Path] = field(default_factory=set)
    retry_counts: dict[Path, int] = field(default_factory=dict)


class _ChangeBuffer:
    """线程安全的文件变更防抖缓冲，分别跟踪变更和删除。"""

    def __init__(self, debounce_seconds: float) -> None:
        self._lock = threading.Lock()
        self._pending = _PendingChange()
        self._debounce = debounce_seconds
        self._last_event_ts = 0.0

    def add(self, path: Path) -> None:
        with self._lock:
            self._pending.changed.add(path)
            self._pending.deleted.discard(path)   # 若之前标记删除，重新出现则取消
            self._last_event_ts = time.monotonic()

    def add_deleted(self, path: Path) -> None:
        with self._lock:
            self._pending.deleted.add(path)
            self._pending.changed.discard(path)   # 删除的文件不再入库
            self._last_event_ts = time.monotonic()

    def re_enqueue_failed(self, paths: set[Path], deleted: set[Path]) -> None:
        """将失败的路径重新入队（用于有限重试），超出次数则从缓冲移除并丢弃。

        Note: retry_counts are intentionally NOT reset by ``drain()``.  Each
        call here increments the *cumulative* failure count so that a path
        that fails on every attempt is abandoned after exactly ``_MAX_RETRIES``
        total failures, rather than resetting the counter between each drain.
        """
        with self._lock:
            for p in paths:
                cnt = self._pending.retry_counts.get(p, 0) + 1
                if cnt <= _MAX_RETRIES:
                    self._pending.changed.add(p)
                    self._pending.retry_counts[p] = cnt
                    logger.warning("重新入队（第 %d 次）：%s", cnt, p)
                else:
                    # 超出重试次数：从缓冲中清除；保留 retry_counts 条目（设为
                    # _MAX_RETRIES+1）以防止后续调用重新加入。
                    self._pending.changed.discard(p)
                    self._pending.retry_counts[p] = _MAX_RETRIES + 1
                    logger.error("放弃重试（超过 %d 次）：%s", _MAX_RETRIES, p)
            for p in deleted:
                cnt = self._pending.retry_counts.get(p, 0) + 1
                if cnt <= _MAX_RETRIES:
                    self._pending.deleted.add(p)
                    self._pending.retry_counts[p] = cnt
                else:
                    self._pending.deleted.discard(p)
                    self._pending.retry_counts[p] = _MAX_RETRIES + 1
                    logger.error("放弃重试删除（超过 %d 次）：%s", _MAX_RETRIES, p)
            if paths or deleted:
                self._last_event_ts = time.monotonic()

    def mark_success(self, paths: set[Path], deleted: set[Path]) -> None:
        """在一批事件成功处理后清除其重试计数。

        只有真正成功处理的路径才会被清除计数，从而允许下一次入队时从零开始。
        """
        with self._lock:
            for p in paths | deleted:
                self._pending.retry_counts.pop(p, None)

    def drain(self, *, force: bool = False) -> tuple[set[Path], set[Path]]:
        """若防抖窗口已过（或 force=True），返回并清空待处理集合。

        Returns
        -------
        (changed, deleted)

        Note: ``retry_counts`` are intentionally preserved across drains.
        They are only cleared by ``mark_success()`` after a successful
        callback, or reset to ``_MAX_RETRIES + 1`` by ``re_enqueue_failed()``
        when the limit is exceeded.  Clearing them here would cause every
        drain to reset the counter, allowing infinite "first retry" loops.
        """
        with self._lock:
            if not (self._pending.changed or self._pending.deleted):
                return set(), set()
            elapsed = time.monotonic() - self._last_event_ts
            if not force and elapsed < self._debounce:
                return set(), set()
            changed = set(self._pending.changed)
            deleted = set(self._pending.deleted)
            self._pending.changed.clear()
            self._pending.deleted.clear()
            # Do NOT clear retry_counts — they track cumulative failures and
            # must survive across drain/re-enqueue cycles.
            return changed, deleted


# ---------------------------------------------------------------------------
# 公开：文件监听器
# ---------------------------------------------------------------------------

class CodeRepositoryWatcher:
    """
    监听源码目录，文件新增/修改/重命名/删除后触发回调。

    Parameters
    ----------
    watch_dir:
        要监听的根目录（如 ClusterHMI）。
    on_change:
        变更回调，接收 (changed: set[Path], deleted: set[Path])。
        在后台线程中执行。
    debounce_seconds:
        防抖等待时间（秒）。连续变更会被合并到同一批次处理。
    exclude_dirs:
        *追加*排除的目录名（会与 DEFAULT_EXCLUDE_DIRS 合并，不会替换）。
    watchable_extensions:
        要监听的文件扩展名集合。
    """

    def __init__(
        self,
        watch_dir: Path | str,
        on_change: Callable[[set[Path], set[Path]], None],
        debounce_seconds: float = 3.0,
        exclude_dirs: set[str] | frozenset[str] | None = None,
        watchable_extensions: set[str] | frozenset[str] | None = None,
    ) -> None:
        self._watch_dir = Path(watch_dir).resolve()
        self._on_change = on_change
        self._buffer = _ChangeBuffer(debounce_seconds)
        # 用户自定义 exclude_dirs 与默认集合合并（不替换）
        extra = frozenset(exclude_dirs) if exclude_dirs is not None else frozenset()
        self._exclude_dirs: frozenset[str] = DEFAULT_EXCLUDE_DIRS | extra
        self._watchable_ext = (
            frozenset(watchable_extensions)
            if watchable_extensions is not None
            else WATCHABLE_EXTENSIONS
        )
        self._stop_event = threading.Event()
        self._observer = None
        self._flush_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动文件监听（非阻塞）。"""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError as exc:
            raise ImportError(
                "watchdog 未安装，请执行：pip install watchdog"
            ) from exc

        watcher = self

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):  # type: ignore[override]
                if not event.is_directory:
                    watcher._enqueue(Path(event.src_path))

            def on_created(self, event):  # type: ignore[override]
                if not event.is_directory:
                    watcher._enqueue(Path(event.src_path))

            def on_deleted(self, event):  # type: ignore[override]
                if not event.is_directory:
                    watcher._enqueue_deleted(Path(event.src_path))

            def on_moved(self, event):  # type: ignore[override]
                if not event.is_directory:
                    # 源路径视为删除，目标路径视为新增
                    watcher._enqueue_deleted(Path(event.src_path))
                    watcher._enqueue(Path(event.dest_path))

        self._observer = Observer()
        self._observer.schedule(_Handler(), str(self._watch_dir), recursive=True)
        self._observer.start()

        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            daemon=True,
            name="code-watcher-flush",
        )
        self._flush_thread.start()

        logger.info("CodeRepositoryWatcher 已启动，监听目录：%s", self._watch_dir)

    def stop(self) -> None:
        """停止文件监听；先 flush 防抖窗口中的剩余事件再退出。"""
        # 停止 watchdog observer（不再产生新事件）
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()

        # Shutdown drain：强制 flush 剩余事件，不等防抖窗口
        changed, deleted = self._buffer.drain(force=True)
        if changed or deleted:
            logger.info(
                "shutdown drain：处理 %d 个变更，%d 个删除",
                len(changed), len(deleted),
            )
            try:
                self._on_change(changed, deleted)
            except Exception:
                # We are shutting down — there is nowhere to re-enqueue.
                # Log the specific paths so operators can manually re-trigger
                # ingestion for anything that was lost.
                logger.exception(
                    "shutdown drain 回调异常，以下事件将丢失（%d 个变更，%d 个删除）："
                    "\n  changed: %s\n  deleted: %s",
                    len(changed), len(deleted),
                    sorted(changed), sorted(deleted),
                )

        self._stop_event.set()
        if self._flush_thread is not None:
            self._flush_thread.join(timeout=10.0)
        logger.info("CodeRepositoryWatcher 已停止")

    def __enter__(self) -> "CodeRepositoryWatcher":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _is_allowed(self, path: Path) -> bool:
        """返回 True 当路径通过扩展名/目录/symlink 过滤。"""
        resolved = path.resolve()
        # 扩展名过滤
        if resolved.suffix.lower() not in self._watchable_ext:
            return False
        # 排除目录过滤（任意层级）
        if any(part in self._exclude_dirs for part in resolved.parts):
            return False
        # Symlink 安全检查：拒绝指向仓库外的 symlink
        if path.is_symlink():
            real = resolved
            if not _is_within(real, self._watch_dir):
                logger.warning(
                    "跳过仓库外 symlink：%s -> %s", path, real
                )
                return False
        return True

    def _enqueue(self, path: Path) -> None:
        """过滤并入队一个变更路径。"""
        if not self._is_allowed(path):
            return
        self._buffer.add(path.resolve())
        logger.debug("已入队变更：%s", path)

    def _enqueue_deleted(self, path: Path) -> None:
        """入队一个删除/移走的路径（无需文件存在）。

        Note: For deleted files ``path.resolve()`` may not follow the same
        symlink chain as when the file existed (the symlink itself may already
        be gone).  We therefore check extension and excluded dirs against the
        *original* path parts rather than the resolved path to avoid false
        negatives.  The resolved path is still used as the state key so it
        matches the key written during ingestion.
        """
        # Check extension and excluded dirs on the raw path (file may be gone).
        if path.suffix.lower() not in self._watchable_ext:
            return
        if any(part in self._exclude_dirs for part in path.parts):
            return
        # Use resolve() for the state key to match the key stored at ingest time.
        # For a deleted regular file, os.path.abspath gives the same result
        # without following a (now-missing) symlink.
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        self._buffer.add_deleted(resolved)
        logger.debug("已入队删除：%s", resolved)

    def _flush_loop(self) -> None:
        """后台线程：定期检查防抖缓冲，触发回调；失败时有限重试。"""
        while not self._stop_event.is_set():
            time.sleep(0.5)
            changed, deleted = self._buffer.drain()
            if not changed and not deleted:
                continue
            logger.info(
                "检测到 %d 个文件变更，%d 个删除，开始处理…",
                len(changed), len(deleted),
            )
            try:
                self._on_change(changed, deleted)
                # Clear retry counts only after a fully successful callback so
                # that persistent failures accumulate toward the retry limit.
                self._buffer.mark_success(changed, deleted)
            except Exception:
                logger.exception("增量入库回调异常，将重新入队")
                self._buffer.re_enqueue_failed(changed, deleted)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _is_within(child: Path, parent: Path) -> bool:
    """Return True if *child* is inside *parent* (both resolved)."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# 公开：高层入口 — 启动完整的「监听 → 入库 → 重建索引」服务
# ---------------------------------------------------------------------------

def run_watch_service(
    *,
    watch_dir: Path | str,
    out_dir: Path | str,
    project: str = "ClusterHMI",
    owner: str = "PATAC",
    fts_index_path: Path | str | None = None,
    vector_index_path: Path | str | None = None,
    exclude_dirs: set[str] | None = None,
    debounce_seconds: float = 3.0,
    rebuild_indexes: bool = True,
) -> None:
    """
    阻塞式运行代码仓监听服务。

    流程：
      文件变更/删除 → 防抖 → 增量入库（ingest_paths_incremental）
                           → 重建 FTS 索引（候选 → 原子替换）
                           → 重建向量索引（候选 → 原子替换）

    Parameters
    ----------
    watch_dir:
        监听的代码仓根目录。
    out_dir:
        知识库产物输出目录（processed/）。
    project:
        嵌入 chunk 元数据的项目名。
    owner:
        嵌入 chunk 元数据的归属方。
    fts_index_path:
        FTS 索引文件路径；为 None 时跳过重建。
    vector_index_path:
        向量索引文件路径；为 None 时跳过重建。
    exclude_dirs:
        追加排除的目录名（与默认集合合并）。
    debounce_seconds:
        防抖等待秒数。
    rebuild_indexes:
        变更入库后是否自动重建索引。
    """
    from agent_knowledge_hub.incremental import ingest_paths_incremental
    from agent_knowledge_hub.code_manifest import get_repo_version
    from agent_knowledge_hub.fts_index import build_fts_index
    from agent_knowledge_hub.vector_index import build_vector_index

    watch_root = Path(watch_dir).resolve()
    out_root = Path(out_dir).resolve()

    # Warn early if out_dir sits inside watch_dir.  Watchdog would then pick
    # up every index/state file write as a new change event, potentially
    # triggering an infinite ingest → write → re-trigger loop.
    try:
        out_root.relative_to(watch_root)
        logger.warning(
            "out_dir (%s) 位于 watch_dir (%s) 内部。"
            "建议将产物目录移到监听目录之外，否则每次入库写入都会触发新的变更事件。",
            out_root, watch_root,
        )
    except ValueError:
        pass  # out_root is outside watch_root — correct configuration

    doc_version = get_repo_version(watch_root)

    def _on_change(changed_paths: set[Path], deleted_paths: set[Path]) -> None:
        summary = ingest_paths_incremental(
            paths=changed_paths,
            deleted_paths=deleted_paths,
            watch_dir=watch_root,
            out_dir=out_root,
            project=project,
            owner=owner,
            document_version=doc_version,
        )
        logger.info(
            "入库完成：处理 %d 个，未变更 %d 个，失败 %d 个，清除 %d 个",
            summary.processed_count,
            summary.unchanged_count,
            summary.failed_count,
            len(deleted_paths),
        )

        # Surface per-file parse/ingest failures as an exception so that the
        # watcher's retry mechanism re-enqueues the failed paths.  Unchanged
        # files are not re-enqueued (they were skipped by hash check anyway).
        if summary.failed_count > 0:
            failed_paths = {
                f["file_path"] for f in summary.failed if "file_path" in f
            }
            raise RuntimeError(
                f"入库失败 {summary.failed_count} 个文件，将由 Watcher 重试: "
                + ", ".join(sorted(failed_paths))
            )

        if not rebuild_indexes:
            return

        # Rebuild both FTS and vector indexes to candidate paths *before*
        # touching either production path.  Only when both builds succeed are
        # both candidates swapped into production back-to-back.  This minimises
        # the window during which FTS and vector are inconsistent and ensures
        # that a failed build leaves the production indexes untouched.
        _rebuild_indexes_atomic(
            build_fts_fn=(
                (lambda cand: build_fts_index(processed_dir=out_root, index_path=cand))
                if fts_index_path is not None else None
            ),
            build_vec_fn=(
                (lambda cand: build_vector_index(processed_dir=out_root, index_path=cand))
                if vector_index_path is not None else None
            ),
            fts_target=Path(fts_index_path) if fts_index_path is not None else None,
            vector_target=Path(vector_index_path) if vector_index_path is not None else None,
        )

    watcher = CodeRepositoryWatcher(
        watch_dir=watch_root,
        on_change=_on_change,
        debounce_seconds=debounce_seconds,
        exclude_dirs=exclude_dirs,
    )

    print(f"[watch-repo] 开始监听：{watch_root}")
    print(f"[watch-repo] 产物输出：{out_root}")
    print("[watch-repo] 按 Ctrl+C 停止")

    with watcher:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            # watcher.__exit__ -> stop() 会自动执行 shutdown drain
            print("\n[watch-repo] 收到中断信号，正在 flush 剩余事件并停止…")


def _remove_candidate(path: Path) -> None:
    """Remove a candidate index path (file or directory), ignoring errors."""
    try:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    except OSError:
        pass


def _rebuild_indexes_atomic(
    *,
    build_fts_fn: Callable[[Path], object] | None,
    build_vec_fn: Callable[[Path], object] | None,
    fts_target: Path | None,
    vector_target: Path | None,
) -> None:
    """Build FTS and/or vector indexes then atomically swap both into production.

    Both indexes are built to candidate paths *before* either production path
    is touched.  Only when all requested builds succeed are the candidates
    renamed into production back-to-back.  This minimises the inconsistency
    window between FTS and vector (a reader would have to query between the
    two ``replace()`` calls to see mismatched indexes, which is far shorter
    than the full build time) and guarantees that a failed build leaves the
    production indexes untouched.

    If only one index type is requested (the other target is None) this
    function degrades gracefully to a single-index atomic swap.
    """
    candidates: list[tuple[Path, Path]] = []  # (candidate, target) pairs to swap

    try:
        if build_fts_fn is not None and fts_target is not None:
            fts_cand = fts_target.with_suffix(fts_target.suffix + ".candidate")
            _remove_candidate(fts_cand)
            logger.info("重建 FTS 索引（候选：%s）…", fts_cand)
            build_fts_fn(fts_cand)
            candidates.append((fts_cand, fts_target))

        if build_vec_fn is not None and vector_target is not None:
            vec_cand = vector_target.with_suffix(vector_target.suffix + ".candidate")
            _remove_candidate(vec_cand)
            logger.info("重建向量索引（候选：%s）…", vec_cand)
            build_vec_fn(vec_cand)
            candidates.append((vec_cand, vector_target))

        # All builds succeeded — swap candidates into production back-to-back.
        for cand, target in candidates:
            cand.replace(target)
        if candidates:
            labels = [str(t.name) for _, t in candidates]
            logger.info("索引已原子更新：%s", ", ".join(labels))

    except Exception:
        logger.exception("索引重建失败，生产索引未被修改")
        # Clean up any partially-built candidates.
        for cand, _ in candidates:
            _remove_candidate(cand)
        # Also clean up candidates that were built but not yet in the list
        # (build_vec_fn failed after build_fts_fn succeeded).
        if build_vec_fn is not None and vector_target is not None:
            vec_cand = vector_target.with_suffix(vector_target.suffix + ".candidate")
            _remove_candidate(vec_cand)
        raise
