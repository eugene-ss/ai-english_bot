import re

# Telegram отклоняет сообщения длиннее 4096 символов
TELEGRAM_MAX_LEN = 4096

_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)

def escape_html(text: str) -> str:
    """Экранирует HTML и переводит markdown-маркеры LLM в теги Telegram.

    Конвертируются только сбалансированные пары на границах слова: одиночный
    `_` внутри snake_case и висячие маркеры остаются обычным текстом, иначе
    Telegram отклонит сообщение с ошибкой разбора сущностей.
    """
    if not text:
        return ""

    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = _HEADING_RE.sub("", text)
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_STAR_RE.sub(r"<i>\1</i>", text)
    text = _ITALIC_UNDERSCORE_RE.sub(r"<i>\1</i>", text)
    return text

def strip_markup(text: str) -> str:
    """Версия без тегов — фолбэк, когда Telegram не принял HTML."""
    if not text:
        return ""
    without_tags = re.sub(r"<[^>]+>", "", text)
    return (
        without_tags.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )

def split_for_telegram(text: str, limit: int = TELEGRAM_MAX_LEN) -> list[str]:
    """Режет текст на части в рамках лимита Telegram, по возможности по строкам."""
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
