import re

def escape_html(text: str) -> str:
    """Экранирует HTML и переводит markdown-маркеры LLM в теги Telegram."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"_(.*?)_", r"<i>\1</i>", text)
    return text
