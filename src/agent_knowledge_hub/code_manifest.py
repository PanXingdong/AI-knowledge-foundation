"""
code_manifest.py — 扫描源码仓并生成知识库接入清单。

提供两套接口：
  - scan_repo() / write_csv()         旧接口，保持向后兼容
  - scan_repo_with_snapshot()         Phase A 接口，返回 (RepositorySnapshot, list[FileRecord])
  - scan_repo_full()                  Phase A 完整接口，另外返回 Chunk 和 Evidence 列表
"""
from __future__ import annotations

import csv
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from agent_knowledge_hub.code_chunker import (
    FALLBACK_OVERLAP,
    FALLBACK_WINDOW,
    MAX_CHUNK_LINES,
    CodeChunk,
    chunk_source_file,
)
from agent_knowledge_hub.code_evidence import EvidenceRecord, attach_evidence
from agent_knowledge_hub.code_snapshot import (
    FileRecord,
    RepositorySnapshot,
    SnapshotState,
    _git_file_bytes,
    _is_worktree_dirty,
    create_file_record,
    create_snapshot,
)
from agent_knowledge_hub.utils import write_json, write_jsonl

_log = logging.getLogger(__name__)

# 分块策略常量：纳入 index_config_hash，分块参数变更时 snapshot_id 也会变化
_CHUNK_PARAMS: dict[str, Any] = {
    "max_chunk_lines": MAX_CHUNK_LINES,
    "fallback_window": FALLBACK_WINDOW,
    "fallback_overlap": FALLBACK_OVERLAP,
}

# 默认排除的目录名（任意层级命中即跳过）
# 与 code_watcher.DEFAULT_EXCLUDE_DIRS 保持一致，并额外排除 IDE/隐藏目录
DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset({
    # 第三方大体积目录
    "KanziEngine",
    "someip",
    "ClusterHMIPrebuilts",
    # VCS / 工具
    ".git",
    ".github",
    ".claude",
    ".vscode",
    ".lingma",
    # 构建产物
    "__pycache__",
    "node_modules",
    "build",
    ".tmp",
    # 项目特定
    "video_frames",
})

# 要扫描的文件扩展名
TARGET_EXTENSIONS: frozenset[str] = frozenset({
    ".c", ".cc", ".cpp", ".cxx",
    ".h", ".hh", ".hpp", ".hxx", ".inl",
    ".py", ".sh", ".cmake", ".mk",
    ".json", ".yaml", ".yml", ".xml",
    ".md",
})

# 模块目录 → supplier 映射
_SUPPLIER_MAP: dict[str, str] = {
    "ClusterFunctionService":        "PATAC",
    "ClusterHMIFramework":           "PATAC",
    "Cluster":                       "PATAC",
    "PeekInScreensHMIBuickFreeform": "PATAC",
    "WallpaperHMIBuickFreeform":     "PATAC",
    "SafetyIconHMI":                 "PATAC",
    "libfsa":                        "PATAC",
    "buildCentralProject":           "PATAC",
    "qnx_kb":                        "PATAC",
    "tools":                         "PATAC",
    "someip":                        "unknown",
    "KanziEngine":                   "Rightware",
}

CSV_FIELDNAMES = [
    "sample_id", "file_path", "document_title",
    "slot_type", "owner", "project", "supplier", "document_version",
]


def get_repo_version(repo_dir: Path) -> str:
    """
    返回代码仓版本标识：优先用 git 短哈希，不可用时 fallback 到
    目录内容的聚合哈希前 8 位，保证永远有意义的版本号。
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return f"git-{result.stdout.strip()}"
    except Exception:
        pass

    # Fallback：用仓库路径的哈希作为稳定标识
    digest = hashlib.sha256(str(repo_dir.resolve()).encode()).hexdigest()[:8]
    return f"repo-{digest}"


def _make_sample_id(rel_path: Path) -> str:
    """用相对路径的 SHA256 前 8 位作为唯一 sample_id。"""
    digest = hashlib.sha256(rel_path.as_posix().encode()).hexdigest()[:8]
    return f"code-{digest}"


def _infer_supplier(rel_parts: tuple[str, ...]) -> str:
    if rel_parts:
        return _SUPPLIER_MAP.get(rel_parts[0], "unknown")
    return "unknown"


def _should_exclude(rel_parts: tuple[str, ...], exclude_dirs: frozenset[str]) -> bool:
    return any(part in exclude_dirs for part in rel_parts)


def scan_repo(
    repo_dir: Path,
    exclude_dirs: frozenset[str] | None = None,
    extensions: frozenset[str] | None = None,
) -> list[dict[str, str]]:
    """
    扫描 repo_dir，返回符合条件的文件行（dict 列表，字段与 CSV_FIELDNAMES 对应）。
    """
    _exclude = exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDE_DIRS
    _exts = extensions if extensions is not None else TARGET_EXTENSIONS
    document_version = get_repo_version(repo_dir)

    repo_root = repo_dir.resolve()
    rows: list[dict[str, str]] = []
    for file_path in sorted(repo_root.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in _exts:
            continue
        # Reject symlinks that point outside the repo to prevent accidental
        # inclusion of files from outside the expected boundary.
        if file_path.is_symlink():
            real = file_path.resolve()
            try:
                real.relative_to(repo_root)
            except ValueError:
                import logging as _log
                _log.getLogger(__name__).warning(
                    "跳过仓库外 symlink：%s -> %s", file_path, real
                )
                continue
        rel = file_path.relative_to(repo_root)
        rel_parts = rel.parts
        if _should_exclude(rel_parts, _exclude):
            continue

        module = rel_parts[0] if rel_parts else "unknown"
        rows.append({
            "sample_id":        _make_sample_id(rel),
            # 使用相对路径而非绝对路径，使 CSV 可跨机器复用
            "file_path":        rel.as_posix(),
            "document_title":   rel.as_posix(),
            "slot_type":        "source_code",
            "owner":            "PATAC",
            "project":          f"ClusterHMI/{module}",
            "supplier":         _infer_supplier(rel_parts),
            "document_version": document_version,
        })
    return rows


def write_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    """将 scan_repo 结果写入 CSV 文件。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Phase A 内部：单文件扫描（含脏工作树保护）
# ---------------------------------------------------------------------------

