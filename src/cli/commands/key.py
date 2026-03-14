#!/usr/bin/env python3
"""
Encryption key management commands for TempleDB
Manage Yubikeys, age keys, and multi-recipient encryption
"""
import sys
import os
import json
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from repositories import BaseRepository
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class KeyCommands(Command):
    """Encryption key management command handlers"""

    def __init__(self):
        super().__init__()
        self.repo = BaseRepository()

    def _get_yubikey_info(self):
        """Get information about connected Yubikey"""
        try:
            # Try to get Yubikey serial number
            proc = subprocess.run(
                ["ykman", "list", "--serials"],
                capture_output=True,
                check=True,
                text=True
            )
            serials = proc.stdout.strip().split('\n')
            if serials and serials[0]:
                return {"serial": serials[0]}
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Check if Yubikey is present via lsusb
        try:
            proc = subprocess.run(
                ["lsusb"],
                capture_output=True,
                check=True,
                text=True
            )
            if "yubi" in proc.stdout.lower():
                return {"present": True}
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return None

    def _get_age_plugin_yubikey_recipient(self):
        """Get age recipient for plugged-in Yubikey"""
        try:
            proc = subprocess.run(
                ["age-plugin-yubikey", "--identity"],
                capture_output=True,
                check=True,
                text=True
            )
            # Look for age1yubikey... line
            for line in proc.stdout.split('\n'):
                line = line.strip()
                if line.startswith('age1yubikey'):
                    return line
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        return None

    def _get_age_public_key(self, key_path: str) -> str:
        """Get age public key from private key file"""
        try:
            proc = subprocess.run(
                ["age-keygen", "-y", os.path.expanduser(key_path)],
                capture_output=True,
                check=True,
                text=True
            )
            return proc.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"Failed to get public key: {e}")
            return None

    def _test_key_decrypt(self, recipient: str, key_path: str = None) -> bool:
        """Test if a key can encrypt and decrypt"""
        test_message = b"templedb-key-test"

        try:
            # Encrypt
            age_cmd = ["age", "-r", recipient, "-a"]
            enc_proc = subprocess.run(
                age_cmd,
                input=test_message,
                capture_output=True,
                check=True
            )
            encrypted = enc_proc.stdout

            # Decrypt
            dec_cmd = ["age", "-d"]
            if key_path:
                dec_cmd.extend(["-i", os.path.expanduser(key_path)])

            dec_proc = subprocess.run(
                dec_cmd,
                input=encrypted,
                capture_output=True,
                check=True
            )

            return dec_proc.stdout == test_message

        except subprocess.CalledProcessError:
            return False

    def _audit_log(self, action: str, key_id: int = None, details: dict = None, success: bool = True):
        """Log key operation to audit table"""
        self.repo.execute("""
            INSERT INTO encryption_key_audit (key_id, action, actor, details, success)
            VALUES (?, ?, ?, ?, ?)
        """, (
            key_id,
            action,
            os.environ.get('USER', 'unknown'),
            json.dumps(details or {}),
            1 if success else 0
        ))

    def key_add(self, args) -> int:
        """Add a new encryption key to the registry"""
        key_name = args.name
        key_type = args.type

        # Get recipient based on type
        if key_type == 'yubikey':
            return self._add_yubikey(args)
        elif key_type == 'filesystem':
            return self._add_filesystem_key(args)
        else:
            logger.error(f"Unknown key type: {key_type}")
            return 1

    def _add_yubikey(self, args) -> int:
        """Add a Yubikey to the registry"""
        key_name = args.name
        location = args.location
        piv_slot = args.slot or '9a'

        # Check if Yubikey is connected
        yubikey_info = self._get_yubikey_info()
        if not yubikey_info:
            logger.error("No Yubikey detected. Please insert Yubikey and try again.")
            return 1

        # Get age recipient
        recipient = self._get_age_plugin_yubikey_recipient()
        if not recipient:
            logger.error("Could not get age recipient from Yubikey")
            logger.info("Run: age-plugin-yubikey --generate")
            return 1

        serial_number = yubikey_info.get('serial')

        # Test the key
        logger.info("Testing Yubikey encryption/decryption...")
        if not self._test_key_decrypt(recipient):
            logger.warning("Key test failed, but adding anyway (you may need to enter PIN)")

        # Add to database
        try:
            self.repo.execute("""
                INSERT INTO encryption_keys
                    (key_name, key_type, recipient, serial_number, piv_slot, location, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                key_name,
                'yubikey',
                recipient,
                serial_number,
                piv_slot,
                location,
                args.notes or ''
            ))

            key_id = self.repo.query_one("SELECT last_insert_rowid() as id", ())['id']
            self._audit_log('add', key_id, {
                'key_name': key_name,
                'serial': serial_number,
                'slot': piv_slot
            })

            logger.info(f"✓ Added Yubikey: {key_name}")
            logger.info(f"  Recipient: {recipient}")
            if serial_number:
                logger.info(f"  Serial: {serial_number}")
            logger.info(f"  Slot: {piv_slot}")
            logger.info(f"  Location: {location}")

            return 0

        except Exception as e:
            logger.error(f"Failed to add Yubikey: {e}")
            self._audit_log('add', None, {'error': str(e)}, success=False)
            return 1

    def _add_filesystem_key(self, args) -> int:
        """Add a filesystem age key to the registry"""
        key_name = args.name
        key_path = os.path.expanduser(args.path)
        location = args.location or 'filesystem'

        if not os.path.exists(key_path):
            logger.error(f"Key file not found: {key_path}")
            return 1

        # Get public key
        recipient = self._get_age_public_key(key_path)
        if not recipient:
            logger.error("Could not extract public key from file")
            return 1

        # Test the key
        logger.info("Testing key encryption/decryption...")
        if not self._test_key_decrypt(recipient, key_path):
            logger.error("Key test failed - encryption/decryption not working")
            return 1

        # Add to database
        try:
            self.repo.execute("""
                INSERT INTO encryption_keys
                    (key_name, key_type, recipient, location, notes, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                key_name,
                'filesystem',
                recipient,
                location,
                args.notes or '',
                json.dumps({'key_path': key_path})
            ))

            key_id = self.repo.query_one("SELECT last_insert_rowid() as id", ())['id']
            self._audit_log('add', key_id, {
                'key_name': key_name,
                'key_path': key_path
            })

            logger.info(f"✓ Added filesystem key: {key_name}")
            logger.info(f"  Recipient: {recipient}")
            logger.info(f"  Path: {key_path}")
            logger.info(f"  Location: {location}")

            return 0

        except Exception as e:
            logger.error(f"Failed to add key: {e}")
            self._audit_log('add', None, {'error': str(e)}, success=False)
            return 1

    def key_list(self, args) -> int:
        """List all registered encryption keys"""
        active_only = not args.all

        query = "SELECT * FROM encryption_key_stats_view"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY key_name"

        keys = self.repo.query_all(query, ())

        if not keys:
            logger.info("No encryption keys registered")
            logger.info("Add keys with: templedb key add")
            return 0

        print(f"\n{'='*80}")
        print(f"Encryption Keys ({len(keys)} total)")
        print(f"{'='*80}\n")

        for key in keys:
            status = "✓ ACTIVE" if key['is_active'] else "✗ DISABLED"
            print(f"{key['key_name']} ({key['key_type']}) - {status}")
            print(f"  Location: {key['location'] or 'unknown'}")
            print(f"  Secrets: {key['secrets_encrypted']}, Projects: {key['projects_count']}")
            if key['serial_number']:
                print(f"  Serial: {key['serial_number']}")
            if key['last_used_at']:
                print(f"  Last used: {key['last_used_at']}")
            if key['last_tested_at']:
                print(f"  Last tested: {key['last_tested_at']}")
            print()

        return 0

    def key_info(self, args) -> int:
        """Show detailed information about a specific key"""
        key_name = args.name

        key = self.repo.query_one("""
            SELECT * FROM encryption_keys WHERE key_name = ?
        """, (key_name,))

        if not key:
            logger.error(f"Key not found: {key_name}")
            return 1

        print(f"\n{'='*80}")
        print(f"Key: {key['key_name']}")
        print(f"{'='*80}\n")

        print(f"Type: {key['key_type']}")
        print(f"Status: {'ACTIVE' if key['is_active'] else 'DISABLED'}")
        print(f"Recipient: {key['recipient']}")

        if key['serial_number']:
            print(f"Serial Number: {key['serial_number']}")
        if key['piv_slot']:
            print(f"PIV Slot: {key['piv_slot']}")
        if key['location']:
            print(f"Location: {key['location']}")

        print(f"Created: {key['created_at']}")
        if key['last_used_at']:
            print(f"Last Used: {key['last_used_at']}")
        if key['last_tested_at']:
            print(f"Last Tested: {key['last_tested_at']}")

        if key['notes']:
            print(f"Notes: {key['notes']}")

        # Show secrets encrypted with this key
        secrets = self.repo.query_all("""
            SELECT p.slug, sb.profile, sb.secret_name
            FROM secret_key_assignments ska
            JOIN secret_blobs sb ON ska.secret_blob_id = sb.id
            JOIN projects p ON sb.project_id = p.id
            WHERE ska.key_id = ?
            ORDER BY p.slug, sb.profile
        """, (key['id'],))

        if secrets:
            print(f"\nSecrets encrypted with this key ({len(secrets)}):")
            for secret in secrets:
                print(f"  - {secret['slug']} ({secret['profile']})")

        # Show recent audit entries
        audit = self.repo.query_all("""
            SELECT action, timestamp, success
            FROM encryption_key_audit
            WHERE key_id = ?
            ORDER BY timestamp DESC
            LIMIT 10
        """, (key['id'],))

        if audit:
            print(f"\nRecent Activity:")
            for entry in audit:
                status = "✓" if entry['success'] else "✗"
                print(f"  {status} {entry['action']} - {entry['timestamp']}")

        print()
        return 0

    def key_test(self, args) -> int:
        """Test if a key can encrypt and decrypt"""
        key_name = args.name

        key = self.repo.query_one("""
            SELECT * FROM encryption_keys WHERE key_name = ?
        """, (key_name,))

        if not key:
            logger.error(f"Key not found: {key_name}")
            return 1

        logger.info(f"Testing key: {key_name}")
        logger.info(f"Type: {key['key_type']}")

        # Extract key_path for filesystem keys
        key_path = None
        if key['key_type'] == 'filesystem' and key['metadata']:
            try:
                metadata = json.loads(key['metadata'])
                key_path = metadata.get('key_path')
            except json.JSONDecodeError:
                pass

        # Run test
        success = self._test_key_decrypt(key['recipient'], key_path)

        # Update last_tested_at
        self.repo.execute("""
            UPDATE encryption_keys
            SET last_tested_at = datetime('now')
            WHERE id = ?
        """, (key['id'],))

        self._audit_log('test', key['id'], {'success': success}, success=success)

        if success:
            logger.info("✓ Key test PASSED - encryption/decryption working")
            return 0
        else:
            logger.error("✗ Key test FAILED - encryption/decryption not working")
            return 1

    def key_disable(self, args) -> int:
        """Disable a key without deleting it"""
        key_name = args.name

        key = self.repo.query_one("""
            SELECT id FROM encryption_keys WHERE key_name = ?
        """, (key_name,))

        if not key:
            logger.error(f"Key not found: {key_name}")
            return 1

        self.repo.execute("""
            UPDATE encryption_keys
            SET is_active = 0
            WHERE id = ?
        """, (key['id'],))

        self._audit_log('disable', key['id'])
        logger.info(f"✓ Disabled key: {key_name}")
        return 0

    def key_enable(self, args) -> int:
        """Enable a previously disabled key"""
        key_name = args.name

        key = self.repo.query_one("""
            SELECT id FROM encryption_keys WHERE key_name = ?
        """, (key_name,))

        if not key:
            logger.error(f"Key not found: {key_name}")
            return 1

        self.repo.execute("""
            UPDATE encryption_keys
            SET is_active = 1
            WHERE id = ?
        """, (key['id'],))

        self._audit_log('enable', key['id'])
        logger.info(f"✓ Enabled key: {key_name}")
        return 0

    def key_setup_yubikey(self, args) -> int:
        """Interactive setup to generate age identity on Yubikey"""
        logger.info("=" * 70)
        logger.info("Yubikey Age Identity Setup")
        logger.info("=" * 70)
        logger.info("")
        logger.info("This will:")
        logger.info("  1. Generate an age identity on your Yubikey")
        logger.info("  2. Set/use your Yubikey PIN")
        logger.info("  3. Save the identity to ~/.config/age-plugin-yubikey/identities.txt")
        logger.info("")
        logger.info("You'll be prompted for:")
        logger.info("  - Yubikey PIN (default: 123456 if never changed)")
        logger.info("  - New PIN (if you want to change it)")
        logger.info("")

        # Check if Yubikey is connected
        yubikey_info = self._get_yubikey_info()
        if not yubikey_info:
            logger.error("No Yubikey detected. Please insert Yubikey and try again.")
            return 1

        input("Press Enter to continue...")
        logger.info("")
        logger.info("Generating age identity on Yubikey...")

        try:
            # Run age-plugin-yubikey --generate
            proc = subprocess.run(
                ["age-plugin-yubikey", "--generate"],
                check=True
            )

            logger.info("")
            logger.info("=" * 70)
            logger.info("Identity Generated Successfully!")
            logger.info("=" * 70)
            logger.info("")

            # Get the recipient
            recipient = self._get_age_plugin_yubikey_recipient()
            if recipient:
                logger.info(f"Recipient: {recipient}")
                logger.info("")
                logger.info("Now you can add it to TempleDB:")
                logger.info(f"  ./templedb key add yubikey --name yubikey-1 --location \"daily-use\"")
            else:
                logger.warning("Could not extract recipient. Check ~/.config/age-plugin-yubikey/identities.txt")

            return 0

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to generate Yubikey identity: {e}")
            return 1
        except FileNotFoundError:
            logger.error("age-plugin-yubikey not found")
            logger.info("Install with: cargo install age-plugin-yubikey")
            return 1


