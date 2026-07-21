#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

show_usage() {
    cat <<'USAGE'
用法:
  ./scripts/run-feishu-knowledge-chain.sh [options]

选项:
  --root-dir PATH            指定一个知识库输入根目录，可重复传入
  --processed-dir PATH       指定输出 processed 目录
  --artifact-root PATH       指定中间产物目录，默认 /tmp/akh-feishu-chain
  --smoke-query TEXT         指定 Layer2 冒烟问题
  --skip-prepare             跳过 inventory / ingest / quality / validate
  --skip-smoke               跳过 layer2-run 冒烟校验
  --top-k N                  冒烟检索 top-k，默认 8
  --per-document-limit N     冒烟每文档上限，默认 2
  --max-files N              inventory 最大文件数，默认 30
  --max-file-mb N            inventory 单文件大小上限，默认 100
  --sample-size N            inventory 采样数，默认 8
  -h, --help                 显示帮助

说明:
  该脚本会先把知识库链路跑通：inventory -> manifest ingest -> parse-quality-summary -> validate-processed -> layer2-run。
  通过后再委托给 scripts/start-feishu-bot.sh 启动本地 API 和飞书长连接机器人。
USAGE
}

ROOT_DIRS=()
PROCESSED_DIR=""
ARTIFACT_ROOT="${AKH_ARTIFACT_ROOT:-/tmp/akh-feishu-chain}"
DEFAULT_PROCESSED_DIR="$PROJECT_ROOT/qnx-knowledge/processed"
SMOKE_QUERY="${AKH_SMOKE_QUERY:-QNX 里有哪些可用的调试工具和 demo？}"
SKIP_PREPARE=0
SKIP_SMOKE=0
TOP_K="${AKH_TOP_K:-8}"
PER_DOCUMENT_LIMIT="${AKH_PER_DOCUMENT_LIMIT:-2}"
MAX_FILES="${AKH_MAX_FILES:-30}"
MAX_FILE_MB="${AKH_MAX_FILE_MB:-100}"
SAMPLE_SIZE="${AKH_SAMPLE_SIZE:-8}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root-dir)
            ROOT_DIRS+=("${2:-}")
            shift 2
            ;;
        --processed-dir)
            PROCESSED_DIR="${2:-}"
            shift 2
            ;;
        --artifact-root)
            ARTIFACT_ROOT="${2:-}"
            shift 2
            ;;
        --smoke-query)
            SMOKE_QUERY="${2:-}"
            shift 2
            ;;
        --skip-prepare)
            SKIP_PREPARE=1
            shift
            ;;
        --skip-smoke)
            SKIP_SMOKE=1
            shift
            ;;
        --top-k)
            TOP_K="${2:-}"
            shift 2
            ;;
        --per-document-limit)
            PER_DOCUMENT_LIMIT="${2:-}"
            shift 2
            ;;
        --max-files)
            MAX_FILES="${2:-}"
            shift 2
            ;;
        --max-file-mb)
            MAX_FILE_MB="${2:-}"
            shift 2
            ;;
        --sample-size)
            SAMPLE_SIZE="${2:-}"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            show_usage >&2
            exit 1
            ;;
    esac
done

if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ -z "${FEISHU_APP_ID:-}" ]]; then
    echo "错误: FEISHU_APP_ID 未设置" >&2
    exit 1
fi

if [[ -z "${FEISHU_APP_SECRET:-}" ]]; then
    echo "错误: FEISHU_APP_SECRET 未设置" >&2
    exit 1
fi

