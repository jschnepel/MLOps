"""Logging for every service: one `basicConfig` and a redaction filter on the handlers (T11 review note 4).

What the filter removes is every shape a credential takes on its way through this system: `Authorization: Bearer`
and `Basic` values, JWT-shaped strings (ID, access, refresh and logout tokens), the `code`, `state`, `session_state`,
`nonce`, `code_verifier`, `logout_token`, `id_token_hint`, `refresh_token`, `access_token`, `id_token` and
`client_secret` parameters of OIDC exchanges (as `key=value`, `'key': 'value'` or `('key', 'value')`), `password=` and
`postgresql://user:password@` connection strings, `X-Ops-Invocation` handles (SA:566: never logged) and `X-CSRF-Token`
values, `Cookie` headers, the three session cookies' values and Keycloak's own cookies (`KEYCLOAK_*`,
`AUTH_SESSION_ID`). It sits on the handlers, not on a logger: a filter on a parent logger never sees a child's
records (spike §6). It also rewrites the formatted traceback and clears `exc_info`, because an exception's text
bypasses `msg` and uvicorn logs "Exception in ASGI application" with the full chain (spike §6). T28 extends the
same patterns to telemetry.
"""

from __future__ import annotations

import logging
import re
from typing import Final

REDACTED: Final = "[REDACTED]"
_SECRET_KEYS = (
    r"code|state|session_state|nonce|code_verifier|logout_token|id_token_hint|refresh_token|access_token|id_token"
    r"|client_secret|password|ops_session|ops_csrf|ops_login|keycloak_[a-z_]+|auth_session_id\w*|kc_[a-z_]+"
)
# Order matters only where patterns overlap (the authorization rule runs before the bare-JWT rule so a redacted bearer
# is not rewritten twice); each pattern keeps the key and replaces the value. Over-redaction is accepted where a key is
# also an ordinary word: "run state=X", "exit code=1" and "password=" in prose lose their value too.
_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # An Authorization value (Bearer or Basic): 16+ token characters, so "bearer token missing" is left alone.
    (re.compile(r"(?i)(\b(?:bearer|basic)\s+)[A-Za-z0-9._~+/=-]{16,}"), rf"\1{REDACTED}"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), REDACTED),
    # key=value in a query string, a form body or a log line.
    (re.compile(rf"(?i)((?:^|[?&;,\s'\"])(?:{_SECRET_KEYS})=)[^&\s\"'<>;]+"), rf"\1{REDACTED}"),
    # 'key': 'value' or 'key': b'value' in a repr of query params, cookies, a token response or headers.
    (re.compile(rf"(?i)(['\"](?:{_SECRET_KEYS})['\"]\s*:\s*b?['\"])[^'\"]+"), rf"\1{REDACTED}"),
    # ('key', 'value') in a repr of form data (Starlette's FormData, a list of pairs).
    (re.compile(rf"(?i)(\(['\"](?:{_SECRET_KEYS})['\"],\s*b?['\"])[^'\"]+"), rf"\1{REDACTED}"),
    (re.compile(r"(postgres(?:ql)?://[^:/\s@]+:)[^@\s]+@"), rf"\1{REDACTED}@"),
    (re.compile(r"(?i)((?:x-ops-invocation|x-csrf-token)['\"]?\s*[,:=]\s*b?['\"]?)[^\s'\",;}]+"), rf"\1{REDACTED}"),
    (re.compile(r"(?i)(\bcookie['\"]?\s*:\s*)[^\r\n]+"), rf"\1{REDACTED}"),
    (re.compile(r"(\bops_(?:session|csrf|login)=)[^;\s\"'<>]+"), rf"\1{REDACTED}"),
    (re.compile(r"(\b(?:KEYCLOAK_[A-Z_]+|AUTH_SESSION_ID\w*|KC_[A-Z_]+)=)[^;\s\"'<>]+"), rf"\1{REDACTED}"),
)


def redact(text: str) -> str:
    """Return `text` with every credential-shaped value replaced by the marker; ordinary text is unchanged."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Rewrite each record's message and traceback before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact message and traceback in place; never raises and never drops the line."""
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - bad format, mapping args or a raising __str__ must not lose the line
            message = _safe_repr(record.msg, record.args)
        record.msg = redact(message)
        record.args = ()
        if record.exc_info:
            try:
                # Formatter.formatException renders the chain; the redacted text goes where the formatter looks first,
                # and exc_info is cleared so nothing re-renders the original.
                record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            except Exception:  # noqa: BLE001 - an exception whose __str__ raises must not hide the log line
                record.exc_text = "traceback unavailable"
            record.exc_info = None
        return True


def _safe_repr(msg: object, args: object) -> str:
    """Best-effort text for a record whose message cannot be formatted."""
    try:
        return f"{msg!r} {args!r}"
    except Exception:  # noqa: BLE001 - even repr may raise
        return "unformattable log message"


def install(level: int = logging.INFO) -> None:
    """Configure the root logger once and put the filter on every root handler (idempotent)."""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        if not any(isinstance(existing, RedactingFilter) for existing in handler.filters):
            handler.addFilter(RedactingFilter())
