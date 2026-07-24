# AGENTS.md

本文件用于约束本仓库的默认开发流程，目标是减少重复沟通、减少返工，并让改动和当前项目结构保持一致。

如果本文件与仓库中的脚本、工作流、代码现状不一致，以实际可执行内容为准，并在相关改动中顺手修正文档，避免规则继续漂移。

## 1. 硬规则

- 遵循现有目录边界：
  - 后端逻辑优先放在 `src/`、`data_provider/`、`api/`、`bot/`
  - Web 前端改动在 `apps/dsa-web/`
  - 桌面端改动在 `apps/dsa-desktop/`
  - 部署与流水线改动在 `scripts/`、`.github/workflows/`、`docker/`
- 未经明确确认，不执行 `git commit`、`git tag`、`git push`。
- commit message 使用英文，不添加 `Co-Authored-By`。
- 不写死密钥、账号、路径、模型名、端口或环境差异逻辑。
- 优先复用现有模块、配置入口、脚本和测试，不新增平行实现。
- 默认稳定性优先于“顺手优化”；非当前任务直接需要的重构、抽象和基础设施迁移一律克制。
- 新增配置项时，必须同步更新 `.env.example` 和相关文档。
- 涉及用户可见能力、CLI/API 行为、部署方式、通知方式、报告结构变化时，必须同步更新相关文档与 `docs/CHANGELOG.md`。
- 修改报告格式、报告渲染效果或 Web UI 界面时，PR 描述必须附受影响报告 / 页面截图；涉及前后差异时优先附前后对比，无法截图时说明原因与替代可视证据。
- Issue / PR 过程截图、审查截图、一次性验收截图和临时可视证据不得作为仓库文件合入；应放在 PR 描述、PR 评论、GitHub 附件、Actions artifact 或外部可访问证据链接中。产品长期文档确需保留的示意图除外，但文件名和文档语义必须脱离具体 issue / PR 编号。
- `docs/CHANGELOG.md` 的 `[Unreleased]` 段使用**扁平格式**：每条独立一行，格式为 `- [类型] 描述`，类型取值：`新功能`/`改进`/`修复`/`文档`/`测试`/`chore`；**禁止在 `[Unreleased]` 内新增 `### 类目标题`**，以减少并发 PR 的 merge 冲突。发版时由 maintainer 汇总整理成带标题的正式格式。
- `README.md` 只用于项目定位、核心能力总览、快速开始、主要入口、赞助/合作等首页级信息；非必要不更新 README，避免持续膨胀。
- 更细的模块行为、页面交互、专题配置、排障说明、字段契约、实现语义和边界条件，优先更新对应 `docs/*.md` 或专题文档，不写入 README。
- 变更中英双语文档之一时，需评估另一份是否需要同步；若未同步，交付说明里要写明原因。
- 注释、docstring、日志文案以清晰准确为准，不强制要求英文，但应与文件语境保持一致。
- **【证据优先】所有调查结论与完成声明必须按第 10 章“证据优先执行规范”标注证据等级；不得用单一词汇混淆"实现已修复 / 用户问题已修复 / 生产问题已修复"的区别。未经明确确认，不执行 `git commit` / `git push` / `merge` / 生产部署。**
- **【证据优先】所有调查结论与完成声明必须按第 10 章“证据优先执行规范”标注证据等级；不得用单一词汇混淆"实现已修复 / 用户问题已修复 / 生产问题已修复"的区别。未经明确确认，不执行 `git commit` / `git push` / `merge` / 生产部署。**
- **【证据优先】所有调查结论与完成声明必须按第 10 章“证据优先执行规范”标注证据等级；只有当用户要求的最终路径被本轮直接验证后，才能宣称完整完成。未经明确确认，不执行 `git commit` / `git push` / `merge` / 生产部署。**

## 1.1 PR 标题规范（非阻断建议）

- 推荐使用 `<类型>: <修改内容>` 作为 PR 标题，例如 `fix: 修复大盘分析历史记录丢失`，优先类型为 `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci`。
- 标题应描述实际变更内容，建议不添加 `[codex]`、`codex`、`autocode`、`copilot` 或其他工具/agent 来源前缀。
- 该规范仅用于协作可读性与一致性提示，不应单独作为 review process blocker。

## 1.2 贡献质量底线

