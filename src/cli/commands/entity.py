#!/usr/bin/env python3
"""`templedb ingest`, `templedb graph explore`, `templedb doctor entities`.

Phase 3 groundwork of the observer/integrator plan. See
`docs/ENTITY_GRAPH_DESIGN.md` for the framing (spans as first-class
relations, commuting-diagram invariants, local charts + transition
maps).

This module hosts three related surfaces that all read/write the
entities and relations tables added in migration 089:

    templedb ingest {git, agent, intent}
        Transition maps from local authorities' native models into
        TempleDB's uniform entity/relation graph.

    templedb graph explore <kind>/<ref>
        Walks outbound relations one hop. Prelude to more elaborate
        traversal in later phases.

    templedb doctor entities [--check <name>]
        Runs commuting-diagram invariant checks. Small MVP starter
        set; more get added as new entity kinds land.

All three are read-mostly. Ingest is the only writer, and it's
idempotent (upserts by (kind, external_ref) and (from, kind, to)).
"""
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class EntityCommands(Command):
    """Entity graph ingest + query + reconcile."""

    # ==== INGEST ==============================================================

    def ingest(self, args) -> int:
        """Dispatch to a specific ingestion adapter.

        Each adapter reads from its authority's native tables and
        upserts into entities/relations. See docs/ENTITY_GRAPH_DESIGN.md
        for the local-algebras framing."""
        adapters = {
            'git':    self._ingest_git,
            'agent':  self._ingest_agent,
            'intent': self._ingest_intent,
            'reports': self._ingest_reports,
            'all':    self._ingest_all,
        }
        adapter = adapters.get(args.source)
        if not adapter:
            logger.error(
                f"Unknown ingest source {args.source!r}. "
                f"Available: {', '.join(sorted(adapters))}"
            )
            return 1
        return adapter(args)

    def _ingest_all(self, args) -> int:
        for sub in ('git', 'agent', 'intent', 'reports'):
            args.source = sub
            rc = self.ingest(args)
            if rc != 0:
                return rc
        return 0

    def _ingest_git(self, args) -> int:
        """Ingest git-authority entities: File, Commit + contains edges.

        Reads from project_files and vcs_commits. Derives Commit
        -> contains -> File relations from vcs_file_states."""
        from db_utils import query_all
        added_e, added_r = 0, 0

        # Files
        files = query_all(
            """SELECT pf.id, pf.file_path, p.slug
                 FROM project_files pf
                 JOIN projects p ON p.id = pf.project_id
                WHERE pf.status = 'active'"""
        )
        for f in files:
            eref = f"{f['slug']}/{f['file_path']}"
            if self._upsert_entity('File', eref, 'git', label=f['file_path']):
                added_e += 1

        # Commits
        commits = query_all(
            """SELECT c.id, c.commit_hash, c.commit_message,
                      p.slug
                 FROM vcs_commits c
                 JOIN vcs_branches b ON b.id = c.branch_id
                 JOIN projects p     ON p.id = b.project_id"""
        )
        for c in commits:
            eref = f"{c['slug']}/{c['commit_hash']}"
            summary = (c['commit_message'] or '').split('\n', 1)[0][:80]
            if self._upsert_entity('Commit', eref, 'git', label=summary):
                added_e += 1

        # Commit -> contains -> File edges via vcs_file_states
        contains = query_all(
            """SELECT DISTINCT
                      p.slug || '/' || c.commit_hash AS commit_ref,
                      p.slug || '/' || pf.file_path  AS file_ref
                 FROM vcs_file_states vfs
                 JOIN vcs_commits c   ON c.id = vfs.commit_id
                 JOIN project_files pf ON pf.id = vfs.file_id
                 JOIN vcs_branches b  ON b.id = c.branch_id
                 JOIN projects p      ON p.id = b.project_id"""
        )
        for row in contains:
            from_id = self._entity_id('Commit', row['commit_ref'])
            to_id = self._entity_id('File', row['file_ref'])
            if from_id and to_id:
                if self._upsert_relation(from_id, 'contains', to_id, 'git'):
                    added_r += 1

        print(f"✓ ingest git: +{added_e} entities, +{added_r} relations")
        return 0

    def _ingest_agent(self, args) -> int:
        """Ingest agent-runtime authority: AgentSession + owns edges to
        their EditIntents (populated by _ingest_intent)."""
        from db_utils import query_all
        added_e, added_r = 0, 0

        sessions = query_all(
            """SELECT s.id, s.session_uuid, s.title, s.status, p.slug
                 FROM agent_sessions s
                 LEFT JOIN projects p ON p.id = s.project_id"""
        )
        for s in sessions:
            eref = str(s['session_uuid'])
            label = s['title'] or f"session {s['id']}"
            if self._upsert_entity('AgentSession', eref,
                                   'agent-runtime', label=label):
                added_e += 1

        # AgentSession -> proposed -> EditIntent
        # (EditIntent entities must exist — run intent ingest first
        # or as part of --all)
        proposals = query_all(
            """SELECT s.session_uuid AS suid, i.id AS iid
                 FROM edit_intents i
                 JOIN agent_sessions s ON s.id = i.session_id"""
        )
        for row in proposals:
            from_id = self._entity_id('AgentSession', row['suid'])
            to_id = self._entity_id('EditIntent', str(row['iid']))
            if from_id and to_id:
                if self._upsert_relation(from_id, 'proposed',
                                         to_id, 'agent-runtime'):
                    added_r += 1

        print(f"✓ ingest agent: +{added_e} entities, +{added_r} relations")
        return 0

    def _ingest_intent(self, args) -> int:
        """Ingest EditIntent entities. Adds `applied-to -> Commit`
        edges when applied_commit_id is set."""
        from db_utils import query_all
        added_e, added_r = 0, 0

        intents = query_all(
            """SELECT i.id, i.status, i.file_path,
                      i.applied_commit_id,
                      p.slug AS project_slug
                 FROM edit_intents i
                 JOIN projects p ON p.id = i.project_id"""
        )
        for it in intents:
            label = f"{it['project_slug']}/{it['file_path']} ({it['status']})"
            if self._upsert_entity('EditIntent', str(it['id']),
                                   'templedb', label=label):
                added_e += 1

        # EditIntent -> applied-to -> Commit
        for it in intents:
            if it['applied_commit_id']:
                commit_row = self._commit_ref_from_id(
                    it['applied_commit_id'])
                if commit_row:
                    from_id = self._entity_id('EditIntent', str(it['id']))
                    to_id = self._entity_id('Commit', commit_row)
                    if from_id and to_id:
                        if self._upsert_relation(from_id, 'applied-to',
                                                 to_id, 'templedb'):
                            added_r += 1

        print(f"✓ ingest intent: +{added_e} entities, +{added_r} relations")
        return 0

    def _ingest_reports(self, args) -> int:
        """Ingest Report entities + auto-detect Report ↔ Commit spans.

        Walks reports/ HTML files from the templedb project, creates
        Report entities, and regex-scans each report for commit hash
        prefixes ([0-9a-f]{7,40}). For each candidate, verifies the
        prefix is unique in vcs_commits and if so inserts a
        report_implementations row with confidence='auto-detected'.

        Existing 'confirmed' or 'verified' or 'rejected' rows are
        preserved. Only 'auto-detected' rows can be superseded on
        rerun.
        """
        import re
        from db_utils import query_all, query_one, execute
        added_e = 0
        added_impls = 0

        # Any project with reports/*.html files. In practice templedb
        # is the only one, but keeping it general lets other projects
        # accumulate report archives too.
        reports = query_all(
            """SELECT pf.file_path, cb.content_text, p.slug AS project_slug
                 FROM project_files pf
                 JOIN file_contents fc
                   ON fc.file_id = pf.id AND fc.is_current = 1
                 JOIN content_blobs cb
                   ON cb.hash_sha256 = fc.content_hash
                 JOIN projects p ON p.id = pf.project_id
                WHERE pf.status = 'active'
                  AND pf.file_path LIKE 'reports/%.html'
                  AND pf.file_path NOT LIKE 'reports/index.html'"""
        )

        _HEX_RE = re.compile(r'\b([0-9a-fA-F]{7,40})\b')

        for r in reports:
            eref = r['file_path']
            # Extract a nice label from <title> if present.
            m = re.search(r'<title>([^<]+)</title>',
                          r['content_text'] or '', re.IGNORECASE)
            label = m.group(1).strip() if m else eref
            if self._upsert_entity('Report', eref, 'author', label=label):
                added_e += 1

            # Auto-detect commit references. Deduplicate by hash prefix
            # per report so a report that mentions the same commit
            # 5 times only produces one impl row.
            seen = set()
            for match in _HEX_RE.finditer(r['content_text'] or ''):
                candidate = match.group(1).lower()
                # Filter out short hex substrings that are unlikely to
                # be commit hashes (color codes, content hashes, etc.).
                if len(candidate) < 7:
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)

                # Prefix-match against vcs_commits. If exactly one
                # match, we're confident. If zero or many, skip.
                matches = query_all(
                    """SELECT c.commit_hash, p.slug
                         FROM vcs_commits c
                         JOIN vcs_branches b ON b.id = c.branch_id
                         JOIN projects p     ON p.id = b.project_id
                        WHERE LOWER(c.commit_hash) LIKE ? || '%'
                        LIMIT 2""",
                    (candidate,),
                )
                if len(matches) != 1:
                    continue
                mrow = matches[0]

                # Insert impl row, respecting existing confirmed/rejected.
                existing = query_one(
                    """SELECT id, confidence FROM report_implementations
                        WHERE report_path = ? AND commit_hash = ?""",
                    (r['file_path'], mrow['commit_hash']),
                )
                if existing:
                    # Never overwrite a human decision.
                    if existing['confidence'] in (
                        'confirmed', 'verified', 'rejected'
                    ):
                        continue
                    # Auto-detected duplicate — leave it as-is.
                    continue
                execute(
                    """INSERT INTO report_implementations
                           (report_path, project_slug, commit_hash,
                            confidence)
                         VALUES (?, ?, ?, 'auto-detected')""",
                    (r['file_path'], r['project_slug'], mrow['commit_hash']),
                )
                added_impls += 1

                # Also add the graph relation for cross-authority queries.
                from_id = self._entity_id('Report', r['file_path'])
                to_id = self._entity_id(
                    'Commit', f"{mrow['slug']}/{mrow['commit_hash']}"
                )
                if from_id and to_id:
                    self._upsert_relation(
                        from_id, 'motivated', to_id, 'author'
                    )

        print(f"✓ ingest reports: +{added_e} entities, "
              f"+{added_impls} auto-detected impl link(s)")
        return 0

    # ==== REPORT LINKS ========================================================

    def report_link(self, args) -> int:
        """Manually record a Report ↔ Commit link at confidence='confirmed'."""
        from db_utils import query_one, execute
        # Resolve the commit hash (accept prefixes).
        matches = query_one(
            """SELECT c.commit_hash, p.slug
                 FROM vcs_commits c
                 JOIN vcs_branches b ON b.id = c.branch_id
                 JOIN projects p     ON p.id = b.project_id
                WHERE LOWER(c.commit_hash) LIKE LOWER(?) || '%'
                LIMIT 1""",
            (args.commit,),
        )
        if not matches:
            logger.error(f"No commit matches {args.commit!r}")
            return 1
        commit_hash = matches['commit_hash']
        slug = matches['slug']

        # Upsert with confidence='confirmed', preserve prior link's note.
        existing = query_one(
            """SELECT id FROM report_implementations
                WHERE report_path = ? AND commit_hash = ?""",
            (args.report_path, commit_hash),
        )
        import os
        author = os.environ.get('TEMPLEDB_AUTHOR') \
            or os.environ.get('USER') or None
        if existing:
            execute(
                """UPDATE report_implementations
                      SET confidence = 'confirmed',
                          note = COALESCE(?, note),
                          linked_by = ?,
                          linked_at = datetime('now')
                    WHERE id = ?""",
                (args.message, author, existing['id']),
            )
            print(f"✓ Link updated to confirmed: {args.report_path} ↔ "
                  f"{commit_hash[:12]}")
        else:
            execute(
                """INSERT INTO report_implementations
                       (report_path, project_slug, commit_hash,
                        confidence, note, linked_by)
                     VALUES (?, ?, ?, 'confirmed', ?, ?)""",
                (args.report_path, slug, commit_hash,
                 args.message, author),
            )
            print(f"✓ Link created (confirmed): {args.report_path} ↔ "
                  f"{commit_hash[:12]}")
        return 0

    def report_links(self, args) -> int:
        """Show Report ↔ Commit links. Filter by --report, --commit,
        or --confidence."""
        from db_utils import query_all
        clauses = []
        params = []
        if args.report:
            clauses.append("report_path LIKE ?")
            params.append(f"%{args.report}%")
        if args.commit:
            clauses.append("commit_hash LIKE ? || '%'")
            params.append(args.commit.lower())
        if args.confidence:
            clauses.append("confidence = ?")
            params.append(args.confidence)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = query_all(
            f"""SELECT id, report_path, commit_hash, confidence,
                       note, linked_by, linked_at
                  FROM report_implementations
                  {where}
                 ORDER BY linked_at DESC
                 LIMIT ?""",
            tuple(params) + (int(args.limit),),
        )
        if not rows:
            print("(no matching report links)")
            return 0
        confidence_glyph = {
            'auto-detected': '?',
            'confirmed':     '✓',
            'verified':      '✓✓',
            'rejected':      '✗',
        }
        for r in rows:
            g = confidence_glyph.get(r['confidence'], '?')
            note = f" — {r['note']}" if r['note'] else ""
            report_stem = r['report_path'].removeprefix('reports/')
            print(f"  {g:<3} #{r['id']:<4} "
                  f"{report_stem}  ↔  {r['commit_hash'][:12]}"
                  f"  ({r['confidence']}){note}")
        return 0

    def report_confirm(self, args) -> int:
        """Promote an auto-detected link to confirmed."""
        from db_utils import query_one, execute
        row = query_one(
            "SELECT confidence FROM report_implementations WHERE id=?",
            (int(args.id),),
        )
        if not row:
            logger.error(f"Report link #{args.id} not found")
            return 1
        if row['confidence'] == 'confirmed':
            print(f"Link #{args.id} already confirmed")
            return 0
        import os
        author = os.environ.get('TEMPLEDB_AUTHOR') \
            or os.environ.get('USER') or None
        execute(
            """UPDATE report_implementations
                  SET confidence = 'confirmed',
                      linked_by = COALESCE(linked_by, ?),
                      linked_at = datetime('now')
                WHERE id = ?""",
            (author, int(args.id)),
        )
        print(f"✓ Link #{args.id} confirmed")
        return 0

    def report_reject(self, args) -> int:
        """Mark a link rejected (auto-detection was wrong)."""
        from db_utils import query_one, execute
        row = query_one(
            "SELECT confidence FROM report_implementations WHERE id=?",
            (int(args.id),),
        )
        if not row:
            logger.error(f"Report link #{args.id} not found")
            return 1
        execute(
            """UPDATE report_implementations
                  SET confidence = 'rejected',
                      linked_at = datetime('now')
                WHERE id = ?""",
            (int(args.id),),
        )
        print(f"✗ Link #{args.id} rejected")
        return 0

    # ==== GRAPH ===============================================================

    def graph_explore(self, args) -> int:
        """Walk outbound relations from `<kind>/<external_ref>` one hop.

        Prints the entity + each outgoing edge with target entity."""
        from db_utils import query_one, query_all
        kind, sep, ref = args.entity.partition('/')
        if not sep:
            logger.error(
                "Expected `<kind>/<ref>` (e.g. `Commit/templedb/abc123`)"
            )
            return 1
        # ref may itself contain slashes (project/path). Everything
        # after the first slash is the external_ref.
        entity = query_one(
            """SELECT * FROM entities
                WHERE kind = ? AND external_ref = ? LIMIT 1""",
            (kind, ref),
        )
        if not entity:
            logger.error(f"Entity not found: {kind}/{ref}")
            return 2

        print(f"● {kind}/{ref}")
        print(f"  label:            {entity['label'] or '(none)'}")
        print(f"  source_authority: {entity['source_authority']}")
        print(f"  observed_at:      {entity['observed_at']}")

        outbound = query_all(
            """SELECT r.kind, r.source_authority, r.observed_at,
                      e2.kind AS to_kind, e2.external_ref AS to_ref,
                      e2.label AS to_label
                 FROM relations r
                 JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE r.from_entity_id = ?
                ORDER BY r.kind""",
            (entity['id'],),
        )
        if outbound:
            print()
            print(f"  outbound ({len(outbound)}):")
            for r in outbound:
                label = f" — {r['to_label']}" if r['to_label'] else ""
                print(f"    -[{r['kind']}]→ {r['to_kind']}/"
                      f"{r['to_ref']}{label}")

        inbound = query_all(
            """SELECT r.kind, e1.kind AS from_kind,
                      e1.external_ref AS from_ref, e1.label AS from_label
                 FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                WHERE r.to_entity_id = ?
                ORDER BY r.kind""",
            (entity['id'],),
        )
        if inbound:
            print()
            print(f"  inbound ({len(inbound)}):")
            for r in inbound:
                label = f" — {r['from_label']}" if r['from_label'] else ""
                print(f"    {r['from_kind']}/{r['from_ref']}{label} "
                      f"-[{r['kind']}]→")
        return 0

    def graph_stats(self, args) -> int:
        """Compact summary of the graph."""
        from db_utils import query_all, query_one
        n_entities = query_one(
            "SELECT COUNT(*) AS n FROM entities"
        )['n']
        n_relations = query_one(
            "SELECT COUNT(*) AS n FROM relations"
        )['n']
        by_kind = query_all(
            """SELECT kind, COUNT(*) AS n
                 FROM entities GROUP BY kind ORDER BY n DESC"""
        )
        by_rel = query_all(
            """SELECT kind, COUNT(*) AS n
                 FROM relations GROUP BY kind ORDER BY n DESC"""
        )
        print(f"entities:  {n_entities}")
        for r in by_kind:
            print(f"  {r['kind']:<20} {r['n']}")
        print()
        print(f"relations: {n_relations}")
        for r in by_rel:
            print(f"  {r['kind']:<20} {r['n']}")
        return 0

    # ==== DOCTOR ==============================================================

    def doctor_entities(self, args) -> int:
        """Run commuting-diagram invariant checks.

        See docs/ENTITY_GRAPH_DESIGN.md — each check names an invariant
        we expect to hold, and reports when it doesn't. Read-only:
        never mutates the graph, just reports drift.
        """
        checks = [
            ('edit_intent_applied_to_valid_commit',
             self._check_intent_applied_valid),
            ('every_edit_intent_has_entity',
             self._check_intents_have_entities),
            ('every_commit_has_entity',
             self._check_commits_have_entities),
            ('relations_reference_valid_entities',
             self._check_relations_valid_endpoints),
            ('report_impls_reference_valid_reports',
             self._check_report_impls_valid_report),
            ('report_impls_reference_valid_commits',
             self._check_report_impls_valid_commit),
        ]
        if args.check:
            checks = [c for c in checks if c[0] == args.check]
            if not checks:
                logger.error(f"Unknown check: {args.check}")
                return 1
        problems = []
        for name, fn in checks:
            issues = fn()
            marker = "✓" if not issues else "✗"
            print(f"  {marker} {name:<40} "
                  f"{'OK' if not issues else f'{len(issues)} issue(s)'}")
            for issue in issues[:5]:
                print(f"      - {issue}")
            if len(issues) > 5:
                print(f"      ... and {len(issues) - 5} more")
            problems.extend(issues)
        return 0 if not problems else 1

    def _check_intent_applied_valid(self):
        """Invariant: edit_intents.applied_commit_id points at a real
        vcs_commits row when non-null."""
        from db_utils import query_all
        rows = query_all(
            """SELECT i.id, i.applied_commit_id
                 FROM edit_intents i
                 LEFT JOIN vcs_commits c ON c.id = i.applied_commit_id
                WHERE i.applied_commit_id IS NOT NULL AND c.id IS NULL"""
        )
        return [f"EditIntent#{r['id']} applied_commit_id={r['applied_commit_id']} "
                f"has no matching vcs_commits row" for r in rows]

    def _check_intents_have_entities(self):
        """Invariant: every edit_intents row has a corresponding
        entities row of kind='EditIntent'."""
        from db_utils import query_all
        rows = query_all(
            """SELECT i.id
                 FROM edit_intents i
                 LEFT JOIN entities e
                   ON e.kind = 'EditIntent' AND e.external_ref = CAST(i.id AS TEXT)
                WHERE e.id IS NULL"""
        )
        return [f"EditIntent#{r['id']} not in entities table "
                f"(run `templedb ingest intent`)" for r in rows]

    def _check_commits_have_entities(self):
        """Invariant: every vcs_commits row has a corresponding
        entities row of kind='Commit'."""
        from db_utils import query_all
        rows = query_all(
            """SELECT c.id, c.commit_hash, p.slug
                 FROM vcs_commits c
                 JOIN vcs_branches b ON b.id = c.branch_id
                 JOIN projects p     ON p.id = b.project_id
                 LEFT JOIN entities e
                   ON e.kind = 'Commit'
                  AND e.external_ref = p.slug || '/' || c.commit_hash
                WHERE e.id IS NULL"""
        )
        return [f"Commit {r['slug']}/{r['commit_hash'][:12]} not in "
                f"entities table (run `templedb ingest git`)" for r in rows]

    def _check_report_impls_valid_report(self):
        """Invariant: every report_implementations.report_path exists as
        an active project_files entry. Catches renamed / deleted reports
        that still have dangling impl rows."""
        from db_utils import query_all
        rows = query_all(
            """SELECT ri.id, ri.report_path
                 FROM report_implementations ri
                 LEFT JOIN project_files pf
                   ON pf.file_path = ri.report_path
                  AND pf.status = 'active'
                 LEFT JOIN projects p ON p.id = pf.project_id
                     AND p.slug = ri.project_slug
                WHERE pf.id IS NULL"""
        )
        return [f"report_implementations#{r['id']} references missing "
                f"report {r['report_path']}" for r in rows]

    def _check_report_impls_valid_commit(self):
        """Invariant: every report_implementations.commit_hash matches
        a real vcs_commits row."""
        from db_utils import query_all
        rows = query_all(
            """SELECT ri.id, ri.commit_hash, ri.report_path
                 FROM report_implementations ri
                 LEFT JOIN vcs_commits c ON c.commit_hash = ri.commit_hash
                WHERE c.id IS NULL"""
        )
        return [f"report_implementations#{r['id']} references missing "
                f"commit {r['commit_hash'][:12]} "
                f"(report {r['report_path']})" for r in rows]

    def _check_relations_valid_endpoints(self):
        """Invariant: every relations row points at entities that
        still exist. FK cascade should prevent this but audit anyway."""
        from db_utils import query_all
        rows = query_all(
            """SELECT r.id
                 FROM relations r
                 LEFT JOIN entities e1 ON e1.id = r.from_entity_id
                 LEFT JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE e1.id IS NULL OR e2.id IS NULL"""
        )
        return [f"Relation#{r['id']} has a dangling endpoint" for r in rows]

    # ==== helpers ============================================================

    def _upsert_entity(self, kind: str, external_ref: str,
                       authority: str, label: Optional[str] = None) -> bool:
        """Insert-or-refresh an entity. Returns True if a new row was
        inserted, False on update. Refreshes observed_at either way."""
        from db_utils import execute, query_one
        existing = query_one(
            "SELECT id FROM entities WHERE kind=? AND external_ref=?",
            (kind, external_ref),
        )
        if existing:
            execute(
                """UPDATE entities SET label = COALESCE(?, label),
                                        observed_at = datetime('now'),
                                        source_authority = ?
                    WHERE id = ?""",
                (label, authority, existing['id']),
            )
            return False
        execute(
            """INSERT INTO entities
                   (kind, external_ref, source_authority, label)
                 VALUES (?, ?, ?, ?)""",
            (kind, external_ref, authority, label),
        )
        return True

    def _upsert_relation(self, from_id: int, kind: str, to_id: int,
                         authority: str) -> bool:
        """Insert-or-refresh a relation. Returns True on new insert."""
        from db_utils import execute, query_one
        existing = query_one(
            """SELECT id FROM relations
                WHERE from_entity_id=? AND kind=? AND to_entity_id=?""",
            (from_id, kind, to_id),
        )
        if existing:
            execute(
                """UPDATE relations SET observed_at = datetime('now')
                    WHERE id = ?""",
                (existing['id'],),
            )
            return False
        execute(
            """INSERT INTO relations
                   (from_entity_id, kind, to_entity_id, source_authority)
                 VALUES (?, ?, ?, ?)""",
            (from_id, kind, to_id, authority),
        )
        return True

    def _entity_id(self, kind: str, external_ref: str) -> Optional[int]:
        from db_utils import query_one
        row = query_one(
            "SELECT id FROM entities WHERE kind=? AND external_ref=?",
            (kind, external_ref),
        )
        return row['id'] if row else None

    def _commit_ref_from_id(self, commit_id: int) -> Optional[str]:
        """Build the (project_slug/commit_hash) external_ref for a
        vcs_commits row."""
        from db_utils import query_one
        row = query_one(
            """SELECT p.slug, c.commit_hash
                 FROM vcs_commits c
                 JOIN vcs_branches b ON b.id = c.branch_id
                 JOIN projects p     ON p.id = b.project_id
                WHERE c.id = ?""",
            (commit_id,),
        )
        return f"{row['slug']}/{row['commit_hash']}" if row else None


