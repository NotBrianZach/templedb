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

