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

    def test_deleted_path_removes_artifacts_and_state(self, tmp_path: Path):
        """Tombstoned paths must be purged from state and artifacts from disk."""
        src = _write_md(tmp_path / "docs" / "remove_me.md", "# Delete me\n\nContent.")
        out = tmp_path / "processed"

        # Ingest once to produce artifacts and state.
        summary1 = ingest_paths_incremental(paths={src}, out_dir=out)
        assert summary1.processed_count == 1
        artifact_dir = summary1.documents[0].output_dir
        assert artifact_dir is not None
        from pathlib import Path as _P
        assert _P(artifact_dir).exists(), "artifact dir should exist after first ingest"

        # Now tombstone the deleted file.
        summary2 = ingest_paths_incremental(
            paths=set(),
            out_dir=out,
            deleted_paths={src},
        )

        # Artifact directory must be cleaned up.
        assert not _P(artifact_dir).exists(), "artifact dir should be removed after tombstone"

        # State must no longer contain the deleted file.
        import json
        state_file = out / "ingest-state.json"
        state = json.loads(state_file.read_text())
        assert str(src.resolve()) not in state.get("documents", {}), (
            "deleted key must be removed from state"
        )

    def test_same_stem_different_dirs_get_unique_sample_ids(self, tmp_path: Path):
        """Two files with the same name in different directories must not
        collide on sample_id or output artifacts."""
        f1 = _write_md(tmp_path / "dir_a" / "module.md", "# A\n\nContent A.")
        f2 = _write_md(tmp_path / "dir_b" / "module.md", "# B\n\nContent B.")
        out = tmp_path / "processed"

        summary = ingest_paths_incremental(paths={f1, f2}, out_dir=out, watch_dir=tmp_path)

        assert summary.processed_count == 2
        ids = [d.sample_id for d in summary.documents if d.status == "processed"]
        assert ids[0] != ids[1], "files from different dirs must have distinct sample_ids"
        # Their output directories must also be distinct.
        dirs = [d.output_dir for d in summary.documents if d.status == "processed"]
        assert dirs[0] != dirs[1], "output directories must be distinct"

    def test_concurrent_state_writes_merge_not_overwrite(self, tmp_path: Path):
        """Two threads ingesting different files must not lose each other's state."""
        import threading

        f1 = _write_md(tmp_path / "a.md", "# A\n\nContent A.")
        f2 = _write_md(tmp_path / "b.md", "# B\n\nContent B.")
        out = tmp_path / "processed"

        errors: list[Exception] = []

        def ingest(path: Path) -> None:
            try:
                ingest_paths_incremental(paths={path}, out_dir=out)
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=ingest, args=(f1,))
        t2 = threading.Thread(target=ingest, args=(f2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"threads raised: {errors}"

        import json
        state = json.loads((out / "ingest-state.json").read_text())
        docs = state.get("documents", {})
        assert str(f1.resolve()) in docs, "f1 must be in merged state"
        assert str(f2.resolve()) in docs, "f2 must be in merged state"