def register(cli):
    """Register `templedb ingest`, `graph explore/stats`, `doctor entities`."""
    cmd = EntityCommands()

    # --- templedb ingest ---
    ingest_parser = cli.subparsers.add_parser(
        'ingest',
        help='Populate entity graph from an authority (git, agent, intent)',
    )
    ingest_parser.add_argument(
        'source',
        choices=['git', 'agent', 'intent', 'reports', 'all'],
        help='Which ingestion adapter to run',
    )
    cli.commands['ingest'] = cmd.ingest

    # --- extend existing graph subparser if it exists ---
    # We inject explore/stats subcommands under `templedb graph`.
    # This is a bit gymnastic because graph is owned by another
    # module; safest to add a separate `templedb entity` namespace.
    entity_parser = cli.subparsers.add_parser(
        'entity',
        help='Entity graph query (Phase 3)',
    )
    esub = entity_parser.add_subparsers(dest='entity_subcommand', required=True)

    explore = esub.add_parser(
        'explore',
        help='Walk outbound + inbound relations of an entity one hop',
    )
    explore.add_argument('entity', help='<kind>/<external_ref>, e.g. Commit/templedb/abc123')
    cli.commands['entity.explore'] = cmd.graph_explore

    stats = esub.add_parser(
        'stats', help='Print entity + relation counts by kind',
    )
    cli.commands['entity.stats'] = cmd.graph_stats

    # --- templedb doctor entities ---
    doctor_parser = cli.subparsers.add_parser(
        'doctor',
        help='Reconcile checks (Phase 3 groundwork)',
    )
    dsub = doctor_parser.add_subparsers(dest='doctor_subcommand', required=True)
    ent = dsub.add_parser(
        'entities',
        help='Run commuting-diagram invariant checks',
    )
    ent.add_argument(
        '--check', metavar='NAME',
        help='Run one named check instead of all',
    )
    cli.commands['doctor.entities'] = cmd.doctor_entities

    # --- templedb report {link, links, confirm, reject} ---
    # Workflow F: Report ↔ Commit first-class span
    report_parser = cli.subparsers.add_parser(
        'report',
        help='Report ↔ Commit links (which reports got implemented)',
    )
    rsub = report_parser.add_subparsers(dest='report_subcommand', required=True)

    link = rsub.add_parser(
        'link',
        help='Manually record a Report ↔ Commit link (confidence=confirmed)',
    )
    link.add_argument('report_path',
                      help='reports/YYYY-MM-DD-HHMM-slug.html')
    link.add_argument('commit',
                      help='Commit hash (prefix ok)')
    link.add_argument('-m', '--message',
                      help='Note explaining the link')
    cli.commands['report.link'] = cmd.report_link

    links = rsub.add_parser(
        'links',
        help='List Report ↔ Commit links',
    )
    links.add_argument('-r', '--report',
                       help='Filter by report path substring')
    links.add_argument('-c', '--commit',
                       help='Filter by commit hash prefix')
    links.add_argument(
        '--confidence',
        choices=['auto-detected', 'confirmed', 'verified', 'rejected'],
        help='Filter by confidence level',
    )
    links.add_argument('--limit', default=50,
                       help='Max rows (default 50)')
    cli.commands['report.links'] = cmd.report_links

    confirm = rsub.add_parser(
        'confirm',
        help='Promote an auto-detected link to confirmed',
    )
    confirm.add_argument('id', help='report_implementations.id')
    cli.commands['report.confirm'] = cmd.report_confirm

    reject = rsub.add_parser(
        'reject',
        help='Mark a link rejected (auto-detection was wrong)',
    )
    reject.add_argument('id', help='report_implementations.id')
    cli.commands['report.reject'] = cmd.report_reject
