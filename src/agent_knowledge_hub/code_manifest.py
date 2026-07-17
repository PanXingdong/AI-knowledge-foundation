"""
code_manifest.py — 扫描源码仓并生成知识库接入清单 CSV。

可作为模块导入，也可通过 CLI 的 generate-code-manifest 命令调用。
"""
from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path

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
