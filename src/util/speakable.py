import re

# Учитель помечает реплику для озвучки строкой [SAY]: ...
SAY_TAG_RE = re.compile(r"^\s*\[SAY\]\s*:?\s*(.+)$", re.IGNORECASE | re.MULTILINE)

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_MARKUP_RE = re.compile(r"[*_`#]+|<[^>]+>")
_BULLET_RE = re.compile(r"^[\s]*[-•\d.)]+\s*")
_LABEL_RE = re.compile(
    r"^(correct(?:ed)?|fix|example|answer|question|say|try)\s*[:\-–—]\s*",
    re.IGNORECASE,
)

def strip_say_tag(text: str) -> str:
    """Убирает служебную строку [SAY] из текста, который увидит пользователь."""
    if not text:
        return ""
    cleaned = SAY_TAG_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

def extract_speakable_english(text: str, max_chars: int = 200) -> str:
    """Короткая английская реплика учителя для TTS.

    Приоритет у явной строки [SAY]: её модель выделяет сама. Эвристика по
    строкам остаётся фолбэком на случай, когда модель тег не поставила.
    """
    if not text:
        return ""

    tagged = SAY_TAG_RE.findall(text)
    if tagged:
        candidate = _clean_line(tagged[-1])
        if candidate:
            return _fit(candidate, max_chars)

    return _fit(_heuristic(text), max_chars)


def _clean_line(raw: str) -> str:
    line = _MARKUP_RE.sub("", raw).strip()
    line = _BULLET_RE.sub("", line).strip()
    line = _LABEL_RE.sub("", line).strip()
    return re.sub(r"\s+", " ", line).strip()

def _heuristic(text: str) -> str:
    lines = []
    for raw in text.splitlines():
        line = _clean_line(raw)
        if not line:
            continue
        if _CYRILLIC_RE.search(line):
            # Смешанная строка: вырезаем английский хвост после последнего
            # знака препинания, идущего за кириллицей
            line = _english_tail(line)
            if not line:
                continue
        if sum(ch.isalpha() for ch in line) < 3:
            continue
        lines.append(line)

    if not lines:
        return ""

    joined = " ".join(lines[-2:] if len(lines) >= 2 else lines)
    return re.sub(r"\s+", " ", joined).strip()

def _english_tail(line: str) -> str:
    """Достаёт английский фрагмент из строки, где смешаны русский и английский."""
    parts = re.split(r"[:\-–—]\s*", line, maxsplit=1)
    tail = parts[-1].strip() if len(parts) > 1 else ""
    if tail and not _CYRILLIC_RE.search(tail):
        return tail
    # Иначе собираем последовательность слов без кириллицы
    words = line.split()
    kept: list[str] = []
    for word in reversed(words):
        if _CYRILLIC_RE.search(word):
            break
        kept.append(word)
    return " ".join(reversed(kept)).strip(" :-–—")

def _fit(text: str, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    truncated = text[: max_chars - 1]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip(" ,;:-") + "."