def register(cli):
    """Register key management commands"""
    cmd = KeyCommands()

    key_parser = cli.register_command('key', None, help_text='Manage encryption keys')
    subparsers = key_parser.add_subparsers(dest='key_subcommand', required=True)

    # key add
    add_parser = subparsers.add_parser('add', help='Add encryption key to registry')
    add_parser.add_argument('type', choices=['yubikey', 'filesystem'], help='Key type')
    add_parser.add_argument('--name', required=True, help='Key name (e.g., yubikey-1-primary)')
    add_parser.add_argument('--location', help='Physical location (e.g., daily-use, safe, offsite)')
    add_parser.add_argument('--path', help='Path to key file (for filesystem keys)')
    add_parser.add_argument('--slot', help='PIV slot for Yubikey (default: 9a)')
    add_parser.add_argument('--notes', help='Additional notes')
    cli.commands['key.add'] = cmd.key_add

    # key list
    list_parser = subparsers.add_parser('list', help='List all encryption keys')
    list_parser.add_argument('--all', action='store_true', help='Include disabled keys')
    cli.commands['key.list'] = cmd.key_list

    # key info
    info_parser = subparsers.add_parser('info', help='Show detailed key information')
    info_parser.add_argument('name', help='Key name')
    cli.commands['key.info'] = cmd.key_info

    # key test
    test_parser = subparsers.add_parser('test', help='Test key encryption/decryption')
    test_parser.add_argument('name', help='Key name')
    cli.commands['key.test'] = cmd.key_test

    # key disable
    disable_parser = subparsers.add_parser('disable', help='Disable a key')
    disable_parser.add_argument('name', help='Key name')
    cli.commands['key.disable'] = cmd.key_disable

    # key enable
    enable_parser = subparsers.add_parser('enable', help='Enable a key')
    enable_parser.add_argument('name', help='Key name')
    cli.commands['key.enable'] = cmd.key_enable

    # key setup-yubikey
    setup_yubikey_parser = subparsers.add_parser('setup-yubikey',
                                                   help='Generate age identity on Yubikey')
    cli.commands['key.setup-yubikey'] = cmd.key_setup_yubikey
