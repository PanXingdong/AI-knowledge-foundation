"""
tests/test_code_evidence.py — EvidenceRecord 单元测试

验收标准（对应方案第14章、第24.5节）：
  - evidence.text == chunk.text（Phase A 无脱敏）
  - evidence.text_hash == sha256(evidence.text)
  - evidence.source_text_hash == evidence.text_hash（Phase A）
  - start_line / end_line 与 chunk 一致（1-based）
  - commit_sha 来自 RepositorySnapshot，不含本机路径
  - evidence_id 确定性（相同输入 → 相同结果）
  - 内容变化 → evidence_id 变化
  - attach_evidence 后 chunk.evidence_ids == [evidence_id]
  - 产物不含本机绝对路径
  - 所有 evidence_id 唯一
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from agent_knowledge_hub.code_chunker import (
    ChunkKind,
    CodeChunk,
    chunk_source_file,
    compute_chunk_id,
)
from agent_knowledge_hub.code_evidence import (
    EvidenceRecord,
    attach_evidence,
    compute_evidence_id,
    create_evidence,
)
from agent_knowledge_hub.code_snapshot import (
    FileRecord,
    ParserMode,
    RepositorySnapshot,
    SecretStatus,
    SnapshotState,
)
from agent_knowledge_hub.utils import sha256_text


# ---------------------------------------------------------------------------
# 测试用 Fixture 工厂
# ---------------------------------------------------------------------------

def _make_snapshot(commit_sha: str = "a" * 40) -> RepositorySnapshot:
    return RepositorySnapshot(
        snapshot_id="snap_" + "a" * 24,
        schema_version="code-index.v1",
        repo_id="repo_" + "a" * 16,
        repo_remote="https://git.example.com/repo",
        branch="main",
        commit_sha=commit_sha,
        tree_hash="b" * 40,
        submodule_commits={},
        index_config_hash="c" * 16,
        parser_versions={"fallback": "1.0"},
        parent_snapshot_id=None,
        state=SnapshotState.PLANNED.value,
        created_at="2026-07-21T00:00:00Z",
    )


def _make_file_record(
    language: str = "cpp",
    relative_path: str = "src/foo.cpp",
) -> FileRecord:
    return FileRecord(
        logical_file_id="file_" + "b" * 16,
        file_version_id="fver_" + "b" * 16,
        snapshot_id="snap_" + "a" * 24,
        repo_id="repo_" + "a" * 16,
        relative_path=relative_path,
        language=language,
        parser_mode=ParserMode.FALLBACK.value,
        content_hash="c" * 64,
        size_bytes=200,
        encoding="utf-8",
        generated=False,
        vendored=False,
        binary=False,
        ownership_ids=[],
        acl_tags=[],
        secret_status=SecretStatus.NOT_SCANNED.value,
        diagnostics=[],
    )


def _make_chunk(
    text: str,
    start_line: int = 1,
    end_line: int = 3,
    file_record: FileRecord | None = None,
) -> CodeChunk:
    fr = file_record or _make_file_record()
    content_hash = sha256_text(text)
    chunk_id = compute_chunk_id(
        fr.snapshot_id, fr.file_version_id, start_line, end_line, content_hash
    )
    return CodeChunk(
        chunk_id=chunk_id,
        snapshot_id=fr.snapshot_id,
        repo_id=fr.repo_id,
        file_version_id=fr.file_version_id,
        symbol_id=None,
        chunk_kind=ChunkKind.FUNCTION.value,
        language=fr.language,
        relative_path=fr.relative_path,
        start_line=start_line,
        end_line=end_line,
        text=text,
        content_hash=content_hash,
        evidence_ids=[],
        ownership_ids=[],
        acl_tags=[],
        secret_status=SecretStatus.NOT_SCANNED.value,
        parser_mode=ParserMode.FALLBACK.value,
    )


# ---------------------------------------------------------------------------
# compute_evidence_id
# ---------------------------------------------------------------------------

class TestComputeEvidenceId:
    def test_deterministic(self):
        id1 = compute_evidence_id("snap_aaa", "fver_bbb", 1, 10, "hash_x")
        id2 = compute_evidence_id("snap_aaa", "fver_bbb", 1, 10, "hash_x")
        assert id1 == id2

    def test_prefix(self):
        eid = compute_evidence_id("snap_aaa", "fver_bbb", 1, 10, "hash_x")
        assert eid.startswith("evid_")

    def test_changes_with_text_hash(self):
        id1 = compute_evidence_id("snap_aaa", "fver_bbb", 1, 10, "hash_x")
        id2 = compute_evidence_id("snap_aaa", "fver_bbb", 1, 10, "hash_y")
        assert id1 != id2

    def test_changes_with_start_line(self):
        id1 = compute_evidence_id("snap_aaa", "fver_bbb", 1, 10, "hash_x")
        id2 = compute_evidence_id("snap_aaa", "fver_bbb", 2, 10, "hash_x")
        assert id1 != id2

    def test_changes_with_end_line(self):
        id1 = compute_evidence_id("snap_aaa", "fver_bbb", 1, 10, "hash_x")
        id2 = compute_evidence_id("snap_aaa", "fver_bbb", 1, 11, "hash_x")
        assert id1 != id2

    def test_changes_with_snapshot(self):
        id1 = compute_evidence_id("snap_aaa", "fver_bbb", 1, 10, "hash_x")
        id2 = compute_evidence_id("snap_bbb", "fver_bbb", 1, 10, "hash_x")
        assert id1 != id2

    def test_changes_with_file_version(self):
        id1 = compute_evidence_id("snap_aaa", "fver_bbb", 1, 10, "hash_x")
        id2 = compute_evidence_id("snap_aaa", "fver_ccc", 1, 10, "hash_x")
        assert id1 != id2


# ---------------------------------------------------------------------------
# create_evidence：单条 EvidenceRecord 不变量
# ---------------------------------------------------------------------------

class TestCreateEvidence:
    def test_text_equals_chunk_text(self):
        snap  = _make_snapshot()
        chunk = _make_chunk("int foo() {\n    return 1;\n}")
        ev    = create_evidence(chunk, snap)
        assert ev.text == chunk.text

    def test_text_hash_correct(self):
        snap  = _make_snapshot()
        chunk = _make_chunk("int foo() {\n    return 1;\n}")
        ev    = create_evidence(chunk, snap)
        assert ev.text_hash == sha256_text(ev.text)

    def test_text_hash_is_sha256(self):
        snap  = _make_snapshot()
        chunk = _make_chunk("void bar() {}")
        ev    = create_evidence(chunk, snap)
        assert len(ev.text_hash) == 64
        assert all(c in "0123456789abcdef" for c in ev.text_hash)

    def test_source_text_hash_equals_text_hash_in_phase_a(self):
        """Phase A 无脱敏：source_text_hash == text_hash。"""
        snap  = _make_snapshot()
        chunk = _make_chunk("int x = 42;")
        ev    = create_evidence(chunk, snap)
        assert ev.source_text_hash == ev.text_hash

    def test_line_numbers_match_chunk(self):
        snap  = _make_snapshot()
        chunk = _make_chunk("line1\nline2\nline3", start_line=5, end_line=7)
        ev    = create_evidence(chunk, snap)
        assert ev.start_line == 5
        assert ev.end_line   == 7

    def test_commit_sha_from_snapshot(self):
        commit = "d" * 40
        snap   = _make_snapshot(commit_sha=commit)
        chunk  = _make_chunk("int x;")
        ev     = create_evidence(chunk, snap)
        assert ev.commit_sha == commit

    def test_relative_path_no_absolute(self):
        snap  = _make_snapshot()
        fr    = _make_file_record(relative_path="src/adapter/odi_adapter.cpp")
        chunk = _make_chunk("int x;", file_record=fr)
        ev    = create_evidence(chunk, snap)
        assert not ev.relative_path.startswith("/")
        assert ev.relative_path == "src/adapter/odi_adapter.cpp"

    def test_no_absolute_path_in_serialization(self, tmp_path):
        snap  = _make_snapshot()
        fr    = _make_file_record(relative_path="src/foo.cpp")
        chunk = _make_chunk("int x;", file_record=fr)
        ev    = create_evidence(chunk, snap)
        serialized = json.dumps(ev.to_dict())
        assert str(tmp_path) not in serialized
        # relative_path 不含根目录标志
        assert '"/' not in serialized or '"relative_path": "/' not in serialized

    def test_snapshot_id_matches(self):
        snap  = _make_snapshot()
        chunk = _make_chunk("int x;")
        ev    = create_evidence(chunk, snap)
        assert ev.snapshot_id == chunk.snapshot_id

    def test_file_version_id_matches(self):
        snap  = _make_snapshot()
        chunk = _make_chunk("int x;")
        ev    = create_evidence(chunk, snap)
        assert ev.file_version_id == chunk.file_version_id

    def test_repo_id_matches(self):
        snap  = _make_snapshot()
        chunk = _make_chunk("int x;")
        ev    = create_evidence(chunk, snap)
        assert ev.repo_id == chunk.repo_id

    def test_parser_mode_matches_chunk(self):
        snap  = _make_snapshot()
        chunk = _make_chunk("int x;")
        ev    = create_evidence(chunk, snap)
        assert ev.parser_mode == chunk.parser_mode

    def test_phase_a_fields_are_none_or_empty(self):
        """Phase A：symbol_id/列号为 None，redactions 为空。"""
        snap  = _make_snapshot()
        chunk = _make_chunk("int x;")
        ev    = create_evidence(chunk, snap)
        assert ev.symbol_id    is None
        assert ev.start_column is None
        assert ev.end_column   is None
        assert ev.redactions   == ()

    def test_evidence_id_deterministic(self):
        snap   = _make_snapshot()
        chunk  = _make_chunk("int foo() {\n    return 1;\n}")
        ev1    = create_evidence(chunk, snap)
        ev2    = create_evidence(chunk, snap)
        assert ev1.evidence_id == ev2.evidence_id

    def test_evidence_id_changes_when_text_changes(self):
        snap   = _make_snapshot()
        chunk1 = _make_chunk("int foo() { return 1; }")
        chunk2 = _make_chunk("int foo() { return 2; }")
        ev1    = create_evidence(chunk1, snap)
        ev2    = create_evidence(chunk2, snap)
        assert ev1.evidence_id != ev2.evidence_id

    def test_evidence_id_changes_when_lines_change(self):
        snap   = _make_snapshot()
        text   = "int x;"
        chunk1 = _make_chunk(text, start_line=1, end_line=1)
        chunk2 = _make_chunk(text, start_line=5, end_line=5)
        ev1    = create_evidence(chunk1, snap)
        ev2    = create_evidence(chunk2, snap)
        assert ev1.evidence_id != ev2.evidence_id

    def test_to_dict_is_json_serializable(self):
        snap  = _make_snapshot()
        chunk = _make_chunk("void f() {}")
        ev    = create_evidence(chunk, snap)
        d     = ev.to_dict()
        # 应可直接 JSON 序列化（无 tuple/set 等不可序列化类型）
        serialized = json.dumps(d)
        assert isinstance(serialized, str)

    def test_to_dict_redactions_is_list(self):
        """redactions 在 to_dict() 中必须是 list（JSON 友好）。"""
        snap  = _make_snapshot()
        chunk = _make_chunk("int x;")
        ev    = create_evidence(chunk, snap)
        d     = ev.to_dict()
        assert isinstance(d["redactions"], list)


# ---------------------------------------------------------------------------
# attach_evidence：批量绑定与 chunk 回填
# ---------------------------------------------------------------------------

class TestAttachEvidence:
    def _make_chunks_from_src(self, src: str) -> tuple[list[CodeChunk], FileRecord]:
        fr     = _make_file_record()
        chunks = chunk_source_file(fr, src)
        return chunks, fr

    def test_returns_same_count(self):
        src   = "int foo() {\n    return 1;\n}\nint bar() {\n    return 2;\n}\n"
        fr    = _make_file_record()
        snap  = _make_snapshot()
        chunks = chunk_source_file(fr, src)
        evs, updated = attach_evidence(chunks, snap)
        assert len(evs)     == len(chunks)
        assert len(updated) == len(chunks)

    def test_each_chunk_has_one_evidence_id(self):
        src   = "int foo() {\n    return 1;\n}\n"
        fr    = _make_file_record()
        snap  = _make_snapshot()
        chunks = chunk_source_file(fr, src)
        evs, updated = attach_evidence(chunks, snap)
        for c in updated:
            assert len(c.evidence_ids) == 1

    def test_evidence_id_in_chunk_evidence_ids(self):
        src   = "int x;\nint y;\n"
        fr    = _make_file_record()
        snap  = _make_snapshot()
        chunks = chunk_source_file(fr, src)
        evs, updated = attach_evidence(chunks, snap)
        for ev, c in zip(evs, updated):
            assert ev.evidence_id in c.evidence_ids

    def test_original_chunks_unchanged(self):
        """frozen dataclass：原始 chunks 的 evidence_ids 仍为 []。"""
        src   = "int foo() {\n    return 1;\n}\n"
        fr    = _make_file_record()
        snap  = _make_snapshot()
        original = chunk_source_file(fr, src)
        _evs, _updated = attach_evidence(original, snap)
        for c in original:
            assert c.evidence_ids == []

    def test_all_evidence_ids_unique(self):
        src = "\n".join(
            f"int func_{i}() {{\n    return {i};\n}}" for i in range(10)
        )
        fr   = _make_file_record()
        snap = _make_snapshot()
        chunks = chunk_source_file(fr, src)
        evs, _ = attach_evidence(chunks, snap)
        ids = [ev.evidence_id for ev in evs]
        assert len(ids) == len(set(ids)), "存在重复 evidence_id"

    def test_evidence_text_matches_chunk_text(self):
        src   = "void foo() {\n    bar();\n}\n"
        fr    = _make_file_record()
        snap  = _make_snapshot()
        chunks = chunk_source_file(fr, src)
        evs, updated = attach_evidence(chunks, snap)
        for ev, c in zip(evs, updated):
            assert ev.text == c.text

    def test_evidence_line_numbers_match_chunk(self):
        src   = "int a;\nint b;\nint c;\n"
        fr    = _make_file_record()
        snap  = _make_snapshot()
        chunks = chunk_source_file(fr, src)
        evs, updated = attach_evidence(chunks, snap)
        for ev, c in zip(evs, updated):
            assert ev.start_line == c.start_line
            assert ev.end_line   == c.end_line

    def test_commit_sha_propagated_to_all_evidence(self):
        commit = "e" * 40
        snap   = _make_snapshot(commit_sha=commit)
        src    = "int x;\nint y;\n"
        fr     = _make_file_record()
        chunks = chunk_source_file(fr, src)
        evs, _ = attach_evidence(chunks, snap)
        for ev in evs:
            assert ev.commit_sha == commit

    def test_no_absolute_paths_in_evidence(self):
        snap = _make_snapshot()
        fr   = _make_file_record(relative_path="module/src/impl.cpp")
        src  = "void impl() {\n    return;\n}\n"
        chunks = chunk_source_file(fr, src)
        evs, _ = attach_evidence(chunks, snap)
        for ev in evs:
            assert not ev.relative_path.startswith("/")
            assert ev.relative_path == "module/src/impl.cpp"

    def test_empty_chunks_returns_empty(self):
        snap = _make_snapshot()
        evs, updated = attach_evidence([], snap)
        assert evs    == []
        assert updated == []

    def test_attach_is_deterministic(self):
        """相同输入两次调用，evidence_id 列表完全一致。"""
        src   = "int foo() {\n    return 1;\n}\n"
        fr    = _make_file_record()
        snap  = _make_snapshot()
        chunks = chunk_source_file(fr, src)
        evs1, _ = attach_evidence(chunks, snap)
        evs2, _ = attach_evidence(chunks, snap)
        assert [e.evidence_id for e in evs1] == [e.evidence_id for e in evs2]

    def test_updated_chunks_retain_other_fields(self):
        """attach_evidence 只改 evidence_ids，其他字段不变。"""
        src   = "int foo() {\n    return 1;\n}\n"
        fr    = _make_file_record()
        snap  = _make_snapshot()
        chunks = chunk_source_file(fr, src)
        _evs, updated = attach_evidence(chunks, snap)
        for orig, upd in zip(chunks, updated):
            assert orig.chunk_id        == upd.chunk_id
            assert orig.text            == upd.text
            assert orig.start_line      == upd.start_line
            assert orig.end_line        == upd.end_line
            assert orig.content_hash    == upd.content_hash
            assert orig.chunk_kind      == upd.chunk_kind
            assert orig.snapshot_id     == upd.snapshot_id
            assert orig.file_version_id == upd.file_version_id


# ---------------------------------------------------------------------------
# 端到端：snapshot → file_record → chunks → evidence
# ---------------------------------------------------------------------------

class TestEndToEnd:
    ODI_IMPL = """\
