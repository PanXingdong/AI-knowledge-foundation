#!/usr/bin/env bash
# Start the local machine as a remote Knowledge Hub server for VS Code clients.
# Usage:
#   ./scripts/start-knowledge-hub-remote.sh
#   ./scripts/start-knowledge-hub-remote.sh --host 0.0.0.0 --port 8787 --knowledge-base-id qnx-main --processed-dir samples/golden --token local-dev-token

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

HOST="0.0.0.0"
PORT="8787"
KNOWLEDGE_BASE_ID="${KNOWLEDGE_BASE_ID:-qnx-main}"
PROCESSED_DIR="${PROCESSED_DIR:-$PROJECT_ROOT/samples/golden}"
TOKEN="${KNOWLEDGE_HUB_API_TOKEN:-local-dev-token}"
FTS_INDEX_PATH="${FTS_INDEX_PATH:-}"
VECTOR_INDEX_PATH="${VECTOR_INDEX_PATH:-}"
DEFAULT_TASK_TYPE="${DEFAULT_TASK_TYPE:-general_query}"
DEFAULT_TOP_K="${DEFAULT_TOP_K:-8}"
DEFAULT_PER_DOCUMENT_LIMIT="${DEFAULT_PER_DOCUMENT_LIMIT:-2}"

print_usage() {
    cat <<'USAGE'
Usage: scripts/start-knowledge-hub-remote.sh [options]

Options:
  --host <host>                         Bind host. Default: 0.0.0.0
  --port <port>                         Bind port. Default: 8787
    --knowledge-base-id <id>              Knowledge base id. Default: $KNOWLEDGE_BASE_ID or qnx-main
    --processed-dir <path>                Processed directory. Default: $PROCESSED_DIR or samples/golden
    --token <token>                       Bearer token. Default: $KNOWLEDGE_HUB_API_TOKEN or local-dev-token
    --fts-index-path <path>               Optional FTS index path. Default: $FTS_INDEX_PATH
    --vector-index-path <path>            Optional vector index path. Default: $VECTOR_INDEX_PATH
    --default-task-type <task_type>       Default task type. Default: $DEFAULT_TASK_TYPE or general_query
    --top-k <n>                           Default top_k. Default: $DEFAULT_TOP_K or 8
    --per-document-limit <n>              Default per_document_limit. Default: $DEFAULT_PER_DOCUMENT_LIMIT or 2
  --no-token                            Disable bearer-token requirement.
  -h, --help                            Show this help.

Environment compatibility:
    This script intentionally reuses the same knowledge settings as Feishu bot:
    PROCESSED_DIR, FTS_INDEX_PATH, VECTOR_INDEX_PATH, DEFAULT_TOP_K,
    DEFAULT_PER_DOCUMENT_LIMIT, DEFAULT_TASK_TYPE.
USAGE
}

port_listener_pids() {
    ss -ltnp 2>/dev/null \
        | awk -v port=":$PORT" '$4 ~ port {
            while (match($0, /pid=[0-9]+/)) {
                print substr($0, RSTART + 4, RLENGTH - 4)
                $0 = substr($0, RSTART + RLENGTH)
            }
        }' \
        | sort -u
}

is_knowledge_hub_server_process() {
    local pid="$1"
    local args
    args="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    [[ "$args" == *"uvicorn"* && "$args" == *"agent_knowledge_hub.service:create_app"* ]]
}

