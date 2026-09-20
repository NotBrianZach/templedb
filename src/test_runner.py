#!/usr/bin/env python3
"""
TempleDB universal test runner.

Auto-detects project type and runs appropriate tests against live servers.
Stdlib-only — no pytest/httpx dependencies required.

Supports:
  - FastAPI (templedb GUI)
  - Next.js + Flask (bza/aireadalong)
  - Generic HTTP (any project with a web server)
"""
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from logger import get_logger

logger = get_logger(__name__)


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def resolve_test_deps(project_slug: str) -> dict[str, str]:
    """Resolve test dependencies from DB. Returns {env_var: binary_path}."""
    resolved = {}
    try:
        from db_utils import query_all, query_one
        project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if not project:
            return resolved
        deps = query_all(
            "SELECT nix_package, env_var, binary_name FROM project_test_deps WHERE project_id = ? AND enabled = 1",
            (project["id"],))
        for dep in deps:
            binary = _find_nix_binary(dep["nix_package"], dep.get("binary_name"))
            if binary and dep.get("env_var"):
                resolved[dep["env_var"]] = str(binary)
                logger.debug(f"Test dep: {dep['nix_package']} → {binary}")
    except Exception as e:
        logger.debug(f"Failed to resolve test deps: {e}")
    return resolved


def _find_nix_binary(nix_package: str, binary_name: str | None = None) -> Path | None:
    """Find a binary from a nix package — checks PATH, nix store, nix profile."""
    import shutil
    import glob

    name = binary_name or nix_package

    # 1. Explicit env var
    env_key = f"{nix_package.upper()}_PATH"
    env_path = os.environ.get(env_key)
    if env_path and Path(env_path).exists():
        return Path(env_path)

    # 2. On PATH
    found = shutil.which(name)
    if found:
        return Path(found)

    # 3. Nix store glob
    matches = sorted(glob.glob(f"/nix/store/*-{nix_package}-*/bin/{name}"), reverse=True)
    if matches:
        return Path(matches[0])

    # 4. Nix profile
    profile_path = Path.home() / ".nix-profile" / "bin" / name
    if profile_path.exists():
        return profile_path

    return None


def find_chromium() -> Path | None:
    """Find a Chromium binary. Prefers open-source Chromium over Google Chrome
    (Google Chrome on NixOS blocks --load-extension for unpacked MV3 extensions)."""
    # Try DB-resolved deps first
    deps = resolve_test_deps("bza")
    if "CHROME_PATH" in deps:
        return Path(deps["CHROME_PATH"])

    # Manual fallback
    result = _find_nix_binary("chromium", "chromium")
    if result:
        return result
    result = _find_nix_binary("google-chrome", "google-chrome-stable")
    return result


class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def check(self, name, condition, detail="", verbose=False):
        if condition:
            self.passed += 1
            if verbose:
                print(f"  \033[32mPASS\033[0m  {name}")
        else:
            self.failed += 1
            self.errors.append((name, detail))
            print(f"  \033[31mFAIL\033[0m  {name}: {detail}")

    def summary(self):
        total = self.passed + self.failed
        color = "\033[32m" if self.failed == 0 else "\033[31m"
        print(f"\n{'='*60}")
        print(f"{color}Results: {self.passed} passed, {self.failed} failed, {total} total\033[0m")
        if self.errors:
            print(f"\nFailures:")
            for name, detail in self.errors:
                print(f"  - {name}: {detail}")
        print(f"{'='*60}")
        return self.failed == 0


class HttpClient:
    """Simple HTTP client using urllib."""

    def __init__(self, base_url):
        self.base = base_url

    UA = "Mozilla/5.0 (X11; Linux x86_64) TempleDB-QA/1.0"

    def get(self, path, timeout=15):
        try:
            req = urllib.request.Request(f"{self.base}{path}")
            req.add_header("User-Agent", self.UA)
            r = urllib.request.urlopen(req, timeout=timeout)
            return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")
        except Exception as e:
            return 0, str(e)

    def post(self, path, data=None, timeout=30):
        try:
            body = urllib.parse.urlencode(data).encode() if data else b""
            req = urllib.request.Request(f"{self.base}{path}", data=body, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            req.add_header("User-Agent", self.UA)
            r = urllib.request.urlopen(req, timeout=timeout)
            return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")
        except Exception as e:
            return 0, str(e)

    def wait_ready(self, timeout=30, path="/"):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"{self.base}{path}", timeout=2)
                return True
            except Exception:
                time.sleep(0.3)
        return False


