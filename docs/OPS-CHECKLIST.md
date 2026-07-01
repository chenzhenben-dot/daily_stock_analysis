# DSA 项目运维清单 (OPS CHECKLIST)

> 维护者: chenzhen · 最后更新: 2026-07-02 · 健康状态: ⚠️ **能跑但有 6 个待加固隐患**

---

## 1. 系统稳定状态 (Current State)

| 模块 | 当前值 | 状态 |
|---|---|---|
| 服务器 | 阿里云 ECS `root@147.139.145.89` | ✅ 运行中 |
| 部署路径 | `/opt/dsa/` | ✅ |
| Git 最新 commit | `a83dfb6 feat(美股大盘): 加入 NDX 纳斯达克100 和 RUT 罗素2000` | ✅ |
| mac git 镜像 | `/private/tmp/dsa-src3` | ✅ |
| 容器 stock-analyzer | healthy | ✅ |
| 容器 stock-server | healthy | ✅ |
| WebUI `/health` | `{"status":"ok"}` | ✅ |
| 大盘报告最新 | `/opt/dsa/reports/market_review_20260702.md` | ✅ 含 NDX/RUT |
| 邮件推送 | chenzhenben@gmail.com | ✅ |
| MiniMax LLM | 国内 `minimaxi.com` + `sk-cp-...` key | ✅ |
| MiniMax 订阅 | Token Plan Max (月度) | ✅ |
| **swap** | **9.0 GiB** (/swapfile 8G + /www/swap 1G) | ✅ 2026-07-02 加固 |
| docker memory 限制 | analyzer 1Gi / server 768Mi | ✅ 2026-07-02 加固 |
| sshd 自愈 | systemd Restart=on-failure | ✅ 2026-07-02 加固 |
| SSH key 备援 | 无,只靠密码 | 🟡 待 P1-4 |
| container restart policy | on-failure / max_attempts=3 | ✅ 2026-07-02 加固 |
| MiniMax base_url | `https://api.minimaxi.com/v1` | ✅ 2026-07-02 修正 |
| minimaxi.com /v1/models 自测 | HTTP 200 | ✅ |

---

## 2. ✅ P0/P1 加固状态

每条对应一次可能的下一次故障。已经完成的标 ✅,未完成的仍标 🔴 / 🟡。

| 项 | 状态 | 时间 |
|---|---|---|
| 🔥 P0-1 swap 3Gi→8Gi + swappiness=10 | ✅ 2026-07-02 | 实际 8G swapfile + 1G /www/swap,total 9Gi |
| 🔥 P0-2 docker memory 收紧 | ✅ 2026-07-02 | analyzer 1Gi / server 768Mi,on-failure x3 |
| 🔥 P0-3 sshd 自愈 | ✅ 2026-07-02 | Restart=on-failure / RestartUSec=10s / Burst=5 |
| ⚠️ P1-4 SSH key 备援 | 🟡 待 P1 | 不依赖 |
| ⚠️ P1-5 关 LiteLLM stream fallback | 🟡 待 P1 | 不依赖 |
| ⚠️ P1-6 OOM 告警 cron | 🟡 待 P1 | 不依赖 |

---

### P0-1:swap 3Gi → 8Gi(OOM 根因修复) ✅

```bash
ssh root@147.139.145.89 '
  fallocate -l 8G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
  sysctl vm.swappiness=10
  echo "vm.swappiness=10" >> /etc/sysctl.d/99-dsa.conf
  free -h
'
```

### P0-2:docker memory 限制收紧(单容器别吃光宿主)

编辑 `/opt/dsa/docker/docker-compose.yml` 的 services.analyzer 和 services.server 的 `deploy.resources.limits`:
```yaml
  analyzer:
    <<: *common
    deploy:
      resources:
        limits:
          memory: 1024M     # ← 已经在 1Gi,但加一行 memory-swap 保护
          memory-swap: 1536M
        reservations:
          memory: 384M
      restart_policy:
        condition: on-failure
        max_attempts: 3
```
`docker compose up -d --force-recreate stock-analyzer stock-server` 重启容器生效。

**踩坑警告(2026-07-02):** ~~`memory-swap` 字段不要用~~ —— `deploy.resources.limits.memory-swap` **不是 docker compose v2 schema 允许的字段**,会触发 `Additional property memory-swap is not allowed` 错误,`docker compose config` 拒绝解析,导致配置回滚。**compose v2 schema 在 `deploy.resources.limits` 下只允许 `cpus / memory / pids` 三个字段。**

