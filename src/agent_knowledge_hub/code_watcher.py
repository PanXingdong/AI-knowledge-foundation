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
import threading
import time
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

# 默认排除的目录名（第三方库 / 体积过大）
DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset({
    "KanziEngine",
    "someip",
    "ClusterHMIPrebuilts",
    ".git",
    "__pycache__",
    "node_modules",
    "build",
    ".tmp",
})


# ---------------------------------------------------------------------------
# 内部：防抖缓冲
# ---------------------------------------------------------------------------

class _ChangeBuffer:
    """线程安全的文件变更防抖缓冲。"""

    def __init__(self, debounce_seconds: float) -> None:
        self._lock = threading.Lock()
        self._pending: set[Path] = set()
        self._debounce = debounce_seconds
        self._last_event_ts = 0.0

    def add(self, path: Path) -> None:
        with self._lock:
            self._pending.add(path)
            self._last_event_ts = time.monotonic()

    def drain(self) -> set[Path]:
        """若防抖窗口已过，返回并清空待处理集合；否则返回空集合。"""
        with self._lock:
            if not self._pending:
                return set()
            if time.monotonic() - self._last_event_ts < self._debounce:
                return set()
            paths = set(self._pending)
            self._pending.clear()
            return paths


# ---------------------------------------------------------------------------
# 公开：文件监听器
# ---------------------------------------------------------------------------

class CodeRepositoryWatcher:
    """
    监听源码目录，文件新增/修改/重命名后触发回调。

    Parameters
    ----------
    watch_dir:
        要监听的根目录（如 ClusterHMI）。
    on_change:
        变更回调，接收一组已变更的 Path 对象。回调在后台线程中执行。
    debounce_seconds:
        防抖等待时间（秒）。连续变更会被合并到同一批次处理。
    exclude_dirs:
        要排除的目录名集合（任意层级命中即跳过）。
    watchable_extensions:
        要监听的文件扩展名集合。
    """

    def __init__(
        self,
        watch_dir: Path | str,
        on_change: Callable[[set[Path]], None],
        debounce_seconds: float = 3.0,
        exclude_dirs: set[str] | frozenset[str] | None = None,
        watchable_extensions: set[str] | frozenset[str] | None = None,
    ) -> None:
        self._watch_dir = Path(watch_dir).resolve()
        self._on_change = on_change
        self._buffer = _ChangeBuffer(debounce_seconds)
        self._exclude_dirs = frozenset(exclude_dirs) if exclude_dirs is not None else DEFAULT_EXCLUDE_DIRS
        self._watchable_ext = frozenset(watchable_extensions) if watchable_extensions is not None else WATCHABLE_EXTENSIONS
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

            def on_moved(self, event):  # type: ignore[override]
                if not event.is_directory:
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
        """停止文件监听。"""
        self._stop_event.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
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

    def _enqueue(self, path: Path) -> None:
        """过滤并入队一个变更路径。"""
        resolved = path.resolve()
        # 扩展名过滤
        if resolved.suffix.lower() not in self._watchable_ext:
            return
        # 排除目录过滤（任意层级）
        if any(part in self._exclude_dirs for part in resolved.parts):
            return
        self._buffer.add(resolved)
        logger.debug("已入队变更：%s", resolved)

    def _flush_loop(self) -> None:
        """后台线程：定期检查防抖缓冲，触发回调。"""
        while not self._stop_event.is_set():
            time.sleep(0.5)
            changed = self._buffer.drain()
            if not changed:
                continue
            logger.info("检测到 %d 个文件变更，开始处理…", len(changed))
            try:
                self._on_change(changed)
            except Exception:
                logger.exception("增量入库回调异常")


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
      文件变更 → 防抖 → 增量入库（ingest_paths_incremental）
                      → 重建 FTS 索引（可选）
                      → 重建向量索引（可选）

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
        排除的目录名，默认使用 DEFAULT_EXCLUDE_DIRS。
    debounce_seconds:
        防抖等待秒数。
    rebuild_indexes:
        变更入库后是否自动重建索引。
    """
    from agent_knowledge_hub.incremental import ingest_paths_incremental
    from agent_knowledge_hub.fts_index import build_fts_index
    from agent_knowledge_hub.vector_index import build_vector_index

    watch_root = Path(watch_dir).resolve()
    out_root = Path(out_dir).resolve()

    def _on_change(changed_paths: set[Path]) -> None:
        summary = ingest_paths_incremental(
            paths=changed_paths,
            out_dir=out_root,
            project=project,
            owner=owner,
        )
        logger.info(
            "入库完成：处理 %d 个，未变更 %d 个，失败 %d 个",
            summary.processed_count,
            summary.unchanged_count,
            summary.failed_count,
        )

        if not rebuild_indexes:
            return
        if fts_index_path is not None:
            logger.info("重建 FTS 索引…")
            build_fts_index(processed_dir=out_root, index_path=Path(fts_index_path))
            logger.info("FTS 索引已更新：%s", fts_index_path)
        if vector_index_path is not None:
            logger.info("重建向量索引…")
            build_vector_index(processed_dir=out_root, index_path=Path(vector_index_path))
            logger.info("向量索引已更新：%s", vector_index_path)

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
            print("\n[watch-repo] 收到中断信号，正在停止…")