- 本仓库不接受以堆叠代码量、扩大 diff 面、补丁式响应 review 来替代真实设计收敛的 PR。
- 贡献质量以是否解决明确问题、是否最小化影响面、是否保持现有契约一致、是否覆盖真实风险路径为准；不以新增行数、文件数量、功能宣传或“看起来完整”为准。
- 请不要把本仓库当作低成本试验场、简历展示场或 contribution farming 场所。任何 PR 都必须证明作者理解当前系统契约，并完成基本自审、集成和验证。
- 使用 AI 辅助开发本身不是问题；问题是提交 AI 生成后未经人工语义审查、未验证、未收敛的代码。此类 PR 会按低质量提交处理。
- review 反馈后，不接受只在被指出的位置追加局部 patch。作者必须重新检查同一业务语义涉及的所有入口、配置、测试、文档、workflow 和用户可见路径。
- 如果一个 PR 在多轮 review 后仍持续出现同类契约漂移、重复 fallback、测试绕过真实风险层、PR body 与实际 diff 不一致等问题，维护者可以要求关闭重做，而不是继续逐点 review。

## 2. AI 协作资产治理

- `AGENTS.md` 是仓库内 AI 协作规则的唯一真源。
- `CLAUDE.md` 必须是指向 `AGENTS.md` 的软链接，用于兼容 Claude 生态。
- `.github/copilot-instructions.md` 与 `.github/instructions/*.instructions.md` 是 GitHub Copilot / Coding Agent 的镜像或分层补充；若与本文件冲突，以 `AGENTS.md` 为准。
- 仓库协作 skill 存放在 `.claude/skills/`，分析产物存放在 `.claude/reviews/`；前者可以入库，后者默认视为本地产物。
- 根目录 `SKILL.md` 与 `docs/openclaw-skill-integration.md` 属于产品或外部集成说明，不是仓库协作规则真源。
- 若未来新增 `.agents/skills/` 或其他 agent 专用目录，必须先明确单一真源，再通过脚本或镜像同步；禁止手工长期维护多份同义内容。
- 修改 AI 协作治理资产时，执行：

```bash
python scripts/check_ai_assets.py
```

## 3. 仓库速览

- 项目定位：股票智能分析系统，覆盖 A 股、港股、美股。
- 主流程：抓取数据 -> 技术分析/新闻检索 -> LLM 分析 -> 生成报告 -> 通知推送。
- 关键入口：
  - `main.py`：分析任务主入口
  - `server.py`：FastAPI 服务入口
  - `apps/dsa-web/`：Web 前端
  - `apps/dsa-desktop/`：Electron 桌面端
  - `.github/workflows/`：CI、发布、每日任务
- 核心职责：
  - `src/core/`：主流程编排
  - `src/services/`：业务服务层
  - `src/repositories/`：数据访问层
  - `src/reports/`：报告生成
  - `src/schemas/`：Schema / 数据结构
  - `data_provider/`：多数据源适配与 fallback
  - `api/`：FastAPI API
  - `bot/`：机器人接入
  - `scripts/`：本地脚本
  - `.github/scripts/`：GitHub 自动化脚本
  - `tests/`：pytest 测试
  - `docs/`：文档与说明

## 4. 常用命令

### 运行应用

```bash
python main.py
python main.py --debug
python main.py --dry-run
python main.py --stocks 600519,hk00700,AAPL
python main.py --market-review
python main.py --schedule
python main.py --serve
python main.py --serve-only
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### 后端验证

```bash
pip install -r requirements.txt
pip install flake8 pytest
./scripts/ci_gate.sh
python -m pytest -m "not network"
python -m py_compile <changed_python_files>
```

### Web / Desktop

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build

cd ../dsa-desktop
npm install
npm run build
```

### PR / CI 证据

```bash
gh pr view <pr_number>
gh pr checks <pr_number>
gh run view <run_id> --log-failed
```

## 5. 默认工作流

