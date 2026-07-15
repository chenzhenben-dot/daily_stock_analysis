#!/usr/bin/env python3
"""
===================================
Telegram Bot 长轮询 daemon
===================================

用 Telegram Bot API 的 getUpdates 端点持续轮询，
收到你发的消息后调 DSA 命令系统处理。

优势：
- 不需要公网 IP / 域名 / HTTPS
- 不需要 Webhook
- systemd 启动，挂了自动重启
- 跟 DSA 其他 channel（email / moomoo watch dog）解耦

依赖：
pip install requests

使用：
    .venv-moomoo/bin/python bot/telegram_polling.py
    # 或在 Docker 容器内
    docker exec -d stock-server python3 /app/bot/telegram_polling.py

环境变量：
- TELEGRAM_BOT_TOKEN: BotFather 给的 token（必填）
- TELEGRAM_POLLING_TIMEOUT: 长轮询超时秒数（默认 30）
- TELEGRAM_POLLING_INTERVAL: 轮询间隔秒数（默认 1）
- TELEGRAM_DROP_PENDING_UPDATES: 启动时跳过历史积压消息（默认 true）
- LOG_LEVEL: INFO / DEBUG
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# 把项目根目录加到 sys.path,让 bot.* 能 import
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.dispatcher import get_dispatcher  # noqa: E402
from bot.platforms.telegram import TelegramPlatform  # noqa: E402

logger = logging.getLogger("telegram_polling")

API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _api(token: str, method: str) -> str:
    return API_BASE.format(token=token, method=method)


def get_updates(token: str, offset: Optional[int], timeout: int) -> List[Dict[str, Any]]:
    """调 Telegram getUpdates 拉取新消息。

    long polling: Telegram 保持连接 timeout 秒,期间有新消息立即返回。
    offset: 只返回 update_id > offset 的消息,避免重复处理。
    """
    params: Dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "edited_message"]}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(_api(token, "getUpdates"), params=params, timeout=timeout + 10)
    data = resp.json()
    if not data.get("ok"):
        logger.error("getUpdates failed: %s", data)
        return []
    return data.get("result", [])


def offset_after_pending_updates(updates: List[Dict[str, Any]]) -> Optional[int]:
    """Return the first update id after a batch of already-pending messages."""
    update_ids = [item.get("update_id") for item in updates]
    valid_ids = [update_id for update_id in update_ids if isinstance(update_id, int)]
    return max(valid_ids) + 1 if valid_ids else None


def process_update(platform: TelegramPlatform, update: Dict[str, Any]) -> None:
    """处理单条 Telegram update。"""
    update_id = update.get("update_id")
    chat_id = (
        (update.get("message") or update.get("edited_message") or {})
        .get("chat", {})
        .get("id")
    )
    logger.info("收到 update_id=%s chat_id=%s", update_id, chat_id)

    try:
        # 走 DSA 通用 handle_webhook (跟 webhook 模式同一条路径)
        bot_message, _ = platform.handle_webhook(
            headers={},  # polling 模式没 header
            body=b"",
            data=update,
        )
        if not bot_message:
            logger.debug("update_id=%s 非文本消息,跳过", update_id)
            return
    except Exception as exc:
        logger.exception("处理 update_id=%s 异常: %s", update_id, exc)
        return

    # 调 DSA 命令系统
    dispatcher = get_dispatcher()
    try:
        logger.info("dispatch: content=%r", bot_message.content[:80])
        response = dispatcher.dispatch(bot_message)
        logger.info(
            "dispatch 完成: text_len=%d",
            len(response.text or ""),
        )
    except Exception as exc:
        logger.exception("dispatch 异常: %s", exc)
        from bot.models import BotResponse

        response = BotResponse.error_response(f"❌ 命令处理失败: {exc}")

    # 把结果 send_followup 回 Telegram
    try:
        sent = platform.send_followup(response, bot_message)
        logger.info("send_followup: %s", "OK" if sent else "FAILED")
    except Exception as exc:
        logger.exception("send_followup 异常: %s", exc)


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.error("未配置 TELEGRAM_BOT_TOKEN 环境变量")
        return 1

    timeout = int(os.getenv("TELEGRAM_POLLING_TIMEOUT", "30"))
    interval = int(os.getenv("TELEGRAM_POLLING_INTERVAL", "1"))

    platform = TelegramPlatform()
    if not platform._bot_token:
        logger.error("TelegramPlatform 未能加载 token")
        return 1

    # 优雅退出
    running = True

    def _stop(signum, frame):
        nonlocal running
        logger.info("收到信号 %s,准备退出", signum)
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    logger.info(
        "Telegram bot polling daemon 启动 (token=...%s, timeout=%ds, interval=%ds)",
        token[-6:],
        timeout,
        interval,
    )

    offset: Optional[int] = None
    drop_pending = os.getenv("TELEGRAM_DROP_PENDING_UPDATES", "true").lower() not in {
        "0", "false", "no", "off",
    }
    if drop_pending:
        try:
            # A negative offset asks Telegram for only the newest queued update
            # and confirms all older updates, preventing stale commands on deploy.
            pending = get_updates(token, -1, 0)
            offset = offset_after_pending_updates(pending)
            if offset is not None:
                logger.info("已跳过启动前积压的 Telegram 消息")
        except Exception as exc:
            logger.error("清理 Telegram 积压消息失败: %s", exc)
            return 1

    while running:
        try:
            updates = get_updates(token, offset, timeout)
        except requests.Timeout:
            # long polling 正常超时 (无新消息)
            continue
        except Exception as exc:
            logger.error("getUpdates 异常: %s", exc)
            time.sleep(interval * 5)
            continue

        if not updates:
            continue

        for update in updates:
            update_id = update.get("update_id")
            if offset is None or update_id >= offset:
                offset = update_id + 1
            process_update(platform, update)

        # 处理完后短暂 sleep (避免 429 限流)
        time.sleep(interval)

    logger.info("退出 polling daemon")
    return 0


if __name__ == "__main__":
    sys.exit(main())
