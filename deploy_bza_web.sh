#!/usr/bin/env bash
# BZA Multi-User Web Frontend Deployment Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

error() { echo -e "${RED}❌ $1${NC}" >&2; }
success() { echo -e "${GREEN}✓ $1${NC}"; }
info() { echo -e "${YELLOW}→ $1${NC}"; }
header() { echo -e "${BLUE}━━━ $1 ━━━${NC}"; }

# Parse arguments
PROFILE=""
DRY_RUN=false
DEPLOY_WORKER=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --target) PROFILE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --deploy-worker) DEPLOY_WORKER=true; shift ;;
        local|production|default) PROFILE="$1"; shift ;;
        *) shift ;;
    esac
done

PROFILE="${PROFILE:-local}"
PROFILE_BEHAVIOR="$PROFILE"
[ "$PROFILE" = "default" ] && PROFILE_BEHAVIOR="local"

header "BZA Multi-User Web Frontend Deployment"
echo
info "Profile: $PROFILE"
[ "$DRY_RUN" = true ] && info "Mode: DRY RUN"
[ "$DEPLOY_WORKER" = true ] && info "Cloud Run worker: will deploy"
echo

# Check BZA exists
[ ! -d "/tmp/bza" ] && { error "BZA not found at /tmp/bza"; exit 1; }

header "Deployment Configuration"
echo

info "Profile:  $PROFILE"

if [ "$DRY_RUN" = true ]; then
    success "DRY RUN: Would deploy with:"
    echo "  Profile: $PROFILE"
    echo "  Working Dir: /tmp/bza"
    echo
    [ "$PROFILE_BEHAVIOR" = "production" ] && echo "  Frontend: Cloudflare Workers (npm run deploy:cf)" || echo "  Frontend: Next.js dev server"
    [ "$DEPLOY_WORKER" = true ] && echo "  Cloud Run: ./scripts/deploy_worker.sh"
    exit 0
fi

header "Injecting Secrets"
echo

info "Exporting secrets from TempleDB..."

_source_vars() {
    local project="$1"
    local blob
    # Export plain (non-encrypted) runtime vars; skip scoped keys like dev:KEY
    blob=$(templedb var export "$project" --format dotenv --no-secrets 2>/dev/null) || return 0
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
        [[ "$key" =~ : ]] && continue  # skip dev:/production: scoped keys
        if [ -z "${!key}" ]; then export "$key=$value"; fi
    done <<< "$blob"
}

_source_secrets() {
    local project="$1"
    local blob
    blob=$(templedb secret export "$project" --format dotenv 2>/dev/null) || return 0
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
        # Secrets override plain vars (project secrets take precedence over sibling projects)
        export "$key=$value"
    done <<< "$blob"
}

# bza runtime vars first, then encrypted secrets override
_source_vars bza    || { error "Failed to export bza vars from TempleDB"; exit 1; }
_source_secrets bza || { error "Failed to export bza secrets from TempleDB"; exit 1; }

# Deploy credentials stored in sibling projects
_source_vars    system_config    # provides SUPABASE_ACCESS_TOKEN (plain)
_source_secrets system_config    # provides SUPABASE_ACCESS_TOKEN (encrypted)
_source_vars    woofs_projects   # provides CLOUDFLARE_PAGES_API_TOKEN (plain)
_source_secrets woofs_projects   # provides CLOUDFLARE_PAGES_API_TOKEN (encrypted)

# wrangler reads CLOUDFLARE_API_TOKEN; alias from the Pages token if needed
[ -z "${CLOUDFLARE_API_TOKEN}" ] && export CLOUDFLARE_API_TOKEN="${CLOUDFLARE_PAGES_API_TOKEN}"

# Determine APP_ENV from target
APP_ENV="development"
[ "$PROFILE_BEHAVIOR" = "production" ] && APP_ENV="production"

# Write frontend/.env.local for Next.js
info "Writing frontend/.env.local..."
cat > /tmp/bza/frontend/.env.local <<EOF
# Auto-generated at deploy time by templedb deploy — do not edit by hand.

# Supabase
NEXT_PUBLIC_SUPABASE_URL=${NEXT_PUBLIC_SUPABASE_URL}
NEXT_PUBLIC_SUPABASE_ANON_KEY=${NEXT_PUBLIC_SUPABASE_ANON_KEY}
SUPABASE_SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_KEY}

# OpenAI
OPENAI_API_KEY=${OPENAI_API_KEY}

# Stripe
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=${NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY:-pk_test_placeholder}

