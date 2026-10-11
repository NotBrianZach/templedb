"""`templedb var set` value sources: positional, --value-stdin, --value-file.

A value passed on the command line lands in shell history, and the atuin
setup here syncs that history to api.atuin.sh -- so a secret in argv leaves
the machine. Three credentials got out that way before these flags existed
(a Cloudflare token, a Supabase access token and an OpenAI key), each from a
plain `env set`/`secret set` with the value inline. argv is also readable via
/proc for the life of the process.

The trailing-newline rule is the fiddly part and the reason this file exists:
exactly ONE trailing newline is stripped, because `printf '%s\\n' "$v" | ...`
and an editor-written --value-file would otherwise store a value no API
accepts -- while interior newlines and leading whitespace are preserved, so a
PEM block survives --value-file intact.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from cli.commands.var import _resolve_set_value


class _Args:
    """Stands in for the argparse namespace `var_set` receives."""

    def __init__(self, value=None, value_stdin=False, value_file=None):
        self.value = value
        self.value_stdin = value_stdin
        self.value_file = value_file


def test_positional_value_is_returned_verbatim():
    assert _resolve_set_value(_Args(value='plain')) == 'plain'


def test_positional_value_is_not_newline_stripped():
    # Only the stdin/file paths strip, because only they acquire a newline
    # from the mechanism rather than from the user's intent.
    assert _resolve_set_value(_Args(value='keep\n')) == 'keep\n'


def test_stdin_value(monkeypatch):
    monkeypatch.setattr('sys.stdin', __import__('io').StringIO('from-stdin'))
    assert _resolve_set_value(_Args(value_stdin=True)) == 'from-stdin'


def test_stdin_strips_exactly_one_trailing_newline(monkeypatch):
    monkeypatch.setattr('sys.stdin', __import__('io').StringIO('tok\n'))
    assert _resolve_set_value(_Args(value_stdin=True)) == 'tok'


def test_stdin_keeps_the_second_trailing_newline(monkeypatch):
    # Two newlines means one was intended; strip the mechanism's, keep theirs.
    monkeypatch.setattr('sys.stdin', __import__('io').StringIO('tok\n\n'))
    assert _resolve_set_value(_Args(value_stdin=True)) == 'tok\n'


def test_file_value(tmp_path):
    f = tmp_path / 'v.txt'
    f.write_text('from-file\n')
    assert _resolve_set_value(_Args(value_file=str(f))) == 'from-file'


def test_file_preserves_interior_newlines_and_leading_space(tmp_path):
    pem = '-----BEGIN X-----\n  indented\nbody\n-----END X-----\n'
    f = tmp_path / 'k.pem'
    f.write_text(pem)
    assert _resolve_set_value(_Args(value_file=str(f))) == pem[:-1]


def test_unreadable_file_is_an_error(tmp_path, capsys):
    assert _resolve_set_value(_Args(value_file=str(tmp_path / 'nope'))) is None
    assert 'could not read --value-file' in capsys.readouterr().err


def test_no_source_is_an_error(capsys):
    assert _resolve_set_value(_Args()) is None
    assert 'no value given' in capsys.readouterr().err


@pytest.mark.parametrize('args', [
    _Args(value='inline', value_stdin=True),
    _Args(value='inline', value_file='/tmp/x'),
    _Args(value_stdin=True, value_file='/tmp/x'),
])
def test_more_than_one_source_is_an_error(args, capsys):
    assert _resolve_set_value(args) is None
    assert 'give the value once' in capsys.readouterr().err


def test_empty_stdin_yields_empty_string_not_an_error(monkeypatch):
    # Distinct from "no source given": an explicit --value-stdin that reads
    # nothing is a deliberate empty value, and _resolve_set_value signals
    # failure with None, so '' must survive as a real result.
    monkeypatch.setattr('sys.stdin', __import__('io').StringIO(''))
    assert _resolve_set_value(_Args(value_stdin=True)) == ''
