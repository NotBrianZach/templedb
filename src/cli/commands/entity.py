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
        for sub in ('git', 'agent', 'intent'):
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
        choices=['git', 'agent', 'intent', 'all'],
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