def _read_file_content(
    abs_path: Path,
    repo_dir: Path,
    commit_sha: str,
    use_git: bool,
) -> bytes | None:
    """
    读取文件内容字节。
    - use_git=True：从 git show 读取 commit 版本，避免脏工作树污染证据
    - use_git=False：直接读磁盘（工作树干净或无 git 时）
    """
    if use_git:
        rel_posix = abs_path.relative_to(repo_dir).as_posix()
        data = _git_file_bytes(repo_dir, commit_sha, rel_posix)
        if data is None:
            _log.warning("git show 失败，降级读磁盘：%s", rel_posix)
        return data  # None 表示降级后由调用方处理
    return None  # 返回 None → create_file_record 读磁盘


# ---------------------------------------------------------------------------
# Phase A 新接口：返回 RepositorySnapshot + FileRecord 列表
# ---------------------------------------------------------------------------

def scan_repo_with_snapshot(
    repo_dir: Path,
    exclude_dirs: frozenset[str] | None = None,
    extensions: frozenset[str] | None = None,
    parent_snapshot_id: str | None = None,
) -> tuple[RepositorySnapshot, list[FileRecord]]:
    """
    扫描 repo_dir，返回 (RepositorySnapshot, list[FileRecord])。

    脏工作树保护：若 git 可用且工作树有未提交修改，
    自动通过 git show 读取 commit 版本内容，
    确保 FileRecord.content_hash 与 commit_sha 对应的内容一致。

    扫描顺序确定（sorted），保证相同仓库产出顺序一致。
    """
    _exclude = exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDE_DIRS
    _exts    = extensions    if extensions    is not None else TARGET_EXTENSIONS

    repo_dir = Path(repo_dir).resolve()
    snapshot = create_snapshot(
        repo_dir,
        exclude_dirs=_exclude,
        extensions=_exts,
        parent_snapshot_id=parent_snapshot_id,
        chunk_params=_CHUNK_PARAMS,
    )

    # 检测脏工作树：若 git 可用且有未提交变更，从 git 读内容
    is_git = not snapshot.commit_sha.startswith("no-git-")
    use_git = is_git and _is_worktree_dirty(repo_dir)
    if use_git:
        _log.warning(
            "工作树有未提交修改，将从 git commit %s 读取文件内容以保证证据真实性",
            snapshot.commit_sha[:12],
        )

    file_records: list[FileRecord] = []
    for abs_path in sorted(repo_dir.rglob("*")):
        if not abs_path.is_file():
            continue
        if abs_path.suffix.lower() not in _exts:
            continue

        # Symlink 越界检测
        if abs_path.is_symlink():
            real = abs_path.resolve()
            try:
                real.relative_to(repo_dir)
            except ValueError:
                _log.warning("跳过仓库外 symlink：%s -> %s", abs_path, real)
                continue

        rel_parts = abs_path.relative_to(repo_dir).parts
        if _should_exclude(rel_parts, _exclude):
            continue

        source_bytes = _read_file_content(abs_path, repo_dir, snapshot.commit_sha, use_git)
        file_records.append(create_file_record(abs_path, repo_dir, snapshot, source_bytes=source_bytes))

    return snapshot, file_records


# ---------------------------------------------------------------------------
# Phase A 完整接口：额外返回 Chunk 和 Evidence 列表
# ---------------------------------------------------------------------------

