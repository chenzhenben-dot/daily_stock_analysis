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

### P0-3:sshd 死了能自愈(⚠️ **只能救"sshd 自己 crash",救不了"宿主 OOM 把 systemd + sshd 一起杀"**)

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

**踩坑警告(2026-07-02 复发 OOM 教训):** `Restart=on-failure` 仅对 sshd **自身 clean crash** 有效。

如果宿主 OOM killer **杀的不是 sshd 而是 systemd 自己** (`systemd --user` / `systemd-logind` / `dbus-daemon` 这类核心), 或者 OOM 引发 docker daemon 进入 hang 状态,systemd 的 Restart 规则可能根本来不及触发。**这是 24h 内第二次 OOM sshd 卡 banner 的根因** —— 不是"sshd 自愈配置没生效",而是"那种 OOM 根本不是 systemd 救得了的事"。

**真正的终极修法(必做):** 改写 docker / sshd 的 OOMScoreAdjustment(让他们 OOM killer 不优先杀他们),详见 P0-4。

---

### P0-4 ⚠️ 新增:保护 systemd + sshd + docker 不被宿主 OOM 杀(OOMScoreAdjustment)

**严重警告:** 上面的 P0-3 不够,以下是真正抗宿主 OOM 的修法。

OOM killer 按 `oom_score_adj` 选目标杀进程。我们要把 sshd / docker / systemd 的 OOMScore 调到很负,这样 OOM 不优先杀它们:

```bash
ssh root@147.139.145.89 '
  # 1) sshd 永久保护
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

  # 2) docker 保护(让它挂之前先杀容器进程,不杀 docker daemon)
  mkdir -p /etc/systemd/system/docker.service.d/
  cat > /etc/systemd/system/docker.service.d/oom-guard.conf << EOF
[Service]
OOMScoreAdjust=-900
EOF
  systemctl daemon-reload
  systemctl restart docker
  # 注:重启 docker 会瞬断所有容器几秒,大盘 / WebUI 也会断 ~5-10s
'
```

`OOMScoreAdjust=-900` + `OOMPolicy=continue`(systemd 230+)语义:
- OOM killer 不优先选他们(分数被压到负)
- OOMPolicy=continue 当真被杀时不再 panic loop

**光有这个还不够**,还需要:
- **swap 够(✅ 9Gi,我们已有)**
- **容器 memory 上限 + max-attempts 限制(✅ P0-2,已有 1Gi)**
- **禁止会引发死锁的 flag(新增 P0-4b:ban `--force-run`,见下)**

---

### P0-4b ⚠️ 新增:Ban `--force-run` 这个危险 flag

`--force-run` 在大盘复盘场景触发完整 6 指数抓取 + LiteLLM stream + non-stream 双 retry + 全文渲染 + 邮件 + Markdown 落盘,**任意一步卡都会拖整个调用链 → docker daemon 状态堆栈挂住**。这是 2026-07-02 第二次 OOM 的直接诱因。

**以后绝不能用 `--force-run`,走 `--market-review --region us` 默认逻辑**,DSA 自己判断 cache 是否新鲜。需要"强制清缓存跑"的话:
```bash
# 在 analyzer 容器里手工删 cache(可控),然后 --market-review
ssh root@147.139.145.89 '
  docker exec stock-analyzer rm -f /app/data/market_review_cache.json 2>/dev/null || true
  docker exec -e MARKET_REVIEW_REGION=us stock-analyzer python main.py --market-review --region us
'
```

或者改代码把 `--force-run` flag 移除 / 改成 dry-run。

---

## ⚠️ 紧急状态(2026-07-02 18:00 之前必须做完)

**24h 内 3 次 OOM 复发**(`swap 9Gi` + `docker 1Gi` 限制 + `OOMScore drop-in` 都没装完就又死了):
- 加固方案没有击中根因
- 真因疑似 DSA `get_main_indices` / yfinance / LiteLLM 死锁(在 Workbench 日志里"卡在 get_main_indices status=start")
- crontab scheduler 18:00 自动跑大盘复盘是下次 OOM 高概率诱因