restart_existing_server_if_needed() {
    local pids
    pids="$(port_listener_pids)"
    if [[ -z "$pids" ]]; then
        return
    fi

    local pid
    for pid in $pids; do
        if ! is_knowledge_hub_server_process "$pid"; then
            echo "Error: port $PORT is already in use by a non-Knowledge Hub process (pid $pid)." >&2
            echo "Stop that process or pass --port <another-port>." >&2
            exit 1
        fi
    done

    echo "Existing Knowledge Hub server found on port $PORT: $pids"
    echo "Stopping existing server before restart..."
    for pid in $pids; do
        kill "$pid" 2>/dev/null || true
    done

    for _ in {1..30}; do
        if [[ -z "$(port_listener_pids)" ]]; then
            echo "Previous Knowledge Hub server stopped."
            return
        fi
        sleep 0.2
    done

    echo "Existing Knowledge Hub server did not stop after graceful termination; forcing stop..."
    for pid in $(port_listener_pids); do
        if is_knowledge_hub_server_process "$pid"; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done

    for _ in {1..20}; do
        if [[ -z "$(port_listener_pids)" ]]; then
            echo "Previous Knowledge Hub server force-stopped."
            return
        fi
        sleep 0.2
    done

    echo "Error: port $PORT is still in use after stopping the existing Knowledge Hub server." >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            HOST="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --knowledge-base-id)
            KNOWLEDGE_BASE_ID="$2"
            shift 2
            ;;
        --processed-dir)
            PROCESSED_DIR="$2"
            shift 2
            ;;
        --token)
            TOKEN="$2"
            shift 2
            ;;
        --fts-index-path)
            FTS_INDEX_PATH="$2"
            shift 2
            ;;
        --vector-index-path)
            VECTOR_INDEX_PATH="$2"
            shift 2
            ;;
        --default-task-type)
            DEFAULT_TASK_TYPE="$2"
            shift 2
            ;;
        --top-k)
            DEFAULT_TOP_K="$2"
            shift 2
            ;;
        --per-document-limit)
            DEFAULT_PER_DOCUMENT_LIMIT="$2"
            shift 2
            ;;
        --no-token)
            TOKEN=""
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            print_usage >&2
            exit 2
            ;;
    esac
done

if [[ "$PROCESSED_DIR" != /* ]]; then
    PROCESSED_DIR="$PROJECT_ROOT/$PROCESSED_DIR"
fi

if [[ ! -d "$PROCESSED_DIR" ]]; then
    echo "Error: processed directory does not exist: $PROCESSED_DIR" >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is not available." >&2
    exit 1
fi

restart_existing_server_if_needed

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUTF8="1"
export PYTHONIOENCODING="utf-8"
export KNOWLEDGE_BASE_ID
export PROCESSED_DIR
export FTS_INDEX_PATH
export VECTOR_INDEX_PATH
export DEFAULT_TASK_TYPE
export DEFAULT_TOP_K
export DEFAULT_PER_DOCUMENT_LIMIT

if [[ -n "$TOKEN" ]]; then
    export KNOWLEDGE_HUB_API_TOKEN="$TOKEN"
else
    unset KNOWLEDGE_HUB_API_TOKEN || true
fi

export KNOWLEDGE_BASES_JSON="$($(
    command -v python3
) - <<PY
import json
import os

entry = {
    "processed_dir": os.environ["PROCESSED_DIR"],
    "default_task_type": os.environ["DEFAULT_TASK_TYPE"],
    "default_top_k": int(os.environ["DEFAULT_TOP_K"]),
    "default_per_document_limit": int(os.environ["DEFAULT_PER_DOCUMENT_LIMIT"]),
}
if os.environ.get("FTS_INDEX_PATH"):
    entry["fts_index_path"] = os.environ["FTS_INDEX_PATH"]
if os.environ.get("VECTOR_INDEX_PATH"):
    entry["vector_index_path"] = os.environ["VECTOR_INDEX_PATH"]
print(json.dumps({"knowledge_bases": {os.environ["KNOWLEDGE_BASE_ID"]: entry}}, ensure_ascii=False))
PY
)"

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

cat <<INFO
========================================
Knowledge Hub remote server
========================================
Project root:        $PROJECT_ROOT
Knowledge base id:  $KNOWLEDGE_BASE_ID
Processed dir:      $PROCESSED_DIR
FTS index path:     ${FTS_INDEX_PATH:-<none>}
Vector index path:  ${VECTOR_INDEX_PATH:-<none>}
Bind:               $HOST:$PORT
Local URL:          http://127.0.0.1:$PORT
LAN URL:            ${LAN_IP:+http://$LAN_IP:$PORT}
Token required:     $(if [[ -n "$TOKEN" ]]; then echo yes; else echo no; fi)

VS Code settings example:
{
  "knowledgeHub.baseUrl": "${LAN_IP:+http://$LAN_IP:$PORT}",
  "knowledgeHub.token": "$TOKEN",
  "knowledgeHub.defaultKnowledgeBaseId": "$KNOWLEDGE_BASE_ID"
}
========================================
INFO

exec python3 -m uvicorn agent_knowledge_hub.service:create_app --factory --host "$HOST" --port "$PORT"
