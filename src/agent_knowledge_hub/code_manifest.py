"""
code_manifest.py — 扫描源码仓并生成知识库接入清单。

提供两套接口：
  - scan_repo() / write_csv()         旧接口，保持向后兼容
  - scan_repo_with_snapshot()         新接口（Phase A），返回 RepositorySnapshot
                                       + list[FileRecord]，产物不含绝对路径
"""
from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path

from agent_knowledge_hub.code_snapshot import (
    FileRecord,
    RepositorySnapshot,
    SnapshotState,
    create_file_record,
    create_snapshot,
)
from agent_knowledge_hub.utils import write_json, write_jsonl

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

    与旧 scan_repo() 的区别：
      - 产物中不含本机绝对路径（relative_path 为 POSIX 相对路径）
      - snapshot_id 由 repo+commit+config 哈希确定，相同输入必然相同
      - FileRecord 携带 logical_file_id / file_version_id / language /
        parser_mode / content_hash / generated / vendored 等结构化字段

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
    )

    file_records: list[FileRecord] = []
    for abs_path in sorted(repo_dir.rglob("*")):
        if not abs_path.is_file():
            continue
        if abs_path.suffix.lower() not in _exts:
            continue
        rel_parts = abs_path.relative_to(repo_dir).parts
        if _should_exclude(rel_parts, _exclude):
            continue

        file_records.append(create_file_record(abs_path, repo_dir, snapshot))

    return snapshot, file_records


def write_snapshot_bundle(
    snapshot: RepositorySnapshot,
    file_records: list[FileRecord],
    output_dir: Path,
) -> dict[str, Path]:
    """
    将 RepositorySnapshot 和 FileRecord 列表写入 output_dir。

    输出结构：
      <output_dir>/
        <snapshot_id>/
          repository-snapshot.json
          files.jsonl

    返回 {key: path} 方便调用方引用各文件路径。
    """
    snap_dir = Path(output_dir) / snapshot.snapshot_id
    snap_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = snap_dir / "repository-snapshot.json"
    files_path    = snap_dir / "files.jsonl"

    write_json(snapshot_path, snapshot.to_dict())
    write_jsonl(files_path, [fr.to_dict() for fr in file_records])

    return {
        "snapshot": snapshot_path,
        "files":    files_path,
    }
