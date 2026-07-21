# syntax=docker/dockerfile:1.7
#
# ER Dashboard Server — OrbStack 本地预发布完整不可变镜像。
#
# 镜像内打包：
#   /opt/er-dashboard/app.py
#   /opt/er-dashboard/trigger.py
#   /opt/er-dashboard/equity-research/SKILL.md
#   /opt/er-dashboard/equity-research/references/dashboard-template.html
#   /opt/er-dashboard/equity-research/references/dashboard-generator.py
#
# 不打包：
#   - 任何 API Key / Token / 生产 .env / 生产数据 / 历史报告。
#   - 宿主机源码 bind mount（compose 中已全部移除）。
#
# ER SKILL.md / 提示词 / 研究阶段 / 字段 / 内容质量规则保持原状。

FROM python:3.11-slim-bookworm

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# trigger.py 当前只使用 Python 标准库；保留 curl 以便 healthcheck 与 smoke 使用。
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/er-dashboard

# ER dashboard server
COPY ops/er-dashboard/app.py /opt/er-dashboard/app.py

# ER trigger pipeline (完整不可变；运行时不依赖宿主挂载)
COPY ops/er-dashboard/trigger.py /opt/er-dashboard/trigger.py

# ER SKILL.md + 模板 + 生成器（references 目录整体带入）
COPY ops/er-dashboard/equity-research /opt/er-dashboard/equity-research

# 保证 dashboard 输出目录存在并可写；本地通过 volume 挂入 .orbstack/er/dashboards，
# 这里只创建空目录作为默认占位。
RUN mkdir -p /opt/er-dashboards /opt/er-dashboard/logs /opt/er-dashboard/jobs

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/ | grep -Eq '^2[0-9]{2}$$' || exit 1

CMD ["python3", "/opt/er-dashboard/app.py"]