1. 先判断任务类型：`fix / feat / refactor / docs / chore / test / review`
2. 先读现有实现、配置、测试、脚本、工作流和文档，再动手修改。
3. 识别改动边界：后端 / API / Web / Desktop / Workflow / Docs / AI 协作资产。
4. 先判断是否命中高风险区域：配置语义、API / Schema、数据源 fallback、报告结构、认证、调度、发布流程、桌面端启动链路。
5. 只做和当前任务直接相关的最小改动，不顺手夹带无关重构。
6. 如果发现文档、脚本、工作流描述不一致，优先信任实际代码与工作流，再决定是否顺手修正文档。
7. 改完后按下面的验证矩阵执行检查。
8. 最终交付默认要说明：
   - 改了什么
   - 为什么这么改
   - 验证情况
   - 未验证项
   - 风险点
   - 回滚方式

## 6. 验证矩阵

### CI 覆盖原则

当前仓库 CI 主要包含：

| 检查项 | 来源 | 说明 | 是否阻断 |
| --- | --- | --- | --- |
| `ai-governance` | `.github/workflows/ci.yml` | 校验 `AGENTS.md` / `CLAUDE.md` / `.github` 指令 / `.claude/skills` 关系 | 是 |
| `backend-gate` | `.github/workflows/ci.yml` | 执行 `./scripts/ci_gate.sh` | 是 |
| `docker-build` | `.github/workflows/ci.yml` | Docker 构建与关键模块导入 smoke | 是 |
| `web-gate` | `.github/workflows/ci.yml` | 前端改动时执行 `npm run lint` + `npm run build` | 是（触发时） |
| `network-smoke` | `.github/workflows/network-smoke.yml` | `pytest -m network` + `scripts/test.sh quick` | 否，观测项 |
| `pr-review` | `.github/workflows/pr-review.yml` | PR 静态检查 + AI 审查 + 自动标签 | 否，辅助项 |

若 PR 上已有对应 CI 结果，可直接引用 CI 结论；若 CI 未覆盖改动面，或本地与 CI 环境差异较大，需要补充说明本地验证与缺口。

### 按改动面执行

- Python 后端改动：
  - 适用范围：`main.py`、`src/`、`data_provider/`、`api/`、`bot/`、`tests/`
  - 优先执行：`./scripts/ci_gate.sh`
  - 最低要求：`python -m py_compile <changed_python_files>`
  - 若影响 API、任务编排、报告生成、通知发送、数据源 fallback、认证、调度，交付说明中要写明是否覆盖了对应路径。

- Web 前端改动：
  - 适用范围：`apps/dsa-web/`
  - 默认执行：`cd apps/dsa-web && npm ci && npm run lint && npm run build`
  - 若涉及 API 联调、路由、状态管理、Markdown/图表渲染或认证状态，交付说明中要明确说明联动面和未覆盖风险。

- 桌面端改动：
  - 适用范围：`apps/dsa-desktop/`、`scripts/run-desktop.ps1`、`scripts/build-desktop*.ps1`、`scripts/build-*.sh`、`docs/desktop-package.md`
  - 默认执行：先构建 Web，再构建桌面端
  - 如受平台限制未能完整验证，需要明确说明是否验证了 Web 构建产物、Electron 构建以及 Release 工作流影响。

- API / Schema / 认证联动改动：
  - 适用范围：`api/**`、`src/schemas/**`、`src/services/**`、`apps/dsa-web/**`、`apps/dsa-desktop/**`
  - 至少覆盖对应后端验证 + 受影响客户端构建验证。
  - 若涉及登录、Cookie、会话、轮询状态、字段增删或枚举变化，必须明确写出兼容性影响。

- 文档与治理文件改动：
  - 适用范围：`README.md`、`docs/**`、`AGENTS.md`、`.github/copilot-instructions.md`、`.github/instructions/**`、`.claude/skills/**`
  - 不强制代码测试。
  - 需确认命令、配置项、文件名、工作流名称与实际仓库一致。
  - 改动 AI 协作治理资产时，执行 `python scripts/check_ai_assets.py`。

- 工作流 / 脚本 / Docker 改动：
  - 适用范围：`.github/**`、`scripts/**`、`docker/**`
  - 运行最接近改动面的本地验证。
  - 交付时说明影响了哪条流水线、发布路径或部署路径。
  - 若未执行 Docker / GitHub Actions 相关验证，明确说明原因与潜在风险。

- 网络或三方依赖相关改动：
  - 先跑离线或确定性检查。
  - 优先确认 timeout、retry、fallback、异常文案、降级路径是否仍然成立。
  - 若未执行在线验证，必须明确写出原因。

