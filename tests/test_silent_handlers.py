"""Ratchet: no NEW silent-debug handlers around side-effecting code.

`except Exception: logger.debug(...)` wrapping a write makes total
failure indistinguishable from "there was nothing to do". It is the
single most repeated shape behind this project's invisible bugs:

  - _adopt_relocked_flake_lock built a path from a config attribute
    that does not exist, and no-op'd for a whole rebuild cycle.
  - sync_engine.apply_changes dropped replicated CRDT rows at debug
    level while still returning a success count, so two peers could
    believe they agreed while diverging.
  - system_service silently skipped every POSIX exec bit when it could
    not read git's modes, surfacing much later as a non-executable
    script.

Not every instance is wrong — some really are best-effort telemetry
where failure costs nothing, and `file set`'s intent_id link says so in
its own comment. So this is a ratchet, not a ban, in the same spirit as
unmaintained_columns_baseline: the current set is accepted, and growth
fails. Fixing one means deleting its line from ACCEPTED.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Verbs that make a try-block side-effecting. If one of these appears
# in the guarded code, a silent handler is hiding a failed mutation
# rather than a failed read.
WRITE = re.compile(
    r'\b(execute|INSERT|UPDATE|DELETE|write_text|mkdir|subprocess|'
    r'rename|unlink|chmod|commit)\b', re.I)

# Accepted as of 2026-10-07. Each is a deliberate best-effort path
# where a failure genuinely costs nothing the operator needs to know.
# Audited individually; the three that did matter were fixed instead of
# being listed here.
ACCEPTED = {
    ('src/cli/commands/claude.py', 80),
    ('src/cli/commands/claude.py', 514),
    ('src/cli/commands/entity.py', 259),
    ('src/cli/commands/entity.py', 3824),
    ('src/cli/commands/file.py', 325),
    ('src/cli/commands/file.py', 951),
    ('src/cli/commands/reconcile.py', 261),
    ('src/cli/commands/vcs.py', 447),
    ('src/cli/commands/vcs.py', 719),
    ('src/cli/commands/vcs.py', 733),
}

# Line numbers move. Match on the enclosing function instead so an
# unrelated edit above does not fail this test — the point is "no new
# silent handler", not "nothing moved".
ACCEPTED_FUNCS_ONLY = True


def _enclosing_def(lines, idx):
    for j in range(idx, -1, -1):
        m = re.match(r'\s*(?:async )?def (\w+)', lines[j])
        if m:
            return m.group(1)
    return '<module>'


def silent_write_handlers(root: Path):
    """[(relpath, enclosing_def)] for silent handlers around writes."""
    found = []
    for path in sorted((root / 'src').rglob('*.py')):
        lines = path.read_text(errors='ignore').splitlines()
        for i, line in enumerate(lines):
            if not re.match(r'\s*except (Exception|BaseException)', line):
                continue
            indent = len(line) - len(line.lstrip())
            body = []
            for j in range(i + 1, min(i + 6, len(lines))):
                s = lines[j]
                if s.strip() and (len(s) - len(s.lstrip())) <= indent:
                    break
                body.append(s)
            if not body:
                continue
            joined = ' '.join(body)
            if 'logger.debug' not in joined:
                continue
            if not all(('logger.debug' in b or 'pass' in b or not b.strip())
                       for b in body):
                continue
            guarded = '\n'.join(lines[max(0, i - 30):i])
            if WRITE.search(guarded):
                found.append((str(path.relative_to(root)),
                              _enclosing_def(lines, i)))
    return found


class SilentHandlerRatchetTest(unittest.TestCase):

    def test_no_new_silent_handlers(self):
        found = silent_write_handlers(REPO)
        accepted_files = {f for f, _ in ACCEPTED}
        # A file with no accepted entry must have no silent handlers at
        # all; a file with accepted entries may not grow past its count.
        from collections import Counter
        got = Counter(f for f, _ in found)
        allowed = Counter(f for f, _ in ACCEPTED)
        offenders = []
        for f, n in got.items():
            if n > allowed.get(f, 0):
                fns = [fn for ff, fn in found if ff == f]
                offenders.append(
                    f"{f}: {n} silent handler(s), {allowed.get(f, 0)} "
                    f"accepted — in {', '.join(sorted(set(fns)))}")
        self.assertFalse(
            offenders,
            "New `except Exception: logger.debug(...)` around code that "
            "writes. Total failure will look like a no-op. Either report "
            "it (logger.warning / print) or add it to ACCEPTED in this "
            "file with a reason:\n  " + "\n  ".join(offenders))

    def test_the_three_fixed_sites_stayed_fixed(self):
        """Regressions here are silent by construction, so pin them."""
        found = {(f, fn) for f, fn in silent_write_handlers(REPO)}
        for f, fn in (
            ('src/sync_engine.py', 'apply_changes'),
            ('src/services/system_service.py', 'materialize_from_db'),
            ('src/cli/commands/nixos.py', '_adopt_relocked_flake_lock'),
        ):
            self.assertNotIn(
                (f, fn), found,
                f"{f}:{fn} went back to swallowing failures at debug")

    def test_the_detector_detects(self):
        """A ratchet that cannot fire is worse than no ratchet."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'src').mkdir()
            (root / 'src' / 'bad.py').write_text(
                "def f():\n"
                "    try:\n"
                "        execute('DELETE FROM t')\n"
                "    except Exception as e:\n"
                "        logger.debug(f'nope: {e}')\n")
            (root / 'src' / 'loud.py').write_text(
                "def g():\n"
                "    try:\n"
                "        execute('DELETE FROM t')\n"
                "    except Exception as e:\n"
                "        logger.warning(f'nope: {e}')\n")
            (root / 'src' / 'readonly.py').write_text(
                "def h():\n"
                "    try:\n"
                "        x = compute()\n"
                "    except Exception as e:\n"
                "        logger.debug(f'nope: {e}')\n")
            got = silent_write_handlers(root)
            self.assertEqual(got, [('src/bad.py', 'f')])


if __name__ == '__main__':
    unittest.main()