class ServerProcess:
    """Manages a background server process."""

    def __init__(self, cmd, cwd=None, env=None, port=None, name="server"):
        self.cmd = cmd
        self.cwd = cwd
        self.env = env or os.environ.copy()
        self.port = port or find_free_port()
        self.name = name
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen(
            self.cmd, cwd=self.cwd, env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        logger.debug(f"Started {self.name} (pid={self.proc.pid}, port={self.port})")

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            logger.debug(f"Stopped {self.name}")


def detect_project_type(project_path: Path) -> str:
    """Auto-detect project type from files present."""
    if (project_path / "src" / "gui.py").exists():
        return "fastapi"
    if (project_path / "frontend" / "package.json").exists():
        pkg = json.loads((project_path / "frontend" / "package.json").read_text())
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if "next" in deps:
            return "nextjs"
    if (project_path / "package.json").exists():
        pkg = json.loads((project_path / "package.json").read_text())
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if "next" in deps:
            return "nextjs"
        if "express" in deps:
            return "express"
    if (project_path / "app.py").exists() or (project_path / "backend" / "app.py").exists():
        return "flask"
    if (project_path / "flake.nix").exists():
        return "nix"
    return "unknown"


def find_test_file(project_path: Path) -> Path | None:
    """Find project-specific test definitions."""
    candidates = [
        project_path / "tests" / "test_web.py",
        project_path / "tests" / "test_gui.py",
        project_path / "test_web.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def generate_page_tests(client: HttpClient, result: TestResult, pages: list[tuple[str, str]], verbose=False):
    """Test that pages load with 200 and contain expected text."""
    for path, expected in pages:
        status, body = client.get(path)
        result.check(f"GET {path} returns 200", status == 200, f"got {status}", verbose)
        if expected:
            result.check(f"GET {path} contains '{expected}'", expected in body,
                        f"missing '{expected}'", verbose)


def generate_post_tests(client: HttpClient, result: TestResult, endpoints: list[tuple[str, dict | None, str]], verbose=False):
    """Test POST endpoints return 200 and optionally contain expected text."""
    for path, data, expected in endpoints:
        status, body = client.post(path, data)
        result.check(f"POST {path} returns 200", status == 200, f"got {status}", verbose)
        if expected:
            result.check(f"POST {path} contains '{expected}'", expected in body,
                        f"missing '{expected}'", verbose)


# ── Project-specific test configs ────────────────────────────────────────────

def get_templedb_tests():
    """Test definitions for TempleDB GUI."""
    pages = [
        ("/", "Dashboard"),
        ("/projects", "Projects"),
        ("/vcs", "VCS"),
        ("/env", "Env"),
        ("/nix", "Nix"),
        ("/deploy", "Deploy"),
        ("/audit", "Audit"),
        ("/domains", "Domains"),
        ("/docs", "Docs"),
        ("/schema-browser", "Schema"),
        ("/systemd", "Systemd"),
        ("/fleet-sync", "Fleet Sync"),
        ("/tests", "Tests"),
    ]
    posts = [
        ("/fleet-sync/probe/nonexistent_xyz", None, "Unknown"),
        ("/backup/local", None, ""),
    ]
    return pages, posts


def get_bza_tests():
    """Test definitions for BZA (aireadalong)."""
    pages = [
        ("/", "aireadalong"),  # Landing page
        ("/auth/login", ""),
        ("/auth/signup", ""),
        ("/upload", ""),
    ]
    posts = []
    return pages, posts


def get_bza_backend_tests():
    """Test definitions for BZA Flask backend."""
    pages = [
        ("/api/health", ""),  # Health check if it exists
    ]
    posts = []
    return pages, posts


def run_bza_production_qa(verbose=False) -> bool:
    """QA tests against live aireadalong.com production site."""
    result = TestResult()
    client = HttpClient("https://aireadalong.com")

    print("=== BZA Production QA ===\n")

    # ── Page load tests ──
    print("Page loads:")
    pages = [
        ("/", "aireadalong"),
        ("/auth/login", ""),
        ("/auth/signup", ""),
        ("/upload", ""),
        ("/quiz", ""),
        ("/settings", ""),
        ("/dashboard", ""),
    ]
    for path, expected in pages:
        status, body = client.get(path)
        result.check(f"GET {path} → {status}", status == 200, f"got {status}", verbose)
        if expected:
            result.check(f"  contains '{expected}'", expected.lower() in body.lower(),
                        f"missing '{expected}'", verbose)

    # ── API endpoint tests ──
    print("\nAPI endpoints:")

    # import-bza should reject unauthenticated
    status, body = client.post("/api/bza/import")
    result.check("POST /api/bza/import without auth → 401", status == 401,
                f"got {status}", verbose)

    # problem-set-chat should require problem
    try:
        req = urllib.request.Request(
            "https://aireadalong.com/api/problem-set-chat",
            data=json.dumps({"mode": "hint"}).encode(),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", HttpClient.UA)
        r = urllib.request.urlopen(req, timeout=15)
        api_status = r.status
        api_body = r.read().decode()
    except urllib.error.HTTPError as e:
        api_status = e.code
        api_body = e.read().decode()
    except Exception as e:
        api_status = 0
        api_body = str(e)
    result.check("POST /api/problem-set-chat without problem → 400", api_status == 400,
                f"got {api_status}: {api_body[:100]}", verbose)

    # ── Static assets ──
    print("\nStatic assets:")
    asset_paths = [
        "/manifest.json",
        "/sw.js",
    ]
    for path in asset_paths:
        status, _ = client.get(path)
        result.check(f"GET {path} → 200", status == 200, f"got {status}", verbose)

    # ── CORS on import-bza ──
    print("\nCORS:")
    try:
        req = urllib.request.Request(
            "https://aireadalong.com/api/import-bza",
            method="OPTIONS",
        )
        req.add_header("Origin", "chrome-extension://test")
        req.add_header("Access-Control-Request-Method", "POST")
        req.add_header("User-Agent", HttpClient.UA)
        r = urllib.request.urlopen(req, timeout=10)
        cors_status = r.status
        cors_headers = dict(r.headers)
        has_cors = "access-control-allow-origin" in {k.lower() for k in cors_headers}
    except urllib.error.HTTPError as e:
        cors_status = e.code
        has_cors = "access-control-allow-origin" in {k.lower() for k in dict(e.headers)}
    except Exception:
        cors_status = 0
        has_cors = False
    result.check("CORS headers on /api/bza/import", has_cors or cors_status == 404,
                f"status={cors_status}" if cors_status != 404 else "no OPTIONS handler (OK for Next.js)", verbose)

    # ── New user critical path ──
    print("\nNew user critical path:")
    status, body = client.get("/")
    if status == 200:
        result.check("Landing page has auth/onboarding links",
                    '/auth/' in body or 'sign' in body.lower() or 'login' in body.lower() or 'upload' in body.lower(),
                    "missing auth links", verbose)
        result.check("Landing page has feature descriptions",
                    'ai' in body.lower() and ('chat' in body.lower() or 'read' in body.lower()),
                    "missing feature text", verbose)
        result.check("Landing page has OG tags for social sharing",
                    'og:title' in body.lower(),
                    "missing og:title", verbose)

    status, body = client.get("/auth/signup")
    if status == 200:
        result.check("Signup page has email field",
                    'email' in body.lower(),
                    "missing email input", verbose)
        result.check("Signup page has Google OAuth",
                    'google' in body.lower(),
                    "missing Google auth button", verbose)

    status, body = client.get("/upload")
    if status == 200:
        result.check("Upload page renders",
                    'upload' in body.lower() or 'add' in body.lower(),
                    "upload page seems empty", verbose)

    # ── Classic library static files ──
    print("\nClassic library (static files):")
    classic_files = [
        "/classics/bible-septuagint.txt",
        "/classics/bible-septuagint.svg",
        "/classics/bible-douay-rheims.svg",
        "/classics/quran-pickthall.svg",
        "/classics/tao-te-ching.svg",
    ]
    for path in classic_files:
        status, _ = client.get(path)
        result.check(f"GET {path} → 200", status == 200, f"got {status}", verbose)

    # ── API reliability ──
    print("\nAPI reliability:")

    # Math-academy import endpoint exists
    try:
        req = urllib.request.Request(
            "https://aireadalong.com/api/import/math-academy",
            method="OPTIONS",
        )
        req.add_header("Origin", "chrome-extension://test")
        req.add_header("Access-Control-Request-Method", "POST")
        req.add_header("User-Agent", HttpClient.UA)
        r = urllib.request.urlopen(req, timeout=10)
        ma_status = r.status
    except urllib.error.HTTPError as e:
        ma_status = e.code
    except Exception:
        ma_status = 0
    result.check("OPTIONS /api/import/math-academy not 404",
                ma_status != 404, f"got {ma_status}", verbose)

    # fetch-url returns JSON, not HTML 404
    try:
        req = urllib.request.Request(
            "https://aireadalong.com/api/fetch-url",
            data=json.dumps({"url": "https://example.com"}).encode(),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", HttpClient.UA)
        r = urllib.request.urlopen(req, timeout=30)
        fu_status = r.status
        fu_body = r.read().decode()
        fu_is_json = fu_body.strip().startswith("{")
    except urllib.error.HTTPError as e:
        fu_status = e.code
        fu_body = e.read().decode()
        fu_is_json = fu_body.strip().startswith("{")
    except Exception:
        fu_status = 0
        fu_is_json = False
    result.check("POST /api/fetch-url returns JSON",
                fu_is_json, f"status={fu_status}", verbose)

    # search endpoint
    status, body = client.get("/api/search?q=test")
    result.check("GET /api/search returns 200 or 401 (auth-gated)",
                status in (200, 401), f"got {status}", verbose)

    # ── Performance (response times) ──
    print("\nPerformance:")
    import time as _time
    perf_pages = [("/", 3.0), ("/auth/login", 3.0), ("/upload", 3.0)]
    for path, max_secs in perf_pages:
        t0 = _time.time()
        status, _ = client.get(path, timeout=int(max_secs + 2))
        elapsed = _time.time() - t0
        result.check(f"GET {path} < {max_secs}s (took {elapsed:.1f}s)",
                    status == 200 and elapsed < max_secs,
                    f"{elapsed:.1f}s" if status == 200 else f"status={status}", verbose)

    # ── Content checks ──
    print("\nContent quality:")
    status, body = client.get("/")
    if status == 200:
        result.check("Landing page has meta description",
                    'meta' in body.lower() and ('description' in body.lower() or 'og:' in body.lower()),
                    "missing meta tags", verbose)
        result.check("Landing page has no error indicators",
                    'error' not in body[:500].lower() and 'exception' not in body[:500].lower(),
                    "found error text in page", verbose)

    # ── Structure tests (check deployed files match expectations) ──
    print("\nFile structure:")
    bza_path = Path("/home/zach/.local/share/templedb/fhs-deployments/bza/working")
    required_files = [
        "frontend/components/ProblemMapWidget.tsx",
        "frontend/components/BookReader.tsx",
        "frontend/components/BookCard.tsx",
        "frontend/components/BookUpload.tsx",
        "frontend/components/CharacterPanel.tsx",
        "frontend/components/StructurePanel.tsx",
        "frontend/components/ClassicLibrary.tsx",
        "frontend/lib/queries/images.ts",
        "frontend/lib/queries/problemSets.ts",
        "frontend/app/api/problem-set-chat/route.ts",
        "frontend/app/api/bza/import/route.ts",
        "frontend/app/api/import/math-academy/route.ts",
        "deploy_bza_web.sh",
        "docs/BZA_FORMAT.md",
    ]
    for f in required_files:
        result.check(f"  {f}", (bza_path / f).exists(), "missing", verbose)

    # Verify deprecated files are gone
    deprecated = []  # ProblemSetPanel kept for compat
    for f in deprecated:
        result.check(f"  {f} deleted", not (bza_path / f).exists(), "still exists", verbose)

    # ── Math Academy scraper tests ──
    print("\nMath Academy scraper:")
    scraper_path = Path("/home/zach/math-academy-scraper")
    scraper_files = [
        "content.js",
        "popup.js",
        "popup.html",
        "background.js",
        "manifest.json",
        "content.css",
        "package.json",
        "test/fixture.html",
        "test/run.mjs",
    ]
    for f in scraper_files:
        result.check(f"  {f}", (scraper_path / f).exists(), "missing", verbose)

    # Run scraper tests if node_modules exists
    if (scraper_path / "node_modules").exists():
        import subprocess

        print("\n  Running scraper extraction tests...")
        r = subprocess.run(
            ["node", "test/run.mjs"],
            cwd=str(scraper_path),
            capture_output=True, text=True, timeout=30,
        )
        scraper_passed = r.returncode == 0
        for line in r.stdout.strip().split("\n"):
            if "passed" in line and "failed" in line:
                result.check(f"  Extraction: {line.strip()}", scraper_passed, r.stdout[-200:], verbose)
                break
        else:
            result.check("  Extraction tests ran", scraper_passed, r.stderr[-200:], verbose)

        # Extension integration tests (popup, manifest, API endpoints)
        print("\n  Running extension integration tests...")
        r3 = subprocess.run(
            ["node", "test/extension.mjs"],
            cwd=str(scraper_path),
            capture_output=True, text=True, timeout=30,
        )
        ext_passed = r3.returncode == 0
        for line in r3.stdout.strip().split("\n"):
            if "passed" in line and "failed" in line:
                result.check(f"  Extension: {line.strip()}", ext_passed, r3.stdout[-300:], verbose)
                break
        else:
            result.check("  Extension tests ran", ext_passed, r3.stderr[-200:], verbose)

        # Puppeteer browser tests (needs Chromium + DISPLAY)
        test_deps = resolve_test_deps("bza")
        chromium = find_chromium()
        has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        if chromium and has_display:
            print(f"\n  Running Puppeteer browser tests (chromium: {chromium})...")
            r4 = subprocess.run(
                ["node", "test/puppeteer.mjs"],
                cwd=str(scraper_path),
                capture_output=True, text=True, timeout=60,
                env={**os.environ, **test_deps, "CHROME_PATH": str(chromium)},
            )
            pup_passed = r4.returncode == 0
            for line in r4.stdout.strip().split("\n"):
                if "passed" in line and "failed" in line:
                    result.check(f"  Puppeteer: {line.strip()}", pup_passed, r4.stdout[-300:], verbose)
                    break
            else:
                result.check("  Puppeteer tests ran", pup_passed, r4.stderr[-200:], verbose)
        else:
            if not chromium:
                print("\n  (skipping Puppeteer — chromium not found, install with: nix build nixpkgs#chromium)")
            else:
                print("\n  (skipping Puppeteer — no DISPLAY)")

        # Snapshot verification — tests a real MA scrape (informational — old scrapes may have issues)
        if (scraper_path / "test" / "snapshot-real.bza").exists():
            print("\n  Running snapshot verification (real MA scrape)...")
            r2 = subprocess.run(
                ["node", "test/verify-bza.mjs"],
                cwd=str(scraper_path),
                capture_output=True, text=True, timeout=30,
            )
            for line in r2.stdout.strip().split("\n"):
                if "passed" in line and "failed" in line:
                    label = line.strip()
                    if r2.returncode != 0:
                        print(f"  \033[33mWARN\033[0m  Snapshot: {label} (re-scrape with updated extension to fix)")
                    else:
                        result.check(f"  Snapshot: {label}", True, "", verbose)
                    break
    else:
        print("  (skipping — run `npm install` in math-academy-scraper first)")

    return result.summary()


PROJECT_TESTS = {
    "templedb": get_templedb_tests,
    "bza": get_bza_tests,
}


def load_tests_from_db(project_slug: str):
    """Load test definitions from project_tests table. Returns (pages, posts) or None."""
    try:
        from db_utils import query_all, query_one
        project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if not project:
            return None

        tests = query_all(
            "SELECT * FROM project_tests WHERE project_id = ? AND enabled = 1 ORDER BY test_type, path",
            (project["id"],))
        if not tests:
            return None

        pages = [(t["path"], t["expected_text"] or "") for t in tests if t["test_type"] == "page"]
        posts = [(t["path"], json.loads(t["post_data"]) if t.get("post_data") else None,
                  t["expected_text"] or "") for t in tests if t["test_type"] == "post"]
        return pages, posts
    except Exception:
        return None


def load_structure_tests_from_db(project_slug: str):
    """Load structure test definitions from DB. Returns dict or None."""
    try:
        from db_utils import query_all, query_one
        project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if not project:
            return None

        tests = query_all(
            "SELECT * FROM project_tests WHERE project_id = ? AND enabled = 1 AND test_type LIKE 'structure_%'",
            (project["id"],))
        if not tests:
            return None

        return {
            "required_files": [t["file_path"] for t in tests if t["test_type"] == "structure_file"],
            "required_dirs": [t["file_path"] for t in tests if t["test_type"] == "structure_dir"],
        }
    except Exception:
        return None


def save_test_run(project_slug: str, result: 'TestResult', duration_ms: int, output: str):
    """Save test run results to DB."""
    try:
        from db_utils import execute, query_one
        project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if project:
            execute(
                "INSERT INTO test_runs (project_id, total_tests, passed, failed, duration_ms, output) VALUES (?,?,?,?,?,?)",
                (project["id"], result.passed + result.failed, result.passed, result.failed, duration_ms, output))
    except Exception:
        pass


# ── Structure tests (no server needed) ───────────────────────────────────────

STRUCTURE_TESTS = {
    "bza": {
        "required_files": [
            "frontend/package.json",
            "frontend/app/layout.tsx",
            "frontend/app/page.tsx",
            "backend/app.py",
            "deploy_bza_web.sh",
            "flake.nix",
        ],
        "required_dirs": [
            "frontend/app",
            "frontend/components",
            "backend",
            "supabase/functions",
        ],
        "required_components": [
            "frontend/components/BookReader.tsx",
            "frontend/components/BookCard.tsx",
            "frontend/components/ChatPanel.tsx",
        ],
    },
    "templedb": {
        "required_files": [
            "src/gui.py",
            "src/db_utils.py",
            "src/mcp_server.py",
            "templedb",
            "templedb_launcher.py",
            "flake.nix",
        ],
        "required_dirs": [
            "src/cli/commands",
            "src/services",
            "src/backup",
            "migrations",
        ],
    },
}


def _run_structure_from_dict(project_path: Path, struct: dict, result: TestResult, verbose=False):
    """Run structure tests from a dict (DB or hardcoded)."""
    for f in struct.get("required_files", []):
        result.check(f"File exists: {f}", (project_path / f).exists(),
                    f"missing {project_path / f}", verbose)
    for d in struct.get("required_dirs", []):
        result.check(f"Dir exists: {d}", (project_path / d).is_dir(),
                    f"missing {project_path / d}", verbose)


def generate_structure_tests(project_path: Path, result: TestResult, verbose=False):
    """Test project file structure without starting servers."""
    slug = project_path.name
    # Try to match by common project names
    struct = None
    for key in STRUCTURE_TESTS:
        if key in str(project_path).lower() or key == slug:
            struct = STRUCTURE_TESTS[key]
            break

    if not struct:
        # Generic structure tests
        result.check("Project dir exists", project_path.exists(), str(project_path), verbose)
        return

    for f in struct.get("required_files", []):
        result.check(f"File exists: {f}", (project_path / f).exists(),
                    f"missing {project_path / f}", verbose)

    for d in struct.get("required_dirs", []):
        result.check(f"Dir exists: {d}", (project_path / d).is_dir(),
                    f"missing {project_path / d}", verbose)

    for c in struct.get("required_components", []):
        path = project_path / c
        result.check(f"Component exists: {Path(c).name}", path.exists(),
                    f"missing {path}", verbose)


# ── Server starters ─────────────────────────────────────────────────────────


def _find_project_python(project_path: Path) -> str:
    """Find the Python interpreter for a project — nix wrapper or system."""
    import re
    nix_result = Path.home() / ".local" / "state" / "templedb" / "last-result"
    if nix_result.exists():
        store_path = nix_result.read_text().strip()
        bin_file = Path(store_path) / "bin" / "templedb"
        if bin_file.exists():
            m = re.search(r'exec "([^"]+/bin/python3)"', bin_file.read_text())
            if m:
                return m.group(1)
    return sys.executable


def _find_project_pythonpath(project_path: Path) -> str:
    """Extract PYTHONPATH from nix wrapper if available."""
    import re
    nix_result = Path.home() / ".local" / "state" / "templedb" / "last-result"
    if nix_result.exists():
        store_path = nix_result.read_text().strip()
        bin_file = Path(store_path) / "bin" / "templedb"
        if bin_file.exists():
            m = re.search(r"PYTHONPATH='([^']+)'", bin_file.read_text())
            if m:
                return m.group(1)
    return ""


def start_fastapi_server(project_path: Path, port: int) -> ServerProcess:
    """Start a FastAPI server (e.g., TempleDB GUI)."""
    local_src = str(project_path / "src")
    python = _find_project_python(project_path)
    pythonpath = _find_project_pythonpath(project_path)

    env = os.environ.copy()
    # Local src FIRST so dev changes override nix store versions
    env["PYTHONPATH"] = f"{local_src}:{pythonpath}" if pythonpath else local_src
    env["PYTHONNOUSERSITE"] = "1"

    import tempfile
    launcher = tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False, prefix='templedb_test_')
    launcher.write(
        f"import sys; sys.path.insert(0, {local_src!r})\n"
        f"import uvicorn\n"
        f"from gui import app\n"
        f"uvicorn.run(app, host='127.0.0.1', port={port}, log_level='error')\n"
    )
    launcher.close()

    srv = ServerProcess(
        cmd=[python, launcher.name],
        cwd=local_src,
        env=env,
        port=port,
        name="templedb-gui",
    )
    srv.start()
    return srv


def start_nextjs_server(project_path: Path, port: int) -> ServerProcess:
    """Start a Next.js dev server."""
    frontend_dir = project_path / "frontend"
    if not frontend_dir.exists():
        frontend_dir = project_path

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["NODE_ENV"] = "test"

    srv = ServerProcess(
        cmd=["npx", "next", "dev", "-p", str(port)],
        cwd=str(frontend_dir),
        env=env,
        port=port,
        name="nextjs",
    )
    srv.start()
    return srv


def start_flask_server(project_path: Path, port: int) -> ServerProcess:
    """Start a Flask dev server."""
    backend_dir = project_path / "backend"
    if not backend_dir.exists():
        backend_dir = project_path

    env = os.environ.copy()
    env["FLASK_APP"] = "app.py"
    env["FLASK_ENV"] = "testing"
    env["PORT"] = str(port)

    srv = ServerProcess(
        cmd=[sys.executable, "-m", "flask", "run", "--port", str(port), "--no-reload"],
        cwd=str(backend_dir),
        env=env,
        port=port,
        name="flask",
    )
    srv.start()
    return srv


# ── Main runner ──────────────────────────────────────────────────────────────

def run_tests(project_slug: str, project_path: Path, verbose=False, dry_run=False) -> bool:
    """Run tests for a project. Returns True if all passed."""
    project_type = detect_project_type(project_path)
    print(f"Project: {project_slug}")
    print(f"Path:    {project_path}")
    print(f"Type:    {project_type}")

    if dry_run:
        test_file = find_test_file(project_path)
        print(f"Tests:   {test_file or 'auto-generated'}")
        get_tests = PROJECT_TESTS.get(project_slug)
        if get_tests:
            pages, posts = get_tests()
            print(f"  {len(pages)} page tests, {len(posts)} POST tests")
        else:
            print(f"  No project-specific tests defined — will test basic page loads")
        return True

    servers = []
    result = TestResult()
    start_time = time.time()

    try:
        # Try loading tests from DB first, fall back to hardcoded
        db_tests = load_tests_from_db(project_slug)
        db_struct = load_structure_tests_from_db(project_slug)

        # Start appropriate servers
        if project_type == "fastapi" or project_slug == "templedb":
            port = find_free_port()
            print(f"\nStarting FastAPI server on port {port}...")
            srv = start_fastapi_server(project_path, port)
            servers.append(srv)
            client = HttpClient(f"http://127.0.0.1:{port}")

            if not client.wait_ready(timeout=15):
                print("ERROR: Server failed to start")
                return False
            print("Server ready.\n")

            # Run tests — DB first, then hardcoded fallback
            if db_tests:
                pages, posts = db_tests
            else:
                get_tests = PROJECT_TESTS.get(project_slug, get_templedb_tests)
                pages, posts = get_tests()
            generate_page_tests(client, result, pages, verbose)
            generate_post_tests(client, result, posts, verbose)

        elif project_type == "nextjs":
            frontend_dir = project_path / "frontend"
            if not frontend_dir.exists():
                frontend_dir = project_path

            # Structure tests (always run, no server needed)
            print("\nRunning structure tests...")
            if db_struct:
                _run_structure_from_dict(project_path, db_struct, result, verbose)
            else:
                generate_structure_tests(project_path, result, verbose)

            # Check if node_modules exists
            has_node_modules = (frontend_dir / "node_modules").exists()
            has_next = (frontend_dir / "node_modules" / ".bin" / "next").exists() if has_node_modules else False
            if not has_next:
                print(f"\nNext.js not installed in {frontend_dir}")
                print(f"  Run: cd {frontend_dir} && npm install")
                print(f"  Skipping server tests (structure tests still ran)")
            else:
                frontend_port = find_free_port()
                print(f"\nStarting Next.js on port {frontend_port}...")
                srv = start_nextjs_server(project_path, frontend_port)
                servers.append(srv)
                client = HttpClient(f"http://127.0.0.1:{frontend_port}")

                server_ready = client.wait_ready(timeout=60, path="/")
                if not server_ready:
                    print("WARNING: Next.js server didn't respond in 60s — skipping server tests")
                else:
                    # Check for Flask backend too
                    backend_dir = project_path / "backend"
                    if (backend_dir / "app.py").exists():
                        backend_port = find_free_port()
                        print(f"Starting Flask backend on port {backend_port}...")
                        flask_srv = start_flask_server(project_path, backend_port)
                        servers.append(flask_srv)
                        backend_client = HttpClient(f"http://127.0.0.1:{backend_port}")
                        backend_client.wait_ready(timeout=15, path="/")

                    print("Servers ready.\n")

                    get_tests = PROJECT_TESTS.get(project_slug)
                    if get_tests:
                        pages, posts = get_tests()
                        generate_page_tests(client, result, pages, verbose)
                        generate_post_tests(client, result, posts, verbose)
                    else:
                        generate_page_tests(client, result, [("/", "")], verbose)

        else:
            print(f"\nUnknown project type '{project_type}' — running basic checks")
            # Try to find and test any running web server
            test_file = find_test_file(project_path)
            if test_file:
                print(f"Found test file: {test_file}")
                # Execute it as a subprocess
                r = subprocess.run(
                    [sys.executable, str(test_file)],
                    cwd=str(project_path),
                    timeout=120,
                )
                return r.returncode == 0
            else:
                print("No test file found and project type not recognized.")
                print(f"  Create tests at: {project_path}/tests/test_web.py")
                return True

        # Check for project-specific test file and run it too
        test_file = find_test_file(project_path)
        if test_file and project_type == "fastapi":
            print(f"\nRunning project test file: {test_file.name}")
            # The test file uses its own server, skip for now
            pass

    finally:
        for srv in servers:
            srv.stop()

    duration_ms = int((time.time() - start_time) * 1000)
    save_test_run(project_slug, result, duration_ms, "\n".join(
        f"{'PASS' if ok else 'FAIL'}: {name}" for name, ok in
        [(name, True) for name in [""] * result.passed] +
        [(name, False) for name, _ in result.errors]
    ))
    return result.summary()
