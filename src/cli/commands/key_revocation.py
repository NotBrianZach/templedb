#!/usr/bin/env python3
"""
Quorum-based key revocation for TempleDB
Requires M-of-N keys to approve revocation of a key
"""
import sys
import os
import json
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from repositories import BaseRepository
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class KeyRevocationCommands(Command):
    """Quorum-based key revocation"""

    def __init__(self):
        super().__init__()
        self.repo = BaseRepository()

    def _age_decrypt(self, encrypted: bytes) -> bytes:
        """Decrypt age-encrypted data using any available key"""
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
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8", errors="replace")
            logger.error(f"age decryption failed: {err.strip()}")
            sys.exit(1)

    def _age_encrypt_multi(self, plaintext: bytes, recipients: list) -> bytes:
        """Encrypt data using age with multiple recipients"""
        age_cmd = ["age"]
        for recipient in recipients:
            age_cmd.extend(["-r", recipient])
        age_cmd.append("-a")

        try:
            proc = subprocess.run(
                age_cmd,
                input=plaintext,
                capture_output=True,
                check=True,
            )
            return proc.stdout
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8", errors="replace")
            logger.error(f"age encryption failed: {err.strip()}")
            sys.exit(1)

    def _create_revocation_challenge(self, key_to_revoke: str) -> dict:
        """Create a revocation challenge that requires 2-of-N keys to approve"""
        timestamp = datetime.now().isoformat()
        challenge = {
            "action": "revoke_key",
            "key_to_revoke": key_to_revoke,
            "timestamp": timestamp,
            "required_approvals": 2,
            "approvals": []
        }
        return challenge

    def _get_all_active_keys(self) -> list:
        """Get all active keys (including the one being revoked)"""
        keys = self.repo.query_all("""
            SELECT key_name, recipient, key_type
            FROM encryption_keys
            WHERE is_active = 1 AND is_revoked = 0
            ORDER BY key_name
        """, ())
        return keys

    def _prompt_for_key_approval(self, key: dict, challenge: dict) -> bool:
        """Prompt user to approve with a specific key"""
        logger.info(f"\nApproval needed from key: {key['key_name']} ({key['key_type']})")

        if key['key_type'] == 'yubikey':
            logger.info("  Please insert the Yubikey and enter PIN when prompted")
        else:
            logger.info("  Filesystem key will be used")

        # Encrypt challenge with this key's recipient
        challenge_json = json.dumps(challenge, sort_keys=True).encode('utf-8')

        try:
            # Try to encrypt with this key
            proc = subprocess.run(
                ["age", "-r", key['recipient'], "-a"],
                input=challenge_json,
                capture_output=True,
                check=True
            )
            encrypted = proc.stdout

            # Try to decrypt (proves they have the key)
            decrypted = self._age_decrypt(encrypted)

            if decrypted == challenge_json:
                logger.info(f"✓ Approval granted with {key['key_name']}")
                return True
            else:
                logger.error("✗ Decryption verification failed")
                return False

        except subprocess.CalledProcessError as e:
            logger.error(f"✗ Failed to approve with {key['key_name']}: {e}")
            return False

    def key_revoke(self, args) -> int:
        """Revoke a key with 2-of-N quorum approval"""
        key_name = args.name
        reason = args.reason or "Manual revocation"
        quorum = args.quorum or 2

        # Get the key to revoke
        key_to_revoke = self.repo.query_one("""
            SELECT id, key_name, key_type, is_revoked
            FROM encryption_keys
            WHERE key_name = ?
        """, (key_name,))

        if not key_to_revoke:
            logger.error(f"Key not found: {key_name}")
            return 1

        if key_to_revoke['is_revoked']:
            logger.error(f"Key already revoked: {key_name}")
            return 1

        # Get all active keys (including the one being revoked)
        all_keys = self._get_all_active_keys()

        if len(all_keys) < quorum:
            logger.error(f"Not enough active keys for {quorum}-of-{len(all_keys)} revocation")
            logger.error(f"Found {len(all_keys)} total active keys, need at least {quorum}")
            return 1

        logger.info(f"\n{'='*70}")
        logger.info(f"KEY REVOCATION PROCEDURE")
        logger.info(f"{'='*70}")
        logger.info(f"\nRevoking key: {key_name}")
        logger.info(f"Reason: {reason}")
        logger.info(f"\nThis action requires approval from {quorum} keys (including the one being revoked if available)")
        logger.info(f"Total active keys: {len(all_keys)}")

        # Create revocation challenge
        challenge = self._create_revocation_challenge(key_name)

        # Collect approvals
        approvals = []
        logger.info(f"\n{'='*70}")
        logger.info("COLLECTING APPROVALS")
        logger.info(f"{'='*70}\n")

        for i, key in enumerate(all_keys, 1):
            if len(approvals) >= quorum:
                break

            logger.info(f"\nApproval {len(approvals)+1}/{quorum}")
            logger.info(f"Key: {key['key_name']}")

            if key['key_name'] == key_name:
                logger.info("  (This is the key being revoked)")

            response = input(f"Use this key for approval? [y/n/skip]: ").strip().lower()

            if response == 'skip':
                logger.info("Skipping this key")
                continue
            elif response != 'y':
                logger.info("Not using this key")
                continue

            # Try to get approval with this key
            if self._prompt_for_key_approval(key, challenge):
                approvals.append({
                    "key_name": key['key_name'],
                    "key_type": key['key_type'],
                    "timestamp": datetime.now().isoformat()
                })
                challenge['approvals'] = approvals
            else:
                logger.warning("Failed to get approval with this key")

        # Check if we have enough approvals
        if len(approvals) < quorum:
            logger.error(f"\n✗ Insufficient approvals: {len(approvals)}/{quorum}")
            logger.error("Revocation aborted")
            return 1

        logger.info(f"\n✓ Received {len(approvals)}/{quorum} approvals")
        logger.info("\nApproving keys:")
        for approval in approvals:
            logger.info(f"  - {approval['key_name']} ({approval['key_type']})")

        # Final confirmation
        logger.info(f"\n{'='*70}")
        logger.info("FINAL CONFIRMATION")
        logger.info(f"{'='*70}")
        logger.info(f"\nKey to revoke: {key_name}")
        logger.info(f"Reason: {reason}")
        logger.info(f"\nThis will:")
        logger.info(f"  1. Mark key as REVOKED (cannot be undone)")
        logger.info(f"  2. Remove key from ALL secrets")
        logger.info(f"  3. Re-encrypt all secrets without this key")

        confirm = input("\nProceed with revocation? [yes/no]: ").strip().lower()
        if confirm != 'yes':
            logger.info("Revocation cancelled")
            return 1

        # Revoke the key in database
        logger.info(f"\nRevoking key {key_name}...")

        self.repo.execute("""
            UPDATE encryption_keys
            SET is_active = 0,
                is_revoked = 1,
                revoked_at = datetime('now'),
                revoked_by = ?,
                revocation_reason = ?
            WHERE id = ?
        """, (os.environ.get('USER', 'unknown'), reason, key_to_revoke['id']))

        # Log revocation with approval details
        self.repo.execute("""
            INSERT INTO encryption_key_audit (key_id, action, actor, details, success)
            VALUES (?, 'revoke', ?, ?, 1)
        """, (
            key_to_revoke['id'],
            os.environ.get('USER', 'unknown'),
            json.dumps({
                "reason": reason,
                "approvals": approvals,
                "quorum": quorum
            })
        ))

        # Get all secrets using this key
        secrets = self.repo.query_all("""
            SELECT DISTINCT sb.id, sb.project_id, sb.profile, sb.secret_blob, p.slug
            FROM secret_key_assignments ska
            JOIN secret_blobs sb ON ska.secret_blob_id = sb.id
            JOIN projects p ON sb.project_id = p.id
            WHERE ska.key_id = ?
        """, (key_to_revoke['id'],))

        if secrets:
            logger.info(f"\nRe-encrypting {len(secrets)} secrets without revoked key...")

            for secret in secrets:
                try:
                    # Get remaining recipients for this secret
                    remaining_keys = self.repo.query_all("""
                        SELECT ek.recipient
                        FROM secret_key_assignments ska
                        JOIN encryption_keys ek ON ska.key_id = ek.id
                        WHERE ska.secret_blob_id = ? AND ek.id != ? AND ek.is_active = 1
                    """, (secret['id'], key_to_revoke['id']))

                    if not remaining_keys:
                        logger.error(f"  ✗ No remaining keys for {secret['slug']} - SKIPPING")
                        continue

                    recipients = [k['recipient'] for k in remaining_keys]

                    # Decrypt with current keys (including revoked one)
                    decrypted = self._age_decrypt(secret['secret_blob'])

                    # Re-encrypt without revoked key
                    encrypted = self._age_encrypt_multi(decrypted, recipients)

                    # Update secret
                    self.repo.execute("""
                        UPDATE secret_blobs
                        SET secret_blob = ?, updated_at = datetime('now')
                        WHERE id = ?
                    """, (encrypted, secret['id']))

                    # Remove key assignment
                    self.repo.execute("""
                        DELETE FROM secret_key_assignments
                        WHERE secret_blob_id = ? AND key_id = ?
                    """, (secret['id'], key_to_revoke['id']))

                    logger.info(f"  ✓ Re-encrypted {secret['slug']} ({secret['profile']})")

                except Exception as e:
                    logger.error(f"  ✗ Failed to re-encrypt {secret['slug']}: {e}")

        logger.info(f"\n{'='*70}")
        logger.info(f"✓ KEY REVOCATION COMPLETE")
        logger.info(f"{'='*70}")
        logger.info(f"\nRevoked: {key_name}")
        logger.info(f"Reason: {reason}")
        logger.info(f"Approved by: {', '.join([a['key_name'] for a in approvals])}")
        logger.info(f"Secrets re-encrypted: {len(secrets)}")

        return 0

    def key_show_revoked(self, args) -> int:
        """Show all revoked keys"""
        revoked_keys = self.repo.query_all("""
            SELECT key_name, key_type, revoked_at, revoked_by, revocation_reason
            FROM encryption_keys
            WHERE is_revoked = 1
            ORDER BY revoked_at DESC
        """, ())

        if not revoked_keys:
            logger.info("No revoked keys")
            return 0

        print(f"\n{'='*70}")
        print(f"Revoked Keys ({len(revoked_keys)} total)")
        print(f"{'='*70}\n")

        for key in revoked_keys:
            print(f"{key['key_name']} ({key['key_type']})")
            print(f"  Revoked: {key['revoked_at']}")
            print(f"  By: {key['revoked_by']}")
            print(f"  Reason: {key['revocation_reason']}")
            print()

        return 0


def register(cli):
    """Register key revocation commands"""
    cmd = KeyRevocationCommands()

    # Get existing key parser - assumes key.register() was called first
    # Access via subparsers._name_parser_map (internal but stable API)
    if 'key' not in cli.subparsers._name_parser_map:
        logger.error("Key command not registered - cannot add revocation subcommands")
        return

    key_parser = cli.subparsers._name_parser_map['key']

    # Get the subparsers action for the key command
    subparsers = None
    for action in key_parser._subparsers._group_actions:
        subparsers = action
        break

    if not subparsers:
        logger.error("Key command has no subparsers")
        return

    # key revoke (with quorum)
    revoke_parser = subparsers.add_parser('revoke',
                                           help='Revoke a key with multi-key approval')
    revoke_parser.add_argument('name', help='Key name to revoke')
    revoke_parser.add_argument('--reason', help='Reason for revocation')
    revoke_parser.add_argument('--quorum', type=int, default=2,
                               help='Number of keys required for approval (default: 2)')
    cli.commands['key.revoke'] = cmd.key_revoke

    # key show-revoked
    show_revoked_parser = subparsers.add_parser('show-revoked',
                                                 help='Show all revoked keys')
    cli.commands['key.show-revoked'] = cmd.key_show_revoked
