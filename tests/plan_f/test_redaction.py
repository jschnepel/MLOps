"""The core logging redaction filter (T11 review note 4; SA:566: `X-Ops-Invocation` is never logged; BUILD_SPEC
§9: no credentials in logs). A canary stands in for every secret shape the services handle.

Catches: a filter on a logger rather than a handler (child records bypass it, spike §6), an exception whose text
carries a token (`exc_info` bypasses `msg`), an access line with `?code=`, a connection string with a password, a
cookie header, and an invocation handle.
"""

import io
import logging

from ops_core import redaction
from ops_core.redaction import REDACTED, RedactingFilter, redact

CANARY = "CANARYc4f7e2d81a9b03"  # 20 characters: the Authorization rule redacts 16+ (shorter words are prose)


def capture() -> tuple[logging.Logger, io.StringIO]:
    logger = logging.getLogger("ops_test.redaction")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    return logger, stream


def test_every_secret_shape_is_redacted_in_messages_and_tracebacks() -> None:
    logger, stream = capture()
    child = logging.getLogger("ops_test.redaction.child")  # a child record must pass the parent's handler filter
    shapes = [
        f'127.0.0.1:50872 - "GET /auth/callback?code={CANARY}&state={CANARY}&session_state={CANARY} HTTP/1.1" 200',
        f"Authorization: Bearer {CANARY}",
        f"eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOi{CANARY}.{CANARY}sig",
        f"postgresql://api:{CANARY}@127.0.0.1:15432/ops",
        f"host=127.0.0.1 password={CANARY} user=api",
        f"X-Ops-Invocation: {CANARY}",
        f"headers={{'x-ops-invocation': '{CANARY}'}}",
        f"Cookie: ops_session={CANARY}; ops_csrf={CANARY}",
        f"set-cookie ops_login={CANARY}; Path=/",
        f"logout_token={CANARY}&id_token_hint={CANARY}&refresh_token={CANARY}",
        f"Authorization: Basic {CANARY}",  # authlib's client_secret_basic and the end-session call
        f"client_secret={CANARY}&grant_type=client_credentials",
        f"X-CSRF-Token: {CANARY}",
        f"params={{'code': '{CANARY}', 'state': '{CANARY}'}}",
        f"cookies={{'ops_session': '{CANARY}'}}",
        f"OAuth2Token({{'access_token': '{CANARY}', 'expires_in': 300}})",
        f"code_verifier={CANARY}&nonce={CANARY}",
        f"{{'password': '{CANARY}', 'logout_token': b'{CANARY}'}}",
        f"FormData([('logout_token', '{CANARY}')])",
        f"KEYCLOAK_IDENTITY={CANARY}; AUTH_SESSION_ID={CANARY}",
        f"raw_headers=[(b'x-ops-invocation', b'{CANARY}')]",  # the ASGI scope's header tuples
        f"headers=[('x-csrf-token', '{CANARY}')]",
        f"cookies={{'KEYCLOAK_IDENTITY': '{CANARY}'}}",
        f"AUTH_SESSION_ID_LEGACY={CANARY}",
    ]
    for shape in shapes:
        child.info("%s", shape)
    try:
        raise RuntimeError(f"upstream said: Bearer {CANARY}")
    except RuntimeError:
        logger.exception("exchange failed for ?code=%s", CANARY)
    out = stream.getvalue()
    assert CANARY not in out
    assert out.count(REDACTED) >= len(shapes) + 2
    assert "RuntimeError" in out and "Traceback" in out  # the traceback survives, redacted
    assert "GET /auth/callback?code=" in out and "user=api" in out  # only the values go


def test_redact_is_a_pure_function_and_keeps_ordinary_text() -> None:
    assert redact("run abc accepted status=QUEUED") == "run abc accepted status=QUEUED"
    assert redact("bearer token missing; Basic setup complete") == "bearer token missing; Basic setup complete"
    assert redact(f"Bearer {CANARY}") == f"Bearer {REDACTED}"
    assert redact(f"postgresql://api:{CANARY}@h/db") == f"postgresql://api:{REDACTED}@h/db"
    assert redact("exit code=1") == f"exit code={REDACTED}"  # accepted over-redaction (see the comment on _PATTERNS)


class _Hostile:
    def __str__(self) -> str:
        raise RuntimeError("no string for you")


def test_a_record_that_cannot_be_formatted_is_still_emitted_and_redacted() -> None:
    logger, stream = capture()
    logger.warning("%(x)s", {"y": f"Bearer {CANARY}"})  # mapping args with a missing key: KeyError in getMessage
    logger.warning(_Hostile())  # __str__ raises
    try:
        raise ValueError(_Hostile())  # formatException calls str() on the exception
    except ValueError:
        logger.exception("handled %s", f"code={CANARY}")
    out = stream.getvalue()
    assert CANARY not in out and out.count("WARNING") == 2 and "ERROR" in out
    assert "ValueError" in out  # the traceback module guards str() itself; our fallback covers anything else


def test_install_puts_the_filter_on_every_root_handler() -> None:
    root = logging.getLogger()
    before = {id(h): list(h.filters) for h in root.handlers}  # pytest's capture handlers live for the session
    level, handlers = root.level, list(root.handlers)
    try:
        redaction.install()
        assert root.handlers, "basicConfig must have installed a handler"
        for handler in root.handlers:
            assert any(isinstance(f, RedactingFilter) for f in handler.filters), handler
        redaction.install()  # idempotent: one filter per handler
        for handler in root.handlers:
            assert sum(isinstance(f, RedactingFilter) for f in handler.filters) == 1
    finally:
        for handler in root.handlers:  # leave pytest's handlers as they were (other tests inspect record.args)
            handler.filters[:] = before.get(id(handler), [])
        for added in [h for h in root.handlers if h not in handlers]:  # basicConfig on a bare root adds a handler
            root.removeHandler(added)
        root.setLevel(level)
