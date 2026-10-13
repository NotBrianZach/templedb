"""`file set` must refuse content that newly looks double-encoded.

bza's frontend/app/page.tsx was corrupted on 2026-09-29 and shipped for two
weeks: a `perl -0pi -e` one-liner inserted a literal `\\x{2014}`, which
upgrades the whole buffer and re-encodes every pre-existing character on
output. The result is *valid* UTF-8 -- so the strict decode in `file set`
accepted it, the hash matched, materialize mirrored it, the build compiled it,
and the only symptom was a button reading "a-circumflex   done" where the
source said "check done".

The guard lives at `file set` rather than in any producer because the hazard
is a throwaway shell idiom, not code templedb owns.

Two properties matter here and the second is the one that makes the guard
usable rather than merely loud:

  1. Adding double-encoded sequences is refused.
  2. Content that merely *contains* non-ASCII is not. page.tsx legitimately
     holds 114 non-ASCII characters after repair -- em dashes, box drawing,
     a check mark, six emoji -- and a guard that tripped on those would be
     turned off within a day.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cli.commands.file import _mojibake_runs, _MOJIBAKE_RE  # noqa: E402


def mangle(text: str) -> str:
    """What a Latin-1 read of UTF-8 bytes produces."""
    return text.encode("utf-8").decode("latin-1")


# ── The detector itself ────────────────────────────────────────────────────

def test_regex_classes_survived_the_source_file():
    """The C1 range must not have been stripped out of the pattern.

    This is the failure that matters most: a degraded character class makes
    the guard report every input clean, which is worse than having no guard
    at all because it reads as a passed check. The module asserts this at
    import time; this test states it as a requirement rather than a
    side-effect.
    """
    assert _MOJIBAKE_RE.search(mangle("—"))
    assert _MOJIBAKE_RE.search(mangle("·"))
    assert _MOJIBAKE_RE.search(mangle("📖"))


@pytest.mark.parametrize("char", ["—", "…", "·", "→", "─", "⚠", "✓", "✕", "📖", "🧠"])
def test_detects_each_width(char):
    """Two-, three- and four-byte characters all mangle differently."""
    assert _mojibake_runs(mangle(char)) == [char]


def test_decodes_back_to_the_intended_character():
    """The error message claims "these decode back to X" -- it must be true."""
    assert _mojibake_runs(mangle("a — b … c")) == ["—", "…"]


def test_clean_utf8_is_not_flagged():
    """The repaired page.tsx shape: plenty of non-ASCII, none of it mangled."""
    clean = "// ── header ──\nconst a = '✓ done'  // em dash — here 📖\n"
    assert _mojibake_runs(clean) == []


def test_ascii_only_is_not_flagged():
    assert _mojibake_runs("const x = 1\n") == []


def test_non_string_is_not_flagged():
    """Binary content takes the blob branch and must not reach the regex."""
    assert _mojibake_runs(b"\x84\x00\xff") == []
    assert _mojibake_runs(None) == []


# ── The guard's decision rule ──────────────────────────────────────────────
#
# `file set` compares counts rather than testing for presence, so that an
# already-corrupt file stays editable and a repair can land.

def decision(new: str, prev: str) -> bool:
    """True when `file set` would refuse. Mirrors the check in set()."""
    return len(_mojibake_runs(new)) > len(_mojibake_runs(prev))


def test_refuses_newly_introduced_corruption():
    prev = "x = '—'\n"
    assert decision(mangle(prev), prev)


def test_allows_a_repair():
    """Corrupt in the DB, clean incoming -- the fix must not be blocked."""
    clean = "x = '—'\n"
    assert not decision(clean, mangle(clean))


def test_allows_unrelated_edits_to_an_already_corrupt_file():
    """Count is unchanged, so an orthogonal edit still goes through."""
    corrupt = mangle("x = '—'\n")
    assert not decision(corrupt + "y = 2\n", corrupt)


def test_refuses_corruption_added_on_top_of_existing_corruption():
    corrupt = mangle("x = '—'\n")
    assert decision(corrupt + mangle("y = '…'\n"), corrupt)


def test_the_real_incident_is_caught():
    """The actual bza commit: one newly-typed em dash, the rest mangled."""
    before = (
        "const SECTIONS = []\n"
        "// Show cached books instantly — don't wait for network\n"
        "<span>Loading your library…</span>\n"
        "  ✓ done\n"
        "  · spaced repetition\n"
    )
    # perl mangles everything it read, but encodes the inserted char correctly.
    after = mangle(before).replace(
        "const SECTIONS = []",
        "const SECTIONS = []\n// below the prompt — that is the one thing",
    )
    assert decision(after, before)
    # And the survivor is why this was so hard to spot: exactly one correct
    # character in a file where everything else was mangled.
    assert "—" in after