**Workbench 救活后第一时间执行(必须):**
```bash
# 1) 救活 sshd
systemctl restart sshd; sleep 3
# 2) 立即禁自动跑(避免下次 18:00 又死)
sed -i 's|^SCHEDULE_ENABLED=.*|SCHEDULE_ENABLED=false|' /opt/dsa/.env
sed -i 's|^RUN_IMMEDIATELY=.*|RUN_IMMEDIATELY=false|' /opt/dsa/.env
# 3) 杀 crontab 里所有 DSA 相关任务
crontab -l 2>/dev/null | grep -v "market_review\|DSA\|stock-analyzer" | crontab -
# 4) 关掉 analyzer 容器里一切正在跑的进程
docker exec stock-analyzer pkill -9 -f "python main.py" || true
docker restart stock-analyzer stock-server
# 5) 看 dmesg 找元凶进程
dmesg --since "-24h" | grep -iE "killed|out of memory" | tail -20
# 6) 收集证据(把以下 4 段贴给我,不要分析,直接贴):
free -h
df -h /opt/dsa
uptime
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Size}}"
```

**禁止动作(直到根因诊断清楚):**
- ❌ 不能再跑 `python main.py --market-review --force-run`
- ❌ 不能再跑 `python main.py --market-review` 自动大盘复盘路径(必须先 debug)
- ❌ 不要让 scheduler 自动跑
- ❌ 不要再做"加固"层(已经没有意义,得 debug 代码)

**根因诊断方向(下一步):**
1. 把 dmesg 完整 OOM 段贴出来 — 哪个 python 进程被杀?`/usr/bin/python` / `python3` / `litellm` ?
2. `cat /opt/dsa/logs/*.log | tail -200` 看 yfinance / LiteLLM 哪个 API 卡住
3. 如果是 yfinance 死锁,考虑换数据源(efinance 已经有,优先试试,国内 IP 更稳)
4. 如果是 LiteLLM stream 死锁,临时禁用 stream(`LITELLM_DISABLE_STREAMING=true` in .env)
5. 写一个 `src/llm/__init__.py` 加 timeout + retry 限速,避免 OOM

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

---

## 10. equity-research 数据源规则 v2(融合 DSA 模式 + equity 特有)

> **背景(2026-07-03 沉淀):** 跑台积电 (TSM) 分析时复盘,发现 DSA 项目的"priority + fallback + timeout"模式值得借鉴,但 equity-report 还有 DSA 没有的"质量评分"和"前瞻数据"需求。这章是**所有 equity-research 分析(新公司 / 旧公司 retro)统一规则**。下次做新公司(NVDA / Apple / 任何)直接按这 5 条 priority 链跑,不依赖单一 stockanalysis。

### 10.1 借鉴自 DSA 的 3 个核心原则

**Priority + Fallback 链**(整套设计的灵魂)
- 每类数据一条 priority 链(0 最先,4 最后,失败自动降级)
- env var 可配置,用户能改
- 失败时优雅降级,不会"一个源挂整个流程死"

**Timeout 保护**(每个源都设)
- **DSA 默认 30s 太长**,equity 实时数据要快 — 8-15s 看数据类型
- 不设 timeout 的教训:2026-07-02 SPCX 调研时 10 分钟卡死没人管

**注释 + 可配置**(每个源都有"为什么用 / 什么时候用 / 限制")
- 不是"用这个 source"就完事,要写明好处 + 限制 + 数据延迟

### 10.2 equity-research 特有(DSR 没有的 3 个)

**A. 数据点 A/B/C/D 等级标签**
- DSA 数据源机读无所谓等级,equity 报告每条数字要让读者知道可信度
- `[A]` 10-K / 一手 + 多源验证
- `[B]` Wikipedia / 二手 / 单一权威
- `[C]` 行业估算 / 反推
- `[D]` 推测 / 弱证据

**B. 看板底部"质量摘要"**
- 占比% 显示:整体 A 占 50% / B 占 25% / C 占 20% / D 占 5% = B+ 级
- 一眼看出哪些数字硬哪些软

**C. Action tag 跟 quality 挂钩**
- 数据 ≥70% A → 可给 buy
- 30-70% A → wait / try
- <30% A → watch / avoid(数据不足以支撑动作)

### 10.3 5 条 priority 链(下次分析必跑)

