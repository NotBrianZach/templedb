#!/usr/bin/env python3
"""
Secret management commands using age encryption
Includes multi-recipient key management
"""
import sys
import os
import json
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from repositories import BaseRepository, ProjectRepository
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)

# Import yaml only when needed
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    logger.warning("PyYAML not installed - secret commands will not work")


class SecretCommands(Command):
    """Secret management command handlers"""

    def __init__(self):
        super().__init__()
        """Initialize with repositories"""
        self.project_repo = ProjectRepository()
        self.secret_repo = BaseRepository()  # Generic repository for secret-specific queries

    def _get_recipients_from_keys(self, key_names: list) -> tuple:
        """Get age recipients for given key names.
        Returns: (recipients_list, key_id_list)
        """
        recipients = []
        key_ids = []

        for key_name in key_names:
            key = self.secret_repo.query_one("""
                SELECT id, recipient, key_type, is_active
                FROM encryption_keys
                WHERE key_name = ?
            """, (key_name,))

            if not key:
                logger.error(f"Key not found: {key_name}")
                sys.exit(1)

            if not key['is_active']:
                logger.warning(f"Key '{key_name}' is disabled")
                continue

            recipients.append(key['recipient'])
            key_ids.append(key['id'])

        return recipients, key_ids

    def _age_encrypt(self, plaintext: bytes, age_recipient: str) -> bytes:
        """Encrypt data using age with the given recipient public key(s).

        Args:
            age_recipient: Single recipient or comma-separated list of recipients
        """
        # Support multiple recipients (comma-separated)
        recipients = [r.strip() for r in age_recipient.split(',')]

        # Build age command with multiple -r flags
        age_cmd = ["age"]
        for recipient in recipients:
            age_cmd.extend(["-r", recipient])
        age_cmd.append("-a")  # ASCII armor

        try:
            proc = subprocess.run(
                age_cmd,
                input=plaintext,
                capture_output=True,
                check=True,
            )
            return proc.stdout
        except FileNotFoundError:
            logger.error("age not found on PATH")
            logger.info("Install age: https://github.com/FiloSottile/age/releases")
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8", errors="replace")
            logger.error(f"age encryption failed: {err.strip()}")
            sys.exit(1)

    def _age_encrypt_multi(self, plaintext: bytes, recipients: list) -> bytes:
        """Encrypt data using age with multiple recipients (list of recipient strings)"""
        age_cmd = ["age"]
        for recipient in recipients:
            age_cmd.extend(["-r", recipient])
        age_cmd.append("-a")  # ASCII armor

        try:
            proc = subprocess.run(
                age_cmd,
                input=plaintext,
                capture_output=True,
                check=True,
            )
            return proc.stdout
        except FileNotFoundError:
            logger.error("age not found on PATH")
            logger.info("Install age: https://github.com/FiloSottile/age/releases")
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8", errors="replace")
            logger.error(f"age encryption failed: {err.strip()}")
            sys.exit(1)

    def _age_decrypt(self, encrypted: bytes) -> bytes:
        """Decrypt age-encrypted data using any available key."""
        # Collect all available identity files
        key_file_candidates = [
            os.environ.get("TEMPLEDB_AGE_KEY_FILE"),
            os.environ.get("SOPS_AGE_KEY_FILE"),
            os.path.expanduser("~/.config/sops/age/keys.txt"),
            os.path.expanduser("~/.age/key.txt"),
            os.path.expanduser("~/.config/age-plugin-yubikey/identities.txt")
        ]

        # Filter to only existing files
        available_key_files = [kf for kf in key_file_candidates if kf and os.path.exists(kf)]

        if not available_key_files:
            logger.error("No age key files found")
            logger.info("Tried locations:")
            for kf in key_file_candidates:
                if kf:
                    logger.info(f"  {kf}")
            logger.info("\nGenerate a key with:")
            logger.info("  age-keygen -o ~/.age/key.txt")
            logger.info("Or setup Yubikey:")
            logger.info("  age-plugin-yubikey --generate")
            sys.exit(1)

        # Build age command with ALL available identity files
        # age will try each identity until one works (any-of-N decryption)
        age_cmd = ["age", "-d"]
        for key_file in available_key_files:
            age_cmd.extend(["-i", key_file])

        try:
            proc = subprocess.run(
                age_cmd,
                input=encrypted,
                capture_output=True,
                check=True,
            )
            return proc.stdout
        except FileNotFoundError:
            logger.error("age not found on PATH")
            logger.info("Install age: https://github.com/FiloSottile/age/releases")
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8", errors="replace")
            logger.error(f"age decryption failed: {err.strip()}")
            logger.info(f"\nTried {len(available_key_files)} identity file(s):")
            for kf in available_key_files:
                logger.info(f"  - {kf}")
            logger.info("\nPossible reasons:")
            logger.info("  1. None of your keys can decrypt this secret")
            logger.info("  2. Yubikey not inserted or PIN incorrect")
            logger.info("  3. Secret was encrypted with different keys")
            sys.exit(1)

    def _get_project_id(self, slug: str) -> int:
        """Get project ID from slug"""
        project = self.project_repo.get_by_slug(slug)
        if not project:
            logger.error(f"Project not found: {slug}")
            sys.exit(1)
        return project['id']

    def _audit_log(self, action: str, slug: str, profile: str, metadata: dict = None):
        """Log audit event"""
        self.secret_repo.execute("""
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
        if not YAML_AVAILABLE:
            logger.error("PyYAML not installed. Install with: pip install pyyaml")
            return 1

        slug = args.slug
        profile = args.profile
        age_recipient = args.age_recipient

        project_id = self._get_project_id(slug)

        # Create empty secret document
        empty_doc = {"env": {}, "meta": {"created_at": "now"}}
        plaintext_yaml = yaml.safe_dump(empty_doc, sort_keys=True).encode("utf-8")

        # Encrypt with age
        encrypted = self._age_encrypt(plaintext_yaml, age_recipient)

        # Store in database using join table approach
        # First, insert the secret blob
        self.secret_repo.execute("""
            INSERT INTO secret_blobs (profile, secret_name, secret_blob, content_type)
            VALUES (?, ?, ?, ?)
        """, (profile, 'secrets', encrypted, 'application/x-age+yaml'))

        # Get the secret_blob_id (last inserted)
        blob_row = self.secret_repo.query_one("""
            SELECT id FROM secret_blobs WHERE id = last_insert_rowid()
        """)

        # Link to project via join table
        self.secret_repo.execute("""
            INSERT OR IGNORE INTO project_secret_blobs (project_id, secret_blob_id, profile)
            VALUES (?, ?, ?)
        """, (project_id, blob_row['id'], profile))

        self._audit_log('init-secret', slug, profile, {'content_type': 'application/x-age+yaml'})
        print(f"Initialized secrets for {slug} (profile: {profile})")
        return 0

    def secret_edit(self, args) -> int:
        """Edit secrets for a project"""
        if not YAML_AVAILABLE:
            logger.error("PyYAML not installed. Install with: pip install pyyaml")
            return 1

        slug = args.slug
        profile = args.profile

        project_id = self._get_project_id(slug)

        # Get existing secret blob via join table
        row = self.secret_repo.query_one("""
            SELECT sb.secret_blob, sb.id as secret_blob_id
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND psb.profile = ?
        """, (project_id, profile))

        if not row:
            logger.error(f"no secrets found for {slug} (profile: {profile})")
            logger.info(f"Run: templedb secret init {slug} --age-recipient <key>")
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
                logger.error(f"invalid YAML: {e}")
                logger.info("Fix the YAML syntax and try again")
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
                    logger.error("could not determine age recipient")
                    logger.info("Set TEMPLEDB_AGE_RECIPIENT environment variable")
                    os.unlink(temp_path)
                    sys.exit(1)

            # Encrypt new content
            encrypted = self._age_encrypt(edited_text.encode('utf-8'), age_recipient)

            # Update database using the secret_blob_id we got earlier
            self.secret_repo.execute("""
                UPDATE secret_blobs
                SET secret_blob = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (encrypted, row['secret_blob_id']))

            self._audit_log('edit-secret', slug, profile, {})
            print(f"Updated secrets for {slug} (profile: {profile})")

        finally:
            os.unlink(temp_path)

        return 0

    def secret_export(self, args) -> int:
        """Export secrets in various formats"""
        if not YAML_AVAILABLE:
            logger.error("PyYAML not installed. Install with: pip install pyyaml")
            return 1

        slug = args.slug
        profile = args.profile
        fmt = args.format

        project_id = self._get_project_id(slug)

        # Get secret blob via join table
        row = self.secret_repo.query_one("""
            SELECT sb.secret_blob
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND psb.profile = ?
        """, (project_id, profile))

        if not row:
            logger.error(f"no secrets found for {slug} (profile: {profile})")
            logger.info(f"Run: templedb secret init {slug} --age-recipient <key>")
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
            logger.error(f"unknown format: {fmt}")
            logger.info("Supported formats: yaml, json, env, shell")
            sys.exit(1)

        self._audit_log('export-secret', slug, profile, {'format': fmt})
        return 0

    def secret_print_raw(self, args) -> int:
        """Print raw encrypted blob (for debugging)"""
        slug = args.slug
        profile = args.profile

        project_id = self._get_project_id(slug)

        row = self.secret_repo.query_one("""
            SELECT sb.secret_blob
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND psb.profile = ?
        """, (project_id, profile))

        if not row:
            logger.error(f"no secrets found for {slug} (profile: {profile})")
            logger.info(f"Run: templedb secret init {slug} --age-recipient <key>")
            sys.exit(1)

        # Print raw encrypted blob
        print(row['secret_blob'].decode('utf-8'))
        return 0

    # Multi-key secret management commands

    def secret_init_multi(self, args) -> int:
        """Initialize secrets with multiple encryption keys"""
        if not YAML_AVAILABLE:
            logger.error("PyYAML not installed. Install with: pip install pyyaml")
            return 1

        slug = args.slug
        profile = args.profile
        key_names = args.keys.split(',')

        project_id = self._get_project_id(slug)

        # Get recipients from key registry
        recipients, key_ids = self._get_recipients_from_keys(key_names)

        if not recipients:
            logger.error("No valid recipients found")
            return 1

        logger.info(f"Encrypting with {len(recipients)} recipients:")
        for i, (key_name, recipient) in enumerate(zip(key_names, recipients), 1):
            logger.info(f"  {i}. {key_name} ({recipient[:20]}...)")

        # Create empty secret document
        empty_doc = {
            "env": {},
            "meta": {
                "created_at": "now",
                "encrypted_with": key_names,
                "recipient_count": len(recipients)
            }
        }
        plaintext_yaml = yaml.safe_dump(empty_doc, sort_keys=True).encode("utf-8")

        # Encrypt with multiple recipients
        encrypted = self._age_encrypt_multi(plaintext_yaml, recipients)

        # Store in database
        self.secret_repo.execute("""
            INSERT INTO secret_blobs (profile, secret_name, secret_blob, content_type)
            VALUES (?, ?, ?, ?)
        """, (profile, 'secrets', encrypted, 'application/x-age+yaml'))

        secret_blob_id = self.secret_repo.query_one("""
            SELECT id FROM secret_blobs WHERE id = last_insert_rowid()
        """)['id']

        # Link to project via join table
        self.secret_repo.execute("""
            INSERT OR IGNORE INTO project_secret_blobs (project_id, secret_blob_id, profile)
            VALUES (?, ?, ?)
        """, (project_id, secret_blob_id, profile))

        # Record key assignments
        for key_id in key_ids:
            self.secret_repo.execute("""
                INSERT INTO secret_key_assignments (secret_blob_id, key_id, added_by)
                VALUES (?, ?, ?)
                ON CONFLICT(secret_blob_id, key_id) DO NOTHING
            """, (secret_blob_id, key_id, os.environ.get('USER', 'unknown')))

        logger.info(f"✓ Initialized secrets for {slug} (profile: {profile})")
        logger.info(f"✓ Protected by {len(recipients)} encryption keys")
        return 0

    def secret_show_keys(self, args) -> int:
        """Show which keys encrypt a secret"""
        slug = args.slug
        profile = args.profile

        project_id = self._get_project_id(slug)

        # Get secret blob via join table
        secret = self.secret_repo.query_one("""
            SELECT sb.id
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND psb.profile = ?
        """, (project_id, profile))

        if not secret:
            logger.error(f"No secrets found for {slug} (profile: {profile})")
            return 1

        # Get assigned keys
        keys = self.secret_repo.query_all("""
            SELECT ek.key_name, ek.key_type, ek.location, ek.is_active,
                   ska.added_at, ska.added_by
            FROM secret_key_assignments ska
            JOIN encryption_keys ek ON ska.key_id = ek.id
            WHERE ska.secret_blob_id = ?
            ORDER BY ska.added_at
        """, (secret['id'],))

        print(f"\nSecret: {slug} (profile: {profile})")
        print(f"{'='*60}")

        if not keys:
            print("No encryption keys registered")
            print("This secret may have been created before key registry was enabled")
        else:
            print(f"\nEncrypted with {len(keys)} keys:\n")
            for i, key in enumerate(keys, 1):
                status = "✓ ACTIVE" if key['is_active'] else "✗ DISABLED"
                print(f"{i}. {key['key_name']} ({key['key_type']}) - {status}")
                print(f"   Location: {key['location'] or 'unknown'}")
                print(f"   Added: {key['added_at']} by {key['added_by']}")
                print()

        return 0

    def secret_add_key(self, args) -> int:
        """Add a new encryption key to an existing secret (re-encrypt)"""
        if not YAML_AVAILABLE:
            logger.error("PyYAML not installed. Install with: pip install pyyaml")
            return 1

        slug = args.slug
        profile = args.profile
        key_name = args.key

        project_id = self._get_project_id(slug)

        # Get the key
        key = self.secret_repo.query_one("""
            SELECT id, recipient FROM encryption_keys WHERE key_name = ?
        """, (key_name,))

        if not key:
            logger.error(f"Key not found: {key_name}")
            return 1

        # Get secret blob via join table
        secret = self.secret_repo.query_one("""
            SELECT sb.id, sb.secret_blob
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND psb.profile = ?
        """, (project_id, profile))

        if not secret:
            logger.error(f"No secrets found for {slug} (profile: {profile})")
            return 1

        # Decrypt with current keys
        logger.info("Decrypting secret...")
        decrypted = self._age_decrypt(secret['secret_blob'])

        # Get all current recipients plus new one
        current_keys = self.secret_repo.query_all("""
            SELECT ek.recipient
            FROM secret_key_assignments ska
            JOIN encryption_keys ek ON ska.key_id = ek.id
            WHERE ska.secret_blob_id = ? AND ek.is_active = 1
        """, (secret['id'],))

        recipients = [k['recipient'] for k in current_keys]
        recipients.append(key['recipient'])

        logger.info(f"Re-encrypting with {len(recipients)} recipients...")

        # Re-encrypt with all recipients
        encrypted = self._age_encrypt_multi(decrypted, recipients)

        # Update database
        self.secret_repo.execute("""
            UPDATE secret_blobs
            SET secret_blob = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (encrypted, secret['id']))

        # Add key assignment
        self.secret_repo.execute("""
            INSERT INTO secret_key_assignments (secret_blob_id, key_id, added_by)
            VALUES (?, ?, ?)
            ON CONFLICT(secret_blob_id, key_id) DO NOTHING
        """, (secret['id'], key['id'], os.environ.get('USER', 'unknown')))

        logger.info(f"✓ Added key '{key_name}' to {slug} (profile: {profile})")
        return 0

    def secret_share(self, args) -> int:
        """Share an existing secret with another project via join table"""
        source_slug = args.source_slug
        target_slug = args.target_slug
        profile = args.profile

        # Get project IDs
        source_project_id = self._get_project_id(source_slug)
        target_project_id = self._get_project_id(target_slug)

        # Get the secret blob from source project
        secret = self.secret_repo.query_one("""
            SELECT psb.secret_blob_id
            FROM project_secret_blobs psb
            WHERE psb.project_id = ? AND psb.profile = ?
        """, (source_project_id, profile))

        if not secret:
            logger.error(f"No secrets found for {source_slug} (profile: {profile})")
            logger.info(f"Run: templedb secret init {source_slug} --age-recipient <key>")
            return 1

        # Share with target project by creating join table entry
        try:
            self.secret_repo.execute("""
                INSERT INTO project_secret_blobs (project_id, secret_blob_id, profile)
                VALUES (?, ?, ?)
            """, (target_project_id, secret['secret_blob_id'], profile))

            logger.info(f"✓ Shared {source_slug} secrets with {target_slug} (profile: {profile})")
            logger.info(f"  Both projects now have access to the same encrypted secret blob")
            return 0
        except Exception as e:
            # Check if already shared
            existing = self.secret_repo.query_one("""
                SELECT 1 FROM project_secret_blobs
                WHERE project_id = ? AND secret_blob_id = ? AND profile = ?
            """, (target_project_id, secret['secret_blob_id'], profile))

            if existing:
                logger.warning(f"Secret already shared with {target_slug}")
                return 0
            else:
                logger.error(f"Failed to share secret: {e}")
                return 1

    def secret_remove_key(self, args) -> int:
        """Remove an encryption key from a secret (re-encrypt without it)"""
        if not YAML_AVAILABLE:
            logger.error("PyYAML not installed. Install with: pip install pyyaml")
            return 1

        slug = args.slug
        profile = args.profile
        key_name = args.key

        project_id = self._get_project_id(slug)

        # Get the key
        key = self.secret_repo.query_one("""
            SELECT id FROM encryption_keys WHERE key_name = ?
        """, (key_name,))

        if not key:
            logger.error(f"Key not found: {key_name}")
            return 1

        # Get secret blob via join table
        secret = self.secret_repo.query_one("""
            SELECT sb.id, sb.secret_blob
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND psb.profile = ?
        """, (project_id, profile))

        if not secret:
            logger.error(f"No secrets found for {slug} (profile: {profile})")
            return 1

        # Get remaining recipients (excluding the one to remove)
        remaining_keys = self.secret_repo.query_all("""
            SELECT ek.id, ek.recipient
            FROM secret_key_assignments ska
            JOIN encryption_keys ek ON ska.key_id = ek.id
            WHERE ska.secret_blob_id = ? AND ek.id != ? AND ek.is_active = 1
        """, (secret['id'], key['id']))

        if not remaining_keys:
            logger.error("Cannot remove last encryption key")
            logger.info("At least one key must remain to encrypt the secret")
            return 1

        # Decrypt with current keys
        logger.info("Decrypting secret...")
        decrypted = self._age_decrypt(secret['secret_blob'])

        recipients = [k['recipient'] for k in remaining_keys]
        logger.info(f"Re-encrypting with {len(recipients)} recipients (removing {key_name})...")

        # Re-encrypt without the removed key
        encrypted = self._age_encrypt_multi(decrypted, recipients)

        # Update database
        self.secret_repo.execute("""
            UPDATE secret_blobs
            SET secret_blob = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (encrypted, secret['id']))

        # Remove key assignment
        self.secret_repo.execute("""
            DELETE FROM secret_key_assignments
            WHERE secret_blob_id = ? AND key_id = ?
        """, (secret['id'], key['id']))

        logger.info(f"✓ Removed key '{key_name}' from {slug} (profile: {profile})")
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
    init_parser.add_argument('--age-recipient', required=True,
                            help='Age public key (age1...) or comma-separated list for multiple recipients')
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

    # Multi-key secret management commands

    # secret init-multi (multi-recipient initialization)
    init_multi_parser = subparsers.add_parser('init-multi',
                                               help='Initialize secrets with multiple encryption keys')
    init_multi_parser.add_argument('slug', help='Project slug')
    init_multi_parser.add_argument('--profile', default='default', help='Secret profile')
    init_multi_parser.add_argument('--keys', required=True,
                                    help='Comma-separated list of key names')
    cli.commands['secret.init-multi'] = cmd.secret_init_multi

    # secret show-keys
    show_keys_parser = subparsers.add_parser('show-keys',
                                              help='Show which keys encrypt a secret')
    show_keys_parser.add_argument('slug', help='Project slug')
    show_keys_parser.add_argument('--profile', default='default', help='Secret profile')
    cli.commands['secret.show-keys'] = cmd.secret_show_keys

    # secret add-key
    add_key_parser = subparsers.add_parser('add-key',
                                            help='Add encryption key to secret (re-encrypt)')
    add_key_parser.add_argument('slug', help='Project slug')
    add_key_parser.add_argument('--key', required=True, help='Key name to add')
    add_key_parser.add_argument('--profile', default='default', help='Secret profile')
    cli.commands['secret.add-key'] = cmd.secret_add_key

    # secret share
    share_parser = subparsers.add_parser('share',
                                          help='Share existing secret with another project')
    share_parser.add_argument('source_slug', help='Source project slug (owner of secret)')
    share_parser.add_argument('target_slug', help='Target project slug (will gain access)')
    share_parser.add_argument('--profile', default='default', help='Secret profile')
    cli.commands['secret.share'] = cmd.secret_share

    # secret remove-key
    remove_key_parser = subparsers.add_parser('remove-key',
                                               help='Remove encryption key from secret (re-encrypt)')
    remove_key_parser.add_argument('slug', help='Project slug')
    remove_key_parser.add_argument('--key', required=True, help='Key name to remove')
    remove_key_parser.add_argument('--profile', default='default', help='Secret profile')
    cli.commands['secret.remove-key'] = cmd.secret_remove_key
