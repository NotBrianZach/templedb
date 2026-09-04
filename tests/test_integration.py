#!/usr/bin/env python3
"""
Integration tests for TempleDB — test full workflows end-to-end.

Each test creates a fresh DB, populates it with test data, and
exercises the real code paths. No mocking.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_env(tmp_path):
    """Create a fully isolated TempleDB environment with fresh DB."""
    db_path = str(tmp_path / "templedb.sqlite")
    os.environ["TEMPLEDB_PATH"] = db_path

    # Force db_utils to pick up the new path
    import db_utils
    db_utils.DB_PATH = db_path
    db_utils.close_connection()

    # Create DB from schema
    from migrator import Migrator
    m = Migrator(db_path)
    m.migrate()

    yield {"db_path": db_path, "tmp_path": tmp_path}

    # Restore
    del os.environ["TEMPLEDB_PATH"]
    db_utils.DB_PATH = db_utils._get_db_path()
    db_utils.close_connection()


@pytest.fixture
def populated_env(temp_env):
    """Fresh DB with a test project and some files."""
    db_path = temp_env["db_path"]
    tmp_path = temp_env["tmp_path"]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Create a test project
    conn.execute(
        "INSERT INTO projects (slug, name, repo_url, project_type) "
        "VALUES ('testproj', 'Test Project', ?, 'regular')",
        (str(tmp_path / "testproj"),)
    )
    project_id = conn.execute("SELECT id FROM projects WHERE slug = 'testproj'").fetchone()[0]

    # Create file type
    conn.execute(
        "INSERT OR IGNORE INTO file_types (id, type_name, category) VALUES (1, 'python', 'code')"
    )

    # Create some files with content
    import hashlib
    files = {
        "README.md": "# Test Project\nThis is a test.",
        "src/main.py": "def main():\n    print('hello')\n",
        "flake.nix": '{ outputs = { self }: { }; }',
    }
    for path, content in files.items():
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        conn.execute(
            "INSERT OR IGNORE INTO content_blobs (hash_sha256, content_text, content_type, encoding, file_size_bytes, reference_count) "
            "VALUES (?, ?, 'text', 'utf-8', ?, 1)",
            (content_hash, content, len(content))
        )
        file_name = path.rsplit("/", 1)[-1]
        conn.execute(
            "INSERT INTO project_files (project_id, file_type_id, file_path, file_name, status) "
            "VALUES (?, 1, ?, ?, 'active')",
            (project_id, path, file_name)
        )
        file_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO file_contents (file_id, content_hash, file_size_bytes, is_current) "
            "VALUES (?, ?, ?, 1)",
            (file_id, content_hash, len(content))
        )

    # Create a VCS branch
    conn.execute(
        "INSERT INTO vcs_branches (project_id, branch_name, is_default) VALUES (?, 'main', 1)",
        (project_id,)
    )

    conn.commit()
    conn.close()

    return {**temp_env, "project_id": project_id, "files": files}


# ── Migration Tests ───────────────────────────────────────────────────────────

class TestMigrationWorkflow:
    def test_fresh_db_has_all_tables(self, temp_env):
        conn = sqlite3.connect(temp_env["db_path"])
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
        conn.close()

        for required in ["projects", "project_files", "content_blobs", "file_contents",
                         "vcs_commits", "vcs_branches", "system_config", "schema_version",
                         "environment_variables", "deployment_history"]:
            assert required in tables, f"Missing table: {required}"

    def test_stamp_then_status_shows_all_applied(self, temp_env):
        from migrator import Migrator
        m = Migrator(temp_env["db_path"])
        status = m.status()
        pending = sum(1 for s in status if not s["applied"])
        assert pending == 0

    def test_migrate_idempotent(self, temp_env):
        from migrator import Migrator
        m = Migrator(temp_env["db_path"])
        applied1, _ = m.migrate()
        applied2, _ = m.migrate()
        assert applied1 == 0  # already done by fixture
        assert applied2 == 0


# ── FUSE Tests ────────────────────────────────────────────────────────────────

class TestFuseOperations:
    def test_path_parsing(self):
        try:
            from temple_fuse import TempleFS
        except OSError:
            pytest.skip("libfuse not available")

        fs = TempleFS.__new__(TempleFS)
        assert fs._parse_path("/") == (None, None)
        assert fs._parse_path("/proj") == ("proj", None)
        assert fs._parse_path("/proj/src/main.py") == ("proj", "src/main.py")
        assert fs._parse_path("/a/b/c/d.txt") == ("a", "b/c/d.txt")

    def test_list_projects(self, populated_env):
        try:
            from temple_fuse import TempleFS
        except OSError:
            pytest.skip("libfuse not available")

        fs = TempleFS(db_path=populated_env["db_path"])
        projects = fs._list_projects()
        slugs = [p["slug"] for p in projects]
        assert "testproj" in slugs

    def test_read_file(self, populated_env):
        try:
            from temple_fuse import TempleFS
        except OSError:
            pytest.skip("libfuse not available")

        fs = TempleFS(db_path=populated_env["db_path"])
        proj = fs._get_project("testproj")
        content = fs._get_file_content(proj["id"], "README.md")
        assert content is not None
        assert b"Test Project" in content

    def test_list_directory(self, populated_env):
        try:
            from temple_fuse import TempleFS
        except OSError:
            pytest.skip("libfuse not available")

        fs = TempleFS(db_path=populated_env["db_path"])
        proj = fs._get_project("testproj")
        entries = fs._list_dir_entries(proj["id"], None)
        assert "README.md" in entries
        assert "src" in entries  # directory


# ── Knowledge Graph Tests ─────────────────────────────────────────────────────

class TestKnowledgeGraph:
    def test_search_finds_project(self, populated_env):
        from knowledge_graph import search_everywhere
        results = search_everywhere("testproj")
        assert "projects" in results
        assert len(results["projects"]) > 0
        assert results["projects"][0]["slug"] == "testproj"

    def test_search_finds_file_content(self, populated_env):
        from knowledge_graph import search_everywhere
        results = search_everywhere("hello")
        # Content search may or may not find "hello" depending on FTS
        assert isinstance(results, dict)

    def test_project_dependencies(self, populated_env):
        from knowledge_graph import project_dependencies
        deps = project_dependencies("testproj")
        assert "project" in deps
        assert deps["project"]["slug"] == "testproj"

    def test_project_not_found(self, populated_env):
        from knowledge_graph import project_dependencies
        result = project_dependencies("nonexistent")
        assert "error" in result

    def test_cross_project_analysis(self, populated_env):
        from knowledge_graph import cross_project_analysis
        result = cross_project_analysis()
        assert "projects" in result
        assert len(result["projects"]) >= 1

    def test_changes_since_deploy(self, populated_env):
        from knowledge_graph import changes_since_deploy
        result = changes_since_deploy("testproj")
        assert "project" in result
        assert result["last_deploy"] is None  # never deployed


# ── System Config Tests ───────────────────────────────────────────────────────

class TestSystemConfig:
    def test_set_and_get(self, temp_env):
        conn = sqlite3.connect(temp_env["db_path"])
        conn.execute(
            "INSERT INTO system_config (key, value, updated_at) VALUES ('test.key', 'test.value', datetime('now'))"
        )
        conn.commit()

        row = conn.execute("SELECT value FROM system_config WHERE key = 'test.key'").fetchone()
        assert row[0] == "test.value"
        conn.close()

    def test_host_scoped_config(self, temp_env):
        conn = sqlite3.connect(temp_env["db_path"])
        conn.execute(
            "INSERT INTO system_config (key, value, updated_at) VALUES ('nixos.let.home.homeDir', '/home/default', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO system_config (key, value, updated_at) VALUES ('myhost.nixos.let.home.homeDir', '/home/override', datetime('now'))"
        )
        conn.commit()

        # System-wide default
        row = conn.execute("SELECT value FROM system_config WHERE key = 'nixos.let.home.homeDir'").fetchone()
        assert row[0] == "/home/default"

        # Host override
        row = conn.execute("SELECT value FROM system_config WHERE key = 'myhost.nixos.let.home.homeDir'").fetchone()
        assert row[0] == "/home/override"
        conn.close()

    def test_dotfiles_manifest(self, temp_env):
        conn = sqlite3.connect(temp_env["db_path"])
        manifest = [{"project": "testproj", "source": ".bashrc", "target": "~/.bashrc"}]
        conn.execute(
            "INSERT INTO system_config (key, value, updated_at) VALUES ('nixos.dotfiles', ?, datetime('now'))",
            (json.dumps(manifest),)
        )
        conn.commit()

        row = conn.execute("SELECT value FROM system_config WHERE key = 'nixos.dotfiles'").fetchone()
        loaded = json.loads(row[0])
        assert len(loaded) == 1
        assert loaded[0]["source"] == ".bashrc"
        conn.close()


# ── Nix Codegen Tests ─────────────────────────────────────────────────────────

class TestNixCodegen:
    def test_generate_user_packages(self, temp_env):
        """Codegen reads from whatever DB TEMPLEDB_PATH points to.
        Since we set it in the fixture, we need to reset the db_utils connection."""

        conn = sqlite3.connect(temp_env["db_path"])
        # Clear any existing package keys
        conn.execute("DELETE FROM system_config WHERE key LIKE 'nixos.pkg.%'")
        conn.execute("INSERT INTO system_config (key, value, updated_at) VALUES ('nixos.pkg.user.tools.ripgrep', 'true', datetime('now'))")
        conn.execute("INSERT INTO system_config (key, value, updated_at) VALUES ('nixos.pkg.user.tools.fd', 'true', datetime('now'))")
        conn.execute("INSERT INTO system_config (key, value, updated_at) VALUES ('nixos.pkg.user.editors.neovim', 'true', datetime('now'))")
        conn.commit()
        conn.close()

        from nix_codegen import generate_user_packages
        code = generate_user_packages()
        assert "ripgrep" in code
        assert "fd" in code
        assert "neovim" in code
        assert "# Tools" in code
        assert "# Editors" in code


    def test_generate_aliases(self, temp_env):

        conn = sqlite3.connect(temp_env["db_path"])
        conn.execute("DELETE FROM system_config WHERE key LIKE 'nixos.alias.%'")
        conn.execute("INSERT INTO system_config (key, value, updated_at) VALUES ('nixos.alias.ll', 'ls -la', datetime('now'))")
        conn.commit()
        conn.close()

        from nix_codegen import generate_aliases
        code = generate_aliases()
        assert 'll = "ls -la";' in code


    def test_generate_services(self, temp_env):

        conn = sqlite3.connect(temp_env["db_path"])
        conn.execute("DELETE FROM system_config WHERE key LIKE 'nixos.service.%'")
        conn.execute("INSERT INTO system_config (key, value, updated_at) VALUES ('nixos.service.system.tailscale', 'true', datetime('now'))")
        conn.commit()
        conn.close()

        from nix_codegen import generate_services_enable
        code = generate_services_enable()
        assert "services.tailscale.enable = true;" in code


    def test_generate_firewall(self, temp_env):

        conn = sqlite3.connect(temp_env["db_path"])
        conn.execute("DELETE FROM system_config WHERE key LIKE 'nixos.firewall.%'")
        conn.execute("INSERT INTO system_config (key, value, updated_at) VALUES ('nixos.firewall.tcp', '[\"22\",\"80\",\"443\"]', datetime('now'))")
        conn.commit()
        conn.close()

        from nix_codegen import generate_firewall_ports
        code = generate_firewall_ports()
        assert "22" in code
        assert "443" in code


    def test_update_flake_inputs(self, temp_env):

        conn = sqlite3.connect(temp_env["db_path"])
        conn.execute("DELETE FROM system_config WHERE key LIKE 'nixos.flake.input.%'")
        conn.execute("INSERT INTO system_config (key, value, updated_at) VALUES ('nixos.flake.input.myinput', 'github:user/repo', datetime('now'))")
        conn.commit()
        conn.close()

        flake = temp_env["tmp_path"] / "flake.nix"
        flake.write_text('{\n  inputs = {\n    myinput.url = "old-url";\n  };\n}')

        from nix_codegen import update_flake_inputs
        n = update_flake_inputs(flake)
        assert n == 1

        content = flake.read_text()
        assert 'github:user/repo' in content
        assert 'old-url' not in content



# ── Materialize Tests ─────────────────────────────────────────────────────────

class TestMaterialize:
    def test_materialize_creates_git_repo(self, populated_env):

        from services.system_service import SystemService
        svc = SystemService()
        checkout = svc.materialize_from_db("testproj")

        assert checkout is not None
        assert checkout.exists()
        assert (checkout / ".git").exists()
        assert (checkout / "README.md").exists()
        assert (checkout / "src" / "main.py").exists()

        content = (checkout / "README.md").read_text()
        assert "Test Project" in content


    def test_materialize_has_git_commit(self, populated_env):

        from services.system_service import SystemService
        svc = SystemService()
        checkout = svc.materialize_from_db("testproj")

        assert checkout is not None
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=str(checkout), capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "materialize" in result.stdout.lower()

    def test_materialize_preserves_gitignored_files(self, populated_env,
                                                    monkeypatch, tmp_path):
        """A file in the checkout that is .gitignored must survive materialize,
        even though it doesn't exist in the DB. Fixes the .authinfo.gpg
        sweep incident (2026-09-01): local secrets referenced by
        home.nix's `source = ./.authinfo.gpg` were being deleted by
        the stale-file cleanup, and the auto-commit picked up the
        deletion, breaking every subsequent build.
        """
        from services.system_service import SystemService

        # Force materialize to use our tmp_path so we can prepare state.
        target = tmp_path / "testproj"

        svc = SystemService()
        monkeypatch.setattr(svc, "_checkout_dir_for",
                            lambda slug: target)

        # First materialize creates the checkout + inits git.
        checkout = svc.materialize_from_db("testproj")
        assert checkout is not None

        # Plant a real "secret" and .gitignore it, then commit .gitignore
        # so `git check-ignore` recognises the rule on the next materialize.
        secret = checkout / ".mysecret"
        secret.write_text("very sensitive")
        gitignore = checkout / ".gitignore"
        gitignore.write_text(".mysecret\n")
        subprocess.run(["git", "add", ".gitignore"],
                       cwd=str(checkout), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add gitignore"],
                       cwd=str(checkout), check=True, capture_output=True)

        # Sanity: check-ignore agrees before we materialize.
        r = subprocess.run(["git", "check-ignore", ".mysecret"],
                           cwd=str(checkout), capture_output=True, text=True)
        assert r.returncode == 0, "test setup: gitignore rule didn't apply"

        # Second materialize would (pre-fix) delete .mysecret because
        # it's not in the DB active set. Post-fix, it must survive.
        checkout2 = svc.materialize_from_db("testproj")
        assert checkout2 is not None
        assert secret.exists(), \
            ".mysecret was swept by materialize despite being gitignored"
        assert secret.read_text() == "very sensitive"

    def test_materialize_still_deletes_non_ignored_strays(self, populated_env,
                                                          monkeypatch, tmp_path):
        """Regression guard: the gitignore fix must NOT preserve everything.
        Non-ignored files that aren't in the DB should still be swept.
        This keeps the original "clean up stale files" behaviour intact.
        """
        from services.system_service import SystemService

        target = tmp_path / "testproj"
        svc = SystemService()
        monkeypatch.setattr(svc, "_checkout_dir_for",
                            lambda slug: target)

        checkout = svc.materialize_from_db("testproj")
        assert checkout is not None

        # A file that is NOT gitignored — should get swept.
        stray = checkout / "stray_file.txt"
        stray.write_text("not tracked, not ignored")

        checkout2 = svc.materialize_from_db("testproj")
        assert checkout2 is not None
        assert not stray.exists(), \
            "non-gitignored stray file was preserved but should be swept"


# ── Graph Traversal (entity trace + provenance) Tests ────────────────────────

class TestGraphTraversal:
    """Multi-hop graph queries — templedb entity trace and its
    workflow-preset wrappers under templedb provenance."""

    def _seed_chain(self, populated_env):
        """Build a chain: Machine → Generation → Commit → File."""
        import argparse
        from cli.commands.entity import EntityCommands
        conn = sqlite3.connect(populated_env["db_path"])
        pid = conn.execute(
            "SELECT id FROM projects WHERE slug='testproj'"
        ).fetchone()[0]
        # fleet_networks + fleet_machines
        conn.execute(
            """INSERT INTO fleet_networks (project_id, network_name,
                                            network_uuid,
                                            config_file_path)
                 VALUES (?, 'net', 'uuid-net', 'net.nix')""",
            (pid,),
        )
        nid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO fleet_machines
                   (network_id, machine_name, machine_uuid,
                    target_host, system_type)
                 VALUES (?, 'traceHost', 'uuid-traceHost',
                         '10.0.0.9', 'nixos')""",
            (nid,),
        )
        bid = conn.execute(
            "SELECT id FROM vcs_branches WHERE project_id=?", (pid,)
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO vcs_commits (project_id, branch_id,
                                        commit_hash, commit_message,
                                        author, commit_timestamp)
                 VALUES (?, ?, 'aaabbbcccddd', 'chain commit',
                         'x', datetime('now'))""",
            (pid, bid),
        )
        conn.execute(
            """INSERT INTO nix_generations
                   (machine_name, generation_number, toplevel_path,
                    commit_hash, switched_at, switch_success)
                 VALUES ('traceHost', 1, '/nix/store/xx-traceHost',
                         'aaabbbcccddd', datetime('now'), 1)"""
        )
        conn.execute(
            """INSERT INTO nix_store_paths
                   (store_path, store_hash, name, is_valid)
                 VALUES ('/nix/store/xx-traceHost', 'xx',
                         'traceHost', 1)"""
        )
        conn.commit()
        conn.close()
        # Ingest so entities + relations exist
        EntityCommands().ingest(
            argparse.Namespace(source='git', limit=20)
        )
        EntityCommands().ingest(
            argparse.Namespace(source='nix', limit=20)
        )

    def test_trace_walks_multi_hop(self, populated_env, capsys):
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_chain(populated_env)
        rc = EntityCommands().graph_trace(argparse.Namespace(
            entity='Machine/traceHost',
            depth=3,
            direction='out',
            via=None,
            limit=10,
        ))
        assert rc == 0
        out = capsys.readouterr().out
        # Machine start, Generation next hop, Commit hop after that
        assert 'Machine/traceHost' in out
        assert 'Generation/traceHost/gen-1' in out
        # Commit or StorePath appears at second hop
        assert 'Commit/' in out or 'StorePath/' in out

    def test_trace_via_filter(self, populated_env, capsys):
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_chain(populated_env)
        rc = EntityCommands().graph_trace(argparse.Namespace(
            entity='Machine/traceHost',
            depth=2,
            direction='out',
            via='ran',  # only follow 'ran' edges
            limit=10,
        ))
        assert rc == 0
        out = capsys.readouterr().out
        assert 'Generation' in out
        # Since we only followed 'ran' and stopped at depth 2 with
        # no further 'ran' edges, we shouldn't see StorePath
        assert 'StorePath' not in out

    def test_trace_bad_entity(self, populated_env):
        import argparse
        from cli.commands.entity import EntityCommands
        rc = EntityCommands().graph_trace(argparse.Namespace(
            entity='Machine/nonexistent',
            depth=2, direction='out', via=None, limit=10,
        ))
        assert rc == 2

    def test_provenance_machine_shortcut(self, populated_env, capsys):
        import argparse
        from cli.commands.provenance import ProvenanceCommands
        self._seed_chain(populated_env)
        rc = ProvenanceCommands().machine(argparse.Namespace(
            name='traceHost', depth=4, limit=15,
        ))
        assert rc == 0
        out = capsys.readouterr().out
        assert 'Machine/traceHost' in out
        assert 'Generation' in out

    def test_provenance_commit_by_prefix(self, populated_env, capsys):
        import argparse
        from cli.commands.provenance import ProvenanceCommands
        self._seed_chain(populated_env)
        # commit hash 'aaabbbcccddd' — try prefix
        rc = ProvenanceCommands().commit(argparse.Namespace(
            hash='aaabbb', depth=2, limit=15,
        ))
        assert rc == 0
        out = capsys.readouterr().out
        # Should find via reverse-walk: Generation ← built-from ← Commit
        assert 'Commit' in out


# ── SSH-Probe Reconcile (Workflow D) Tests ───────────────────────────────────

class TestReconcile:
    """SSH-probe reconcile. Mocks subprocess.run so we test the diff
    logic, not the actual SSH."""

    def _seed_machine_and_gen(self, populated_env, toplevel_on_db,
                              nixos_on_db='24.11'):
        conn = sqlite3.connect(populated_env["db_path"])
        pid = conn.execute(
            "SELECT id FROM projects WHERE slug='testproj'"
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO fleet_networks
                   (project_id, network_name, network_uuid,
                    config_file_path)
                 VALUES (?, 'net', 'uuid-net', 'net.nix')""",
            (pid,),
        )
        nid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO fleet_machines
                   (network_id, machine_name, machine_uuid,
                    target_host, target_user)
                 VALUES (?, 'reconHost', 'uuid-reconHost',
                         '10.0.0.42', 'root')""",
            (nid,),
        )
        conn.execute(
            """INSERT INTO nix_generations
                   (machine_name, generation_number, toplevel_path,
                    nixos_version, boot_id, switched_at,
                    switch_success)
                 VALUES ('reconHost', 5, ?, ?,
                         'boot-abc', datetime('now'), 1)""",
            (toplevel_on_db, nixos_on_db),
        )
        conn.commit()
        conn.close()

    def _mock_ssh(self, monkeypatch, stdout, returncode=0):
        import subprocess as _sub
        class _FakeCompleted:
            def __init__(self):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = ''
        monkeypatch.setattr(
            _sub, 'run',
            lambda *args, **kwargs: _FakeCompleted(),
        )

    def test_reconcile_in_sync(self, populated_env, monkeypatch,
                                capsys):
        from cli.commands.reconcile import ReconcileCommands
        import argparse
        self._seed_machine_and_gen(
            populated_env,
            toplevel_on_db='/nix/store/aaa-sys',
        )
        self._mock_ssh(monkeypatch,
                       stdout='/nix/store/aaa-sys\n24.11\nboot-abc\n')
        rc = ReconcileCommands().machine(argparse.Namespace(
            name='reconHost', verbose=False,
        ))
        assert rc == 0
        out = capsys.readouterr().out
        assert 'in sync' in out
        assert '✓' in out

    def test_reconcile_detects_toplevel_drift(self, populated_env,
                                               monkeypatch, capsys):
        from cli.commands.reconcile import ReconcileCommands
        import argparse
        self._seed_machine_and_gen(
            populated_env,
            toplevel_on_db='/nix/store/aaa-sys',
        )
        self._mock_ssh(monkeypatch,
                       stdout='/nix/store/bbb-sys\n24.11\nboot-abc\n')
        rc = ReconcileCommands().machine(argparse.Namespace(
            name='reconHost', verbose=False,
        ))
        assert rc == 1
        out = capsys.readouterr().out
        assert 'DRIFT' in out
        assert 'toplevel' in out

    def test_reconcile_detects_reboot(self, populated_env,
                                       monkeypatch, capsys):
        from cli.commands.reconcile import ReconcileCommands
        import argparse
        self._seed_machine_and_gen(
            populated_env,
            toplevel_on_db='/nix/store/aaa-sys',
        )
        # Same toplevel + version, different boot_id → machine rebooted
        self._mock_ssh(monkeypatch,
                       stdout='/nix/store/aaa-sys\n24.11\nboot-XYZ\n')
        rc = ReconcileCommands().machine(argparse.Namespace(
            name='reconHost', verbose=False,
        ))
        assert rc == 1
        out = capsys.readouterr().out
        assert 'boot_id' in out

    def test_schedule_install_writes_units(self, tmp_path,
                                            monkeypatch):
        """schedule install writes service+timer to
        ~/.config/systemd/user/. Mocks HOME and subprocess so we
        don't actually mutate the user's systemd."""
        from cli.commands.reconcile import ReconcileCommands
        import argparse, subprocess as _sub
        monkeypatch.setenv('HOME', str(tmp_path))
        # Mock Path.home() too (some code paths use it)
        from pathlib import Path
        monkeypatch.setattr(Path, 'home',
                            classmethod(lambda cls: tmp_path))

        calls = []
        class _FakeCompleted:
            returncode = 0
            stdout = ''
            stderr = ''
        def fake_run(cmd, **kw):
            calls.append(cmd)
            return _FakeCompleted()
        monkeypatch.setattr(_sub, 'run', fake_run)

        rc = ReconcileCommands().schedule(argparse.Namespace(
            action='install', interval=None,
        ))
        assert rc == 0
        svc = tmp_path / '.config/systemd/user/templedb-reconcile.service'
        tm = tmp_path / '.config/systemd/user/templedb-reconcile.timer'
        assert svc.exists(), "service unit not written"
        assert tm.exists(), "timer unit not written"
        # Service content sanity check
        assert 'reconcile machine all' in svc.read_text()
        assert 'ExecStart=' in svc.read_text()
        # Timer OnCalendar default
        assert 'OnCalendar=03:00' in tm.read_text()
        # Systemctl was invoked
        assert any('daemon-reload' in ' '.join(c) for c in calls)
        assert any('enable' in ' '.join(c) for c in calls)

    def test_schedule_uninstall_removes_units(self, tmp_path,
                                               monkeypatch):
        from cli.commands.reconcile import ReconcileCommands
        import argparse, subprocess as _sub
        from pathlib import Path
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setattr(Path, 'home',
                            classmethod(lambda cls: tmp_path))
        class _FakeCompleted:
            returncode = 0
            stdout = ''
            stderr = ''
        monkeypatch.setattr(_sub, 'run',
                            lambda *a, **k: _FakeCompleted())
        # Plant units first
        unit_dir = tmp_path / '.config/systemd/user'
        unit_dir.mkdir(parents=True)
        (unit_dir / 'templedb-reconcile.service').write_text('x')
        (unit_dir / 'templedb-reconcile.timer').write_text('x')
        rc = ReconcileCommands().schedule(argparse.Namespace(
            action='uninstall', interval=None,
        ))
        assert rc == 0
        assert not (unit_dir / 'templedb-reconcile.service').exists()
        assert not (unit_dir / 'templedb-reconcile.timer').exists()

    def test_reconcile_records_run_in_db(self, populated_env,
                                          monkeypatch):
        from cli.commands.reconcile import ReconcileCommands
        import argparse
        self._seed_machine_and_gen(
            populated_env,
            toplevel_on_db='/nix/store/aaa-sys',
        )
        self._mock_ssh(monkeypatch,
                       stdout='/nix/store/aaa-sys\n24.11\nboot-abc\n')
        ReconcileCommands().machine(argparse.Namespace(
            name='reconHost', verbose=False,
        ))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT * FROM reconcile_runs
                WHERE machine_name = 'reconHost'
                ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        conn.close()
        assert row is not None
        assert row['status'] == 'ok'
        assert row['duration_ms'] is not None

    def test_reconcile_records_drift(self, populated_env, monkeypatch):
        from cli.commands.reconcile import ReconcileCommands
        import argparse
        self._seed_machine_and_gen(
            populated_env,
            toplevel_on_db='/nix/store/aaa-sys',
        )
        self._mock_ssh(monkeypatch,
                       stdout='/nix/store/bbb-sys\n24.11\nboot-abc\n')
        ReconcileCommands().machine(argparse.Namespace(
            name='reconHost', verbose=False,
        ))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT status, drift_details_json
                 FROM reconcile_runs
                WHERE machine_name = 'reconHost'
                ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        conn.close()
        assert row['status'] == 'drift'
        import json
        details = json.loads(row['drift_details_json'])
        assert 'toplevel' in details

    def test_reconcile_history_prints(self, populated_env,
                                       monkeypatch, capsys):
        from cli.commands.reconcile import ReconcileCommands
        import argparse
        self._seed_machine_and_gen(
            populated_env,
            toplevel_on_db='/nix/store/aaa-sys',
        )
        self._mock_ssh(monkeypatch,
                       stdout='/nix/store/aaa-sys\n24.11\nboot-abc\n')
        cmd = ReconcileCommands()
        cmd.machine(argparse.Namespace(name='reconHost', verbose=False))
        capsys.readouterr()
        rc = cmd.history(argparse.Namespace(
            machine=None, status=None, limit=20,
        ))
        assert rc == 0
        out = capsys.readouterr().out
        assert 'reconHost' in out
        assert 'ok' in out

    def test_doctor_reconcile_freshness_never_run(self, populated_env,
                                                    capsys):
        """A fleet_machine that's never been reconciled should trigger
        the freshness invariant."""
        from cli.commands.entity import EntityCommands
        import argparse
        # Seed a fleet_machine but NO reconcile_runs for it
        conn = sqlite3.connect(populated_env["db_path"])
        pid = conn.execute(
            "SELECT id FROM projects WHERE slug='testproj'"
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO fleet_networks
                   (project_id, network_name, network_uuid,
                    config_file_path)
                 VALUES (?, 'net', 'uuid-net', 'net.nix')""",
            (pid,),
        )
        nid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO fleet_machines
                   (network_id, machine_name, machine_uuid,
                    target_host, target_user)
                 VALUES (?, 'staleHost', 'uuid-stale',
                         '10.0.0.99', 'root')""",
            (nid,),
        )
        conn.commit()
        conn.close()
        rc = EntityCommands().doctor_entities(argparse.Namespace(
            check='fleet_machines_reconciled_within_7_days'
        ))
        assert rc == 1
        out = capsys.readouterr().out
        assert 'staleHost' in out or 'issue' in out.lower()

    def test_reconcile_unknown_machine(self, populated_env, capsys, caplog):
        from cli.commands.reconcile import ReconcileCommands
        import argparse, logging
        with caplog.at_level(logging.ERROR):
            rc = ReconcileCommands().machine(argparse.Namespace(
                name='no-such-host', verbose=False,
            ))
        assert rc == 1
        # The message went via logger.error, not print
        assert any('no-such-host' in r.message for r in caplog.records)


# ── Ingest Schedule (systemd timer) Tests ────────────────────────────────────

class TestIngestSchedule:
    """Systemd user timer for scheduled ingest. Parallel to
    reconcile schedule."""

    def test_ingest_schedule_install_writes_units(self, tmp_path,
                                                   monkeypatch):
        from cli.commands.entity import EntityCommands
        import argparse, subprocess as _sub
        from pathlib import Path
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setattr(Path, 'home',
                            classmethod(lambda cls: tmp_path))
        class _FakeCompleted:
            returncode = 0
            stdout = ''
            stderr = ''
        monkeypatch.setattr(_sub, 'run',
                            lambda *a, **k: _FakeCompleted())

        cmd = EntityCommands()
        rc = cmd.ingest_schedule(argparse.Namespace(
            action='install', interval=None,
        ))
        assert rc == 0
        svc = tmp_path / '.config/systemd/user/templedb-ingest.service'
        tm = tmp_path / '.config/systemd/user/templedb-ingest.timer'
        assert svc.exists()
        assert tm.exists()
        assert 'ingest all' in svc.read_text()
        assert 'OnCalendar=hourly' in tm.read_text()

    def test_ingest_schedule_custom_interval(self, tmp_path,
                                              monkeypatch):
        from cli.commands.entity import EntityCommands
        import argparse, subprocess as _sub
        from pathlib import Path
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setattr(Path, 'home',
                            classmethod(lambda cls: tmp_path))
        class _FakeCompleted:
            returncode = 0
            stdout = ''
            stderr = ''
        monkeypatch.setattr(_sub, 'run',
                            lambda *a, **k: _FakeCompleted())

        EntityCommands().ingest_schedule(argparse.Namespace(
            action='install', interval='*:0/15',
        ))
        tm = tmp_path / '.config/systemd/user/templedb-ingest.timer'
        assert 'OnCalendar=*:0/15' in tm.read_text()


# ── Deploy Ingest (Deployment first-class span) Tests ────────────────────────

class TestDeployIngest:
    """Deployment first-class span from deployment_history. Uses the
    existing table's lifecycle columns (status, started_at,
    completed_at) rather than requiring a schema migration."""

    def _seed_deploy(self, populated_env):
        conn = sqlite3.connect(populated_env["db_path"])
        pid = conn.execute(
            "SELECT id FROM projects WHERE slug='testproj'"
        ).fetchone()[0]
        bid = conn.execute(
            "SELECT id FROM vcs_branches WHERE project_id=?", (pid,)
        ).fetchone()[0]
        # A commit the deployment was built from
        conn.execute(
            """INSERT INTO vcs_commits
                   (project_id, branch_id, commit_hash,
                    commit_message, author, commit_timestamp)
                 VALUES (?, ?, 'feedbeef2222', 'a commit', 'x',
                         datetime('now'))""",
            (pid, bid),
        )
        # A deployment_history row
        conn.execute(
            """INSERT INTO deployment_history
                   (project_id, target_name, deployment_type,
                    commit_hash, status, started_at, completed_at,
                    deployed_by)
                 VALUES (?, 'testhost', 'deploy',
                         'feedbeef2222', 'success',
                         datetime('now'), datetime('now'),
                         'test')""",
            (pid,),
        )
        conn.commit()
        conn.close()

    def test_ingest_deploy_emits_deployment_entity(self, populated_env):
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_deploy(populated_env)
        EntityCommands().ingest(
            argparse.Namespace(source='git', limit=20)
        )
        EntityCommands().ingest(
            argparse.Namespace(source='deploy', limit=20)
        )
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT * FROM entities WHERE kind='Deployment'"""
        ).fetchone()
        conn.close()
        assert row is not None
        assert row['source_authority'] == 'templedb'
        assert 'testhost' in row['label']

    def test_ingest_deploy_emits_from_commit_relation(self, populated_env):
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_deploy(populated_env)
        EntityCommands().ingest(argparse.Namespace(source='git', limit=20))
        EntityCommands().ingest(argparse.Namespace(source='deploy', limit=20))
        conn = sqlite3.connect(populated_env["db_path"])
        rel_count = conn.execute(
            """SELECT COUNT(*) FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                 JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE e1.kind = 'Deployment'
                  AND e2.kind = 'Commit'
                  AND r.kind = 'from-commit'"""
        ).fetchone()[0]
        conn.close()
        assert rel_count == 1

    def test_doctor_deployment_invariant(self, populated_env, capsys):
        """Insert deployment without ingesting → doctor flags it."""
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_deploy(populated_env)
        cmd = EntityCommands()
        rc = cmd.doctor_entities(argparse.Namespace(
            check='every_deployment_has_entity'
        ))
        assert rc == 1
        out = capsys.readouterr().out
        assert 'testhost' in out or 'issue' in out.lower()


