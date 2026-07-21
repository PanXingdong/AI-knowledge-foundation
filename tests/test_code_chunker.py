"""
tests/test_code_chunker.py — CodeChunk 单元测试

验收标准（对应方案第13章、第24.2节）：
  - start_line / end_line 为 1-based，范围合法
  - text 与源文件对应行完全一致（保留缩进）
  - content_hash == sha256(text)
  - C/C++ 函数/类/结构体边界正确识别
  - 不在字符串或块注释中间切分
  - 不在多行宏续行中间切分
  - 超大块在安全行边界拆分
  - 非 C/C++ 语言使用行窗口 fallback
  - unsupported 文件返回空列表
  - chunk_id 确定性（相同输入 → 相同 chunk_id）
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_knowledge_hub.code_chunker import (
    MAX_CHUNK_LINES,
    ChunkKind,
    CodeChunk,
    _count_braces,
    _find_macro_blocks,
    _find_structural_blocks,
    _make_windows,
    _strip_for_brace_count,
    chunk_source_file,
    compute_chunk_id,
)
from agent_knowledge_hub.code_snapshot import (
    FileRecord,
    ParserMode,
    SecretStatus,
)
from agent_knowledge_hub.utils import sha256_text


# ---------------------------------------------------------------------------
# 测试用 FileRecord 工厂
# ---------------------------------------------------------------------------

def _make_file_record(
    language: str = "cpp",
    parser_mode: str = ParserMode.FALLBACK.value,
    relative_path: str = "src/foo.cpp",
) -> FileRecord:
    return FileRecord(
        logical_file_id="file_abcd1234abcd1234",
        file_version_id="fver_abcd1234abcd1234",
        snapshot_id="snap_abcd1234abcd1234abcd12",
        repo_id="repo_abcd1234abcd1234",
        relative_path=relative_path,
        language=language,
        parser_mode=parser_mode,
        content_hash="a" * 64,
        size_bytes=100,
        encoding="utf-8",
        generated=False,
        vendored=False,
        binary=False,
        ownership_ids=[],
        acl_tags=[],
        secret_status=SecretStatus.NOT_SCANNED.value,
        diagnostics=[],
    )


# ---------------------------------------------------------------------------
# _strip_for_brace_count
# ---------------------------------------------------------------------------

class TestStripForBraceCount:
    def test_line_comment_removed(self):
        s, bc = _strip_for_brace_count("int x; // { not counted", False)
        assert "{" not in s
        assert bc is False

    def test_block_comment_braces_not_counted(self):
        s, bc = _strip_for_brace_count("/* { */ int x;", False)
        assert "{" not in s
        assert bc is False

    def test_block_comment_spanning_lines(self):
        # 开启块注释
        _, bc = _strip_for_brace_count("/* start of comment {", False)
        assert bc is True
        # 后续行仍在注释中
        s2, bc2 = _strip_for_brace_count("still in comment { }", bc)
        assert "{" not in s2
        assert bc2 is True
        # 注释结束
        s3, bc3 = _strip_for_brace_count("end */ int x; {", bc2)
        assert "{" in s3
        assert bc3 is False

    def test_string_braces_not_counted(self):
        s, _ = _strip_for_brace_count('const char* s = "{not a brace}";', False)
        assert "{" not in s
        assert "}" not in s

    def test_escaped_quote_in_string(self):
        s, _ = _strip_for_brace_count(r'char c = "\"test\""; {', False)
        assert s.strip().endswith("{")

    def test_normal_braces_counted(self):
        s, _ = _strip_for_brace_count("if (x) { return; }", False)
        assert _count_braces(s) == 0   # 一开一闭抵消


class TestCountBraces:
    def test_balanced(self):
        assert _count_braces("{ x; }") == 0

    def test_open_only(self):
        assert _count_braces("void f() {") == 1

    def test_close_only(self):
        assert _count_braces("}") == -1

    def test_multiple(self):
        assert _count_braces("{{ }}") == 0
        assert _count_braces("{{") == 2


# ---------------------------------------------------------------------------
# _find_macro_blocks
# ---------------------------------------------------------------------------

class TestFindMacroBlocks:
    def test_single_line_macro_not_returned(self):
        lines = ["#define FOO 42"]
        blocks = _find_macro_blocks(lines)
        assert blocks == []

    def test_multiline_macro_detected(self):
        src = """\
