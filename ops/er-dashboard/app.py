#!/usr/bin/env python3
"""
ER Dashboard Server - stdlib HTTP, no Flask dependency
Auto-generates index page listing all *.html files in /opt/er-dashboards/
Smart routing: /<TICKER> -> latest <TICKER>-*.html
Python 3.6+ compatible
"""
import http.server
import socketserver
import json
import os
import re
import urllib.parse
import sys
import time
import subprocess
import threading
import uuid

DASH_DIR = "/opt/er-dashboards"
PORT = 8080
HOST = "0.0.0.0"
LOG_FILE = "/opt/er-dashboard/logs/access.log"
JOB_LOG_FILE = "/opt/er-dashboard/logs/jobs.log"
TRIGGER_SCRIPT = "/opt/er-dashboard/trigger.py"
ER_JOB_TIMEOUT_SECONDS = 1800
JOBS = {}
JOBS_LOCK = threading.Lock()
ER_JOB_LOCK = threading.Lock()

# DSA webUI URL (for the "back to DSA" link in ER service)
DSA_URL = "http://147.139.145.89:8088/"

# Ticker metadata (ticker -> (name, desc, tag, summary))
TICKER_META = {
    "NVDA": ("NVIDIA Corporation", "英伟达 - AI 半导体 / 数据中心 GPU", "t-try", "AI 时代挖金铲垄断者,FY26 净利 +65% / 毛利 74%"),
    "TSM":  ("Taiwan Semiconductor", "台积电 - 半导体代工 70% 份额", "t-wait", "全球代工 70% 份额,2nm 量产领先,1 年涨 93% / P/E 33 透支"),
    "SPCX": ("SpaceX", "Nasdaq: SPCX - 商业航天 + Starlink", "t-wait", "商业航天 + Starlink 全栈,但 P/S 49-69x 是 sector 1.9x 的 33-37x"),
    "RKLB": ("Rocket Lab USA", "小型火箭 + 卫星 + Neutron Q4 2026", "t-watch", "唯一上市小型航天综合玩家,Neutron Q4 2026 是分水岭"),
    "GLW":  ("Corning Inc.", "康宁 - 光通信 / 玻璃基板 / Gorilla Glass", "t-watch", "光纤 / 玻璃基板多元化,AI 数据中心光纤新增 catalyst"),
    "LITE": ("Lumentum Holdings", "光通信 / 激光器 - NVIDIA 投资", "t-watch", "AI 数据中心光通信核心供应商,NVIDIA $2B 投资 + 2026 capex 持续"),
}


def parse_filename(fn):
    """Parse 'TICKER-YYYY-MM-DD.html' -> (ticker, date) or (None, None)."""
    m = re.match(r"^([A-Z]+)-(\d{4}-\d{2}-\d{2})\.html$", fn)
    if m:
        return m.group(1), m.group(2)
    return None, None


