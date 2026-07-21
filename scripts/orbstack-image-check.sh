#!/usr/bin/env bash
# ------------------------------------------------------------
# OrbStack 本地预发布镜像结构检查
#
# 在已构建的 er-dashboard-local:orbstack 镜像上检查：
#   /opt/er-dashboard/app.py
#   /opt/er-dashboard/trigger.py
#   /opt/er-dashboard/equity-research/SKILL.md
#   /opt/er-dashboard/equity-research/references/dashboard-template.html
#   /opt/er-dashboard/equity-research/references/dashboard-generator.py
#   /opt/er-dashboard/equity-research 目录可读
#   /opt/er-dashboards 目录可写
#   /opt/er-dashboard/.env.local（本 compose 挂入的本地配置）可读
#   trigger.py 可被 Python import（语法合法，模块载入不抛错）
#
# 不调用 LLM、不执行真实股票分析、不产生费用。
# ------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="er-dashboard-local:orbstack"

if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
  echo "[image-check] FAIL: image ${IMAGE} not built locally"
  exit 1
fi

required=(
  "/opt/er-dashboard/app.py"
  "/opt/er-dashboard/trigger.py"
  "/opt/er-dashboard/equity-research/SKILL.md"
  "/opt/er-dashboard/equity-research/references/dashboard-template.html"
  "/opt/er-dashboard/equity-research/references/dashboard-generator.py"
)

echo "[image-check] file existence"
for path in "${required[@]}"; do
  docker run --rm --entrypoint ls "${IMAGE}" -la "${path}" >/dev/null \
    || { echo "[image-check] FAIL: missing ${path}"; exit 1; }
  echo "    OK: ${path}"
done

echo "[image-check] dashboard output dir writable"
docker run --rm --entrypoint sh "${IMAGE}" -c '
  mkdir -p /opt/er-dashboards/_write_probe && \
  test -w /opt/er-dashboards && \
  rm -rf /opt/er-dashboards/_write_probe' >/dev/null \
  || { echo "[image-check] FAIL: /opt/er-dashboards not writable"; exit 1; }
echo "    OK"

echo "[image-check] trigger.py importable"
docker run --rm --entrypoint python3 "${IMAGE}" -c "import importlib.util, sys; \
spec=importlib.util.spec_from_file_location('trigger','/opt/er-dashboard/trigger.py'); \
m=importlib.util.module_from_spec(spec); \
spec.loader.exec_module(m); \
print('DSA_ENV_PATH=', m.DSA_ENV_PATH); \
print('DASH_DIR=', m.DASH_DIR); \
print('SKILL_PATH exists=', m.SKILL_PATH.exists()); \
print('TEMPLATE_PATH exists=', m.TEMPLATE_PATH.exists()); \
print('GENERATOR_PATH exists=', m.GENERATOR_PATH.exists())" >/dev/null \
  || { echo "[image-check] FAIL: trigger.py import failed"; exit 1; }
echo "    OK"

echo "[image-check] local env file path readable (when mounted)"
docker run --rm \
  --mount type=bind,source="${REPO_ROOT}/.env.orbstack.local",target=/opt/er-dashboard/.env.local,readonly \
  --entrypoint sh "${IMAGE}" -c '
  test -r /opt/er-dashboard/.env.local && \
  echo "  size=$(wc -c < /opt/er-dashboard/.env.local) bytes"' >/dev/null \
  || { echo "[image-check] FAIL: local env file not readable when mounted"; exit 1; }
echo "    OK"

echo "[image-check] ALL IMAGE CHECKS PASSED"