如果需要"总内存 + swap 上限"类似效果,用**顶层服务字段**(不是 deploy 块):
```yaml
analyzer:
  mem_limit: 1024m        # 与 limits.memory 等价
  mem_reservation: 384m
  mem_swappiness: 0        # 限制容器内 swap 行为(0=不动 swap,只 RAM)
  restart: on-failure     # 顶层字符串,简单够用
```
但这些顶层字段在 compose v2 已 deprecated,推荐写法就是 **`deploy.resources.limits.memory` + `deploy.restart_policy.condition: on-failure`**,**这套标准写法足够,不要碰 `memory-swap`。**

### P0-3:sshd 死了能自愈

```bash
ssh root@147.139.145.89 '
  mkdir -p /etc/systemd/system/sshd.service.d/
  cat > /etc/systemd/system/sshd.service.d/recovery.conf << EOF
[Service]
Restart=on-failure
RestartSec=10
StartLimitInterval=300
StartLimitBurst=5
EOF
  systemctl daemon-reload
  systemctl restart sshd
'
```

### P1-4:SSH 密码忘了也是灾难 → 加 SSH key 备援

```bash
# mac 这边:
ssh-keygen -t ed25519 -f ~/.ssh/dsa-ecs -N "" -C "dsa@147.139.145.89"
ssh-copy-id -i ~/.ssh/dsa-ecs.pub root@147.139.145.89
# 之后 ssh -i ~/.ssh/dsa-ecs root@147.139.145.89 就能免密
# Workbench 也能用这个 key 登录(Settings → SSH Public Key)
```

### P1-5:关闭 stream → non-stream 双 fallback(失败浪费)

如果 LiteLLM 端点确定 stream 不工作(国内端常限制 stream),在 `.env` 加:
```bash
LITELLM_DISABLE_STREAMING=true
# 或针对 main model:
LITELLM_MODEL=openai/MiniMax-M3  # 改后禁用 stream via route config
```
更精确:在 `/opt/dsa/src/config.py` 或 litellm config 里禁用 stream。**这一步等价格测试后再做**,因为会让长输出不能实时吐。

### P1-6:OMM 告警监控 + dmesg 历史

```bash
ssh root@147.139.145.89 '
  # 简单监控,加到 cron
  (crontab -l 2>/dev/null; echo "*/5 * * * * dmesg --since=\"-5 minutes\" | grep -iE \"killed process|out of memory\" | mail -s \"OOM alert 147.139.145.89\" chenzhenben@gmail.com || true") | crontab -
'
```

---

## 3. ✅ 日常巡检 (Daily Health Check)

每次开盘前 5 分钟跑一遍(任一异常就停下来查):

```bash
ssh root@147.139.145.89 '
  echo "=== 时间 ==="; date
  echo "=== 宿主 ==="; uptime; free -h; df -h /opt/dsa
  echo "=== docker ==="; cd /opt/dsa && docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Size}}"
  echo "=== 最近 OOM ==="; dmesg --since "-24 hours" | grep -iE "killed|out of memory" | tail -5 || echo "无 OOM"
  echo "=== WebUI ==="; curl -sS -m 5 http://localhost:8000/health || echo "WebUI 不可达"
  echo "=== 报告 ==="; ls -lt /opt/dsa/reports/market_review_*.md 2>/dev/null | head -3
  echo "=== 大盘 LLM 健康 ==="; docker logs --tail 50 stock-analyzer 2>&1 | grep -iE "auth|invalid api key|2049|401" | tail -3 || echo "无 401/2049"
'
```

**期望输出:**
```
最近 OOM: 无 OOM
WebUI: {"status":"ok",...}
报告: market_review_YYYYMMDD.md (今日)
大盘 LLM 健康: 无 401/2049
```

---

## 4. 故障 SOP(按症状)

### 4.1 SSH 卡 banner

```bash
nc -zv 147.139.145.89 22           # 端口通?
ssh -vvv root@147.139.145.89 'echo ok'  # 看握手卡哪
```

