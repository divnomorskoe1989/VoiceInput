from __future__ import annotations

import re

# Pre-compiled patterns — avoids recompilation on every call
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[Vv]oice\s+[Ii]nput\b"), "VoiceInput"),
    (re.compile(r"\b1\.\s+0\b"), "1.0"),
    (re.compile(r"(?i)(сочетание\s+)ctrl[\+\s]*v\b"), r"\1Ctrl+Win"),
    (re.compile(r"(?i)(по\s+)ctrl[\+\s]*v\b"), r"\1Ctrl+Win"),
    (re.compile(r"(?i)\btest\s+example\.?\s*com\b"), "test@example.com"),
    (re.compile(r"(?i)\bautostop\b"), "автостоп"),
    (re.compile(r"\bавто\s+стоп\b", re.IGNORECASE), "автостоп"),
    (re.compile(r"(?i)\bточка\s+с\s+запятой\b"), ";"),
    (re.compile(r"(?i)\bвосклицательный\s+знак\b"), "!"),
    (re.compile(r"(?i)\bвопросительный\s+знак\b"), "?"),
    (re.compile(r"(?i)\bдвоеточие\b"), ":"),
    (re.compile(r"(?i)\bзапятая\b"), ","),
    (re.compile(r"(?i)\bточка\b"), "."),
    (re.compile(r"(?i)\bвопрос\b"), "?"),
    (re.compile(r"(?i)\bвосклицание\b"), "!"),
    (re.compile(r"(?i)\bтире\b"), " - "),
    (re.compile(r"\s+([,.;:!?])"), r"\1"),
    (re.compile(r"([,.;:!?])([A-Za-zА-Яа-я0-9])"), r"\1 \2"),
    (re.compile(r"\b1\.\s+0\b"), "1.0"),
    (re.compile(r"\b1\.0\s+скорость\b", re.IGNORECASE), "1.0: скорость"),
    (re.compile(r"([а-яА-Я0-9])\s+(Нужно\b)"), r"\1. \2"),
    (re.compile(r"(?i)\btest@example\.\s*com\b"), "test@example.com"),
    (re.compile(r"[ \t]{2,}"), " "),
]


def normalize_transcript_text(text: str) -> str:
    if not text:
        return ""

    value = text.replace("\u00a0", " ")
    for pattern, replacement in _RULES:
        value = pattern.sub(replacement, value)
    return value.strip()
