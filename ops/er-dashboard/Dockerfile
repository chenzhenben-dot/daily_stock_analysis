# syntax=docker/dockerfile:1.7
#
# ER Dashboard Server — local OrbStack staging image.
#
# This image is intentionally tiny: the dashboard server is a stdlib
# ``http.server`` process that reads pre-rendered HTML from a mounted
# directory and shells out to ``trigger.py`` only when a user clicks
# the ER button. There is no LLM call inside the dashboard image itself.
#
# Production ER SKILL.md, prompts, and field schema are untouched and
# remain owned by ``ops/er-dashboard/equity-research/SKILL.md``.

FROM python:3.11-slim-bookworm

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /opt/er-dashboard

COPY ops/er-dashboard/app.py /opt/er-dashboard/app.py

# trigger.py is mounted from the host at runtime so local edits to the
# skill pipeline take effect without rebuilding the image. The default
# image therefore exposes only the dashboard server.
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/', timeout=3).status == 200 else 1)"

CMD ["python3", "/opt/er-dashboard/app.py"]