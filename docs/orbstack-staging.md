# OrbStack 本地预发布环境

本文档说明 `dsa-fork` 的本地 OrbStack 预发布编排。**该环境与生产完全隔离**，
**不会触碰生产服务器、生产数据、Telegram Bot、Moomoo OpenD 或 ER SKILL.md**。

## 拓扑

| 组件 | 生产（阿里云） | 本地 OrbStack 预发布 |
| --- | --- | --- |
| DSA Web/API | `stock-server`，绑定公网 | `dsa-local`，仅 `127.0.0.1:18088` |
| DSA Telegram Bot | `dsa-telegram-bot`，长轮询 | **不启动**（避免同一 Token 多实例） |
| DSA 定时调度 | `runtime_scheduler` + `.env SCHEDULE_TIME` | `--serve-only --no-notify`，CLI 关闭 |
| DSA 通知 | Telegram / 邮件 / webhook | `--no-notify`，本地不推送 |
| ER Dashboard | `er-dashboard`（裸机 systemd） | `er-dashboard-local`，仅 `127.0.0.1:18080` |
| cloudflared | 系统服务暴露公网 | **不启动** |
| Moomoo OpenD | Mac 原生进程 + SSH 反向隧道 | **不在 Compose 中管理**，按需由 Mac 原生提供 |

## 访问地址

- DSA 预发布：http://127.0.0.1:18088/
- ER 预发布：http://127.0.0.1:18080/

两个端口只绑定 loopback，不会暴露到局域网。

## 文件结构

```
docker/docker-compose.orbstack.yml   # 本地编排（唯一入口）
ops/er-dashboard/Dockerfile          # ER dashboard 镜像定义
.env.orbstack.example                # 变量名 + 安全占位
.env.orbstack.local                  # 本地真实配置（git 忽略）
.orbstack/                           # 数据 / 日志 / 报告（git 忽略）
scripts/orbstack-up.sh               # 构建并启动
scripts/orbstack-down.sh             # 停止（保留数据）
scripts/orbstack-smoke.sh            # 健康检查
docs/orbstack-staging.md             # 本文档
```

## 启动 / 停止 / 重建

```bash
# 启动（首次会自动构建本地 arm64 镜像）
./scripts/orbstack-up.sh

# 查看日志
docker compose -f docker/docker-compose.orbstack.yml logs -f dsa-local
docker compose -f docker/docker-compose.orbstack.yml logs -f er-local

# 健康检查
./scripts/orbstack-smoke.sh

# 停止（数据保留在 .orbstack/）
./scripts/orbstack-down.sh

# 重建镜像（DSA 依赖或 Dockerfile 变化后）
docker compose -f docker/docker-compose.orbstack.yml build dsa-local er-local

# 完全清理本地数据（慎重）
# rm -rf .orbstack/
```

## 隔离保证

1. **容器名**：本地使用 `dsa-local`、`er-dashboard-local`，**不与生产
   `stock-server` / `dsa-telegram-bot` 同名**，避免误操作。
2. **数据目录**：本地全部落在 `.orbstack/`，**生产 `data/ logs/ reports/`
   不会被挂载或复制**。
3. **环境变量**：本地真实配置走 `.env.orbstack.local`（`.gitignore`），
   `.env.example` 的现有示例不包含任何生产 Secret，本地示例也只放占位。
4. **网络**：端口只绑 `127.0.0.1`，没有 `network_mode: host`，本机外网不可达。
5. **重启策略**：`restart: no`，本机启动后不会因 Docker 自启而意外拉起。
6. **scheduler / notify**：`dsa-local` 通过 `--serve-only --no-notify`
   显式关闭，**与生产 `docker-compose.yml` 的 `serve-only` 命令一致**，
   没有引入新行为。

## 生产兼容性

- ER SKILL.md / 提示词 / 字段：**完全未触碰**。
- ER `trigger.py` / `equity-research/`：**以 `ro` 挂入**，本地修改立即生效；
  不通过 build 拷贝，确保生产路径与本地路径同一份代码。
- `docker/Dockerfile`、`docker/docker-compose.yml`、
  `docker/docker-compose.server-image.yml`：**未修改**。
- `main.py`：**未修改**；本地只是复用现有 CLI 参数 `--serve-only --no-notify`。

## 手动构建 linux/amd64 生产候选镜像（按需）

默认情况下本地构建走 OrbStack 自带的 Linux VM，**架构与本机一致（arm64）**，
适合本机本地预发布。

需要把代码做成生产候选（`linux/amd64`，供阿里云服务器拉取）时，**不要在本
Compose 中自动执行**——它会消耗几分钟的交叉构建时间。按需手动执行：

```bash
docker buildx build \
  --platform linux/amd64 \
  -f docker/Dockerfile \
  -t ghcr.io/chenzhenben-dot/daily_stock_analysis:orbstack-candidate \
  --push \
  .
```

仅在确实需要给生产服务器替换镜像时执行，并单独走人工评审。

## 本地预发布通过后

本地一切绿灯之后，**生产发布仍需单独人工确认**：

1. 在 PR 中评审本分支 `ops/orbstack-staging` 的改动。
2. 确认生产发布窗口、变更日志、回滚预案。
3. 由维护者手动触发生产镜像发布流程，**不在本分支内自动合并到 `main`**。