if [[ -n "$PROCESSED_DIR" && ${#ROOT_DIRS[@]} -eq 0 ]]; then
    SKIP_PREPARE=1
fi

sanitize_processed_dir_if_needed() {
    local source_dir="$1"
    local sanitized_dir="$ARTIFACT_ROOT/processed-sanitized"

    python3 - "$source_dir" "$sanitized_dir" <<'PY'
import shutil
import sys
from pathlib import Path

from agent_knowledge_hub.contract import validate_processed_dir

source_dir = Path(sys.argv[1]).resolve()
sanitized_dir = Path(sys.argv[2]).resolve()
summary = validate_processed_dir(source_dir)

if summary.is_valid:
    print(source_dir)
    raise SystemExit(0)

errors = summary.to_dict().get("errors", [])
unsupported = [error for error in errors if error.get("code") != "empty_chunks_jsonl"]
if unsupported:
    for error in errors:
        print(f"ERROR: {error.get('code')} {error.get('path')}", file=sys.stderr)
    raise SystemExit(1)

invalid_version_dirs = {
    str(Path(str(error["path"])).resolve().parent)
    for error in errors
}

if sanitized_dir.exists():
    shutil.rmtree(sanitized_dir)
sanitized_dir.mkdir(parents=True, exist_ok=True)

for child in sorted(source_dir.iterdir()):
    target = sanitized_dir / child.name
    if child.is_file():
        shutil.copy2(child, target)
        continue
    if not child.is_dir():
        continue
    target.mkdir(parents=True, exist_ok=True)
    for version_dir in sorted(child.iterdir()):
        if str(version_dir.resolve()) in invalid_version_dirs:
            continue
        shutil.copytree(version_dir, target / version_dir.name)

print(sanitized_dir)
PY
}

prepare_chain() {
    local inventory_dir="$ARTIFACT_ROOT/inventory"
    local quality_dir="$ARTIFACT_ROOT/quality"
    local layer2_dir="$ARTIFACT_ROOT/layer2-smoke"

    if [[ ${#ROOT_DIRS[@]} -eq 0 ]]; then
        ROOT_DIRS=("$PROJECT_ROOT/samples")
    fi

    if [[ -z "$PROCESSED_DIR" ]]; then
        PROCESSED_DIR="$ARTIFACT_ROOT/processed"
    fi

    mkdir -p "$ARTIFACT_ROOT" "$inventory_dir" "$quality_dir" "$layer2_dir" "$PROCESSED_DIR"

    local inventory_args=(
        -m agent_knowledge_hub.cli
        inventory
        --output-dir "$inventory_dir"
        --max-files "$MAX_FILES"
        --max-file-mb "$MAX_FILE_MB"
        --sample-size "$SAMPLE_SIZE"
        --owner checker
        --project feishu-bot
    )
    local root_dir
    for root_dir in "${ROOT_DIRS[@]}"; do
        inventory_args+=(--root-dir "$root_dir")
    done

    python3 "${inventory_args[@]}"

    local manifest_path="$inventory_dir/raw-docs-sample-manifest.csv"
    python3 -m agent_knowledge_hub.cli manifest \
        --manifest-path "$manifest_path" \
        --out-dir "$PROCESSED_DIR" \
        --project-root "$PROJECT_ROOT" \
        --incremental

    python3 -m agent_knowledge_hub.cli parse-quality-summary \
        --processed-dir "$PROCESSED_DIR" \
        --output-dir "$quality_dir"

    python3 -m agent_knowledge_hub.cli validate-processed \
        --processed-dir "$PROCESSED_DIR" \
        --require-valid

    if [[ $SKIP_SMOKE -eq 0 ]]; then
        python3 -m agent_knowledge_hub.cli layer2-run \
            --processed-dir "$PROCESSED_DIR" \
            --output-dir "$layer2_dir" \
            --query "$SMOKE_QUERY" \
            --top-k "$TOP_K" \
            --per-document-limit "$PER_DOCUMENT_LIMIT" \
            --require-ready
    fi
}

if [[ -z "$PROCESSED_DIR" && ${#ROOT_DIRS[@]} -eq 0 && -d "$DEFAULT_PROCESSED_DIR" ]]; then
    PROCESSED_DIR="$DEFAULT_PROCESSED_DIR"
    SKIP_PREPARE=1
fi

if [[ $SKIP_PREPARE -eq 0 ]]; then
    prepare_chain
fi

if [[ -z "$PROCESSED_DIR" ]]; then
    echo "错误: 未找到可用的 processed 目录，请传 --processed-dir 或提供 --root-dir 触发预处理。" >&2
    exit 1
fi

mkdir -p "$ARTIFACT_ROOT"
PROCESSED_DIR="$(sanitize_processed_dir_if_needed "$PROCESSED_DIR")"

if [[ $SKIP_SMOKE -eq 0 ]]; then
    python3 -m agent_knowledge_hub.cli layer2-run \
        --processed-dir "$PROCESSED_DIR" \
        --output-dir "$ARTIFACT_ROOT/layer2-smoke" \
        --query "$SMOKE_QUERY" \
        --top-k "$TOP_K" \
        --per-document-limit "$PER_DOCUMENT_LIMIT" \
        --require-ready
fi

export PROCESSED_DIR
export LOCAL_API_BASE="${LOCAL_API_BASE:-http://127.0.0.1:8789}"

exec "$SCRIPT_DIR/start-feishu-bot.sh"