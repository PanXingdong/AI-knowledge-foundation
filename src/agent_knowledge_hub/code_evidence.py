"""
code_evidence.py — Phase A 代码行号证据（EvidenceRecord）

职责：
  - 为每个 CodeChunk 生成可回溯到 repo+commit+文件+行号 的 EvidenceRecord
  - 将 evidence_id 写回 CodeChunk.evidence_ids（返回新实例，原实例不变）
  - Phase A：text 不做脱敏，text_hash == source_text_hash，redactions == []
  - Phase D：SecurityEnricher 会更新 text（脱敏后）并填充 redactions

不变量（对应方案第14章）：
  - evidence.text 与 chunk.text 完全一致（Phase A 无脱敏）
  - evidence.text_hash == sha256(evidence.text)
  - evidence.source_text_hash == sha256(chunk 对应的源文件原始文本)
  - 行号范围与 chunk 一致（start_line / end_line 均为 1-based）
  - commit_sha 来自 RepositorySnapshot，不含本机路径
  - 每个 chunk 恰好对应一条 evidence（Phase A 1:1 关系）

对应方案文档：第14章、第27.8节
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import asdict, dataclass
from typing import Any

from agent_knowledge_hub.code_chunker import CodeChunk
from agent_knowledge_hub.code_snapshot import ParserMode, RepositorySnapshot, _sha256_of
from agent_knowledge_hub.utils import sha256_text

# ---------------------------------------------------------------------------
# EvidenceRecord 数据类（对应方案第27.8节）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRecord:
    """
    单条代码证据，将 Chunk 锚定到 repo + commit + 文件 + 行号范围。

    Phase A 说明：
      - text 与 chunk.text 相同（未脱敏）
      - text_hash == source_text_hash（无脱敏时两者相同）
      - redactions == []（Phase D 填充）
      - symbol_id == None（Phase B 填充）
      - start_column / end_column == None（Phase B 细化）
    """
    evidence_id:      str
    snapshot_id:      str
    repo_id:          str
    commit_sha:       str          # 完整 40 位 SHA，来自 RepositorySnapshot
    relative_path:    str          # POSIX 相对路径，无绝对路径
    file_version_id:  str
    symbol_id:        str | None   # Phase B 填充
    start_line:       int          # 1-based，与 CodeChunk 一致
    end_line:         int          # 1-based，与 CodeChunk 一致
    start_column:     int | None   # Phase B 细化
    end_column:       int | None   # Phase B 细化
    text:             str          # 安全处理后的源码文本（Phase A 与原文相同）
    text_hash:        str          # sha256(text)
    source_text_hash: str          # sha256(chunk 对应源文件原始范围)
                                   # Phase A: == text_hash；Phase D 脱敏后可能不同
    parser_mode:      str          # 与来源 FileRecord.parser_mode 一致
    redactions:       tuple[dict[str, Any], ...]  # Phase A 为 ()，Phase D 填充脱敏位置

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["redactions"] = list(d["redactions"])   # tuple → list 便于 JSON 序列化
        return d


# ---------------------------------------------------------------------------
# ID 计算
# ---------------------------------------------------------------------------


def compute_evidence_id(
    snapshot_id:     str,
    file_version_id: str,
    start_line:      int,
    end_line:        int,
    text_hash:       str,
) -> str:
    """
    确定性 evidence_id：相同输入必然产生相同结果。
    text_hash 参与计算，确保同一行范围在内容变化后 ID 也变化。
    """
    obj = {
        "snapshot_id":     snapshot_id,
        "file_version_id": file_version_id,
        "start_line":      start_line,
        "end_line":        end_line,
        "text_hash":       text_hash,
    }
    return "evid_" + _sha256_of(obj)[:20]


# ---------------------------------------------------------------------------
# 工厂：单条 EvidenceRecord
# ---------------------------------------------------------------------------


def create_evidence(
    chunk:    CodeChunk,
    snapshot: RepositorySnapshot,
) -> EvidenceRecord:
    """
    为单个 CodeChunk 生成对应的 EvidenceRecord。

    Phase A 规则：
      - text = chunk.text（无脱敏）
      - text_hash = source_text_hash = sha256(chunk.text)
      - redactions = ()
    """
    text             = chunk.text
    text_hash        = sha256_text(text)
    source_text_hash = text_hash          # Phase A：无脱敏，两者相同

    evidence_id = compute_evidence_id(
        snapshot_id=chunk.snapshot_id,
        file_version_id=chunk.file_version_id,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        text_hash=text_hash,
    )

    return EvidenceRecord(
        evidence_id=evidence_id,
        snapshot_id=chunk.snapshot_id,
        repo_id=chunk.repo_id,
        commit_sha=snapshot.commit_sha,
        relative_path=chunk.relative_path,
        file_version_id=chunk.file_version_id,
        symbol_id=None,               # Phase B 填充
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        start_column=None,            # Phase B 细化
        end_column=None,              # Phase B 细化
        text=text,
        text_hash=text_hash,
        source_text_hash=source_text_hash,
        parser_mode=chunk.parser_mode,
        redactions=(),                # Phase D 填充
    )


# ---------------------------------------------------------------------------
# 批量绑定：chunk → evidence，回填 evidence_ids
# ---------------------------------------------------------------------------


def attach_evidence(
    chunks:   list[CodeChunk],
    snapshot: RepositorySnapshot,
) -> tuple[list[EvidenceRecord], list[CodeChunk]]:
    """
    为 chunks 批量生成 EvidenceRecord，并返回填充了 evidence_ids 的新 CodeChunk 列表。

    由于 CodeChunk 是 frozen dataclass，通过 dataclasses.replace() 生成新实例。

    返回：
      (evidence_records, updated_chunks)

    不变量：
      - len(evidence_records) == len(updated_chunks) == len(chunks)
      - updated_chunks[i].evidence_ids == [evidence_records[i].evidence_id]
      - 所有 evidence_id 全局唯一（相同 chunk 内容 + snapshot → 相同 evidence_id）
    """
    evidence_records: list[EvidenceRecord] = []
    updated_chunks:   list[CodeChunk]      = []

    for chunk in chunks:
        ev = create_evidence(chunk, snapshot)
        evidence_records.append(ev)
        # frozen dataclass 用 dataclasses.replace() 返回新实例
        updated_chunk = dataclasses.replace(
            chunk,
            evidence_ids=[ev.evidence_id],
        )
        updated_chunks.append(updated_chunk)

    return evidence_records, updated_chunks