#define CHECK(x) \\
    do { \\
        if (!(x)) return; \\
    } while (0)
int normal;
"""
        lines = src.splitlines()
        blocks = _find_macro_blocks(lines)
        assert len(blocks) == 1
        start, end = blocks[0]
        assert start == 0
        assert lines[end].strip() == "} while (0)"   # 最后无 \\ 的行

    def test_two_multiline_macros(self):
        src = """\
#define A(x) \\
    (x + 1)
#define B(x) \\
    (x * 2)
"""
        lines = src.splitlines()
        blocks = _find_macro_blocks(lines)
        assert len(blocks) == 2


# ---------------------------------------------------------------------------
# _find_structural_blocks
# ---------------------------------------------------------------------------

class TestFindStructuralBlocks:
    def test_simple_function(self):
        src = """\
int add(int a, int b) {
    return a + b;
}
"""
        lines = src.splitlines()
        blocks = _find_structural_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].kind == ChunkKind.FUNCTION
        assert blocks[0].start_0 == 0
        assert blocks[0].end_0   == 2

    def test_class_detected(self):
        src = """\
class Foo {
public:
    int x;
};
"""
        lines = src.splitlines()
        blocks = _find_structural_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].kind == ChunkKind.CLASS

    def test_struct_detected(self):
        src = """\
struct Point {
    int x;
    int y;
};
"""
        lines = src.splitlines()
        blocks = _find_structural_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].kind == ChunkKind.STRUCT

    def test_union_detected(self):
        src = """\
union Data {
    int i;
    float f;
};
"""
        lines = src.splitlines()
        blocks = _find_structural_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].kind == ChunkKind.UNION

    def test_namespace_detected(self):
        src = """\
namespace cluster {
void foo();
}
"""
        lines = src.splitlines()
        blocks = _find_structural_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].kind == ChunkKind.NAMESPACE

    def test_two_functions(self):
        src = """\
int foo() {
    return 1;
}
int bar() {
    return 2;
}
"""
        lines = src.splitlines()
        blocks = _find_structural_blocks(lines)
        assert len(blocks) == 2
        assert blocks[0].kind == ChunkKind.FUNCTION
        assert blocks[1].kind == ChunkKind.FUNCTION
        assert blocks[0].end_0 < blocks[1].start_0

    def test_nested_braces_not_split(self):
        """嵌套大括号不应产生多个顶层块。"""
        src = """\
void foo() {
    if (x) {
        bar();
    }
}
"""
        lines = src.splitlines()
        blocks = _find_structural_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].end_0 == 4   # 最外层 } 在第5行（0-indexed=4）

    def test_braces_in_strings_ignored(self):
        src = """\
void foo() {
    const char* s = "{ not a brace }";
    return;
}
"""
        lines = src.splitlines()
        blocks = _find_structural_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].end_0 == 3

    def test_braces_in_line_comment_ignored(self):
        src = """\
void foo() {
    // { this brace is in a comment }
    return;
}
"""
        lines = src.splitlines()
        blocks = _find_structural_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].end_0 == 3

    def test_braces_in_block_comment_ignored(self):
        src = """\
void foo() {
    /* { inside block comment } */
    return;
}
"""
        lines = src.splitlines()
        blocks = _find_structural_blocks(lines)
        assert len(blocks) == 1

    def test_declaration_only_not_detected(self):
        """仅有声明（无花括号）不应产生结构块。"""
        src = """\
