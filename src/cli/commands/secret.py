#!/usr/bin/env python3
"""
Individual secret management - each secret is stored as its own encrypted blob
No YAML bundles - direct key-value storage with metadata
"""
import sys
import os
import json
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from repositories import BaseRepository, ProjectRepository
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class SecretV2Commands(Command):
    """Individual secret management command handlers"""

    def __init__(self):
        super().__init__()
        self.project_repo = ProjectRepository()
        self.secret_repo = BaseRepository()

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
                logger.info("List available keys with: templedb key list")
                sys.exit(1)

            if not key['is_active']:
                logger.warning(f"Key '{key_name}' is disabled")
                continue

            recipients.append(key['recipient'])
            key_ids.append(key['id'])

        return recipients, key_ids

    def _age_encrypt_multi(self, plaintext: bytes, recipients: list) -> bytes:
        """Encrypt data using age with multiple recipients"""
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
        """Decrypt age-encrypted data using any available key"""
        key_file_candidates = [
            os.environ.get("TEMPLEDB_AGE_KEY_FILE"),
            os.environ.get("SOPS_AGE_KEY_FILE"),
            os.path.expanduser("~/.config/sops/age/keys.txt"),
            os.path.expanduser("~/.age/key.txt"),
            os.path.expanduser("~/.config/age-plugin-yubikey/identities.txt")
        ]

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

    def _audit_log(self, action: str, slug: str, secret_name: str, metadata: dict = None):
        """Log audit event"""
        self.secret_repo.execute("""
            INSERT INTO audit_log (ts, actor, action, project_slug, profile, details)
            VALUES (datetime('now'), ?, ?, ?, ?, ?)
        """, (
            os.environ.get('USER', 'unknown'),
            action,
            slug,
            secret_name,
            json.dumps(metadata or {})
        ))

    def secret_set(self, args) -> int:
        """Set an individual secret"""
        slug = args.slug
        secret_name = args.name
        secret_value = args.value
        profile = args.profile
        key_names = args.keys.split(',') if args.keys else None

        project_id = self._get_project_id(slug)

        # Get recipients
        if not key_names:
            logger.error("No encryption keys specified")
            logger.info("Use --keys to specify comma-separated key names")
            logger.info("List available keys with: templedb key list")
            return 1

        recipients, key_ids = self._get_recipients_from_keys(key_names)

        if not recipients:
            logger.error("No valid recipients found")
            return 1

        # Encrypt the value
        plaintext = secret_value.encode('utf-8')
        encrypted = self._age_encrypt_multi(plaintext, recipients)

        # Check if secret already exists for this project
        existing = self.secret_repo.query_one("""
            SELECT sb.id, sb.secret_name
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND sb.secret_name = ? AND psb.profile = ?
        """, (project_id, secret_name, profile))

        if existing:
            # Update existing secret
            self.secret_repo.execute("""
                UPDATE secret_blobs
                SET secret_blob = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (encrypted, existing['id']))

            # Update key assignments
            self.secret_repo.execute("""
                DELETE FROM secret_key_assignments WHERE secret_blob_id = ?
            """, (existing['id'],))

            for key_id in key_ids:
                self.secret_repo.execute("""
                    INSERT INTO secret_key_assignments (secret_blob_id, key_id, added_by)
                    VALUES (?, ?, ?)
                """, (existing['id'], key_id, os.environ.get('USER', 'unknown')))

            logger.info(f"✓ Updated secret '{secret_name}' for {slug}")
        else:
            # Create new secret blob
            self.secret_repo.execute("""
                INSERT INTO secret_blobs (profile, secret_name, secret_blob, content_type)
                VALUES (?, ?, ?, ?)
            """, (profile, secret_name, encrypted, 'application/text'))

            secret_blob_id = self.secret_repo.query_one("""
                SELECT id FROM secret_blobs WHERE id = last_insert_rowid()
            """)['id']

            # Link to project
            self.secret_repo.execute("""
                INSERT INTO project_secret_blobs (project_id, secret_blob_id, profile)
                VALUES (?, ?, ?)
            """, (project_id, secret_blob_id, profile))

            # Record key assignments
            for key_id in key_ids:
                self.secret_repo.execute("""
                    INSERT INTO secret_key_assignments (secret_blob_id, key_id, added_by)
                    VALUES (?, ?, ?)
                """, (secret_blob_id, key_id, os.environ.get('USER', 'unknown')))

            logger.info(f"✓ Set secret '{secret_name}' for {slug}")

        self._audit_log('set-secret', slug, secret_name, {'keys': key_names})
        return 0

    def secret_get(self, args) -> int:
        """Get an individual secret value"""
        slug = args.slug
        secret_name = args.name
        profile = args.profile
        show_metadata = args.metadata

        project_id = self._get_project_id(slug)

        # Get secret blob
        row = self.secret_repo.query_one("""
            SELECT sb.id, sb.secret_blob, sb.created_at, sb.updated_at,
                   sb.content_type
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND sb.secret_name = ? AND psb.profile = ?
        """, (project_id, secret_name, profile))

        if not row:
            logger.error(f"Secret '{secret_name}' not found for {slug}")
            logger.info(f"List secrets with: templedb secret list {slug}")
            return 1

        # Decrypt
        decrypted = self._age_decrypt(row['secret_blob'])
        value = decrypted.decode('utf-8')

        if show_metadata:
            # Show metadata
            print(f"Secret: {secret_name}")
            print(f"Project: {slug}")
            print(f"Profile: {profile}")
            print(f"Created: {row['created_at']}")
            print(f"Updated: {row['updated_at']}")
            print(f"Content-Type: {row['content_type']}")
            print(f"\nValue:")
            print(value)
        else:
            # Just print the value
            print(value)

        self._audit_log('get-secret', slug, secret_name, {})
        return 0

    def secret_list(self, args) -> int:
        """List all secrets for a project"""
        slug = args.slug
        profile = args.profile
        show_values = args.values

        project_id = self._get_project_id(slug)

        # Get all secrets for this project
        secrets = self.secret_repo.query_all("""
            SELECT sb.id, sb.secret_name, sb.created_at, sb.updated_at,
                   sb.content_type, psb.secret_blob_id,
                   (SELECT COUNT(*) FROM project_secret_blobs psb2
                    WHERE psb2.secret_blob_id = sb.id) as share_count
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND psb.profile = ?
            ORDER BY sb.secret_name
        """, (project_id, profile))

        if not secrets:
            logger.info(f"No secrets found for {slug} (profile: {profile})")
            logger.info(f"Set a secret with: templedb secret set {slug} <name> <value> --keys <key>")
            return 0

        print(f"\nSecrets for {slug} (profile: {profile}):")
        print("=" * 60)

        for secret in secrets:
            shared = " (shared)" if secret['share_count'] > 1 else ""
            print(f"\n{secret['secret_name']}{shared}")
            print(f"  Created: {secret['created_at']}")
            print(f"  Updated: {secret['updated_at']}")

            if show_values:
                # Decrypt and show value
                row = self.secret_repo.query_one("""
                    SELECT secret_blob FROM secret_blobs WHERE id = ?
                """, (secret['id'],))

                try:
                    decrypted = self._age_decrypt(row['secret_blob'])
                    value = decrypted.decode('utf-8')
                    print(f"  Value: {value}")
                except Exception as e:
                    print(f"  Value: (decryption failed)")

        print()
        return 0

    def secret_delete(self, args) -> int:
        """Delete a secret from a project"""
        slug = args.slug
        secret_name = args.name
        profile = args.profile

        project_id = self._get_project_id(slug)

        # Find the secret
        row = self.secret_repo.query_one("""
            SELECT psb.secret_blob_id, sb.secret_name,
                   (SELECT COUNT(*) FROM project_secret_blobs psb2
                    WHERE psb2.secret_blob_id = psb.secret_blob_id) as share_count
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND sb.secret_name = ? AND psb.profile = ?
        """, (project_id, secret_name, profile))

        if not row:
            logger.error(f"Secret '{secret_name}' not found for {slug}")
            return 1

        # Remove from join table
        self.secret_repo.execute("""
            DELETE FROM project_secret_blobs
            WHERE project_id = ? AND secret_blob_id = ? AND profile = ?
        """, (project_id, row['secret_blob_id'], profile))

        # If no other projects reference this secret, delete the blob
        if row['share_count'] == 1:
            self.secret_repo.execute("""
                DELETE FROM secret_blobs WHERE id = ?
            """, (row['secret_blob_id'],))
            logger.info(f"✓ Deleted secret '{secret_name}' from {slug}")
        else:
            logger.info(f"✓ Removed secret '{secret_name}' from {slug}")
            logger.info(f"  Secret is still shared with {row['share_count'] - 1} other project(s)")

        self._audit_log('delete-secret', slug, secret_name, {})
        return 0

    def secret_share_key(self, args) -> int:
        """Share an individual secret from one project to another"""
        source_slug = args.source_slug
        target_slug = args.target_slug
        secret_name = args.name
        profile = args.profile

        source_project_id = self._get_project_id(source_slug)
        target_project_id = self._get_project_id(target_slug)

        # Find the secret in source project
        secret = self.secret_repo.query_one("""
            SELECT psb.secret_blob_id
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND sb.secret_name = ? AND psb.profile = ?
        """, (source_project_id, secret_name, profile))

        if not secret:
            logger.error(f"Secret '{secret_name}' not found in {source_slug}")
            logger.info(f"List secrets with: templedb secret list {source_slug}")
            return 1

        # Check if already shared
        existing = self.secret_repo.query_one("""
            SELECT 1 FROM project_secret_blobs
            WHERE project_id = ? AND secret_blob_id = ? AND profile = ?
        """, (target_project_id, secret['secret_blob_id'], profile))

        if existing:
            logger.warning(f"Secret '{secret_name}' already shared with {target_slug}")
            return 0

        # Share by creating join table entry
        self.secret_repo.execute("""
            INSERT INTO project_secret_blobs (project_id, secret_blob_id, profile)
            VALUES (?, ?, ?)
        """, (target_project_id, secret['secret_blob_id'], profile))

        logger.info(f"✓ Shared '{secret_name}' from {source_slug} to {target_slug}")
        logger.info(f"  Both projects now have access to the same secret")

        self._audit_log('share-secret', f"{source_slug}→{target_slug}", secret_name, {})
        return 0

    def secret_export(self, args) -> int:
        """Export secrets in various formats"""
        slug = args.slug
        profile = args.profile
        fmt = args.format

        project_id = self._get_project_id(slug)

        # Get all individual secrets for this project
        secrets = self.secret_repo.query_all("""
            SELECT sb.id, sb.secret_name, sb.secret_blob
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND psb.profile = ?
              AND sb.content_type = 'application/text'
            ORDER BY sb.secret_name
        """, (project_id, profile))

        if not secrets:
            # Return empty structure based on format
            if fmt == 'yaml':
                print("{}")
            elif fmt == 'json':
                print("{}")
            elif fmt in ['dotenv', 'shell']:
                pass  # Empty output
            return 0

        # Decrypt all secrets
        env_vars = {}
        for secret in secrets:
            try:
                decrypted = self._age_decrypt(secret['secret_blob'])
                value = decrypted.decode('utf-8')
                env_vars[secret['secret_name']] = value
            except Exception as e:
                logger.warning(f"Failed to decrypt {secret['secret_name']}: {e}")
                continue

        # Format output
        if fmt == 'yaml':
            try:
                import yaml
                print(yaml.safe_dump(env_vars, sort_keys=True))
            except ImportError:
                logger.error("PyYAML not installed. Install with: pip install pyyaml")
                return 1
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
            logger.error(f"Unknown format: {fmt}")
            logger.info("Supported formats: yaml, json, dotenv, shell")
            return 1

        return 0

    def secret_migrate(self, args) -> int:
        """Migrate YAML-based secrets to individual secrets"""
        try:
            import yaml
        except ImportError:
            logger.error("PyYAML not installed. Install with: pip install pyyaml")
            return 1

        slug = args.slug
        profile = args.profile
        key_names = args.keys.split(',') if args.keys else None

        project_id = self._get_project_id(slug)

        # Get encryption keys
        if not key_names:
            logger.error("No encryption keys specified")
            logger.info("Use --keys to specify comma-separated key names")
            logger.info("List available keys with: templedb key list")
            return 1

        recipients, key_ids = self._get_recipients_from_keys(key_names)

        if not recipients:
            logger.error("No valid recipients found")
            return 1

        # Find YAML-based secret blob
        yaml_secret = self.secret_repo.query_one("""
            SELECT sb.id, sb.secret_blob, sb.secret_name
            FROM project_secret_blobs psb
            JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
            WHERE psb.project_id = ? AND psb.profile = ?
              AND sb.content_type = 'application/x-age+yaml'
        """, (project_id, profile))

        if not yaml_secret:
            logger.error(f"No YAML-based secrets found for {slug} (profile: {profile})")
            logger.info("Nothing to migrate")
            return 0

        logger.info(f"Found YAML secret blob: {yaml_secret['secret_name']}")

        # Decrypt YAML
        try:
            decrypted = self._age_decrypt(yaml_secret['secret_blob'])
            doc = yaml.safe_load(decrypted)
        except Exception as e:
            logger.error(f"Failed to decrypt YAML secret: {e}")
            return 1

        env_vars = doc.get('env', {})

        if not env_vars:
            logger.warning("No secrets found in 'env' section of YAML")
            return 0

        logger.info(f"Found {len(env_vars)} secrets to migrate:")
        for key in env_vars.keys():
            logger.info(f"  - {key}")

        # Migrate each secret
        migrated_count = 0
        for secret_name, secret_value in env_vars.items():
            logger.info(f"Migrating {secret_name}...")

            # Encrypt as individual secret
            plaintext = str(secret_value).encode('utf-8')
            encrypted = self._age_encrypt_multi(plaintext, recipients)

            # Check if already exists
            existing = self.secret_repo.query_one("""
                SELECT sb.id
                FROM project_secret_blobs psb
                JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
                WHERE psb.project_id = ? AND sb.secret_name = ? AND psb.profile = ?
                  AND sb.content_type = 'application/text'
            """, (project_id, secret_name, profile))

            if existing:
                logger.warning(f"  Secret '{secret_name}' already exists, skipping")
                continue

            # Create new individual secret blob
            self.secret_repo.execute("""
                INSERT INTO secret_blobs (profile, secret_name, secret_blob, content_type)
                VALUES (?, ?, ?, ?)
            """, (profile, secret_name, encrypted, 'application/text'))

            secret_blob_id = self.secret_repo.query_one("""
                SELECT id FROM secret_blobs WHERE id = last_insert_rowid()
            """)['id']

            # Link to project
            self.secret_repo.execute("""
                INSERT INTO project_secret_blobs (project_id, secret_blob_id, profile)
                VALUES (?, ?, ?)
            """, (project_id, secret_blob_id, profile))

            # Record key assignments
            for key_id in key_ids:
                self.secret_repo.execute("""
                    INSERT INTO secret_key_assignments (secret_blob_id, key_id, added_by)
                    VALUES (?, ?, ?)
                """, (secret_blob_id, key_id, os.environ.get('USER', 'unknown')))

            migrated_count += 1

        # Delete old YAML blob
        logger.info(f"\n✓ Migrated {migrated_count} secrets")
        logger.info("Deleting old YAML blob...")

        self.secret_repo.execute("""
            DELETE FROM project_secret_blobs
            WHERE project_id = ? AND secret_blob_id = ? AND profile = ?
        """, (project_id, yaml_secret['id'], profile))

        self.secret_repo.execute("""
            DELETE FROM secret_blobs WHERE id = ?
        """, (yaml_secret['id'],))

        logger.info(f"✓ Migration complete for {slug}")
        self._audit_log('migrate-secrets', slug, f"migrated_{migrated_count}_secrets", {})
        return 0


def register(cli):
    """Register individual secret commands"""
    cmd = SecretV2Commands()

    secret_parser = cli.register_command('secret', None, help_text='Manage individual encrypted secrets')
    subparsers = secret_parser.add_subparsers(dest='secret_subcommand', required=True)

    # secret set
    set_parser = subparsers.add_parser('set', help='Set an individual secret')
    set_parser.add_argument('slug', help='Project slug')
    set_parser.add_argument('name', help='Secret name (e.g., OPENROUTER_API_KEY)')
    set_parser.add_argument('value', help='Secret value')
    set_parser.add_argument('--profile', default='default', help='Secret profile')
    set_parser.add_argument('--keys', required=True,
                           help='Comma-separated list of encryption key names')
    cli.commands['secret.set'] = cmd.secret_set

    # secret get
    get_parser = subparsers.add_parser('get', help='Get an individual secret value')
    get_parser.add_argument('slug', help='Project slug')
    get_parser.add_argument('name', help='Secret name')
    get_parser.add_argument('--profile', default='default', help='Secret profile')
    get_parser.add_argument('--metadata', action='store_true',
                           help='Show metadata along with value')
    cli.commands['secret.get'] = cmd.secret_get

    # secret list
    list_parser = subparsers.add_parser('list', help='List all secrets for a project')
    list_parser.add_argument('slug', help='Project slug')
    list_parser.add_argument('--profile', default='default', help='Secret profile')
    list_parser.add_argument('--values', action='store_true',
                            help='Show decrypted values (use with caution)')
    cli.commands['secret.list'] = cmd.secret_list

    # secret delete
    delete_parser = subparsers.add_parser('delete', help='Delete a secret from a project')
    delete_parser.add_argument('slug', help='Project slug')
    delete_parser.add_argument('name', help='Secret name')
    delete_parser.add_argument('--profile', default='default', help='Secret profile')
    cli.commands['secret.delete'] = cmd.secret_delete

    # secret share-key
    share_parser = subparsers.add_parser('share-key',
                                        help='Share an individual secret with another project')
    share_parser.add_argument('source_slug', help='Source project slug (owner of secret)')
    share_parser.add_argument('target_slug', help='Target project slug (will gain access)')
    share_parser.add_argument('name', help='Secret name to share')
    share_parser.add_argument('--profile', default='default', help='Secret profile')
    cli.commands['secret.share-key'] = cmd.secret_share_key

    # secret export
    export_parser = subparsers.add_parser('export', help='Export secrets in various formats')
    export_parser.add_argument('slug', help='Project slug')
    export_parser.add_argument('--profile', default='default', help='Secret profile')
    export_parser.add_argument('--format', default='yaml',
                              choices=['shell', 'yaml', 'json', 'dotenv'],
                              help='Output format (default: yaml for backward compatibility)')
    cli.commands['secret.export'] = cmd.secret_export

    # secret migrate
    migrate_parser = subparsers.add_parser('migrate',
                                          help='Migrate YAML-based secrets to individual secrets')
    migrate_parser.add_argument('slug', help='Project slug')
    migrate_parser.add_argument('--profile', default='default', help='Secret profile')
    migrate_parser.add_argument('--keys', required=True,
                               help='Comma-separated list of encryption key names')
    cli.commands['secret.migrate'] = cmd.secret_migrate
