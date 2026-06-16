#!/bin/bash
# 启动飞书Bot（官方SDK长连接方式）
# 用法: ./start-feishu-bot.sh

set -e

# 定位项目根目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 自动加载本地 .env 文件（如果存在）
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

export PYTHONPATH="$PROJECT_ROOT/src"

# 校验必要环境变量
if [ -z "$FEISHU_APP_ID" ]; then
    echo "错误: FEISHU_APP_ID 未设置"
    echo "请在项目根目录创建 .env 文件，或手动 export FEISHU_APP_ID"
    exit 1
fi

if [ -z "$FEISHU_APP_SECRET" ]; then
    echo "错误: FEISHU_APP_SECRET 未设置"
    echo "请在项目根目录创建 .env 文件，或手动 export FEISHU_APP_SECRET"
    exit 1
fi

# 设置默认值
: "${FEISHU_API_BASE:=https://open.feishu.cn/open-apis}"
: "${LOCAL_API_BASE:=http://127.0.0.1:8789}"
: "${PROCESSED_DIR:=$PROJECT_ROOT/.tmp_demo_processed}"

API_PORT=8789
API_LOG="/tmp/uvicorn.log"
BOT_LOG="/tmp/feishu_bot.log"

echo "=================================="
echo "启动飞书Bot（官方SDK长连接方式）"
echo "=================================="
echo "App ID: $FEISHU_APP_ID"
echo "API端口: $API_PORT"
echo "Bot日志: $BOT_LOG"
echo ""

# 1. 停止旧进程
echo "停止旧进程..."
pkill -f "feishu_bot_sdk" 2>/dev/null || true
pkill -f "uvicorn.*service:create_app" 2>/dev/null || true
sleep 2

# 2. 确保processed目录存在
mkdir -p "$PROCESSED_DIR"

# 3. 启动本地API服务
echo "启动本地API服务..."
nohup python3 -m uvicorn agent_knowledge_hub.service:create_app --factory --host 127.0.0.1 --port $API_PORT > "$API_LOG" 2>&1 &
API_PID=$!
sleep 3

# 检查API是否启动成功
if ! ss -tlnp 2>/dev/null | grep -q ":$API_PORT "; then
    echo "API服务启动失败，请检查日志:"
    tail -n 20 "$API_LOG"
    exit 1
fi
echo "API服务已启动 (端口 $API_PORT)"
echo ""

# 4. 启动Bot
echo "启动Bot..."
nohup python3 -m agent_knowledge_hub.feishu_bot_sdk > "$BOT_LOG" 2>&1 &
sleep 3

# 检查Bot启动状态
if ps aux | grep "feishu_bot_sdk" | grep -v grep > /dev/null; then
    echo "Bot启动成功!"
    echo ""
    echo "查看Bot日志:"
    tail -n 5 "$BOT_LOG"
    echo ""
    echo "实时查看Bot日志: tail -f $BOT_LOG"
    echo "实时查看API日志: tail -f $API_LOG"
else
    echo "Bot启动失败，请检查日志:"
    tail -n 20 "$BOT_LOG"
    exit 1
fi
