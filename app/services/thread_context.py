import logging
from typing import Any

logger = logging.getLogger(__name__)


def format_inquiry_thread(messages: list[dict[str, Any]], fallback_content: str = "") -> str:
    if not messages:
        return fallback_content or "記録なし"

    lines: list[str] = []
    last_customer_line = ""

    for msg in messages:
        sender = "お客様" if str(msg.get("senderType")) == "1" else "ショップ"
        created_at = str(msg.get("createdDateTime") or "-").replace("T", " ")[:19]
        body = (msg.get("message") or "").strip()
        images = msg.get("images") or []
        attachment_note = ""
        if images:
            labels = []
            for image in images:
                parts = str(image).split("|")
                labels.append(parts[1] if len(parts) >= 2 else "添付ファイル")
            attachment_note = f"\n添付: {', '.join(labels)}"

        line = f"[{created_at}] {sender}:\n{body or '(本文なし)'}{attachment_note}"
        lines.append(line)
        if sender == "お客様":
            last_customer_line = line

    if last_customer_line:
        lines.append("\n【最後のお客様メッセージ】\n" + last_customer_line)

    return "\n\n".join(lines)


async def fetch_and_format_inquiry_thread(inquiry: dict[str, Any]) -> str:
    shop = inquiry.get("connected_shops")
    fallback_content = inquiry.get("content") or ""

    if not shop or shop.get("platform") != "rakuten" or not inquiry.get("rakuten_inquiry_id"):
        return fallback_content or "記録なし"

    try:
        from app.core.rakuten_client import RakutenRMSClient

        rakuten = RakutenRMSClient(
            service_secret=shop.get("api_key", ""),
            license_key=shop.get("api_secret", "")
        )
        messages = await rakuten.get_inquiry_thread(inquiry["rakuten_inquiry_id"])
        logger.info(
            "[AI Context] inquiry=%s thread_messages=%s",
            inquiry.get("rakuten_inquiry_id"),
            len(messages or []),
        )
        return format_inquiry_thread(messages or [], fallback_content=fallback_content)
    except Exception as exc:
        logger.warning(
            "[AI Context] Failed to fetch inquiry thread for %s: %s",
            inquiry.get("rakuten_inquiry_id"),
            exc,
        )
        return fallback_content or "記録なし"
