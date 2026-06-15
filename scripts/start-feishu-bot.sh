#!/bin/bash
# 启动飞书Bot（官方SDK长连接方式）
# 用法: ./start-feishu-bot.sh

set -e

# 配置
export PYTHONPATH="/home/xyd/AI-knowledge-foundation/AI-knowledge-foundation/src"
export FEISHU_APP_ID="cli_aaa3b8fe933a5ccc"
export FEISHU_APP_SECRET="wCkxgMrneywL8A6uYfM9chdCLBDrazRQ"
export PROCESSED_DIR="/home/xyd/AI-knowledge-foundation/AI-knowledge-foundation/.tmp_demo_processed"
export FEISHU_API_BASE="https://open.feishu.cn/open-apis"

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