## 7. 稳定性护栏

- 配置与运行入口：
  - 修改 `.env` 语义、默认值、CLI 参数、服务启动方式、调度语义时，要同时评估本地运行、Docker、GitHub Actions、API、Web、Desktop 的影响。
  - 新配置优先做到“不配置也可运行，配置后增强能力”，避免叠加开关和互斥模式。

- 数据源与 fallback：
  - 修改 `data_provider/` 时，要关注数据源优先级、失败降级、字段标准化、缓存与超时策略。
  - 单一数据源失败不应拖垮整个分析流程，除非需求明确要求 fail-fast。

- API / Web / Desktop 兼容：
  - 改 API / Schema / 认证 / 报告载荷时，要同时检查后端、Web、Desktop 的兼容性。
  - 默认优先追加字段、保留旧字段或提供兼容层，避免无提示破坏现有客户端。

- 报告 / Prompt / 通知：
  - 修改报告结构、Prompt、提取器、通知模板、机器人链路时，要检查上游输入与下游消费方是否仍兼容。
  - 单一通知渠道失败不应拖垮整个分析主流程，除非需求明确要求 fail-fast。
  - 修改 `src/services/image_stock_extractor.py` 中 `EXTRACT_PROMPT` 时，要在 PR 描述中附完整最新 prompt。

- 工作流 / 发布 / 打包：
  - 修改自动 tag、Release、Docker 发布、日常分析或桌面端打包流程时，要评估触发条件、产物路径、权限边界和回滚方式。
  - 自动 tag 默认保持 opt-in：只有 commit title 含 `#patch`、`#minor`、`#major` 才触发版本号更新，除非需求明确要求改变发布策略。

## 8. Issue / PR / Skill 工作流

- 仓库内已有以下 skill，可优先复用：
  - `.claude/skills/analyze-issue/SKILL.md`
  - `.claude/skills/analyze-pr/SKILL.md`
  - `.claude/skills/fix-issue/SKILL.md`
- 如果任务明确是 issue 分析、PR 审查、issue 修复，优先按对应 skill 执行，并将产物保存到 `.claude/reviews/`。
- skill 中的命令、模板、验证顺序和交付结构必须与 `AGENTS.md` 保持一致。
- 每次进行 PR 创建 / 更新、PR 审查或 issue 分析前，必须先同步最新代码基线：先检查工作区状态并执行 `git fetch --all --prune`；若工作区干净且当前分支可 fast-forward，则执行 `git pull --ff-only`。如存在本地改动、冲突状态、未跟踪风险文件或无法 fast-forward，不得强行切分支、stash、reset 或覆盖本地状态；PR 审查 / issue 分析可改用已 fetch 的远端 refs/PR head 做分析，并在分析文档中明确记录未更新本地工作树的原因、当前本地 HEAD 与使用的远端基线；PR 创建 / 更新应先说明当前分支与目标基线差异，必要时请求用户确认 rebase、merge 或继续基于当前分支推进。
- skill 默认优先读取 CI / 工作流证据，再决定是否补本地验证。
- 除上述 PR 创建 / 更新、PR 审查 / issue 分析的安全 fast-forward 同步外，skill 不得默认执行 `git pull`、`git push`、`git tag`、`gh pr create` 等会改变远端或当前分支状态的操作；这些操作必须要求用户确认。
- PR 审查默认顺序：
  1. 必要性
  2. 关联性
  3. 标题建议（`<类型>: <修改内容>`，且不含工具/agent 前缀；不作为硬性阻断项）
  4. 描述完整性（对照 `.github/PULL_REQUEST_TEMPLATE.md`）
  5. 验证证据
  6. 实现正确性
  7. 合入判定
- 对 `fix` 类 PR，必须说明：原问题、根因、修复点、回归风险。
- 合入阻断条件：
  - 正确性或安全性问题
  - 阻断型 CI 未通过
  - PR 描述与实际改动内容实质性矛盾
  - 缺少回滚方案
  - 反复出现未收敛的契约漂移、补丁堆叠或验证证据失真

## 8.1 Review 反馈处理与补丁堆叠禁止

当你处理 review 反馈时，禁止只在 reviewer 点名的位置追加局部 patch 后声称“已全部修复”。你必须先重新理解 reviewer 指出的业务契约，再检查同一语义涉及的所有入口、配置、测试、文档、workflow 和用户可见路径。

