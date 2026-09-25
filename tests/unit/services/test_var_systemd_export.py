"""`templedb var export --format systemd`.

The point of this format is to remove the reason a service would ever
need to read the TempleDB database. systemd parses EnvironmentFile= as
PID 1, before dropping privileges, so the rendered file can be 0600
root-owned and the service user never touches it -- which is exactly
the wall woofs-sync.service ran into, running as User=woofs against a
DB under a mode-700 /home/zach.

The decoder modelled here is systemd's real one, established by feeding
candidate files to `systemd-run -p EnvironmentFile=` and reading back
what the service actually saw. Inside a double-quoted value systemd
unescapes \\\\ and \\" and NOTHING else -- \\t and \\n come back as a
literal backslash plus the letter. Asserting against a hand-rolled
inverse of our own encoder would prove nothing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from cli.commands.var import _systemd_env_line


def render(key, value):
    line, reason = _systemd_env_line(key, value)
    assert reason is None, f"unexpectedly refused: {reason}"
    return line


def systemd_decode(line):
    """Decode a KEY="..." line the way systemd actually does."""
    key, _, quoted = line.partition('=')
    assert quoted.startswith('"') and quoted.endswith('"')
    body = quoted[1:-1]
    out, i = [], 0
    while i < len(body):
        if body[i] == '\\' and i + 1 < len(body) and body[i + 1] in '\\"':
            out.append(body[i + 1])      # only \\ and \" are unescaped
            i += 2
        else:
            out.append(body[i])
            i += 1
    return key, ''.join(out)


# --- shape ----------------------------------------------------------

def test_basic_line_is_quoted():
    assert render("DB_PORT", "5432") == 'DB_PORT="5432"'


def test_null_becomes_empty_not_the_string_None():
    """The dotenv format rendered a NULL var_value as the literal
    "None", and every consumer read that as a four-character value."""
    assert render("API_URL", None) == 'API_URL=""'


def test_empty_string_stays_empty():
    assert render("API_URL", "") == 'API_URL=""'


# --- round-trip through systemd's real decoder ----------------------

@pytest.mark.parametrize("value", [
    "plain",
    "",
    "with spaces",
    "  leading and trailing  ",
    'quote " inside',
    r"back\slash",
    r"trailing\\",
    '\\"',
    "tab\there",
    "postgresql://postgres.abc:p%40ss@aws-0.pooler.supabase.com:6543/postgres",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig",
])
def test_round_trips_exactly(value):
    key, decoded = systemd_decode(render("K", value))
    assert key == "K"
    assert decoded == value


def test_raw_tab_is_not_backslash_escaped():
    """A raw tab survives quoting. Escaping it as \\t would hand the
    service two characters where the database holds one."""
    line = render("T", "a\tb")
    assert line == 'T="a\tb"'
    assert "\\t" not in line


def test_whitespace_is_preserved_by_quoting():
    """Unquoted, systemd strips leading and trailing whitespace."""
    assert systemd_decode(render("PAD", "  x  "))[1] == "  x  "


def test_backslash_escaped_before_quote():
    """Order matters: doing quotes first would leave a literal
    backslash acting as an escape for the quote after it."""
    _, decoded = systemd_decode(render("P", '\\"'))
    assert decoded == '\\"'


# --- refusals -------------------------------------------------------

@pytest.mark.parametrize("key", [
    "git_server.url",   # real key in this DB; systemd rejects the dot
    "9LIVES",           # leading digit
    "has-dash",
    "has space",
    "",
])
def test_invalid_names_are_refused_with_a_reason(key):
    line, reason = _systemd_env_line(key, "x")
    assert line is None
    assert "valid environment variable name" in reason


@pytest.mark.parametrize("bad", ["a\nb", "a\r\nb", "trailing\n"])
def test_newline_values_are_refused_not_mangled(bad):
    """Unquoted a newline ends the assignment and lets the remainder
    parse as further KEY=VALUE lines; as \\n it would silently give the
    service a different string than the one stored. Refuse instead."""
    line, reason = _systemd_env_line("NOTE", bad)
    assert line is None
    assert "newline" in reason


def test_newline_refusal_blocks_assignment_forgery():
    line, _ = _systemd_env_line("NOTE", "benign\nINJECTED=pwned")
    assert line is None


@pytest.mark.parametrize("key", ["DATABASE_URL", "_LEADING", "a", "A1_b2"])
def test_valid_names_are_accepted(key):
    line, reason = _systemd_env_line(key, "v")
    assert reason is None and line.startswith(f"{key}=")