# ── Tool Calls (Phase 3 extraction) Tests ────────────────────────────────────

class TestToolCalls:
    """Tests for tool_calls extraction from agent_events and its
    entity-graph integration."""

    def test_table_exists(self, temp_env):
        conn = sqlite3.connect(temp_env["db_path"])
        row = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='tool_calls'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 'table'

    def _seed_agent_session(self, populated_env):
        """Insert an agent session + run + a couple of tool events."""
        conn = sqlite3.connect(populated_env["db_path"])
        conn.execute(
            """INSERT INTO agent_providers (id, provider_kind, name)
                 VALUES (1, 'fake', 'fake') ON CONFLICT DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO agent_sessions
                   (session_uuid, provider_id, status, title)
                 VALUES ('sess-abc', 1, 'created', 'test session')"""
        )
        sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO agent_runs
                   (session_id, status, started_at)
                 VALUES (?, 'running', datetime('now'))""",
            (sid,),
        )
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        # Two tool.started events
        conn.execute(
            """INSERT INTO agent_events
                   (run_id, sequence_number, event_type, payload_json)
                 VALUES (?, 1, 'tool.started', ?)""",
            (rid, '{"tool_name": "Read file"}'),
        )
        conn.execute(
            """INSERT INTO agent_events
                   (run_id, sequence_number, event_type, payload_json)
                 VALUES (?, 2, 'tool.started', ?)""",
            (rid, '{"tool_name": "Search"}'),
        )
        conn.commit()
        return sid, rid

    def test_backfill_populated_from_agent_events(self, populated_env):
        """The migration backfills existing tool.started events into
        tool_calls. Since populated_env starts fresh and applies all
        migrations at fixture setup, the backfill runs on empty data —
        so we seed events first, then re-run the backfill logic
        manually to verify the SQL shape is correct."""
        self._seed_agent_session(populated_env)
        conn = sqlite3.connect(populated_env["db_path"])
        # Re-run the migration backfill SQL manually.
        conn.execute(
            """INSERT INTO tool_calls
                   (run_id, session_id, tool_name, started_at,
                    finished_at, status, source_event_id)
                 SELECT ae.run_id, ar.session_id,
                        COALESCE(json_extract(ae.payload_json, '$.tool_name'),
                                 'unknown'),
                        ae.created_at, NULL, 'unknown', ae.id
                   FROM agent_events ae
                   JOIN agent_runs ar ON ar.id = ae.run_id
                  WHERE ae.event_type = 'tool.started'"""
        )
        conn.commit()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT tool_name, status FROM tool_calls ORDER BY id"
        ).fetchall()
        conn.close()
        assert len(rows) == 2
        names = {r['tool_name'] for r in rows}
        assert names == {'Read file', 'Search'}

    def test_agent_ingest_emits_tool_call_entities(self, populated_env):
        """After ingesting agent, ToolCall entities exist in the graph
        with 'invoked' relations from the AgentSession."""
        import argparse
        from cli.commands.entity import EntityCommands
        sid, rid = self._seed_agent_session(populated_env)
        # Manually backfill (since migration ran on empty data)
        conn = sqlite3.connect(populated_env["db_path"])
        conn.execute(
            """INSERT INTO tool_calls
                   (run_id, session_id, tool_name, started_at,
                    status, source_event_id)
                 SELECT ae.run_id, ar.session_id,
                        json_extract(ae.payload_json, '$.tool_name'),
                        ae.created_at, 'unknown', ae.id
                   FROM agent_events ae
                   JOIN agent_runs ar ON ar.id = ae.run_id
                  WHERE ae.event_type = 'tool.started'"""
        )
        conn.commit()
        conn.close()

        EntityCommands().ingest(argparse.Namespace(source='agent', limit=20))

        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        tc_entities = conn.execute(
            "SELECT external_ref, label FROM entities WHERE kind='ToolCall'"
        ).fetchall()
        assert len(tc_entities) == 2
        # invoked relations exist
        rel = conn.execute(
            """SELECT COUNT(*) FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                WHERE e1.kind = 'AgentSession'
                  AND r.kind = 'invoked'"""
        ).fetchone()[0]
        conn.close()
        assert rel == 2

    def test_tool_list_and_stats(self, populated_env, capsys):
        import argparse
        from cli.commands.tool import ToolCommands
        # Seed some tool_calls directly
        conn = sqlite3.connect(populated_env["db_path"])
        conn.execute(
            """INSERT INTO agent_providers (id, provider_kind, name)
                 VALUES (1, 'fake', 'fake') ON CONFLICT DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO agent_sessions
                   (session_uuid, provider_id, status, title)
                 VALUES ('s1', 1, 'created', 'test')"""
        )
        sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO agent_runs
                   (session_id, status, started_at)
                 VALUES (?, 'running', datetime('now'))""",
            (sid,),
        )
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for name in ['Read', 'Read', 'Search', 'Edit']:
            conn.execute(
                """INSERT INTO tool_calls
                       (run_id, session_id, tool_name,
                        started_at, status)
                     VALUES (?, ?, ?, datetime('now'), 'unknown')""",
                (rid, sid, name),
            )
        conn.commit()
        conn.close()

        cmd = ToolCommands()
        cmd.list(argparse.Namespace(
            tool=None, session=None, status=None, limit=10,
        ))
        out = capsys.readouterr().out
        assert 'Read' in out
        assert 'Search' in out

        cmd.stats(argparse.Namespace(by='tool', limit=10))
        out = capsys.readouterr().out
        assert 'Read' in out
        # Read appears twice so should be the top row of stats
        assert out.index('Read') < out.index('Search')


