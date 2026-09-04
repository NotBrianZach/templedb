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

    # Per-adapter declared version. Bump when the adapter's emitted
    # shape changes (new entity kinds, new relations, resolution
    # semantics). Recorded on every ingestion_runs row so cross-machine
    # drift shows up as a queryable divergence, not silent noise.
    # See docs/ENTITY_GRAPH_DESIGN.md; recommended by parallel-session
    # report 2026-09-03-1947-answers-to-open-questions-*.html Q3.
    # Per-kind default sync_scope. Values: 'fleet' | 'machine-local' | 'none'.
    # Set at ingest time in _upsert_entity. Q5 answer classification.
    _SYNC_SCOPES = {
        'Project':      'fleet',
        'Commit':       'fleet',
        'File':         'fleet',
        'Deployment':   'fleet',
        'Machine':      'fleet',
        'Generation':   'fleet',
        'AstBuild':     'fleet',
        'Report':       'fleet',
        'Decision':     'fleet',
        'EditIntent':   'fleet',
        'Symbol':       'machine-local',
        'ToolCall':     'machine-local',
        'AgentSession': 'machine-local',
        # Nix store: default machine-local since per-machine.
        # Deployment references bump these implicitly at query time.
        'StorePath':    'machine-local',
        'Derivation':   'machine-local',
    }

    _ADAPTER_VERSIONS = {
        'git':     '1.1',    # 1.1 dual-writes Commit.attributes_json
                             # from vcs_commit_parents + metadata (Q4)
        'agent':   '1.1',    # 1.1 emits ToolCall entities too
        'intent':  '1.0',
        'reports': '1.0',
        'nix':     '1.2',    # 1.2 emits Machine + Generation + spans
        'deploy':  '1.0',
        'python':  '1.3',    # 1.3 = defines + calls + methods + imports
    }

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
            'python': self._ingest_python,
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
        version = self._ADAPTER_VERSIONS.get(adapter_name)
        run_id = execute(
            """INSERT INTO ingestion_runs (adapter, adapter_version)
                 VALUES (?, ?)""",
            (adapter_name, version),
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

    def ingest_schedule(self, args) -> int:
        """Manage the systemd user timer for scheduled ingest.

        Parallel to `templedb reconcile schedule`. Ingest is cheaper
        than reconcile (no SSH), so default cadence is hourly rather
        than daily — new commits, intents, deployments show up in the
        graph within ~1h without manual runs.

        Sub-actions:
          install [--interval SPEC]   default 'hourly' (systemd OnCalendar)
          uninstall
          status
        """
        action = args.action
        if action == 'install':
            return self._ingest_schedule_install(args)
        if action == 'uninstall':
            return self._ingest_schedule_uninstall()
        if action == 'status':
            return self._ingest_schedule_status()
        logger.error(f"Unknown schedule action: {action}")
        return 1

    def _ingest_schedule_install(self, args) -> int:
        import shutil
        import subprocess
        from pathlib import Path

        interval = args.interval or 'hourly'
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)

        templedb_bin = shutil.which('templedb') \
            or '/home/zach/.nix-profile/bin/templedb'

        service = f"""[Unit]
Description=TempleDB scheduled ingest — refresh entity graph
Documentation=file://{Path.home()}/.config/templedb/checkouts/templedb/docs/ENTITY_GRAPH_DESIGN.md

[Service]
Type=oneshot
ExecStart={templedb_bin} ingest all
"""

        timer = f"""[Unit]
Description=Trigger templedb ingest {interval}
Documentation=file://{Path.home()}/.config/templedb/checkouts/templedb/docs/ENTITY_GRAPH_DESIGN.md

[Timer]
OnCalendar={interval}
RandomizedDelaySec=5m
Persistent=true

[Install]
WantedBy=timers.target
"""

        svc_path = unit_dir / "templedb-ingest.service"
        timer_path = unit_dir / "templedb-ingest.timer"
        svc_path.write_text(service)
        timer_path.write_text(timer)

        for cmd, label in (
            (['systemctl', '--user', 'daemon-reload'], 'reload'),
            (['systemctl', '--user', 'enable', '--now',
              'templedb-ingest.timer'], 'enable + start'),
        ):
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                logger.error(f"systemctl failed ({label}): "
                             f"{r.stderr.strip()}")
                return 2

        print(f"✓ Installed templedb-ingest.timer")
        print(f"  units:      {unit_dir}")
        print(f"  oncalendar: {interval} (randomized ±5m)")
        print()
        print("  status:  templedb ingest schedule status")
        print("  logs:    journalctl --user -u templedb-ingest "
              "--since '24 hours ago'")
        print("  disable: templedb ingest schedule uninstall")
        return 0

    def _ingest_schedule_uninstall(self) -> int:
        import subprocess
        from pathlib import Path
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        for cmd in (
            ['systemctl', '--user', 'disable', '--now',
             'templedb-ingest.timer'],
            ['systemctl', '--user', 'reset-failed',
             'templedb-ingest.service'],
        ):
            subprocess.run(cmd, capture_output=True)
        for name in ('templedb-ingest.timer',
                     'templedb-ingest.service'):
            p = unit_dir / name
            if p.exists():
                p.unlink()
        subprocess.run(
            ['systemctl', '--user', 'daemon-reload'],
            capture_output=True,
        )
        print("✓ Uninstalled templedb-ingest timer + service")
        return 0

    def _ingest_schedule_status(self) -> int:
        import subprocess
        r = subprocess.run(
            ['systemctl', '--user', 'list-timers',
             'templedb-ingest.timer', '--no-pager'],
            capture_output=True, text=True,
        )
        print(r.stdout)
        r2 = subprocess.run(
            ['systemctl', '--user', 'status',
             'templedb-ingest.service', '--no-pager', '-n', '3'],
            capture_output=True, text=True,
        )
        print(r2.stdout)
        return 0

    def ingest_history(self, args) -> int:
        """Print the last N ingestion runs. Handy for 'when did this
        adapter last see updates?' questions."""
        from db_utils import query_all
        rows = query_all(
            """SELECT id, adapter, adapter_version, started_at,
                      finished_at, status,
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
            ver = f" v{r['adapter_version']}" if r['adapter_version'] else ""
            note = f"  — {r['notes']}" if r['notes'] else ""
            print(f"  {m} #{r['id']:<4} {r['adapter']:<9}{ver:<6} "
                  f"{r['started_at']}  {r['status']:<7}  {counts}{note}")
        return 0

    def _ingest_all(self, args) -> int:
        for sub in ('git', 'agent', 'intent', 'reports', 'nix', 'deploy',
                    'python'):
            args.source = sub
            rc = self.ingest(args)
            if rc != 0:
                return rc
        return 0

    def _ingest_python(self, args) -> int:
        """Parse every .py file in the DB and emit Symbol entities
        for module-level function + class definitions, with
        File → defines → Symbol relations.

        Zero external dependencies — uses stdlib `ast` module. Ships
        Phase 4 groundwork for the class of code-intelligence queries
        SCIP would give you across many languages; here we cover
        Python natively.

        Skips files that fail to parse (syntax errors in old snapshots,
        Python-2-only files). Counts skipped files in `extra_added`.
        """
        import ast
        from db_utils import query_all
        added_e, added_r, skipped = 0, 0, 0

        rows = query_all(
            """SELECT p.slug AS slug, pf.file_path AS file_path,
                      cb.content_text AS content
                 FROM project_files pf
                 JOIN projects p ON p.id = pf.project_id
                 JOIN file_contents fc ON fc.file_id = pf.id
                    AND fc.is_current = 1
                 JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
                WHERE pf.status = 'active'
                  AND pf.file_path LIKE '%.py'
                  AND cb.content_text IS NOT NULL"""
        )

        # Cache: per-project, list of (file_path, entity_id) for .py
        # files, used for import resolution.
        py_files_by_project: dict[str, list] = {}
        for r in rows:
            slug = r['slug']
            if slug not in py_files_by_project:
                py_files_by_project[slug] = []
            py_files_by_project[slug].append(r['file_path'])

        for r in rows:
            try:
                tree = ast.parse(r['content'] or '')
            except (SyntaxError, ValueError):
                skipped += 1
                continue
            file_ref = f"{r['slug']}/{r['file_path']}"
            file_id = self._entity_id('File', file_ref)
            if not file_id:
                # File entity doesn't exist yet — run git ingest first.
                # Skip rather than fail; the relation will be added on
                # next python ingest after a git ingest lands.
                continue

            # Two-pass walk. First pass collects every symbol —
            # module-level defs, class methods, and inner functions
            # too if we walked them; for now we keep to two levels:
            # module + one nesting layer inside a class (methods).
            #
            # Symbol name conventions:
            #   module-level def foo   → 'foo'
            #   class Foo              → 'Foo'
            #   method Foo.bar         → 'Foo.bar'
            #
            # Same-file call resolution then handles three cases:
            #   bare foo()             → 'foo' (module-level)
            #   self.foo() (in method) → '<enclosing class>.foo'
            #   Class.foo()            → 'Class.foo' via attribute chain
            local_defs = {}  # name → (entity_id, eref, ast_node,
                             #          enclosing_class or None)

            def _register(name, node, kind_label, enclosing=None):
                nonlocal added_e, added_r
                eref = f"{r['slug']}:{r['file_path']}:{name}"
                label = f"{kind_label} {name} (line {node.lineno})"
                if self._upsert_entity('Symbol', eref, 'python',
                                       label=label):
                    added_e += 1
                sym_id = self._entity_id('Symbol', eref)
                if sym_id and self._upsert_relation(
                    file_id, 'defines', sym_id, 'python'
                ):
                    added_r += 1
                if sym_id:
                    local_defs[name] = (sym_id, eref, node, enclosing)

            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                    _register(node.name, node, 'def')
                elif isinstance(node, ast.ClassDef):
                    _register(node.name, node, 'class')
                    # Methods: iterate the class body
                    for cnode in ast.iter_child_nodes(node):
                        if isinstance(cnode, (ast.FunctionDef,
                                              ast.AsyncFunctionDef)):
                            _register(
                                f"{node.name}.{cnode.name}",
                                cnode, 'method',
                                enclosing=node.name,
                            )

            # Second pass: for each locally-defined symbol, walk its
            # body for Call nodes and emit Symbol → calls → Symbol
            # for same-file matches. Attribute access is resolved for
            # self.foo() and Class.foo().
            for name, (sym_id, eref, def_node, enclosing) in \
                    local_defs.items():
                for sub in ast.walk(def_node):
                    if not isinstance(sub, ast.Call):
                        continue
                    called = None
                    if isinstance(sub.func, ast.Name):
                        called = sub.func.id
                    elif isinstance(sub.func, ast.Attribute):
                        # Handle: self.foo, Class.foo, module.foo, etc.
                        func = sub.func
                        if isinstance(func.value, ast.Name):
                            root = func.value.id
                            attr = func.attr
                            if root == 'self' and enclosing:
                                # self.foo → <enclosing>.foo
                                called = f"{enclosing}.{attr}"
                            elif root in local_defs:
                                # Class.method or foo.attr where foo is
                                # a local def (rare but honest)
                                called = f"{root}.{attr}"
                        # Deeper chains (a.b.c.foo) deferred.
                    if called and called in local_defs and called != name:
                        target_sym_id = local_defs[called][0]
                        if self._upsert_relation(
                            sym_id, 'calls', target_sym_id, 'python'
                        ):
                            added_r += 1

            # Third pass: extract imports at module level and emit
            # File → imports → File relations. Resolves the imported
            # module name against other .py files in the same project
            # via suffix match (foo.bar → foo/bar.py or
            # foo/bar/__init__.py). Skips imports that don't resolve
            # (stdlib, third-party, unresolved). Same-project only —
            # cross-project imports are rare and would need registry.
            project_pyfiles = py_files_by_project.get(r['slug'], [])
            for node in ast.iter_child_nodes(tree):
                targets = []
                if isinstance(node, ast.Import):
                    # `import foo.bar` — foo.bar is the module
                    for alias in node.names:
                        targets.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    # `from foo.bar import baz` — foo.bar is the
                    # module; baz might be a submodule or a symbol.
                    # Try module = foo.bar; skip level>0 (relative).
                    if node.level == 0 and node.module:
                        targets.append(node.module)
                for mod in targets:
                    parts = mod.split('.')
                    # Candidate file paths: foo/bar.py, foo/bar/__init__.py
                    cand_a = '/'.join(parts) + '.py'
                    cand_b = '/'.join(parts) + '/__init__.py'
                    match_path = None
                    for pf in project_pyfiles:
                        if pf.endswith(cand_a) or pf.endswith(cand_b):
                            match_path = pf
                            break
                    if not match_path:
                        continue
                    target_file_ref = f"{r['slug']}/{match_path}"
                    target_file_id = self._entity_id(
                        'File', target_file_ref
                    )
                    if target_file_id and target_file_id != file_id:
                        if self._upsert_relation(
                            file_id, 'imports',
                            target_file_id, 'python'
                        ):
                            added_r += 1

        print(f"✓ ingest python: +{added_e} symbols, +{added_r} relations, "
              f"{skipped} unparseable")
        self._last_counts = {'e': added_e, 'r': added_r, 'x': skipped}
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

        # Q4 dual-write: backfill Commit.attributes_json from the two
        # sidecar tables vcs_commit_parents and vcs_commit_metadata.
        # Both are still the write-of-record; this is stage 1 of the
        # expand/read-migrate/contract pattern proposed in the parallel-
        # session Q4 answer. New consumers can read attributes_json
        # instead of joining sidecar tables.
        import json
        sidecar_data = {}
        parents = query_all(
            """SELECT cp.commit_id,
                      parent.commit_hash AS parent_hash,
                      cp.parent_order
                 FROM vcs_commit_parents cp
                 JOIN vcs_commits parent
                   ON parent.id = cp.parent_commit_id
                ORDER BY cp.commit_id, cp.parent_order"""
        )
        for p in parents:
            sd = sidecar_data.setdefault(p['commit_id'], {})
            sd.setdefault('parents', []).append(p['parent_hash'])

        metadata = query_all(
            """SELECT commit_id, intent, change_type, scope,
                      is_breaking, breaking_change_description
                 FROM vcs_commit_metadata"""
        )
        for m in metadata:
            sd = sidecar_data.setdefault(m['commit_id'], {})
            meta = {}
            if m['intent']:      meta['intent'] = m['intent']
            if m['change_type']: meta['change_type'] = m['change_type']
            if m['scope']:       meta['scope'] = m['scope']
            if m['is_breaking']:
                meta['is_breaking'] = bool(m['is_breaking'])
                if m['breaking_change_description']:
                    meta['breaking_change_description'] = \
                        m['breaking_change_description']
            if meta:
                sd['metadata'] = meta

        if sidecar_data:
            # We keep a commit_id → external_ref map for the update pass
            commit_id_to_ref = {
                c['id']: f"{c['slug']}/{c['commit_hash']}" for c in commits
            }
            from db_utils import execute
            for cid, attrs in sidecar_data.items():
                ref = commit_id_to_ref.get(cid)
                if not ref:
                    continue
                # Only update if it changes anything — the archive
                # trigger doesn't fire on attributes_json changes
                # (trigger watches label/source_authority only),
                # so unconditional updates would be silent.
                execute(
                    """UPDATE entities
                          SET attributes_json = ?
                        WHERE kind = 'Commit' AND external_ref = ?""",
                    (json.dumps(attrs, sort_keys=True), ref),
                )

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

        # NOT YET: AstBuild → built-from → Commit
        #
        # I tried bridging via nix_generations
        # (Generation.toplevel_path == AstBuild.output_path,
        # then use Generation.commit_hash) but the data doesn't
        # support it: ast_builds.output_path is the local emit
        # directory (~/.config/templedb/ast-builds/<host>/<hash>),
        # not the nix-store system closure. Different concept.
        #
        # To wire this properly requires either:
        #   (a) adding a commit_hash column to ast_builds and
        #       populating at emit time in ast_build_service, OR
        #   (b) storing commit_hash inside manifest_json and joining
        #       through that.
        #
        # Deferred to a follow-up. The path exists via 3 hops
        # (AstBuild → produces → StorePath ← installs ← Generation
        # → built-from → Commit) so nothing is unreachable.

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

    def graph_observations_gc(self, args) -> int:
        """Delete observations_archive rows older than the cutoff.

        Per-kind retention (Symbol 90d, ToolCall 90d, Commit forever)
        deferred to a follow-up when we have data on how the archive
        actually grows. For now: one global cutoff.

        Suggested defaults:
          - Manual sweep: --older-than-days 90 (matches the schema
            report's ToolCall retention proposal).
          - Regular sweep (systemd): --older-than-days 90 daily.

        Kinds to keep forever per the schema report:
          Commit, Deployment, Report, Decision, Machine, Session.
        For now we don't preserve those — the archive holds
        *observations* (changes), not the current state. Commit
        entities themselves live in entities table which never
        gets touched by this GC."""
        from db_utils import execute, query_one
        cutoff_days = int(args.older_than_days)
        pre = query_one(
            "SELECT COUNT(*) AS n FROM observations_archive"
        )['n']
        if args.dry_run:
            row = query_one(
                """SELECT COUNT(*) AS n FROM observations_archive
                    WHERE observed_at < datetime('now', ?)""",
                (f"-{cutoff_days} days",),
            )
            print(f"Would delete {row['n']} rows "
                  f"(of {pre} total) older than {cutoff_days} days")
            return 0
        execute(
            """DELETE FROM observations_archive
                WHERE observed_at < datetime('now', ?)""",
            (f"-{cutoff_days} days",),
        )
        post = query_one(
            "SELECT COUNT(*) AS n FROM observations_archive"
        )['n']
        deleted = pre - post
        print(f"✓ Deleted {deleted} rows from observations_archive "
              f"(pre {pre} → post {post})")
        return 0

    def graph_observations(self, args) -> int:
        """Show observations_archive history for one entity.

        Every time an entity's label or source_authority changed,
        the archive captured the pre-update state. This surface
        answers 'when did the label change' and 'was this entity
        ever attributed to a different authority?'
        """
        from db_utils import query_all
        kind, sep, ref = args.entity.partition('/')
        if not sep:
            logger.error(
                "Expected `<kind>/<ref>` "
                "(e.g. `Machine/zMothership2`)"
            )
            return 1
        rows = query_all(
            """SELECT id, observed_at,
                      label, prior_label,
                      source_authority, prior_source_authority
                 FROM observations_archive
                WHERE entity_kind = ? AND entity_ref = ?
                ORDER BY observed_at DESC
                LIMIT ?""",
            (kind, ref, int(args.limit)),
        )
        if not rows:
            print(f"(no archived observations for {kind}/{ref})")
            print("  This means the entity hasn't been mutated since "
                  "migration 097 landed, or doesn't exist.")
            return 0
        print(f"Observation history for {kind}/{ref}:")
        for r in rows:
            label_change = ""
            if r['prior_label'] != r['label']:
                label_change = f" label: {r['prior_label']!r} → {r['label']!r}"
            auth_change = ""
            if r['prior_source_authority'] != r['source_authority']:
                auth_change = (f" authority: "
                               f"{r['prior_source_authority']!r} → "
                               f"{r['source_authority']!r}")
            print(f"  #{r['id']:<5} {r['observed_at']}"
                  f"{label_change}{auth_change}")
        return 0

    def graph_search(self, args) -> int:
        """Case-insensitive substring search across entity
        label + external_ref.

        Examples:
          templedb entity search 'auth cookie'   # find commits about auth
          templedb entity search zMothership --kind Machine
        """
        from db_utils import query_all
        clauses = ["(LOWER(label) LIKE ? OR LOWER(external_ref) LIKE ?)"]
        pattern = f"%{args.query.lower()}%"
        params = [pattern, pattern]
        if args.kind:
            clauses.append("kind = ?")
            params.append(args.kind)
        where = " AND ".join(clauses)
        rows = query_all(
            f"""SELECT kind, external_ref, label, source_authority,
                       observed_at
                  FROM entities
                 WHERE {where}
                 ORDER BY observed_at DESC
                 LIMIT ?""",
            tuple(params) + (int(args.limit),),
        )
        if not rows:
            print(f"(no entities match {args.query!r}"
                  f"{f' in kind={args.kind}' if args.kind else ''})")
            return 0
        for r in rows:
            label = f" — {r['label']}" if r['label'] else ""
            print(f"  {r['kind']:<14} {r['external_ref']:<50} "
                  f"{r['source_authority']:<12}{label}")
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
            ('every_tool_call_has_entity',
             self._check_tool_calls_have_entities),
            ('every_generation_with_commit_has_relation',
             self._check_generations_have_built_from),
            ('every_deployment_has_entity',
             self._check_deployments_have_entities),
            ('fleet_machines_reconciled_within_7_days',
             self._check_reconcile_freshness),
            ('entity_counts_match_source_tables',
             self._check_entity_counts_match_sources),
            ('every_entity_has_sync_scope',
             self._check_entities_have_sync_scope),
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

    def _check_entities_have_sync_scope(self):
        """Invariant: every entity has a non-NULL sync_scope. New
        rows get the default from _SYNC_SCOPES on insert; old rows
        (pre-mig-099) may have NULL until re-ingested. This check
        surfaces backfill status."""
        from db_utils import query_all
        rows = query_all(
            """SELECT kind, COUNT(*) AS n
                 FROM entities
                WHERE sync_scope IS NULL
                GROUP BY kind
                ORDER BY n DESC
                LIMIT 20"""
        )
        return [f"{r['kind']}: {r['n']} entities with NULL sync_scope — "
                f"re-run `templedb ingest all` or bulk-backfill"
                for r in rows]

    def _check_entity_counts_match_sources(self):
        """Invariant: for every dual-write pair, the entity count
        equals the source table's active row count.

        This is the doctor-shape answer to Q1's dual-write concern
        (parallel-session report 2026-09-03-1947-*.html). If a
        write to the source table silently drops the projection to
        entities — or vice versa — the counts diverge and this
        check surfaces it.

        Not enforcing exact equality: entities are lazily upserted
        via ingest, so a source-row landing between ingest runs
        will legitimately show a delta. We tolerate ±5 rows before
        flagging. Bigger deltas are actionable drift."""
        from db_utils import query_one
        pairs = [
            ('Commit', "SELECT COUNT(*) FROM vcs_commits", None),
            ('EditIntent',
             "SELECT COUNT(*) FROM edit_intents", None),
            ('AgentSession',
             "SELECT COUNT(*) FROM agent_sessions", None),
            ('ToolCall',
             "SELECT COUNT(*) FROM tool_calls", None),
            ('Deployment',
             "SELECT COUNT(*) FROM deployment_history", None),
            # For File, we count only project_files whose project
            # still exists — orphan rows (project deleted, file rows
            # leaked) legitimately have no entity emission because
            # git ingest INNER JOINs projects.
            ('File',
             """SELECT COUNT(*)
                  FROM project_files pf
                  JOIN projects p ON p.id = pf.project_id
                 WHERE pf.status = 'active'""", None),
            ('AstBuild',
             "SELECT COUNT(*) FROM ast_builds", None),
        ]
        issues = []
        for kind, src_sql, _extra in pairs:
            src_row = query_one(src_sql)
            src_n = list(src_row.values())[0] if src_row else 0
            ent_row = query_one(
                "SELECT COUNT(*) AS n FROM entities WHERE kind = ?",
                (kind,),
            )
            ent_n = ent_row['n'] if ent_row else 0
            delta = abs(ent_n - src_n)
            if delta > 5:
                issues.append(
                    f"{kind}: {ent_n} entities vs {src_n} source rows "
                    f"(delta {delta}) — run `templedb ingest all`"
                )
        return issues

    def _check_reconcile_freshness(self):
        """Invariant: every fleet_machine should have been reconciled
        within the last 7 days. Otherwise drift is undetectable —
        we can't know if the machine has diverged from the DB.

        Warns for machines never probed too."""
        from db_utils import query_all
        rows = query_all(
            """SELECT fm.machine_name,
                      MAX(rr.ran_at) AS last_run
                 FROM fleet_machines fm
                 LEFT JOIN reconcile_runs rr
                   ON rr.machine_name = fm.machine_name
                GROUP BY fm.machine_name
                HAVING last_run IS NULL
                    OR datetime(last_run) < datetime('now', '-7 days')"""
        )
        return [f"Machine {r['machine_name']} last reconciled at "
                f"{r['last_run'] or '(never)'} — "
                f"run `templedb reconcile machine {r['machine_name']}`"
                for r in rows]

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
        inserted, False on update. Refreshes observed_at either way.

        Sets sync_scope on insert per _SYNC_SCOPES table (Q5). Does
        NOT overwrite existing scope on update — allows manual
        overrides via SQL to survive re-ingest."""
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
        scope = self._SYNC_SCOPES.get(kind, 'fleet')
        execute(
            """INSERT INTO entities
                   (kind, external_ref, source_authority, label,
                    sync_scope)
                 VALUES (?, ?, ?, ?, ?)""",
            (kind, external_ref, authority, label, scope),
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
                 'python', 'all', 'history', 'schedule'],
        help="Which ingestion adapter to run, or 'history'/'schedule' "
             "for meta-commands",
    )
    ingest_parser.add_argument(
        '--limit', default=20,
        help='For history: max rows (default 20)',
    )
    # Schedule action + interval — only meaningful when source='schedule'.
    ingest_parser.add_argument(
        'action', nargs='?',
        choices=['install', 'uninstall', 'status'],
        help="For schedule: install / uninstall / status",
    )
    ingest_parser.add_argument(
        '--interval',
        help="For schedule install: systemd OnCalendar spec "
             "(default: 'hourly')",
    )

    def _ingest_dispatch(args):
        if args.source == 'history':
            return cmd.ingest_history(args)
        if args.source == 'schedule':
            if not args.action:
                logger.error("ingest schedule needs an action: "
                             "install | uninstall | status")
                return 1
            return cmd.ingest_schedule(args)
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

    obs = esub.add_parser(
        'observations',
        help='Archive history for one entity — when did label / '
             'source_authority change (migration 097)',
    )
    obs.add_argument('entity', help='<kind>/<external_ref>')
    obs.add_argument('--limit', default=50,
                     help='Max rows (default 50)')
    cli.commands['entity.observations'] = cmd.graph_observations

    obs_gc = esub.add_parser(
        'observations-gc',
        help='Delete observations_archive rows older than a cutoff '
             '(retention policy per Q2 answer)',
    )
    obs_gc.add_argument('--older-than-days', default=90,
                        help='Delete rows older than N days (default 90)')
    obs_gc.add_argument('--dry-run', action='store_true',
                        help='Show what would be deleted without acting')
    cli.commands['entity.observations-gc'] = cmd.graph_observations_gc

    search = esub.add_parser(
        'search',
        help='Case-insensitive substring search across '
             'entity label + external_ref',
        description="Search across every entity's label and external_ref. "
                    "See `templedb entity stats` for the current kind list.",
    )
    search.add_argument('query', help='Substring to look for')
    search.add_argument(
        '--kind',
        help='Restrict to one entity kind. Common kinds: File, Commit, '
             'Machine, Generation, Deployment, EditIntent, Report, '
             'AgentSession, ToolCall, StorePath, Derivation, AstBuild. '
             'Full list: `templedb entity stats`.',
    )
    search.add_argument('--limit', default=30,
                        help='Max rows (default 30)')
    cli.commands['entity.search'] = cmd.graph_search

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
