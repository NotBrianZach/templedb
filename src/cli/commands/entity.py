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
        for the local-algebras framing.

        Wraps each adapter run in an ingestion_runs row (migration 091)
        so freshness telemetry per authority is queryable via
        `templedb ingest history`."""
        adapters = {
            'git':    self._ingest_git,
            'agent':  self._ingest_agent,
            'intent': self._ingest_intent,
            'reports': self._ingest_reports,
            'nix':    self._ingest_nix,
            'deploy': self._ingest_deploy,
            'all':    self._ingest_all,
        }
        adapter = adapters.get(args.source)
        if not adapter:
            logger.error(
                f"Unknown ingest source {args.source!r}. "
                f"Available: {', '.join(sorted(adapters))}"
            )
            return 1
        # 'all' recursively calls ingest() for each sub-source, which
        # will each open their own run row. Don't double-wrap.
        if args.source == 'all':
            return adapter(args)
        return self._run_with_log(args.source, adapter, args)

    def _run_with_log(self, adapter_name, fn, args) -> int:
        """Execute an adapter inside an ingestion_runs row. Records
        status + any exception as notes. Adapters that want to report
        entity/relation counts can set self._last_counts before
        returning (a dict with e/r/x keys)."""
        from db_utils import execute
        self._last_counts = None
        run_id = execute(
            "INSERT INTO ingestion_runs (adapter) VALUES (?)",
            (adapter_name,),
        )
        try:
            rc = fn(args)
        except Exception as e:
            execute(
                """UPDATE ingestion_runs
                      SET finished_at = datetime('now'),
                          status = 'error',
                          notes = ?
                    WHERE id = ?""",
                (str(e), run_id),
            )
            raise
        # Success — record counts if adapter set them.
        counts = self._last_counts or {}
        execute(
            """UPDATE ingestion_runs
                  SET finished_at = datetime('now'),
                      status = ?,
                      entities_added = ?,
                      relations_added = ?,
                      extra_added = ?
                WHERE id = ?""",
            ('ok' if rc == 0 else 'partial',
             int(counts.get('e', 0)),
             int(counts.get('r', 0)),
             int(counts.get('x', 0)),
             run_id),
        )
        return rc

    def ingest_history(self, args) -> int:
        """Print the last N ingestion runs. Handy for 'when did this
        adapter last see updates?' questions."""
        from db_utils import query_all
        rows = query_all(
            """SELECT id, adapter, started_at, finished_at, status,
                      entities_added, relations_added, extra_added,
                      notes
                 FROM ingestion_runs
                ORDER BY started_at DESC
                LIMIT ?""",
            (int(args.limit),),
        )
        if not rows:
            print("(no ingestion runs recorded)")
            return 0
        marker = {'ok': '✓', 'partial': '⋯', 'error': '✗', 'running': '…'}
        for r in rows:
            m = marker.get(r['status'], '?')
            counts = (f"+{r['entities_added']}e "
                      f"+{r['relations_added']}r "
                      f"+{r['extra_added']}x")
            note = f"  — {r['notes']}" if r['notes'] else ""
            print(f"  {m} #{r['id']:<4} {r['adapter']:<9} "
                  f"{r['started_at']}  {r['status']:<7}  {counts}{note}")
        return 0

    def _ingest_all(self, args) -> int:
        for sub in ('git', 'agent', 'intent', 'reports', 'nix', 'deploy'):
            args.source = sub
            rc = self.ingest(args)
            if rc != 0:
                return rc
        return 0

    def _ingest_deploy(self, args) -> int:
        """Ingest deployment_history as first-class Deployment span.

        Deployment is a junction with its own identity + lifecycle
        (status: in_progress / success / failed / rolled_back) plus
        timestamps, per the schema-report's Phase 3 promotion queue.
        We don't need a migration because deployment_history already
        carries all this — just wire it into the entity graph.

        Emits:
          Deployment entities (kind='Deployment',
              external_ref=deployment_history.id as string,
              source_authority='templedb')
          Deployment → targets → Machine (via target_name)
          Deployment → from-commit → Commit (fuzzy match on commit_hash)
        """
        from db_utils import query_all
        added_e, added_r = 0, 0

        deployments = query_all(
            """SELECT id, project_id, target_name, deployment_type,
                      commit_hash, status, started_at, completed_at,
                      duration_ms, deployed_by
                 FROM deployment_history"""
        )
        for d in deployments:
            eref = str(d['id'])
            # Nice compact label: 'zMothership2 deploy (success)'
            status_marker = {
                'success': '✓', 'failed': '✗',
                'rolled_back': '↩', 'in_progress': '⋯',
            }.get(d['status'], '?')
            label = (f"{d['target_name']} {d['deployment_type']} "
                     f"{status_marker}")
            if self._upsert_entity('Deployment', eref, 'templedb',
                                   label=label):
                added_e += 1

        # Deployment → targets → Machine
        for d in deployments:
            from_id = self._entity_id('Deployment', str(d['id']))
            to_id = self._entity_id('Machine', d['target_name'])
            if from_id and to_id:
                if self._upsert_relation(from_id, 'targets',
                                         to_id, 'templedb'):
                    added_r += 1

        # Deployment → from-commit → Commit (fuzzy match)
        for d in deployments:
            if not d['commit_hash']:
                continue
            from_id = self._entity_id('Deployment', str(d['id']))
            if not from_id:
                continue
            commit_rows = query_all(
                """SELECT external_ref FROM entities
                    WHERE kind = 'Commit'
                      AND (external_ref LIKE '%/' || ?
                           OR LOWER(external_ref) LIKE '%/' || LOWER(?))
                    LIMIT 1""",
                (d['commit_hash'], d['commit_hash']),
            )
            if commit_rows:
                to_id = self._entity_id(
                    'Commit', commit_rows[0]['external_ref']
                )
                if to_id:
                    if self._upsert_relation(
                        from_id, 'from-commit', to_id, 'templedb'
                    ):
                        added_r += 1

        print(f"✓ ingest deploy: +{added_e} entities, "
              f"+{added_r} relations")
        self._last_counts = {'e': added_e, 'r': added_r}
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
        self._last_counts = {'e': added_e, 'r': added_r}
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

        # ToolCall entities (Phase 3 span extracted from agent_events
        # via migration 094). Each tool_calls row becomes a ToolCall
        # entity; the AgentSession that ran it gets a `invoked` edge.
        # See docs/ENTITY_GRAPH_DESIGN.md — ToolCall is a first-class
        # span AgentRun ← ToolCall → Tool.
        tool_calls = query_all(
            """SELECT tc.id, tc.tool_name, tc.status,
                      s.session_uuid AS suid
                 FROM tool_calls tc
                 JOIN agent_runs ar ON ar.id = tc.run_id
                 JOIN agent_sessions s ON s.id = ar.session_id"""
        )
        for tc in tool_calls:
            eref = str(tc['id'])
            label = f"{tc['tool_name']} ({tc['status']})"
            if self._upsert_entity('ToolCall', eref,
                                   'agent-runtime', label=label):
                added_e += 1

        # AgentSession → invoked → ToolCall
        for tc in tool_calls:
            from_id = self._entity_id('AgentSession', tc['suid'])
            to_id = self._entity_id('ToolCall', str(tc['id']))
            if from_id and to_id:
                if self._upsert_relation(from_id, 'invoked',
                                         to_id, 'agent-runtime'):
                    added_r += 1

        print(f"✓ ingest agent: +{added_e} entities, +{added_r} relations")
        self._last_counts = {'e': added_e, 'r': added_r}
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
        self._last_counts = {'e': added_e, 'r': added_r}
        return 0

    def _ingest_nix(self, args) -> int:
        """Ingest nix-authority entities: StorePath, Derivation, AstBuild
        + their relations.

        Reads three existing tables:
          nix_store_paths — populated by earlier nix-store scans
          ast_builds      — first-class span (Commit ← Build → StorePath)
                            per docs/ENTITY_GRAPH_DESIGN.md

        Emits:
          StorePath entities (kind='StorePath', external_ref=store_path)
          Derivation entities (kind='Derivation', external_ref=deriver
                                store path when present)
          AstBuild entities (kind='AstBuild',
                             external_ref='{host}/{output_hash}')

        Relations:
          StorePath → built-by → Derivation (from nix_store_paths.deriver)
          AstBuild → produces → StorePath (from ast_builds.output_path)
          AstBuild → built-for-host → the host is stored on the entity
                                       label, not a relation

        Note: ast_builds does NOT currently carry a commit_hash column,
        so we can't emit AstBuild → built-from → Commit yet. That would
        need a schema change (add commit_hash to ast_builds, or join
        via config_nodes → commit). Deferred to a follow-up.
        """
        from db_utils import query_all
        added_e, added_r = 0, 0

        # 1. StorePath entities from nix_store_paths.
        paths = query_all(
            """SELECT store_path, store_hash, name, deriver, is_valid,
                      nar_size, closure_size, last_seen_at
                 FROM nix_store_paths
                WHERE is_valid = 1"""
        )
        for p in paths:
            label = f"{p['name']} ({p['store_hash'][:8]})"
            if self._upsert_entity('StorePath', p['store_path'],
                                   'nix', label=label):
                added_e += 1

        # 2. Derivation entities from unique nix_store_paths.deriver.
        derivers = query_all(
            """SELECT DISTINCT deriver
                 FROM nix_store_paths
                WHERE deriver IS NOT NULL
                  AND is_valid = 1"""
        )
        for d in derivers:
            drv = d['deriver']
            # Derivation label: strip /nix/store/<hash>- prefix
            label = drv.split('/')[-1] if '/' in drv else drv
            if self._upsert_entity('Derivation', drv, 'nix', label=label):
                added_e += 1

        # 3. StorePath → built-by → Derivation relations
        deriver_pairs = query_all(
            """SELECT store_path, deriver
                 FROM nix_store_paths
                WHERE deriver IS NOT NULL AND is_valid = 1"""
        )
        for row in deriver_pairs:
            sp_id = self._entity_id('StorePath', row['store_path'])
            drv_id = self._entity_id('Derivation', row['deriver'])
            if sp_id and drv_id:
                if self._upsert_relation(sp_id, 'built-by', drv_id, 'nix'):
                    added_r += 1

        # 4. AstBuild entities (first-class span).
        builds = query_all(
            """SELECT id, output_hash, host_name, output_path,
                      nix_buildable, generated_at
                 FROM ast_builds"""
        )
        for b in builds:
            eref = f"{b['host_name']}/{b['output_hash']}"
            buildable = ('' if b['nix_buildable'] is None
                        else ' ✓' if b['nix_buildable']
                        else ' ✗')
            label = (f"{b['host_name']} "
                     f"({b['output_hash'][:12]}){buildable}")
            if self._upsert_entity('AstBuild', eref, 'nix',
                                   label=label):
                added_e += 1

        # 5. AstBuild → produces → StorePath relations
        for b in builds:
            eref = f"{b['host_name']}/{b['output_hash']}"
            from_id = self._entity_id('AstBuild', eref)
            to_id = self._entity_id('StorePath', b['output_path'])
            if from_id and to_id:
                if self._upsert_relation(from_id, 'produces',
                                         to_id, 'nix'):
                    added_r += 1

        # 5b. AstBuild → built-from → Commit
        #     No commit_hash column on ast_builds, so bridge via
        #     nix_generations: AstBuild.output_path matches
        #     Generation.toplevel_path, and Generation.commit_hash
        #     is the source. This uses only existing schema.
        for b in builds:
            eref = f"{b['host_name']}/{b['output_hash']}"
            from_id = self._entity_id('AstBuild', eref)
            if not from_id:
                continue
            # Find a Generation with matching toplevel_path AND
            # matching host_name (both must agree to be safe).
            gen_row = query_all(
                """SELECT commit_hash FROM nix_generations
                    WHERE toplevel_path = ?
                      AND machine_name = ?
                      AND commit_hash IS NOT NULL
                    LIMIT 1""",
                (b['output_path'], b['host_name']),
            )
            if not gen_row or not gen_row[0]['commit_hash']:
                continue
            commit_hash = gen_row[0]['commit_hash']
            commit_rows = query_all(
                """SELECT external_ref FROM entities
                    WHERE kind = 'Commit'
                      AND (external_ref LIKE '%/' || ?
                           OR LOWER(external_ref) LIKE
                              '%/' || LOWER(?))
                    LIMIT 1""",
                (commit_hash, commit_hash),
            )
            if commit_rows:
                to_id = self._entity_id(
                    'Commit', commit_rows[0]['external_ref']
                )
                if to_id:
                    if self._upsert_relation(
                        from_id, 'built-from', to_id, 'nix'
                    ):
                        added_r += 1

        # 6a. Machine entities from fleet_machines (source_authority=
        #     templedb, since fleet is our own config).
        machines = query_all(
            """SELECT machine_name, machine_uuid, target_host,
                      system_type
                 FROM fleet_machines"""
        )
        for m in machines:
            eref = m['machine_name']
            label = (f"{m['machine_name']}"
                     f" ({m['target_host']})" if m['target_host']
                     else m['machine_name'])
            if self._upsert_entity('Machine', eref, 'templedb',
                                   label=label):
                added_e += 1

        # 6b. Machine entities from nix_generations.machine_name for
        #     any hosts not in fleet_machines. These are NixOS host
        #     names observed via generation records — source_authority
        #     is 'nix' (the nix-generation scan told us they exist).
        #     Covers zMothership2, zStation, etc. — configured but
        #     not registered as fleet targets.
        observed_hosts = query_all(
            """SELECT DISTINCT machine_name FROM nix_generations"""
        )
        for h in observed_hosts:
            if self._entity_id('Machine', h['machine_name']):
                continue  # already covered by fleet_machines path
            if self._upsert_entity('Machine', h['machine_name'], 'nix',
                                   label=f"{h['machine_name']} "
                                         f"(via nix generations)"):
                added_e += 1

        # 7. Generation entities from nix_generations.
        #    Rich span: Machine ← Generation → Commit + StorePath
        gens = query_all(
            """SELECT id, machine_name, generation_number,
                      commit_hash, toplevel_path,
                      switched_at, switch_success
                 FROM nix_generations"""
        )
        for g in gens:
            eref = f"{g['machine_name']}/gen-{g['generation_number']}"
            marker = '' if g['switch_success'] else ' ✗'
            label = (f"{g['machine_name']} gen "
                     f"{g['generation_number']}{marker}")
            if self._upsert_entity('Generation', eref, 'nix',
                                   label=label):
                added_e += 1

        # 8. Machine → ran → Generation
        for g in gens:
            from_id = self._entity_id('Machine', g['machine_name'])
            to_id = self._entity_id(
                'Generation',
                f"{g['machine_name']}/gen-{g['generation_number']}"
            )
            if from_id and to_id:
                if self._upsert_relation(from_id, 'ran', to_id, 'nix'):
                    added_r += 1

        # 9. Generation → built-from → Commit (when commit_hash known
        #    and a matching Commit entity exists).
        for g in gens:
            if not g['commit_hash']:
                continue
            from_id = self._entity_id(
                'Generation',
                f"{g['machine_name']}/gen-{g['generation_number']}"
            )
            if not from_id:
                continue
            # Match commit_hash against Commit entities. External_ref
            # is 'project_slug/hash', so we need a fuzzy match.
            commit_rows = query_all(
                """SELECT external_ref FROM entities
                    WHERE kind = 'Commit'
                      AND (external_ref LIKE '%/' || ?
                           OR LOWER(external_ref) LIKE '%/' || LOWER(?))
                    LIMIT 1""",
                (g['commit_hash'], g['commit_hash']),
            )
            if commit_rows:
                to_id = self._entity_id(
                    'Commit', commit_rows[0]['external_ref']
                )
                if to_id:
                    if self._upsert_relation(
                        from_id, 'built-from', to_id, 'nix'
                    ):
                        added_r += 1

        # 10. Generation → installs → StorePath (via toplevel_path)
        for g in gens:
            if not g['toplevel_path']:
                continue
            from_id = self._entity_id(
                'Generation',
                f"{g['machine_name']}/gen-{g['generation_number']}"
            )
            to_id = self._entity_id('StorePath', g['toplevel_path'])
            if from_id and to_id:
                if self._upsert_relation(from_id, 'installs',
                                         to_id, 'nix'):
                    added_r += 1

        print(f"✓ ingest nix: +{added_e} entities, +{added_r} relations")
        self._last_counts = {'e': added_e, 'r': added_r}
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
        self._last_counts = {'e': added_e, 'r': 0, 'x': added_impls}
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

    def graph_trace(self, args) -> int:
        """Recursive BFS from a starting entity, printing a path tree.

        Turns the entity graph into a queryable substrate: the 5-hop
        provenance query the plan has been building toward is now
        one command.

        Args:
          entity:     <kind>/<external_ref> to start from
          depth:      max hops (default 3)
          direction:  out (outbound edges only, default), in, or both
          via:        comma-separated relation kinds to follow;
                      empty = all
          limit:      per-node fan-out cap (avoid StorePath explosions)
        """
        from db_utils import query_one, query_all

        kind, sep, ref = args.entity.partition('/')
        if not sep:
            logger.error(
                "Expected `<kind>/<ref>` "
                "(e.g. `Machine/zMothership2`)"
            )
            return 1
        start = query_one(
            """SELECT id FROM entities
                WHERE kind = ? AND external_ref = ?""",
            (kind, ref),
        )
        if not start:
            logger.error(f"Entity not found: {kind}/{ref}")
            return 2

        via = None
        if args.via:
            via = {v.strip() for v in args.via.split(',') if v.strip()}
        direction = args.direction or 'out'
        depth = int(args.depth)
        fanout_limit = int(args.limit)

        visited = {start['id']}
        # Queue of (entity_id, path_prefix). path_prefix is a list of
        # ("kind/ref", "→ relkind →" | "← relkind ←") strings.
        queue = [(start['id'], [f"● {kind}/{ref}"])]
        print(queue[0][1][0])

        current_depth = 0
        while queue and current_depth < depth:
            next_queue = []
            for eid, prefix in queue:
                edges = self._fetch_edges(
                    eid, direction, via, fanout_limit,
                )
                for e in edges:
                    peer_id = e['peer_id']
                    if peer_id in visited:
                        continue
                    visited.add(peer_id)
                    if e['dir'] == 'out':
                        arrow = f"─[{e['relkind']}]→"
                    else:
                        arrow = f"←[{e['relkind']}]─"
                    label_bit = f" — {e['peer_label']}" \
                        if e['peer_label'] else ""
                    indent = "  " * (current_depth + 1)
                    print(f"{indent}{arrow} {e['peer_kind']}/"
                          f"{e['peer_ref']}{label_bit}")
                    next_queue.append((peer_id, prefix + [arrow]))
            queue = next_queue
            current_depth += 1
        return 0

    def _fetch_edges(self, entity_id, direction, via, limit):
        """Fetch one hop from entity_id in the given direction,
        filtered by via (set of relation kinds) if provided."""
        from db_utils import query_all
        rows = []
        if direction in ('out', 'both'):
            where = "r.from_entity_id = ?"
            if via:
                placeholders = ','.join('?' for _ in via)
                where += f" AND r.kind IN ({placeholders})"
            params = [entity_id] + list(via) if via else [entity_id]
            outbound = query_all(
                f"""SELECT r.kind AS relkind,
                           e.id AS peer_id, e.kind AS peer_kind,
                           e.external_ref AS peer_ref,
                           e.label AS peer_label
                      FROM relations r
                      JOIN entities e ON e.id = r.to_entity_id
                     WHERE {where}
                     LIMIT ?""",
                tuple(params) + (limit,),
            )
            for r in outbound:
                rows.append({**dict(r), 'dir': 'out'})
        if direction in ('in', 'both'):
            where = "r.to_entity_id = ?"
            if via:
                placeholders = ','.join('?' for _ in via)
                where += f" AND r.kind IN ({placeholders})"
            params = [entity_id] + list(via) if via else [entity_id]
            inbound = query_all(
                f"""SELECT r.kind AS relkind,
                           e.id AS peer_id, e.kind AS peer_kind,
                           e.external_ref AS peer_ref,
                           e.label AS peer_label
                      FROM relations r
                      JOIN entities e ON e.id = r.from_entity_id
                     WHERE {where}
                     LIMIT ?""",
                tuple(params) + (limit,),
            )
            for r in inbound:
                rows.append({**dict(r), 'dir': 'in'})
        return rows

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
            ('every_tool_call_has_entity',
             self._check_tool_calls_have_entities),
            ('every_generation_with_commit_has_relation',
             self._check_generations_have_built_from),
            ('every_deployment_has_entity',
             self._check_deployments_have_entities),
        ]
        if args.check:
            checks = [c for c in checks if c[0] == args.check]
            if not checks:
                logger.error(f"Unknown check: {args.check}")
                return 1
        import json, time
        from db_utils import execute
        problems = []
        for name, fn in checks:
            t0 = time.monotonic()
            try:
                issues = fn()
                status = 'ok' if not issues else 'violated'
                note = None
            except Exception as e:
                issues = []
                status = 'error'
                note = str(e)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            marker = {'ok': '✓', 'violated': '✗',
                      'error': '!'}.get(status, '?')
            summary = ('OK' if status == 'ok'
                       else f'{len(issues)} issue(s)'
                       if status == 'violated'
                       else f'error: {note}')
            print(f"  {marker} {name:<40} {summary}")
            for issue in issues[:5]:
                print(f"      - {issue}")
            if len(issues) > 5:
                print(f"      ... and {len(issues) - 5} more")
            # Persist to invariant_checks (migration 092).
            try:
                execute(
                    """INSERT INTO invariant_checks
                           (check_name, duration_ms, status,
                            issue_count, sample_issues_json)
                         VALUES (?, ?, ?, ?, ?)""",
                    (name, elapsed_ms, status, len(issues),
                     json.dumps(issues[:20]) if issues else note),
                )
            except Exception as e:
                # Non-fatal — doctor is diagnostic, not required.
                logger.debug(f"invariant_checks record failed: {e}")
            problems.extend(issues)
        return 0 if not problems else 1

    def doctor_history(self, args) -> int:
        """Print the recent history of invariant check results.

        Handy for 'when did this drift first appear?' questions.
        Filter by --check to see one invariant over time."""
        from db_utils import query_all
        clauses = []
        params = []
        if args.check:
            clauses.append("check_name = ?")
            params.append(args.check)
        if args.violated_only:
            clauses.append("status != 'ok'")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = query_all(
            f"""SELECT id, check_name, ran_at, duration_ms, status,
                       issue_count, sample_issues_json
                  FROM invariant_checks
                  {where}
                 ORDER BY ran_at DESC
                 LIMIT ?""",
            tuple(params) + (int(args.limit),),
        )
        if not rows:
            print("(no invariant check history yet — run "
                  "`templedb doctor entities` first)")
            return 0
        marker = {'ok': '✓', 'violated': '✗', 'error': '!'}
        for r in rows:
            m = marker.get(r['status'], '?')
            summary = ('OK' if r['status'] == 'ok'
                       else f"{r['issue_count']} issue(s)"
                       if r['status'] == 'violated'
                       else 'error')
            print(f"  {m} #{r['id']:<5} {r['ran_at']}  "
                  f"{r['check_name']:<40} {summary}")
        return 0

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

    def _check_deployments_have_entities(self):
        """Invariant: every deployment_history row has a matching
        Deployment entity. Flags stale ingest after new deploys."""
        from db_utils import query_all
        rows = query_all(
            """SELECT dh.id, dh.target_name, dh.status
                 FROM deployment_history dh
                 LEFT JOIN entities e
                   ON e.kind = 'Deployment'
                  AND e.external_ref = CAST(dh.id AS TEXT)
                WHERE e.id IS NULL
                LIMIT 100"""
        )
        return [f"deployment_history#{r['id']} "
                f"({r['target_name']}, {r['status']}) not in "
                f"entities table (run `templedb ingest deploy`)"
                for r in rows]

    def _check_generations_have_built_from(self):
        """Invariant: every nix_generations row with a commit_hash
        should have a corresponding Generation → built-from → Commit
        relation, provided both entities exist. Flags stale ingest.
        This is a commuting-diagram check: the join through
        nix_generations should match the join through relations."""
        from db_utils import query_all
        rows = query_all(
            """SELECT g.id, g.machine_name, g.generation_number,
                      g.commit_hash
                 FROM nix_generations g
                WHERE g.commit_hash IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                        FROM entities e_gen
                        JOIN relations r
                          ON r.from_entity_id = e_gen.id
                         AND r.kind = 'built-from'
                        JOIN entities e_com
                          ON e_com.id = r.to_entity_id
                       WHERE e_gen.kind = 'Generation'
                         AND e_gen.external_ref =
                             g.machine_name || '/gen-' ||
                             g.generation_number
                         AND e_com.kind = 'Commit'
                         AND (e_com.external_ref LIKE '%/' || g.commit_hash
                              OR LOWER(e_com.external_ref) LIKE
                                  '%/' || LOWER(g.commit_hash))
                  )
                LIMIT 50"""
        )
        return [f"nix_generation#{r['id']} "
                f"{r['machine_name']}/gen-{r['generation_number']} "
                f"(commit {r['commit_hash'][:12]}) has no built-from "
                f"relation — run `templedb ingest nix`" for r in rows]

    def _check_tool_calls_have_entities(self):
        """Invariant: every tool_calls row has a corresponding ToolCall
        entity. Detects when agent ingest is behind after new tool
        events landed."""
        from db_utils import query_all
        rows = query_all(
            """SELECT tc.id
                 FROM tool_calls tc
                 LEFT JOIN entities e
                   ON e.kind = 'ToolCall'
                  AND e.external_ref = CAST(tc.id AS TEXT)
                WHERE e.id IS NULL
                LIMIT 200"""  # cap since backfill can be large
        )
        return [f"ToolCall#{r['id']} not in entities table "
                f"(run `templedb ingest agent`)" for r in rows]

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
        help='Populate entity graph from an authority (git, agent, intent, reports, history)',
    )
    ingest_parser.add_argument(
        'source',
        choices=['git', 'agent', 'intent', 'reports', 'nix', 'deploy',
                 'all', 'history'],
        help="Which ingestion adapter to run, or 'history' to show past runs",
    )
    ingest_parser.add_argument(
        '--limit', default=20,
        help='For history: max rows (default 20)',
    )

    def _ingest_dispatch(args):
        if args.source == 'history':
            return cmd.ingest_history(args)
        return cmd.ingest(args)
    cli.commands['ingest'] = _ingest_dispatch

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

    trace = esub.add_parser(
        'trace',
        help='Recursive BFS walk from an entity — multi-hop graph queries',
    )
    trace.add_argument('entity',
                       help='<kind>/<external_ref> (e.g. Machine/zMothership2)')
    trace.add_argument('--depth', default=3,
                       help='Max hops (default 3)')
    trace.add_argument('--direction',
                       choices=['out', 'in', 'both'], default='out',
                       help="Follow outbound (default), inbound, or both")
    trace.add_argument('--via',
                       help='Comma-separated relation kinds to follow '
                            '(default: all)')
    trace.add_argument('--limit', default=10,
                       help='Per-node fan-out cap (default 10)')
    cli.commands['entity.trace'] = cmd.graph_trace

    # --- templedb doctor entities / history ---
    doctor_parser = cli.subparsers.add_parser(
        'doctor',
        help='Reconcile checks (Phase 3 groundwork)',
    )
    dsub = doctor_parser.add_subparsers(dest='doctor_subcommand', required=True)
    ent = dsub.add_parser(
        'entities',
        help='Run commuting-diagram invariant checks (persisted to invariant_checks)',
    )
    ent.add_argument(
        '--check', metavar='NAME',
        help='Run one named check instead of all',
    )
    cli.commands['doctor.entities'] = cmd.doctor_entities

    dhist = dsub.add_parser(
        'history',
        help='Show recent invariant check history (drift over time)',
    )
    dhist.add_argument('--check', metavar='NAME',
                       help='Filter to one invariant name')
    dhist.add_argument('--violated-only', action='store_true',
                       help='Only show violations / errors')
    dhist.add_argument('--limit', default=30,
                       help='Max rows (default 30)')
    cli.commands['doctor.history'] = cmd.doctor_history

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
