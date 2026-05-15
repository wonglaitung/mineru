#!/bin/bash
# 启动 fin-rag 服务
# 用法: ./start_fin_rag.sh

# LLM 配置（请修改为你的实际配置）
export QWEN_API_KEY="${QWEN_API_KEY:-your-api-key}"
export QWEN_CHAT_URL="${QWEN_CHAT_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions}"
export QWEN_CHAT_MODEL="${QWEN_CHAT_MODEL:-qwen-plus-2025-12-01}"
export MAX_TOKENS="${MAX_TOKENS:-32768}"

# Docker 配置
IMAGE_NAME="fin-rag"
CONTAINER_NAME="fin-rag-server"
GPU_MODE="${GPU_MODE:-all}"
HOST_PORT="${HOST_PORT:-8000}"

# 检查镜像是否存在
if ! docker image inspect $IMAGE_NAME &>/dev/null; then
    echo "错误: 镜像 $IMAGE_NAME 不存在"
    echo "请先构建镜像: docker build -t $IMAGE_NAME ."
    exit 1
fi

# 停止并删除旧容器（如果存在）
docker rm -f $CONTAINER_NAME 2>/dev/null

# 启动容器
echo "启动 $IMAGE_NAME 服务..."
docker run -d \
    --gpus $GPU_MODE \
    --name $CONTAINER_NAME \
    -p $HOST_PORT:8000 \
    -e QWEN_API_KEY="$QWEN_API_KEY" \
    -e QWEN_CHAT_URL="$QWEN_CHAT_URL" \
    -e QWEN_CHAT_MODEL="$QWEN_CHAT_MODEL" \
    -e MAX_TOKENS="$MAX_TOKENS" \
    $IMAGE_NAME \
    mineru-api --host 0.0.0.0 --port 8000 --allow-public-http-client

# 检查启动状态
sleep 3
if docker ps | grep -q $CONTAINER_NAME; then
    echo "服务启动成功!"
    echo "API 文档: http://localhost:$HOST_PORT/docs"
    echo "健康检查: http://localhost:$HOST_PORT/health"
else
    echo "服务启动失败，请检查日志:"
    echo "docker logs $CONTAINER_NAME"
    exit 1
fi
