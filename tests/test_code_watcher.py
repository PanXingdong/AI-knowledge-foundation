"""
tests/test_code_watcher.py — CodeRepositoryWatcher 单元测试
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from agent_knowledge_hub.code_watcher import (
    WATCHABLE_EXTENSIONS,
    _ChangeBuffer,
    CodeRepositoryWatcher,
    _MAX_RETRIES,
)
from agent_knowledge_hub.code_manifest import DEFAULT_EXCLUDE_DIRS


# ---------------------------------------------------------------------------
# _ChangeBuffer
# ---------------------------------------------------------------------------

class TestChangeBuffer:
    def test_empty_buffer_returns_empty_set(self):
        buf = _ChangeBuffer(debounce_seconds=0.1)
        changed, deleted = buf.drain()
        assert changed == set()
        assert deleted == set()

    def test_drain_before_debounce_returns_empty(self):
        buf = _ChangeBuffer(debounce_seconds=10.0)
        buf.add(Path("/tmp/a.cpp"))
        changed, deleted = buf.drain()
        assert changed == set()

    def test_drain_after_debounce_returns_paths(self):
        buf = _ChangeBuffer(debounce_seconds=0.05)
        buf.add(Path("/tmp/a.cpp"))
        buf.add(Path("/tmp/b.h"))
        time.sleep(0.1)
        changed, deleted = buf.drain()
        assert changed == {Path("/tmp/a.cpp"), Path("/tmp/b.h")}
        assert deleted == set()

    def test_drain_clears_buffer(self):
        buf = _ChangeBuffer(debounce_seconds=0.05)
        buf.add(Path("/tmp/a.cpp"))
        time.sleep(0.1)
        buf.drain()
        changed, deleted = buf.drain()
        assert changed == set()

    def test_new_event_resets_debounce(self):
        buf = _ChangeBuffer(debounce_seconds=0.15)
        buf.add(Path("/tmp/a.cpp"))
        time.sleep(0.1)
        buf.add(Path("/tmp/b.cpp"))   # 重置计时器
        changed, _ = buf.drain()
        assert changed == set()       # 尚未超过防抖窗口

    def test_thread_safety(self):
        buf = _ChangeBuffer(debounce_seconds=0.0)
        paths = [Path(f"/tmp/f{i}.cpp") for i in range(50)]

        def add_paths():
            for p in paths:
                buf.add(p)

        threads = [threading.Thread(target=add_paths) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        changed, _ = buf.drain()
        assert changed == set(paths)

    def test_deleted_tracked_separately(self):
        buf = _ChangeBuffer(debounce_seconds=0.0)
        buf.add(Path("/tmp/a.cpp"))
        buf.add_deleted(Path("/tmp/b.cpp"))
        time.sleep(0.05)
        changed, deleted = buf.drain()
        assert changed == {Path("/tmp/a.cpp")}
        assert deleted == {Path("/tmp/b.cpp")}

    def test_delete_cancels_pending_change(self):
        buf = _ChangeBuffer(debounce_seconds=0.0)
        buf.add(Path("/tmp/a.cpp"))
        buf.add_deleted(Path("/tmp/a.cpp"))  # 删除取消变更
        time.sleep(0.05)
        changed, deleted = buf.drain()
        assert Path("/tmp/a.cpp") not in changed
        assert Path("/tmp/a.cpp") in deleted

    def test_change_after_delete_cancels_delete(self):
        buf = _ChangeBuffer(debounce_seconds=0.0)
        buf.add_deleted(Path("/tmp/a.cpp"))
        buf.add(Path("/tmp/a.cpp"))           # 文件重新出现
        time.sleep(0.05)
        changed, deleted = buf.drain()
        assert Path("/tmp/a.cpp") in changed
        assert Path("/tmp/a.cpp") not in deleted

    def test_force_drain_bypasses_debounce(self):
        buf = _ChangeBuffer(debounce_seconds=9999.0)
        buf.add(Path("/tmp/a.cpp"))
        changed, _ = buf.drain(force=True)
        assert changed == {Path("/tmp/a.cpp")}

    def test_re_enqueue_retry_limit(self):
        buf = _ChangeBuffer(debounce_seconds=0.0)
        path = Path("/tmp/fail.cpp")
        for _ in range(_MAX_RETRIES + 2):
            buf.re_enqueue_failed({path}, set())
        time.sleep(0.05)
        changed, _ = buf.drain()
        # After exceeding retries the path should be silently dropped
        assert path not in changed

    def test_retry_counts_survive_drain(self):
        """Retry counts must NOT be reset when drain() is called.

        This is the core correctness property: if a path fails on every
        attempt, the counter must accumulate across drain cycles so that the
        path is eventually abandoned after exactly _MAX_RETRIES failures,
        rather than restarting the count from 1 on every drain.
        """
        buf = _ChangeBuffer(debounce_seconds=0.0)
        path = Path("/tmp/persistent_fail.cpp")

        # Simulate _MAX_RETRIES failure cycles, each preceded by a drain
        # (which is what _flush_loop does between re_enqueue_failed calls).
        for attempt in range(1, _MAX_RETRIES + 1):
            buf.re_enqueue_failed({path}, set())
            time.sleep(0.05)
            changed, _ = buf.drain()
            # Path should still be in changed until the limit is reached.
            assert path in changed, (
                f"path should still be queued on attempt {attempt} of {_MAX_RETRIES}"
            )

        # One more failure — now over the limit.
        buf.re_enqueue_failed({path}, set())
        time.sleep(0.05)
        changed, _ = buf.drain()
        assert path not in changed, "path must be abandoned once retry limit is exceeded"

    def test_mark_success_clears_retry_counts(self):
        """mark_success() must reset the retry counter so a path that
        eventually succeeds can start fresh if it fails again later."""
        buf = _ChangeBuffer(debounce_seconds=0.0)
        path = Path("/tmp/flaky.cpp")

        # Fail once, then succeed.
        buf.re_enqueue_failed({path}, set())
        buf.mark_success({path}, set())

        # After success the retry count should be zero; we should get
        # _MAX_RETRIES more attempts before abandonment.
        for attempt in range(1, _MAX_RETRIES + 1):
            buf.re_enqueue_failed({path}, set())
            time.sleep(0.05)
            changed, _ = buf.drain()
            assert path in changed, f"should still be queued on attempt {attempt}"

        buf.re_enqueue_failed({path}, set())
        time.sleep(0.05)
        changed, _ = buf.drain()
        assert path not in changed, "must be abandoned after _MAX_RETRIES post-success failures"


# ---------------------------------------------------------------------------
# CodeRepositoryWatcher — 过滤逻辑
# ---------------------------------------------------------------------------

class TestCodeRepositoryWatcherFiltering:
    """通过直接调用 _enqueue 测试过滤逻辑，不依赖 watchdog。"""

    def _make_watcher(self, tmp_path: Path) -> CodeRepositoryWatcher:
        return CodeRepositoryWatcher(
            watch_dir=tmp_path,
            on_change=lambda _c, _d: None,
            debounce_seconds=0.0,
        )

    def test_cpp_file_is_accepted(self, tmp_path: Path):
        watcher = self._make_watcher(tmp_path)
        target = tmp_path / "src" / "foo.cpp"
        target.parent.mkdir()
        target.touch()
        watcher._enqueue(target)
        time.sleep(0.05)
        changed, _ = watcher._buffer.drain()
        assert target.resolve() in changed

    def test_unsupported_extension_is_rejected(self, tmp_path: Path):
        watcher = self._make_watcher(tmp_path)
        target = tmp_path / "foo.exe"
        target.touch()
        watcher._enqueue(target)
        time.sleep(0.05)
        changed, _ = watcher._buffer.drain()
        assert changed == set()

    def test_excluded_dir_is_rejected(self, tmp_path: Path):
        watcher = self._make_watcher(tmp_path)
        excluded = tmp_path / "KanziEngine" / "foo.cpp"
        excluded.parent.mkdir()
        excluded.touch()
        watcher._enqueue(excluded)
        time.sleep(0.05)
        changed, _ = watcher._buffer.drain()
        assert changed == set()

    def test_nested_excluded_dir_is_rejected(self, tmp_path: Path):
        watcher = self._make_watcher(tmp_path)
        nested = tmp_path / "src" / "__pycache__" / "foo.py"
        nested.parent.mkdir(parents=True)
        nested.touch()
        watcher._enqueue(nested)
        time.sleep(0.05)
        changed, _ = watcher._buffer.drain()
        assert changed == set()

    def test_custom_exclude_merges_with_defaults(self, tmp_path: Path):
        """用户自定义 exclude 不应替换默认 exclude。"""
        watcher = CodeRepositoryWatcher(
            watch_dir=tmp_path,
            on_change=lambda _c, _d: None,
            debounce_seconds=0.0,
            exclude_dirs={"my_custom_dir"},
        )
        # 默认 exclude 仍然生效
        assert "KanziEngine" in watcher._exclude_dirs
        assert "my_custom_dir" in watcher._exclude_dirs

    def test_deleted_file_enqueued_to_deleted_set(self, tmp_path: Path):
        watcher = self._make_watcher(tmp_path)
        path = tmp_path / "foo.cpp"
        # File doesn't need to exist for deletion tracking
        watcher._enqueue_deleted(path)
        time.sleep(0.05)
        _, deleted = watcher._buffer.drain()
        assert path.resolve() in deleted


# ---------------------------------------------------------------------------
# DEFAULT_EXCLUDE_DIRS 一致性
# ---------------------------------------------------------------------------

def test_watcher_uses_same_exclude_dirs_as_manifest():
    """code_watcher 和 code_manifest 的默认排除目录必须一致。"""
    from agent_knowledge_hub.code_watcher import DEFAULT_EXCLUDE_DIRS as WATCHER_EXCLUDES
    assert WATCHER_EXCLUDES is DEFAULT_EXCLUDE_DIRS, (
        "code_watcher.DEFAULT_EXCLUDE_DIRS 应直接引用 code_manifest.DEFAULT_EXCLUDE_DIRS"
    )


# ---------------------------------------------------------------------------
# WATCHABLE_EXTENSIONS 覆盖
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ext", [".cpp", ".h", ".hpp", ".c", ".py", ".cmake", ".md", ".yaml"])
def test_watchable_extensions_covers_common_types(ext: str):
    assert ext in WATCHABLE_EXTENSIONS
