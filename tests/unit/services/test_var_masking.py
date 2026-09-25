"""Value masking in `templedb var list`.

A connection string defeats every check the masker had: the key is
called DATABASE_URL so no sensitive word appears in the name, and the
value carries ':', '@' and '%' so it fails the API-key charset test.
`var list` printed the staging Postgres password in the clear while
dutifully masking the JWTs right above it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from cli.commands.var import _mask_value, _redact_url_password


# The real value that leaked, password altered.
STAGING_DSN = (
    "postgresql://postgres.ekfffwmbeloqcflvlzsg:4Zsp3LQvNUmr4s%40"
    "@aws-0-us-east-2.pooler.supabase.com:6543/postgres"
)


# --- the regression -------------------------------------------------

def test_connection_string_password_is_hidden():
    out = _mask_value("DATABASE_URL", STAGING_DSN)
    assert "4Zsp3LQvNUmr4s%40" not in out
    assert "****" in out


def test_connection_string_keeps_everything_that_is_not_secret():
    """Blanket-masking to 'post...gres' would hide the password and also
    destroy the reason anyone lists a DSN: which host and DB it points
    at."""
    out = _mask_value("DATABASE_URL", STAGING_DSN)
    assert out == (
        "postgresql://postgres.ekfffwmbeloqcflvlzsg:****"
        "@aws-0-us-east-2.pooler.supabase.com:6543/postgres"
    )


@pytest.mark.parametrize("dsn,secret", [
    ("postgres://u:hunter2@db.internal:5432/app", "hunter2"),
    ("mysql://root:p%40ssw0rd@10.0.0.5/shop", "p%40ssw0rd"),
    ("redis://default:abc123@cache:6379/0", "abc123"),
    ("mongodb+srv://svc:s3cr3t@cluster0.mongodb.net/db", "s3cr3t"),
    ("amqp://guest:guest@rabbit:5672/%2f", "guest:guest@"),
])
def test_other_schemes(dsn, secret):
    assert secret not in _mask_value("SOME_URL", dsn)


def test_unencoded_at_sign_in_password_still_splits_correctly():
    """userinfo runs to the LAST '@' in the authority per RFC 3986, so a
    password containing a literal '@' must not truncate the redaction
    and leak its tail."""
    dsn = "postgres://user:pa@ss@realhost:5432/db"
    out = _mask_value("DATABASE_URL", dsn)
    assert out == "postgres://user:****@realhost:5432/db"
    assert "pa@ss" not in out


# --- must NOT over-mask ---------------------------------------------

@pytest.mark.parametrize("url", [
    "https://staging.woofspetsalon.com",
    "https://ekfffwmbeloqcflvlzsg.supabase.co",
    "postgres://readonly@db.internal:5432/app",   # user, no password
    "localhost",
    "5432",
    "",
])
def test_harmless_values_are_left_alone(url):
    """These are why `var list` is useful. Masking a plain URL or a
    port number would be a regression in its own right."""
    assert _mask_value("SOME_URL", url) == url


def test_empty_password_is_not_redacted():
    assert _redact_url_password("postgres://user:@host/db") is None


def test_non_url_returns_none():
    assert _redact_url_password("just-a-plain-value") is None
    assert _redact_url_password("user:pass@host") is None  # no scheme


# --- existing behaviour preserved -----------------------------------

def test_name_based_masking_still_wins():
    """The change is additive: anything the key-name rule already
    caught must still be blanket-masked, not merely URL-redacted."""
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
    out = _mask_value("SUPABASE_SERVICE_ROLE_KEY", jwt)
    assert out.startswith("eyJh") and out.endswith(out[-4:])
    assert "payload" not in out


def test_short_sensitive_value_is_fully_starred():
    assert _mask_value("API_TOKEN", "abc") == "****"


def test_sensitive_key_holding_a_dsn_is_blanket_masked_not_redacted():
    """A key the user named 'password' is treated as wholly secret --
    the name-based rule runs first and stays authoritative."""
    out = _mask_value("DB_PASSWORD_URL", STAGING_DSN)
    assert "****" not in out.replace("...", "")
    assert out.startswith("post") and out.endswith("gres")
