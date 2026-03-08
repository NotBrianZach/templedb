# TempleDB DNS Automation Workflow

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INITIAL SETUP (One Time)                     │
└─────────────────────────────────────────────────────────────────────┘

    1. Register Domain in TempleDB
    ┌──────────────────────────────────────────────┐
    │ ./templedb domain register                   │
    │   woofs_projects woofs-demo.com              │
    │   --registrar "Cloudflare"                   │
    └──────────────────────────────────────────────┘
                        ↓
    2. Add Deployment Target
    ┌──────────────────────────────────────────────┐
    │ ./templedb target add                        │
    │   woofs_projects staging                     │
    │   --provider supabase                        │
    │   --host staging.woofs.com                   │
    └──────────────────────────────────────────────┘
                        ↓
    3. Add DNS Provider Credentials
    ┌──────────────────────────────────────────────┐
    │ ./templedb domain provider add cloudflare    │
    │                                              │
    │ Interactive prompts:                         │
    │ • Use API Token? Y                           │
    │ • API Token: ****************************   │
    └──────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    DEPLOYMENT WORKFLOW (Each Deploy)                 │
└─────────────────────────────────────────────────────────────────────┘

    4. Configure DNS Records (Database)
    ┌──────────────────────────────────────────────┐
    │ ./templedb domain dns configure              │
    │   woofs_projects woofs-demo.com              │
    │   --target staging                           │
    └──────────────────────────────────────────────┘
                        ↓
    ┌────────────────────────────────────┐
    │  What it does:                     │
    │  • Reads deployment target info    │
    │  • Generates DNS records:          │
    │    - CNAME for staging subdomain   │
    │  • Creates environment variables:  │
    │    - DATABASE_URL                  │
    │    - PUBLIC_URL                    │
    │    - API_URL                       │
    │  • Stores in TempleDB database     │
    └────────────────────────────────────┘
                        ↓
    5. Apply DNS via API ✨ AUTOMATED!
    ┌──────────────────────────────────────────────┐
    │ ./templedb domain dns apply                  │
    │   woofs_projects woofs-demo.com              │
    │   --target staging                           │
    └──────────────────────────────────────────────┘
                        ↓
    ┌────────────────────────────────────┐
    │  What it does:                     │
    │  1. Load credentials from DB       │
    │  2. Connect to Cloudflare API      │
    │  3. Get zone ID                    │
    │  4. Sync DNS records:              │
    │     • Create if doesn't exist      │
    │     • Update if exists             │
    │  5. Mark domain as active          │
    └────────────────────────────────────┘
                        ↓
    6. Verify DNS Propagation
    ┌──────────────────────────────────────────────┐
    │ ./templedb domain dns verify                 │
    │   woofs_projects woofs-demo.com              │
    └──────────────────────────────────────────────┘
                        ↓
    7. Deploy Application
    ┌──────────────────────────────────────────────┐
    │ ./templedb deploy run                        │
    │   woofs_projects --target staging            │
    └──────────────────────────────────────────────┘
                        ↓
                   ✅ DONE!


┌─────────────────────────────────────────────────────────────────────┐
│                     DATA FLOW ARCHITECTURE                          │
└─────────────────────────────────────────────────────────────────────┘

    TempleDB SQLite Database
    ┌─────────────────────────────────────────────┐
    │ • project_domains                           │
    │   - domain, registrar, status               │
    │                                             │
    │ • dns_records                               │
    │   - record_type, name, value, ttl           │
    │   - target_name (staging/production)        │
    │                                             │
    │ • deployment_targets                        │
    │   - target_name, provider, host             │
    │                                             │
    │ • environment_variables                     │
    │   - dns_provider:cloudflare credentials     │
    │   - staging:DATABASE_URL                    │
    │   - staging:PUBLIC_URL                      │
    └─────────────────────────────────────────────┘
                        ↕
    DNS Provider Abstraction Layer
    ┌─────────────────────────────────────────────┐
    │ dns_providers/                              │
    │ • base.py (interface)                       │
    │ • cloudflare.py ──→ Cloudflare API         │
    │ • namecheap.py  ──→ Namecheap API          │
    │ • route53.py    ──→ AWS Route53            │
    └─────────────────────────────────────────────┘
                        ↕
    External DNS Provider
    ┌─────────────────────────────────────────────┐
    │ Cloudflare / Namecheap / Route53            │
    │                                             │
    │ Live DNS Records:                           │
    │ staging.woofs-demo.com → staging.woofs.com  │
    └─────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                   COMPARISON: MANUAL vs AUTOMATED                    │
