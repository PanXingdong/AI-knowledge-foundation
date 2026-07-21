"""
code_chunker.py — Phase A 行号保留代码分块器

策略（对应方案第13章）：
  C/C++ 语言：大括号跟踪 + 上下文启发式识别函数/类/宏块边界
  其他语言  ：行窗口 fallback

Phase B 将用 Tree-sitter AST 替换启发式层，CodeChunk 数据结构不变。

输出不变量：
  - start_line / end_line 为 1-based，范围合法
  - text 与源文件对应行完全一致（保留缩进）
  - content_hash == sha256(text)
  - 不在字符串字面量或块注释中间切分
  - 不在多行宏 (\\续行) 中间切分
  - 超大块在安全行边界拆分，每个子块保留 parent_symbol_hint

对应方案文档：第13章、第27.7节
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from agent_knowledge_hub.code_snapshot import FileRecord, ParserMode, SecretStatus, _sha256_of
from agent_knowledge_hub.utils import sha256_text

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

MAX_CHUNK_LINES     = 200   # 单个结构块超过此行数时拆分
FALLBACK_WINDOW     = 80    # 行窗口大小（fallback 模式）
FALLBACK_OVERLAP    = 10    # 行窗口重叠行数
MIN_CHUNK_LINES     = 1     # 行窗口最小行数；设为 1 确保所有非空行都被覆盖

# 使用大括号跟踪的语言集合
_BRACE_LANGUAGES: frozenset[str] = frozenset({
    "c", "cpp", "c_header", "cpp_header", "java", "javascript", "typescript",
})

# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class ChunkKind(str, Enum):
    FUNCTION        = "function"
    CLASS           = "class"
    STRUCT          = "struct"
    UNION           = "union"
    MACRO_BLOCK     = "macro_block"
    NAMESPACE       = "namespace"
    FALLBACK_WINDOW = "fallback_window"


# ---------------------------------------------------------------------------
# CodeChunk 数据类（对应方案第27.7节）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CodeChunk:
    chunk_id:        str
    snapshot_id:     str
    repo_id:         str
    file_version_id: str
    symbol_id:       str | None   # Phase B 填充；Phase A 为 None
    chunk_kind:      str          # ChunkKind 值
    language:        str
    relative_path:   str
    start_line:      int          # 1-based
    end_line:        int          # 1-based
    text:            str          # 保留缩进的原始源码
    content_hash:    str          # sha256(text)
    evidence_ids:    list[str]    # Phase A-3 填充；Phase A 为 []
    ownership_ids:   list[str]
    acl_tags:        list[str]
    secret_status:   str          # SecretStatus 值
    parser_mode:     str          # ParserMode 值

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_chunk_id(
    snapshot_id: str,
    file_version_id: str,
    start_line: int,
    end_line: int,
    content_hash: str,
) -> str:
    obj = {
        "snapshot_id":     snapshot_id,
        "file_version_id": file_version_id,
        "start_line":      start_line,
        "end_line":        end_line,
        "content_hash":    content_hash,
    }
    return "chunk_" + _sha256_of(obj)[:20]


# ---------------------------------------------------------------------------
# 内部：源码行分析工具
# ---------------------------------------------------------------------------

# 多行宏：以 # 开头（跳过空白）且行尾有 \ 续行符
_MACRO_DEF_RE  = re.compile(r"^\s*#\s*define\b")
_MACRO_CONT_RE = re.compile(r"\\\s*$")

# 块前缀关键字，用于判断 { 块的类型
_CLASS_KW_RE    = re.compile(r"\bclass\b")
_STRUCT_KW_RE   = re.compile(r"\bstruct\b")
_UNION_KW_RE    = re.compile(r"\bunion\b")
_NAMESPACE_KW_RE= re.compile(r"\bnamespace\b")


def _strip_for_brace_count(line: str, in_block_comment: bool) -> tuple[str, bool]:
    """
    从一行文本中去除字符串字面量、行注释和块注释内容后返回"净化"文本，
    同时更新块注释状态。净化后的文本只用于大括号计数，不影响原始 text。
    """
    out: list[str] = []
    i = 0
    n = len(line)

    while i < n:
        if in_block_comment:
            if line[i:i+2] == "*/":
                in_block_comment = False
                i += 2
            else:
                i += 1
        else:
            if line[i:i+2] == "//":
                break                      # 行注释，后续全部忽略
            if line[i:i+2] == "/*":
                in_block_comment = True
                i += 2
                continue
            if line[i] in ('"', "'"):
                quote = line[i]
                i += 1
                while i < n:
                    if line[i] == "\\" and i + 1 < n:
                        i += 2             # 转义字符跳过
                        continue
                    if line[i] == quote:
                        i += 1
                        break
                    i += 1
                continue
            out.append(line[i])
            i += 1

    return "".join(out), in_block_comment


def _count_braces(stripped: str) -> int:
    """净化行中 { 计 +1，} 计 -1，返回差值。"""
    return stripped.count("{") - stripped.count("}")


# ---------------------------------------------------------------------------
# 内部：C/C++ 宏块检测
# ---------------------------------------------------------------------------

def _find_macro_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """
    返回多行宏块的行范围列表，格式 [(start_0, end_0), ...]（0-indexed，含两端）。
    单行 #define 不纳入（长度 < MIN_CHUNK_LINES）。
    """
    blocks: list[tuple[int, int]] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _MACRO_DEF_RE.match(line) and _MACRO_CONT_RE.search(line):
            start = i
            while i < n and _MACRO_CONT_RE.search(lines[i]):
                i += 1
            end = i  # 最后一行（无 \ 续行符）
            if end - start + 1 >= 2:   # 多行宏至少 2 行（含 #define 行和续行）
                blocks.append((start, end))
        else:
            i += 1
    return blocks


# ---------------------------------------------------------------------------
# 内部：C/C++ 大括号结构块检测
# ---------------------------------------------------------------------------

@dataclass
class _RawBlock:
    start_0: int        # 0-indexed 起始行（含）
    end_0:   int        # 0-indexed 结束行（含，即 } 所在行）
    kind:    ChunkKind


def _classify_block(lines: list[str], block_start_0: int) -> ChunkKind:
    """
    根据 block_start_0 前几行的关键字猜测块类型。
    查看范围：block_start_0 往前最多 5 行，找到第一个含关键字的行。
    """
    look_back = lines[max(0, block_start_0 - 4): block_start_0 + 1]
    # 从最近的行往前找
    for raw in reversed(look_back):
        text = raw
        if _NAMESPACE_KW_RE.search(text):
            return ChunkKind.NAMESPACE
        if _CLASS_KW_RE.search(text):
            return ChunkKind.CLASS
        if _STRUCT_KW_RE.search(text):
            return ChunkKind.STRUCT
        if _UNION_KW_RE.search(text):
            return ChunkKind.UNION
    return ChunkKind.FUNCTION


def _find_structural_blocks(lines: list[str]) -> list[_RawBlock]:
    """
    用大括号跟踪识别顶层结构块（深度 0→1→0）。
    返回 _RawBlock 列表，不含宏块（宏块由 _find_macro_blocks 处理）。
    """
    blocks: list[_RawBlock] = []
    n = len(lines)
    depth = 0
    block_start: int | None = None
    in_block_comment = False

    for i, raw_line in enumerate(lines):
        # 多行宏不参与大括号跟踪
        if _MACRO_DEF_RE.match(raw_line):
            continue

        stripped, in_block_comment = _strip_for_brace_count(raw_line, in_block_comment)
        delta = _count_braces(stripped)

        if depth == 0 and delta > 0:
            block_start = i
            depth += delta
        elif depth > 0:
            depth += delta
            if depth <= 0:
                depth = 0
                if block_start is not None:
                    blocks.append(_RawBlock(
                        start_0=block_start,
                        end_0=i,
                        kind=_classify_block(lines, block_start),
                    ))
                    block_start = None

    return blocks


# ---------------------------------------------------------------------------
# 内部：超大块拆分
# ---------------------------------------------------------------------------

def _split_oversized(
    lines: list[str],
    block: _RawBlock,
    max_lines: int,
) -> list[tuple[int, int]]:
    """
    将超大块在"安全行"处拆分，返回子范围列表 [(start_0, end_0), ...]。
    安全行：大括号深度为 1 且行以 ; 或 } 结尾（语句边界）。
    拆分后每段长度目标 ≤ max_lines，但保证整块被覆盖。
    """
    start = block.start_0
    end   = block.end_0
    total = end - start + 1

    if total <= max_lines:
        return [(start, end)]

    # 找深度=1 的安全分割点（相对于 block 内部）
    safe_points: list[int] = []
    depth = 0
    in_bc = False
    for i in range(start, end + 1):
        stripped, in_bc = _strip_for_brace_count(lines[i], in_bc)
        depth += _count_braces(stripped)
        if depth == 1 and stripped.rstrip().endswith((";", "}")):
            safe_points.append(i)

    if not safe_points:
        # 无安全点则按行数强切（最后手段）
        ranges: list[tuple[int, int]] = []
        cur = start
        while cur <= end:
            seg_end = min(cur + max_lines - 1, end)
            ranges.append((cur, seg_end))
            cur = seg_end + 1
        return ranges

    # 按 safe_points 切分，每段 ≤ max_lines
    ranges = []
    seg_start = start
    for sp in safe_points:
        if sp - seg_start + 1 >= max_lines:
            ranges.append((seg_start, sp))
            seg_start = sp + 1
    if seg_start <= end:
        ranges.append((seg_start, end))
    return ranges


# ---------------------------------------------------------------------------
# 内部：行窗口 fallback
# ---------------------------------------------------------------------------

def _make_windows(
    total_lines: int,
    occupied: set[int],
    window: int,
    overlap: int,
) -> list[tuple[int, int]]:
    """
    对 occupied 以外的行生成非重叠行窗口。
    返回 [(start_0, end_0), ...]，每段均不含已被结构块占用的行。
    """
    # 找到未被占用的连续区间
    free_ranges: list[tuple[int, int]] = []
    in_free = False
    seg_start = 0
    for i in range(total_lines):
        if i not in occupied:
            if not in_free:
                seg_start = i
                in_free = True
        else:
            if in_free:
                free_ranges.append((seg_start, i - 1))
                in_free = False
    if in_free:
        free_ranges.append((seg_start, total_lines - 1))

    windows: list[tuple[int, int]] = []
    for (fr_start, fr_end) in free_ranges:
        cur = fr_start
        while cur <= fr_end:
            win_end = min(cur + window - 1, fr_end)
            if win_end - cur + 1 >= MIN_CHUNK_LINES:
                windows.append((cur, win_end))
            # 下一窗口从 (win_end - overlap + 1) 开始，但不后退
            next_start = win_end - overlap + 1
            if next_start <= cur:
                next_start = cur + 1
            cur = next_start
            if win_end == fr_end:
                break

    return windows


# ---------------------------------------------------------------------------
# 内部：CodeChunk 构建
# ---------------------------------------------------------------------------

def _make_chunk(
    lines: list[str],
    start_0: int,
    end_0: int,
    kind: ChunkKind,
    file_record: FileRecord,
    parent_symbol_hint: str | None = None,
) -> CodeChunk:
    """从行范围构建 CodeChunk（1-based 行号，保留原始缩进）。"""
    chunk_lines = lines[start_0: end_0 + 1]
    text = "\n".join(chunk_lines)
    content_hash = sha256_text(text)
    start_line = start_0 + 1
    end_line   = end_0   + 1

    chunk_id = compute_chunk_id(
        file_record.snapshot_id,
        file_record.file_version_id,
        start_line,
        end_line,
        content_hash,
    )

    return CodeChunk(
        chunk_id=chunk_id,
        snapshot_id=file_record.snapshot_id,
        repo_id=file_record.repo_id,
        file_version_id=file_record.file_version_id,
        symbol_id=parent_symbol_hint,   # Phase B 将填入真实 symbol_id
        chunk_kind=kind.value,
        language=file_record.language,
        relative_path=file_record.relative_path,
        start_line=start_line,
        end_line=end_line,
        text=text,
        content_hash=content_hash,
        evidence_ids=[],                # Phase A-3 填充
        ownership_ids=list(file_record.ownership_ids),
        acl_tags=list(file_record.acl_tags),
        secret_status=file_record.secret_status,
        parser_mode=file_record.parser_mode,
    )


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------

def chunk_source_file(
    file_record: FileRecord,
    source_text: str,
    *,
    max_chunk_lines: int = MAX_CHUNK_LINES,
    fallback_window:  int = FALLBACK_WINDOW,
    fallback_overlap: int = FALLBACK_OVERLAP,
) -> list[CodeChunk]:
    """
    对单个源文件执行代码分块，返回 CodeChunk 列表（按 start_line 升序）。

    - C/C++ 文件：大括号跟踪识别函数/类/结构体 + 多行宏，行窗口填充空隙
    - 其他语言  ：全部使用行窗口 fallback
    - parser_mode=unsupported 的文件：直接返回 []

    不变量：
      - 所有 chunk 的 start_line/end_line 落在文件行范围内
      - text 完全对应源文件对应行（保留缩进）
      - content_hash == sha256(text)
    """
    if file_record.parser_mode == ParserMode.UNSUPPORTED.value:
        return []

    # 按行拆分，保留空行（维持行号一致性）
    lines: list[str] = source_text.splitlines()
    if not lines:
        return []

    n = len(lines)
    chunks: list[CodeChunk] = []
    occupied: set[int] = set()   # 已被结构块覆盖的行 (0-indexed)

    use_brace_tracking = file_record.language in _BRACE_LANGUAGES

    if use_brace_tracking:
        # --- 多行宏块 ---
        for (ms, me) in _find_macro_blocks(lines):
            for (ss, se) in _split_oversized(
                lines,
                _RawBlock(ms, me, ChunkKind.MACRO_BLOCK),
                max_chunk_lines,
            ):
                chunks.append(_make_chunk(lines, ss, se, ChunkKind.MACRO_BLOCK, file_record))
                occupied.update(range(ss, se + 1))

        # --- 结构块（函数/类/命名空间等）---
        raw_blocks = _find_structural_blocks(lines)
        for rb in raw_blocks:
            for (ss, se) in _split_oversized(lines, rb, max_chunk_lines):
                hint = None if rb.kind in (ChunkKind.CLASS, ChunkKind.STRUCT,
                                            ChunkKind.UNION, ChunkKind.NAMESPACE) else None
                chunks.append(_make_chunk(lines, ss, se, rb.kind, file_record, hint))
                occupied.update(range(ss, se + 1))

    # --- 行窗口：填充空隙（或全文件，当非 C/C++ 时）---
    for (ws, we) in _make_windows(n, occupied, fallback_window, fallback_overlap):
        chunks.append(_make_chunk(lines, ws, we, ChunkKind.FALLBACK_WINDOW, file_record))

    # 按 start_line 排序，相同则按 end_line
    chunks.sort(key=lambda c: (c.start_line, c.end_line))
    return chunks


def chunk_source_file_from_path(
    file_record: FileRecord,
    abs_path: Path,
    **kwargs: Any,
) -> list[CodeChunk]:
    """
    从磁盘路径读取源文件后调用 chunk_source_file()。
    编码回退顺序与 FileRecord.encoding 一致。
    """
    encoding = file_record.encoding or "utf-8"
    try:
        text = abs_path.read_text(encoding=encoding)
    except (UnicodeDecodeError, LookupError):
        text = abs_path.read_text(encoding="latin-1")
    return chunk_source_file(file_record, text, **kwargs)
