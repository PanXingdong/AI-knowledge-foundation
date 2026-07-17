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
)
from agent_knowledge_hub.code_manifest import DEFAULT_EXCLUDE_DIRS


# ---------------------------------------------------------------------------
# _ChangeBuffer
# ---------------------------------------------------------------------------

class TestChangeBuffer:
    def test_empty_buffer_returns_empty_set(self):
        buf = _ChangeBuffer(debounce_seconds=0.1)
        assert buf.drain() == set()

    def test_drain_before_debounce_returns_empty(self):
        buf = _ChangeBuffer(debounce_seconds=10.0)
        buf.add(Path("/tmp/a.cpp"))
        assert buf.drain() == set()

    def test_drain_after_debounce_returns_paths(self):
        buf = _ChangeBuffer(debounce_seconds=0.05)
        buf.add(Path("/tmp/a.cpp"))
        buf.add(Path("/tmp/b.h"))
        time.sleep(0.1)
        result = buf.drain()
        assert result == {Path("/tmp/a.cpp"), Path("/tmp/b.h")}

    def test_drain_clears_buffer(self):
        buf = _ChangeBuffer(debounce_seconds=0.05)
        buf.add(Path("/tmp/a.cpp"))
        time.sleep(0.1)
        buf.drain()
        assert buf.drain() == set()

    def test_new_event_resets_debounce(self):
        buf = _ChangeBuffer(debounce_seconds=0.15)
        buf.add(Path("/tmp/a.cpp"))
        time.sleep(0.1)
        buf.add(Path("/tmp/b.cpp"))   # 重置计时器
        assert buf.drain() == set()   # 尚未超过防抖窗口

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

        result = buf.drain()
        assert result == set(paths)


# ---------------------------------------------------------------------------
# CodeRepositoryWatcher — 过滤逻辑
# ---------------------------------------------------------------------------

class TestCodeRepositoryWatcherFiltering:
    """通过直接调用 _enqueue 测试过滤逻辑，不依赖 watchdog。"""

    def _make_watcher(self, tmp_path: Path) -> CodeRepositoryWatcher:
        return CodeRepositoryWatcher(
            watch_dir=tmp_path,
            on_change=lambda _: None,
            debounce_seconds=0.0,
        )

    def test_cpp_file_is_accepted(self, tmp_path: Path):
        watcher = self._make_watcher(tmp_path)
        target = tmp_path / "src" / "foo.cpp"
        target.parent.mkdir()
        target.touch()
        watcher._enqueue(target)
        time.sleep(0.05)
        assert target.resolve() in watcher._buffer.drain()

    def test_unsupported_extension_is_rejected(self, tmp_path: Path):
        watcher = self._make_watcher(tmp_path)
        target = tmp_path / "foo.exe"
        target.touch()
        watcher._enqueue(target)
        time.sleep(0.05)
        assert watcher._buffer.drain() == set()

    def test_excluded_dir_is_rejected(self, tmp_path: Path):
        watcher = self._make_watcher(tmp_path)
        excluded = tmp_path / "KanziEngine" / "foo.cpp"
        excluded.parent.mkdir()
        excluded.touch()
        watcher._enqueue(excluded)
        time.sleep(0.05)
        assert watcher._buffer.drain() == set()

    def test_nested_excluded_dir_is_rejected(self, tmp_path: Path):
        watcher = self._make_watcher(tmp_path)
        nested = tmp_path / "src" / "__pycache__" / "foo.py"
        nested.parent.mkdir(parents=True)
        nested.touch()
        watcher._enqueue(nested)
        time.sleep(0.05)
        assert watcher._buffer.drain() == set()


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
