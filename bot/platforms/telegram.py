# -*- coding: utf-8 -*-
"""
===================================
Telegram 平台适配器
===================================

通过 Telegram Bot API 接收你发的消息，路由到 DSA 命令处理器。

支持：
- 长轮询 (getUpdates) 模式（推荐，无需公网 webhook）
- 兼容 webhook 模式（如果服务器有 HTTPS + 公网）

配置要求：
- TELEGRAM_BOT_TOKEN: BotFather 获取的 token
- TELEGRAM_CHAT_ID: 用户私聊 chat_id（与推送通知共用）

使用：
    你: 分析 SNDK
    DSA: ✅ 任务已提交
    ...
    你: (一段时间后)
    DSA: [完整分析报告 markdown]

Telegram 文档：
https://core.telegram.org/bots/api
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

import requests

from bot.platforms.base import BotPlatform
from bot.models import BotMessage, BotResponse, WebhookResponse, ChatType

logger = logging.getLogger(__name__)


class TelegramPlatform(BotPlatform):
    """
    Telegram 平台适配器。

    与钉钉 / 飞书不同，Telegram 默认不需要签名验证（webhook 模式下有 secret_token 可选）。
    推荐使用 polling 模式：bot/telegram_polling.py 持续调用 getUpdates，
    解析后调 handle_webhook 进入 DSA 命令系统。
    """

    TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self):
        # token 从 .env 直接读 (与推送通知共用同一个 bot)
        self._bot_token = (
            os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
            or self._get_token_from_config()
        )
        self._api_timeout = int(os.getenv("TELEGRAM_API_TIMEOUT", "10"))

    @staticmethod
    def _get_token_from_config() -> str:
        try:
            from src.config import get_config
            return (getattr(get_config(), "telegram_bot_token", "") or "").strip()
        except Exception:
            return ""

    @property
    def platform_name(self) -> str:
        return "telegram"

    # ----- 必须实现: 签名验证 (Telegram 用 secret_token) -----

    def verify_request(self, headers: Dict[str, str], body: bytes) -> bool:
        """Telegram webhook 可选 secret_token 验证。

        通过环境变量 TELEGRAM_WEBHOOK_SECRET 设置。
        如果未设置,跳过验证 (polling 模式不需要)。
        """
        secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
        if not secret:
            # polling 模式不验证
            return True

        # Telegram 把 secret 放在 X-Telegram-Bot-Api-Secret-Token header
        request_secret = headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not request_secret:
            logger.warning("[Telegram] Webhook 请求缺少 secret_token header")
            return False
        if request_secret != secret:
            logger.warning("[Telegram] Webhook secret_token 验证失败")
            return False
        return True

    # ----- 验证请求 (Telegram webhook 有时不发) -----

    def handle_challenge(self, data: Dict[str, Any]) -> Optional[WebhookResponse]:
        """Telegram 不发 URL 验证 challenge。"""
        return None

    # ----- 必须实现: 解析消息 -----

    def parse_message(self, data: Dict[str, Any]) -> Optional[BotMessage]:
        """解析 Telegram update 为 BotMessage。

        Telegram update 格式 (来自 getUpdates 或 webhook):
        {
            "update_id": 123456,
            "message": {
                "message_id": 1,
                "from": {"id": 8416338886, "is_bot": false, "first_name": "ZHEN", ...},
                "chat": {"id": 8416338886, "type": "private"},
                "date": 1783173375,
                "text": "分析 SNDK"
            }
        }

        也支持 edited_message / channel_post 等变体。
        """
        # 提取 message (可能是 message / edited_message / channel_post)
        msg = (
            data.get("message")
            or data.get("edited_message")
            or data.get("channel_post")
            or data.get("edited_channel_post")
        )
        if not msg:
            logger.debug(f"[Telegram] update {data.get('update_id')} 无 message 字段,跳过")
            return None

        # 必须是文本消息
        text = msg.get("text", "")
        if not text:
            logger.debug(f"[Telegram] 非文本消息,跳过")
            return None

        # 提取 sender 信息
        sender = msg.get("from", {})
        user_id = str(sender.get("id", ""))
        user_name = (
            sender.get("username")
            or f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip()
            or user_id
        )

        # 提取 chat 信息
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        chat_type_raw = chat.get("type", "")
        # private / group / supergroup / channel
        if chat_type_raw == "private":
            chat_type = ChatType.PRIVATE
        elif chat_type_raw in ("group", "supergroup"):
            chat_type = ChatType.GROUP
        else:
            chat_type = ChatType.UNKNOWN

        # 时间戳
        unix_ts = msg.get("date", 0)
        try:
            timestamp = datetime.fromtimestamp(int(unix_ts))
        except (ValueError, TypeError):
            timestamp = datetime.now()

        # 提取 entities (mentions)
        entities = msg.get("entities", [])
        mentions = []
        mentioned = False
        for ent in entities:
            if ent.get("type") == "mention":
                mentioned = True
                # 提取 @username 文本
                offset = ent.get("offset", 0)
                length = ent.get("length", 0)
                if offset is not None and length:
                    mention_text = text[offset : offset + length]
                    mentions.append(mention_text)

        return BotMessage(
            platform=self.platform_name,
            message_id=str(msg.get("message_id", "")),
            user_id=user_id,
            user_name=user_name,
            chat_id=chat_id,
            chat_type=chat_type,
            content=text,
            raw_content=text,
            mentioned=mentioned,
            mentions=mentions,
            timestamp=timestamp,
            raw_data=data,
        )

    # ----- 必须实现: 格式化响应 -----

    def format_response(
        self, response: BotResponse, message: BotMessage
    ) -> WebhookResponse:
        """polling 模式不用,但保留以兼容。

        Webhook 模式:直接返回响应让 Telegram 立即显示。
        """
        if not response.text:
            return WebhookResponse.success()

        # Telegram webhook 不能直接返回消息 (只能 200),所以这是个空操作
        # 实际响应通过 send_followup 发
        return WebhookResponse.success()

    # ----- 异步发送 (polling 模式用这个) -----

    def send_followup(
        self, response: BotResponse, message: BotMessage
    ) -> bool:
        """通过 Telegram Bot API 发送消息给原 chat。

        命令处理完成后调用,异步推送结果。
        """
        if not self._bot_token:
            logger.error("[Telegram] 未配置 TELEGRAM_BOT_TOKEN,无法发送")
            return False

        if not response.text:
            logger.debug("[Telegram] 响应文本为空,跳过发送")
            return True

        chat_id = message.chat_id
        if not chat_id:
            logger.error("[Telegram] 消息无 chat_id,无法发送")
            return False

        # Telegram 消息限 4096 字符,长消息要分片
        text = response.text
        MAX_LEN = 4000  # 留 96 字符 buffer
        chunks = [text[i : i + MAX_LEN] for i in range(0, len(text), MAX_LEN)] or [""]

        for idx, chunk in enumerate(chunks):
            try:
                url = self.TELEGRAM_API_BASE.format(
                    token=self._bot_token, method="sendMessage"
                )
                resp = requests.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    },
                    timeout=self._api_timeout,
                )
                data = resp.json()
                if not data.get("ok"):
                    err = data.get("description", "unknown")
                    logger.error(
                        f"[Telegram] sendMessage 失败 (chunk {idx+1}/{len(chunks)}): {err}"
                    )
                    # Markdown 解析失败时,回退纯文本
                    if "can't parse" in err.lower() or "parse_mode" in err.lower():
                        if self._retry_plain_text(chat_id, chunk):
                            continue
                    return False
                logger.debug(
                    f"[Telegram] 消息已发送 (chunk {idx+1}/{len(chunks)}) → chat {chat_id}"
                )
            except requests.Timeout:
                logger.error(f"[Telegram] sendMessage 超时 (chunk {idx+1})")
                return False
            except Exception as exc:
                logger.error(f"[Telegram] sendMessage 异常: {exc}")
                return False

        return True

    def _retry_plain_text(self, chat_id: str, text: str) -> bool:
        """Markdown 解析失败时,fallback 到纯文本。"""
        try:
            url = self.TELEGRAM_API_BASE.format(
                token=self._bot_token, method="sendMessage"
            )
            resp = requests.post(
                url,
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=self._api_timeout,
            )
            return resp.json().get("ok", False)
        except Exception:
            return False
