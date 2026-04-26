#!/usr/bin/env python3
"""
Unified variable management: env vars + secrets with global/tag/project scope hierarchy.

Scope resolution order (most → least specific):
  1. project + target  (e.g. woofs_projects, staging:KEY)
  2. project           (e.g. woofs_projects, KEY)
  3. tag               (e.g. tag frontend, KEY)
  4. global + target   (e.g. global, staging:KEY)
  5. global            (e.g. global, KEY)

Env vars are stored in the environment_variables table.
Secrets are stored in secret_blobs + project_secret_blobs (per-variable age encryption).

Usage examples:
  templedb var set woofs_projects SUPABASE_URL https://... --target staging
  templedb var set woofs_projects SECRET_KEY abc123 --secret --keys templedb-primary
  templedb var set NODE_ENV production --global
  templedb var set DEBUG true --tag backend
  templedb var get woofs_projects SUPABASE_URL --target staging
  templedb var list woofs_projects --target staging
  templedb var export woofs_projects --target staging --format shell
  templedb var unset woofs_projects SUPABASE_URL --target staging
  templedb var tag add frontend woofs_projects shopUI
  templedb var tag list
  templedb var tag list woofs_projects
"""
import sys
import os
import json
import subprocess
import logging
from pathlib import Path

# Allow running standalone (e.g. python var.py) as well as via installed launcher
try:
    from db_utils import query_one, query_all, execute
    from cli.core import Command
except ImportError:
    _src = str(Path(__file__).parent.parent.parent)
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from db_utils import query_one, query_all, execute
    from cli.core import Command

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _var_key(target, var_name):
    """Encode target into var_name for storage."""
    if target and target != 'default':
        return f"{target}:{var_name}"
    return var_name


def _parse_var_key(stored_name):
    """Return (target, var_name) from stored name."""
    if ':' in stored_name:
        target, name = stored_name.split(':', 1)
        return target, name
    return 'default', stored_name


def _get_age_recipient(key_name: str) -> tuple:
    """Look up age recipient and key_id for a named encryption key."""
    row = query_one(
        "SELECT id, recipient FROM encryption_keys WHERE key_name = ? AND is_active = 1",
        (key_name,)
    )
    if not row:
        print(f"error: encryption key '{key_name}' not found or not active", file=sys.stderr)
        print("  List keys: templedb key list", file=sys.stderr)
        sys.exit(1)
    return row['id'], row['recipient']


def _age_encrypt(plaintext: bytes, recipients: list) -> bytes:
    """Encrypt plaintext with one or more age recipients."""
    cmd = ["age"]
    for r in recipients:
        cmd += ["-r", r]
    cmd += ["-a"]  # ASCII armor
    try:
        proc = subprocess.run(cmd, input=plaintext, capture_output=True, check=True)
        return proc.stdout
    except FileNotFoundError:
        print("error: age not found on PATH", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"error: age encryption failed: {e.stderr.decode().strip()}", file=sys.stderr)
        sys.exit(1)