# Feature flags
NEXT_PUBLIC_ENABLE_CHAT=true
NEXT_PUBLIC_ENABLE_IMAGES=true
NEXT_PUBLIC_ENABLE_CHARACTERS=true

# Environment
NEXT_PUBLIC_APP_ENV=${APP_ENV}
EOF
success "frontend/.env.local written"

# Write supabase/.env for edge functions
info "Writing supabase/.env..."
cat > /tmp/bza/supabase/.env <<EOF
# Auto-generated at deploy time by templedb deploy — do not edit by hand.
SUPABASE_URL=${SUPABASE_URL}
SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY}
SUPABASE_SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_KEY}
OPENAI_API_KEY=${OPENAI_API_KEY}
STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY}
STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET}
STRIPE_PRO_PRICE_ID=${STRIPE_PRO_PRICE_ID}
SITE_URL=${SITE_URL}
WORKER_URL=${WORKER_URL:-}
WORKER_SECRET=${WORKER_SECRET:-}
EOF
success "supabase/.env written"
echo

# ── Cloud Run Worker ───────────────────────────────────────────────────────────
if [ "$DEPLOY_WORKER" = true ]; then
    header "Deploying Cloud Run Worker"
    echo

    if [ -z "${GCP_PROJECT_ID:-}" ]; then
        error "GCP_PROJECT_ID not set — add it to TempleDB bza secrets before deploying the worker"
        exit 1
    fi

    cd /tmp/bza
    bash scripts/deploy_worker.sh

    # Re-read WORKER_URL in case it was just set by deploy_worker.sh
    WORKER_URL="${WORKER_URL:-$(templedb var get bza WORKER_URL 2>/dev/null || true)}"
    success "Cloud Run worker deployed → $WORKER_URL"
    echo
fi

# ── Supabase (production only) ─────────────────────────────────────────────────
if [ "$PROFILE_BEHAVIOR" = "production" ] && command -v supabase &> /dev/null; then
    PROJECT_REF=$(echo "$SUPABASE_URL" | sed 's|https://\([^.]*\)\..*|\1|')

    header "Applying Supabase Migrations"
    echo
    info "Running migrations against $PROJECT_REF..."
    cd /tmp/bza
    bash scripts/db-migrate.sh
    success "Migrations applied"
    echo

    header "Setting Supabase Edge Function Secrets"
    echo
    info "Setting WORKER_URL, WORKER_SECRET, DEFAULT_OUTPUT_BUCKET..."
    supabase secrets set \
        WORKER_URL="${WORKER_URL:-}" \
        WORKER_SECRET="${WORKER_SECRET:-}" \
        DEFAULT_OUTPUT_BUCKET="${DEFAULT_OUTPUT_BUCKET:-documents}"
    success "Supabase secrets set"
    echo
fi

# ── Supabase Edge Functions ────────────────────────────────────────────────────
header "Deploying Supabase Edge Functions"
echo

if command -v supabase &> /dev/null; then
    PROJECT_REF=$(echo "$SUPABASE_URL" | sed 's|https://\([^.]*\)\..*|\1|')
    info "Deploying edge functions to $PROJECT_REF..."
    cd /tmp/bza
    for fn_dir in supabase/functions/*/; do
        fn_name=$(basename "$fn_dir")
        # skip _shared — it is not a deployable function
        [[ "$fn_name" == _* ]] && continue
        info "  → $fn_name"
        supabase functions deploy "$fn_name" --project-ref "$PROJECT_REF" 2>&1 | tail -1
    done
    success "Edge functions deployed"
else
    info "supabase CLI not found — skipping edge function deploy"
fi
echo

# ── Next.js Frontend ───────────────────────────────────────────────────────────
header "Deploying Next.js Frontend"
echo

cd /tmp/bza/frontend

if [ ! -d "node_modules" ]; then
    info "Installing npm dependencies..."
    npm install --prefer-offline
    success "Dependencies installed"
fi

if [ "$PROFILE_BEHAVIOR" = "production" ]; then
    info "Building and deploying to Cloudflare Workers..."
    # NEXT_PUBLIC_* vars are already exported from the TempleDB secret export above.
    # opennextjs-cloudflare build inlines them, then wrangler deploy pushes the worker.
    npm run deploy:cf
    success "Frontend deployed → https://aireadalong.com"
else
    npm run dev &
    NEXT_PID=$!
    success "Next.js dev server started (PID: $NEXT_PID) → http://localhost:3000"
fi
echo

success "Deployment complete."