收到 review 反馈后，必须按以下顺序处理：

1. 逐条列出 reviewer 指出的原问题。
2. 说明根因，不能只描述“改了哪几行”。
3. 找出同一语义影响的所有相关路径，例如 runtime、API/Web、CLI、diagnostics、workflow、docs、tests。
4. 修复完整契约，而不是只修复当前失败测试或当前评论行。
5. 补充能覆盖 reviewer 反例的回归测试、最终入口验证，或明确说明无法验证的原因。
6. 同步更新 PR body，保证 scope、验证结果、兼容性、风险和回滚方案与当前 head 一致。

如果你无法完成上述收敛，不要继续堆叠补丁，不要声称 ready for merge。应主动说明当前 PR 需要拆分、关闭重做，或请求维护者确认新的最小范围。

以下行为会被视为低质量 PR：

- 用 broad fallback、静默降级、`return False/None/[]` 掩盖不清晰的契约。
- 测试 mock 掉真实风险层，只证明局部实现通过。
- CI 通过后声称问题已关闭，但没有覆盖 reviewer 指出的反例。
- PR body 与实际 diff、验证结果或兼容风险不一致。
- review 后继续追加零散 patch，而不是重新收敛完整语义。
- 同一业务语义在 runtime、Web/API、docs、workflow、tests 中表现不一致。

CI 通过只能说明自动检查通过，不能替代人工语义收敛，也不能单独证明 reviewer 指出的反例已经关闭。

## 9. 交付与发布

- 默认交付结构：
  - `改了什么`
  - `为什么这么改`
  - `验证情况`
  - `未验证项`
  - `风险点`
  - `回滚方式`
- 如果是 `docs` 任务，可直接写：`Docs only, tests not run`，但仍需说明是否核对了命令和文件名。
- 自动 tag 默认不触发，只有 commit title 包含 `#patch`、`#minor`、`#major` 才会触发版本号更新。
- 手动打 tag 必须使用 annotated tag。
- 用户可见变更优先通过 PR 合入，并补齐 label 与验证说明。

## 10. 证据优先执行规范（Evidence-First Execution）

本章是防止“提前宣称完成 / 把 fallback 当成功 / 只修表面问题 / 确认偏差”的硬约束，优先级与第 1 章硬规则相同。所有 AI 协作任务（包括 Claude Code、Copilot、自定义 agent）在与本仓库交互时都必须遵守。

### 10.1 证据状态与完成声明

每一项调查结论、验收结果和完成声明必须先标注证据状态：

| 状态 | 含义 |
| --- | --- |
| **已验证** | 本轮直接执行并取得可复查证据。 |
| **部分验证** | 只覆盖完整链路中的部分环节，剩余环节已明确列出。 |
| **推断** | 根据代码、配置或日志推导，尚未在本轮运行验证。 |
| **未验证** | 本轮没有执行对应验证。 |
| **失败** | 已执行，但结果不符合验收要求。 |

不得把 `部分验证`、`推断`、`未验证` 或 `失败` 改写成“验证通过”。

三种"完成"是**不同结论**，不得用"已修复"一个词混淆：

| 结论 | 含义 | 必要证据 |
| --- | --- | --- |
| **实现已修复** | 代码 / 函数 / 测试已经能稳定复现并通过；**允许**使用这个词，但必须同时注明当前 L3 状态（L3 已验收 / L3 未验收 / L3 受限）。 | L2 已验证 + 必填的 L3 状态栏。 |
| **用户问题已修复** | 用户报告的现象在用户实际入口（L3）被本轮直接复现并消失。 | L3 已验证（WebUI 截图 / API 完整响应 / 数据库最新行 / 通知到达）。 |
| **生产问题已修复** | 用户问题已在**生产环境**复现并消失，且生产 L1 + L2 + L3 都已验证。 | 可唯一定位部署版本的标识（优先 image digest，否则 image tag + commit SHA）+ 生产 health + 用户路径实跑结果。 |

硬性写作约束：