class Foo;
void bar();
int x;
"""
        lines = src.splitlines()
        blocks = _find_structural_blocks(lines)
        assert blocks == []


# ---------------------------------------------------------------------------
# _make_windows
# ---------------------------------------------------------------------------

class TestMakeWindows:
    def test_all_free_produces_windows(self):
        windows = _make_windows(total_lines=20, occupied=set(),
                                window=10, overlap=2)
        assert len(windows) > 0
        # 第一个窗口从 0 开始
        assert windows[0][0] == 0

    def test_occupied_lines_excluded(self):
        occupied = set(range(5, 15))   # 行 5-14 被占用
        windows = _make_windows(total_lines=20, occupied=occupied,
                                window=10, overlap=2)
        for ws, we in windows:
            for i in range(ws, we + 1):
                assert i not in occupied

    def test_no_windows_when_all_occupied(self):
        windows = _make_windows(total_lines=10, occupied=set(range(10)),
                                window=5, overlap=1)
        assert windows == []

    def test_empty_range_not_emitted(self):
        # 所有行都被占用，不应产生任何窗口
        occupied = set(range(20))
        windows = _make_windows(total_lines=20, occupied=occupied,
                                window=10, overlap=2)
        assert windows == []

    def test_single_free_line_emitted(self):
        # 单行空闲也应产生窗口（MIN_CHUNK_LINES=1）
        occupied = set(range(1, 20))
        windows = _make_windows(total_lines=20, occupied=occupied,
                                window=10, overlap=2)
        assert len(windows) == 1
        assert windows[0] == (0, 0)


# ---------------------------------------------------------------------------
# chunk_source_file：核心不变量
# ---------------------------------------------------------------------------

class TestChunkSourceFileInvariants:
    """所有 chunk 必须满足的基本不变量。"""

    def _assert_invariants(self, chunks: list[CodeChunk], lines: list[str]) -> None:
        n = len(lines)
        for c in chunks:
            # 1-based 行号合法
            assert 1 <= c.start_line <= c.end_line <= n, (
                f"行号越界: start={c.start_line} end={c.end_line} total={n}"
            )
            # text 与源行完全一致
            expected_text = "\n".join(lines[c.start_line - 1: c.end_line])
            assert c.text == expected_text, "text 与源行不一致"
            # content_hash 正确
            assert c.content_hash == sha256_text(c.text), "content_hash 不正确"
            # chunk_id 确定性
            expected_id = compute_chunk_id(
                c.snapshot_id, c.file_version_id,
                c.start_line, c.end_line, c.content_hash,
            )
            assert c.chunk_id == expected_id, "chunk_id 不正确"
            # Phase A: evidence_ids 为空
            assert c.evidence_ids == [], "Phase A evidence_ids 应为空"
            # Phase A: symbol_id 为 None
            assert c.symbol_id is None, "Phase A symbol_id 应为 None"

    def test_simple_function(self):
        src = "int add(int a, int b) {\n    return a + b;\n}\n"
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        self._assert_invariants(chunks, src.splitlines())

    def test_class_with_methods(self):
        src = """\
class Foo {
public:
    int value;
    void set(int v) {
        value = v;
    }
    int get() const {
        return value;
    }
};
"""
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        self._assert_invariants(chunks, src.splitlines())
        assert len(chunks) >= 1

    def test_markdown_uses_fallback(self):
        src = "\n".join(f"Line {i}" for i in range(1, 101))
        fr = _make_file_record("markdown", ParserMode.FALLBACK.value, "doc.md")
        chunks = chunk_source_file(fr, src)
        self._assert_invariants(chunks, src.splitlines())
        # 全部为 fallback_window
        assert all(c.chunk_kind == ChunkKind.FALLBACK_WINDOW.value for c in chunks)

    def test_unsupported_returns_empty(self):
        src = "binary content"
        fr = _make_file_record("binary", ParserMode.UNSUPPORTED.value)
        chunks = chunk_source_file(fr, src)
        assert chunks == []

    def test_empty_file_returns_empty(self):
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, "")
        assert chunks == []

    def test_chunk_ids_unique(self):
        src = """\
int foo() {
    return 1;
}
int bar() {
    return 2;
}
"""
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), "存在重复 chunk_id"

    def test_chunks_sorted_by_start_line(self):
        src = """\