def fmt_size(nbytes):
    """Human-readable file size."""
    if nbytes < 1024:
        return "{}B".format(nbytes)
    if nbytes < 1024 * 1024:
        return "{}K".format(nbytes // 1024)
    return "{}M".format(nbytes // 1024 // 1024)


def find_latest_dashboard(ticker):
    """Return (filename, date) of the latest dashboard for the given ticker, or (None, None)."""
    if not os.path.isdir(DASH_DIR):
        return None, None
    matches = []
    for fn in os.listdir(DASH_DIR):
        if not fn.endswith(".html"):
            continue
        tk, dt = parse_filename(fn)
        if tk == ticker and dt:
            matches.append((dt, fn))
    if not matches:
        return None, None
    matches.sort(reverse=True)
    return matches[0][1], matches[0][0]


def escape_html(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def make_job_id(ticker):
    return "{}-{}-{}".format(ticker, int(time.time()), uuid.uuid4().hex[:8])


def update_job(job_id, **updates):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return None
        job.update(updates)
        job["updated_at"] = time.time()
        return dict(job)


def log_job(job_id, status, message=""):
    job = job_status_payload(job_id)
    line = "{} job={} ticker={} status={} message={}\n".format(
        time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        job_id,
        job.get("ticker", ""),
        status,
        str(message).replace("\n", " ")[:1200],
    )
    try:
        os.makedirs(os.path.dirname(JOB_LOG_FILE), exist_ok=True)
        with open(JOB_LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        pass


def job_status_payload(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return {"status": "missing", "message": "任务不存在或服务已重启"}
        return dict(job)


def run_er_job(job_id):
    job = job_status_payload(job_id)
    ticker = job.get("ticker")
    if not ticker:
        update_job(job_id, status="failed", message="任务缺少 ticker", error="missing ticker")
        return

    if not ER_JOB_LOCK.acquire(False):
        message = "已有 ER 深度分析正在运行，本任务已进入队列"
        update_job(job_id, status="queued", message=message)
        log_job(job_id, "queued", message)
        ER_JOB_LOCK.acquire()

    update_job(job_id, status="running", message="正在执行 ER skill: 抓取最新行情、财报、估值和业务数据")
    log_job(job_id, "running", "ER skill started")
    try:
        try:
            process = subprocess.Popen(
                [sys.executable, TRIGGER_SCRIPT, ticker, "--force"],
                cwd="/opt/er-dashboard",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
            )
            output_lines = []
            started_at = time.time()
            for line in iter(process.stdout.readline, ""):
                line = line.rstrip()
                if line:
                    output_lines.append(line)
                if line.startswith("ER_STAGE "):
                    parts = line.split(" ", 2)
                    detail = parts[2] if len(parts) > 2 else line
                    update_job(job_id, message="正在完整执行 ER skill：" + detail)
                elif line.startswith("ER_BATCH "):
                    parts = line.split(" ", 3)
                    detail = parts[2] if len(parts) > 2 else line
                    progress = parts[3] if len(parts) > 3 else ""
                    update_job(job_id, message="正在研究：{} {}".format(detail, progress))
                if time.time() - started_at > ER_JOB_TIMEOUT_SECONDS:
                    process.terminate()
                    message = "{} 分析超过 {} 秒,请稍后重试或查看服务器日志。".format(ticker, ER_JOB_TIMEOUT_SECONDS)
                    update_job(job_id, status="failed", message="ER 分析超时", error=message)
                    log_job(job_id, "failed", message)
                    return
            returncode = process.wait()
            combined_output = "\n".join(output_lines)
        except Exception as exc:
            message = str(exc)[:1200]
            update_job(job_id, status="failed", message="ER 分析启动失败", error=message)
            log_job(job_id, "failed", message)
            return

        if returncode != 0:
            msg = (combined_output or "unknown error")[-4000:]
            update_job(job_id, status="failed", message="ER 分析失败", error=msg)
            log_job(job_id, "failed", msg)
            return

        latest_fn, _ = find_latest_dashboard(ticker)
        if not latest_fn:
            message = "missing dashboard output"
            update_job(job_id, status="failed", message="ER 已运行但没有找到输出文件", error=message)
            log_job(job_id, "failed", message)
            return

        update_job(
            job_id,
            status="completed",
            message="分析完成,正在打开最新报告",
            url="/" + latest_fn,
            stdout=combined_output[-1200:],
            stderr="",
        )
        log_job(job_id, "completed", latest_fn)
    finally:
        ER_JOB_LOCK.release()


def render_loading_page(ticker, job_id):
    safe_ticker = escape_html(ticker)
    safe_job_id = escape_html(job_id)
    api_path = "/api/jobs/" + urllib.parse.quote(job_id)
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} ER 正在分析</title>
<style>
  :root {{
    --bg: #080c17; --panel: #121826; --panel-2: #0f1422; --text: #f8fafc;
    --muted: #8f98ad; --cyan: #00d4ff; --purple: #a855f7; --border: #263244;
    --green: #00ff9c; --red: #ff5f6d;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    min-height: 100vh; margin: 0; display: grid; place-items: center; padding: 28px;
    color: var(--text); background: radial-gradient(circle at 50% 18%, #172033 0, var(--bg) 46%, #050711 100%);
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', Arial, sans-serif;
  }}
  .panel {{
    width: min(760px, 100%); border: 1px solid var(--border); border-radius: 18px;
    background: linear-gradient(180deg, rgba(18,24,38,.96), rgba(12,17,29,.96));
    padding: 34px; box-shadow: 0 30px 90px rgba(0,0,0,.42);
  }}
  .top {{ display: flex; align-items: center; gap: 18px; }}
  .ring {{
    width: 64px; height: 64px; border-radius: 50%; border: 5px solid rgba(0,212,255,.18);
    border-top-color: var(--cyan); animation: spin 1s linear infinite; flex: 0 0 auto;
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  h1 {{ margin: 0; font-size: clamp(30px, 5vw, 48px); letter-spacing: 0; line-height: 1.05; }}
  .sub {{ color: var(--muted); margin-top: 8px; font-size: 15px; }}
  .status {{
    margin-top: 28px; border: 1px solid var(--border); background: var(--panel-2);
    border-radius: 14px; padding: 18px 20px; font-size: 16px;
  }}
  .steps {{ display: grid; gap: 10px; margin-top: 22px; color: var(--muted); }}
  .step {{ display: flex; align-items: center; gap: 10px; }}
  .dot {{ width: 9px; height: 9px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 18px rgba(0,212,255,.7); }}
  .meta {{ margin-top: 24px; color: var(--muted); font-size: 12px; font-family: 'SF Mono', Menlo, monospace; }}
  .error {{ display: none; margin-top: 18px; white-space: pre-wrap; color: #ffd1d6; background: rgba(255,95,109,.08); border: 1px solid rgba(255,95,109,.25); border-radius: 12px; padding: 14px; }}
  .actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 24px; }}
  a, button {{
    color: var(--cyan); background: rgba(0,212,255,.08); border: 1px solid rgba(0,212,255,.34);
    border-radius: 10px; padding: 10px 14px; text-decoration: none; font-weight: 700; cursor: pointer;
  }}
</style>
</head>
<body>
<main class="panel">
  <div class="top">
    <div class="ring" aria-hidden="true"></div>
    <div>
      <h1>正在分析 {ticker}</h1>
      <div class="sub">正在完整执行 Equity Research 深度尽调，完成后会自动跳转到最新报告。</div>
    </div>
  </div>
  <div class="status" id="status">任务已创建，正在排队...</div>
  <div class="steps">
    <div class="step"><span class="dot"></span><span>抓取最新行情、估值和公司基础数据</span></div>
    <div class="step"><span class="dot"></span><span>按 ER skill 生成业务、产业链、竞对、客户验证和监控清单</span></div>
    <div class="step"><span class="dot"></span><span>校验报告日期，防止打开旧版本</span></div>
  </div>
  <pre class="error" id="error"></pre>
  <div class="actions">
    <a href="/">返回 ER 索引</a>
    <button type="button" onclick="poll()">手动刷新状态</button>
  </div>
  <div class="meta">job: {job_id}</div>
</main>
<script>
const statusEl = document.getElementById('status');
const errorEl = document.getElementById('error');
let done = false;
async function poll() {{
  if (done) return;
  try {{
    const res = await fetch('{api_path}', {{ cache: 'no-store' }});
    const data = await res.json();
    statusEl.textContent = data.message || data.status || '正在分析...';
    if (data.status === 'completed' && data.url) {{
      done = true;
      statusEl.textContent = '分析完成，正在打开最新报告...';
      const sep = data.url.includes('?') ? '&' : '?';
      window.location.href = data.url + sep + 'fresh=' + Date.now();
      return;
    }}
    if (data.status === 'failed' || data.status === 'missing') {{
      done = true;
      errorEl.style.display = 'block';
      errorEl.textContent = data.error || data.message || 'ER 分析失败';
      return;
    }}
  }} catch (err) {{
    statusEl.textContent = '正在等待服务器返回状态...';
  }}
  setTimeout(poll, 2000);
}}
poll();
</script>
</body>
</html>"""
    return html.format(ticker=safe_ticker, job_id=safe_job_id, api_path=api_path)


def create_er_job(ticker, start_thread=True):
    ticker = re.sub(r"[^A-Z0-9._-]", "", ticker.upper())
    if not ticker:
        raise ValueError("empty ticker")
    job_id = make_job_id(ticker)
    now = time.time()
    with JOBS_LOCK:
        for existing_id, existing in JOBS.items():
            if existing.get("ticker") == ticker and existing.get("status") in ("queued", "running"):
                return existing_id, render_loading_page(ticker, existing_id)
        stale_ids = [
            existing_id for existing_id, existing in JOBS.items()
            if now - existing.get("updated_at", now) > 86400
        ]
        for stale_id in stale_ids:
            JOBS.pop(stale_id, None)
        JOBS[job_id] = {
            "job_id": job_id,
            "ticker": ticker,
            "status": "queued",
            "message": "正在排队,准备启动 ER 深度分析",
            "created_at": now,
            "updated_at": now,
            "url": None,
            "error": None,
        }
    if start_thread:
        thread = threading.Thread(target=run_er_job, args=(job_id,))
        thread.daemon = True
        thread.start()
    return job_id, render_loading_page(ticker, job_id)


def list_dashboards():
    """Return list of dashboard metadata dicts, sorted by date desc."""
    items = []
    if not os.path.isdir(DASH_DIR):
        return items
    for fn in sorted(os.listdir(DASH_DIR)):
        if not fn.endswith(".html"):
            continue
        ticker, date = parse_filename(fn)
        if not ticker:
            continue
        full = os.path.join(DASH_DIR, fn)
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        meta = TICKER_META.get(ticker, (ticker, "-", "t-watch", ""))
        name, desc, tag, summary = meta
        items.append({
            "filename": fn,
            "ticker": ticker,
            "date": date,
            "size": size,
            "size_fmt": fmt_size(size),
            "name": name,
            "desc": desc,
            "tag": tag,
            "summary": summary,
        })
    items.sort(key=lambda x: x["date"], reverse=True)
    return items


def render_index():
    """Generate the full index HTML page."""
    items = list_dashboards()
    total = len(items)
    latest = items[0]["date"] if items else "-"
    wait_count = sum(1 for x in items if x["tag"] == "t-wait")
    try_count = sum(1 for x in items if x["tag"] == "t-try")
    watch_count = sum(1 for x in items if x["tag"] == "t-watch")

    rows = []
    for x in items:
        rows.append(
            '<tr class="row-link" data-tag="{tag}" data-ticker="{tk}" data-name="{nm}" onclick="window.location=\'/{fn}\'">'
            '<td class="ticker-cell">{tk}</td>'
            '<td class="label"><div class="company-name">{nm}</div><div class="company-meta">{desc}</div></td>'
            '<td>{date}</td>'
            '<td><span class="action-tag {tag}">{taglabel}</span></td>'
            '<td style="text-align:right;">{size}</td>'
            '<td class="arrow-cell">查看 -&gt;</td>'
            '</tr>'.format(
                tag=x["tag"],
                tk=x["ticker"],
                nm=x["name"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
                fn=x["filename"],
                desc=x["desc"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
                date=x["date"],
                taglabel={"t-wait": "等待回调", "t-try": "小仓试错", "t-watch": "观察"}.get(x["tag"], "未分类"),
                size=x["size_fmt"],
            )
        )
    rows_html = "\n".join(rows) if rows else '<tr><td colspan="6" style="text-align:center;color:var(--text-dim);">没有 dashboard</td></tr>'

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Equity Research 看板</title>
<style>
  :root {{
    --bg: #0a0e1a; --bg-2: #0f1320; --card: #141925; --card-hover: #1c2233;
    --text: #e8e8e8; --text-dim: #8a8a9a; --text-bright: #ffffff;
    --yellow: #ffd60a; --purple: #b066ff; --cyan: #00d4ff;
    --border: #1f2937; --border-bright: #2d3a4f;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
    margin: 0; padding: 24px; line-height: 1.5;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  .header {{
    background: linear-gradient(135deg, var(--card) 0%, var(--bg-2) 100%);
    border-radius: 12px; border: 1px solid var(--border-bright);
    padding: 24px 28px; margin-bottom: 20px;
  }}
  .header-row {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }}
  .header h1 {{ margin: 0 0 8px 0; font-size: 28px; color: var(--text-bright); font-weight: 700; }}
  .header .subtitle {{ color: var(--text-dim); font-size: 14px; }}
  .dsa-link {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 8px 14px; border-radius: 8px;
    background: var(--bg-2); border: 1px solid var(--border);
    color: var(--text); text-decoration: none; font-size: 13px;
    transition: all 0.15s;
  }}
  .dsa-link:hover {{ border-color: var(--border-bright); background: var(--card-hover); color: var(--text-bright); }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 20px; }}
  .stat-card {{ background: var(--bg-2); padding: 12px 16px; border-radius: 8px; border: 1px solid var(--border); }}
  .stat-label {{ font-size: 11px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }}
  .stat-value {{ font-size: 22px; font-weight: 700; margin-top: 4px; color: var(--text-bright); font-family: 'SF Mono', monospace; }}
  .stat-value.pos {{ color: #00ff9c; }}
  .stat-value.warn {{ color: var(--yellow); }}
  .stat-value.try {{ color: var(--purple); }}

  .filter-bar {{
    background: var(--card); border-radius: 12px; border: 1px solid var(--border);
    padding: 12px 16px; margin-bottom: 16px;
    display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
  }}
  .search-box {{
    flex: 1; min-width: 200px; background: var(--bg-2);
    border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 12px; color: var(--text); font-size: 14px; outline: none;
  }}
  .search-box:focus {{ border-color: var(--cyan); }}
  .search-box::placeholder {{ color: var(--text-dim); }}
  .filter-pills {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  .filter-pill {{
    padding: 5px 12px; border-radius: 14px;
    background: var(--bg-2); color: var(--text-dim);
    font-size: 12px; cursor: pointer; border: 1px solid var(--border); user-select: none; white-space: nowrap;
  }}
  .filter-pill:hover {{ color: var(--text); }}
  .filter-pill.active {{ background: var(--cyan); color: #000; font-weight: 700; border-color: var(--cyan); }}
  .er-run-btn {{
    height: 36px; padding: 0 14px; border-radius: 8px;
    border: 1px solid rgba(176,102,255,.45); background: rgba(176,102,255,.12);
    color: #d8b4fe; font-weight: 800; cursor: pointer; letter-spacing: .3px;
  }}
  .er-run-btn:hover {{ background: rgba(176,102,255,.22); color: #f3e8ff; }}

  .table-wrap {{ background: var(--card); border-radius: 12px; border: 1px solid var(--border); overflow: hidden; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  thead {{ background: var(--bg-2); border-bottom: 1px solid var(--border-bright); }}
  th {{
    text-align: left; padding: 10px 14px; color: var(--text-dim);
    font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px;
  }}
  td {{ padding: 12px 14px; border-bottom: 1px solid var(--border); font-family: 'SF Mono', monospace; }}
  td.label {{ font-family: inherit; color: var(--text); }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: var(--card-hover); }}
  tr.row-link {{ cursor: pointer; }}
  tr.row-link:hover td:first-child {{ border-left: 3px solid var(--cyan); }}
  .ticker-cell {{ font-size: 16px; font-weight: 800; color: var(--text-bright); letter-spacing: -0.5px; }}
  .company-name {{ color: var(--text); font-size: 13px; }}
  .company-meta {{ color: var(--text-dim); font-size: 11px; margin-top: 2px; }}
  .action-tag {{
    display: inline-block; font-size: 12px; font-weight: 700;
    padding: 4px 10px; border-radius: 4px; letter-spacing: 0.3px;
  }}
  .t-wait {{ background: var(--yellow); color: #000; }}
  .t-try {{ background: var(--purple); color: #fff; }}
  .t-watch {{ background: var(--card-hover); color: var(--text-dim); border: 1px solid var(--border-bright); }}
  .arrow-cell {{ color: var(--cyan); font-weight: 600; text-align: right; }}

  .footer {{
    text-align: center; padding: 20px; color: var(--text-dim);
    font-size: 11px; margin-top: 16px;
  }}
  .footer code {{ background: var(--card); padding: 1px 5px; border-radius: 3px; font-family: 'SF Mono', monospace; color: var(--cyan); }}

  @media (max-width: 768px) {{
    .stats {{ grid-template-columns: repeat(2, 1fr); }}
    .filter-bar {{ flex-direction: column; align-items: stretch; }}
    table, thead, tbody, th, tr, td {{ display: block; }}
    thead {{ display: none; }}
    tr {{ background: var(--bg-2); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; padding: 12px; }}
    td {{ border: none; padding: 4px 0; }}
    td::before {{ content: attr(data-label); color: var(--text-dim); font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; display: block; margin-bottom: 2px; }}
    .ticker-cell {{ font-size: 20px; }}
    .arrow-cell {{ text-align: left; }}
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="header-row">
      <div>
        <h1>ER 看板索引</h1>
        <div class="subtitle">Equity Research 深度尽调 · {total} 只股票 · 自动列出 /opt/er-dashboards/ 所有 HTML</div>
      </div>
      <a href="{dsa_url}" target="_blank" rel="noopener noreferrer" class="dsa-link">
        ← 返回 DSA 日报
      </a>
    </div>
    <div class="stats">
      <div class="stat-card"><div class="stat-label">看板总数</div><div class="stat-value">{total}</div></div>
      <div class="stat-card"><div class="stat-label">最新更新</div><div class="stat-value pos">{latest}</div></div>
      <div class="stat-card"><div class="stat-label">等待回调 / 试错</div><div class="stat-value warn">{wait_count} / {try_count}</div></div>
      <div class="stat-card"><div class="stat-label">观察名单</div><div class="stat-value try">{watch_count}</div></div>
    </div>
  </div>

  <div class="filter-bar">
    <input type="text" class="search-box" id="searchBox" placeholder="输入 ticker / 公司名,点击 ER 生成深度尽调" oninput="filterRows()" onkeydown="if(event.key==='Enter') runER()">
    <button class="er-run-btn" type="button" onclick="runER()" title="完整执行 Equity Research skill">ER</button>
    <div class="filter-pills">
      <span class="filter-pill active" onclick="setFilter(this, 'all')">全部</span>
      <span class="filter-pill" onclick="setFilter(this, 't-wait')">等待回调</span>
      <span class="filter-pill" onclick="setFilter(this, 't-try')">小仓试错</span>
      <span class="filter-pill" onclick="setFilter(this, 't-watch')">观察</span>
    </div>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Ticker</th>
          <th>公司</th>
          <th>日期</th>
          <th>动作</th>
          <th style="text-align:right;">大小</th>
          <th></th>
        </tr>
      </thead>
      <tbody id="tableBody">
        {rows_html}
      </tbody>
    </table>
  </div>

  <div class="footer">
    ER Dashboard Server (stdlib http.server) · Python 3.6+ · 零依赖<br>
    数据源: <code>{DASH_DIR}</code> · 端口: <code>{PORT}</code> · 最后更新: <code>{now}</code><br>
    <span style="color: var(--text-dim); font-size: 10px;">v2: 增加 /&lt;TICKER&gt; 智能路由 + DSA 互链</span>
  </div>
</div>

<script>
  function runER() {{
    const raw = document.getElementById('searchBox').value.trim();
    const ticker = raw.split(/[ \t\r\n]+/)[0].replace(/[^A-Za-z0-9._-]/g, '').toUpperCase();
    if (!ticker) return;
    window.location.href = '/trigger/' + encodeURIComponent(ticker);
  }}
  function filterRows() {{
    const q = document.getElementById('searchBox').value.toLowerCase();
    document.querySelectorAll('#tableBody tr').forEach(r => {{
      const visible = !q || (r.dataset.ticker || '').toLowerCase().includes(q) || (r.dataset.name || '').toLowerCase().includes(q);
      r.style.display = visible ? '' : 'none';
    }});
  }}
  function setFilter(el, val) {{
    document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
    el.classList.add('active');
    document.querySelectorAll('#tableBody tr').forEach(r => {{
      r.style.display = (val === 'all' || r.dataset.tag === val) ? '' : 'none';
    }});
  }}
</script>
</body>
</html>"""

    return html.format(
        total=total,
        latest=latest,
        wait_count=wait_count,
        try_count=try_count,
        watch_count=watch_count,
        rows_html=rows_html,
        DASH_DIR=DASH_DIR,
        PORT=PORT,
        dsa_url=DSA_URL,
        now=time.strftime("%Y-%m-%d %H:%M"),
    )


def render_404(ticker):
    """Render a 404 page for an unknown ticker."""
    html = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>没有 ER 看板</title>
<style>
body {{ background: #0a0e1a; color: #e8e8e8; font-family: -apple-system, sans-serif; margin: 0; padding: 40px; }}
.container {{ max-width: 600px; margin: 0 auto; text-align: center; }}
h1 {{ color: #ff3838; }}
a {{ color: #00d4ff; text-decoration: none; padding: 8px 16px; border: 1px solid #2d3a4f; border-radius: 8px; display: inline-block; margin: 8px; }}
</style></head>
<body><div class="container">
<h1>没有 {ticker} 的 ER 看板</h1>
<p>该股票还没有深度尽调报告。</p>
<p><a href="/">返回看板索引</a> <a href="{dsa_url}" target="_blank">返回 DSA 日报</a></p>
</div></body></html>"""
    return html.format(ticker=ticker, dsa_url=DSA_URL)


def render_dashboard_404(target_path):
    """Render a 404 page for an unknown specific dashboard."""
    html = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>404</title>
<style>
body {{ background: #0a0e1a; color: #e8e8e8; font-family: -apple-system, sans-serif; margin: 0; padding: 40px; }}
.container {{ max-width: 600px; margin: 0 auto; text-align: center; }}
h1 {{ color: #ff3838; }}
a {{ color: #00d4ff; text-decoration: none; padding: 8px 16px; border: 1px solid #2d3a4f; border-radius: 8px; display: inline-block; margin: 8px; }}
</style></head>
<body><div class="container">
<h1>404 - 找不到文件</h1>
<p>请求路径: {path}</p>
<p><a href="/">返回看板索引</a></p>
</div></body></html>"""
    return html.format(path=target_path)


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            body = render_index().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith("/api/jobs/"):
            job_id = urllib.parse.unquote(path.split("/api/jobs/", 1)[1]).strip()
            payload = job_status_payload(job_id)
            status_code = 404 if payload.get("status") == "missing" else 200
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        # === Run real Equity Research skill: /trigger/<TICKER> ===
        if path.startswith("/trigger/"):
            ticker = urllib.parse.unquote(path.split("/trigger/", 1)[1]).strip().upper()
            ticker = re.sub(r"[^A-Z0-9._-]", "", ticker)
            if not ticker:
                self.send_error(400, "Missing ticker")
                return
            try:
                job_id, page = create_er_job(ticker)
            except ValueError:
                self.send_error(400, "Missing ticker")
                return
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        rel = path.lstrip("/")
        if ".." in rel or rel.startswith("/") or "\x00" in rel:
            self.send_error(400, "Bad request")
            return

        # === Smart routing: /<TICKER> -> latest <TICKER>-*.html ===
        if rel and not rel.endswith(".html") and "/" not in rel:
            latest_fn, latest_date = find_latest_dashboard(rel)
            if latest_fn:
                rel = latest_fn  # redirect-style: serve the file
            else:
                body = render_404(rel).encode("utf-8")
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

        full = os.path.join(DASH_DIR, rel)
        if not os.path.isfile(full) or not rel.endswith(".html"):
            body = render_dashboard_404(path).encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError:
            self.send_error(500, "Read error")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        try:
            with open(LOG_FILE, "a") as f:
                f.write("[{}] {}\n".format(
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    self.address_string() + " - " + (fmt % args)
                ))
        except OSError:
            pass


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    print("ER Dashboard Server starting on {}:{}".format(HOST, PORT))
    print("Serving dashboards from: {}".format(DASH_DIR))
    print("Log file: {}".format(LOG_FILE))
    if not os.path.isdir(DASH_DIR):
        print("WARNING: {} does not exist, creating".format(DASH_DIR))
        os.makedirs(DASH_DIR, exist_ok=True)
    server = ThreadedServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