| 现象 | 根因 | 修复 |
|---|---|---|
| 端口通 + banner 卡 | sshd OOM killed | Workbench → `systemctl restart sshd`,不行强制重启 |
| 端口都不通 | 安全组 / 物理网络 | 阿里云工单 |
| Permission denied | key 错 / 密码错 | 重新发 key,或 Workbench 重置密码 |

### 4.2 LLM 报 `invalid api key (2049)`

```bash
ssh root@147.139.145.89 '
  cd /opt/dsa
  KEY=$(grep -E "^LLM_MINIMAX_API_KEY=" .env | head -1 | cut -d= -f2-)
  curl -sS -m 8 -o /dev/null -w "minimaxi.com: HTTP=%{http_code}\n" "https://api.minimaxi.com/v1/models" -H "Authorization: Bearer ${KEY}"
  curl -sS -m 8 -o /dev/null -w "minimax.io:  HTTP=%{http_code}\n" "https://api.minimax.io/v1/models"  -H "Authorization: Bearer ${KEY}"
'
```

| 国内端 | 海外端 | 诊断 |
|---|---|---|
| 200 | 401 | `.env` 里 `LLM_MINIMAX_BASE_URL` 没指向国内端(常见错误) |
| 401 | 401 | key 在两个端点都不认 → 订阅过期 / key 错账号 |
| 200 | 200 | 都不是 |

**修复 base_url:**
```bash
sed -i "s|^LLM_MINIMAX_BASE_URL=.*|LLM_MINIMAX_BASE_URL=https://api.minimaxi.com/v1|" /opt/dsa/.env
# 不存在就追加
grep -q "^LLM_MINIMAX_BASE_URL=" /opt/dsa/.env || echo "LLM_MINIMAX_BASE_URL=https://api.minimaxi.com/v1" >> /opt/dsa/.env
cd /opt/dsa/docker && docker compose up -d stock-analyzer
```

### 4.3 大盘报告没生成

```bash
ssh root@147.139.145.89 '
  # 1) 容器在跑?
  docker ps --filter name=stock-analyzer
  # 2) 看股票 analyzer 日志最后 100 行
  docker logs --tail 100 stock-analyzer
  # 3) 手动触发一次
  docker exec -e MARKET_REVIEW_REGION=us stock-analyzer python main.py --market-review --force-run
  # 4) 看结果
  ls -lt /opt/dsa/reports/market_review_*.md | head -3
'
```

### 4.4 邮件没发出去

```bash
ssh root@147.139.145.89 '
  # 收件人错了?
  grep -E "EMAIL_SENDER|EMAIL_PASSWORD|EMAIL_RECEIVERS" /opt/dsa/.env | sed "s/=.\{4,\}/=<hidden>/"
  # 试发一封
  docker exec stock-analyzer python -c "from src.notify import send_email; send_email(\"test\", \"这是测试邮件\", [\"chenzhenben@gmail.com\"])"
  # 看日志
  docker logs --tail 50 stock-analyzer | grep -iE "smtp|email|send"
'
```

### 4.5 OOM 又来了

```bash
ssh root@147.139.145.89 '
  # 1) 谁被杀了?
  dmesg --since "-24h" | grep -iE "killed process|out of memory" | tail -20
  # 2) 哪个容器内存失控?
  docker stats --no-stream --format "table {{.Container}}\t{{.MemUsage}}\t{{.MemPerc}}"
  # 3) 临时止血:杀掉最大的
  docker ps --format "{{.Names}}" | xargs -I {} sh -c "mem=\$(docker stats --no-stream {} | tail -1 | awk "{print \$3}"); echo \"{} \$mem\"" | sort -k2 -hr | head
  # 4) 杀前先停 analyzer 释放 1G
  docker stop stock-analyzer
  systemctl restart sshd
'
```

---

## 5. 关键配置 & 路径

### 5.1 服务侧(`/opt/dsa/`)

```
/opt/dsa/
├── .env                                      ← 全部配置入口(LITELLM_MODEL / MiniMax key / base_url / 通知)
├── .env.bak.YYYYMMDD-HHMMSS.*                ← 备份(每次改 .env 前自动备份)
├── docker/
│   └── docker-compose.yml                    ← 容器编排(memory 限制 / restart 策略 在这)
├── data/                                     ← 持久化数据库(SQLite WAL)
├── logs/                                     ← 容器日志 + longbridge SDK 日志
├── reports/                                  ← 报告输出(大盘 + 个股)
├── strategies/                               ← YAML 策略
├── longbridge_tokens/                        ← OAuth token 缓存
└── src/
    ├── config.py                             ← LiteLLM provider 配置
    ├── cli.py                                ← main.py 命令行入口
    ├── notify/                               ← 邮件/IM/微信推送
    └── analyzer/                             ← 大盘复盘 + 个股分析
```