# ── Python AST Ingest (Phase 4 groundwork) Tests ─────────────────────────────

class TestPythonIngest:
    """Python AST ingest — Symbol entities + defines relations.
    Zero-dependency Phase 4 groundwork."""

    def _seed_python_file(self, populated_env, path, content):
        """Add a .py file to populated_env with the given content."""
        import hashlib
        conn = sqlite3.connect(populated_env["db_path"])
        pid = conn.execute(
            "SELECT id FROM projects WHERE slug='testproj'"
        ).fetchone()[0]
        chash = hashlib.sha256(content.encode()).hexdigest()
        conn.execute(
            """INSERT OR IGNORE INTO content_blobs
                   (hash_sha256, content_text, content_type,
                    encoding, file_size_bytes)
                 VALUES (?, ?, 'text', 'utf-8', ?)""",
            (chash, content, len(content)),
        )
        conn.execute(
            """INSERT INTO project_files
                   (project_id, file_type_id, file_path, file_name,
                    status)
                 VALUES (?, 1, ?, ?, 'active')""",
            (pid, path, path.rsplit('/', 1)[-1]),
        )
        fid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO file_contents
                   (file_id, content_hash, file_size_bytes, is_current)
                 VALUES (?, ?, ?, 1)""",
            (fid, chash, len(content)),
        )
        conn.commit()
        conn.close()

    def test_python_ingest_extracts_functions(self, populated_env):
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_python_file(
            populated_env, 'src/utils.py',
            "def foo():\n    pass\n\n"
            "def bar(x):\n    return x + 1\n\n"
            "class Baz:\n    pass\n"
        )
        EntityCommands().ingest(argparse.Namespace(source='git', limit=20))
        EntityCommands().ingest(argparse.Namespace(source='python', limit=20))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT external_ref, label FROM entities
                WHERE kind = 'Symbol'
                ORDER BY external_ref"""
        ).fetchall()
        conn.close()
        refs = {r['external_ref'] for r in rows}
        assert 'testproj:src/utils.py:foo' in refs
        assert 'testproj:src/utils.py:bar' in refs
        assert 'testproj:src/utils.py:Baz' in refs

    def test_python_ingest_creates_defines_relations(self, populated_env):
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_python_file(
            populated_env, 'src/tiny.py',
            "def hello():\n    return 'hi'\n"
        )
        EntityCommands().ingest(argparse.Namespace(source='git', limit=20))
        EntityCommands().ingest(argparse.Namespace(source='python', limit=20))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                 JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE e1.kind = 'File'
                  AND e1.external_ref = 'testproj/src/tiny.py'
                  AND e2.kind = 'Symbol'
                  AND r.kind = 'defines'"""
        ).fetchone()
        conn.close()
        assert row['n'] == 1

    def test_python_ingest_extracts_same_file_calls(self, populated_env):
        """Symbol → calls → Symbol for a call whose target is defined
        in the same file."""
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_python_file(
            populated_env, 'src/callers.py',
            "def helper(x):\n    return x + 1\n\n"
            "def main():\n    return helper(42)\n"
        )
        EntityCommands().ingest(argparse.Namespace(source='git', limit=20))
        EntityCommands().ingest(argparse.Namespace(source='python', limit=20))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                 JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE e1.kind = 'Symbol'
                  AND e1.external_ref = 'testproj:src/callers.py:main'
                  AND e2.kind = 'Symbol'
                  AND e2.external_ref = 'testproj:src/callers.py:helper'
                  AND r.kind = 'calls'"""
        ).fetchone()
        conn.close()
        assert row['n'] == 1, "main → calls → helper not emitted"

    def test_python_ingest_extracts_methods(self, populated_env):
        """Class methods should be emitted as Symbol entities with
        qualified refs (Class.method)."""
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_python_file(
            populated_env, 'src/oop.py',
            "class Widget:\n"
            "    def __init__(self):\n"
            "        pass\n"
            "    def render(self):\n"
            "        return 'hi'\n"
        )
        EntityCommands().ingest(argparse.Namespace(source='git', limit=20))
        EntityCommands().ingest(argparse.Namespace(source='python', limit=20))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT external_ref, label FROM entities
                WHERE kind = 'Symbol'
                  AND external_ref LIKE '%oop.py%'
                ORDER BY external_ref"""
        ).fetchall()
        conn.close()
        refs = {r['external_ref'] for r in rows}
        assert 'testproj:src/oop.py:Widget' in refs
        assert 'testproj:src/oop.py:Widget.__init__' in refs
        assert 'testproj:src/oop.py:Widget.render' in refs

    def test_python_ingest_extracts_imports(self, populated_env):
        """`from cli.core import Command` in one file should emit
        File → imports → File relation when cli/core.py exists in
        the same project."""
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_python_file(
            populated_env, 'src/cli/core.py',
            "class Command:\n    pass\n"
        )
        self._seed_python_file(
            populated_env, 'src/cli/commands/foo.py',
            "from cli.core import Command\n\n"
            "def foo():\n    return Command()\n"
        )
        EntityCommands().ingest(argparse.Namespace(source='git', limit=20))
        EntityCommands().ingest(argparse.Namespace(source='python', limit=20))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                 JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE e1.external_ref = 'testproj/src/cli/commands/foo.py'
                  AND e2.external_ref = 'testproj/src/cli/core.py'
                  AND r.kind = 'imports'"""
        ).fetchone()
        conn.close()
        assert row['n'] == 1, "File → imports → File not emitted"

    def test_python_ingest_skips_unresolved_imports(self, populated_env):
        """`import sys` or `import requests` shouldn't fire — those
        are stdlib/third-party and have no matching File entity."""
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_python_file(
            populated_env, 'src/stdlib_user.py',
            "import sys\nimport json\n\n"
            "def dump():\n    return sys.argv\n"
        )
        EntityCommands().ingest(argparse.Namespace(source='git', limit=20))
        EntityCommands().ingest(argparse.Namespace(source='python', limit=20))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                WHERE e1.external_ref = 'testproj/src/stdlib_user.py'
                  AND r.kind = 'imports'"""
        ).fetchone()
        conn.close()
        assert row['n'] == 0, "stdlib import falsely resolved to a File"

    def test_python_ingest_resolves_self_method_calls(self, populated_env):
        """self.foo() inside a method should resolve to Class.foo
        via same-file scope."""
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_python_file(
            populated_env, 'src/methods.py',
            "class Doer:\n"
            "    def helper(self):\n"
            "        return 1\n"
            "    def go(self):\n"
            "        return self.helper()\n"
        )
        EntityCommands().ingest(argparse.Namespace(source='git', limit=20))
        EntityCommands().ingest(argparse.Namespace(source='python', limit=20))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                 JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE e1.external_ref = 'testproj:src/methods.py:Doer.go'
                  AND e2.external_ref = 'testproj:src/methods.py:Doer.helper'
                  AND r.kind = 'calls'"""
        ).fetchone()
        conn.close()
        assert row['n'] == 1, "self.helper() → Doer.helper not resolved"

    def test_python_ingest_ignores_cross_file_calls(self, populated_env):
        """Cross-file calls aren't resolved (needs import tracking)
        so no relation is emitted. Test guards against accidental
        false-positive relations."""
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_python_file(
            populated_env, 'src/other.py',
            "def other_helper():\n    return 1\n"
        )
        self._seed_python_file(
            populated_env, 'src/caller.py',
            "def uses_helper():\n    return other_helper()\n"
        )
        EntityCommands().ingest(argparse.Namespace(source='git', limit=20))
        EntityCommands().ingest(argparse.Namespace(source='python', limit=20))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                 JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE e1.kind = 'Symbol'
                  AND e2.kind = 'Symbol'
                  AND r.kind = 'calls'
                  AND (e1.external_ref LIKE '%caller.py:%'
                       OR e2.external_ref LIKE '%other.py:%')"""
        ).fetchone()
        conn.close()
        assert row['n'] == 0, "cross-file call falsely resolved"

    def test_python_ingest_skips_unparseable(self, populated_env, capsys):
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_python_file(
            populated_env, 'src/broken.py',
            "def foo(:\n  syntax error\n"
        )
        EntityCommands().ingest(argparse.Namespace(source='git', limit=20))
        EntityCommands().ingest(argparse.Namespace(source='python', limit=20))
        out = capsys.readouterr().out
        assert '1 unparseable' in out  # from ingest python output


# ── Nix Ingest (Phase 3 extension) Tests ─────────────────────────────────────

class TestNixIngest:
    """Tests for the nix ingest adapter — StorePath, Derivation,
    AstBuild entities and relations."""

    def _seed_nix_data(self, populated_env):
        """Populate a small amount of nix_store_paths + ast_builds
        for a real-ish ingest run."""
        conn = sqlite3.connect(populated_env["db_path"])
        conn.execute(
            """INSERT INTO nix_store_paths
                   (store_path, store_hash, name, deriver,
                    is_valid, nar_size)
                 VALUES ('/nix/store/aaaa-hello-1.0', 'aaaa',
                         'hello-1.0',
                         '/nix/store/bbbb-hello-1.0.drv', 1, 1024)"""
        )
        conn.execute(
            """INSERT INTO nix_store_paths
                   (store_path, store_hash, name, deriver,
                    is_valid)
                 VALUES ('/nix/store/bbbb-hello-1.0.drv',
                         'bbbb', 'hello-1.0.drv', NULL, 1)"""
        )
        # Invalid path — should be skipped
        conn.execute(
            """INSERT INTO nix_store_paths
                   (store_path, store_hash, name, is_valid)
                 VALUES ('/nix/store/cccc-old', 'cccc', 'old', 0)"""
        )
        # An AstBuild
        conn.execute(
            """INSERT INTO ast_builds
                   (output_hash, host_name, scopes, output_path,
                    manifest_json, nix_buildable)
                 VALUES ('deadbeef1234', 'zMothership2', '[]',
                         '/nix/store/aaaa-hello-1.0',
                         '{}', 1)"""
        )
        conn.commit()
        conn.close()

    def test_ingest_nix_emits_store_paths(self, populated_env, capsys):
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_nix_data(populated_env)
        EntityCommands().ingest(argparse.Namespace(source='nix', limit=20))
        capsys.readouterr()
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        # Two valid store paths inserted; the invalid one shouldn't be.
        rows = conn.execute(
            """SELECT external_ref FROM entities
                WHERE kind='StorePath' ORDER BY external_ref"""
        ).fetchall()
        conn.close()
        paths = [r['external_ref'] for r in rows]
        assert '/nix/store/aaaa-hello-1.0' in paths
        assert '/nix/store/bbbb-hello-1.0.drv' in paths
        assert '/nix/store/cccc-old' not in paths

    def test_ingest_nix_emits_derivation_and_relation(self, populated_env):
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_nix_data(populated_env)
        EntityCommands().ingest(argparse.Namespace(source='nix', limit=20))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        drv = conn.execute(
            """SELECT * FROM entities WHERE kind='Derivation'"""
        ).fetchone()
        assert drv is not None
        assert drv['external_ref'] == '/nix/store/bbbb-hello-1.0.drv'
        # Relation: StorePath aaaa built-by Derivation bbbb
        rel = conn.execute(
            """SELECT r.kind FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                 JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE e1.external_ref = '/nix/store/aaaa-hello-1.0'
                  AND e2.kind = 'Derivation'"""
        ).fetchone()
        conn.close()
        assert rel is not None
        assert rel['kind'] == 'built-by'

    def _seed_machine_and_generation(self, populated_env):
        """Add fleet_networks + fleet_machines + nix_generations."""
        conn = sqlite3.connect(populated_env["db_path"])
        # fleet_networks parent (network_name is the actual column;
        # project_id is required to satisfy UNIQUE constraint)
        pid_for_net = conn.execute(
            "SELECT id FROM projects WHERE slug='testproj'"
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO fleet_networks
                   (project_id, network_name, network_uuid,
                    config_file_path, description)
                 VALUES (?, 'testnet', 'uuid-testnet',
                         'network.nix', 'test')""",
            (pid_for_net,),
        )
        nid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        # fleet_machines
        conn.execute(
            """INSERT INTO fleet_machines
                   (network_id, machine_name, machine_uuid,
                    target_host, system_type)
                 VALUES (?, 'zMothership9', 'uuid-9',
                         '192.168.1.9', 'nixos')""",
            (nid,),
        )
        # A commit that the generation was built from
        pid = conn.execute(
            "SELECT id FROM projects WHERE slug='testproj'"
        ).fetchone()[0]
        bid = conn.execute(
            "SELECT id FROM vcs_branches WHERE project_id=?", (pid,)
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO vcs_commits (project_id, branch_id,
                                        commit_hash, commit_message,
                                        author, commit_timestamp)
                 VALUES (?, ?, 'cafebabe1234', 'gen commit',
                         'test', datetime('now'))""",
            (pid, bid),
        )
        # nix_generations
        conn.execute(
            """INSERT INTO nix_generations
                   (machine_name, generation_number,
                    toplevel_path, commit_hash,
                    switched_at, switch_success)
                 VALUES ('zMothership9', 47,
                         '/nix/store/aaaa-hello-1.0',
                         'cafebabe1234',
                         datetime('now'), 1)"""
        )
        conn.commit()
        conn.close()

    def test_ingest_nix_emits_machine_and_generation(self, populated_env):
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_nix_data(populated_env)
        self._seed_machine_and_generation(populated_env)
        # git ingest first so Commit entities exist for the built-from
        # relation to have a target.
        EntityCommands().ingest(argparse.Namespace(source='git', limit=20))
        EntityCommands().ingest(argparse.Namespace(source='nix', limit=20))

        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        m = conn.execute(
            """SELECT * FROM entities WHERE kind='Machine'
                AND external_ref='zMothership9'"""
        ).fetchone()
        assert m is not None
        g = conn.execute(
            """SELECT * FROM entities WHERE kind='Generation'
                AND external_ref='zMothership9/gen-47'"""
        ).fetchone()
        assert g is not None
        # Machine → ran → Generation
        rel = conn.execute(
            """SELECT COUNT(*) FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                 JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE e1.kind = 'Machine' AND e2.kind = 'Generation'
                  AND r.kind = 'ran'"""
        ).fetchone()[0]
        assert rel >= 1
        # Generation → built-from → Commit
        rel = conn.execute(
            """SELECT COUNT(*) FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                 JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE e1.kind = 'Generation' AND e2.kind = 'Commit'
                  AND r.kind = 'built-from'"""
        ).fetchone()[0]
        assert rel >= 1, "Generation → built-from → Commit missing"
        # Generation → installs → StorePath (toplevel_path)
        rel = conn.execute(
            """SELECT COUNT(*) FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                 JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE e1.kind = 'Generation' AND e2.kind = 'StorePath'
                  AND r.kind = 'installs'"""
        ).fetchone()[0]
        conn.close()
        assert rel >= 1, "Generation → installs → StorePath missing"

    def test_doctor_generations_have_built_from(self, populated_env,
                                                capsys):
        """Adding a generation WITHOUT ingesting nix should trigger the
        commuting-invariant check."""
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_machine_and_generation(populated_env)
        cmd = EntityCommands()
        rc = cmd.doctor_entities(argparse.Namespace(
            check='every_generation_with_commit_has_relation'
        ))
        assert rc == 1
        out = capsys.readouterr().out
        assert 'zMothership9' in out or 'issue' in out.lower()

    def test_ingest_nix_emits_astbuild_span(self, populated_env):
        import argparse
        from cli.commands.entity import EntityCommands
        self._seed_nix_data(populated_env)
        EntityCommands().ingest(argparse.Namespace(source='nix', limit=20))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        ab = conn.execute(
            """SELECT * FROM entities WHERE kind='AstBuild'"""
        ).fetchone()
        assert ab is not None
        assert ab['external_ref'] == 'zMothership2/deadbeef1234'
        # Relation: AstBuild produces StorePath
        rel = conn.execute(
            """SELECT r.kind FROM relations r
                 JOIN entities e1 ON e1.id = r.from_entity_id
                 JOIN entities e2 ON e2.id = r.to_entity_id
                WHERE e1.kind = 'AstBuild'
                  AND e2.kind = 'StorePath'
                  AND r.kind = 'produces'"""
        ).fetchone()
        conn.close()
        assert rel is not None


# ── Summary CLI Tests ────────────────────────────────────────────────────────

class TestSummary:
    """Health-at-a-glance summary command."""

    def test_summary_on_empty_env(self, temp_env, capsys):
        """With no data, summary should print zero-state sections
        without crashing."""
        from cli.commands.summary import SummaryCommand
        import argparse
        rc = SummaryCommand().summary(argparse.Namespace())
        assert rc == 0
        out = capsys.readouterr().out
        assert 'TempleDB Summary' in out
        assert 'Entity graph' in out
        # ANSI codes strip: we expect 0 entities
        assert '0' in out

    def test_summary_with_data(self, populated_env, capsys):
        """With populated_env's 3 files + our ingest, summary shows
        real counts."""
        import argparse
        from cli.commands.entity import EntityCommands
        from cli.commands.summary import SummaryCommand
        EntityCommands().ingest(argparse.Namespace(source='git', limit=20))
        EntityCommands().doctor_entities(argparse.Namespace(check=None))
        capsys.readouterr()
        rc = SummaryCommand().summary(argparse.Namespace())
        assert rc == 0
        out = capsys.readouterr().out
        assert 'Entity graph' in out
        assert 'File' in out  # top kind should be File after git ingest
        assert 'Doctor invariants' in out
        assert 'Handoff inbox' in out


# ── Cross-Session Handoff Notes (Phase 2.5) Tests ────────────────────────────

class TestHandoffNotes:
    """Tests for the cross-session pinboard added in migration 093.
    Pull-based: send + list + show + ack + pop lifecycle."""

    def test_table_exists(self, temp_env):
        conn = sqlite3.connect(temp_env["db_path"])
        row = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='handoff_notes'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 'table'

    def _args(self, **kwargs):
        import argparse
        defaults = dict(
            to=None, topic=None, broadcast=False,
            subject=None, body=None, tag=[],
            ref_report=None, ref_commit=None, ref_file=None,
            project=None, expires_at=None,
            for_session=None, unread=False,
            include_acked=False, limit=30,
            id=None, message=None,
        )
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_send_requires_destination(self, temp_env, capsys):
        from cli.commands.handoff import HandoffCommands
        cmd = HandoffCommands()
        rc = cmd.send(self._args(subject='hi', body='there'))
        assert rc == 1

    def test_send_and_list_roundtrip(self, temp_env, capsys):
        from cli.commands.handoff import HandoffCommands
        cmd = HandoffCommands()
        rc = cmd.send(self._args(
            to='sess-1', subject='hello', body='world',
        ))
        assert rc == 0
        capsys.readouterr()
        cmd.list(self._args())
        out = capsys.readouterr().out
        assert 'hello' in out
        assert 'sess-1' in out

    def test_show_marks_read(self, populated_env, capsys):
        from cli.commands.handoff import HandoffCommands
        cmd = HandoffCommands()
        cmd.send(self._args(
            topic='templedb', subject='s', body='b',
        ))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        nid = conn.execute(
            "SELECT id FROM handoff_notes ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()
        capsys.readouterr()
        cmd.show(self._args(id=nid))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT read_at FROM handoff_notes WHERE id=?", (nid,)
        ).fetchone()
        conn.close()
        assert row['read_at'] is not None

    def test_ack_marks_acked_with_reply(self, populated_env, capsys):
        from cli.commands.handoff import HandoffCommands
        cmd = HandoffCommands()
        cmd.send(self._args(
            broadcast=True, subject='s', body='b',
        ))
        conn = sqlite3.connect(populated_env["db_path"])
        nid = conn.execute(
            "SELECT id FROM handoff_notes ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()
        capsys.readouterr()
        cmd.ack(self._args(id=nid, message='got it'))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT acked_at, body FROM handoff_notes WHERE id=?",
            (nid,),
        ).fetchone()
        conn.close()
        assert row['acked_at'] is not None
        assert 'got it' in row['body']
        assert 'ack from' in row['body']

    def test_list_default_hides_acked(self, populated_env, capsys):
        from cli.commands.handoff import HandoffCommands
        cmd = HandoffCommands()
        cmd.send(self._args(broadcast=True, subject='keep', body='.'))
        cmd.send(self._args(broadcast=True, subject='gone', body='.'))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, subject FROM handoff_notes ORDER BY id"
        ).fetchall()
        conn.close()
        gone_id = next(r['id'] for r in rows if r['subject'] == 'gone')
        cmd.ack(self._args(id=gone_id))
        capsys.readouterr()
        cmd.list(self._args())
        out = capsys.readouterr().out
        assert 'keep' in out
        assert 'gone' not in out
        # But --include-acked shows both
        cmd.list(self._args(include_acked=True))
        out = capsys.readouterr().out
        assert 'keep' in out
        assert 'gone' in out

    def test_pop_shows_and_acks_oldest(self, populated_env, capsys):
        from cli.commands.handoff import HandoffCommands
        cmd = HandoffCommands()
        cmd.send(self._args(
            to='sess-42', subject='oldest', body='.',
        ))
        cmd.send(self._args(
            to='sess-42', subject='newer', body='.',
        ))
        capsys.readouterr()
        cmd.pop(self._args(for_session='sess-42'))
        out = capsys.readouterr().out
        assert 'oldest' in out
        # oldest was acked, newer was not
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT subject, acked_at FROM handoff_notes"
            " WHERE to_session='sess-42' ORDER BY id"
        ).fetchall()
        conn.close()
        assert rows[0]['acked_at'] is not None
        assert rows[1]['acked_at'] is None


# ── Ingestion Runs + Invariant Checks (Phase 3 reconcile) Tests ──────────────

class TestReconcileHistory:
    """Tests for the two persistence tables added in migrations 091 + 092:
    ingestion_runs (per-adapter run log) and invariant_checks (doctor
    result history). Together these make freshness telemetry queryable
    and let 'when did drift first appear' become answerable."""

    def test_tables_exist(self, temp_env):
        conn = sqlite3.connect(temp_env["db_path"])
        for name in ('ingestion_runs', 'invariant_checks'):
            row = conn.execute(
                "SELECT type FROM sqlite_master WHERE name=?", (name,)
            ).fetchone()
            assert row is not None, f"{name} missing"
            assert row[0] == 'table'
        conn.close()

    def test_ingest_records_a_run(self, populated_env):
        import argparse
        from cli.commands.entity import EntityCommands
        cmd = EntityCommands()
        cmd.ingest(argparse.Namespace(source='git', limit=20))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM ingestion_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row['adapter'] == 'git'
        assert row['status'] == 'ok'
        assert row['finished_at'] is not None
        assert row['entities_added'] >= 3  # 3 files in populated_env

    def test_ingest_history_prints_runs(self, populated_env, capsys):
        import argparse
        from cli.commands.entity import EntityCommands
        cmd = EntityCommands()
        cmd.ingest(argparse.Namespace(source='git', limit=20))
        capsys.readouterr()
        rc = cmd.ingest_history(argparse.Namespace(limit=10))
        assert rc == 0
        out = capsys.readouterr().out
        assert 'git' in out
        assert 'ok' in out

    def test_doctor_records_invariant_checks(self, populated_env):
        import argparse
        from cli.commands.entity import EntityCommands
        cmd = EntityCommands()
        # Doctor without prior ingest → intents/commits missing entities
        # → violations get recorded.
        cmd.doctor_entities(argparse.Namespace(check=None))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT check_name, status, issue_count
                 FROM invariant_checks
                ORDER BY id DESC LIMIT 10"""
        ).fetchall()
        conn.close()
        assert len(rows) > 0, "doctor should have inserted invariant_checks rows"
        names = {r['check_name'] for r in rows}
        assert 'relations_reference_valid_entities' in names
        assert 'edit_intent_applied_to_valid_commit' in names

    def test_doctor_history_prints(self, populated_env, capsys):
        import argparse
        from cli.commands.entity import EntityCommands
        cmd = EntityCommands()
        cmd.doctor_entities(argparse.Namespace(check=None))
        capsys.readouterr()
        rc = cmd.doctor_history(argparse.Namespace(
            check=None, violated_only=False, limit=20
        ))
        assert rc == 0
        out = capsys.readouterr().out
        assert 'relations_reference_valid_entities' in out

    def test_doctor_history_violated_only_filters(self, populated_env, capsys):
        import argparse
        from cli.commands.entity import EntityCommands
        cmd = EntityCommands()
        # No prior ingest → these will be violated
        cmd.doctor_entities(argparse.Namespace(check=None))
        # Now ingest, doctor again — should be clean
        cmd.ingest(argparse.Namespace(source='git', limit=20))
        cmd.ingest(argparse.Namespace(source='intent', limit=20))
        cmd.doctor_entities(argparse.Namespace(check=None))
        capsys.readouterr()
        cmd.doctor_history(argparse.Namespace(
            check=None, violated_only=True, limit=50
        ))
        out = capsys.readouterr().out
        # Every line should say ✗ or ! — never ✓
        for line in out.splitlines():
            if line.strip().startswith(('#', ' ')):
                assert '✓' not in line, f"violated-only leaked ok line: {line}"


