#!/usr/bin/env python3
"""
Enhanced secret management with multi-recipient key support
Extension to secret.py for working with the encryption key registry
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

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class MultiKeySecretCommands(Command):
    """Multi-recipient secret management"""

    def __init__(self):
        super().__init__()
        self.project_repo = ProjectRepository()
        self.secret_repo = BaseRepository()

    def _get_project_id(self, slug: str) -> int:
        """Get project ID from slug"""
        project = self.project_repo.get_by_slug(slug)
        if not project:
            logger.error(f"Project not found: {slug}")
            sys.exit(1)
        return project['id']

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
        # Try multiple key file locations
        key_files = [
            os.environ.get("TEMPLEDB_AGE_KEY_FILE"),
            os.environ.get("SOPS_AGE_KEY_FILE"),
            os.path.expanduser("~/.config/sops/age/keys.txt"),
            os.path.expanduser("~/.age/key.txt")
        ]

        # Also check age-plugin-yubikey identity file
        yubikey_identity = os.path.expanduser("~/.config/age-plugin-yubikey/identities.txt")
        if os.path.exists(yubikey_identity):
            key_files.append(yubikey_identity)

        # Filter to only existing files
        available_key_files = [kf for kf in key_files if kf and os.path.exists(kf)]

        if not available_key_files:
            logger.error("No age key files found")
            logger.info("Tried locations:")
            for kf in key_files:
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
            INSERT INTO secret_blobs (project_id, profile, secret_name, secret_blob, content_type)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id, profile) DO UPDATE SET
                secret_blob = excluded.secret_blob,
                updated_at = datetime('now')
        """, (project_id, profile, 'secrets', encrypted, 'application/x-age+yaml'))

        secret_blob_id = self.secret_repo.query_one("""
            SELECT id FROM secret_blobs WHERE project_id = ? AND profile = ?
        """, (project_id, profile))['id']

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

        # Get secret blob
        secret = self.secret_repo.query_one("""
            SELECT id FROM secret_blobs
            WHERE project_id = ? AND profile = ?
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

        # Get secret blob
        secret = self.secret_repo.query_one("""
            SELECT id, secret_blob FROM secret_blobs
            WHERE project_id = ? AND profile = ?
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

        # Get secret blob
        secret = self.secret_repo.query_one("""
            SELECT id, secret_blob FROM secret_blobs
            WHERE project_id = ? AND profile = ?
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
    """Register multi-key secret commands"""
    cmd = MultiKeySecretCommands()

    # Get existing secret parser - assumes secret.register() was called first
    # Access via subparsers._name_parser_map (internal but stable API)
    if 'secret' not in cli.subparsers._name_parser_map:
        logger.error("Secret command not registered - cannot add multi-key subcommands")
        return

    secret_parser = cli.subparsers._name_parser_map['secret']

    # Get the subparsers action for the secret command
    subparsers = None
    for action in secret_parser._subparsers._group_actions:
        subparsers = action
        break

    if not subparsers:
        logger.error("Secret command has no subparsers")
        return

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

    # secret remove-key
    remove_key_parser = subparsers.add_parser('remove-key',
                                               help='Remove encryption key from secret (re-encrypt)')
    remove_key_parser.add_argument('slug', help='Project slug')
    remove_key_parser.add_argument('--key', required=True, help='Key name to remove')
    remove_key_parser.add_argument('--profile', default='default', help='Secret profile')
    cli.commands['secret.remove-key'] = cmd.secret_remove_key