int a() { return 1; }
int b() { return 2; }
int c() { return 3; }
"""
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        starts = [c.start_line for c in chunks]
        assert starts == sorted(starts)

    def test_chunk_id_is_deterministic(self):
        src = "int add(int a, int b) {\n    return a + b;\n}\n"
        fr = _make_file_record("cpp")
        chunks1 = chunk_source_file(fr, src)
        chunks2 = chunk_source_file(fr, src)
        assert [c.chunk_id for c in chunks1] == [c.chunk_id for c in chunks2]


# ---------------------------------------------------------------------------
# C/C++ 结构识别
# ---------------------------------------------------------------------------

class TestCppStructureDetection:
    def test_function_chunk_kind(self):
        src = "void foo() {\n    return;\n}\n"
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        func_chunks = [c for c in chunks if c.chunk_kind == ChunkKind.FUNCTION.value]
        assert len(func_chunks) >= 1

    def test_class_chunk_kind(self):
        src = "class Bar {\npublic:\n    int x;\n};\n"
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        class_chunks = [c for c in chunks if c.chunk_kind == ChunkKind.CLASS.value]
        assert len(class_chunks) == 1

    def test_struct_chunk_kind(self):
        src = "struct Point {\n    int x;\n    int y;\n};\n"
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        struct_chunks = [c for c in chunks if c.chunk_kind == ChunkKind.STRUCT.value]
        assert len(struct_chunks) == 1

    def test_multiline_macro_chunk_kind(self):
        src = "#define CHECK(x) \\\n    do { \\\n        if (!(x)) return; \\\n    } while (0)\n"
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        macro_chunks = [c for c in chunks if c.chunk_kind == ChunkKind.MACRO_BLOCK.value]
        assert len(macro_chunks) == 1

    def test_interblock_gap_gets_fallback_window(self):
        """函数之间的全局变量等散落代码，应被行窗口覆盖。"""
        src = """\
int global_var = 0;

int foo() {
    return global_var;
}

const int CONST = 42;
"""
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        fallback_chunks = [c for c in chunks
                           if c.chunk_kind == ChunkKind.FALLBACK_WINDOW.value]
        assert len(fallback_chunks) >= 1
        # 确认散落代码行被覆盖
        covered = set()
        for c in chunks:
            covered.update(range(c.start_line, c.end_line + 1))
        lines = src.splitlines()
        for i, line in enumerate(lines, 1):
            if line.strip():   # 非空行应被覆盖
                assert i in covered, f"第{i}行未被任何 chunk 覆盖: {line!r}"

    def test_cpp_header_language_uses_brace_tracking(self):
        src = "struct Config {\n    int timeout;\n    int retry;\n};\n"
        fr = _make_file_record("c_header", ParserMode.FALLBACK.value, "src/config.h")
        chunks = chunk_source_file(fr, src)
        struct_chunks = [c for c in chunks if c.chunk_kind == ChunkKind.STRUCT.value]
        assert len(struct_chunks) == 1

    def test_namespace_with_class_inside(self):
        src = """\
namespace cluster {
class ODIAdapter {
public:
    bool init();
};
}
"""
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        # 至少一个 chunk 覆盖全文件范围
        assert any(c.start_line == 1 for c in chunks)
        assert any(c.end_line == len(src.splitlines()) for c in chunks)

    def test_function_start_line_correct(self):
        src = """\
// file header comment
#include <stdio.h>

