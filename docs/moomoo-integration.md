# Moomoo OpenD 集成指南

> 🇨🇳 moomoo（富途） OpenD 网关 → 通过 SSH 反向隧道 → DSA server
>
> **本指南是 fork 独家**。upstream `ZhuLinsen/daily_stock_analysis` 不支持此功能。
> 本 fork 集成 moomoo OpenD 作为美/港/A 股实时数据源（资金分布/流向/板块/快照）。

---

## 📑 目录

1. [架构概览](#1-架构概览)
2. [为什么需要 moomoo OpenD](#2-为什么需要-moomoo-opend)
3. [前置条件](#3-前置条件)
4. [macOS 端：下载并配置 OpenD](#4-macos-端下载并配置-opend)
5. [建立 SSH 反向隧道](#5-建立-ssh-反向隧道)
6. [DSA server 端：环境变量配置](#6-dsa-server-端环境变量配置)
7. [DSA 自动启用的功能](#7-dsa-自动启用的功能)
8. [macOS 端：launchd 保活](#8-macos-端launchd-保活)
9. [DSA server 端：watch dog 监控](#9-dsa-server-端watch-dog-监控)
10. [故障排除](#10-故障排除)
11. [性能与限制](#11-性能与限制)
12. [参考](#12-参考)

---

## 1. 架构概览

```
┌─────────────────────────────────────────────────────┐
│  你的 macOS                                          │
│                                                     │
│  moomoo app ────► MoomooOpenD (127.0.0.1:11111)   │
│  (登录态稳定)            │                          │
│                          │ SSH 反向隧道             │
│  launchd:                 │ (autossh 保活)            │
│  com.dsa.moomoo-tunnel ──┘                          │
└─────────────────────────────────────────────────────┘
                          │
                          │ root@147.139.145.89:11111
                          ▼
┌─────────────────────────────────────────────────────┐
│  服务器 147.139.145.89                              │
│                                                     │
│  sshd (持有 11111 端口)                              │
│      │                                              │
│  stock-server (Docker, network_mode: host)         │
│      │                                              │
│  MoomooFetcher 拿数据                                │
│      ↓                                              │
│  DataFetcherManager                                 │
│      ↓                                              │
│  DSA 报告 (含筹码分布/资金流向)                      │
└─────────────────────────────────────────────────────┘
```

**关键点**：
- moomoo OpenD 是**本机 TCP 网关**（127.0.0.1:11111），不暴露公网
- 通过 SSH 反向隧道把 macOS 的 11111 暴露到服务器
- 服务器上的 `MoomooFetcher` 连 `127.0.0.1:11111` → 走 SSH 隧道 → 连到 macOS OpenD
- OpenD 再通过 HTTPS 调 moomoo 云服务器拿交易所数据

**链路延迟**：< 200ms（**实时**）

---

## 2. 为什么需要 moomoo OpenD

DSA 原生数据源问题：
- **EfinanceFetcher / AkShareFetcher**：调东方财富国内 API，**印尼服务器访问被 403 拒绝**
- **YFinanceFetcher**：免费，但**美股 AAPL 实时价格延迟 15 分钟**（且对 A 股无能为力）
- **TushareFetcher**：高质量但需要 token，海外访问慢
- **FinnhubFetcher / AlphaVantageFetcher**：free tier 限制（Finnhub candle 403 / Alpha Vantage 25 calls/day）

**moomoo OpenD 解决了什么**：
- ✅ 港股 + 美股 + A 股 + 板块**实时数据**（延迟 < 1s）
- ✅ **资金分布**（4 档：super/big/mid/small）— A 股以外的**唯一可靠源**
- ✅ **资金流向**（分钟级，391 条/天）
- ✅ 板块分类（**40+** 板块/股）
- ✅ 实时行情、订单簿、逐笔成交

**MoomooFetcher 在 DSA 里**：
- P=0 最高优先级（在所有 fetcher 前）
- 实时数据，**只读行情**（不接触交易账户）
- 失败自动 fallback 到 YFinance / Finnhub 等

---

## 3. 前置条件

| 项 | 要求 |
|---|---|
| macOS | 已装 moomoo 桌面 app（**不是** moomoo SG app）|
| 账户 | 已登录 moomoo 账户（**只要登录态**，不需要资金）|
| 登录态 | OpenD 启动时需登录，登录后 token 持久化 |
| 客户端 | MoomooOpenD 10.x+（mac app 启动时自动跑）|
| 服务器 | DSA 在跑（任意平台，**容器需 `network_mode: host`**）|
| SSH | 服务器 root SSH key 在 macOS `~/.ssh/authorized_keys` |

---

## 4. macOS 端：下载并配置 OpenD

### 4.1 验证 OpenD 已在跑

```bash
lsof -i :11111
# 期望: moomoo_Op 62548 chenzhen ... TCP localhost:vce (LISTEN)
```

如果显示，**跳过下面的下载步骤**。

### 4.2 下载 OpenD（如果没有）

- 打开 **moomoo mac app** → 底部 **「我」** → **「设置」** → **「API 接入」**
- 或者直接 https://www.moomoo.com/OpenAPI 页面
- 下载 **MacOS 版本** OpenD
- 拖进 Applications 文件夹

### 4.3 启动并登录

```bash
open -a Moomoo
# 等几秒，moomoo app 启动
# 它会自动启动 OpenD
# 登录你的 moomoo 账户
```

### 4.4 验证 OpenD 监听 11111

```bash
lsof -i :11111
# 期望: moomoo_Op 62548 chenzhen ... TCP localhost:vce (LISTEN)
```

> ⚠️ OpenD 监听 `localhost:vce`（即 `localhost:11111`）。**这只能在 macOS 访问**。
>
> 要让服务器访问，需要 SSH 反向隧道（见下一节）。

---

## 5. 建立 SSH 反向隧道

### 5.1 为什么需要隧道

- OpenD 只监听 macOS 的 127.0.0.1:11111
- 服务器无法直接访问
- **SSH 反向隧道**：把服务器的 11111 端口转发到 macOS 的 11111
- 服务器连 `127.0.0.1:11111` → sshd 转发 → macOS OpenD

### 5.2 配置 macOS 的 SSH key（让服务器信任）

服务器需要 macOS 公钥：

```bash
# macOS 端（如果有 key 直接拿，没有生成）
ls ~/.ssh/id_ed25519.pub 2>/dev/null || ssh-keygen -t ed25519

# 把公钥加到服务器的 authorized_keys
ssh-copy-id root@147.139.145.89
# 或手动:
cat ~/.ssh/id_ed25519.pub | ssh root@147.139.145.89 'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys'
```

### 5.3 测试隧道（手动）

```bash
# macOS 端：建立反向隧道
ssh -fN -R 11111:127.0.0.1:11111 root@147.139.145.89

# 服务器端验证
ssh root@147.139.145.89 'ss -tln | grep 11111'
# 期望: LISTEN 0 128 127.0.0.1:11111 0.0.0.0:*
```

---

## 6. DSA server 端：环境变量配置

在 `/opt/dsa/.env` 末尾加：

```bash
# Moomoo OpenD 集成 (通过 SSH 反向隧道)
MOOMOO_HOST=127.0.0.1
MOOMOO_PORT=11111
MOOMOO_ENABLED=true
MOOMOO_TIMEOUT=10
```

> 注意：
> - `MOOMOO_HOST=127.0.0.1` — **因为 SSH 隧道在服务器本机 listen 11111**
> - 不需要 `MOOMOO_OAUTH_CLIENT_ID` 等 token
> - OpenD 用 **账户登录态**，不需要 API key

重启容器：

```bash
cd /opt/dsa/docker
docker compose -p daily-stock-analysis up -d --no-deps server
```

---

## 7. DSA 自动启用的功能

`MoomooFetcher` 注册在 `DataFetcherManager`，**最高优先级 P=0**：

| API | 用途 | 触发场景 |
|---|---|---|
| `get_chip_distribution` | 筹码分布（**美/港股替代品**）| 个股分析"数据透视"|
| `get_market_snapshot` | 142 字段实时行情 | 个股实时报价 |
| `get_realtime_quote` | 62 字段轻量报价 | 个股实时报价 |
| `get_history_kline` | 多周期 K 线（日/60m/5m）| 个股技术分析 |
| `get_capital_distribution` | 资金分布（4 档）| 个股资金分布分析 |
| `get_capital_flow` | 资金流向（分钟级）| 个股资金流向 |
| `get_owner_plate` | 所属板块（40+）| 个股板块归类 |
| `get_market_stats` | 大盘宽度数据 | 大盘复盘 |
| `get_main_indices` | 大盘指数 | 大盘复盘（**美/港股不适用**）|

**美/港/A 股都能用**（A 股部分接口可能 SG 账户权限限制）。

---

## 8. macOS 端：launchd 保活

让 SSH 隧道**永远在**（mac 重启/睡眠后自动重连）。

### 8.1 安装 autossh

```bash
brew install autossh
```

### 8.2 创建 launchd plist

`~/Library/LaunchAgents/com.dsa.moomoo-tunnel.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.dsa.moomoo-tunnel</string>

    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/autossh</string>
        <string>-M</string>
        <string>0</string>
        <string>-N</string>
        <string>-o</string>
        <string>ServerAliveInterval=30</string>
        <string>-o</string>
        <string>ServerAliveCountMax=3</string>
        <string>-o</string>
        <string>ExitOnForwardFailure=yes</string>
        <string>-R</string>
        <string>11111:127.0.0.1:11111</string>
        <string>root@147.139.145.89</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>StandardOutPath</key>
    <string>/tmp/dsa-moomoo-tunnel.out.log</string>

    <key>StandardErrorPath</key>
    <string>/tmp/dsa-moomoo-tunnel.err.log</string>
</dict>
</plist>
```

### 8.3 加载

```bash
launchctl load -w ~/Library/LaunchAgents/com.dsa.moomoo-tunnel.plist
```

### 8.4 验证

```bash
launchctl list | grep moomoo-tunnel
# 期望: 12345 0 com.dsa.moomoo-tunnel  (PID + 0 状态)
```

### 8.5 重连

隧道会自动重连。如果不工作：

```bash
launchctl kickstart -k gui/$(id -u)/com.dsa.moomoo-tunnel
```

---

## 9. DSA server 端：watch dog 监控

DSA 端有 watch dog（`/opt/dsa/scripts/moomoo_watchdog.py`），**每 5 分钟**检查隧道状态：

- ✅ 端口 11111 在 listen
- ✅ `MoomooFetcher.health_check()` 返回 True
- ✅ OpenD 登录态正常

**状态变化时**（up → down 或 down → up）发 **Telegram 通知**（可配置其他 channel）。

### 9.1 watch dog 自动运行的 systemd 配置

`/etc/systemd/system/dsa-moomoo-watchdog.service` + `dsa-moomoo-watchdog.timer`：

```ini
[Unit]
Description=DSA Moomoo OpenD Watch Dog
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker exec stock-server python3 /app/scripts/moomoo_watchdog.py
WorkingDirectory=/opt/dsa
Environment=PYTHONPATH=/opt/dsa
```

```ini
[Unit]
Description=Run Moomoo watch dog every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
```

启用：

```bash
systemctl daemon-reload
systemctl enable --now dsa-moomoo-watchdog.timer
systemctl list-timers | grep moomoo
```

### 9.2 配置通知

`.env` 加：

```bash
# Telegram
TELEGRAM_BOT_TOKEN=<your_token>
TELEGRAM_CHAT_ID=<your_chat_id>
TELEGRAM_ENABLED=true

# 或 Email (默认 SMTP)
EMAIL_SENDER=xxx@gmail.com
EMAIL_PASSWORD=<gmail_app_password>
EMAIL_RECEIVERS=your@email.com

# 通知路由
NOTIFICATION_REPORT_CHANNELS=telegram
NOTIFICATION_ALERT_CHANNELS=telegram
NOTIFICATION_SYSTEM_ERROR_CHANNELS=telegram
```

### 9.3 watch dog 工作流

```
[每 5 分钟]
  ↓
检查 1: 11111 端口 listen? (3s socket check)
  ↓ 失败
检查 2: OpenD health? (futU SDK 探活,3s timeout)
  ↓ 失败
2-strike debounce: 连续 2 次失败才发 down 通知
  ↓
发 Telegram "moomoo OpenD 隧道断开" 消息
  ↓
[5 分钟后恢复]
  ↓
发 Telegram "moomoo OpenD 隧道已恢复" 消息
```

---

## 10. 故障排除

### Q1: 隧道断了 (launchd 异常退出)

**症状**：`launchctl list | grep moomoo-tunnel` 显示状态 `1`（异常）。

**修复**：
```bash
launchctl kickstart -k gui/$(id -u)/com.dsa.moomoo-tunnel
sleep 5
ssh root@147.139.145.89 'ss -tln | grep 11111'
# 期望: LISTEN 0 128 127.0.0.1:11111
```

### Q2: 大盘复盘 / AAPL 分析卡 10% (30+ 分钟)

**症状**：`status=processing / progress=10` 一直不变。

**原因**：`OpenQuoteContext()` 构造函数阻塞（不会快速失败）。

**修复**：DSA 已通过 `_ensure_ctx` 加 socket 预检（3s timeout）。**升级到 `7627080` commit 后**会自动避免。

### Q3: 隧道起来但 moomoo 仍连不上

**症状**：
- macOS: `lsof -i :11111` 显示 LISTEN
- 服务器: `ss -tln | grep 11111` 显示 LISTEN
- 但 `docker exec stock-server python3 -c "from data_provider.moomoo_fetcher import MoomooFetcher; f=MoomooFetcher(); print(f.health_check())"` 返回 False

**可能原因**：
- macOS OpenD 还在初始化（刚启动 30 秒内）
- moomoo 账户掉登录（重新登录 mac app）

**修复**：
```bash
# macOS 端：重启 OpenD
pkill -f MoomooOpenD
sleep 5
open -a Moomoo
# 等 OpenD 重新登录
sleep 30
# 重连隧道
launchctl kickstart -k gui/$(id -u)/com.dsa.moomoo-tunnel
```

### Q4: server OOM 后 tunnel 自动恢复

**症状**：服务器重启后 moomoo 数据缺失。

**原因**：server 端 tunnel 是 sshd 维护的，**server 重启后 tunnel 自然断**（保留 sshd listen 但转发失效）。

**修复**：
```bash
# macOS 端
launchctl kickstart -k gui/$(id -u)/com.dsa.moomoo-tunnel
sleep 5
# 验证
ssh root@147.139.145.89 'ss -tln | grep 11111'
```

launchd 5 秒内自动重连。

### Q5: A 股数据从 moomoo 拿不到

**症状**：`get_chip_distribution` 对 A 股返回 None。

**原因**：
- moomoo SG 账户对 A 股可能权限不足
- `get_stock_quote`（轻量版）某些账户 ret=-1

**解决**：
- 自动 fallback 到 `TushareFetcher`（需 token）
- 或 `YfinanceFetcher`（A 股无）
- 或 `EfinanceFetcher`（国内 IP 优先）

**DSA 的 fallback 链**自动处理，无需手动配。

---

## 11. 性能与限制

| 维度 | 限制 |
|---|---|
| **实时性** | < 1 秒（OpenD 实时）|
| **延迟** | ~50ms（SSH 隧道）|
| **并发** | **单连接**（DSA 共用一个 OpenQuoteContext）|
| **A 股** | 部分接口 SG 账户权限不足 |
| **网络要求** | 印尼/海外服务器必须靠 SSH 隧道 |
| **macOS 在线** | 隧道依赖 macOS 在线，**关机 = 断**|
| **资源消耗** | macOS: 50-100MB 内存；服务器: +10MB（看 docker 容器）|

**单连接瓶颈**：
- 大盘复盘 5 区域**串行**调用 moomoo_fetcher（用 5-6 秒）
- 不会触发"OpenD 拒绝"（futu SDK 内部队列）
- 但**高并发**（>10 个并行 task 同时）会卡

---

## 12. 参考

### 项目内
- `data_provider/moomoo_fetcher.py` — MoomooFetcher 实现（`get_chip_distribution` / `get_market_snapshot` / `get_capital_distribution` 等）
- `data_provider/base.py:2506` — `get_market_stats` 走并行 fetcher 模式
- `scripts/moomoo_watchdog.py` — server 端 watch dog
- `requirements.txt` — `futu-api>=10.8.0` 依赖
- `docs/data-source-stability.md` — 其他数据源说明（AkShare/Tushare 等）

### 项目外
- [moomoo OpenAPI 官方页](https://www.moomoo.com/OpenAPI)
- [futu-api Python SDK 文档](https://openapi.futunn.com/futu-api-doc/)
- [autossh 文档](https://www.harding.motd.ca/autossh/)

### 关联 commit
- `1de0e74` — feat(data): 集成 moomoo OpenD
- `5d8beda` — perf(data): 并行 fetcher + AkshareFetcher 12s 超时
- `7627080` — fix(moomoo): _ensure_ctx socket 预检防阻塞
- `8a1a718` — ops(moomoo): server-side watch dog（注意：此 commit 在 server 端，**没**推到 fork）

---

## 附录 A：完整部署 checklist

- [ ] macOS 装 moomoo app
- [ ] 登录 moomoo 账户
- [ ] 验证 `lsof -i :11111` LISTEN
- [ ] `brew install autossh`
- [ ] 创建 `~/Library/LaunchAgents/com.dsa.moomoo-tunnel.plist`
- [ ] `launchctl load -w` 加载
- [ ] 服务器 root SSH key 加到 macOS `~/.ssh/authorized_keys`（或反之）
- [ ] 服务器 `/opt/dsa/.env` 加 MOOMOO_* 4 行
- [ ] 重启容器 `docker compose up -d server`
- [ ] 测试：`docker exec stock-server python3 -c "from data_provider.moomoo_fetcher import MoomooFetcher; f=MoomooFetcher(); print(f.health_check())"`
- [ ] 触发 AAPL 分析验证数据透视有"筹码分布"
- [ ] 启用 watch dog 监控
- [ ] 配置 Telegram / Email 通知