### 5.2 mac 侧

```
/Users/chenzhen/.codex/                       ← OpenAI Codex 数据
├── minimax.config.toml                        ← Codex → minimaxi.com 路由(MiniMax-M3 model)
/Users/chenzhen/projects/bali-content-tool/   ← Bali 项目(无关)
/Users/chenzhen/Desktop/equity-dashboards/    ← 股票分析 HTML 看板(SPCX/RKLB/LITE/GLW)
```

---

## 6. 凭据 & 外部信息

| 项 | 值 / 来源 |
|---|---|
| 服务器 root 密码 | **[立刻写进 1Password/Keychain]** —— 这次的痛点 |
| 服务器 SSH key | 待创建(P1-4) |
| MiniMax 国内控制台 | https://platform.minimaxi.com/console |
| MiniMax Token Plan 订阅 | Max 月度,有效中(登录 → console/plan 看日期) |
| MiniMax API key | `sk-cp-...` 国内 endpoint 用,**不**用于海外 endpoint |
| 阿里云控制台 | https://ecs.console.aliyun.com/ |
| Workbench 直连 | https://ecs-workbench.aliyun.com/ |
| 通知收件人 | chenzhenben@gmail.com |
| SMTP 凭证 | 在 .env(`EMAIL_SENDER` + `EMAIL_PASSWORD`,用 QQ/163/Gmail 授权码) |

---

## 7. 紧急联络 / 文档

- **阿里云工单:** ECS console → 工单 → "运维问题"
- **DSA 项目 GitHub:** (committed commit hash above)
- **DSA 完整文档:** `/opt/dsa/docs/` + GitHub README
- **MiniMax 国内工单(开发商用 Slack/Discord):** https://minimaxi.com/ 联系客服

---

## 8. 最近变更日志 (Change Log)

| 日期 | 变更 | 触发事件 |
|---|---|---|
| 2026-07-02 | **OPS-CHECKLIST.md 创建**(本次踩坑沉淀的 runbook + SOP) | 上线一份文档给未来 session 兜底 |
| 2026-07-02 | **P0 加固 3 件套全完成**(P0-1 swap 9G,P0-2 docker memory,P0-3 sshd 自愈) | 6 项高风险待办中 P0 三件全部到位 |
| 2026-07-02 | base_url `minimax.io` → `minimaxi.com`<br>大盘报告 401/2049 修复<br>服务器强制重启恢复 sshd | 大盘 LLM 2049 报错 + 主机 OOM (python killed) |
| 2026-07-01 | 加入 NDX / RUT 指数<br>Yfinance 成功获取 6 个美股指数 | 用户需求(扩展美股覆盖) |
| 2026-06-30 | 容器 healthy,WebUI OK | 上次正常状态 |
| (更早) | swap 持续 3Gi 早就是风险信号 | —— |

---

## 9. 长期防线 (Long-term)

- [ ] **改 mosh 替代 SSH**(mosh 抗网络中断,SSH 卡 banner 不再发生)
- [ ] **加 cAdvisor + Prometheus + Grafana**(容器内存实时可视化)
- [ ] **slack/邮件告警接入**(OOM / 容器 down / LLM 401 → 实时推)
- [ ] **定期演练**恢复流程(每季度做一次强制重启演练)
- [ ] **3-2-1 备份**(`.env` + `reports/` + `data/` 三副本异地)
- [ ] **Ansible/Cron 自动化加固项 P0-1 到 P0-3**(每月跑一次,不靠手工)

---

**文件维护**
- 路径:`/private/tmp/dsa-src3/docs/OPS-CHECKLIST.md`(committed with project)
- 每次完成 P0/P1 项后,更新 §2 完成状态 + §8 change log
- 遇到新故障先查 §4 SOP,不在的话追加新条目

**下次故障怎么 check**: 三步走 → §3 巡检 → §4 SOP → §2 检查对应 P 项是否完成。