└─────────────────────────────────────────────────────────────────────┘

    MANUAL DNS WORKFLOW
    ┌──────────────────────────────────────────┐
    │ 1. Configure (plan records)              │
    │ 2. List records (see what to add)        │
    │ 3. Open browser                          │
    │ 4. Log into DNS provider                 │
    │ 5. Navigate to DNS settings              │
    │ 6. Manually add each record              │
    │ 7. Wait 5-60 minutes                     │
    │ 8. Verify propagation                    │
    │ 9. Deploy                                │
    └──────────────────────────────────────────┘
    Time: 15-60+ minutes

                      vs

    AUTOMATED DNS WORKFLOW
    ┌──────────────────────────────────────────┐
    │ 1. Configure (plan + store records)      │
    │ 2. Apply (automatic via API) ✨          │
    │ 3. Verify (optional)                     │
    │ 4. Deploy                                │
    └──────────────────────────────────────────┘
    Time: 1-2 minutes


┌─────────────────────────────────────────────────────────────────────┐
│                    CREDENTIAL SECURITY MODEL                         │
└─────────────────────────────────────────────────────────────────────┘

    Storage: TempleDB SQLite (environment_variables table)
    ┌─────────────────────────────────────────────┐
    │ scope_type: 'global' or 'domain'            │
    │ scope_id:   'dns_providers' or domain name  │
    │ var_name:   'dns_provider:cloudflare'       │
    │ var_value:  JSON credentials                │
    └─────────────────────────────────────────────┘

    Scoping Options:
    ┌─────────────────────────────────────────────┐
    │ Global Credentials                          │
    │ • One token for all domains                 │
    │ • Easier to manage                          │
    │ • Use: Same Cloudflare account              │
    │                                             │
    │ Domain-Specific Credentials                 │
    │ • Separate tokens per domain                │
    │ • More secure                               │
    │ • Use: Different accounts/permissions       │
    └─────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                      CI/CD INTEGRATION                              │
└─────────────────────────────────────────────────────────────────────┘

    GitHub Actions Example:
    ┌─────────────────────────────────────────────┐
    │ jobs:                                       │
    │   deploy:                                   │
    │     steps:                                  │
    │       - name: Setup TempleDB                │
    │         run: restore database               │
    │                                             │
    │       - name: Update DNS                    │
    │         run: |                              │
    │           templedb domain dns configure ... │
    │           templedb domain dns apply ...     │
    │                                             │
    │       - name: Deploy App                    │
    │         run: templedb deploy run ...        │
    └─────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                    MULTI-ENVIRONMENT SETUP                          │
└─────────────────────────────────────────────────────────────────────┘

    Single Domain, Multiple Environments:

    example.com
    ├── production   → example.com
    ├── staging      → staging.example.com
    └── dev          → dev.example.com

    Commands:
    ┌─────────────────────────────────────────────┐
    │ # Configure all environments                │
    │ templedb domain dns configure ... --target production  │
    │ templedb domain dns configure ... --target staging     │
    │ templedb domain dns configure ... --target dev         │
    │                                             │
    │ # Apply all at once                         │
    │ templedb domain dns apply ... --target production      │
    │ templedb domain dns apply ... --target staging         │
    │ templedb domain dns apply ... --target dev             │
    └─────────────────────────────────────────────┘

    Result:
    ┌─────────────────────────────────────────────┐
    │ DNS Records Created:                        │
    │ • example.com           → prod server       │
    │ • staging.example.com   → staging server    │
    │ • dev.example.com       → dev server        │
    │                                             │
    │ Environment Variables:                      │
    │ • production:DATABASE_URL                   │
    │ • production:PUBLIC_URL                     │
    │ • staging:DATABASE_URL                      │
    │ • staging:PUBLIC_URL                        │
    │ • dev:DATABASE_URL                          │
    │ • dev:PUBLIC_URL                            │
    └─────────────────────────────────────────────┘
