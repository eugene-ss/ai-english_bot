import re

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_MARKUP_RE = re.compile(r"[*_`#]+|<[^>]+>")
_BULLET_RE = re.compile(r"^[\s]*[-•\d.)]+\s*")
_LABEL_RE = re.compile(
    r"^(correct(?:ed)?|fix|example|answer|question|say|try)\s*[:\-–—]\s*",
    re.IGNORECASE,
)

def extract_speakable_english(text: str, max_chars: int = 200) -> str:
    """Достаёт короткую английскую реплику учителя для TTS (лимит Orpheus — 200)."""
    lines = []
    for raw in text.splitlines():
        line = _MARKUP_RE.sub("", raw).strip()
        line = _BULLET_RE.sub("", line).strip()
        line = _LABEL_RE.sub("", line).strip()
        if not line:
            continue
        if _CYRILLIC_RE.search(line):
            continue
        if sum(ch.isalpha() for ch in line) < 3:
            continue
        lines.append(line)

    if not lines:
        return ""

    # Берём последние английские фразы: обычно corrected + question
    joined = " ".join(lines[-2:] if len(lines) >= 2 else lines)
    joined = re.sub(r"\s+", " ", joined).strip()

    if len(joined) <= max_chars:
        return joined

    truncated = joined[: max_chars - 1]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip(" ,;") + "."