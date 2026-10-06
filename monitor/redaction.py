from __future__ import annotations

import re


_REDACTIONS = (
    # Authorization headers and common bearer-style log messages.
    re.compile(r"(?i)(\b(?:authorization|proxy-authorization)\s*[:=]\s*)(?:basic|bearer)\s+[^\s,;]+"),
    # Common key/value secret fields, including quoted JSON values.
    re.compile(
        r'''(?ix)
        ((?:["']?)\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)\b
        (?:["']?)
        \s*[:=]\s*)
        (?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;&]+)
        '''
    ),
    # Telegram bot tokens.
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b"),
    # Credentials embedded in an HTTP(S) URL.
    re.compile(r"(?i)(https?://[^\s/:@]+:)[^\s/@]+(@)"),
)


def redact(text: str) -> str:
    """Best-effort removal of recognizable credentials from one log record."""
    result = text
    result = _REDACTIONS[0].sub(r"\1[REDACTED]", result)
    result = _REDACTIONS[1].sub(r"\1[REDACTED]", result)
    result = _REDACTIONS[2].sub("[REDACTED]", result)
    result = _REDACTIONS[3].sub(r"\1[REDACTED]\2", result)
    return result
