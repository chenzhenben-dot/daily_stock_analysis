#!/usr/bin/env bash
# DSA P0-4 OOM-Safe 加固 一键脚本
# 前提:Workbench 救活 + mac SSH key 已 ssh-copy-id + ssh 免密通
# 跑完会在 fork `ops/` 目录留一份,也是 OPS-CHECKLIST 的对应实现
set -euo pipefail

HOST="root@147.139.145.89"
EXPECTED_HEAD="d1cbf6f7"   # 当前 fork 最新 commit (含 P0-3 修订 + P0-4 新增)

echo "============================================================"
echo "[0/6] 前提确认"
echo "============================================================"
echo "测试 SSH key-based auth(不应问密码)"
if ! ssh -o ConnectTimeout=10 -o PasswordAuthentication=no "$HOST" 'echo KEY_OK' 2>/dev/null; then
  echo ""
  echo "❌ SSH key 还不行 —— 必须先做:"
  echo "  1. Workbench 救活 sshd (SystemD restart sshd)"
  echo "  2. 装 mac SSH key:ssh-copy-id -i ~/.ssh/id_ed25519.pub $HOST"
  exit 1
fi
echo "✅ SSH key OK"

echo ""
echo "============================================================"
echo "[1/6] Git pull 最新(d1cbf6f7,把 P0-4 / P0-3 修订 拉到 server)"
echo "============================================================"
ssh "$HOST" '
  cd /opt/dsa
  echo "[before] git status -sb"
  git status -sb | head -5
  echo "[do] git pull --rebase origin main"
  git pull --rebase origin main 2>&1 | tail -10
  echo "[after] HEAD:"
  git log -1 --format="%H %s%n%ci"
'

echo ""
echo "============================================================"
echo "[2/6] 应用 P0-4(OOMScoreAdjustment 保护 sshd + docker)"
echo "============================================================"
ssh "$HOST" '
  mkdir -p /etc/systemd/system/sshd.service.d/
  cat > /etc/systemd/system/sshd.service.d/recovery.conf << EOF
[Service]
Restart=on-failure
RestartSec=10
StartLimitInterval=300
StartLimitBurst=5
OOMScoreAdjust=-900
OOMPolicy=continue
EOF

  mkdir -p /etc/systemd/system/docker.service.d/
  cat > /etc/systemd/system/docker.service.d/oom-guard.conf << EOF
[Service]
OOMScoreAdjust=-900
EOF

  echo "[do] daemon-reload + restart sshd + restart docker"
  systemctl daemon-reload
  systemctl restart sshd
  sleep 3
  systemctl restart docker   # ⚠️ 这会让所有容器重启 5-10s
  echo "(等 10s 让容器拉起来)"
  sleep 10
'

echo ""
echo "============================================================"
echo "[3/6] 检查容器健康"
echo "============================================================"
ssh "$HOST" '
  echo "--- docker ps ---"
  docker ps --format "table {{.Names}}\t{{.Status}}\t{{.MemUsage}}"
  echo ""
  echo "--- WebUI ---"
  for i in 1 2 3 4 5 6; do
    if R=$(curl -sS -m 5 http://localhost:8000/health 2>/dev/null) && [ -n "$R" ]; then
      echo "  [OK] $R"
      break
    fi
    echo "  [...] waiting (try $i/6)"
    sleep 5
  done
'

echo ""
echo "============================================================"
echo "[4/6] 验证 OOMScore 实际生效"
echo "============================================================"
ssh "$HOST" '
  echo "--- sshd drop-in ---"
  cat /etc/systemd/system/sshd.service.d/recovery.conf
  echo ""
  echo "--- docker drop-in ---"
  cat /etc/systemd/system/docker.service.d/docker.service.d/oom-guard.conf 2>/dev/null \
    || cat /etc/systemd/system/docker.service.d/oom-guard.conf
  echo ""
  echo "--- 进程实际 OOM 分数(systemd-managed 进程)---"
  for p in $(pgrep sshd | head -3); do
    NAME=$(cat /proc/$p/comm 2>/dev/null || echo "?")
    SCORE=$(cat /proc/$p/oom_score_adj 2>/dev/null || echo "?")
    echo "  pid=$p  name=$NAME  oom_score_adj=$SCORE"
  done
  for p in $(pgrep dockerd | head -3); do
    NAME=$(cat /proc/$p/comm 2>/dev/null || echo "?")
    SCORE=$(cat /proc/$p/oom_score_adj 2>/dev/null || echo "?")
    echo "  pid=$p  name=$NAME  oom_score_adj=$SCORE"
  done
  echo "(都应该是 -900 或接近)"
'

echo ""
echo "============================================================"
echo "[5/6] 验证 NDX/RUT 还在大盘报告"
echo "============================================================"
ssh "$HOST" '
  LATEST=$(ls -t /opt/dsa/reports/market_review_*.md 2>/dev/null | head -1 || true)
  if [ -z "$LATEST" ]; then
    echo "(无报告)"
  else
    echo "最新: $LATEST"
    stat -c "%y  size=%s bytes" "$LATEST" 2>/dev/null || stat -f "%Sm  size=%z bytes" "$LATEST"
    grep -nE "NDX|RUT|纳指100|罗素2000|纳斯达克100" "$LATEST" | head -5 || echo "(未命中)"
  fi
'

echo ""
echo "============================================================"
echo "[6/6] 关键 ban 校验(--force-run 不在文档里但请确认你不会随便跑)"
echo "============================================================"
ssh "$HOST" '
  echo "Cron / schedule 配置:"
  grep -E "^SCHEDULE_|MARKET_REVIEW_" /opt/dsa/.env | sed "s/=.\{6,\}/=<hidden>/"
  echo ""
  echo "如果上面 SCHEDULE_ENABLED=true,scheduler 自动 18:00 跑。你不需要手动触发大盘。"
'

echo ""
echo "============================================================"
echo "完成。看 [4] OOMScore 是 -900 / [5] NDX-RUT 命中 / 容器 healthy = 成功"
echo "============================================================"