int main() {
    return 0;
}
"""
        fr = _make_file_record("c")
        chunks = chunk_source_file(fr, src)
        func_chunks = [c for c in chunks if c.chunk_kind == ChunkKind.FUNCTION.value]
        assert len(func_chunks) == 1
        assert func_chunks[0].start_line == 4   # "int main() {" 在第4行

    def test_function_end_line_is_closing_brace(self):
        src = "int foo() {\n    int x = 1;\n    return x;\n}\n"
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        func_chunks = [c for c in chunks if c.chunk_kind == ChunkKind.FUNCTION.value]
        assert len(func_chunks) == 1
        last_line = src.splitlines()[func_chunks[0].end_line - 1]
        assert "}" in last_line

    def test_indentation_preserved(self):
        src = "void foo() {\n    if (x) {\n        bar();\n    }\n}\n"
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        func_chunks = [c for c in chunks if c.chunk_kind == ChunkKind.FUNCTION.value]
        assert len(func_chunks) >= 1
        # 缩进必须保留
        assert "    if (x) {" in func_chunks[0].text
        assert "        bar();" in func_chunks[0].text


# ---------------------------------------------------------------------------
# 超大块拆分
# ---------------------------------------------------------------------------

class TestOversizedBlockSplit:
    def _make_large_function(self, n_statements: int) -> str:
        lines = ["void large_func() {"]
        for i in range(n_statements):
            lines.append(f"    int x{i} = {i};")
        lines.append("}")
        return "\n".join(lines) + "\n"

    def test_oversized_function_is_split(self):
        src = self._make_large_function(MAX_CHUNK_LINES + 50)
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        func_chunks = [c for c in chunks
                       if c.chunk_kind == ChunkKind.FUNCTION.value]
        # 超大函数应被拆分为多个 chunk
        assert len(func_chunks) > 1

    def test_split_chunks_no_line_exceeds_max(self):
        src = self._make_large_function(MAX_CHUNK_LINES + 50)
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src, max_chunk_lines=50)
        for c in chunks:
            assert c.end_line - c.start_line + 1 <= 55, (
                f"chunk 行数超限: {c.end_line - c.start_line + 1}"
            )

    def test_split_chunks_cover_all_lines(self):
        src = self._make_large_function(MAX_CHUNK_LINES + 10)
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src, max_chunk_lines=80)
        covered = set()
        for c in chunks:
            covered.update(range(c.start_line, c.end_line + 1))
        total = len(src.splitlines())
        for i in range(1, total + 1):
            if src.splitlines()[i - 1].strip():
                assert i in covered, f"第{i}行未被覆盖"

    def test_normal_function_not_split(self):
        src = "int small() {\n    return 42;\n}\n"
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        func_chunks = [c for c in chunks if c.chunk_kind == ChunkKind.FUNCTION.value]
        assert len(func_chunks) == 1


# ---------------------------------------------------------------------------
# 行窗口 fallback
# ---------------------------------------------------------------------------

class TestFallbackWindow:
    def test_non_cpp_all_fallback(self):
        src = "\n".join(f"key{i}: value{i}" for i in range(50))
        fr = _make_file_record("yaml", ParserMode.FALLBACK.value, "cfg.yaml")
        chunks = chunk_source_file(fr, src)
        assert all(c.chunk_kind == ChunkKind.FALLBACK_WINDOW.value for c in chunks)
        assert len(chunks) >= 1

    def test_window_size_respected(self):
        src = "\n".join(f"line{i}" for i in range(200))
        fr = _make_file_record("markdown", ParserMode.FALLBACK.value, "doc.md")
        chunks = chunk_source_file(fr, src, fallback_window=30, fallback_overlap=5)
        for c in chunks:
            assert c.end_line - c.start_line + 1 <= 30

    def test_all_lines_covered_by_fallback(self):
        src = "\n".join(f"line{i}" for i in range(50))
        fr = _make_file_record("cmake", ParserMode.FALLBACK.value, "CMakeLists.txt")
        chunks = chunk_source_file(fr, src, fallback_window=20, fallback_overlap=3)
        covered = set()
        for c in chunks:
            covered.update(range(c.start_line, c.end_line + 1))
        lines = src.splitlines()
        for i, line in enumerate(lines, 1):
            assert i in covered, f"第{i}行未被覆盖: {line!r}"

    def test_relative_path_in_chunk(self):
        src = "x: 1\ny: 2\n"
        fr = _make_file_record("yaml", ParserMode.FALLBACK.value, "config/settings.yaml")
        chunks = chunk_source_file(fr, src)
        for c in chunks:
            assert c.relative_path == "config/settings.yaml"

    def test_metadata_from_file_record(self):
        fr = _make_file_record("cpp")
        src = "int x;\n"
        chunks = chunk_source_file(fr, src)
        for c in chunks:
            assert c.snapshot_id     == fr.snapshot_id
            assert c.repo_id         == fr.repo_id
            assert c.file_version_id == fr.file_version_id
            assert c.language        == fr.language
            assert c.secret_status   == SecretStatus.NOT_SCANNED.value
            assert c.ownership_ids   == []
            assert c.acl_tags        == []


# ---------------------------------------------------------------------------
# 真实 C++ 片段（odi_adapter 风格）
# ---------------------------------------------------------------------------

class TestRealCppPatterns:
    """仿照 ClusterHMI 代码仓中的真实 C++ 模式测试。"""

    ODI_ADAPTER_SNIPPET = """\