#include "odi_adapter.h"

namespace cluster {

bool ODIAdapter::init(const Config& config) {
    if (state_ != 0) {
        return false;
    }
    state_ = 1;
    return true;
}

void ODIAdapter::shutdown() {
    state_ = 0;
}

}  // namespace cluster
"""

    def test_full_pipeline_produces_evidence_for_all_chunks(self):
        snap   = _make_snapshot()
        fr     = _make_file_record("cpp", "src/odi_adapter.cpp")
        chunks = chunk_source_file(fr, self.ODI_IMPL)
        evs, updated = attach_evidence(chunks, snap)

        assert len(evs) == len(chunks)
        assert all(len(c.evidence_ids) == 1 for c in updated)

    def test_full_pipeline_evidence_text_hash_invariant(self):
        """端到端：text_hash == sha256(text) 对所有证据成立。"""
        snap   = _make_snapshot()
        fr     = _make_file_record("cpp", "src/odi_adapter.cpp")
        chunks = chunk_source_file(fr, self.ODI_IMPL)
        evs, _ = attach_evidence(chunks, snap)

        for ev in evs:
            assert ev.text_hash == sha256_text(ev.text), (
                f"text_hash 不匹配: evidence_id={ev.evidence_id}"
            )

    def test_full_pipeline_source_text_hash_equals_text_hash(self):
        """Phase A 无脱敏：source_text_hash == text_hash。"""
        snap   = _make_snapshot()
        fr     = _make_file_record("cpp", "src/odi_adapter.cpp")
        chunks = chunk_source_file(fr, self.ODI_IMPL)
        evs, _ = attach_evidence(chunks, snap)

        for ev in evs:
            assert ev.source_text_hash == ev.text_hash, (
                f"Phase A source_text_hash 应等于 text_hash: evidence_id={ev.evidence_id}"
            )

    def test_full_pipeline_evidence_covers_all_lines(self):
        """所有非空行都被某条 evidence 覆盖。"""
        snap   = _make_snapshot()
        fr     = _make_file_record("cpp", "src/odi_adapter.cpp")
        chunks = chunk_source_file(fr, self.ODI_IMPL)
        evs, _ = attach_evidence(chunks, snap)

        covered: set[int] = set()
        for ev in evs:
            covered.update(range(ev.start_line, ev.end_line + 1))

        lines = self.ODI_IMPL.splitlines()
        for i, line in enumerate(lines, 1):
            if line.strip():
                assert i in covered, f"第{i}行未被任何 evidence 覆盖: {line!r}"

    def test_full_pipeline_no_absolute_paths(self):
        """序列化后不含本机绝对路径。"""
        snap   = _make_snapshot()
        fr     = _make_file_record("cpp", "src/odi_adapter.cpp")
        chunks = chunk_source_file(fr, self.ODI_IMPL)
        evs, _ = attach_evidence(chunks, snap)

        for ev in evs:
            d = json.dumps(ev.to_dict())
            assert not any(
                d.count(prefix) > 0
                for prefix in ["/root/", "/home/", "/mnt/", "C:\\", "D:\\"]
            ), f"evidence 含绝对路径: {ev.evidence_id}"
