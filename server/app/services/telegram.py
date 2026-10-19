"""Telegram Bot API: channel broadcasts, DMs, and the webhook commands (spec §6.5)."""

import logging
import time

import httpx

from ..config import get_settings

log = logging.getLogger("huda")


class TelegramError(RuntimeError):
    pass


def _api(method: str, payload: dict, retries: int = 2) -> dict:
    token = get_settings().telegram_bot_token
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    url = f"https://api.telegram.org/bot{token}/{method}"
    for attempt in range(retries + 1):
        r = httpx.post(url, json=payload, timeout=15)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code == 429 and attempt < retries:
            time.sleep(min(int(data.get("parameters", {}).get("retry_after", 3)), 30))
            continue
        if not data.get("ok"):
            raise TelegramError(data.get("description") or f"HTTP {r.status_code}")
        return data["result"]
    raise TelegramError("rate limited")


def send(chat_id: str | int, text: str) -> int:
    """Send a plain-text message; returns the Telegram message_id."""
    result = _api("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})
    return int(result["message_id"])


def send_channel(text: str) -> int:
    channel = get_settings().telegram_channel_id
    if not channel:
        raise TelegramError("TELEGRAM_CHANNEL_ID is not set")
    return send(channel, text)


def reply_to_channel(text: str, message_id: int) -> int:
    result = _api("sendMessage", {"chat_id": get_settings().telegram_channel_id, "text": text,
                                  "reply_parameters": {"message_id": message_id},
                                  "disable_web_page_preview": True})
    return int(result["message_id"])


def parse_command(update: dict) -> tuple[int | None, str | None, str]:
    """(chat_id, command, argument) from a webhook update, e.g. (123, "/start", "HUDA-7F3K2")."""
    message = update.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return chat_id, None, text
    command, _, arg = text.partition(" ")
    return chat_id, command.split("@")[0].lower(), arg.strip()