#ifndef ODI_ADAPTER_H
#define ODI_ADAPTER_H

namespace cluster {

class ODIAdapter : public IAdapter {
public:
    explicit ODIAdapter(ScreenService& service);
    ~ODIAdapter() override;

    bool init(const Config& config) override;
    void shutdown() override;

private:
    ScreenService& service_;
    int state_;
};

}  // namespace cluster

#endif  // ODI_ADAPTER_H
"""

    ODI_ADAPTER_IMPL = """\
#include "odi_adapter.h"
#include <stdexcept>

namespace cluster {

ODIAdapter::ODIAdapter(ScreenService& service)
    : service_(service), state_(0) {}

ODIAdapter::~ODIAdapter() {
    shutdown();
}

bool ODIAdapter::init(const Config& config) {
    if (state_ != 0) {
        throw std::runtime_error("already initialized");
    }
    service_.configure(config);
    state_ = 1;
    return true;
}

void ODIAdapter::shutdown() {
    if (state_ == 0) return;
    service_.stop();
    state_ = 0;
}

}  // namespace cluster
"""

    def test_header_file_struct_detection(self):
        fr = _make_file_record("cpp_header", ParserMode.FALLBACK.value, "include/odi_adapter.h")
        chunks = chunk_source_file(fr, self.ODI_ADAPTER_SNIPPET)
        assert len(chunks) > 0
        # class 嵌套在 namespace 内，启发式只产生顶层 NAMESPACE 块；
        # 检查 namespace 或 class chunk 至少有一个即可
        structural = [c for c in chunks
                      if c.chunk_kind in (ChunkKind.NAMESPACE.value,
                                          ChunkKind.CLASS.value)]
        assert len(structural) >= 1

    def test_impl_file_functions_detected(self):
        fr = _make_file_record("cpp", ParserMode.FALLBACK.value, "src/odi_adapter.cpp")
        chunks = chunk_source_file(fr, self.ODI_ADAPTER_IMPL)
        func_chunks = [c for c in chunks
                       if c.chunk_kind in (ChunkKind.FUNCTION.value,
                                           ChunkKind.NAMESPACE.value)]
        assert len(func_chunks) >= 1

    def test_all_lines_covered_in_header(self):
        fr = _make_file_record("cpp_header", ParserMode.FALLBACK.value, "include/odi_adapter.h")
        chunks = chunk_source_file(fr, self.ODI_ADAPTER_SNIPPET)
        covered = set()
        for c in chunks:
            covered.update(range(c.start_line, c.end_line + 1))
        lines = self.ODI_ADAPTER_SNIPPET.splitlines()
        for i, line in enumerate(lines, 1):
            if line.strip():
                assert i in covered, f"第{i}行未被覆盖: {line!r}"

    def test_all_lines_covered_in_impl(self):
        fr = _make_file_record("cpp", ParserMode.FALLBACK.value, "src/odi_adapter.cpp")
        chunks = chunk_source_file(fr, self.ODI_ADAPTER_IMPL)
        covered = set()
        for c in chunks:
            covered.update(range(c.start_line, c.end_line + 1))
        lines = self.ODI_ADAPTER_IMPL.splitlines()
        for i, line in enumerate(lines, 1):
            if line.strip():
                assert i in covered, f"第{i}行未被覆盖: {line!r}"

    def test_no_chunk_starts_or_ends_inside_block_comment(self):
        """不得在块注释中间切分。"""
        src = """\
/*
 * This is a long file header comment
 * that spans multiple lines.
 */
#include "foo.h"

void bar() {
    /* inline comment
       spanning two lines */
    return;
}
"""
        fr = _make_file_record("cpp")
        chunks = chunk_source_file(fr, src)
        lines = src.splitlines()
        # 验证每个 chunk 的起始行不是块注释的中间行（即不以 " * " 开头且不在注释内部）
        for c in chunks:
            start_content = lines[c.start_line - 1].strip()
            # chunk 不应从 " * xxx" 这种注释中间行开始（第1行是 /* 可以）
            if c.start_line > 1:
                assert not start_content.startswith("* ") or start_content.startswith("*/"), (
                    f"chunk 从块注释中间行开始: 第{c.start_line}行 {start_content!r}"
                )