- 报告里**禁止**出现裸 "已修复 / 已完成 / 全部通过" 这种单字收尾而不附证据等级。
- 报告里**禁止**写"用户问题已修复"但 L3 状态是"未验收"——这两种结论**互斥**。
- 报告里**禁止**写"生产问题已修复"但没有给部署版本标识 / health / 用户路径证据——这等同"推断"。
- L3 受限（无 key / 维护窗口不允许）时，必须用"实现已修复，用户路径尚未验收 / 生产路径尚未验收"的措辞，并明确受限原因与下次窗口。

### 10.2 三层验证模型（L1 / L2 / L3）

每项用户可见改动必须区分三层验证，但不能跨层互证：

| 层 | 含义 | 通过能证明 |
| --- | --- | --- |
| **L1 服务层** | 进程、容器、端口、health endpoint、CI workflow 状态。 | 部署与服务存活。 |
| **L2 功能层** | 函数、接口、数据转换、单元 / 集成测试结果。 | 业务语义实现。 |
| **L3 用户结果层** | 用户实际入口（WebUI 截图 / API 完整响应 / 报告文件 / 通知到达 / 数据库最新行）。 | 真实用户体验。 |

硬性规则：

- L1 通过不能证明 L2 / L3 通过（容器 healthy 不代表业务正确）。
- 单元测试通过不能证明真实 WebUI / 生产环境 / 外部数据源正常。
- **只有 L3 经本轮直接验证后，才能把对应改动标记为"用户问题已修复"**。只跑了 pytest 或只跑了容器 health 都不够。
- 如果 L3 不能跑（如生产环境无 LLM key / 第三方接口受限），必须显式写"代码路径 L1 + L2 已验证，L3 因 <具体原因> 暂未验收"，整体结论只能是"实现已修复 / 部分完成"，**不得**说"用户问题已修复"。

### 10.3 禁止用 fallback 证明主链路成功

- fallback 成功**只表示降级机制可用**，不代表主数据源 / 主模型 / 主通知渠道 / 主执行路径正常。
- 主链路失败时必须单独报告：`主路径 <name> 失败、原因 <X>、fallback <Y> 成功、降级持续时间 <T>`。
- 不得因为流程最终返回了内容，就宣称目标数据源或目标能力运行正常。
- 数据源类任务必须尽可能端到端验证：
  `source → fetcher → normalization → schema/payload → API → WebUI / 报告文件`。
- 报告必须列出实际采用的数据源、覆盖样本、时间戳和降级情况。

### 10.4 修复前必须建立证据链

处理 bug 严格按以下顺序：

1. **复现**：先用真实命令（curl / docker logs / 复现脚本）记录用户看到的问题。
2. **保留前态**：保存修复前证据（日志 / payload / 报告 / DB 行 / 容器状态）。
3. **画链路**：把数据 / 行为经过的完整路径列出：`source → fetcher → payload → 模板 / LLM → 报告 → WebUI / 通知`。
4. **提假设**：基于链路给可证伪的根因假设。
5. **验证假设**：用日志 / 测试 / 最小实验确认假设成立；如果假设不成立，重新回到第 3 步。
6. **先红测试**：bug、数据语义、跨市场、fallback、生产故障等高风险修改，在修复前先增加能稳定复现问题的失败测试；测试覆盖离根因最近且不会 mock 掉风险层的最低有效层级。低风险例外按 10.8 说明理由。
7. **最小修复**：只改能改变根因的最少代码；不改无关代码 / 不顺手重构 / 不调整公共 API 风格。
8. **回归**：跑 pytest / vitest / build / smoke，**确认没有引入新失败**。
9. **再走一遍真实入口**：从 WebUI / API / 数据库 / 通知重新走一次，确认 L3 验收。

无法复现用户现场时的处理：

- 如果已经能写出**确定性的失败测试**（输入 → 期望 → 实际，并且实际错误与用户报告一致或同根因），可以基于明确代码根因实施修复。
- 这种情况下**只能报告"实现已修复，用户路径尚未验收"**，**不得**宣称用户问题已解决。
- 如果连确定性失败测试都写不出来，必须先回到第 1 步收集证据或求用户协助复现，**不得**猜测性修改。

### 10.5 防止确认偏差

执行过程中必须主动寻找反证。每条结论都要回答以下反问：

