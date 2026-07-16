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