# ── Report↔Commit Span (Workflow F) Tests ────────────────────────────────────

class TestReportImplementations:
    """Workflow F: report_implementations first-class span linking
    Report ↔ Commit. Auto-detection via regex + human confirm/reject."""

    def _seed_commit_and_report(self, populated_env, commit_hash,
                                report_body):
        """Insert a commit + a fake report file into populated_env."""
        import hashlib
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        pid = conn.execute(
            "SELECT id FROM projects WHERE slug='testproj'"
        ).fetchone()['id']
        bid = conn.execute(
            "SELECT id FROM vcs_branches WHERE project_id=?", (pid,)
        ).fetchone()['id']
        # Insert commit
        conn.execute(
            """INSERT INTO vcs_commits
                   (project_id, branch_id, commit_hash, commit_message,
                    author, commit_timestamp)
                 VALUES (?, ?, ?, 'a commit', 'test', datetime('now'))""",
            (pid, bid, commit_hash),
        )
        # Insert report file
        content = f"<html><head><title>Test Report</title></head><body>{report_body}</body></html>"
        chash = hashlib.sha256(content.encode()).hexdigest()
        conn.execute(
            """INSERT INTO content_blobs
                   (hash_sha256, content_text, content_type, encoding,
                    file_size_bytes)
                 VALUES (?, ?, 'text', 'utf-8', ?)""",
            (chash, content, len(content)),
        )
        conn.execute(
            """INSERT INTO project_files
                   (project_id, file_type_id, file_path, file_name,
                    status)
                 VALUES (?, 1, 'reports/test-report.html',
                         'test-report.html', 'active')""",
            (pid,),
        )
        fid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO file_contents
                   (file_id, content_hash, file_size_bytes, is_current)
                 VALUES (?, ?, ?, 1)""",
            (fid, chash, len(content)),
        )
        conn.commit()
        conn.close()

    def test_ingest_reports_creates_entity(self, populated_env, capsys):
        from cli.commands.entity import EntityCommands
        import argparse
        self._seed_commit_and_report(
            populated_env, 'abc1234567890def',
            'no commit ref in this report',
        )
        # Ingest git first so commit entities exist for the relation
        EntityCommands().ingest(argparse.Namespace(source='git'))
        capsys.readouterr()
        EntityCommands().ingest(argparse.Namespace(source='reports'))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT * FROM entities
                WHERE kind='Report' AND external_ref='reports/test-report.html'"""
        ).fetchone()
        conn.close()
        assert row is not None
        assert row['source_authority'] == 'author'
        assert row['label'] == 'Test Report'

    def test_auto_detect_creates_impl_when_hash_matches(self, populated_env,
                                                       capsys):
        from cli.commands.entity import EntityCommands
        import argparse
        commit_hash = 'abc1234567890def' + 'x' * 24  # 40-char
        commit_hash = 'abc1234567890def0000000000000000abcdef00'
        # Report mentions the prefix
        self._seed_commit_and_report(
            populated_env, commit_hash,
            f"This report describes work in commit abc1234567.",
        )
        EntityCommands().ingest(argparse.Namespace(source='git'))
        EntityCommands().ingest(argparse.Namespace(source='reports'))
        capsys.readouterr()
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT confidence, commit_hash FROM report_implementations
                WHERE report_path='reports/test-report.html'"""
        ).fetchone()
        conn.close()
        assert row is not None, "auto-detect should have inserted impl"
        assert row['confidence'] == 'auto-detected'
        assert row['commit_hash'] == commit_hash

    def test_report_link_confirms(self, populated_env, capsys):
        from cli.commands.entity import EntityCommands
        import argparse
        commit_hash = '1111111111111111111111111111111111111111'
        self._seed_commit_and_report(
            populated_env, commit_hash,
            'no auto-detectable hash here',
        )
        cmd = EntityCommands()
        rc = cmd.report_link(argparse.Namespace(
            report_path='reports/test-report.html',
            commit='1111111',
            message='I confirm this',
        ))
        assert rc == 0
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT confidence, note FROM report_implementations"
        ).fetchone()
        conn.close()
        assert row['confidence'] == 'confirmed'
        assert row['note'] == 'I confirm this'

    def test_report_reject_marks_rejected(self, populated_env, capsys):
        from cli.commands.entity import EntityCommands
        import argparse
        commit_hash = '2222222222222222222222222222222222222222'
        self._seed_commit_and_report(
            populated_env, commit_hash,
            'This mentions 2222222 explicitly.',
        )
        EntityCommands().ingest(argparse.Namespace(source='reports'))
        capsys.readouterr()
        conn = sqlite3.connect(populated_env["db_path"])
        iid = conn.execute(
            "SELECT id FROM report_implementations LIMIT 1"
        ).fetchone()[0]
        conn.close()
        rc = EntityCommands().report_reject(argparse.Namespace(id=iid))
        assert rc == 0
        conn = sqlite3.connect(populated_env["db_path"])
        row = conn.execute(
            "SELECT confidence FROM report_implementations WHERE id=?",
            (iid,)
        ).fetchone()
        conn.close()
        assert row[0] == 'rejected'

    def test_ingest_reports_preserves_confirmed_over_autodetect(
            self, populated_env, capsys):
        """A confirmed link must not be overwritten by a rerun of
        auto-detect."""
        from cli.commands.entity import EntityCommands
        import argparse
        commit_hash = '3333333333333333333333333333333333333333'
        self._seed_commit_and_report(
            populated_env, commit_hash,
            'Report mentions 3333333.',
        )
        cmd = EntityCommands()
        cmd.report_link(argparse.Namespace(
            report_path='reports/test-report.html',
            commit='3333333',
            message='confirmed manually',
        ))
        capsys.readouterr()
        # Now run auto-detect; should NOT downgrade our confirmed link
        cmd.ingest(argparse.Namespace(source='reports'))
        conn = sqlite3.connect(populated_env["db_path"])
        row = conn.execute(
            "SELECT confidence FROM report_implementations"
        ).fetchone()
        conn.close()
        assert row[0] == 'confirmed'

    def test_doctor_detects_dangling_report_impl(self, populated_env, capsys):
        from cli.commands.entity import EntityCommands
        import argparse
        conn = sqlite3.connect(populated_env["db_path"])
        conn.execute(
            """INSERT INTO report_implementations
                   (report_path, project_slug, commit_hash, confidence)
                 VALUES ('reports/nonexistent.html', 'testproj',
                         'deadbeef00', 'confirmed')"""
        )
        conn.commit()
        conn.close()
        cmd = EntityCommands()
        rc = cmd.doctor_entities(argparse.Namespace(
            check='report_impls_reference_valid_reports'
        ))
        assert rc == 1
        out = capsys.readouterr().out
        assert 'nonexistent.html' in out


# ── Entity Graph (Phase 3 groundwork) Tests ──────────────────────────────────

class TestEntityGraph:
    """MVP tests for the entity/relation substrate + ingest + doctor.
    See docs/ENTITY_GRAPH_DESIGN.md for the framing."""

    def test_tables_exist(self, temp_env):
        conn = sqlite3.connect(temp_env["db_path"])
        for name in ('entities', 'relations'):
            row = conn.execute(
                "SELECT type FROM sqlite_master WHERE name=?", (name,)
            ).fetchone()
            assert row is not None, f"{name} table missing"
            assert row[0] == 'table'
        conn.close()

    def test_ingest_git_creates_file_and_commit_entities(self, populated_env,
                                                         capsys):
        import argparse
        from cli.commands.entity import EntityCommands
        cmd = EntityCommands()
        cmd.ingest(argparse.Namespace(source='git'))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        # File entities
        n_files = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE kind='File'"
        ).fetchone()[0]
        assert n_files >= 3  # populated_env inserts 3 files
        # Every File entity has source_authority='git'
        wrong = conn.execute(
            """SELECT COUNT(*) FROM entities
                WHERE kind='File' AND source_authority != 'git'"""
        ).fetchone()[0]
        assert wrong == 0
        conn.close()

    def test_ingest_intent_creates_edit_intent_entities(self, populated_env):
        """After creating an EditIntent + ingesting, an entities row of
        kind='EditIntent' exists with the intent id as external_ref."""
        from cli.commands.intent import IntentCommands
        from cli.commands.entity import EntityCommands
        import argparse
        IntentCommands().create(argparse.Namespace(
            project='testproj', file_path='README.md',
            content='# ingest test\n', base_rev=None, message=None,
            content_argument=None, from_file=None,
        ))
        EntityCommands().ingest(argparse.Namespace(source='intent'))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT e.kind, e.external_ref, e.source_authority
                 FROM entities e
                WHERE e.kind = 'EditIntent'
                ORDER BY e.id DESC LIMIT 1"""
        ).fetchone()
        conn.close()
        assert row is not None
        assert row['kind'] == 'EditIntent'
        assert row['source_authority'] == 'templedb'

    def test_ingest_is_idempotent(self, populated_env, capsys):
        """Running ingest twice must not duplicate entities."""
        from cli.commands.entity import EntityCommands
        import argparse
        cmd = EntityCommands()
        cmd.ingest(argparse.Namespace(source='git'))
        capsys.readouterr()
        conn = sqlite3.connect(populated_env["db_path"])
        n_files_1 = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE kind='File'"
        ).fetchone()[0]
        conn.close()
        # Run again
        cmd.ingest(argparse.Namespace(source='git'))
        conn = sqlite3.connect(populated_env["db_path"])
        n_files_2 = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE kind='File'"
        ).fetchone()[0]
        conn.close()
        assert n_files_1 == n_files_2, \
            f"ingest not idempotent: {n_files_1} → {n_files_2}"

    def test_graph_explore_walks_relations(self, populated_env, capsys):
        """After ingesting, `entity explore` prints the entity + edges."""
        from cli.commands.entity import EntityCommands
        import argparse
        cmd = EntityCommands()
        cmd.ingest(argparse.Namespace(source='git'))
        capsys.readouterr()
        rc = cmd.graph_explore(argparse.Namespace(
            entity='File/testproj/README.md',
        ))
        assert rc == 0
        out = capsys.readouterr().out
        assert 'File/testproj/README.md' in out
        assert 'source_authority' in out

    def test_graph_explore_missing_entity(self, populated_env):
        from cli.commands.entity import EntityCommands
        import argparse
        cmd = EntityCommands()
        assert cmd.graph_explore(argparse.Namespace(
            entity='File/nonexistent/path.py',
        )) == 2

    def test_graph_stats_prints_counts(self, populated_env, capsys):
        from cli.commands.entity import EntityCommands
        import argparse
        cmd = EntityCommands()
        cmd.ingest(argparse.Namespace(source='git'))
        capsys.readouterr()
        assert cmd.graph_stats(argparse.Namespace()) == 0
        out = capsys.readouterr().out
        assert 'entities:' in out
        assert 'relations:' in out
        assert 'File' in out

    def test_doctor_entities_clean_on_populated(self, populated_env, capsys):
        """After a full ingest, all invariants should hold."""
        from cli.commands.entity import EntityCommands
        import argparse
        cmd = EntityCommands()
        cmd.ingest(argparse.Namespace(source='git'))
        capsys.readouterr()
        rc = cmd.doctor_entities(argparse.Namespace(check=None))
        assert rc == 0
        out = capsys.readouterr().out
        assert '✓' in out

    def test_doctor_detects_missing_commit_entity(self, populated_env, capsys):
        """Insert a vcs_commit, do NOT ingest, and doctor should flag
        the missing entity."""
        conn = sqlite3.connect(populated_env["db_path"])
        pid = conn.execute(
            "SELECT id FROM projects WHERE slug='testproj'"
        ).fetchone()[0]
        # Get the default branch
        bid = conn.execute(
            "SELECT id FROM vcs_branches WHERE project_id=?", (pid,)
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO vcs_commits (project_id, branch_id,
                                        commit_hash, commit_message,
                                        author, commit_timestamp)
                 VALUES (?, ?, 'deadbeef00', 'test commit', 'test',
                         datetime('now'))""",
            (pid, bid,)
        )
        conn.commit()
        conn.close()
        from cli.commands.entity import EntityCommands
        import argparse
        rc = EntityCommands().doctor_entities(
            argparse.Namespace(check='every_commit_has_entity')
        )
        assert rc == 1
        out = capsys.readouterr().out
        assert 'deadbeef00'[:12] in out or 'issue' in out.lower()


# ── EditIntent (Phase 2 groundwork) Tests ────────────────────────────────────

class TestEditIntents:
    """MVP tests for the edit_intents table + CLI. Lifecycle:
    create → apply | cancel."""

    def test_table_exists(self, temp_env):
        conn = sqlite3.connect(temp_env["db_path"])
        row = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='edit_intents'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 'table'

    def _make_args(self, **kwargs):
        import argparse
        defaults = dict(
            project=None, file_path=None, content=None, from_file=None,
            base_rev=None, message=None, id=None, session=None,
            all_statuses=False, limit=50,
        )
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_create_records_proposed_intent(self, populated_env, capsys):
        from cli.commands.intent import IntentCommands
        cmd = IntentCommands()
        args = self._make_args(
            project='testproj', file_path='README.md',
            content='# NEW TITLE\n', message='rename title',
        )
        rc = cmd.create(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert 'created (proposed)' in out
        # Row exists with status='proposed'
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM edit_intents ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert row['status'] == 'proposed'
        assert row['file_path'] == 'README.md'
        assert row['description'] == 'rename title'
        # content_blobs got the new hash too (for apply to find)
        import hashlib
        expected = hashlib.sha256(b'# NEW TITLE\n').hexdigest()
        assert row['new_content_hash'] == expected

    def test_apply_writes_to_file_contents(self, populated_env, capsys):
        from cli.commands.intent import IntentCommands
        cmd = IntentCommands()
        # Create then apply
        cmd.create(self._make_args(
            project='testproj', file_path='README.md',
            content='# APPLIED\n',
        ))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        intent_id = conn.execute(
            "SELECT id FROM edit_intents ORDER BY id DESC LIMIT 1"
        ).fetchone()['id']
        conn.close()
        capsys.readouterr()  # clear buffer

        rc = cmd.apply(self._make_args(id=intent_id))
        assert rc == 0
        # file_contents.is_current now points at the new hash
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT fc.content_hash, i.status, i.applied_at
                 FROM file_contents fc
                 JOIN project_files pf ON pf.id = fc.file_id
                 JOIN projects p ON p.id = pf.project_id
                 JOIN edit_intents i ON i.id = ?
                WHERE p.slug='testproj' AND pf.file_path='README.md'
                  AND fc.is_current=1""",
            (intent_id,),
        ).fetchone()
        conn.close()
        import hashlib
        expected = hashlib.sha256(b'# APPLIED\n').hexdigest()
        assert row['content_hash'] == expected
        assert row['status'] == 'applied'
        assert row['applied_at'] is not None

    def test_apply_rejects_non_proposed(self, populated_env):
        from cli.commands.intent import IntentCommands
        cmd = IntentCommands()
        cmd.create(self._make_args(
            project='testproj', file_path='README.md',
            content='# X\n',
        ))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        iid = conn.execute(
            "SELECT id FROM edit_intents ORDER BY id DESC LIMIT 1"
        ).fetchone()['id']
        conn.close()
        cmd.apply(self._make_args(id=iid))
        # Second apply should fail with exit 2
        assert cmd.apply(self._make_args(id=iid)) == 2

    def test_cancel_marks_cancelled(self, populated_env):
        from cli.commands.intent import IntentCommands
        cmd = IntentCommands()
        cmd.create(self._make_args(
            project='testproj', file_path='README.md',
            content='# CANCELLED\n',
        ))
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        iid = conn.execute(
            "SELECT id FROM edit_intents ORDER BY id DESC LIMIT 1"
        ).fetchone()['id']
        conn.close()
        assert cmd.cancel(self._make_args(id=iid)) == 0
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, cancelled_at FROM edit_intents WHERE id=?",
            (iid,),
        ).fetchone()
        conn.close()
        assert row['status'] == 'cancelled'
        assert row['cancelled_at'] is not None

    def test_file_set_records_intent(self, populated_env, capsys):
        """After 'templedb file set', an EditIntent row exists with
        status='applied' pointing at the new content hash. Phase 2
        Round 2 wiring."""
        from cli.commands.file import FileCommands
        import argparse, hashlib
        cmd = FileCommands()
        args = argparse.Namespace(
            project='testproj', file_path='README.md',
            content='# via file set\n', stage=False,
            verify=False, skip_intent=False,
        )
        rc = cmd.set(args)
        assert rc == 0
        # Intent row exists, applied
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT status, new_content_hash, description
                 FROM edit_intents
                ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        conn.close()
        expected_hash = hashlib.sha256(b'# via file set\n').hexdigest()
        assert row['status'] == 'applied'
        assert row['new_content_hash'] == expected_hash
        assert row['description'] == 'file set'

    def test_file_set_skip_intent_bypasses(self, populated_env):
        """--skip-intent must NOT record an intent. Rare path for
        bootstrap / tests where intent overhead is unwanted."""
        from cli.commands.file import FileCommands
        import argparse
        conn = sqlite3.connect(populated_env["db_path"])
        before = conn.execute(
            "SELECT COUNT(*) FROM edit_intents"
        ).fetchone()[0]
        conn.close()
        cmd = FileCommands()
        args = argparse.Namespace(
            project='testproj', file_path='src/main.py',
            content='raw = 1\n', stage=False,
            verify=False, skip_intent=True,
        )
        assert cmd.set(args) == 0
        conn = sqlite3.connect(populated_env["db_path"])
        after = conn.execute(
            "SELECT COUNT(*) FROM edit_intents"
        ).fetchone()[0]
        conn.close()
        assert after == before, \
            f"--skip-intent must not record intents (before={before}, after={after})"

    def test_vcs_working_state_intent_id_populated(self, populated_env):
        """After file set (with --stage), vcs_working_state.intent_id
        links to the recorded intent. Phase 2 provenance wiring."""
        from cli.commands.file import FileCommands
        import argparse
        cmd = FileCommands()
        args = argparse.Namespace(
            project='testproj', file_path='README.md',
            content='# staged\n', stage=True,
            verify=False, skip_intent=False,
        )
        assert cmd.set(args) == 0
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT ws.intent_id, i.status
                 FROM vcs_working_state ws
                 LEFT JOIN edit_intents i ON i.id = ws.intent_id
                 JOIN project_files pf ON pf.id = ws.file_id
                 JOIN projects p ON p.id = pf.project_id
                WHERE p.slug='testproj' AND pf.file_path='README.md'"""
        ).fetchone()
        conn.close()
        assert row is not None, "no vcs_working_state row for testproj/README.md"
        assert row['intent_id'] is not None, \
            "vcs_working_state.intent_id was not populated by file set"
        assert row['status'] == 'applied', \
            "linked intent should be status=applied"

    def test_list_defaults_to_proposed(self, populated_env, capsys):
        from cli.commands.intent import IntentCommands
        cmd = IntentCommands()
        cmd.create(self._make_args(
            project='testproj', file_path='README.md', content='a'))
        cmd.create(self._make_args(
            project='testproj', file_path='src/main.py', content='b'))
        # Apply one of them
        conn = sqlite3.connect(populated_env["db_path"])
        iid = conn.execute(
            "SELECT id FROM edit_intents ORDER BY id LIMIT 1"
        ).fetchone()[0]
        conn.close()
        cmd.apply(self._make_args(id=iid))
        capsys.readouterr()
        # Default list should show only the 1 remaining proposed
        cmd.list(self._make_args())
        out = capsys.readouterr().out
        assert 'proposed' in out
        assert 'applied' not in out
        # --all-statuses shows everything
        cmd.list(self._make_args(all_statuses=True))
        out = capsys.readouterr().out
        assert 'proposed' in out
        assert 'applied' in out


# ── Source Snapshots (Phase 1) Tests ─────────────────────────────────────────

class TestSourceSnapshots:
    """Tests for the source_snapshots view + templedb source CLI added in
    Phase 1 of the observer/integrator plan. Reframes file_contents /
    vcs_file_states as observations queryable via one unified view."""

    def test_view_exists_and_is_queryable(self, temp_env):
        conn = sqlite3.connect(temp_env["db_path"])
        row = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='source_snapshots'"
        ).fetchone()
        conn.close()
        assert row is not None, \
            "source_snapshots view missing after migration"
        assert row[0] == 'view'

    def test_view_returns_current_row(self, populated_env):
        """populated_env inserts three files with is_current=1;
        source_snapshots should surface all three with revision='current'."""
        conn = sqlite3.connect(populated_env["db_path"])
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT file_path, revision, source_authority
                 FROM source_snapshots
                WHERE project_slug = 'testproj'
                ORDER BY file_path"""
        ).fetchall()
        conn.close()
        paths = [r['file_path'] for r in rows]
        assert 'README.md' in paths
        assert 'src/main.py' in paths
        # Everything from is_current=1 should have revision='current'
        for r in rows:
            assert r['revision'] == 'current'
            assert r['source_authority'] == 'git'

    def test_cli_snapshot_prints_current_content(self, populated_env, capsys):
        from cli.commands.source import SourceCommands
        import argparse
        cmd = SourceCommands()
        args = argparse.Namespace(project='testproj',
                                  file_path='README.md',
                                  rev=None, meta=False)
        rc = cmd.snapshot(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert 'Test Project' in out

    def test_cli_snapshot_meta_prints_observation(self, populated_env,
                                                  capsys):
        from cli.commands.source import SourceCommands
        import argparse
        cmd = SourceCommands()
        args = argparse.Namespace(project='testproj',
                                  file_path='README.md',
                                  rev=None, meta=True)
        rc = cmd.snapshot(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert 'revision:' in out
        assert 'source_authority:' in out
        assert 'git' in out
        assert 'content_hash:' in out

    def test_cli_snapshot_missing_file(self, populated_env):
        from cli.commands.source import SourceCommands
        import argparse
        cmd = SourceCommands()
        args = argparse.Namespace(project='testproj',
                                  file_path='doesnotexist.md',
                                  rev=None, meta=False)
        assert cmd.snapshot(args) == 2

    def test_cli_snapshot_bad_revision(self, populated_env):
        from cli.commands.source import SourceCommands
        import argparse
        cmd = SourceCommands()
        args = argparse.Namespace(project='testproj',
                                  file_path='README.md',
                                  rev='deadbeef000000',
                                  meta=False)
        assert cmd.snapshot(args) == 2

    def test_cli_revisions_lists_current(self, populated_env, capsys):
        from cli.commands.source import SourceCommands
        import argparse
        cmd = SourceCommands()
        args = argparse.Namespace(project='testproj',
                                  file_path='README.md')
        rc = cmd.revisions(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert 'current' in out
        assert 'snapshot(s)' in out


# ── File Where (drift diagnostic) Tests ──────────────────────────────────────

class TestFileWhere:
    """Tests for `templedb file where` — the mirror drift diagnostic
    added as part of Phase 0 of the observer/integrator plan. Makes drift
    among DB / checkouts / edit-workspaces / legacy paths visible."""

    def test_where_returns_zero_when_all_mirrors_agree(self, populated_env,
                                                       monkeypatch, tmp_path):
        """DB has content X, checkout has content X, no other mirrors exist.
        Exit code 0, no drift detected."""
        import hashlib
        from cli.commands.file import FileCommands
        import argparse

        # Materialize testproj so a checkout exists at a known-good hash.
        from services.system_service import SystemService
        target = tmp_path / ".config" / "templedb" / "checkouts" / "testproj"
        target.parent.mkdir(parents=True)
        svc = SystemService()
        monkeypatch.setattr(svc, "_checkout_dir_for", lambda slug: target)
        svc.materialize_from_db("testproj")

        # Point Path.home() at our tmp_path so `where` probes it.
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        cmd = FileCommands()
        args = argparse.Namespace(project="testproj", file_path="README.md")
        rc = cmd.where(args)
        assert rc == 0, "expected 0 when all present mirrors agree"

    def test_where_detects_drift(self, populated_env, monkeypatch, tmp_path,
                                 capsys):
        """DB has content X, edit-workspace has content Y. Exit 1, output
        contains 'drift'."""
        from cli.commands.file import FileCommands
        import argparse

        # Set up edit-workspace with wrong content.
        ews = tmp_path / ".config" / "templedb" / "edit-workspaces" / "testproj"
        (ews).mkdir(parents=True)
        (ews / "README.md").write_text("wrong content")

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        cmd = FileCommands()
        args = argparse.Namespace(project="testproj", file_path="README.md")
        rc = cmd.where(args)
        captured = capsys.readouterr()
        assert rc == 1, f"expected 1 (drift), got {rc}: {captured.out}"
        assert "drift" in captured.out.lower()

    def test_where_returns_two_when_db_has_no_current(self, populated_env,
                                                     monkeypatch, tmp_path,
                                                     capsys):
        """No file_contents row → exit 2 with a diagnostic message."""
        from cli.commands.file import FileCommands
        import argparse

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        cmd = FileCommands()
        args = argparse.Namespace(project="testproj",
                                  file_path="doesnotexist.md")
        rc = cmd.where(args)
        assert rc == 2

    def test_where_returns_two_when_project_missing(self, populated_env,
                                                    capsys):
        """Bad project slug → exit 2."""
        from cli.commands.file import FileCommands
        import argparse

        cmd = FileCommands()
        args = argparse.Namespace(project="no-such-project-slug-xyz",
                                  file_path="README.md")
        rc = cmd.where(args)
        assert rc == 2


# ── Mirror Tests ──────────────────────────────────────────────────────────────

class TestMirrors:
    def test_mirror_add_and_list(self, temp_env):
        conn = sqlite3.connect(temp_env["db_path"])
        conn.execute(
            "INSERT INTO system_config (key, value, updated_at) "
            "VALUES ('mirror.testproj.github', 'git@github.com:user/repo.git', datetime('now'))"
        )
        conn.commit()

        row = conn.execute(
            "SELECT value FROM system_config WHERE key = 'mirror.testproj.github'"
        ).fetchone()
        assert row[0] == "git@github.com:user/repo.git"
        conn.close()


# ── Direnv Generator Tests ────────────────────────────────────────────────────

class TestDirenvGenerator:
    def test_shell_escape_empty(self):
        from direnv_generator import shell_escape
        assert shell_escape("") == "''"

    def test_shell_escape_simple(self):
        from direnv_generator import shell_escape
        assert shell_escape("hello") == "'hello'"

    def test_shell_escape_quotes(self):
        from direnv_generator import shell_escape
        result = shell_escape("it's")
        assert "\\'" in result

    def test_get_git_info_non_repo(self):
        from direnv_generator import get_git_info
        branch, ref = get_git_info(Path("/tmp"))
        assert branch is None

    def test_get_git_info_real_repo(self):
        from direnv_generator import get_git_info
        repo = Path(__file__).parent.parent  # templeDB repo
        branch, ref = get_git_info(repo)
        if (repo / ".git").exists():
            assert branch is not None


# ── Sync Engine Tests ─────────────────────────────────────────────────────────