def scan_repo_full(
    repo_dir: Path,
    exclude_dirs: frozenset[str] | None = None,
    extensions: frozenset[str] | None = None,
    parent_snapshot_id: str | None = None,
) -> tuple[RepositorySnapshot, list[FileRecord], list[CodeChunk], list[EvidenceRecord]]:
    """
    扫描 repo_dir，返回 (snapshot, file_records, chunks, evidences)。

    在 scan_repo_with_snapshot() 基础上额外执行：
      - chunk_source_file()：对每个可解析文件生成 CodeChunk 列表
      - attach_evidence()：为所有 Chunk 生成 EvidenceRecord 并回填 evidence_ids

    产物不含本机绝对路径，所有 ID 均为确定性哈希。
    """
    _exclude = exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDE_DIRS
    _exts    = extensions    if extensions    is not None else TARGET_EXTENSIONS

    repo_dir = Path(repo_dir).resolve()
    snapshot = create_snapshot(
        repo_dir,
        exclude_dirs=_exclude,
        extensions=_exts,
        parent_snapshot_id=parent_snapshot_id,
        chunk_params=_CHUNK_PARAMS,
    )

    is_git  = not snapshot.commit_sha.startswith("no-git-")
    use_git = is_git and _is_worktree_dirty(repo_dir)
    if use_git:
        _log.warning(
            "工作树有未提交修改，将从 git commit %s 读取文件内容",
            snapshot.commit_sha[:12],
        )

    file_records: list[FileRecord] = []
    all_chunks:   list[CodeChunk]  = []

    for abs_path in sorted(repo_dir.rglob("*")):
        if not abs_path.is_file():
            continue
        if abs_path.suffix.lower() not in _exts:
            continue

        if abs_path.is_symlink():
            real = abs_path.resolve()
            try:
                real.relative_to(repo_dir)
            except ValueError:
                _log.warning("跳过仓库外 symlink：%s -> %s", abs_path, real)
                continue

        rel_parts = abs_path.relative_to(repo_dir).parts
        if _should_exclude(rel_parts, _exclude):
            continue

        source_bytes = _read_file_content(abs_path, repo_dir, snapshot.commit_sha, use_git)
        fr = create_file_record(abs_path, repo_dir, snapshot, source_bytes=source_bytes)
        file_records.append(fr)

        # 分块：使用 git 内容（source_bytes）或磁盘内容
        if source_bytes is not None and not fr.binary:
            enc = fr.encoding or "utf-8"
            source_text = source_bytes.decode(enc, errors="replace")
        elif not fr.binary:
            enc = fr.encoding or "utf-8"
            try:
                source_text = abs_path.read_text(encoding=enc)
            except (UnicodeDecodeError, LookupError):
                source_text = abs_path.read_text(encoding="latin-1")
        else:
            source_text = None

        if source_text is not None:
            file_chunks = chunk_source_file(fr, source_text)
            all_chunks.extend(file_chunks)

    # 为所有 Chunk 生成 Evidence，并回填 evidence_ids
    evidences, updated_chunks = attach_evidence(all_chunks, snapshot)

    return snapshot, file_records, updated_chunks, evidences


# ---------------------------------------------------------------------------
# 写出产物（原子写，防止残缺目录）
# ---------------------------------------------------------------------------

def write_snapshot_bundle(
    snapshot: RepositorySnapshot,
    file_records: list[FileRecord],
    output_dir: Path,
    chunks: list[CodeChunk] | None = None,
    evidences: list[EvidenceRecord] | None = None,
    *,
    force: bool = False,
) -> dict[str, Path]:
    """
    将 Snapshot 产物写入 output_dir，使用原子写（tmp 目录 + rename）防止残缺。

    输出结构：
      <output_dir>/
        <snapshot_id>/
          repository-snapshot.json
          files.jsonl
          chunks.jsonl      （chunks 非 None 时输出）
          evidences.jsonl   （evidences 非 None 时输出）

    force=True：若 snapshot 目录已存在则覆盖；默认 False 时抛 FileExistsError。
    返回 {key: path} 方便调用方引用各文件路径。
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    snap_dir = output_dir / snapshot.snapshot_id

    if snap_dir.exists() and not force:
        raise FileExistsError(
            f"Snapshot 目录已存在：{snap_dir}。"
            "使用 force=True 覆盖，或删除后重试。"
        )

    # 写入临时目录，完成后原子 rename，防止中断产生残缺目录
    tmp_dir = Path(tempfile.mkdtemp(dir=output_dir, prefix=".tmp_snap_"))
    try:
        write_json(tmp_dir / "repository-snapshot.json", snapshot.to_dict())
        write_jsonl(tmp_dir / "files.jsonl", [fr.to_dict() for fr in file_records])
        if chunks is not None:
            write_jsonl(tmp_dir / "chunks.jsonl", [c.to_dict() for c in chunks])
        if evidences is not None:
            write_jsonl(tmp_dir / "evidences.jsonl", [e.to_dict() for e in evidences])

        # 原子替换：先删旧目录（若存在），再 rename
        if snap_dir.exists():
            shutil.rmtree(snap_dir)
        os.rename(tmp_dir, snap_dir)   # 同文件系统内的原子操作
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    result: dict[str, Path] = {
        "snapshot": snap_dir / "repository-snapshot.json",
        "files":    snap_dir / "files.jsonl",
    }
    if chunks is not None:
        result["chunks"] = snap_dir / "chunks.jsonl"
    if evidences is not None:
        result["evidences"] = snap_dir / "evidences.jsonl"
    return result
