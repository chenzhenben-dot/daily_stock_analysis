#!/usr/bin/env bash
# ------------------------------------------------------------
# OrbStack 本地预发布启动脚本
#
# 约束：
# - 只启动 docker/docker-compose.orbstack.yml 中的服务。
# - 不连接、不修改、不重启任何生产服务器。
# - 不启动 telegram-bot、不启动 cloudflared、不启动 OpenD。
# - 缺真实 API Key 时仍可启动 UI 与 healthcheck。
# ------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.orbstack.yml"
ENV_LOCAL="${REPO_ROOT}/.env.orbstack.local"
ENV_EXAMPLE="${REPO_ROOT}/.env.orbstack.example"

mkdir -p \
  "${REPO_ROOT}/.orbstack/dsa/data" \
  "${REPO_ROOT}/.orbstack/dsa/logs" \
  "${REPO_ROOT}/.orbstack/dsa/reports" \
  "${REPO_ROOT}/.orbstack/er/dashboards" \
  "${REPO_ROOT}/.orbstack/er/logs" \
  "${REPO_ROOT}/.orbstack/er/jobs"

if [[ ! -f "${ENV_LOCAL}" ]]; then
  echo "[orbstack-up] ${ENV_LOCAL} 不存在，从示例复制占位文件"
  cp "${ENV_EXAMPLE}" "${ENV_LOCAL}"
fi

cd "${REPO_ROOT}"

echo "[orbstack-up] docker compose config 校验"
docker compose -f "${COMPOSE_FILE}" config >/dev/null

echo "[orbstack-up] 构建并启动 dsa-local / er-local"
docker compose -f "${COMPOSE_FILE}" up -d --build

echo "[orbstack-up] 状态："
docker compose -f "${COMPOSE_FILE}" ps

echo "[orbstack-up] 访问地址："
echo "  DSA  : http://127.0.0.1:18088/"
echo "  ER   : http://127.0.0.1:18080/"