#!/usr/bin/env bash
# ------------------------------------------------------------
# OrbStack 本地预发布 smoke test
#
# 检查项（任一失败立即非零退出，绝不允许掩盖）：
# 1. 两个容器存在且 health 状态为 healthy。
# 2. DSA /api/health 严格返回 200。
# 3. ER 首页严格返回 200。
# 4. 端口 18088 / 18080 必须能找到 docker 端口映射，
#    且必须以 127.0.0.1: 开头（loopback only）。
# 5. 没有 telegram-bot / cloudflared / scheduler 容器被本地启动。
# 6. ER 离线测试继续通过（test_stability / test_trigger_stability / test_app_config）。
#
# 不做任何生产服务器调用、不启动定时分析、不推送通知。
# ------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.orbstack.yml"
ER_DIR="${REPO_ROOT}/ops/er-dashboard"

cd "${REPO_ROOT}"

# 容器必须存在并 healthy
echo "[smoke] 1) container health"
docker compose -f "${COMPOSE_FILE}" ps
for svc in dsa-local er-local; do
  json="$(docker compose -f "${COMPOSE_FILE}" ps --format json "${svc}" 2>/dev/null || true)"
  if [[ -z "${json}" ]]; then
    echo "[smoke] FAIL: ${svc} not found in compose ps"
    exit 1
  fi
  state="$(printf '%s' "${json}" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read() or '{}')
print((data.get('Health') or '-').strip())
")"
  echo "    ${svc} Health=${state}"
  if [[ "${state}" != "healthy" ]]; then
    echo "[smoke] FAIL: ${svc} health is '${state}', expected 'healthy'"
    exit 1
  fi
done

# DSA /api/health 严格 200
echo "[smoke] 2) DSA /api/health must be 200"
DSA_HEALTH="$(curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:18088/api/health || true)"
echo "    HTTP ${DSA_HEALTH}"
if [[ "${DSA_HEALTH}" != "200" ]]; then
  echo "[smoke] FAIL: DSA /api/health returned ${DSA_HEALTH}, expected 200"
  exit 1
fi

# ER 首页严格 200
echo "[smoke] 3) ER / must be 200"
ER_INDEX="$(curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/ || true)"
echo "    HTTP ${ER_INDEX}"
if [[ "${ER_INDEX}" != "200" ]]; then
  echo "[smoke] FAIL: ER / returned ${ER_INDEX}, expected 200"
  exit 1
fi

# 禁止的本地服务不存在
echo "[smoke] 4) forbidden local services not running"
for name in telegram-bot cloudflared scheduler; do
  if docker compose -f "${COMPOSE_FILE}" ps --services 2>/dev/null | grep -qx "${name}"; then
    echo "[smoke] FAIL: service ${name} present in orbstack compose"
    exit 1
  fi
done
running="$(docker ps --format '{{.Names}}' | grep -E '(^|[-])(telegram-bot|cloudflared|scheduler)([-]|$)' || true)"
if [[ -n "${running}" ]]; then
  echo "[smoke] FAIL: forbidden container running: ${running}"
  exit 1
fi
echo "    OK: no telegram-bot / cloudflared / scheduler containers locally"

# 端口必须存在并绑 loopback
echo "[smoke] 5) ports bound to 127.0.0.1 only"
for port in 18088 18080; do
  raw="$(docker ps --format '{{.Names}} {{.Ports}}')"
  binding="$(printf '%s\n' "${raw}" | grep -E "${port}->" || true)"
  if [[ -z "${binding}" ]]; then
    echo "[smoke] FAIL: no docker binding found for :${port}"
    exit 1
  fi
  if ! printf '%s\n' "${binding}" | grep -qE "127\.0\.0\.1:${port}->"; then
    echo "[smoke] FAIL: port ${port} has non-loopback binding"
    echo "${binding}"
    exit 1
  fi
  echo "    OK: :${port} -> 127.0.0.1 only"
done

# ER 离线测试
echo "[smoke] 6) ER offline tests"
(cd "${ER_DIR}" && python3 -m unittest test_stability test_trigger_stability test_app_config)

echo "[smoke] ALL CHECKS PASSED"