- 哪些现象可能证明当前判断是错的？
- 是否只验证了一个市场 / 一支股票 / 一个正常样本？异常样本会不会崩？
- 是否只看了旧缓存 / 旧报告 / 旧镜像 / 旧容器？证据的时间戳是不是本轮的？
- 测试是否 mock 掉了真正出错的数据源 / 网络层 / 鉴权层？
- 是否存在字段单位、region、source、sample_size、timestamp 等语义漂移（CN vs HK vs US、亿 vs 美元 vs 港元）？
- 是否有另一条入口（其它 endpoint / 其它 tab / 其它后台脚本 / 历史数据迁移）仍在用旧逻辑？
- 推理链路中是否漏掉了某个中间步骤（schema / 模板 / 提示词 / 边界条件）？

**不能只收集支持"已经修好"的证据**。高风险修改至少使用两条独立探针：一条支持原假设，一条尝试证伪；低风险任务可省略，但必须说明理由。

### 10.6 修改范围控制

开始修改前必须先列出修改边界并写进交付说明：

- **允许修改的文件或模块**：明确列出。
- **明确禁止修改的文件或模块**：包含业务代码、本任务外的脚本、其它无关模块。
- **用户已有的未提交和未跟踪文件**：明确列出（含路径），**不得暂存、提交、stash、覆盖或删除**。
- 任何超出允许列表的改动都必须先停下来征求用户确认。

完成后必须检查：

```bash
git status --short
git diff --stat
git diff -- <预期文件>
```

- 不得为了通过测试顺手扩大重构范围。
- 遇到意外工作区改动时，**不得** `git reset --hard` / `git checkout -- <file>` / `git stash` / 覆盖任何用户改动；必须先停下来告知用户并寻求确认。

### 10.7 验收条件是硬约束

开始前必须把用户需求逐条转成可判定的验收项（带数字 / 阈值 / 输出位置 / 关键字），并写进交付说明。

完成报告必须按如下矩阵逐项填写，**逐条列出证据（命令 + 输出片段或截图）**：

| 验收项 | 状态 | 证据 |
| --- | --- | --- |

整体状态枚举（必须取以下四种之一）：

| 状态 | 适用条件 |
| --- | --- |
| **全部完成** | 所有适用的核心验收项已验证；用户可见改动必须包含 L3 用户路径。 |
| **部分完成** | 至少一项核心验收项为部分验证 / 推断 / 未验证，且未声明阻塞。 |
| **被阻塞** | 至少一项核心验收项为失败，需要用户决策才能继续。 |
| **实现完成但尚未验收** | 代码路径 L1 + L2 通过，L3 受限（无 key / 维护窗口不允许 / 第三方接口挂起），需后续窗口继续验收。 |

**禁止**用"全部完成"以外的措辞声称全部完成；**禁止**用"实现完成"以外的措辞声称已验收。

### 10.8 测试要求

测试必须验证业务语义，而不是字符串存在或函数被调用。

强制"先红测试" + "两条独立探针"的最低门槛：**只对 bug / 数据语义 / 跨市场 / fallback / 生产故障等高风险修改**。下列类型可不强制失败测试，但必须**说明理由**：

- 纯文档 / 注释 / 治理文件改动（按 § 6 章"文档与治理文件改动"已经覆盖）。
- 机械确定性修改（重命名、纯导入路径调整、纯字符串修正等），且无业务语义变化。
- 无业务逻辑变化的可视化 / 文案改动（CSS / i18n / 注释）。

测试覆盖层级原则：**离根因最近、不会 mock 掉真正风险层的最低有效层级**。不必每个改动都真实执行完整 WebUI；L3 验收在 § 10.2 / § 10.7 单独列出。

数据单位修复类测试应同时验证：

- 原始值
- 市场 / region
- 换算规则（1e8 vs 1e9 vs 直接拼接）
- payload `total_amount`
- payload `turnover_unit`
- payload `formatted_turnover`
- WebUI / 报告最终显示

数据源修复类测试应同时覆盖：

- 主链路成功
- 主链路失败（异常 / 超时 / 空 history）
- fallback 成功
- 全部失败
- 缓存 / 旧数据命中
- 边界值（0 / 极小 / 极大 / null / 空字符串）

Mock 不得绕开本次真正的风险层。如果本次问题是 Moomoo 跨市场污染，单元测试必须能模拟 "MoomooFetcher 返回 moomoo_us_exchange_universe 数据 + CN 路径调用" 并断言被拒；如果做不到端到端，必须显式声明 L3 未验收。

