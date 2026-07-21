#!/usr/bin/env bash
# ------------------------------------------------------------
# OrbStack 本地预发布停止脚本
#
# 约束：
# - 只停止本地 OrbStack compose 服务，不触碰生产。
# - 不删除 .orbstack/ 下的数据、日志、报告。
# - 不重启 Moomoo OpenD、不重启 cloudflared、不重启任何生产容器。
# ------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.orbstack.yml"

cd "${REPO_ROOT}"
echo "[orbstack-down] 停止 dsa-local / er-local"
docker compose -f "${COMPOSE_FILE}" down

echo "[orbstack-down] 数据保留在 .orbstack/ 下，未清理"