#!/usr/bin/env python3
"""
generate_cluster_manifest.py — 扫描 ClusterHMI 代码仓，生成知识库接入清单 CSV。

用法：
    python scripts/generate_cluster_manifest.py \
        --repo-dir /path/to/ClusterHMI \
        --output   qnx-knowledge/cluster-code-manifest.csv

默认排除第三方体积目录：KanziEngine / someip / ClusterHMIPrebuilts。
可通过 --exclude-dir 追加排除目录。

输出 CSV 字段（与现有清单格式兼容）：
    sample_id, file_path, document_title, slot_type, owner, project, supplier,
    document_version
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import subprocess
import sys
from pathlib import Path

# 默认排除的目录名（任意层级命中即跳过）
DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset({
    "KanziEngine",
    "someip",
    "ClusterHMIPrebuilts",
    ".git",
    ".github",
    ".claude",
    ".vscode",
    "__pycache__",
    "node_modules",
    "build",
    ".tmp",
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

# 模块目录 → supplier 映射（按目录名前缀匹配）
_SUPPLIER_MAP: dict[str, str] = {
    "ClusterFunctionService": "PATAC",
    "ClusterHMIFramework":    "PATAC",
    "Cluster":                "PATAC",
    "PeekInScreensHMIBuickFreeform": "PATAC",
    "WallpaperHMIBuickFreeform":     "PATAC",
    "SafetyIconHMI":          "PATAC",
    "libfsa":                 "PATAC",
    "buildCentralProject":    "PATAC",
    "qnx_kb":                 "PATAC",
    "tools":                  "PATAC",
    "someip":                 "unknown",
    "KanziEngine":            "Rightware",
}


def _git_short_hash(repo_dir: Path) -> str:
    """获取仓库当前 HEAD 的短哈希；失败时返回 'unknown'。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _infer_supplier(rel_parts: tuple[str, ...]) -> str:
    """从相对路径的第一级目录名推断 supplier。"""
    if rel_parts:
        return _SUPPLIER_MAP.get(rel_parts[0], "unknown")
    return "unknown"


def _should_exclude(rel_parts: tuple[str, ...], exclude_dirs: frozenset[str]) -> bool:
    return any(part in exclude_dirs for part in rel_parts)


def _make_sample_id(rel_path: Path) -> str:
    """用相对路径的 SHA256 前 8 位作为唯一 sample_id。"""
    digest = hashlib.sha256(rel_path.as_posix().encode()).hexdigest()[:8]
    return f"code-{digest}"


def scan_repo(
    repo_dir: Path,
    exclude_dirs: frozenset[str],
    extensions: frozenset[str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    git_hash = _git_short_hash(repo_dir)
    document_version = f"git-{git_hash}"

    for file_path in sorted(repo_dir.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in extensions:
            continue
        rel = file_path.relative_to(repo_dir)
        rel_parts = rel.parts
        if _should_exclude(rel_parts, exclude_dirs):
            continue

        module = rel_parts[0] if rel_parts else "unknown"
        supplier = _infer_supplier(rel_parts)
        rows.append({
            "sample_id":       _make_sample_id(rel),
            "file_path":       str(file_path),
            "document_title":  rel.as_posix(),
            "slot_type":       "source_code",
            "owner":           "PATAC",
            "project":         f"ClusterHMI/{module}",
            "supplier":        supplier,
            "document_version": document_version,
        })

    return rows


def write_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sample_id", "file_path", "document_title",
        "slot_type", "owner", "project", "supplier", "document_version",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="扫描 ClusterHMI 代码仓，生成知识库接入清单 CSV。"
    )
    parser.add_argument(
        "--repo-dir", required=True, type=Path,
        help="ClusterHMI 代码仓根目录。",
    )
    parser.add_argument(
        "--output", required=True, type=Path,
        help="输出 CSV 路径，如 qnx-knowledge/cluster-code-manifest.csv。",
    )
    parser.add_argument(
        "--exclude-dir", action="append", dest="extra_excludes", default=[],
        help="追加排除的目录名（可多次指定）。",
    )
    parser.add_argument(
        "--no-default-excludes", action="store_true",
        help="不使用默认排除列表（KanziEngine / someip / ClusterHMIPrebuilts 等）。",
    )
    args = parser.parse_args(argv)

    repo_dir = args.repo_dir.resolve()
    if not repo_dir.is_dir():
        print(f"ERROR: 目录不存在：{repo_dir}", file=sys.stderr)
        return 1

    exclude_dirs = (
        frozenset[str]()
        if args.no_default_excludes
        else DEFAULT_EXCLUDE_DIRS
    ) | frozenset(args.extra_excludes)

    print(f"扫描目录：{repo_dir}")
    print(f"排除目录：{sorted(exclude_dirs)}")

    rows = scan_repo(repo_dir, exclude_dirs, TARGET_EXTENSIONS)
    write_csv(rows, args.output)

    print(f"共扫描 {len(rows)} 个文件 → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
