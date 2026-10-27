#!/usr/bin/env python3
"""
File management commands for TempleDB.

These commands read/write directly from the TempleDB database and are the
primary write path.

  templedb file cat      — read a file's current DB snapshot
  templedb file set      — write content to DB, mirror to checkout,
                           record EditIntent (v --verify to fail-loud
                           on hash mismatch)
  templedb file edit     — $EDITOR round-trip on the DB blob
  templedb file checkout — extract a file from DB to disk
  templedb file rm       — stage deletion
  templedb file where    — show all mirrors of a file with hashes
                           (drift diagnosis)
  templedb file ls       — directory listing from DB
"""
import sys
import os
import re
import subprocess
import tempfile
import hashlib
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from repositories import ProjectRepository, FileRepository
from cli.core import Command
from cli.fuzzy_matcher import fuzzy_match_project, fuzzy_match_file
from logger import get_logger

logger = get_logger(__name__)


# ── Double-encoded UTF-8 ("mojibake") detection ────────────────────────────
#
# UTF-8 bytes decoded as Latin-1 and re-encoded as UTF-8 double every
# non-ASCII character: an em dash's E2 80 94 becomes C3 A2 C2 80 C2 94. The
# result is still *valid* UTF-8, so every decode on the way into the DB
# accepts it, and it renders as a stray "â" plus two C1 control characters
# that browsers draw as nothing. bza's frontend/app/page.tsx was corrupted
# this way on 2026-09-29 and shipped for two weeks before anyone noticed a
# button reading "â   done" instead of "✓ done".
#
# The cause was not templedb. It was a `perl -0pi -e` one-liner: -0pi reads
# the file as bytes, so every byte becomes one character, and inserting a
# single literal above U+00FF (here \x{2014}) upgrades the whole buffer and
# re-encodes all of it on output. Perl says "Wide character in print" and
# that warning went to a discarded stderr. Since the hazard lives in
# throwaway shell rather than in any code we own, the only place to catch it
# is here, where content enters the DB.
#
# The character classes are built with chr() deliberately. Writing the C1
# range as literals does not survive being pasted through tooling -- the
# bytes get stripped and the class silently degrades to a two-member set
# that matches nothing, reporting every file clean. That happened twice
# while diagnosing the bza incident.
_MOJIBAKE_CONT = "[%s-%s]" % (chr(0x80), chr(0xBF))
_MOJIBAKE_RE = re.compile(
    "[%s-%s]%s" % (chr(0xC2), chr(0xDF), _MOJIBAKE_CONT)
    + "|[%s-%s]%s{2}" % (chr(0xE0), chr(0xEF), _MOJIBAKE_CONT)
    + "|[%s-%s]%s{3}" % (chr(0xF0), chr(0xF4), _MOJIBAKE_CONT)
)
# Self-check, not decoration: if the classes above ever degrade, this module
# would report every input clean rather than failing, which is the worst
# possible behaviour for a corruption guard.
assert _MOJIBAKE_RE.search("—".encode("utf-8").decode("latin-1")), (
    "mojibake regex is broken -- its character classes did not survive"
)


def _mojibake_runs(text) -> list:
    """Sequences in `text` that are valid UTF-8 when encoded back to Latin-1.

    Each hit is returned as the character it would decode back to, so callers
    can show "this looks like it should be —" rather than dumping bytes.
    """
    if not isinstance(text, str):
        return []
    out = []
    for match in _MOJIBAKE_RE.finditer(text):
        try:
            out.append(match.group(0).encode('latin-1').decode('utf-8'))
        except (UnicodeEncodeError, UnicodeDecodeError):
            # Matched the shape but is not actually re-decodable, so it is
            # ordinary text that happens to look like the pattern.
            pass
    return out


def _apply_session_override(value) -> None:
    """Pin session identity for this process from `--session <id|name>`.

    `file set` auto-stages, so it is session-scoped whether or not the
    caller thinks about sessions — and it had no way to say which one.
    That bites subprocess callers hardest: `templedb reports reindex`
    shells out to `templedb file set`, which resolves its own session, so
    the stage can land somewhere the parent is not looking and the
    parent's next `vcs commit` finds nothing. Observed twice on
    2026-10-08, each time blocking a publish.

    Exports TEMPLEDB_SESSION_ID rather than threading an argument,
    because identity is read independently by VCSService (staging), the
    intent recorder, and CheckoutRepository (checkout roles). Setting the
    env var once is what makes all three agree. Process-local.
    """
    import os

    value = (value or "").strip()
    if not value:
        return
    from services.context import ServiceContext

    svc = ServiceContext().get_vcs_service()
    svc.set_session_override(value)
    os.environ['TEMPLEDB_SESSION_ID'] = str(svc.get_current_session()['id'])
    os.environ.pop('TEMPLEDB_SESSION', None)


