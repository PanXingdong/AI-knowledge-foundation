#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CLUSTER_ROOT="${CLUSTER_ROOT:-/root/qnx-sdk/qnx/vendor/patac/patac-qnx/ClusterHMI}"
PROCESSED_DIR="${PROCESSED_DIR:-$PROJECT_ROOT/qnx-knowledge/processed}"
MANIFEST_PATH="${MANIFEST_PATH:-/tmp/akh-kb-update-manifest.csv}"
REPOS_CSV="${REPOS_CSV:-Cluster,ClusterFunctionService,ClusterHMIFramework,libfsa}"
RESTART_BOT="${RESTART_BOT:-1}"
DRY_RUN="0"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN="1"
            shift
            ;;
        --no-restart)
            RESTART_BOT="0"
            shift
            ;;
        --repos)
            REPOS_CSV="${2:-}"
            shift 2
            ;;
        --cluster-root)
            CLUSTER_ROOT="${2:-}"
            shift 2
            ;;
        --processed-dir)
            PROCESSED_DIR="${2:-}"
            shift 2
            ;;
        *)
            echo "Unknown arg: $1" >&2
            exit 1
            ;;
    esac
done

if [[ ! -d "$CLUSTER_ROOT" ]]; then
    echo "Cluster root not found: $CLUSTER_ROOT" >&2
    exit 1
fi

if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$PROJECT_ROOT/.env"
    set +a
fi

mkdir -p "$PROCESSED_DIR"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export CLUSTER_ROOT PROCESSED_DIR MANIFEST_PATH REPOS_CSV

python3 - <<'PY'
from pathlib import Path
import csv
import os

root = Path(os.environ["CLUSTER_ROOT"]).resolve()
manifest_path = Path(os.environ["MANIFEST_PATH"]).resolve()
repos = [item.strip() for item in os.environ["REPOS_CSV"].split(",") if item.strip()]

code_ext = {
    '.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx', '.inl',
    '.py', '.sh', '.cmake', '.mk', '.java', '.js', '.ts', '.rs', '.proto',
    '.json', '.yaml', '.yml', '.xml', '.md', '.txt'
}
exclude_names = {
    'build', 'build_qnx', 'coverage', '.git', 'node_modules', '3rdparty',
    'prebuilts', 'assets', 'video_frames', '__pycache__', '.lingma', '.github', '.vscode'
}

rows = []
idx = 1
for repo in repos:
    base = root / repo
    if not base.exists() or not base.is_dir():
        continue
    for path in sorted(base.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in exclude_names for part in rel.parts):
            continue
        if path.suffix.lower() not in code_ext:
            continue
        rows.append({
            'sample_id': f'onecmd-{idx:06d}',
            'file_path': rel.as_posix(),
            'document_title': path.name,
            'slot_type': 'project_code',
            'owner': 'patac',
            'project': repo,
            'supplier': 'internal',
            'document_version': 'local',
        })
        idx += 1

manifest_path.parent.mkdir(parents=True, exist_ok=True)
with manifest_path.open('w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(
        f,
        fieldnames=['sample_id', 'file_path', 'document_title', 'slot_type', 'owner', 'project', 'supplier', 'document_version'],
    )
    writer.writeheader()
    writer.writerows(rows)

print(f"manifest={manifest_path}")
print(f"rows={len(rows)}")
PY

if [[ "$DRY_RUN" == "1" ]]; then
    echo "Dry run complete. Manifest only: $MANIFEST_PATH"
    exit 0
fi

python3 -m agent_knowledge_hub.cli manifest \
    --manifest-path "$MANIFEST_PATH" \
    --out-dir "$PROCESSED_DIR" \
    --project-root "$CLUSTER_ROOT" \
    --incremental

if [[ "$RESTART_BOT" == "1" ]]; then
    "$PROJECT_ROOT/scripts/start-feishu-bot.sh"
fi

echo "KB update done."
echo "processed_dir=$PROCESSED_DIR"
echo "manifest=$MANIFEST_PATH"
