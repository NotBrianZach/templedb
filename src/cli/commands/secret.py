#!/usr/bin/env python3
"""
Secret management commands using age encryption
"""
import sys
import os
import json
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from db_utils import query_one, execute, query_all
from cli.core import Command
import yaml


class SecretCommands(Command):
    """Secret management command handlers"""

    def _age_encrypt(self, plaintext: bytes, age_recipient: str) -> bytes:
        """Encrypt data using age with the given recipient public key."""
        try:
            proc = subprocess.run(
                ["age", "-r", age_recipient, "-a"],  # -a for ASCII armor
                input=plaintext,
                capture_output=True,
                check=True,
            )
            return proc.stdout
        except FileNotFoundError:
            print("error: age not found on PATH", file=sys.stderr)
            print("Install age: https://github.com/FiloSottile/age/releases", file=sys.stderr)
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8", errors="replace")
            print(f"error: age encryption failed: {err.strip()}", file=sys.stderr)
            sys.exit(1)

    def _age_decrypt(self, encrypted: bytes) -> bytes:
        """Decrypt age-encrypted data using age key file."""
        # Check for key file in environment or default location
        key_file = os.environ.get("TEMPLEDB_AGE_KEY_FILE") or \
                   os.environ.get("SOPS_AGE_KEY_FILE") or \
                   os.path.expanduser("~/.config/sops/age/keys.txt")

        if not os.path.exists(key_file):
            print(f"error: age key file not found: {key_file}", file=sys.stderr)
            print("\nGenerate a key with:", file=sys.stderr)
            print("  mkdir -p ~/.config/sops/age", file=sys.stderr)
            print("  age-keygen -o ~/.config/sops/age/keys.txt", file=sys.stderr)
            print("\nThen set environment variable:", file=sys.stderr)
            print("  export TEMPLEDB_AGE_KEY_FILE=~/.config/sops/age/keys.txt", file=sys.stderr)
            sys.exit(1)

        try:
            proc = subprocess.run(
                ["age", "-d", "-i", key_file],
                input=encrypted,
                capture_output=True,
                check=True,
            )
            return proc.stdout
        except FileNotFoundError:
            print("error: age not found on PATH", file=sys.stderr)
            print("Install age: https://github.com/FiloSottile/age/releases", file=sys.stderr)
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8", errors="replace")
            print(f"error: age decryption failed: {err.strip()}", file=sys.stderr)
            print("\nMake sure you're using the correct age key.", file=sys.stderr)
            sys.exit(1)

    def _get_project_id(self, slug: str) -> int:
        """Get project ID from slug"""
        row = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
        if not row:
            print(f"error: project not found: {slug}", file=sys.stderr)
            sys.exit(1)
        return row['id']

    def _audit_log(self, action: str, slug: str, profile: str, metadata: dict = None):
        """Log audit event"""
        execute("""
            INSERT INTO audit_log (ts, actor, action, project_slug, profile, details)
            VALUES (datetime('now'), ?, ?, ?, ?, ?)
        """, (
            os.environ.get('USER', 'unknown'),
            action,
            slug,
            profile,
            json.dumps(metadata or {})
        ))

    def secret_init(self, args) -> int:
        """Initialize secrets for a project"""
        slug = args.slug
        profile = args.profile
        age_recipient = args.age_recipient

        project_id = self._get_project_id(slug)

        # Create empty secret document
        empty_doc = {"env": {}, "meta": {"created_at": "now"}}
        plaintext_yaml = yaml.safe_dump(empty_doc, sort_keys=True).encode("utf-8")

        # Encrypt with age
        encrypted = self._age_encrypt(plaintext_yaml, age_recipient)

        # Store in database
        execute("""
            INSERT INTO secret_blobs (project_id, profile, secret_name, secret_blob, content_type)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id, profile) DO UPDATE SET
                secret_blob = excluded.secret_blob,
                updated_at = datetime('now')
        """, (project_id, profile, 'secrets', encrypted, 'application/x-age+yaml'))

        self._audit_log('init-secret', slug, profile, {'content_type': 'application/x-age+yaml'})
        print(f"Initialized secrets for {slug} (profile: {profile})")
        return 0

    def secret_edit(self, args) -> int:
        """Edit secrets for a project"""
        slug = args.slug
        profile = args.profile

        project_id = self._get_project_id(slug)

        # Get existing secret blob
        row = query_one("""
            SELECT secret_blob FROM secret_blobs
            WHERE project_id = ? AND profile = ?
        """, (project_id, profile))

        if not row:
            print(f"error: no secrets found for {slug} (profile: {profile})", file=sys.stderr)
            print(f"Run: templedb secret init {slug} --age-recipient <key>", file=sys.stderr)
            sys.exit(1)

        # Decrypt
        decrypted = self._age_decrypt(row['secret_blob'])
        initial_text = decrypted.decode('utf-8')

        # Edit in editor
        editor = os.environ.get('EDITOR', 'vi')
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(initial_text)
            temp_path = f.name

        try:
            subprocess.run([editor, temp_path], check=True)

            # Read edited content
            with open(temp_path, 'r') as f:
                edited_text = f.read()

            # Validate YAML
            try:
                yaml.safe_load(edited_text)
            except yaml.YAMLError as e:
                print(f"error: invalid YAML: {e}", file=sys.stderr)
                os.unlink(temp_path)
                sys.exit(1)

            # Get age recipient from existing encryption
            # For now, we need the recipient passed or stored somewhere
            # Let's get it from environment
            age_recipient = os.environ.get("TEMPLEDB_AGE_RECIPIENT") or \
                           os.environ.get("SOPS_AGE_RECIPIENT")

            if not age_recipient:
                # Try to get public key from key file
                key_file = os.environ.get("TEMPLEDB_AGE_KEY_FILE") or \
                          os.environ.get("SOPS_AGE_KEY_FILE") or \
                          os.path.expanduser("~/.config/sops/age/keys.txt")
                try:
                    proc = subprocess.run(
                        ["age-keygen", "-y", key_file],
                        capture_output=True,
                        check=True
                    )
                    age_recipient = proc.stdout.decode('utf-8').strip()
                except (subprocess.CalledProcessError, FileNotFoundError):
                    print("error: could not determine age recipient", file=sys.stderr)
                    print("Set TEMPLEDB_AGE_RECIPIENT environment variable", file=sys.stderr)
                    os.unlink(temp_path)
                    sys.exit(1)

            # Encrypt new content
            encrypted = self._age_encrypt(edited_text.encode('utf-8'), age_recipient)

            # Update database
            execute("""
                UPDATE secret_blobs
                SET secret_blob = ?, updated_at = datetime('now')
                WHERE project_id = ? AND profile = ?
            """, (encrypted, project_id, profile))

            self._audit_log('edit-secret', slug, profile, {})
            print(f"Updated secrets for {slug} (profile: {profile})")

        finally:
            os.unlink(temp_path)

        return 0

    def secret_export(self, args) -> int:
        """Export secrets in various formats"""
        slug = args.slug
        profile = args.profile
        fmt = args.format

        project_id = self._get_project_id(slug)

        # Get secret blob
        row = query_one("""
            SELECT secret_blob FROM secret_blobs
            WHERE project_id = ? AND profile = ?
        """, (project_id, profile))

        if not row:
            print(f"error: no secrets found for {slug} (profile: {profile})", file=sys.stderr)
            sys.exit(1)

        # Decrypt
        decrypted = self._age_decrypt(row['secret_blob'])
        doc = yaml.safe_load(decrypted)

        env_vars = doc.get('env', {})

        # Format output
        if fmt == 'yaml':
            print(yaml.safe_dump(env_vars, sort_keys=True))
        elif fmt == 'json':
            print(json.dumps(env_vars, indent=2, sort_keys=True))
        elif fmt == 'dotenv':
            for key, value in sorted(env_vars.items()):
                print(f"{key}={value}")
        elif fmt == 'shell':
            for key, value in sorted(env_vars.items()):
                # Escape single quotes in value
                escaped_value = str(value).replace("'", "'\\''")
                print(f"export {key}='{escaped_value}'")
        else:
            print(f"error: unknown format: {fmt}", file=sys.stderr)
            sys.exit(1)

        self._audit_log('export-secret', slug, profile, {'format': fmt})
        return 0

    def secret_print_raw(self, args) -> int:
        """Print raw encrypted blob (for debugging)"""
        slug = args.slug
        profile = args.profile

        project_id = self._get_project_id(slug)

        row = query_one("""
            SELECT secret_blob FROM secret_blobs
            WHERE project_id = ? AND profile = ?
        """, (project_id, profile))

        if not row:
            print(f"error: no secrets found for {slug} (profile: {profile})", file=sys.stderr)
            sys.exit(1)

        # Print raw encrypted blob
        print(row['secret_blob'].decode('utf-8'))
        return 0