class FileCommands(Command):
    """File command handlers — all reads/writes go through the DB, not the filesystem."""

    def __init__(self):
        """Initialize with service context"""
        super().__init__()
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.project_repo = self.ctx.project_repo
        self.file_repo = FileRepository()

    def show(self, args) -> int:
        """Show file content from TempleDB database"""
        try:
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            file_record = fuzzy_match_file(project['id'], args.file_path, show_matched=True)
            if not file_record:
                logger.error(f"File '{args.file_path}' not found in project '{args.project}'")
                return 1

            content = self._read_content_from_db(file_record)
            if content is None:
                logger.error(f"Could not read file content from database")
                return 1

            print(content, end='')
            return 0

        except Exception as e:
            logger.error(f"Failed to show file: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def edit(self, args) -> int:
        """Edit file — reads from DB, writes back to DB"""
        try:
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            file_record = fuzzy_match_file(project['id'], args.file_path, show_matched=True)
            if not file_record:
                logger.error(f"File '{args.file_path}' not found in project '{args.project}'")
                return 1

            content = self._read_content_from_db(file_record)
            if content is None:
                logger.error(f"Could not read file content from database")
                return 1

            # Write to temp file for editing
            suffix = Path(file_record['file_path']).suffix or '.txt'
            with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False) as tf:
                tf.write(content)
                tmp_path = tf.name

            try:
                editor = os.environ.get('EDITOR', 'vi')
                subprocess.run([editor, tmp_path], check=True)

                # Read back and write to DB if changed
                new_content = Path(tmp_path).read_text()
                if new_content != content:
                    self._write_content_to_db(project['id'], args.project,
                                              file_record['file_path'], new_content)
                    print(f"✓ Edited and saved {file_record['file_path']} to database")
                else:
                    print(f"No changes made to {file_record['file_path']}")
                return 0
            except subprocess.CalledProcessError as e:
                logger.error(f"Editor exited with error: {e}")
                return 1
            finally:
                os.unlink(tmp_path)

        except Exception as e:
            logger.error(f"Failed to edit file: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def checkout(self, args) -> int:
        """Checkout file from TempleDB database to a local path"""
        try:
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            file_record = self.file_repo.get_file_by_path(project['id'], args.file_path)
            if not file_record:
                logger.error(f"File '{args.file_path}' not found in project '{args.project}'")
                return 1

            # Determine target path
            if hasattr(args, 'output') and args.output:
                target_path = Path(args.output)
            else:
                repo_path = project.get('repo_url', '').replace('file://', '')
                if not repo_path:
                    logger.error(f"Project path not set for '{args.project}'")
                    return 1
                target_path = Path(repo_path) / args.file_path

            # Create parent directories if needed
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Read content from DB
            content = self._read_content_from_db(file_record)
            if content is None:
                logger.error(f"Could not read file content from database")
                return 1

            # Write to target
            target_path.write_text(content)
            print(f"✓ Checked out {args.file_path} to {target_path}")
            return 0

        except Exception as e:
            logger.error(f"Failed to checkout file: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def cat(self, args) -> int:
        """Alias for show command"""
        return self.show(args)

    def get(self, args) -> int:
        """Get file content as string (alias for show, more explicit for programmatic use)"""
        return self.show(args)

    def set(self, args) -> int:
        """Set file content directly in the database"""
        try:
            _apply_session_override(getattr(args, 'session', None))
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            # Get content from --content flag or stdin.
            #
            # stdin is read as BYTES and decoded only if it is valid
            # UTF-8. Reading it as text made `file set` fail outright on
            # any binary file — "'utf-8' codec can't decode byte 0x84 in
            # position 0" — with nothing written. That is why
            # system_config's .authinfo.gpg could not be put into the DB
            # at all, which in turn let materialize delete it from the
            # checkout as an untracked stray and broke a nix build.
            #
            # Text keeps its exact previous path: the same str, the same
            # hash, stored in content_text. Only genuinely undecodable
            # input takes the blob branch, so nothing that worked before
            # changes shape.
            if hasattr(args, 'content') and args.content:
                content = args.content
            else:
                raw = sys.stdin.buffer.read()
                try:
                    content = raw.decode('utf-8')
                except UnicodeDecodeError:
                    content = raw

            if not content:
                logger.error("No content provided (use --content or pipe to stdin)")
                return 1

            # Do the actual write first. Only record the intent AFTER
            # the write succeeds — otherwise a failed write leaves a
            # lying `edit_intents.status='applied'` row that survives
            # the abort and misleads later provenance queries.
            # Prior ordering (intent → write) caused the 2026-09-14
            # "intent applied but file_cat returns nothing" bug — see
            # handoff #9.
            #
            # Wrapped in a deploy_stage_runs record — migration 104's
            # declarative substrate for chain observability. The
            # context manager auto-classifies outcome: 'noop' when
            # input_hash == output_hash, 'success' otherwise, 'failed'
            # on exception. Downstream stages can chain by hash.
            from services.deploy_stage import record as _record_stage
            import hashlib as _hashlib
            prev_hash = self._get_current_hash(
                project['id'], args.file_path
            )
            new_hash = _hashlib.sha256(
                content.encode('utf-8') if isinstance(content, str) else content
            ).hexdigest()

            # Optimistic lock. `file set` replaces the WHOLE file, so a
            # copy fetched earlier is effectively a lock on all of it:
            # anything committed between the read and the write is
            # reverted silently, with no conflict and a clean --verify
            # (which only checks that what you wrote is what landed, not
            # that you meant to drop the rest). That happened twice on
            # 2026-10-04 to src/cli/commands/entity.py, a 5,239-line file
            # four separate fixes were landing in; the first instance went
            # unnoticed for three commits.
            #
            # Prefix match because every place that shows a hash
            # truncates it -- `file where`, `source snapshot --meta`,
            # doctor output -- so requiring 64 characters would mean
            # nobody uses the flag.
            expected = getattr(args, 'if_match', None)
            if expected:
                exp = expected.strip().lower()
                if len(exp) < 8 or any(c not in '0123456789abcdef' for c in exp):
                    logger.error(
                        f"--if-match wants at least 8 hex chars of a sha256, "
                        f"got {expected!r}"
                    )
                    return 2
                if not prev_hash:
                    logger.error(
                        f"--if-match {exp[:12]} given but {args.file_path} has "
                        f"no current content in {args.project} — it is a new "
                        f"file, so there is no base to match. Drop --if-match "
                        f"if creating it is what you meant."
                    )
                    return 2
                if not prev_hash.startswith(exp):
                    logger.error(
                        f"--if-match mismatch on {args.project}/"
                        f"{args.file_path}: expected {exp[:12]}, DB currently "
                        f"holds {prev_hash[:12]}. Something changed the file "
                        f"since you read it, and writing now would revert it."
                    )
                    logger.error(
                        f"  Re-read and re-apply:  templedb file cat "
                        f"{args.project} {args.file_path}"
                    )
                    logger.error(
                        f"  Or overwrite anyway:   drop --if-match"
                    )
                    return 2
            # Refuse content that newly looks double-encoded. See the
            # _MOJIBAKE_RE comment above for the failure this exists to
            # catch: valid UTF-8 all the way down, so nothing else in the
            # write path can notice it.
            #
            # The test is whether this write *increases* the count, not
            # whether any is present. A file that already contains such
            # sequences -- genuinely, or because it is already corrupt --
            # must stay editable, and a repair that removes them has to
            # pass. Only going up is suspicious.
            if not getattr(args, 'allow_mojibake', False):
                new_runs = _mojibake_runs(content)
                if new_runs:
                    prev_text = None
                    try:
                        _rec = self.file_repo.get_file_by_path(
                            project['id'], args.file_path
                        )
                        if _rec:
                            prev_text = self._read_content_from_db(_rec)
                    except Exception as e:
                        logger.debug(f"mojibake pre-read failed: {e}")
                    prev_runs = _mojibake_runs(prev_text)
                    if len(new_runs) > len(prev_runs):
                        added = len(new_runs) - len(prev_runs)
                        sample = sorted(set(new_runs))[:8]
                        logger.error(
                            f"Refusing to write {args.project}/"
                            f"{args.file_path}: content looks like "
                            f"double-encoded UTF-8 ({added} new sequence"
                            f"{'s' if added != 1 else ''}; the file had "
                            f"{len(prev_runs)})."
                        )
                        logger.error(
                            "  These decode back to: "
                            + " ".join(repr(c) for c in sample)
                        )
                        logger.error(
                            "  That is UTF-8 read as Latin-1 and written "
                            "back as UTF-8. It is valid UTF-8, so nothing "
                            "downstream will catch it, and it renders as a "
                            "stray 'a-circumflex' plus invisible control "
                            "characters."
                        )
                        logger.error(
                            "  Usual cause: `perl -0pi -e` inserting a "
                            "literal above U+00FF, which upgrades the whole "
                            "buffer and re-encodes every pre-existing "
                            "character. Check for 'Wide character in print'."
                        )
                        logger.error(
                            "  If the sequences are genuinely what you "
                            "meant, pass --allow-mojibake."
                        )
                        return 3

            try:
                _session_id = self.ctx.get_vcs_service().get_current_session()['id']
            except Exception:
                _session_id = None
            with _record_stage(
                kind="file_set",
                slug=args.project,
                input_hash=prev_hash,
                session_id=_session_id,
                metadata={"file_path": args.file_path,
                          "size_bytes": len(
                              content.encode('utf-8') if isinstance(content, str) else content
                          )},
            ) as _stage:
                self._write_content_to_db(
                    project['id'], args.project, args.file_path, content,
                )
                _stage.output_hash = new_hash

            # Phase 2 intent recording: unless --skip-intent, record an
            # EditIntent as a bookkeeping side-effect of this write. The
            # intent gives us provenance ("who set this, when, from what
            # session") without changing external behavior.
            intent_id = None
            skip_intent = getattr(args, 'skip_intent', False)
            if not skip_intent:
                intent_id = self._record_and_apply_intent(
                    project_id=project['id'],
                    file_path=args.file_path,
                    content=content,
                    base_revision=prev_hash,
                    session_id=_session_id,
                )

            # Link the just-staged working-state row to the intent
            # (migration 088 adds intent_id column). Cosmetic — the
            # commit path doesn't need it, but downstream provenance
            # queries do.
            if intent_id is not None:
                try:
                    from db_utils import execute
                    execute(
                        """UPDATE vcs_working_state
                              SET intent_id = ?
                            WHERE project_id = ?
                              AND file_id = (SELECT id FROM project_files
                                              WHERE project_id = ?
                                                AND file_path = ?
                                              LIMIT 1)
                              AND intent_id IS NULL""",
                        (intent_id, project['id'], project['id'], args.file_path),
                    )
                except Exception as e:
                    logger.debug(f"intent_id link failed (non-fatal): {e}")

            # --verify: confirm the write actually landed in file_contents.is_current.
            # Guards against the write-broken bug where later refresh/commit can revert.
            if hasattr(args, 'verify') and args.verify:
                from db_utils import query_one
                # content is bytes for binary input; encoding it again
                # would raise and take --verify down with it, which is
                # the one flag callers use to prove a write landed.
                expected_hash = hashlib.sha256(
                    content.encode('utf-8') if isinstance(content, str) else content
                ).hexdigest()
                row = query_one(
                    """SELECT fc.content_hash, fc.line_count
                         FROM file_contents fc
                         JOIN project_files pf ON pf.id = fc.file_id
                        WHERE pf.project_id = ?
                          AND pf.file_path  = ?
                          AND fc.is_current = 1""",
                    (project['id'], args.file_path)
                )
                if not row:
                    logger.error(f"--verify: no file_contents.is_current row for {args.file_path}")
                    return 2
                if row['content_hash'] != expected_hash:
                    logger.error(
                        f"--verify: hash mismatch for {args.file_path}: "
                        f"wrote {expected_hash[:12]} but DB has {row['content_hash'][:12]}"
                    )
                    return 2

            want_commit = getattr(args, 'commit', False)
            want_stage = getattr(args, 'stage', False) or want_commit

            # _write_content_to_db already auto-staged this file in
            # vcs_working_state (content_hash + staged_by_session_id).
            # A follow-up stage_files() would call
            # _refresh_ws_row_from_disk, which re-reads the checkout —
            # and if the mirror-to-checkout step silently failed
            # (e.g. read-only checkout), the disk still holds the OLD
            # content and the refresh reverts working_state.content_hash
            # back to the pre-write hash. The subsequent commit then
            # stores the OLD content and clobbers is_current. Skip.
            if want_stage:
                print(f"✓ Set and staged {args.file_path}")
            else:
                print(f"✓ Set {args.file_path}")

            # Emit the intent id so scripted callers can inspect / cancel
            # it later. Silent when --skip-intent was passed.
            if intent_id is not None:
                print(f"  intent: #{intent_id}")

            if want_commit:
                # In-process invoke — subprocess would fork a new session
                # (ppid differs), defeating the whole point.
                from argparse import Namespace
                from cli.commands.vcs import VCSCommands
                commit_msg = (getattr(args, 'commit_msg', None)
                              or f"file set: {args.file_path}")
                commit_args = Namespace(
                    project=args.project,
                    branch=None,
                    message=commit_msg,
                    author=None,
                )
                rc = VCSCommands().commit(commit_args)
                if rc != 0:
                    return rc

            return 0

        except Exception as e:
            logger.error(f"Failed to set file: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def retype(self, args) -> int:
        """Re-run the classifier over recorded files and correct file_type_id.

        `project_files.file_type_id` is set once, at the moment a file is
        first recorded, by whatever logic was in play then — so it is a
        snapshot of a past classifier, not a derived value. Two sources of
        wrongness accumulated behind that:

          - `_get_file_type_id` used to carry its own 14-entry extension
            map and, for anything outside it, take `SELECT id FROM
            file_types LIMIT 1`. That row is `api_route`, which is how 495
            rows across 10 projects — including templedb's own
            requirements.txt, pyproject.toml and .gitignore — came to be
            recorded as API routes, none of them API routes.
          - `file_types` was missing roughly half the names the scanner
            emits, so even a correct classification had nowhere to land
            (migration 138 seeded it).

        Dry by default. Only rows whose current type differs from what the
        classifier says are touched, so running it twice is a no-op.
        """
        from importer.scanner import (classify_path, is_ignored_path,
                                      GENERIC_TEXT_TYPE)
        from repositories.base import BaseRepository
        from collections import Counter

        base = BaseRepository()
        where, params = "1=1", []
        if getattr(args, 'project', None):
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1
            where, params = "pf.project_id = ?", [project['id']]
        only = getattr(args, 'from_type', None)
        if only:
            where += " AND ft.type_name = ?"
            params.append(only)

        rows = base.query_all(f"""
            SELECT pf.id, pf.file_path, pr.slug, ft.type_name AS current_type
              FROM project_files pf
              JOIN projects pr ON pr.id = pf.project_id
              LEFT JOIN file_types ft ON ft.id = pf.file_type_id
             WHERE {where} AND pf.status = 'active'
        """, tuple(params))

        type_ids, changes, unresolved, ignored = {}, [], 0, []

        def type_id(name):
            """Resolve or create. Never falls back to an arbitrary row —
            that fallback is the bug this command exists to repair."""
            if name in type_ids:
                return type_ids[name]
            row = base.query_one(
                "SELECT id FROM file_types WHERE type_name = ?", (name,))
            if not row:
                base.execute(
                    "INSERT OR IGNORE INTO file_types "
                    "(type_name, category, description) VALUES "
                    "(?, 'uncategorized', 'Auto-registered by file retype')",
                    (name,))
                row = base.query_one(
                    "SELECT id FROM file_types WHERE type_name = ?", (name,))
            type_ids[name] = row['id'] if row else None
            return type_ids[name]

        for r in rows:
            # A path the scanner would now refuse has no right type. Say
            # so instead of assigning one — these are debris that got
            # recorded before the filter existed, and giving them a tidy
            # type would make them look deliberate.
            if is_ignored_path(r['file_path']):
                ignored.append(r)
                continue
            want = classify_path(r['file_path'])
            if not want:
                unresolved += 1
                want = GENERIC_TEXT_TYPE
            if want == r['current_type']:
                continue
            changes.append((r, want))

        if ignored:
            print(f"{len(ignored)} active file(s) match a path the scanner "
                  f"now ignores — debris, not content. Not re-typed; "
                  f"`templedb file rm` is the fix:")
            for r in ignored[:10]:
                print(f"    {r['slug']}/{r['file_path']}")
            if len(ignored) > 10:
                print(f"    … and {len(ignored) - 10} more")
            print()

        if not changes:
            print(f"Nothing to re-type ({len(rows)} active file(s) checked).")
            return 0

        moves = Counter(f"{r['current_type']} -> {want}"
                        for r, want in changes)
        print(f"{len(changes)} of {len(rows)} active file(s) are recorded "
              f"with a type the classifier disagrees with:\n")
        for move, n in moves.most_common(25):
            print(f"  {n:5}  {move}")
        if len(moves) > 25:
            print(f"  … and {len(moves) - 25} more kinds of change")
        if unresolved:
            print(f"\n  {unresolved} path(s) the classifier cannot name at "
                  f"all would become '{GENERIC_TEXT_TYPE}'.")

        if not getattr(args, 'apply', False):
            print("\nDry run. Re-run with --apply to write these.")
            return 0

        written = 0
        for r, want in changes:
            tid = type_id(want)
            if tid is None:
                logger.warning("Could not resolve file type %r; skipping %s",
                               want, r['file_path'])
                continue
            base.execute(
                "UPDATE project_files SET file_type_id = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (tid, r['id']))
            written += 1
        print(f"\nRe-typed {written} file(s).")
        return 0

    def rm(self, args) -> int:
        """Stage a file for deletion. On commit, project_files row is hard-deleted (history preserved in vcs_file_states)."""
        try:
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            file_record = self.file_repo.get_file_by_path(project['id'], args.file_path)
            if not file_record:
                logger.error(f"File '{args.file_path}' not found in project '{args.project}'")
                return 1

            file_id = file_record.get('id') or file_record.get('file_id')

            from repositories.base import BaseRepository
            base = BaseRepository()

            branch = base.query_one(
                "SELECT active_branch_id as id FROM projects WHERE id = ? AND active_branch_id IS NOT NULL",
                (project['id'],))
            if not branch:
                branch = base.query_one(
                    "SELECT id FROM vcs_branches WHERE project_id = ? AND is_default = 1 LIMIT 1",
                    (project['id'],))
            if not branch:
                logger.error(f"No active branch found for project '{args.project}'")
                return 1

            sid = self.ctx.get_vcs_service().get_current_session()['id']
            base.execute("""
                INSERT INTO vcs_working_state
                    (project_id, branch_id, file_id, state,
                     staged_by_session_id, last_modified)
                VALUES (?, ?, ?, 'deleted', ?, datetime('now'))
                ON CONFLICT (project_id, branch_id, file_id)
                DO UPDATE SET state = 'deleted',
                              staged_by_session_id = ?,
                              last_modified = datetime('now')
            """, (project['id'], branch['id'], file_id, sid, sid))

            print(f"✓ Staged {args.file_path} for deletion")
            return 0

        except Exception as e:
            logger.error(f"Failed to remove file: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def ls(self, args) -> int:
        """List files in a project from the database"""
        try:
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            files = self.file_repo.get_files_for_project(project['id'])
            if not files:
                print(f"No files found in project '{args.project}'")
                return 0

            # Filter by path prefix if provided
            prefix = getattr(args, 'path', None)
            # Filter by edit_mode (migration 106). '--edit-mode X'
            # matches files whose edit_mode = X. Special value
            # 'non-immutable' matches everything not NULL and not
            # 'immutable' (i.e. anything that opts out of the default).
            edit_mode_filter = getattr(args, 'edit_mode', None)

            for f in files:
                fp = f['file_path']
                if prefix and not fp.startswith(prefix):
                    continue
                if edit_mode_filter:
                    em = f.get('edit_mode')
                    if edit_mode_filter == 'non-immutable':
                        if em is None or em == 'immutable':
                            continue
                    elif em != edit_mode_filter:
                        continue
                if getattr(args, 'long', False):
                    size = f.get('lines_of_code', 0) or 0
                    em = f.get('edit_mode') or 'immutable'
                    print(f"{size:>6} loc  {em:<13}  {fp}")
                else:
                    print(fp)

            return 0

        except Exception as e:
            logger.error(f"Failed to list files: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def mark(self, args) -> int:
        """Set the edit_mode attribute on a file (migration 106).

        Values: 'immutable' (default), 'hot-reload', 'live-symlink'.
        See design doc: reports/2026-09-19-2012-declarative-reframe-*.html §6.
        """
        try:
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1
            valid = {'immutable', 'hot-reload', 'live-symlink'}
            if args.edit_mode not in valid:
                logger.error(
                    f"Invalid --edit-mode {args.edit_mode!r}. "
                    f"Must be one of: {sorted(valid)}"
                )
                return 1
            from db_utils import execute, query_one
            row = query_one(
                "SELECT id, edit_mode FROM project_files "
                "WHERE project_id = ? AND file_path = ?",
                (project['id'], args.file_path),
            )
            if not row:
                logger.error(
                    f"File not found: {args.project}/{args.file_path}"
                )
                return 1
            new_mode = None if args.edit_mode == 'immutable' else args.edit_mode
            execute(
                "UPDATE project_files SET edit_mode = ? WHERE id = ?",
                (new_mode, row['id']),
            )
            print(
                f"✓ {args.project}/{args.file_path}: "
                f"edit_mode {row['edit_mode'] or 'immutable'} → "
                f"{args.edit_mode}"
            )
            return 0
        except Exception as e:
            logger.error(f"Failed to mark file: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def _record_and_apply_intent(self, project_id: int, file_path: str,
                                 content,
                                 base_revision: Optional[str] = None,
                                 session_id: Optional[int] = None
                                 ) -> Optional[int]:
        """Create an EditIntent row for this write and mark it applied.

        Bookkeeping only — the actual file_contents write still happens
        via the pre-existing `_write_content_to_db` path (called by the
        caller). Recording the intent gives us provenance data for
        Phase 3 cross-authority queries.

        Returns the intent id on success, None on failure. Never
        raises: intent recording must not break the write path.
        """
        try:
            from db_utils import execute
            content_bytes = (content.encode('utf-8')
                             if isinstance(content, str) else content)
            new_hash = hashlib.sha256(content_bytes).hexdigest()
            author = os.environ.get('TEMPLEDB_AUTHOR') \
                or os.environ.get('USER') or None
            # Prefer the session the caller already resolved for the
            # stage. Reading TEMPLEDB_SESSION_ID alone meant one `file
            # set` recorded two different answers to "which session is
            # this?": the stage got get_current_session(), the intent got
            # NULL whenever the var was unset. That is how the two
            # system_config writes of 2026-10-25 (intents #1246/#1247)
            # ended up unattributable, and an ordinary concurrent-agent
            # write read as an anonymous process rewriting the flake on a
            # timer. No new session is opened here — by this point the
            # stage has already resolved one.
            sid = session_id
            if sid is None:
                sid = os.environ.get('TEMPLEDB_SESSION_ID')
                try:
                    sid = int(sid) if sid else None
                except (ValueError, TypeError):
                    sid = None
            # Insert content_blobs so `intent apply` (if replayed
            # from CLI) could find it. Idempotent via OR IGNORE.
            #
            # reference_count starts at 0, not 1. A blob row is not a
            # reference to itself -- the count means "how many
            # file_contents rows point here", and the
            # increment_blob_reference trigger is what answers that.
            # Seeding 1 here made every blob born through the intent
            # path over-count from birth: the trigger then took it to
            # 2 for a single file_contents row. Caught by
            # blob_refcount_is_accurate within hours of that check
            # landing; see migration 128.
            execute(
                """INSERT OR IGNORE INTO content_blobs
                       (hash_sha256, content_text, content_type,
                        encoding, file_size_bytes, reference_count)
                     VALUES (?, ?, 'text', 'utf-8', ?, 0)""",
                (new_hash, content, len(content_bytes)),
            )
            intent_id = execute(
                """INSERT INTO edit_intents
                       (session_id, project_id, file_path,
                        base_revision, new_content_hash,
                        patch_summary, author, description,
                        status, applied_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?,
                             'file set', 'applied', datetime('now'))""",
                # base_revision was the literal string 'current' on all
                # 886 rows -- migration 123 catalogues it as a `constant`
                # in unmaintained_columns_baseline. The field designed to
                # record what an edit was made against never recorded
                # anything, which is why a stale-base overwrite left no
                # trace to audit. 'new-file' rather than NULL when there
                # is no prior content, so the two cases stay
                # distinguishable from a column that is merely unfilled.
                (sid, project_id, file_path,
                 base_revision or 'new-file', new_hash,
                 f"{len(content_bytes)} bytes", author),
            )
            return intent_id
        except Exception as e:
            logger.debug(f"intent recording skipped (non-fatal): {e}")
            return None

    def where(self, args) -> int:
        """Print every known mirror location for SLUG/PATH, with hash + status.

        Solves the 'which of these copies is the current one' pain: templedb
        content lives in several places (DB and two checkouts). Silent drift
        among them was the root of five recent incidents. This command makes
        drift *visible* without trying to make it *impossible*.

        Mirrors probed (skip any that don't exist for this slug):
          - DB (via file_contents.is_current)
          - ~/.config/templedb/checkouts/<slug>/<path>       (read-only publish)
          - ~/.config/templedb/edit-workspaces/<slug>/<path> (writable workspace)
          - Current home-manager profile (built overlays — e.g. Spacemacs
            layer files under ~/.emacs.d/private/local-layers/, resolved
            through their nix-store real paths). Matches by basename.

        Exit code: 0 if all present mirrors agree with the DB. 1 if any
        mirror is drifted. 2 if the DB has no current row for the path.
        """
        from pathlib import Path
        import hashlib

        # 1. Resolve project + get DB hash.
        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            logger.error(f"Project '{args.project}' not found")
            return 2
        slug = project['slug']
        path = args.file_path

        db_hash = self._get_current_hash(project['id'], path)
        if not db_hash:
            print(f"file:  {slug}/{path}")
            print(f"  DB:  (no current row — file is deleted or never existed)")
            return 2

        # 2. Probe filesystem mirrors.
        home = Path.home()
        mirrors = [
            ("checkout ", home / ".config/templedb/checkouts" / slug / path),
            ("edit-work", home / ".config/templedb/edit-workspaces" / slug / path),
        ]

        # 2b. Probe live overlay surfaces. For any file whose basename
        # matches under these entry points, we surface the resolved
        # nix-store path so 'where' shows the copy Emacs / home-manager /
        # NixOS actually loads (e.g. Spacemacs layer templedb-agent.el
        # sourced through home.nix). Without this, a DB-side edit + rebuild
        # leaves an invisible third copy that 'file where' silently ignores.
        #
        # The user-level ~/.local/state/nix/profiles/home-manager can be
        # stale under NixOS-integrated home-manager (the system side owns
        # activation), so we probe the *actual* live directories instead of
        # the profile symlink. rglob returns each hit; .resolve() follows
        # into the nix store.
        basename = Path(path).name
        probe_roots = [
            home / ".emacs.d",           # Spacemacs layers, private/, etc.
            Path("/etc/nixos"),          # system-config symlinks live here
            home / ".config" / "systemd" / "user",  # user unit overrides
        ]
        try:
            seen_real = set()
            import os as _os
            for root in probe_roots:
                if not root.exists():
                    continue
                # os.walk(followlinks=True) — rglob won't descend into
                # symlinked dirs, and the interesting overlay entries
                # (~/.emacs.d/private/local-layers/<layer>) are exactly
                # symlinks into the nix store. Cap depth to avoid runaway
                # walks (spacemacs private/ is shallow anyway).
                for dirpath, dirnames, filenames in _os.walk(
                    root, followlinks=True
                ):
                    if basename not in filenames:
                        continue
                    hit = Path(dirpath) / basename
                    try:
                        real = hit.resolve()
                    except OSError:
                        continue
                    if real in seen_real or not real.is_file():
                        continue
                    seen_real.add(real)
                    # Only surface hits that resolve into the nix store —
                    # that's the "overlay drift" surface. Everything else
                    # is either a stale copy we can't do anything about
                    # or a duplicate of the checkout mirror above.
                    if not str(real).startswith("/nix/store/"):
                        continue
                    try:
                        display = hit.relative_to(home)
                        label = f"~/{display}"
                    except ValueError:
                        label = str(hit)
                    mirrors.append((label, real))
        except Exception as e:
            logger.debug(f"overlay probe failed (non-fatal): {e}")

        # 3. Print header.
        print(f"file:  {slug}/{path}")
        print(f"  {'DB':<10} {db_hash[:12]}  current")

        # 4. Print each mirror with status.
        any_drift = False
        for label, mpath in mirrors:
            if not mpath.exists():
                # Skip printing missing mirrors — noisier than helpful,
                # and their absence is expected for most slug/path pairs.
                continue
            try:
                fs_hash = hashlib.sha256(mpath.read_bytes()).hexdigest()
            except Exception as e:
                print(f"  {label} ????????????  \033[33munreadable\033[0m ({e})")
                any_drift = True
                continue
            if fs_hash == db_hash:
                # Green
                marker = "\033[32m✓ match\033[0m"
            else:
                # Red
                marker = f"\033[31m✗ drift\033[0m (fs={fs_hash[:12]})"
                any_drift = True
            print(f"  {label} {fs_hash[:12]}  {marker}")

        # 5. Summary hint.
        if any_drift:
            print()
            print("  \033[33mdrift detected\033[0m — run "
                  "'templedb project checkout <slug> <path> --writable --force' "
                  "to publish DB → checkouts, or 'templedb file set' from a "
                  "trusted mirror to update DB.")
            return 1
        return 0

    def _get_current_hash(self, project_id: int, file_path: str) -> Optional[str]:
        """Return the current content_hash for project_id/file_path, or None."""
        from db_utils import query_one
        row = query_one(
            """SELECT fc.content_hash
                 FROM file_contents fc
                 JOIN project_files pf ON pf.id = fc.file_id
                WHERE pf.project_id = ? AND pf.file_path = ?
                  AND pf.status = 'active' AND fc.is_current = 1
                LIMIT 1""",
            (project_id, file_path),
        )
        return row['content_hash'] if row else None

    def _read_content_from_db(self, file_record: dict) -> Optional[str]:
        """Read file content directly from the TempleDB database (content_blobs).

        For externally-stored blobs (storage_location='external'), fetches from
        the filesystem via ContentStore.retrieve_content, decompressing if needed.
        """
        try:
            file_id = file_record.get('file_id') or file_record.get('id')
            if not file_id:
                return None

            content_row = self.file_repo.get_file_content(file_id)
            if not content_row:
                return None

            # External storage — read from filesystem
            if content_row.get('storage_location') == 'external' and content_row.get('external_path'):
                try:
                    from importer.content import ContentStore
                    data = ContentStore().retrieve_content(
                        content_row.get('content_hash') or content_row.get('hash_sha256'),
                        'external',
                        content_row['external_path'],
                        content_row.get('compression'),
                    )
                    if data is None:
                        return None
                    try:
                        return data.decode('utf-8')
                    except UnicodeDecodeError:
                        logger.error("File contains binary content, cannot display as text")
                        return None
                except Exception as e:
                    logger.debug(f"External read failed: {e}")
                    return None

            if content_row.get('content_text') is not None:
                return content_row['content_text']
            elif content_row.get('content_blob') is not None:
                # Try to decode binary content
                try:
                    return bytes(content_row['content_blob']).decode('utf-8')
                except UnicodeDecodeError:
                    logger.error("File contains binary content, cannot display as text")
                    return None
            return ""

        except Exception as e:
            logger.debug(f"Error reading content from DB: {e}")
            return None

    def _write_content_to_db(self, project_id: int, project_slug: str,
                             file_path: str, content):
        """Write file content directly to the TempleDB database.

        `content` is a str for text or bytes for binary. Binary is stored
        in content_blob with content_type 'binary_asset' and a NULL
        encoding, matching what the scanner produces for the same file —
        so a blob written here and one written by an import are
        indistinguishable downstream.
        """
        from repositories.base import BaseRepository
        base = BaseRepository()

        is_binary = isinstance(content, (bytes, bytearray))
        content_bytes = bytes(content) if is_binary else content.encode('utf-8')
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        # Line count is meaningless for binary and 0 is the honest answer;
        # counting 0x0a bytes would invent a statistic about a blob.
        line_count = 0 if is_binary else (content.count('\n') + 1 if content else 0)

        # Upsert content blob
        # reference_count 0 on insert: the increment_blob_reference
        # trigger counts the file_contents row that follows. See the
        # note in _record_and_apply_intent and migration 128.
        if is_binary:
            base.execute("""
                INSERT OR IGNORE INTO content_blobs
                (hash_sha256, content_text, content_blob, content_type, encoding,
                 file_size_bytes, reference_count)
                VALUES (?, NULL, ?, 'binary_asset', NULL, ?, 0)
            """, (content_hash, content_bytes, len(content_bytes)))
        else:
            base.execute("""
                INSERT OR IGNORE INTO content_blobs
                (hash_sha256, content_text, content_blob, content_type, encoding,
                 file_size_bytes, reference_count)
                VALUES (?, ?, NULL, 'text', 'utf-8', ?, 0)
            """, (content_hash, content, len(content_bytes)))

        # Check if file exists
        file_record = self.file_repo.get_file_by_path(project_id, file_path)
        if file_record:
            file_id = file_record.get('id') or file_record.get('file_id')
            # Un-delete: file set on a soft-deleted row should revive
            # it. Without this, file_contents gets the new blob but
            # publish materialize / file ls / everything else that
            # filters on status='active' silently skips the file.
            # Discovered during the recap-11 rebuild after `set bza
            # flake.nix` looked like it succeeded but shipped nothing.
            if file_record.get('status') != 'active':
                base.execute(
                    "UPDATE project_files SET status = 'active' WHERE id = ?",
                    (file_id,),
                )
            # Update file_contents
            base.execute("""
                INSERT INTO file_contents (file_id, content_hash, file_size_bytes, line_count, is_current)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(file_id, is_current) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    file_size_bytes = excluded.file_size_bytes,
                    line_count = excluded.line_count,
                    updated_at = datetime('now')
            """, (file_id, content_hash, len(content_bytes), line_count))
        else:
            # Create new file
            file_name = file_path.rsplit("/", 1)[-1]
            ext = Path(file_path).suffix.lstrip(".").lower()
            ext_to_type = {
                "py": "python_script", "js": "javascript", "ts": "typescript",
                "nix": "nix", "sql": "sql_file", "sh": "shell_script",
                "md": "markdown", "json": "json", "yaml": "yaml", "yml": "yaml",
                "toml": "toml", "html": "html", "css": "css", "txt": "text_file",
            }
            type_name = ext_to_type.get(ext)
            ft_row = None
            if type_name:
                ft_row = base.query_one(
                    "SELECT id FROM file_types WHERE type_name = ? LIMIT 1", (type_name,))
            if not ft_row:
                ft_row = base.query_one("SELECT id FROM file_types LIMIT 1")
            file_type_id = ft_row['id'] if ft_row else 1

            file_id = base.execute("""
                INSERT INTO project_files (project_id, file_type_id, file_path, file_name,
                                           status, lines_of_code, last_modified)
                VALUES (?, ?, ?, ?, 'active', ?, datetime('now'))
            """, (project_id, file_type_id, file_path, file_name, line_count))

            # ON CONFLICT clause is critical here — even though this is
            # the "new file" branch, an orphan file_contents row can
            # exist for a project_files.id that just got reused (SQLite
            # rowids can be reused after DELETE without AUTOINCREMENT,
            # and PRAGMA foreign_keys defaults OFF so ON DELETE CASCADE
            # doesn't fire for prior test cleanups or bulk deletes).
            # Without ON CONFLICT the raw INSERT hits UNIQUE(file_id,
            # is_current), raises IntegrityError, and _write_content_to_db
            # aborts. If the caller (`set`) already stamped
            # edit_intents.status='applied' via _record_and_apply_intent,
            # the intent then LIES about the write. Reproduced 2026-09-14
            # while building /agent-work-log; see handoff #9.
            base.execute("""
                INSERT INTO file_contents (file_id, content_hash, file_size_bytes, line_count, is_current)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(file_id, is_current) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    file_size_bytes = excluded.file_size_bytes,
                    line_count = excluded.line_count,
                    updated_at = datetime('now')
            """, (file_id, content_hash, len(content_bytes), line_count))

        # Auto-stage
        try:
            branch = base.query_one(
                "SELECT active_branch_id as id FROM projects WHERE id = ? AND active_branch_id IS NOT NULL",
                (project_id,))
            if not branch:
                branch = base.query_one(
                    "SELECT id FROM vcs_branches WHERE project_id = ? AND is_default = 1 LIMIT 1",
                    (project_id,))
            if branch:
                change_state = "modified" if file_record else "added"
                sid = self.ctx.get_vcs_service().get_current_session()['id']
                # content_hash must be set here — vcs commit reads content via
                # ws.content_hash, not file_contents. Without this, `file set`
                # followed by `vcs commit` silently records the previous content.
                base.execute("""
                    INSERT INTO vcs_working_state
                        (project_id, branch_id, file_id, content_hash, state,
                         staged_by_session_id, last_modified)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT (project_id, branch_id, file_id)
                    DO UPDATE SET content_hash = excluded.content_hash,
                                  state = excluded.state,
                                  staged_by_session_id = ?,
                                  last_modified = datetime('now')
                """, (project_id, branch['id'], file_id, content_hash, change_state, sid, sid))
        except Exception as e:
            logger.debug(f"Auto-stage failed (non-fatal): {e}")

        # Mirror the write to the ACTIVE checkout so a subsequent
        # `vcs status --refresh` doesn't flag the file as disk-stale (it
        # scans the checkout, and without this the disk-scan hash disagrees
        # with the DB blob we just wrote).
        #
        # This is NOT cosmetic, despite what this comment used to claim.
        # The refresh classifies a staged file with no file on disk as
        # state='deleted', and `vcs commit` hard-deletes the
        # project_files row for anything in that state. So a missed
        # mirror doesn't just produce a confusing status line — it makes
        # the next commit silently destroy the file while reporting
        # success. Cost a full report on 2026-09-24 (commit 7A3BF285
        # announced "Files: 2" and committed one).
        #
        # The path must come from the active checkout record, not a
        # hardcoded ~/.config/templedb/checkouts/<slug>. When a project is
        # in edit mode the live working directory is
        # ~/.config/templedb/edit-workspaces/<slug>/<stamp>/, and the old
        # hardcoded path pointed at a stale read-only tree that the
        # refresh never scans — which is exactly how the write went
        # missing.
        try:
            import os
            checkout = None
            try:
                from sync.manager import SyncManager
                checkout = str(SyncManager(project_slug).get_checkout_path())
            except Exception as e:
                logger.debug(f"Active checkout lookup failed: {e}")
                checkout = os.path.expanduser(
                    f"~/.config/templedb/checkouts/{project_slug}"
                )
            if checkout and os.path.isdir(checkout):
                target = os.path.join(checkout, file_path)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                # Atomic write via tmp + rename to avoid partial reads.
                # Binary content mirrors as bytes; opening "w" for it
                # raises "write() argument must be str, not bytes", which
                # the handler below turns into a warning — leaving the DB
                # written and the checkout NOT, exactly the split this
                # mirror exists to prevent.
                tmp = f"{target}.tmp.{os.getpid()}"
                # `os.replace` leaves nothing behind on success, so a
                # surviving temp file means this died mid-write — and the
                # next scan picks it up as a real file. 67 such paths were
                # tracked with current content before the scanner learned
                # to ignore the shape (SKIP_FILE_PATTERNS). Clean up our
                # own debris rather than relying on that filter alone.
                try:
                    if isinstance(content, (bytes, bytearray)):
                        with open(tmp, "wb") as f:
                            f.write(content)
                    else:
                        with open(tmp, "w", encoding="utf-8") as f:
                            f.write(content)
                    os.replace(tmp, target)
                except BaseException:
                    # BaseException, not Exception: a KeyboardInterrupt
                    # here is exactly the case that produced the debris.
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise
            else:
                logger.warning(
                    "No checkout directory for '%s' — %s was written to the "
                    "database but not mirrored to disk. A later `vcs commit` "
                    "may treat it as deleted.", project_slug, file_path)
        except Exception as e:
            # Deliberately louder than the old debug(): a failed mirror is
            # a data-loss precondition, not a cosmetic miss.
            logger.warning(
                "Checkout mirror failed for %s (%s). The database write "
                "succeeded; verify with `templedb file cat` after "
                "committing.", file_path, e)


def register(cli):
    """Register file commands with CLI"""
    cmd = FileCommands()

    # Create file command with subparsers
    file_parser = cli.subparsers.add_parser(
        'file',
        help='File management commands'
    )
    file_subparsers = file_parser.add_subparsers(dest='file_subcommand', required=True)

    # file show
    show_parser = file_subparsers.add_parser(
        'show',
        help='Show file content'
    )
    show_parser.add_argument('project', help='Project name or pattern')
    show_parser.add_argument('file_path', help='File path or pattern (fuzzy matching enabled)')
    cli.commands['file.show'] = cmd.show

    # file edit
    edit_parser = file_subparsers.add_parser(
        'edit',
        help='Edit file in $EDITOR'
    )
    edit_parser.add_argument('project', help='Project name or pattern')
    edit_parser.add_argument('file_path', help='File path or pattern (fuzzy matching enabled)')
    cli.commands['file.edit'] = cmd.edit

    # file checkout
    checkout_parser = file_subparsers.add_parser(
        'checkout',
        help='Checkout file to working directory or specified path'
    )
    checkout_parser.add_argument('project', help='Project name or slug')
    checkout_parser.add_argument('file_path', help='Path to file within project')
    checkout_parser.add_argument('-o', '--output', help='Output path (default: project working directory)')
    cli.commands['file.checkout'] = cmd.checkout

    # file cat (alias for show)
    cat_parser = file_subparsers.add_parser(
        'cat',
        help='Show file content (alias for show)'
    )
    cat_parser.add_argument('project', help='Project name or pattern')
    cat_parser.add_argument('file_path', help='File path or pattern (fuzzy matching enabled)')
    cli.commands['file.cat'] = cmd.cat

    # file get (programmatic alias for show)
    get_parser = file_subparsers.add_parser(
        'get',
        help='Get file content as string (for programmatic use)'
    )
    get_parser.add_argument('project', help='Project name or pattern')
    get_parser.add_argument('file_path', help='File path or pattern (fuzzy matching enabled)')
    cli.commands['file.get'] = cmd.get

    # file set (set content from string)
    set_parser = file_subparsers.add_parser(
        'set',
        help='Set file content from string (stdin or --content)'
    )
    set_parser.add_argument('project', help='Project name or slug')
    set_parser.add_argument('file_path', help='Path to file within project')
    set_parser.add_argument('-c', '--content', help='Content to write (otherwise reads from stdin)')
    set_parser.add_argument('-s', '--stage', action='store_true', help='Stage file after writing')
    # No `-s` short form: that is already --stage here. See
    # docs/CLI_SURFACE.md on short-flag collisions.
    set_parser.add_argument('--session', metavar='ID|NAME',
                            help='Stage into this session (numeric id, or a '
                                 'declared name, created if absent). '
                                 'Outranks TEMPLEDB_SESSION_ID and '
                                 'TEMPLEDB_SESSION. file set auto-stages, so '
                                 'without this the stage lands in whichever '
                                 'session this process resolves — which for a '
                                 'subprocess may not be the caller\'s.')
    set_parser.add_argument('--if-match', metavar='HASH', dest='if_match',
                            help='Refuse the write unless the file currently '
                                 'hashes to HASH (full sha256 or a prefix of '
                                 '>=8 hex chars). Exits 2 on mismatch. Use it '
                                 'whenever the content being written was '
                                 'derived from a copy read earlier: file set '
                                 'replaces the whole file, so a stale base '
                                 'silently reverts anything committed in '
                                 'between.')
    set_parser.add_argument('--verify', action='store_true',
                            help='After write, confirm file_contents.is_current holds the written hash. '
                                 'Exits 2 on mismatch. Guards against silent revert (see docs/known-bugs).')
    set_parser.add_argument('--allow-mojibake', action='store_true',
                            dest='allow_mojibake',
                            help='Permit content that adds double-encoded '
                                 'UTF-8 sequences (UTF-8 read as Latin-1 and '
                                 'written back as UTF-8). Refused by default '
                                 'and exits 3, because the result is valid '
                                 'UTF-8 that nothing downstream can catch and '
                                 'that renders as invisible control '
                                 'characters.')
    set_parser.add_argument('--skip-intent', action='store_true',
                            help='Bypass the EditIntent bookkeeping layer '
                                 '(Phase 2). Rare — mainly for bootstrap and '
                                 'tests. Normal writes should record their '
                                 'intent for provenance.')
    set_parser.add_argument('--commit', action='store_true',
                            help='After writing, commit this session\'s staged '
                                 'files. Implies --stage. Use with -m to set the '
                                 'commit message; defaults to "file set: <path>". '
                                 'Solves the agent workflow where a fresh Bash '
                                 'shell can\'t commit changes staged by an '
                                 'earlier shell\'s session.')
    set_parser.add_argument('-m', '--commit-msg', dest='commit_msg',
                            help='Commit message when --commit is passed.')
    cli.commands['file.set'] = cmd.set

    # file rm (stage a file for deletion)
    rm_parser = file_subparsers.add_parser(
        'rm',
        help='Stage a file for deletion (hard-delete on commit; history preserved)'
    )
    rm_parser.add_argument('project', help='Project name or slug')
    rm_parser.add_argument('file_path', help='Path to file within project')
    cli.commands['file.rm'] = cmd.rm

    # file ls (list files)
    ls_parser = file_subparsers.add_parser(
        'ls',
        help='List files in a project'
    )
    ls_parser.add_argument('project', help='Project name or pattern')
    ls_parser.add_argument('path', nargs='?', help='Optional path prefix to filter by')
    ls_parser.add_argument('-l', '--long', action='store_true', help='Show detailed info (lines of code)')
    ls_parser.add_argument('--edit-mode', dest='edit_mode',
                            choices=['immutable', 'hot-reload',
                                     'live-symlink', 'non-immutable'],
                            help='Filter by edit_mode (migration 106). '
                                 '"non-immutable" matches anything opted '
                                 'out of the default.')
    cli.commands['file.ls'] = cmd.ls

    # file retype (re-run the classifier over recorded file_type_id)
    retype_parser = file_subparsers.add_parser(
        'retype',
        help='Re-run the classifier over recorded files and fix file_type_id'
    )
    retype_parser.add_argument('project', nargs='?',
                               help='Project name or pattern (default: all)')
    retype_parser.add_argument('--from-type', dest='from_type', help=(
        "Only consider rows currently recorded as this type, e.g. "
        "--from-type api_route"))
    retype_parser.add_argument('--apply', action='store_true',
                               help='Write the changes (default: dry run)')
    cli.commands['file.retype'] = cmd.retype

    # file mark (set the edit_mode attribute on a file — mig 106)
    mark_parser = file_subparsers.add_parser(
        'mark',
        help='Set the edit_mode of a file (immutable | hot-reload | live-symlink)',
    )
    mark_parser.add_argument('project', help='Project name or slug')
    mark_parser.add_argument('file_path', help='File path within project')
    mark_parser.add_argument('--edit-mode', dest='edit_mode',
                             required=True,
                             choices=['immutable', 'hot-reload',
                                      'live-symlink'],
                             help='Edit mode to set. See migration 106 '
                                  'for semantics.')
    cli.commands['file.mark'] = cmd.mark

    # file where (mirror drift diagnostic — Phase 0 of the observer plan)
    where_parser = file_subparsers.add_parser(
        'where',
        help='Show every mirror location for a file with content-hash drift status'
    )
    where_parser.add_argument('project', help='Project name or slug')
    where_parser.add_argument('file_path', help='File path within project')
    cli.commands['file.where'] = cmd.where
