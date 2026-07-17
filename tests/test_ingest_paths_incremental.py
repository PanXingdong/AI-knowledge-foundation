"""
tests/test_ingest_paths_incremental.py — ingest_paths_incremental 单元测试
"""
from __future__ import annotations

from pathlib import Path

from agent_knowledge_hub.incremental import ingest_paths_incremental


def _write_md(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestIngestPathsIncremental:
    def test_new_file_is_processed(self, tmp_path: Path):
        src = _write_md(tmp_path / "docs" / "readme.md", "# Hello\n\nWorld.")
        out = tmp_path / "processed"

        summary = ingest_paths_incremental(paths={src}, out_dir=out)

        assert summary.processed_count == 1
        assert summary.unchanged_count == 0
        assert summary.failed_count == 0
        assert len(summary.documents) == 1
        assert summary.documents[0].status == "processed"

    def test_unchanged_file_is_skipped(self, tmp_path: Path):
        src = _write_md(tmp_path / "docs" / "readme.md", "# Hello\n\nWorld.")
        out = tmp_path / "processed"

        # 第一次入库
        ingest_paths_incremental(paths={src}, out_dir=out)
        # 第二次：内容未变，应跳过
        summary = ingest_paths_incremental(paths={src}, out_dir=out)

        assert summary.processed_count == 0
        assert summary.unchanged_count == 1
        assert summary.documents[0].status == "unchanged"

    def test_modified_file_is_reprocessed(self, tmp_path: Path):
        src = _write_md(tmp_path / "docs" / "readme.md", "# Hello\n\nWorld.")
        out = tmp_path / "processed"

        ingest_paths_incremental(paths={src}, out_dir=out)

        src.write_text("# Hello\n\nUpdated content.", encoding="utf-8")
        summary = ingest_paths_incremental(paths={src}, out_dir=out)

        assert summary.processed_count == 1
        assert summary.changed_count == 1
        assert summary.documents[0].status == "processed"

    def test_nonexistent_file_is_silently_skipped(self, tmp_path: Path):
        ghost = tmp_path / "ghost.md"   # 不创建
        out = tmp_path / "processed"

        summary = ingest_paths_incremental(paths={ghost}, out_dir=out)

        assert summary.processed_count == 0
        assert summary.unchanged_count == 0
        assert summary.failed_count == 0

    def test_multiple_files_mixed_state(self, tmp_path: Path):
        f1 = _write_md(tmp_path / "a.md", "# A\n\nContent A.")
        f2 = _write_md(tmp_path / "b.md", "# B\n\nContent B.")
        out = tmp_path / "processed"

        # 先入库 f1
        ingest_paths_incremental(paths={f1}, out_dir=out)

        # 修改 f1，f2 是新文件
        f1.write_text("# A\n\nUpdated A.", encoding="utf-8")
        summary = ingest_paths_incremental(paths={f1, f2}, out_dir=out)

        assert summary.processed_count == 2
        assert summary.unchanged_count == 0

    def test_state_file_is_written(self, tmp_path: Path):
        src = _write_md(tmp_path / "readme.md", "# Test\n\nContent.")
        out = tmp_path / "processed"

        ingest_paths_incremental(paths={src}, out_dir=out)

        state_file = out / "ingest-state.json"
        assert state_file.exists()

    def test_empty_paths_returns_zero_counts(self, tmp_path: Path):
        out = tmp_path / "processed"
        summary = ingest_paths_incremental(paths=set(), out_dir=out)

        assert summary.processed_count == 0
        assert summary.unchanged_count == 0
        assert summary.failed_count == 0
