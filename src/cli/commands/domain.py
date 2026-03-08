#!/usr/bin/env python3
"""
Domain and DNS management commands for TempleDB
Integrates domain registration, DNS updates, and automatic environment variable configuration
"""
import sys
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger
from dns_providers import get_provider, DNSRecord

logger = get_logger(__name__)


class DomainCommands(Command):
    """Domain and DNS command handlers"""

    def register(self, args) -> int:
        """Register a new domain for a project"""
        try:
            project_slug = args.slug
            domain = args.domain
            registrar = args.registrar if hasattr(args, 'registrar') and args.registrar else None
            project = self.get_project_or_exit(project_slug)

            print(f"🌐 Registering domain: {domain}")
            print(f"   Project: {project_slug}\n")

            # Check if domain already exists
            existing = self.query_one("""
                SELECT id FROM project_domains
                WHERE project_id = ? AND domain = ?
            """, (project['id'], domain))

            if existing:
                logger.error(f"Domain '{domain}' already registered for {project_slug}")
                return 1

            # Insert domain
            self.execute("""
                INSERT INTO project_domains (
                    project_id,
                    domain,
                    registrar,
                    status
                ) VALUES (?, ?, ?, ?)
            """, (project['id'], domain, registrar, 'pending'))

            print(f"✅ Domain registered: {domain}")

            if registrar:
                print(f"\n📋 Registrar: {registrar}")
                print(f"\n💡 Next steps:")
                print(f"   1. Complete registration with {registrar}")
                print(f"   2. Configure DNS: ./templedb domain dns configure {project_slug} {domain}")
            else:
                print(f"\n💡 Next steps:")
                print(f"   1. Register domain with your preferred registrar")
                print(f"   2. Update registrar: ./templedb domain update {project_slug} {domain} --registrar <name>")
                print(f"   3. Configure DNS: ./templedb domain dns configure {project_slug} {domain}")

            return 0

        except Exception as e:
            logger.error(f"Failed to register domain: {e}")
            import traceback
            traceback.print_exc()
            return 1

    def list_domains(self, args) -> int:
        """List domains for a project"""
        try:
            project_slug = args.slug if hasattr(args, 'slug') and args.slug else None

            if project_slug:
                project = self.get_project_or_exit(project_slug)
                rows = self.query_all("""
                    SELECT
                        domain,
                        registrar,
                        status,
                        primary_domain,
                        created_at
                    FROM project_domains
                    WHERE project_id = ?
                    ORDER BY primary_domain DESC, domain
                """, (project['id'],))

                if not rows:
                    print(f"\n⚠️  No domains found for {project_slug}")
                    print(f"\n💡 Register one with: ./templedb domain register {project_slug} example.com\n")
                    return 0

                print(f"\n🌐 Domains: {project_slug}\n")
                for row in rows:
                    primary = " 🌟 PRIMARY" if row['primary_domain'] else ""
                    status_icon = "✓" if row['status'] == 'active' else "⏳"
                    print(f"{status_icon} {row['domain']}{primary}")
                    if row['registrar']:
                        print(f"   Registrar: {row['registrar']}")
                    print(f"   Status: {row['status']}")
                    print()
            else:
                # List all domains across all projects
                rows = self.query_all("""
                    SELECT
                        p.slug as project_slug,
                        pd.domain,
                        pd.registrar,
                        pd.status,
                        pd.primary_domain
                    FROM project_domains pd
                    JOIN projects p ON pd.project_id = p.id
                    ORDER BY p.slug, pd.primary_domain DESC, pd.domain
                """)

                if not rows:
                    print("\n⚠️  No domains found")
                    return 0

                print(f"\n🌐 All Domains\n")
                current_project = None
                for row in rows:
                    if row['project_slug'] != current_project:
                        if current_project:
                            print()
                        print(f"Project: {row['project_slug']}")
                        current_project = row['project_slug']

                    primary = " 🌟" if row['primary_domain'] else ""
                    status_icon = "✓" if row['status'] == 'active' else "⏳"
                    print(f"   {status_icon} {row['domain']}{primary}")
                print()

            return 0

        except Exception as e:
            logger.error(f"Failed to list domains: {e}")
            return 1

    def update(self, args) -> int:
        """Update domain configuration"""
        try:
            project_slug = args.slug
            domain = args.domain
            project = self.get_project_or_exit(project_slug)

            # Find the domain
            domain_record = self.query_one("""
                SELECT id FROM project_domains
                WHERE project_id = ? AND domain = ?
            """, (project['id'], domain))

            if not domain_record:
                logger.error(f"Domain '{domain}' not found for {project_slug}")
                return 1

            # Build update statement
            updates = []
            params = []

            if hasattr(args, 'registrar') and args.registrar:
                updates.append("registrar = ?")
                params.append(args.registrar)

            if hasattr(args, 'status') and args.status:
                updates.append("status = ?")
                params.append(args.status)

            if hasattr(args, 'primary') and args.primary:
                # First unset any existing primary domain
                self.execute("""
                    UPDATE project_domains
                    SET primary_domain = 0
                    WHERE project_id = ?
                """, (project['id'],))
                updates.append("primary_domain = 1")

            if not updates:
                logger.error("No updates specified")
                print(f"\n💡 Usage: ./templedb domain update {project_slug} {domain} --registrar <name> --status active --primary")
                return 1

            params.append(domain_record['id'])
            update_sql = f"UPDATE project_domains SET {', '.join(updates)} WHERE id = ?"

            self.execute(update_sql, tuple(params))

            print(f"✅ Updated domain: {domain}")
            return 0

        except Exception as e:
            logger.error(f"Failed to update domain: {e}")
            return 1

    def remove(self, args) -> int:
        """Remove a domain"""
        try:
            project_slug = args.slug
            domain = args.domain
            project = self.get_project_or_exit(project_slug)

            # Find the domain
            domain_record = self.query_one("""
                SELECT id FROM project_domains
                WHERE project_id = ? AND domain = ?
            """, (project['id'], domain))

            if not domain_record:
                logger.error(f"Domain '{domain}' not found for {project_slug}")
                return 1

            # Confirm deletion
            if not (hasattr(args, 'force') and args.force):
                print(f"⚠️  This will remove domain: {domain}")
                print(f"   Use --force to confirm")
                return 1

            # Delete domain and associated DNS records
            self.execute("""
                DELETE FROM dns_records WHERE domain_id = ?
            """, (domain_record['id'],))

            self.execute("""
                DELETE FROM project_domains WHERE id = ?
            """, (domain_record['id'],))

            print(f"✅ Removed domain: {domain}")
            return 0

        except Exception as e:
            logger.error(f"Failed to remove domain: {e}")
            return 1

    def dns_configure(self, args) -> int:
        """Configure DNS records for a domain and deployment target"""
        try:
            project_slug = args.slug
            domain = args.domain
            target_name = args.target if hasattr(args, 'target') and args.target else 'production'
            project = self.get_project_or_exit(project_slug)

            # Get domain
            domain_record = self.query_one("""
                SELECT id FROM project_domains
                WHERE project_id = ? AND domain = ?
            """, (project['id'], domain))

            if not domain_record:
                logger.error(f"Domain '{domain}' not found for {project_slug}")
                print(f"\n💡 Register it first: ./templedb domain register {project_slug} {domain}")
                return 1

            # Get target
            target = self.query_one("""
                SELECT * FROM deployment_targets
                WHERE project_id = ? AND target_name = ?
            """, (project['id'], target_name))

            if not target:
                logger.error(f"Target '{target_name}' not found for {project_slug}")
                print(f"\n💡 Add it first: ./templedb target add {project_slug} {target_name} --host <host>")
                return 1

            print(f"🔧 Configuring DNS for {domain} -> {target_name}")
            print(f"   Target Host: {target['host']}\n")

            # Determine record type and value based on provider
            if target['provider'] == 'supabase':
                # Supabase uses CNAME records
                subdomain = f"{target_name}.{domain}" if target_name != 'production' else domain

                print(f"📋 DNS Configuration Required:\n")
                print(f"   Record Type: CNAME")
                print(f"   Name: {subdomain}")
                print(f"   Value: {target['host']}")
                print(f"   TTL: 3600")

                # Store DNS record
                self.execute("""
                    INSERT OR REPLACE INTO dns_records (
                        domain_id,
                        record_type,
                        name,
                        value,
                        ttl,
                        target_name
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (domain_record['id'], 'CNAME', subdomain, target['host'], 3600, target_name))

                # Generate DATABASE_URL
                database_url = f"postgresql://{target['host']}/postgres"
                full_url = f"https://{subdomain}"

                print(f"\n🔐 Setting environment variables...")

                # Store DATABASE_URL
                self._set_env_var(project, target_name, 'DATABASE_URL', database_url)
                # Store PUBLIC_URL
                self._set_env_var(project, target_name, 'PUBLIC_URL', full_url)
                # Store API_URL
                self._set_env_var(project, target_name, 'API_URL', f"{full_url}/api")

                print(f"\n✅ DNS configuration saved")
                print(f"\n📝 Manual Steps Required:")
                print(f"   1. Log into your DNS provider ({domain_record.get('registrar', 'your registrar')})")
                print(f"   2. Add the CNAME record shown above")
                print(f"   3. Wait for DNS propagation (usually 5-60 minutes)")
                print(f"   4. Verify: ./templedb domain dns verify {project_slug} {domain}")
                print(f"\n💡 Environment variables set:")
                print(f"   • DATABASE_URL")
                print(f"   • PUBLIC_URL = {full_url}")
                print(f"   • API_URL = {full_url}/api")

            elif target['provider'] == 'vercel':
                # Vercel uses A/AAAA records or CNAME
                subdomain = f"{target_name}.{domain}" if target_name != 'production' else domain

                print(f"📋 DNS Configuration Required:\n")
                print(f"   Record Type: CNAME")
                print(f"   Name: {subdomain}")
                print(f"   Value: cname.vercel-dns.com")
                print(f"   TTL: 3600")

                self.execute("""
                    INSERT OR REPLACE INTO dns_records (
                        domain_id,
                        record_type,
                        name,
                        value,
                        ttl,
                        target_name
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (domain_record['id'], 'CNAME', subdomain, 'cname.vercel-dns.com', 3600, target_name))

                full_url = f"https://{subdomain}"
                self._set_env_var(project, target_name, 'PUBLIC_URL', full_url)
                self._set_env_var(project, target_name, 'VERCEL_URL', subdomain)

                print(f"\n✅ DNS configuration saved")
                print(f"\n💡 Environment variables set:")
                print(f"   • PUBLIC_URL = {full_url}")
                print(f"   • VERCEL_URL = {subdomain}")

            else:
                # Generic provider - use A record
                subdomain = f"{target_name}.{domain}" if target_name != 'production' else domain

                print(f"📋 DNS Configuration Required:\n")
                print(f"   Record Type: A or CNAME")
                print(f"   Name: {subdomain}")
                print(f"   Value: {target['host']}")
                print(f"   TTL: 3600")

                record_type = 'A' if target['host'].replace('.', '').isdigit() else 'CNAME'

                self.execute("""
                    INSERT OR REPLACE INTO dns_records (
                        domain_id,
                        record_type,
                        name,
                        value,
                        ttl,
                        target_name
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (domain_record['id'], record_type, subdomain, target['host'], 3600, target_name))

                full_url = f"https://{subdomain}"
                self._set_env_var(project, target_name, 'PUBLIC_URL', full_url)

                print(f"\n✅ DNS configuration saved")

            # Update target with access URL
            self.execute("""
                UPDATE deployment_targets
                SET access_url = ?
                WHERE id = ?
            """, (full_url, target['id']))

            return 0

        except Exception as e:
            logger.error(f"Failed to configure DNS: {e}")
            import traceback
            traceback.print_exc()
            return 1

    def dns_list(self, args) -> int:
        """List DNS records for a domain"""
        try:
            project_slug = args.slug
            domain = args.domain
            project = self.get_project_or_exit(project_slug)

            # Get domain
            domain_record = self.query_one("""
                SELECT id FROM project_domains
                WHERE project_id = ? AND domain = ?
            """, (project['id'], domain))

            if not domain_record:
                logger.error(f"Domain '{domain}' not found for {project_slug}")
                return 1

            # Get DNS records
            records = self.query_all("""
                SELECT
                    record_type,
                    name,
                    value,
                    ttl,
                    target_name,
                    created_at
                FROM dns_records
                WHERE domain_id = ?
                ORDER BY name, record_type
            """, (domain_record['id'],))

            if not records:
                print(f"\n⚠️  No DNS records found for {domain}")
                print(f"\n💡 Configure DNS: ./templedb domain dns configure {project_slug} {domain}")
                return 0

            print(f"\n📋 DNS Records: {domain}\n")
            for record in records:
                target_info = f" (→ {record['target_name']})" if record['target_name'] else ""
                print(f"{record['record_type']:6} {record['name']:30} → {record['value']}{target_info}")
                print(f"       TTL: {record['ttl']}s")
                print()

            return 0

        except Exception as e:
            logger.error(f"Failed to list DNS records: {e}")
            return 1

    def dns_verify(self, args) -> int:
        """Verify DNS records are properly configured"""
        try:
            project_slug = args.slug
            domain = args.domain
            project = self.get_project_or_exit(project_slug)

            # Get domain
            domain_record = self.query_one("""
                SELECT id FROM project_domains
                WHERE project_id = ? AND domain = ?
            """, (project['id'], domain))

            if not domain_record:
                logger.error(f"Domain '{domain}' not found for {project_slug}")
                return 1

            # Get DNS records
            records = self.query_all("""
                SELECT
                    record_type,
                    name,
                    value
                FROM dns_records
                WHERE domain_id = ?
            """, (domain_record['id'],))

            if not records:
                print(f"\n⚠️  No DNS records configured for {domain}")
                return 1

            print(f"🔍 Verifying DNS records for {domain}...\n")

            all_verified = True
            for record in records:
                try:
                    # Use dig or nslookup to verify
                    cmd = ['dig', '+short', record['name'], record['record_type']]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

                    if result.returncode == 0 and result.stdout.strip():
                        actual_value = result.stdout.strip().split('\n')[0].rstrip('.')
                        expected_value = record['value'].rstrip('.')

                        if actual_value == expected_value:
                            print(f"✅ {record['name']:30} ({record['record_type']})")
                        else:
                            print(f"⚠️  {record['name']:30} ({record['record_type']})")
                            print(f"   Expected: {expected_value}")
                            print(f"   Got:      {actual_value}")
                            all_verified = False
                    else:
                        print(f"❌ {record['name']:30} ({record['record_type']}) - Not found")
                        all_verified = False

                except subprocess.TimeoutExpired:
                    print(f"⏱️  {record['name']:30} ({record['record_type']}) - Timeout")
                    all_verified = False
                except FileNotFoundError:
                    print(f"⚠️  'dig' command not found - using nslookup")
                    try:
                        cmd = ['nslookup', '-type=' + record['record_type'], record['name']]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                        if record['value'] in result.stdout:
                            print(f"✅ {record['name']:30} ({record['record_type']})")
                        else:
                            print(f"❌ {record['name']:30} ({record['record_type']}) - Not found")
                            all_verified = False
                    except Exception as e:
                        print(f"❌ {record['name']:30} ({record['record_type']}) - Verification failed")
                        all_verified = False

            print()
            if all_verified:
                print("✅ All DNS records verified!")

                # Update domain status
                self.execute("""
                    UPDATE project_domains
                    SET status = 'active'
                    WHERE id = ?
                """, (domain_record['id'],))

                return 0
            else:
                print("⚠️  Some DNS records are not properly configured")
                print("💡 DNS propagation can take 5-60 minutes. Try again later.")
                return 1

        except Exception as e:
            logger.error(f"Failed to verify DNS: {e}")
            import traceback
            traceback.print_exc()
            return 1

    def provider_add(self, args) -> int:
        """Add DNS provider credentials"""
        try:
            provider_name = args.provider
            domain = args.domain if hasattr(args, 'domain') and args.domain else None

            print(f"🔑 Adding DNS provider credentials: {provider_name}\n")

            # Provider-specific credential prompts
            credentials = {}

            if provider_name == 'cloudflare':
                print("Cloudflare DNS API Setup")
                print("You need either:")
                print("  Option 1: API Token (recommended) - Create at https://dash.cloudflare.com/profile/api-tokens")
                print("  Option 2: Global API Key + Email\n")

                use_token = input("Use API Token? (Y/n): ").strip().lower() != 'n'

                if use_token:
                    import getpass
                    credentials['api_token'] = getpass.getpass("API Token: ")
                else:
                    credentials['email'] = input("Email: ")
                    import getpass
                    credentials['api_key'] = getpass.getpass("Global API Key: ")

            elif provider_name == 'namecheap':
                print("Namecheap DNS API Setup")
                print("Enable API access: https://ap.www.namecheap.com/settings/tools/apiaccess/\n")

                credentials['api_user'] = input("API Username: ")
                import getpass
                credentials['api_key'] = getpass.getpass("API Key: ")
                credentials['client_ip'] = input("Whitelisted IP: ")

            elif provider_name == 'route53':
                print("AWS Route53 DNS API Setup\n")

                credentials['aws_access_key_id'] = input("AWS Access Key ID: ")
                import getpass
                credentials['aws_secret_access_key'] = getpass.getpass("AWS Secret Access Key: ")
                credentials['region'] = input("AWS Region (default: us-east-1): ") or 'us-east-1'

            else:
                logger.error(f"Unsupported provider: {provider_name}")
                print(f"\n💡 Supported providers: cloudflare, namecheap, route53")
                return 1

            # Store credentials in secrets table
            credentials_json = json.dumps(credentials)

            # Use domain-specific or global scope
            scope_type = 'domain' if domain else 'global'
            scope_id = domain or 'dns_providers'

            self.execute("""
                INSERT OR REPLACE INTO environment_variables (
                    scope_type,
                    scope_id,
                    var_name,
                    var_value
                ) VALUES (?, ?, ?, ?)
            """, (scope_type, scope_id, f"dns_provider:{provider_name}", credentials_json))

            print(f"\n✅ DNS provider credentials stored: {provider_name}")

            if domain:
                print(f"   Scope: {domain}")
            else:
                print(f"   Scope: global")

            print(f"\n💡 Now you can use automated DNS management:")
            if domain:
                print(f"   ./templedb domain dns apply PROJECT_SLUG {domain} --target TARGET")
            else:
                print(f"   ./templedb domain dns apply PROJECT_SLUG DOMAIN --target TARGET")

            return 0

        except Exception as e:
            logger.error(f"Failed to add DNS provider: {e}")
            import traceback
            traceback.print_exc()
            return 1

    def provider_list(self, args) -> int:
        """List configured DNS providers"""
        try:
            rows = self.query_all("""
                SELECT scope_type, scope_id, var_name
                FROM environment_variables
                WHERE var_name LIKE 'dns_provider:%'
            """)

            if not rows:
                print("\n⚠️  No DNS providers configured")
                print("\n💡 Add one with: ./templedb domain provider add PROVIDER_NAME")
                return 0

            print("\n🔑 Configured DNS Providers\n")
            for row in rows:
                provider_name = row['var_name'].replace('dns_provider:', '')
                scope_info = f"{row['scope_type']}: {row['scope_id']}" if row['scope_type'] != 'global' else 'global'
                print(f"✓ {provider_name:15} ({scope_info})")

            print()
            return 0

        except Exception as e:
            logger.error(f"Failed to list providers: {e}")
            return 1

    def dns_apply(self, args) -> int:
        """Apply DNS records using DNS provider API"""
        try:
            project_slug = args.slug
            domain = args.domain
            target_name = args.target if hasattr(args, 'target') and args.target else 'production'
            provider_name = args.provider if hasattr(args, 'provider') and args.provider else None
            project = self.get_project_or_exit(project_slug)

            print(f"🚀 Applying DNS records for {domain} via API...")

            # Get domain record
            domain_record = self.query_one("""
                SELECT id, registrar FROM project_domains
                WHERE project_id = ? AND domain = ?
            """, (project['id'], domain))

            if not domain_record:
                logger.error(f"Domain '{domain}' not found for {project_slug}")
                print(f"\n💡 Register it first: ./templedb domain register {project_slug} {domain}")
                return 1

            # Auto-detect provider from registrar if not specified
            if not provider_name:
                registrar = domain_record.get('registrar', '').lower()
                if 'cloudflare' in registrar:
                    provider_name = 'cloudflare'
                elif 'namecheap' in registrar:
                    provider_name = 'namecheap'
                elif 'aws' in registrar or 'route53' in registrar:
                    provider_name = 'route53'
                else:
                    logger.error("Could not auto-detect DNS provider")
                    print("\n💡 Specify provider: --provider cloudflare|namecheap|route53")
                    return 1

            print(f"   Provider: {provider_name}")

            # Get provider credentials
            # Try domain-specific first, then global
            creds_row = self.query_one("""
                SELECT var_value FROM environment_variables
                WHERE var_name = ? AND (
                    (scope_type = 'domain' AND scope_id = ?) OR
                    (scope_type = 'global' AND scope_id = 'dns_providers')
                )
                ORDER BY CASE WHEN scope_type = 'domain' THEN 0 ELSE 1 END
                LIMIT 1
            """, (f"dns_provider:{provider_name}", domain))

            if not creds_row:
                logger.error(f"No credentials found for provider: {provider_name}")
                print(f"\n💡 Add credentials: ./templedb domain provider add {provider_name}")
                return 1

            credentials = json.loads(creds_row['var_value'])

            # Get DNS records from database
            dns_records = self.query_all("""
                SELECT record_type, name, value, ttl, priority
                FROM dns_records
                WHERE domain_id = ? AND target_name = ?
            """, (domain_record['id'], target_name))

            if not dns_records:
                logger.error(f"No DNS records configured for {domain} / {target_name}")
                print(f"\n💡 Configure DNS first: ./templedb domain dns configure {project_slug} {domain} --target {target_name}")
                return 1

            print(f"   Records to apply: {len(dns_records)}\n")

            # Initialize DNS provider
            try:
                provider = get_provider(provider_name, credentials)
            except Exception as e:
                logger.error(f"Failed to initialize DNS provider: {e}")
                return 1

            # Apply each record
            success_count = 0
            for record_data in dns_records:
                try:
                    record = DNSRecord(
                        record_type=record_data['record_type'],
                        name=record_data['name'],
                        value=record_data['value'],
                        ttl=record_data['ttl'],
                        priority=record_data.get('priority')
                    )

                    # Sync record (create or update)
                    provider.sync_record(domain, record)
                    print(f"✓ {record.record_type:6} {record.name:30} → {record.value}")
                    success_count += 1

                except Exception as e:
                    print(f"✗ {record.record_type:6} {record.name:30} - {e}")

            print(f"\n✅ Applied {success_count}/{len(dns_records)} DNS records")

            if success_count == len(dns_records):
                # Update domain status
                self.execute("""
                    UPDATE project_domains
                    SET status = 'active'
                    WHERE id = ?
                """, (domain_record['id'],))

                print("\n💡 DNS records are live! Verify with:")
                print(f"   ./templedb domain dns verify {project_slug} {domain}")

            return 0 if success_count == len(dns_records) else 1

        except Exception as e:
            logger.error(f"Failed to apply DNS records: {e}")
            import traceback
            traceback.print_exc()
            return 1

    def _set_env_var(self, project: Dict, target: str, var_name: str, value: str):
        """Helper to set an environment variable"""
        try:
            # Store with target prefix for scoping
            full_var_name = f"{target}:{var_name}"

            self.execute("""
                INSERT OR REPLACE INTO environment_variables (
                    scope_type,
                    scope_id,
                    var_name,
                    var_value
                ) VALUES (?, ?, ?, ?)
            """, ('project', project['id'], full_var_name, value))

            print(f"   ✓ Set {var_name}")

        except Exception as e:
            logger.error(f"Failed to set environment variable {var_name}: {e}")


def register(cli):
    """Register domain commands with CLI"""
    handler = DomainCommands()

    # Create domain command group
    domain_parser = cli.register_command('domain', None, help_text='Manage domains and DNS')
    subparsers = domain_parser.add_subparsers(dest='domain_subcommand', required=True)

    # register command
    register_parser = subparsers.add_parser('register', help='Register a domain for a project')
    register_parser.add_argument('slug', help='Project slug')
    register_parser.add_argument('domain', help='Domain name (e.g., example.com)')
    register_parser.add_argument('--registrar', help='Domain registrar name')
    cli.commands['domain.register'] = handler.register

    # list command
    list_parser = subparsers.add_parser('list', help='List domains', aliases=['ls'])
    list_parser.add_argument('slug', nargs='?', help='Project slug (optional)')
    cli.commands['domain.list'] = handler.list_domains
    cli.commands['domain.ls'] = handler.list_domains

    # update command
    update_parser = subparsers.add_parser('update', help='Update domain configuration')
    update_parser.add_argument('slug', help='Project slug')
    update_parser.add_argument('domain', help='Domain name')
    update_parser.add_argument('--registrar', help='Update registrar')
    update_parser.add_argument('--status', choices=['pending', 'active', 'expired'], help='Update status')
    update_parser.add_argument('--primary', action='store_true', help='Set as primary domain')
    cli.commands['domain.update'] = handler.update

    # remove command
    remove_parser = subparsers.add_parser('remove', help='Remove a domain', aliases=['rm'])
    remove_parser.add_argument('slug', help='Project slug')
    remove_parser.add_argument('domain', help='Domain name')
    remove_parser.add_argument('--force', action='store_true', help='Confirm deletion')
    cli.commands['domain.remove'] = handler.remove
    cli.commands['domain.rm'] = handler.remove

    # dns subcommand group - needs special handler wrapper
    dns_parser = subparsers.add_parser('dns', help='Manage DNS records')
    dns_subparsers = dns_parser.add_subparsers(dest='dns_subcommand', required=True)

    # dns configure
    dns_configure_parser = dns_subparsers.add_parser('configure', help='Configure DNS for a deployment target')
    dns_configure_parser.add_argument('slug', help='Project slug')
    dns_configure_parser.add_argument('domain', help='Domain name')
    dns_configure_parser.add_argument('--target', default='production', help='Deployment target (default: production)')

    # dns list
    dns_list_parser = dns_subparsers.add_parser('list', help='List DNS records for a domain', aliases=['ls'])
    dns_list_parser.add_argument('slug', help='Project slug')
    dns_list_parser.add_argument('domain', help='Domain name')

    # dns verify
    dns_verify_parser = dns_subparsers.add_parser('verify', help='Verify DNS records are configured correctly')
    dns_verify_parser.add_argument('slug', help='Project slug')
    dns_verify_parser.add_argument('domain', help='Domain name')

    # dns apply (API-based DNS updates)
    dns_apply_parser = dns_subparsers.add_parser('apply', help='Apply DNS records using provider API')
    dns_apply_parser.add_argument('slug', help='Project slug')
    dns_apply_parser.add_argument('domain', help='Domain name')
    dns_apply_parser.add_argument('--target', default='production', help='Deployment target (default: production)')
    dns_apply_parser.add_argument('--provider', help='DNS provider (cloudflare, namecheap, route53)')

    # Create a wrapper handler for DNS commands
    def dns_handler(args):
        subcommand = args.dns_subcommand
        if subcommand == 'configure':
            return handler.dns_configure(args)
        elif subcommand in ('list', 'ls'):
            return handler.dns_list(args)
        elif subcommand == 'verify':
            return handler.dns_verify(args)
        elif subcommand == 'apply':
            return handler.dns_apply(args)
        else:
            print(f"Unknown DNS subcommand: {subcommand}")
            return 1

    cli.commands['domain.dns'] = dns_handler

    # provider subcommand group
    provider_parser = subparsers.add_parser('provider', help='Manage DNS provider credentials')
    provider_subparsers = provider_parser.add_subparsers(dest='provider_subcommand', required=True)

    # provider add
    provider_add_parser = provider_subparsers.add_parser('add', help='Add DNS provider credentials')
    provider_add_parser.add_argument('provider', choices=['cloudflare', 'namecheap', 'route53'], help='DNS provider')
    provider_add_parser.add_argument('--domain', help='Scope credentials to specific domain (optional)')

    # provider list
    provider_list_parser = provider_subparsers.add_parser('list', help='List configured DNS providers', aliases=['ls'])

    # Create wrapper handler for provider commands
    def provider_handler(args):
        subcommand = args.provider_subcommand
        if subcommand == 'add':
            return handler.provider_add(args)
        elif subcommand in ('list', 'ls'):
            return handler.provider_list(args)
        else:
            print(f"Unknown provider subcommand: {subcommand}")
            return 1

    cli.commands['domain.provider'] = provider_handler
