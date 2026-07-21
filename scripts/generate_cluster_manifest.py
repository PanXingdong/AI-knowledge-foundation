#!/usr/bin/env python3
"""
generate_cluster_manifest.py — 扫描 ClusterHMI 代码仓，生成知识库接入清单 CSV。

用法：
    python scripts/generate_cluster_manifest.py \
        --repo-dir /path/to/ClusterHMI \
        --output   qnx-knowledge/cluster-code-manifest.csv

核心逻辑在 agent_knowledge_hub.code_manifest 中，本脚本仅作命令行入口。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 将 src/ 加入路径，兼容未安装包的直接运行场景
_HERE = Path(__file__).parent.parent / "src"
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from agent_knowledge_hub.code_manifest import (
    DEFAULT_EXCLUDE_DIRS,
    TARGET_EXTENSIONS,
    scan_repo,
    write_csv,
)


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
        frozenset[str]() if args.no_default_excludes else DEFAULT_EXCLUDE_DIRS
    ) | frozenset(args.extra_excludes)

    print(f"扫描目录：{repo_dir}")
    print(f"排除目录：{sorted(exclude_dirs)}")

    rows = scan_repo(repo_dir, exclude_dirs, TARGET_EXTENSIONS)
    write_csv(rows, args.output)

    print(f"共扫描 {len(rows)} 个文件 → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