def _age_decrypt(encrypted: bytes) -> bytes:
    """Decrypt using the key file from env."""
    key_file = (
        os.environ.get("TEMPLEDB_AGE_KEY_FILE")
        or os.environ.get("SOPS_AGE_KEY_FILE")
        or os.path.expanduser("~/.config/sops/age/keys.txt")
    )
    if not os.path.exists(key_file):
        print(f"error: age key file not found: {key_file}", file=sys.stderr)
        sys.exit(1)
    try:
        proc = subprocess.run(
            ["age", "-d", "-i", key_file],
            input=encrypted, capture_output=True, check=True
        )
        return proc.stdout
    except FileNotFoundError:
        print("error: age not found on PATH", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"error: age decryption failed: {e.stderr.decode().strip()}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command class
# ---------------------------------------------------------------------------

class VarCommands(Command):
    """Unified variable (env + secret) management with scope hierarchy."""

    def _get_project(self, slug):
        row = self.query_one("SELECT * FROM projects WHERE slug = ?", (slug,))
        if not row:
            print(f"error: project not found: {slug}", file=sys.stderr)
            sys.exit(1)
        return row

    def _get_or_create_tag(self, tag_name: str) -> int:
        row = self.query_one("SELECT id FROM tags WHERE name = ?", (tag_name,))
        if row:
            return row['id']
        return self.execute("INSERT INTO tags (name) VALUES (?)", (tag_name,))

    def _get_tag(self, tag_name: str):
        row = self.query_one("SELECT * FROM tags WHERE name = ?", (tag_name,))
        if not row:
            print(f"error: tag '{tag_name}' not found", file=sys.stderr)
            sys.exit(1)
        return row

    def _project_tag_ids(self, project_id: int) -> list:
        rows = self.query_all("SELECT tag_id FROM project_tags WHERE project_id = ?", (project_id,))
        return [r['tag_id'] for r in rows]

    # ------------------------------------------------------------------
    # Secret helpers (uses project_secret_blobs + secret_blobs schema)
    # ------------------------------------------------------------------

    def _secret_set(self, project_id: int, profile: str, secret_name: str,
                    value: str, key_names: list):
        """Set an individual secret, encrypted for the given keys."""
        key_ids = []
        recipients = []
        for kn in key_names:
            kid, rec = _get_age_recipient(kn)
            key_ids.append(kid)
            recipients.append(rec)

        encrypted = _age_encrypt(value.encode('utf-8'), recipients)

        # Check if this secret already exists for this project+profile
        existing = self.query_one("""
            SELECT sb.id
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND sb.secret_name = ? AND psb.profile = ?
        """, (project_id, secret_name, profile))

        actor = os.environ.get('USER', 'unknown')

        if existing:
            # Update existing blob
            self.execute("""
                UPDATE secret_blobs SET secret_blob = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (encrypted, existing['id']))
            # Re-assign keys
            self.execute("DELETE FROM secret_key_assignments WHERE secret_blob_id = ?",
                         (existing['id'],))
            for kid in key_ids:
                self.execute("""
                    INSERT INTO secret_key_assignments (secret_blob_id, key_id, added_by)
                    VALUES (?, ?, ?)
                """, (existing['id'], kid, actor))
        else:
            # Insert new blob
            self.execute("""
                INSERT INTO secret_blobs (profile, secret_name, secret_blob, content_type)
                VALUES (?, ?, ?, 'application/text')
            """, (profile, secret_name, encrypted))
            row = self.query_one("SELECT id FROM secret_blobs WHERE id = last_insert_rowid()")
            secret_blob_id = row['id']
            self.execute("""
                INSERT INTO project_secret_blobs (project_id, secret_blob_id, profile)
                VALUES (?, ?, ?)
            """, (project_id, secret_blob_id, profile))
            for kid in key_ids:
                self.execute("""
                    INSERT INTO secret_key_assignments (secret_blob_id, key_id, added_by)
                    VALUES (?, ?, ?)
                """, (secret_blob_id, kid, actor))

    def _secret_get(self, project_id: int, profile: str, secret_name: str):
        """Get and decrypt a single secret. Returns plaintext str or None."""
        row = self.query_one("""
            SELECT sb.secret_blob
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND sb.secret_name = ? AND psb.profile = ?
        """, (project_id, secret_name, profile))
        if not row:
            return None
        return _age_decrypt(row['secret_blob']).decode('utf-8')

    def _secrets_export(self, project_id: int, profile: str) -> dict:
        """Export all secrets for a project as {name: plaintext}."""
        rows = self.query_all("""
            SELECT sb.secret_name, sb.secret_blob
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND psb.profile = ?
              AND sb.content_type = 'application/text'
            ORDER BY sb.secret_name
        """, (project_id, profile))
        result = {}
        for row in rows:
            try:
                result[row['secret_name']] = _age_decrypt(row['secret_blob']).decode('utf-8')
            except SystemExit:
                logger.warning(f"Failed to decrypt {row['secret_name']}")
        return result

    def _secret_unset(self, project_id: int, profile: str, secret_name: str):
        existing = self.query_one("""
            SELECT sb.id
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND sb.secret_name = ? AND psb.profile = ?
        """, (project_id, secret_name, profile))
        if existing:
            # Cascade deletes handle key_assignments and project_secret_blobs
            self.execute("DELETE FROM secret_blobs WHERE id = ?", (existing['id'],))
            return True
        return False

    # ------------------------------------------------------------------
    # var set
    # ------------------------------------------------------------------

    def var_set(self, args) -> int:
        key = args.key
        value = args.value
        target = args.target or 'default'
        profile = getattr(args, 'profile', 'default') or 'default'

        if args.global_scope:
            stored_name = _var_key(target, key)
            self.execute("""
                INSERT INTO environment_variables (scope_type, scope_id, var_name, var_value)
                VALUES ('global', NULL, ?, ?)
                ON CONFLICT(scope_type, scope_id, var_name)
                DO UPDATE SET var_value = excluded.var_value, updated_at = CURRENT_TIMESTAMP
            """, (stored_name, value))
            scope_label = "global" + (f" ({target})" if target != 'default' else "")
            print(f"set {key} [{scope_label}]")
            return 0

        if getattr(args, 'tag', None):
            stored_name = _var_key(target, key)
            tag_id = self._get_or_create_tag(args.tag)
            self.execute("""
                INSERT INTO environment_variables (scope_type, scope_id, var_name, var_value)
                VALUES ('tag', ?, ?, ?)
                ON CONFLICT(scope_type, scope_id, var_name)
                DO UPDATE SET var_value = excluded.var_value, updated_at = CURRENT_TIMESTAMP
            """, (tag_id, stored_name, value))
            print(f"set {key} [tag:{args.tag}]")
            return 0

        if not getattr(args, 'project', None):
            print("error: specify a project slug, --global, or --tag", file=sys.stderr)
            return 1

        project = self._get_project(args.project)

        if getattr(args, 'secret', False):
            if not getattr(args, 'keys', None):
                print("error: --secret requires --keys (e.g. --keys templedb-primary)", file=sys.stderr)
                return 1
            key_names = [k.strip() for k in args.keys.split(',')]
            self._secret_set(project['id'], profile, key, value, key_names)
            print(f"set secret {key} [{args.project}/{profile}]")
            return 0

        stored_name = _var_key(target, key)
        self.execute("""
            INSERT INTO environment_variables (scope_type, scope_id, var_name, var_value)
            VALUES ('project', ?, ?, ?)
            ON CONFLICT(scope_type, scope_id, var_name)
            DO UPDATE SET var_value = excluded.var_value, updated_at = CURRENT_TIMESTAMP
        """, (project['id'], stored_name, value))
        scope_label = args.project + (f" ({target})" if target != 'default' else "")
        print(f"set {key} [{scope_label}]")
        return 0

    # ------------------------------------------------------------------
    # var get
    # ------------------------------------------------------------------

    def var_get(self, args) -> int:
        key = args.key
        target = getattr(args, 'target', None) or 'default'
        profile = getattr(args, 'profile', 'default') or 'default'

        if getattr(args, 'global_scope', False):
            stored_name = _var_key(target, key)
            row = self.query_one("""
                SELECT var_value FROM environment_variables
                WHERE scope_type = 'global' AND scope_id IS NULL AND var_name = ?
            """, (stored_name,))
            if not row and target != 'default':
                row = self.query_one("""
                    SELECT var_value FROM environment_variables
                    WHERE scope_type = 'global' AND scope_id IS NULL AND var_name = ?
                """, (key,))
            if row:
                print(row['var_value'])
                return 0
            print(f"error: {key} not found in global scope", file=sys.stderr)
            return 1

        if not getattr(args, 'project', None):
            print("error: specify a project slug or --global", file=sys.stderr)
            return 1

        project = self._get_project(args.project)

        if getattr(args, 'secret', False):
            val = self._secret_get(project['id'], profile, key)
            if val is None:
                print(f"error: secret {key} not found [{args.project}/{profile}]", file=sys.stderr)
                return 1
            print(val)
            return 0

        value = self._resolve(project['id'], key, target)
        if value is None:
            print(f"error: {key} not found (project={args.project}, target={target})", file=sys.stderr)
            return 1
        print(value)
        return 0

    def _ev_lookup(self, scope_type, scope_id, var_name):
        if scope_id is None:
            row = self.query_one("""
                SELECT var_value FROM environment_variables
                WHERE scope_type = ? AND scope_id IS NULL AND var_name = ?
            """, (scope_type, var_name))
        else:
            row = self.query_one("""
                SELECT var_value FROM environment_variables
                WHERE scope_type = ? AND scope_id = ? AND var_name = ?
            """, (scope_type, scope_id, var_name))
        return row['var_value'] if row else None

    def _resolve(self, project_id: int, key: str, target: str = 'default'):
        """Resolve env var using scope hierarchy. Returns value or None."""
        # 1. project + target
        if target and target != 'default':
            v = self._ev_lookup('project', project_id, _var_key(target, key))
            if v is not None:
                return v

        # 2. project (no target)
        v = self._ev_lookup('project', project_id, key)
        if v is not None:
            return v

        # 3. tag scope
        for tag_id in self._project_tag_ids(project_id):
            if target and target != 'default':
                v = self._ev_lookup('tag', tag_id, _var_key(target, key))
                if v is not None:
                    return v
            v = self._ev_lookup('tag', tag_id, key)
            if v is not None:
                return v

        # 4. global + target
        if target and target != 'default':
            v = self._ev_lookup('global', None, _var_key(target, key))
            if v is not None:
                return v

        # 5. global
        return self._ev_lookup('global', None, key)

    # ------------------------------------------------------------------
    # var list
    # ------------------------------------------------------------------

    def var_list(self, args) -> int:
        target_filter = getattr(args, 'target', None)
        profile = getattr(args, 'profile', 'default') or 'default'

        if getattr(args, 'global_scope', False):
            rows = self.query_all("""
                SELECT var_name, var_value FROM environment_variables
                WHERE scope_type = 'global' AND scope_id IS NULL ORDER BY var_name
            """)
            self._print_vars(rows, "[global]", target_filter)
            return 0

        if getattr(args, 'tag', None):
            tag = self._get_tag(args.tag)
            rows = self.query_all("""
                SELECT var_name, var_value FROM environment_variables
                WHERE scope_type = 'tag' AND scope_id = ? ORDER BY var_name
            """, (tag['id'],))
            self._print_vars(rows, f"[tag:{args.tag}]", target_filter)
            return 0

        if not getattr(args, 'project', None):
            self._list_all(target_filter)
            return 0

        project = self._get_project(args.project)
        print(f"\nVars for {args.project}:")
        print("=" * 50)

        # Global
        global_rows = self.query_all("""
            SELECT var_name, var_value FROM environment_variables
            WHERE scope_type = 'global' AND scope_id IS NULL ORDER BY var_name
        """)
        if global_rows:
            self._print_vars(global_rows, "  [global]", target_filter)

        # Tag
        for tag_id in self._project_tag_ids(project['id']):
            tag_row = self.query_one("SELECT name FROM tags WHERE id = ?", (tag_id,))
            tag_rows = self.query_all("""
                SELECT var_name, var_value FROM environment_variables
                WHERE scope_type = 'tag' AND scope_id = ? ORDER BY var_name
            """, (tag_id,))
            if tag_rows:
                self._print_vars(tag_rows, f"  [tag:{tag_row['name']}]", target_filter)

        # Project
        proj_rows = self.query_all("""
            SELECT var_name, var_value FROM environment_variables
            WHERE scope_type = 'project' AND scope_id = ? ORDER BY var_name
        """, (project['id'],))
        if proj_rows:
            self._print_vars(proj_rows, f"  [project]", target_filter)

        # Secret keys (names only — don't decrypt for list)
        try:
            secret_rows = self.query_all("""
                SELECT sb.secret_name
                FROM project_secret_blobs psb
                JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
                WHERE psb.project_id = ? AND psb.profile = ?
                  AND sb.content_type = 'application/text'
                ORDER BY sb.secret_name
            """, (project['id'], profile))
            if secret_rows:
                print(f"\n  [secrets/{profile}]")
                for r in secret_rows:
                    print(f"    {r['secret_name']}=<encrypted>")
        except Exception:
            pass

        print()
        return 0

    def _print_vars(self, rows, label, target_filter):
        filtered = []
        for row in rows:
            t, name = _parse_var_key(row['var_name'])
            if target_filter and t != target_filter and t != 'default':
                continue
            filtered.append((t, name, row['var_value']))
        if not filtered:
            return
        print(f"\n{label}")
        for t, name, value in filtered:
            target_suffix = f" ({t})" if t != 'default' else ""
            display = f"{value[:12]}...{value[-6:]}" if value and len(value) > 40 else (value or '')
            print(f"    {name}{target_suffix}={display}")

    def _list_all(self, target_filter):
        rows = self.query_all("""
            SELECT ev.scope_type, ev.scope_id, ev.var_name, ev.var_value,
                   p.slug as project_slug, t.name as tag_name
            FROM environment_variables ev
            LEFT JOIN projects p ON ev.scope_type = 'project' AND ev.scope_id = p.id
            LEFT JOIN tags t ON ev.scope_type = 'tag' AND ev.scope_id = t.id
            ORDER BY ev.scope_type, ev.scope_id, ev.var_name
        """)
        for row in rows:
            t, name = _parse_var_key(row['var_name'])
            if target_filter and t != target_filter and t != 'default':
                continue
            if row['scope_type'] == 'global':
                scope = 'global'
            elif row['scope_type'] == 'project':
                scope = row['project_slug'] or f"project:{row['scope_id']}"
            elif row['scope_type'] == 'tag':
                scope = f"tag:{row['tag_name'] or row['scope_id']}"
            else:
                scope = row['scope_type']
            target_suffix = f" ({t})" if t != 'default' else ""
            print(f"{scope}  {name}{target_suffix}={row['var_value'] or ''}")

    # ------------------------------------------------------------------
    # var export
    # ------------------------------------------------------------------

    def var_export(self, args) -> int:
        if not getattr(args, 'project', None):
            print("error: project slug required for export", file=sys.stderr)
            return 1

        project = self._get_project(args.project)
        target = getattr(args, 'target', None) or 'default'
        fmt = getattr(args, 'format', 'shell')
        profile = getattr(args, 'profile', 'default') or 'default'

        # Collect env vars with scope resolution (lowest priority first, overridden up)
        merged = {}

        def apply_rows(rows):
            for row in rows:
                t, name = _parse_var_key(row['var_name'])
                if t == 'default':
                    merged[name] = row['var_value']

        def apply_rows_target(rows):
            for row in rows:
                t, name = _parse_var_key(row['var_name'])
                if t == target:
                    merged[name] = row['var_value']

        # 5. global
        g_rows = self.query_all("""
            SELECT var_name, var_value FROM environment_variables
            WHERE scope_type = 'global' AND scope_id IS NULL
        """)
        apply_rows(g_rows)
        if target != 'default':
            apply_rows_target(g_rows)

        # 3. tags
        for tag_id in self._project_tag_ids(project['id']):
            t_rows = self.query_all("""
                SELECT var_name, var_value FROM environment_variables
                WHERE scope_type = 'tag' AND scope_id = ?
            """, (tag_id,))
            apply_rows(t_rows)
            if target != 'default':
                apply_rows_target(t_rows)

        # 2. project
        p_rows = self.query_all("""
            SELECT var_name, var_value FROM environment_variables
            WHERE scope_type = 'project' AND scope_id = ?
        """, (project['id'],))
        apply_rows(p_rows)
        # 1. project + target
        if target != 'default':
            apply_rows_target(p_rows)

        # Secrets
        if not getattr(args, 'no_secrets', False):
            try:
                for k, v in self._secrets_export(project['id'], profile).items():
                    merged[k] = v
            except SystemExit:
                pass

        if fmt == 'shell':
            for key, value in sorted(merged.items()):
                escaped = str(value or '').replace("'", "'\\''")
                print(f"export {key}='{escaped}'")
        elif fmt == 'dotenv':
            for key, value in sorted(merged.items()):
                print(f"{key}={value}")
        elif fmt == 'json':
            print(json.dumps(merged, indent=2, sort_keys=True))
        else:
            print(f"error: unknown format: {fmt}", file=sys.stderr)
            return 1
        return 0

    # ------------------------------------------------------------------
    # var unset
    # ------------------------------------------------------------------

    def var_unset(self, args) -> int:
        key = args.key
        target = getattr(args, 'target', None) or 'default'
        stored_name = _var_key(target, key)
        profile = getattr(args, 'profile', 'default') or 'default'

        if getattr(args, 'global_scope', False):
            self.execute("""
                DELETE FROM environment_variables
                WHERE scope_type = 'global' AND scope_id IS NULL AND var_name = ?
            """, (stored_name,))
            print(f"unset {key} [global]")
            return 0

        if getattr(args, 'tag', None):
            tag = self._get_tag(args.tag)
            self.execute("""
                DELETE FROM environment_variables
                WHERE scope_type = 'tag' AND scope_id = ? AND var_name = ?
            """, (tag['id'], stored_name))
            print(f"unset {key} [tag:{args.tag}]")
            return 0

        if not getattr(args, 'project', None):
            print("error: specify a project slug, --global, or --tag", file=sys.stderr)
            return 1

        project = self._get_project(args.project)

        if getattr(args, 'secret', False):
            found = self._secret_unset(project['id'], profile, key)
            if found:
                print(f"unset secret {key} [{args.project}/{profile}]")
            else:
                print(f"warning: secret {key} not found [{args.project}/{profile}]", file=sys.stderr)
            return 0

        self.execute("""
            DELETE FROM environment_variables
            WHERE scope_type = 'project' AND scope_id = ? AND var_name = ?
        """, (project['id'], stored_name))
        print(f"unset {key} [{args.project}]")
        return 0

    # ------------------------------------------------------------------
    # var tag
    # ------------------------------------------------------------------

    def tag_dispatch(self, args) -> int:
        sub = getattr(args, 'tag_subcommand', None)
        if sub == 'add':
            return self.tag_add(args)
        if sub == 'remove':
            return self.tag_remove(args)
        return self.tag_list(args)

    def tag_add(self, args) -> int:
        tag_id = self._get_or_create_tag(args.tag_name)
        for slug in args.projects:
            project = self._get_project(slug)
            self.execute("""
                INSERT OR IGNORE INTO project_tags (project_id, tag_id) VALUES (?, ?)
            """, (project['id'], tag_id))
            print(f"tagged {slug} as {args.tag_name}")
        return 0

    def tag_remove(self, args) -> int:
        tag = self._get_tag(args.tag_name)
        project = self._get_project(args.project)
        self.execute("""
            DELETE FROM project_tags WHERE project_id = ? AND tag_id = ?
        """, (project['id'], tag['id']))
        print(f"removed {args.project} from tag {args.tag_name}")
        return 0

    def tag_list(self, args) -> int:
        if getattr(args, 'project', None):
            project = self._get_project(args.project)
            rows = self.query_all("""
                SELECT t.name, t.description
                FROM tags t
                JOIN project_tags pt ON pt.tag_id = t.id
                WHERE pt.project_id = ?
                ORDER BY t.name
            """, (project['id'],))
            if not rows:
                print(f"no tags for {args.project}")
            else:
                for r in rows:
                    desc = f"  — {r['description']}" if r['description'] else ""
                    print(f"{r['name']}{desc}")
        else:
            rows = self.query_all("""
                SELECT t.name, t.description,
                       COUNT(pt.project_id) as project_count
                FROM tags t
                LEFT JOIN project_tags pt ON pt.tag_id = t.id
                GROUP BY t.id
                ORDER BY t.name
            """)
            if not rows:
                print("no tags defined")
            else:
                print(self.format_table(rows, ['name', 'project_count', 'description'], title="Tags"))
        return 0


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(cli):
    """Register var commands with the CLI instance."""
    cmd = VarCommands()

    var_parser = cli.register_command(
        'var', None, help_text='Unified variable management (env vars + secrets with scope hierarchy)'
    )
    subparsers = var_parser.add_subparsers(dest='var_subcommand', required=True)

    # --- var set ---
    p = subparsers.add_parser('set', help='Set a variable')
    p.add_argument('project', nargs='?', help='Project slug (omit with --global or --tag)')
    p.add_argument('key', help='Variable name')
    p.add_argument('value', help='Variable value')
    p.add_argument('--target', '-t', default=None, help='Deployment target (staging, production, …)')
    p.add_argument('--secret', action='store_true', help='Store as age-encrypted secret')
    p.add_argument('--keys', default=None, help='Comma-separated encryption key names (required with --secret)')
    p.add_argument('--global', dest='global_scope', action='store_true', help='Set at global scope')
    p.add_argument('--tag', default=None, help='Set at tag scope (creates tag if new)')
    p.add_argument('--profile', default='default', help='Secret profile (default: default)')
    cli.commands['var.set'] = cmd.var_set

    # --- var get ---
    p = subparsers.add_parser('get', help='Get a variable (with scope resolution)')
    p.add_argument('project', nargs='?', help='Project slug')
    p.add_argument('key', help='Variable name')
    p.add_argument('--target', '-t', default=None, help='Deployment target')
    p.add_argument('--secret', action='store_true', help='Look up in secrets')
    p.add_argument('--profile', default='default', help='Secret profile')
    p.add_argument('--global', dest='global_scope', action='store_true',
                   help='Look up in global scope only')
    cli.commands['var.get'] = cmd.var_get

    # --- var list ---
    p = subparsers.add_parser('list', aliases=['ls'], help='List variables annotated by scope')
    p.add_argument('project', nargs='?', help='Project slug (omit to show all)')
    p.add_argument('--target', '-t', default=None, help='Filter by deployment target')
    p.add_argument('--global', dest='global_scope', action='store_true', help='Global vars only')
    p.add_argument('--tag', default=None, help='Tag vars only')
    p.add_argument('--profile', default='default', help='Secret profile for listing secret keys')
    cli.commands['var.list'] = cmd.var_list
    cli.commands['var.ls'] = cmd.var_list

    # --- var export ---
    p = subparsers.add_parser('export', help='Export merged vars for a project (env + secrets)')
    p.add_argument('project', help='Project slug')
    p.add_argument('--target', '-t', default=None, help='Deployment target')
    p.add_argument('--format', default='shell', choices=['shell', 'dotenv', 'json'])
    p.add_argument('--no-secrets', action='store_true', help='Skip secrets (no age key needed)')
    p.add_argument('--profile', default='default', help='Secret profile')
    cli.commands['var.export'] = cmd.var_export

    # --- var unset ---
    p = subparsers.add_parser('unset', help='Delete a variable')
    p.add_argument('project', nargs='?', help='Project slug')
    p.add_argument('key', help='Variable name')
    p.add_argument('--target', '-t', default=None, help='Deployment target')
    p.add_argument('--global', dest='global_scope', action='store_true')
    p.add_argument('--tag', default=None, help='Tag scope')
    p.add_argument('--secret', action='store_true', help='Delete from secrets')
    p.add_argument('--profile', default='default', help='Secret profile')
    cli.commands['var.unset'] = cmd.var_unset

    # --- var tag ---
    tag_parser = subparsers.add_parser('tag', help='Manage project tag groups')
    tag_sub = tag_parser.add_subparsers(dest='tag_subcommand', required=True)
    cli.commands['var.tag'] = cmd.tag_dispatch

    p = tag_sub.add_parser('add', help='Add project(s) to a tag group (creates tag if new)')
    p.add_argument('tag_name', help='Tag name')
    p.add_argument('projects', nargs='+', help='Project slug(s)')

    p = tag_sub.add_parser('remove', help='Remove a project from a tag group')
    p.add_argument('tag_name', help='Tag name')
    p.add_argument('project', help='Project slug')

    p = tag_sub.add_parser('list', aliases=['ls'], help='List tags (optionally for one project)')
    p.add_argument('project', nargs='?', help='Project slug (optional)')
