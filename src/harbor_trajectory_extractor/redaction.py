from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any


REDACTED = "[REDACTED]"

# These names denote credentials themselves. Token accounting fields such as
# input_tokens/max_tokens deliberately do not match this exact-name list.
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "bearer_token",
    "callback_token",
    "client_secret",
    "refresh_token",
    "secret_key",
    "token",
    "access_token",
}

_ASSIGNMENT_KEY_PATTERN = (
    r"callback[_-]?token|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"bearer[_-]?token|api[_-]?key|apikey|client[_-]?secret|secret[_-]?key"
)

# Explicit key/value syntax in JSON, YAML, shell assignments, environment
# dumps, and command output. Keep colon matching separate so Python attribute
# syntax such as ``if args.callback_token:`` is never mistaken for a secret.
_JSON_ASSIGNMENT_RE = re.compile(
    rf"(?P<prefix>(?P<quote>[\"'])(?P<key>{_ASSIGNMENT_KEY_PATTERN})(?P=quote)\s*:\s*)"
    r"(?P<value>\[REDACTED\]|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)",
    re.IGNORECASE,
)
_SHELL_ASSIGNMENT_RE = re.compile(
    rf"(?P<prefix>\b(?P<key>{_ASSIGNMENT_KEY_PATTERN})\s*=\s*)"
    r"(?P<value>\[REDACTED\]|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)",
    re.IGNORECASE,
)
_YAML_ASSIGNMENT_RE = re.compile(
    rf"(?P<prefix>^(?P<indent>\s*)(?P<key>{_ASSIGNMENT_KEY_PATTERN})\s*:\s*)"
    r"(?P<value>\[REDACTED\]|[^\s#][^\r\n#]*)",
    re.IGNORECASE | re.MULTILINE,
)
_AUTHORIZATION_RE = re.compile(
    r"(?P<prefix>Authorization\s*:\s*(?:Bearer|Basic)\s+)(?P<value>[^\s,;}]+)",
    re.IGNORECASE,
)
_QUERY_RE = re.compile(
    r"(?P<prefix>[?&](?:token|callback[_-]?token|access[_-]?token|"
    r"refresh[_-]?token|auth[_-]?token|api[_-]?key|apikey)=)"
    r"(?P<value>\[REDACTED\]|[^&#\s]+)",
    re.IGNORECASE,
)
_CREDENTIAL_URL_RE = re.compile(
    r"(?P<prefix>[a-z][a-z0-9+.-]*://[^\s/:@]+:)(?P<value>[^\s/@]+)(?=@)",
    re.IGNORECASE,
)


@dataclass
class RedactionStats:
    total: int = 0
    categories: dict[str, int] = field(default_factory=dict)

    def add(self, category: str, count: int = 1) -> None:
        if count <= 0:
            return
        self.total += count
        self.categories[category] = self.categories.get(category, 0) + count


def _normalized_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _is_placeholder_value(value: str) -> bool:
    plain_value = value.strip().strip('"\'').strip()
    normalized_value = plain_value.upper()
    return bool(
        not plain_value
        or plain_value == REDACTED
        or normalized_value in {"NONE", "NULL", "TRUE", "FALSE"}
        or re.fullmatch(r"(?:\$\{[^}]+\}|\{\{[^}]+\}\}|<[^>]+>)", plain_value)
        or re.fullmatch(
            r"(?:RUN_)?(?:CALLBACK_)?TOKEN|API_?KEY|CLIENT_SECRET|SECRET_KEY",
            normalized_value,
        )
        or plain_value.startswith(("args.", "os.environ", "env.", "config."))
    )


def _redact_match(match: re.Match[str]) -> str:
    value = match.group("value")
    if _is_placeholder_value(value):
        return match.group(0)
    if value.startswith(('"', "'")) and value[-1:] == value[:1]:
        replacement = f"{value[0]}{REDACTED}{value[0]}"
    else:
        replacement = REDACTED
    return f"{match.group('prefix')}{replacement}"


def redact_text(text: str, stats: RedactionStats) -> str:
    patterns = (
        ("authorization", _AUTHORIZATION_RE),
        ("query_parameter", _QUERY_RE),
        ("credential_url", _CREDENTIAL_URL_RE),
        ("json_field", _JSON_ASSIGNMENT_RE),
        ("environment_assignment", _SHELL_ASSIGNMENT_RE),
        ("yaml_field", _YAML_ASSIGNMENT_RE),
    )
    redacted = text
    for category, pattern in patterns:
        count = 0

        def replace(match: re.Match[str]) -> str:
            nonlocal count
            replacement = _redact_match(match)
            if replacement != match.group(0):
                count += 1
            return replacement

        redacted = pattern.sub(replace, redacted)
        stats.add(category, count)
    return redacted


def _redact_value(value: Any, stats: RedactionStats) -> Any:
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _normalized_key(key) in _SENSITIVE_KEYS:
                if item not in (None, "", REDACTED) and not (
                    isinstance(item, str) and _is_placeholder_value(item)
                ):
                    stats.add("structured_field")
                    result[key] = REDACTED
                else:
                    result[key] = item
            else:
                result[key] = _redact_value(item, stats)
        return result
    if isinstance(value, list):
        return [_redact_value(item, stats) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, stats) for item in value)
    if isinstance(value, str):
        return redact_text(value, stats)
    return value


def redact_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], RedactionStats]:
    """Return a sanitized copy without changing message/tool identifiers."""

    stats = RedactionStats()
    redacted = _redact_value(copy.deepcopy(messages), stats)
    assert isinstance(redacted, list)
    return redacted, stats