def register(cli):
    """Register secret commands"""
    cmd = SecretCommands()

    secret_parser = cli.register_command('secret', None, help_text='Manage encrypted secrets')
    subparsers = secret_parser.add_subparsers(dest='secret_subcommand', required=True)

    # secret init
    init_parser = subparsers.add_parser('init', help='Initialize secrets for a project')
    init_parser.add_argument('slug', help='Project slug')
    init_parser.add_argument('--profile', default='default', help='Secret profile')
    init_parser.add_argument('--age-recipient', required=True, help='Age public key (age1...)')
    cli.commands['secret.init'] = cmd.secret_init

    # secret edit
    edit_parser = subparsers.add_parser('edit', help='Edit secrets in $EDITOR')
    edit_parser.add_argument('slug', help='Project slug')
    edit_parser.add_argument('--profile', default='default', help='Secret profile')
    cli.commands['secret.edit'] = cmd.secret_edit

    # secret export
    export_parser = subparsers.add_parser('export', help='Export secrets in various formats')
    export_parser.add_argument('slug', help='Project slug')
    export_parser.add_argument('--profile', default='default', help='Secret profile')
    export_parser.add_argument('--format', default='shell',
                              choices=['shell', 'yaml', 'json', 'dotenv'],
                              help='Output format')
    cli.commands['secret.export'] = cmd.secret_export

    # secret print-raw
    raw_parser = subparsers.add_parser('print-raw', help='Print raw encrypted blob')
    raw_parser.add_argument('slug', help='Project slug')
    raw_parser.add_argument('--profile', default='default', help='Secret profile')
    cli.commands['secret.print-raw'] = cmd.secret_print_raw