### 10.9 OrbStack 与生产部署

DSA 默认部署流程：

1. 在 `ops/orbstack-staging` 或相应分支修改代码并本地验证（pytest / vitest / build）。
2. 在 OrbStack 重建镜像（**不能只重启旧容器**），跑离线测试 + 接口 smoke + WebUI 用户路径验收。
3. 记录本轮实际跑的镜像对应的 commit SHA / image digest / 创建时间。
4. **未经用户明确确认，不部署生产**。确认方式：用户在本会话或 issue / PR 评论里明确说"可以部署生产"。
5. 生产部署后重新执行 L1（容器 health）+ L2（接口 smoke）+ L3（用户路径）。
6. 部署前必须确认实际可执行的回滚目标与命令（详见 § 10.11），不强制统一命名。

报告必须分开三段写：

- "**代码已修复**"：只表示 L2 通过。
- "**OrbStack 已验收**"：表示本轮 OrbStack 重建镜像、离线测试、接口 smoke 以及适用的用户路径验收通过。
- "**生产已部署**"：必须给出部署版本标识（优先 image digest，否则 image tag + commit SHA）、容器名、health endpoint 状态、用户路径实跑结果。

**本地通过不得写成生产已修复**。

### 10.10 完成声明限制

说"已修复 / 已完成 / 已部署 / 可以使用"前，必须具备**本轮新鲜证据**：

- 引用旧日志 / 旧截图 / 之前的测试结果 / 别人的完成报告 → 一律无效。
- 验证命令未运行、运行失败、输出不完整 → 必须如实说明。

完成报告必须包括：

- 实际修改（文件 + 行号 + 关键 diff）
- 根因（一句话 + 链路证据）
- 验收矩阵（10.7 的表，逐项状态 + 证据）
- 运行过的命令与结果（关键输出片段）
- 未验证项（明确列出，含原因）
- fallback / 降级情况（实际是否走 fallback / 走的是哪个 / 降级时长）
- 风险（剩余风险 + 触发条件）
- 回滚方法（具体命令 + 实际可执行的回滚目标）
- 工作区状态（`git status --short` 输出）
- 是否 commit / push / deploy（默认都是"未执行"，必须用户授权后才执行）

### 10.11 部署证据 + 回滚要求

部署证据：

- 必须提供当前部署方式能够取得的**唯一版本标识**，**优先 image digest**（如 `sha256:f208c6138c9b4a211b24a3f86ec788df6941180ec67afdcc1fa6221623ed8565`）。
- 当部署方式无法获取 digest（如直接用 image tag）时，至少提供 image tag + commit SHA 组合（如 `v3.27.11 @ 7fcc5f2a`），不能只给 image tag。
- 报告里必须写明：
  - 生产容器当前 image digest 或 tag + commit SHA
  - 容器健康状态（health endpoint 200 / "healthy"）
  - 用户路径实跑结果（WebUI 截图 / API 响应片段 / 数据库最新行）

回滚要求：

- **部署前**必须确认实际可执行的回滚目标（生产 image 仍存在 / compose 备份仍存在 / 数据未变）。
- **不强制**统一命名格式（不再要求 `bak-<image_tag>-<YYYYMMDD>`），但报告中必须写明：
  - 回滚目标的具体内容（image tag / digest / compose 文件路径 / 数据库快照）
  - 回滚命令（具体到能在用户机器上一键执行）
  - 回滚后预期状态（容器健康 / 用户路径）
- 如果回滚目标不可用（例如 image 已被覆盖、compose 备份被删除），必须在部署前报告并征求用户决策。

### 10.12 与其它章节的关系

- 第 1 章硬规则：本章是硬规则的执行细化；冲突时以本章为准。
- 第 6 章验证矩阵：CI / 自动化检查矩阵；与本章互补，CI 通过不等于本章意义上的"已验证"。
- 第 8.1 章 review 处理：禁止"补丁堆叠"与本章"证据链"要求一致；review 后必须重建完整证据链。
- 第 9 章交付与发布：本章进一步约束交付文档必须含验收矩阵和证据等级。
- 第 1.1 / 1.2 节 PR 标题与贡献质量底线：本章不替代，仅补充任务执行期的证据和措辞要求。