**链 1: 价格 + 估值倍数**
```
primary:  stockanalysis.com (Fiscal.ai 后端)
fallback: Yahoo Finance
tertiary: 自己 curl SEC EDGAR
TIMEOUT:  8s
DOC:      "实时共识;stockanalysis 免费 tier 有 ~15min 延迟"
```

**链 2: 财务数据 / 财报**
```
primary:  SEC EDGAR (10-K / 10-Q / 20-F)  ← 必须真去拉,不是只引用
fallback: stockanalysis.com (Fiscal.ai)
tertiary: 公司 IR
TIMEOUT:  15s
DOC:      "primary 是金标准;fallback 聚合数据可能有 ~5% 误差"
```

**链 3: 客户 / 行业份额 / 竞对**
```
primary:  公司 10-K 风险因素段(实际披露的前 N 大客户)
fallback: Wikipedia + TrendForce / IDC 公开报告
tertiary: 反推(标 C — 之前我没标,现在强制)
TIMEOUT:  10s
DOC:      "客户占比 10-K 通常不单独披露,只能反推"
```

**链 4: Forward Guidance(前瞻)**
```
primary:  Earnings call transcript(Seeking Alpha / Motley Fool)
fallback: 卖方研报(找免费能拿到的)
tertiary: 共识(标 C,consensus 通常滞后 1 季度)
TIMEOUT:  15s
DOC:      "Q2 财报后第一时间拉 transcript;这是未来业绩源头"
```

**链 5: 新闻 / 地缘风险 / 突发**
```
primary:  Reuters / Bloomberg(机构来源,月费)
fallback: Wikipedia current events + Investing.com
tertiary: my memory(标 D)
TIMEOUT:  8s
DOC:      "地缘事件几小时内影响估值,必须实时拉"
```

### 10.4 强制给每个数据点打 [A/B/C/D] 标签

格式:数据点后挂小标签,例:
```
Apple  ~22-25% [C]  ← 反推,不是 10-K 披露
NVIDIA  ~13-15% [C]  ← 反推
Forward P/E  23.14x [A]  ← stockanalysis 实时共识
毛利率 60% [A]  ← 10-K / IR 直接披露
Foundry 70% 份额 [B]  ← Wikipedia 引用 TrendForce
```

### 10.5 看板底部"质量摘要"模板

```
════════ DATA QUALITY ════════
A 占比: ~XX%   <填实际>
B 占比: ~XX%   <填实际>
C 占比: ~XX%   <填实际>
D 占比: ~XX%   <填实际>
═══════════════════════════════
总评: <B+ / A- / C+ 等>
下次高 ROI 提升方向: <拉 10-K / 拉 earnings call / 拉 Reuters>
```

### 10.6 3 个高 ROI 补充(下次分析必做)

| 优先级 | 数据源 | 补什么 | 当前 TSM 缺什么 |
|---|---|---|---|
| 1 必补 | **Earnings call transcript** (7/16 后) | 管理层原话 + Q&A | forward guidance 数字 + capex 节奏全靠"行业共识"反推 |
| 2 必补 | **10-K / 20-F primary** (SEC EDGAR) | 风险因素段 + 客户披露 | "Apple 22%" 客户占比是估的,10-K 有实际披露 |
| 3 推荐 | **Reuters 近 30 天新闻** | 地缘政治 / Apple iPhone cycle | TSMC 90% 估值受地缘影响,实时新闻不可缺 |

### 10.7 不补的(噪音大)

- ❌ Seeking Alpha 散户文章(信噪比低)
- ❌ 卖方研报(Bernstein / MS,要付费且和 consensus 重复)
- ❌ 推特 / Reddit 情绪(对机构盘意义小)

### 10.8 现有看板的 retrofit 决策

- SPCX / RKLB / LITE / GLW / TSM 5 个看板:不 retrofit(用户明确表示不改)
- 下次新公司分析:从一开始就用 v2(5 链 priority + ABCD 标签 + 质量摘要)
- 跟 DSA 项目的关系:本规则不直接影响 DSA 部署,但是做"公司基本面分析"的统一流程,跟 DSA 项目的"A股/美股分析"业务直接相关

