#!/usr/bin/env bash
# ------------------------------------------------------------
# OrbStack 本地预发布 smoke test
#
# 检查项：
# 1. 容器在运行。
# 2. DSA health 接口可达。
# 3. ER 首页可达。
# 4. 没有 telegram-bot / cloudflared / scheduler 容器被本地启动。
# 5. 端口只绑定 127.0.0.1。
# 6. ER 离线测试继续通过。
#
# 不做任何生产服务器调用、不启动定时分析、不推送通知。
# ------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.orbstack.yml"
ER_DIR="${REPO_ROOT}/ops/er-dashboard"

cd "${REPO_ROOT}"

echo "[smoke] 1) compose ps"
docker compose -f "${COMPOSE_FILE}" ps

echo "[smoke] 2) DSA health (http://127.0.0.1:18088/api/health)"
DSA_HEALTH="$(curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:18088/api/health || true)"
echo "    HTTP ${DSA_HEALTH}"
if [[ "${DSA_HEALTH}" != "200" && "${DSA_HEALTH}" != "404" ]]; then
  echo "[smoke] FAIL: DSA health endpoint unreachable (HTTP ${DSA_HEALTH})"
  exit 1
fi

echo "[smoke] 3) ER index (http://127.0.0.1:18080/)"
ER_INDEX="$(curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/ || true)"
echo "    HTTP ${ER_INDEX}"
if [[ "${ER_INDEX}" != "200" ]]; then
  echo "[smoke] FAIL: ER index unreachable (HTTP ${ER_INDEX})"
  exit 1
fi

echo "[smoke] 4) forbidden local services not running"
forbidden_names=(telegram-bot cloudflared scheduler)
for name in "${forbidden_names[@]}"; do
  if docker compose -f "${COMPOSE_FILE}" ps --services | grep -qx "${name}"; then
    echo "[smoke] FAIL: service ${name} present in orbstack compose"
    exit 1
  fi
  running="$(docker ps --format '{{.Names}}' | grep -E "(^|[-])${name}([-]|$)" || true)"
  if [[ -n "${running}" ]]; then
    echo "[smoke] FAIL: forbidden container running: ${running}"
    exit 1
  fi
done
echo "    OK: no telegram-bot / cloudflared / scheduler containers locally"

echo "[smoke] 5) ports bound to 127.0.0.1 only"
for port in 18088 18080; do
  binds="$(docker ps --format '{{.Names}}\t{{.Ports}}' | awk -v p=":${port}->" '$2 ~ p {print $1 " " $2}')"
  if [[ -z "${binds}" ]]; then
    echo "    WARN: no docker binding found for :${port}"
    continue
  fi
  echo "${binds}" | grep -vE "127\.0\.0\.1:${port}->" >/dev/null && {
    echo "[smoke] FAIL: port ${port} bound to non-loopback interface"
    echo "${binds}"
    exit 1
  }
done
echo "    OK: 18088 / 18080 bound to 127.0.0.1"

echo "[smoke] 6) ER offline tests"
(cd "${ER_DIR}" && python3 -m unittest test_stability test_trigger_stability test_app_config)

echo "[smoke] ALL CHECKS PASSED"