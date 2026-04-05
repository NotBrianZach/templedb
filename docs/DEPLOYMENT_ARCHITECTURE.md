# TempleDB Deployment Architecture Review

**Version**: 1.0
**Date**: 2026-03-21
**Status**: Architectural Design Document

## Executive Summary

This document presents a comprehensive architectural review of deployment strategies for TempleDB-managed projects, with specific focus on three deployment archetypes:

1. **CLI Tools** (exemplar: `bza`) - Self-contained executables with minimal runtime dependencies
2. **Web Services** (exemplar: `woofs_projects`) - Long-running services with database backends
3. **Games** - Interactive applications with assets, state management, and multiplayer considerations

The architecture emphasizes **intelligent fallback strategies** for dependencies, **seamless integration** with Cathedral packages for TempleDB-to-TempleDB deployments, and **portability** to systems with or without TempleDB.

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Core Deployment Challenges](#core-deployment-challenges)
3. [Architectural Patterns](#architectural-patterns)
4. [Deployment by Project Type](#deployment-by-project-type)
5. [Secret Management & Fallback Strategies](#secret-management--fallback-strategies)
6. [Cathedral Integration](#cathedral-integration)
7. [Target Environment Detection](#target-environment-detection)
8. [Comparison Matrices](#comparison-matrices)
9. [Implementation Roadmap](#implementation-roadmap)

---

## Current State Analysis

### Existing TempleDB Infrastructure

TempleDB currently provides:

#### 1. **Cathedral Package System**
- Export/import projects as `.cathedral` packages
- Content-addressable storage with deduplication
- VCS history preservation
- Compression support (zlib, zstd)

```bash
# Export project
templedb cathedral export myproject --output ./packages/

# Import on target system
templedb cathedral import myproject.cathedral
```

#### 2. **Deployment Targets**
- Database schema: `deployment_targets` table
- Supports multiple target types: `database`, `edge_function`, `static_site`, `container`, `serverless`
- Provider tracking: Supabase, Vercel, AWS, GCP, Cloudflare, local
- VPN requirements, access URLs

```sql
CREATE TABLE deployment_targets (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    target_name TEXT NOT NULL,        -- 'production', 'staging', 'development'
    target_type TEXT NOT NULL,
    host TEXT,
    region TEXT,
    provider TEXT,
    requires_vpn BOOLEAN DEFAULT 0,
    access_url TEXT,
    connection_string TEXT,
    UNIQUE(project_id, target_name, target_type)
);
```

#### 3. **Environment Management**
- Per-project environment variables
- Profile support (default, production, staging)
- Integration with deployment targets

#### 4. **Deployment Cache**
- Content-addressable deployment artifacts
- Hash-based caching to avoid redundant deployments
- Lock file enforcement (package-lock.json, requirements.txt.lock)

#### 5. **Nix Integration**
- FHS (Filesystem Hierarchy Standard) environments
- Reproducible builds
- Isolated execution environments

### Current Limitations

1. **No unified deployment workflow** - Each project type requires custom deployment logic
2. **Limited fallback handling** - No systematic approach for missing dependencies/secrets
3. **Manual Cathedral transfer** - No built-in remote sync for `.cathedral` packages
4. **No deployment orchestration** - Multi-service deployments require manual coordination
5. **Partial secret integration** - Secrets exist but not fully integrated with deployment flow

---

## Core Deployment Challenges

### 1. **Dependency Resolution**

Different project types have different dependency models:

| Project Type | Package Manager | Lock File | Runtime |
|-------------|----------------|-----------|---------|
| Python CLI | pip, poetry | requirements.txt.lock | Python 3.x |
| Python Web Service | pip, poetry | pyproject.toml + lock | Python 3.x + WSGI/ASGI |
| Node CLI | npm, pnpm, yarn | package-lock.json | Node.js |
| Node Web Service | npm, pnpm | package-lock.json | Node.js + Express/Fastify |
| JavaScript Games | npm, pnpm | package-lock.json | Browser (bundled) |

**Challenge**: Ensure dependencies are available on target, with fallbacks for missing packages.

### 2. **Secret & API Key Management**

Secrets must be:
- **Encrypted at rest** (TempleDB uses age encryption)
- **Injected at deployment time** (not committed to VCS)
- **Environment-specific** (dev, staging, prod)
- **Have fallbacks** (placeholder values for local dev)

**Challenge**: Balance security with developer experience (local dev shouldn't require production keys).

### 3. **Environment Portability**

Target environments vary widely:

| Environment | Has TempleDB? | Has Nix? | Has Docker? | Package Managers |
|------------|---------------|----------|-------------|-----------------|
| Developer Laptop (with TDB) | ✅ | ✅ | ✅ | ✅ |
| CI/CD Runner | ❌ | Sometimes | ✅ | ✅ |
| Cloud VPS | ❌ | Rare | Usually | ✅ |
| Serverless (Vercel/Netlify) | ❌ | ❌ | N/A | Managed |
| Edge (Cloudflare Workers) | ❌ | ❌ | N/A | Bundled |

**Challenge**: Deploy to diverse targets with graceful degradation.

### 4. **Database Portability**

Projects may use:
- **SQLite** (embedded, great for CLI tools and small services)
- **PostgreSQL** (powerful, required for Supabase, Vercel Postgres)
- **Supabase** (managed Postgres with extras)

**Challenge**: Support local SQLite dev with production Postgres deployment.

### 5. **State Management**

Different project types handle state differently:

| Project Type | State Storage | Persistence |
|-------------|---------------|-------------|
| CLI Tools | Local files, SQLite | Per-machine |
| Web Services | Database, Redis | Centralized |
| Games (single-player) | localStorage, IndexedDB | Per-browser |
| Games (multiplayer) | Server database + client sync | Centralized + local |

**Challenge**: Migrate state during deployments, handle backups.

---

## Architectural Patterns

### Pattern 1: Cathedral-Native Deployment

**Use Case**: TempleDB → TempleDB deployment (full infrastructure available)

**Flow**:
```
┌─────────────┐
│ Source TDB  │
│             │
│ 1. Export   │──────┐
│    cathedral│      │
└─────────────┘      │
                     │ .cathedral
                     │ package
                     │
                     ▼
              ┌─────────────┐
              │ Transfer    │
              │ (scp/S3/    │
              │  rsync)     │
              └─────────────┘
                     │
                     │
                     ▼
              ┌─────────────┐
              │ Target TDB  │
              │             │
              │ 2. Import   │
              │    cathedral│
              │             │
              │ 3. Deploy   │
              │    from VCS │
              └─────────────┘
```

**Advantages**:
- ✅ Content deduplication (shared blobs)
- ✅ VCS history preserved
- ✅ Component sharing (if using component library)
- ✅ Secrets managed by TempleDB on both ends
- ✅ Deployment cache benefits

**Disadvantages**:
- ❌ Requires TempleDB on target
- ❌ Cathedral transfer is manual
- ❌ More complex setup

**Implementation**:
```bash
# Source system
templedb cathedral export myproject --compress

# Transfer
scp myproject.cathedral deploy@target:/tmp/

# Target system (with TempleDB)
templedb cathedral import /tmp/myproject.cathedral
templedb deploy run myproject --target production
```

### Pattern 2: Self-Contained Artifact Deployment

**Use Case**: TempleDB → Bare system (no TempleDB on target)

**Flow**:
```
┌─────────────┐
│ Source TDB  │
│             │
│ 1. Package  │──────┐
│    for      │      │
│    target   │      │
└─────────────┘      │
                     │ Artifact
                     │ (Nix closure,
                     │  Docker image,
                     │  or tarball)
                     ▼
              ┌─────────────┐
              │ Transfer &  │
              │ Extract     │
              └─────────────┘
                     │
                     │
                     ▼
              ┌─────────────┐
              │ Target      │
              │ (bare)      │
              │             │
              │ 2. Run      │
              │    artifact │
              └─────────────┘
```

**Advantages**:
- ✅ Works on any system
- ✅ No TempleDB required on target
- ✅ Self-contained (all dependencies included)
- ✅ Reproducible (especially with Nix)

**Disadvantages**:
- ❌ Larger artifacts (no deduplication)
- ❌ No VCS history on target
- ❌ Secrets must be injected separately

**Implementation**:
```bash
# Generate deployment package
templedb deploy package myproject --format nix-closure --output ./dist/

# Or Docker image
templedb deploy package myproject --format docker --tag myproject:latest

# Or standalone tarball
templedb deploy package myproject --format standalone --output ./dist/
```

### Pattern 3: Hybrid Smart Deployment

**Use Case**: Adapt to target capabilities automatically

**Flow**:
```
┌─────────────┐
│ Source TDB  │
│             │
│ 1. Detect   │
│    target   │
└─────┬───────┘
      │
      │ SSH probe
      │
      ▼
┌─────────────────────────────────┐
│ Target Capability Detection     │
│                                  │
│ ✓ Has TempleDB?                 │
│ ✓ Has Nix?                      │
│ ✓ Has Docker?                   │
│ ✓ Available package managers?   │
└─────────┬───────────────────────┘
          │
          │ Choose strategy
          │
    ┌─────┴─────────────┬──────────────┐
    ▼                   ▼              ▼
┌──────────┐     ┌──────────┐   ┌──────────┐
│Cathedral │     │Nix       │   │Tarball   │
│(best)    │     │Closure   │   │(fallback)│
└──────────┘     └──────────┘   └──────────┘
```

**Advantages**:
- ✅ Best of both worlds
- ✅ Automatic optimization
- ✅ Graceful degradation

**Disadvantages**:
- ❌ More complex logic
- ❌ Requires target SSH access for detection

**Implementation**:
```bash
# Smart deployment
templedb deploy push myproject --target production --auto-detect

# Manually specify capabilities
templedb deploy push myproject --target production \
  --has-templedb --has-nix
```

### Pattern 4: Continuous Deployment Integration

**Use Case**: GitHub Actions, GitLab CI, etc.

**Flow**:
```
┌──────────────┐
│ Git Push     │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ CI Pipeline  │
│              │
│ 1. Checkout  │
│ 2. templedb  │──────┐
│    sync      │      │ Update TDB
└──────┬───────┘      │
       │              │
       │              ▼
       │        ┌──────────────┐
       │        │ TempleDB     │
       │        │ (CI Runner)  │
       │        └──────────────┘
       │
       │ 3. templedb deploy
       │
       ▼
┌──────────────┐
│ Production   │
│ Target       │
└──────────────┘
```

**Example GitHub Actions**:
```yaml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup TempleDB
        run: |
          curl -sSL https://install.templedb.dev | sh
          templedb project sync .

      - name: Deploy
        env:
          DEPLOYMENT_KEY: ${{ secrets.DEPLOYMENT_KEY }}
        run: |
          templedb deploy push $(basename $PWD) --target production
```

---

## Deployment by Project Type

### 1. CLI Tools (bza archetype)

**Characteristics**:
- Single executable or script
- Minimal runtime dependencies
- Config file + env vars
- May use SQLite for local state
- Distributed to end users

**Deployment Strategy**: **Self-Contained Binary**

#### Option A: Nix Package (Recommended)

```nix
# flake.nix
{
  description = "BZA - CLI tool";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }: {
    packages.x86_64-linux.default =
      let pkgs = nixpkgs.legacyPackages.x86_64-linux;
      in pkgs.python3Packages.buildPythonApplication {
        pname = "bza";
        version = "1.0.0";
        src = ./.;

        propagatedBuildInputs = with pkgs.python3Packages; [
          anthropic
          requests
          # ... dependencies from requirements.txt
        ];

        # Bundle SQLite database schema
        postInstall = ''
          mkdir -p $out/share/bza
          cp schema.sql $out/share/bza/
        '';
      };
  };
}
```

**Deployment**:
```bash
# Build distributable
nix build

# Install on target
nix profile install github:yourorg/bza

# Or: Build closure for non-Nix systems
nix build --out-link ./dist/bza
nix-store --export $(nix-store -qR ./dist/bza) > bza-bundle.nar

# Transfer and import on target
nix-store --import < bza-bundle.nar
```

#### Option B: PyInstaller/Nuitka (No Nix required)

```bash
# Build standalone executable
templedb deploy package bza --format pyinstaller --output ./dist/

# Creates: dist/bza (Linux), dist/bza.exe (Windows)
```

**Secret Management**:
```python
# bza/config.py
import os
from pathlib import Path

def get_config():
    """Load config with fallback chain"""
    config = {}

    # 1. Try TempleDB secrets (if available)
    try:
        from templedb_secrets import get_secret
        config['openrouter_api_key'] = get_secret('OPENROUTER_API_KEY')
    except ImportError:
        pass

    # 2. Fall back to environment variables
    if 'openrouter_api_key' not in config:
        config['openrouter_api_key'] = os.getenv('OPENROUTER_API_KEY')

    # 3. Fall back to config file
    if 'openrouter_api_key' not in config:
        config_file = Path.home() / '.config' / 'bza' / 'config.json'
        if config_file.exists():
            import json
            file_config = json.load(config_file.open())
            config['openrouter_api_key'] = file_config.get('openrouter_api_key')

    # 4. Fail with helpful message
    if 'openrouter_api_key' not in config:
        raise ValueError(
            "OPENROUTER_API_KEY not found. Set it via:\n"
            "  1. Environment: export OPENROUTER_API_KEY=sk-...\n"
            "  2. Config file: ~/.config/bza/config.json\n"
            "  3. TempleDB: templedb secret set bza OPENROUTER_API_KEY sk-..."
        )

    return config
```

**Distribution**:
```bash
# Via Nix (best)
nix profile install github:yourorg/bza

# Via pip (requires Python)
pip install bza

# Via direct download (standalone binary)
curl -L https://github.com/yourorg/bza/releases/latest/download/bza-linux-x64 -o bza
chmod +x bza
sudo mv bza /usr/local/bin/
```

---

### 2. Web Services (woofs_projects archetype)

**Characteristics**:
- Long-running process
- Database backend (PostgreSQL/Supabase)
- Environment-specific config
- Static assets
- Potentially multiple services (frontend + backend)

**Deployment Strategy**: **Container or Systemd Service**

#### Architecture

```
┌──────────────────────────────────────┐
│ Frontend (Next.js/React)             │
│ - Static generation or SSR           │
│ - Deployed to Vercel/Netlify         │
│   or served by Nginx                 │
└─────────────┬────────────────────────┘
              │ API calls
              │
              ▼
┌──────────────────────────────────────┐
│ Backend (FastAPI/Express)            │
│ - REST/GraphQL API                   │
│ - WebSocket for real-time            │
│ - Deployed as container or systemd   │
└─────────────┬────────────────────────┘
              │ SQL queries
              │
              ▼
┌──────────────────────────────────────┐
│ Database (PostgreSQL/Supabase)       │
│ - Managed service or self-hosted     │
│ - Migrations tracked by TempleDB     │
└──────────────────────────────────────┘
```

#### Deployment Flow

**Step 1: Database Preparation**

```bash
# Create migration from TempleDB schema
templedb migration generate woofs_projects \
  --from-schema schema.sql \
  --output migrations/001_initial.sql

# Apply migrations to target database
templedb migration apply woofs_projects \
  --target production \
  --connection $DATABASE_URL
```

**Step 2: Backend Deployment**

##### Option A: Docker (recommended for VPS)

```dockerfile
# Dockerfile (generated by TempleDB)
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Runtime user (non-root)
RUN useradd -m appuser
USER appuser

# Health check
HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Deployment**:
```bash
# Build and push
templedb deploy package woofs_projects --format docker --push

# Or: Generate docker-compose.yml
templedb deploy compose woofs_projects --output docker-compose.yml

# On target
docker compose pull
docker compose up -d
```

##### Option B: Systemd Service (for VPS without Docker)

```bash
# Generate systemd unit
templedb deploy systemd woofs_projects --output woofs-backend.service

# Transfer and install
scp woofs-backend.service production:/etc/systemd/system/
ssh production 'systemctl enable --now woofs-backend'
```

**Step 3: Frontend Deployment**

##### Vercel (easiest for Next.js)

```bash
# templedb-vercel.json (generated)
{
  "buildCommand": "npm run build",
  "outputDirectory": ".next",
  "env": {
    "NEXT_PUBLIC_API_URL": "@woofs-api-url",
    "DATABASE_URL": "@woofs-database-url"
  }
}

# Deploy
templedb deploy vercel woofs_projects --frontend-only
```

##### Static hosting (Nginx)

```bash
# Build frontend
cd frontend && npm run build

# Deploy static files
templedb deploy static woofs_projects \
  --source frontend/out \
  --target production-cdn
```

**Secret Injection**:

```python
# backend/config.py
import os
from typing import Optional

class Config:
    """Configuration with fallback chain"""

    @staticmethod
    def get_database_url() -> str:
        """Get database URL with fallbacks"""
        # 1. Production: Environment variable (from systemd/docker)
        if url := os.getenv('DATABASE_URL'):
            return url

        # 2. TempleDB secret (if running locally with TDB)
        try:
            from templedb import get_secret
            if url := get_secret('woofs_projects', 'DATABASE_URL'):
                return url
        except ImportError:
            pass

        # 3. Local development: SQLite fallback
        if os.getenv('ENV') == 'development':
            return 'sqlite:///./dev.db'

        raise ValueError(
            "DATABASE_URL not configured. Set via:\n"
            "  1. Environment: DATABASE_URL=postgresql://...\n"
            "  2. TempleDB: templedb secret set woofs_projects DATABASE_URL postgresql://..."
        )

    @staticmethod
    def get_api_key(service: str) -> Optional[str]:
        """Get external service API key with fallbacks"""
        key_name = f'{service.upper()}_API_KEY'

        # Same fallback chain
        return (
            os.getenv(key_name) or
            try_templedb_secret(key_name) or
            None
        )

# Load config
config = Config()
DATABASE_URL = config.get_database_url()
```

**Deployment Orchestration**:

```bash
# Full deployment (coordinated)
templedb deploy run woofs_projects --target production

# This executes:
# 1. Apply database migrations
# 2. Build and deploy backend
# 3. Build and deploy frontend
# 4. Run smoke tests
# 5. Update deployment_history table
```

---

### 3. Games

**Characteristics**:
- Client-side rendering (WebGL, Canvas, WebAssembly)
- Asset loading (images, audio, 3D models)
- State persistence (localStorage, backend)
- Multiplayer: WebSocket server
- Physics/game loop optimization

**Deployment Strategy**: **Static Frontend + Optional Game Server**

#### Architecture

```
┌──────────────────────────────────────┐
│ Game Client (Browser)                │
│                                      │
│ - Phaser/PixiJS/Three.js             │
│ - Bundled assets                     │
│ - Local state (localStorage)         │
└────────┬─────────────────────────────┘
         │
         │ WebSocket (if multiplayer)
         │ REST (leaderboards, profiles)
         │
         ▼
┌──────────────────────────────────────┐
│ Game Server (Optional)               │
│                                      │
│ - Node.js + Socket.io / ws           │
│ - Game state synchronization         │
│ - Authoritative physics              │
└────────┬─────────────────────────────┘
         │
         │ Persist state
         │
         ▼
┌──────────────────────────────────────┐
│ Database (PostgreSQL/Redis)          │
│ - Player profiles                    │
│ - Game saves                         │
│ - Leaderboards                       │
└──────────────────────────────────────┘
```

#### Client Deployment

**Build Pipeline**:
```bash
# templedb generates build config
templedb deploy package mygame --format static

# Internally:
# 1. Bundle JavaScript (esbuild/vite)
# 2. Optimize assets (image compression, audio encoding)
# 3. Generate service worker (for offline play)
# 4. Create index.html with asset preloading
```

**Output Structure**:
```
dist/
├── index.html          # Entry point
├── assets/
│   ├── images/         # Compressed PNGs/WebP
│   ├── audio/          # Compressed OGG/MP3
│   └── models/         # glTF/GLB files
├── js/
│   ├── game.bundle.js  # Minified game logic
│   └── vendor.bundle.js # Libraries (Phaser, etc.)
└── sw.js               # Service worker for offline
```

**Deployment Targets**:

1. **Static Hosting (Netlify/Vercel/Cloudflare Pages)**
   ```bash
   templedb deploy static mygame --provider netlify
   ```

2. **GitHub Pages**
   ```bash
   templedb deploy github-pages mygame
   ```

3. **Itch.io**
   ```bash
   # Generate itch.io-compatible build
   templedb deploy itch mygame --output itch-build.zip
   ```

4. **Self-hosted (Nginx)**
   ```bash
   templedb deploy nginx mygame --target game-server
   ```

#### Multiplayer Server Deployment

**Server Code** (`server.js`):
```javascript
// Game server with state sync
import { WebSocketServer } from 'ws';
import { createServer } from 'http';

const server = createServer();
const wss = new WebSocketServer({ server });

// Game rooms
const rooms = new Map();

wss.on('connection', (ws) => {
  // Handle player join, game state sync, etc.
});

server.listen(process.env.PORT || 8080);
```

**Deployment**:
```bash
# Container deployment
templedb deploy package mygame-server --format docker

# Or: Serverless (for lighter multiplayer)
templedb deploy cloudflare-workers mygame-server
```

**State Persistence**:
```javascript
// Game save to backend
async function saveGame(playerId, gameState) {
  // Try backend API
  try {
    await fetch(`${API_URL}/save`, {
      method: 'POST',
      body: JSON.stringify({ playerId, gameState }),
      headers: { 'Authorization': `Bearer ${authToken}` }
    });
  } catch (err) {
    // Fallback to localStorage
    localStorage.setItem(`game_save_${playerId}`, JSON.stringify(gameState));
    console.warn('Saved locally (offline)');
  }
}
```

---

## Secret Management & Fallback Strategies

### Multi-Layer Secret Resolution

The secret resolution follows a **priority chain**:

```
1. TempleDB Secrets (production, encrypted)
   ↓ (if not available)
2. Environment Variables (CI/CD, systemd)
   ↓ (if not available)
3. .env File (local development)
   ↓ (if not available)
4. Config File (~/.config/app/config.json)
   ↓ (if not available)
5. Interactive Prompt (CLI tools only)
   ↓ (if not available)
6. Error with clear instructions
```

### Implementation

**Python**:
```python
# common/secrets.py
from pathlib import Path
import os
import json
from typing import Optional

def get_secret(key: str, project: Optional[str] = None) -> str:
    """
    Get secret with fallback chain.

    Priority:
    1. TempleDB (if available)
    2. Environment variable
    3. .env file
    4. Config file
    5. Error
    """
    # 1. TempleDB
    if project:
        try:
            import subprocess
            result = subprocess.run(
                ['templedb', 'secret', 'get', project, key],
                capture_output=True,
                text=True,
                check=True
            )
            if result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    # 2. Environment variable
    if value := os.getenv(key):
        return value

    # 3. .env file
    env_file = Path.cwd() / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f'{key}='):
                return line.split('=', 1)[1].strip().strip('"\'')

    # 4. Config file
    config_file = Path.home() / '.config' / (project or 'app') / 'config.json'
    if config_file.exists():
        config = json.loads(config_file.read_text())
        if key in config:
            return config[key]

    # 5. Error
    raise ValueError(
        f"Secret '{key}' not found. Set it via:\n"
        f"  • TempleDB: templedb secret set {project or 'PROJECT'} {key} VALUE\n"
        f"  • Environment: export {key}=VALUE\n"
        f"  • File: echo '{key}=VALUE' >> .env\n"
        f"  • Config: ~/.config/{project or 'app'}/config.json"
    )
```

**JavaScript**:
```javascript
// lib/secrets.js
import { readFileSync, existsSync } from 'fs';
import { homedir } from 'os';
import { join } from 'path';
import { execSync } from 'child_process';

export function getSecret(key, project = null) {
  // 1. TempleDB
  if (project) {
    try {
      const result = execSync(
        `templedb secret get ${project} ${key}`,
        { encoding: 'utf-8', stdio: 'pipe' }
      );
      if (result.trim()) return result.trim();
    } catch {}
  }

  // 2. Environment variable
  if (process.env[key]) return process.env[key];

  // 3. .env file
  const envFile = join(process.cwd(), '.env');
  if (existsSync(envFile)) {
    const line = readFileSync(envFile, 'utf-8')
      .split('\n')
      .find(l => l.startsWith(`${key}=`));
    if (line) return line.split('=')[1].trim().replace(/['"]/g, '');
  }

  // 4. Config file
  const configFile = join(homedir(), '.config', project || 'app', 'config.json');
  if (existsSync(configFile)) {
    const config = JSON.parse(readFileSync(configFile, 'utf-8'));
    if (config[key]) return config[key];
  }

  // 5. Error
  throw new Error(
    `Secret '${key}' not found. Set it via:\n` +
    `  • TempleDB: templedb secret set ${project || 'PROJECT'} ${key} VALUE\n` +
    `  • Environment: export ${key}=VALUE\n` +
    `  • File: echo '${key}=VALUE' >> .env\n` +
    `  • Config: ~/.config/${project || 'app'}/config.json`
  );
}
```

### Environment-Specific Secrets

**Structure**:
```
secrets/
├── development/
│   ├── DATABASE_URL = sqlite:///dev.db
│   └── API_KEY = demo-key-1234
├── staging/
│   ├── DATABASE_URL = postgresql://staging.db
│   └── API_KEY = <real-staging-key>
└── production/
    ├── DATABASE_URL = postgresql://prod.db (encrypted)
    └── API_KEY = <real-prod-key> (encrypted)
```

**Usage**:
```bash
# Development (unencrypted, can commit to VCS)
templedb secret set myproject DATABASE_URL sqlite:///dev.db --env development

# Production (encrypted with age)
templedb secret set myproject DATABASE_URL postgresql://... --env production

# Retrieve
templedb secret get myproject DATABASE_URL --env production
```

### Secret Injection at Deployment

**Docker**:
```bash
# Inject secrets as environment variables
templedb deploy run myproject --target production \
  --inject-secrets  # Fetches from TempleDB and passes to container
```

**Systemd**:
```ini
# Generated by TempleDB
[Service]
EnvironmentFile=/etc/myproject/secrets.env  # Generated at deploy time
ExecStart=/usr/local/bin/myproject
```

**Serverless (Vercel)**:
```bash
# Sync TempleDB secrets to Vercel
templedb deploy vercel myproject --sync-secrets

# Internally runs:
# vercel env add DATABASE_URL production < (templedb secret get ...)
```

---

## Cathedral Integration

### Cathedral Package Format

A `.cathedral` package is a content-addressable, deduplicated project bundle:

```
myproject.cathedral        # Tarball or directory
├── manifest.json          # Project metadata
├── blobs/                 # Content-addressed blobs (SHA-256)
│   ├── a3f5e2... (zlib)  # Deduplicated file content
│   ├── b8c1d9... (zlib)
│   └── ...
├── vcs/                   # Version control history
│   ├── commits.json
│   ├── branches.json
│   └── refs.json
├── environments/          # Environment configs
│   ├── development.json
│   ├── staging.json
│   └── production.json (secrets excluded)
└── metadata/
    ├── dependencies.json  # Lock files, package manifests
    ├── migrations/        # Database migrations
    └── deploy.sh          # Optional deployment script
```

### Cathedral Workflow

#### 1. Export from Source TempleDB

```bash
# Full export
templedb cathedral export myproject \
  --output /tmp/myproject.cathedral \
  --compress

# Selective export (exclude large assets)
templedb cathedral export myproject \
  --exclude '*.mp4' \
  --exclude 'node_modules/' \
  --exclude-history  # Omit VCS history for faster transfer
```

#### 2. Transfer

**Option A: Direct SCP**
```bash
scp /tmp/myproject.cathedral deploy@target:/opt/cathedral/
```

**Option B: S3/Object Storage**
```bash
# Upload to S3
aws s3 cp myproject.cathedral s3://deployments/myproject-2026-03-21.cathedral

# Download on target
aws s3 cp s3://deployments/myproject-2026-03-21.cathedral ./
```

**Option C: Cathedral Registry** (future enhancement)
```bash
# Push to cathedral registry
templedb cathedral push myproject --registry https://cathedral.example.com

# Pull on target
templedb cathedral pull myproject --registry https://cathedral.example.com
```

#### 3. Import on Target TempleDB

```bash
# Import cathedral
templedb cathedral import /opt/cathedral/myproject.cathedral

# Verify
templedb project show myproject

# Deploy
templedb deploy run myproject --target production
```

### Cathedral Benefits for Deployment

1. **Deduplication**: Shared blobs (e.g., common libraries) are stored once
2. **Incremental Updates**: Only changed blobs need transfer
3. **Integrity**: SHA-256 hashes verify blob integrity
4. **VCS Preservation**: Full git history available on target
5. **Reproducibility**: Exact source code state captured

### Cathedral + Deployment Cache

When both source and target have TempleDB:

```
Source TDB                    Target TDB
┌─────────────┐              ┌─────────────┐
│ Project A   │              │ Project A   │
│ - blob X    │──────────────│ - blob X    │ (deduplicated)
│ - blob Y    │  Cathedral   │ - blob Y    │
│ - blob Z    │──────────────│ - blob Z    │
│             │              │             │
│ Deploy      │              │ Deploy      │
│ Cache:      │              │ Cache:      │
│ hash(Y+Z)   │──────────────│ hash(Y+Z)   │ (reused!)
│ → artifact  │  Transfer    │ → artifact  │
└─────────────┘              └─────────────┘
```

**Result**: If `blob Y` and `blob Z` haven't changed, the deployment artifact is **reused** on the target, avoiding redundant builds.

---

## Target Environment Detection

### Detection Script

```bash
#!/bin/bash
# templedb-detect-target.sh
# Detect target system capabilities

detect_capabilities() {
  local target=$1  # SSH target (user@host)

  echo "🔍 Detecting capabilities on $target..."

  # SSH command executor
  run_remote() {
    ssh "$target" "$1" 2>/dev/null
  }

  # Detect TempleDB
  has_templedb=false
  if run_remote "command -v templedb" >/dev/null; then
    has_templedb=true
    tdb_version=$(run_remote "templedb --version")
  fi

  # Detect Nix
  has_nix=false
  if run_remote "command -v nix" >/dev/null; then
    has_nix=true
    nix_version=$(run_remote "nix --version")
  fi

  # Detect Docker
  has_docker=false
  if run_remote "command -v docker" >/dev/null; then
    has_docker=true
    docker_version=$(run_remote "docker --version")
  fi

  # Detect init system
  init_system="unknown"
  if run_remote "command -v systemctl" >/dev/null; then
    init_system="systemd"
  elif run_remote "command -v rc-service" >/dev/null; then
    init_system="openrc"
  fi

  # Detect package managers
  package_managers=()
  run_remote "command -v apt-get" >/dev/null && package_managers+=(apt)
  run_remote "command -v dnf" >/dev/null && package_managers+=(dnf)
  run_remote "command -v pacman" >/dev/null && package_managers+=(pacman)

  # Detect databases
  databases=()
  run_remote "command -v psql" >/dev/null && databases+=(postgresql)
  run_remote "command -v mysql" >/dev/null && databases+=(mysql)
  run_remote "command -v sqlite3" >/dev/null && databases+=(sqlite)

  # Output JSON
  cat <<EOF
{
  "has_templedb": $has_templedb,
  "has_nix": $has_nix,
  "has_docker": $has_docker,
  "init_system": "$init_system",
  "package_managers": [$(IFS=,; echo "${package_managers[*]/#/\"}"; echo "${package_managers[*]/%/\"}")],
  "databases": [$(IFS=,; echo "${databases[*]/#/\"}"; echo "${databases[*]/%/\"}")]
}
EOF
}

detect_capabilities "$1"
```

### Smart Deployment Selection

```python
# deployment_strategy.py
import json
import subprocess

def select_deployment_strategy(target: str, project: str) -> str:
    """
    Select optimal deployment strategy based on target capabilities.

    Returns: 'cathedral', 'nix-closure', 'docker', or 'tarball'
    """
    # Detect target
    result = subprocess.run(
        ['templedb-detect-target.sh', target],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"⚠️  Target detection failed, using fallback (tarball)")
        return 'tarball'

    capabilities = json.loads(result.stdout)

    # Decision tree
    if capabilities['has_templedb']:
        print("✅ Target has TempleDB → Using Cathedral")
        return 'cathedral'

    elif capabilities['has_nix']:
        print("✅ Target has Nix → Using Nix closure")
        return 'nix-closure'

    elif capabilities['has_docker']:
        print("✅ Target has Docker → Using Docker image")
        return 'docker'

    else:
        print("ℹ️  Target has basic capabilities → Using standalone tarball")
        return 'tarball'
```

**Usage**:
```bash
# Auto-detect and deploy
templedb deploy push myproject --target production --auto-detect

# Force specific strategy
templedb deploy push myproject --target production --strategy cathedral
```

---

## Comparison Matrices

### Deployment Strategy Comparison

| Strategy | Target Requirements | Artifact Size | Reproducibility | Setup Complexity | Best For |
|----------|-------------------|---------------|-----------------|------------------|----------|
| **Cathedral** | TempleDB | Small (dedup) | ⭐⭐⭐⭐⭐ | Medium | TDB → TDB |
| **Nix Closure** | Nix | Medium | ⭐⭐⭐⭐⭐ | Medium | VPS, NixOS |
| **Docker** | Docker | Large | ⭐⭐⭐⭐ | Low | VPS, Cloud |
| **Systemd Service** | systemd + pkgmgr | Small | ⭐⭐⭐ | High | Traditional Linux |
| **Standalone Tarball** | None | Large | ⭐⭐ | Low | Any Linux |
| **Serverless** | Platform-specific | N/A | ⭐⭐⭐⭐ | Low | Vercel, Netlify |

### Project Type Deployment Matrix

| Project Type | Recommended Primary | Acceptable Alternatives | Not Recommended |
|-------------|-------------------|------------------------|-----------------|
| **CLI Tools** | Nix, Standalone Binary | PyInstaller, Docker | Systemd |
| **Web Services** | Docker, Systemd | Nix Closure, Serverless | Standalone |
| **Games (client)** | Static Hosting | CDN, GitHub Pages | Docker |
| **Games (server)** | Docker, Systemd | Cloudflare Workers | Standalone |

### Secret Management Comparison

| Method | Security | Portability | Developer UX | Best For |
|--------|----------|-------------|--------------|----------|
| **TempleDB Secrets** | ⭐⭐⭐⭐⭐ (age) | Medium | ⭐⭐⭐⭐ | Production |
| **Environment Variables** | ⭐⭐⭐ | High | ⭐⭐⭐ | CI/CD |
| **.env File** | ⭐⭐ (git-ignored) | High | ⭐⭐⭐⭐⭐ | Local dev |
| **Config File** | ⭐⭐ | Medium | ⭐⭐⭐ | CLI tools |
| **Vault (HashiCorp)** | ⭐⭐⭐⭐⭐ | Low | ⭐⭐ | Enterprise |

---

## Implementation Roadmap

### Phase 1: Core Deployment Infrastructure (Week 1-2)

**Goal**: Establish foundation for multi-strategy deployment

Tasks:
1. ✅ **Target Detection**
   - Implement `templedb-detect-target.sh`
   - Add detection results to deployment cache

2. ✅ **Deployment Strategy Selection**
   - Auto-select based on capabilities
   - Allow manual override with `--strategy` flag

3. ✅ **Secret Fallback Chain**
   - Implement `get_secret()` helper in Python/JS
   - Add example `.env.example` generation
   - Document secret setup

4. ✅ **Cathedral Remote Sync** (enhancement)
   - `templedb cathedral push --target ssh://user@host`
   - Automatic transfer + import on target

**Deliverables**:
- [ ] `src/services/deployment_strategy_service.py`
- [ ] `scripts/templedb-detect-target.sh`
- [ ] `src/utils/secrets.py` and `lib/secrets.js`
- [ ] Updated `cathedral.py` with remote push/pull

### Phase 2: Project Type Templates (Week 3-4)

**Goal**: Provide out-of-the-box deployment for common project types

Tasks:
1. ✅ **CLI Tool Template**
   - Nix flake generator
   - PyInstaller config generator
   - Secret fallback boilerplate

2. ✅ **Web Service Template**
   - Dockerfile generator (multi-stage builds)
   - docker-compose.yml generator
   - Systemd service unit generator
   - Migration runner integration

3. ✅ **Game Template**
   - Vite/esbuild config for bundling
   - Asset optimization pipeline
   - Service worker generation (offline support)
   - Multiplayer server template (Socket.io)

**Deliverables**:
- [ ] `templedb deploy init <project> --type cli`
- [ ] `templedb deploy init <project> --type web-service`
- [ ] `templedb deploy init <project> --type game`

### Phase 3: Database & Migration Management (Week 5)

**Goal**: Seamless database deployment

Tasks:
1. ✅ **Migration Tracking**
   - Track applied migrations per target
   - `templedb migration status <project> --target production`

2. ✅ **SQLite → PostgreSQL Migration**
   - Schema converter
   - Data migration scripts
   - Validation

3. ✅ **Supabase Integration**
   - Auto-configure Supabase projects
   - Edge function deployment
   - RLS policy generation

**Deliverables**:
- [ ] `templedb migration apply <project> --target <target>`
- [ ] `templedb migration convert <project> --from sqlite --to postgresql`
- [ ] Supabase CLI integration

### Phase 4: CI/CD Integration (Week 6)

**Goal**: GitHub Actions, GitLab CI integration

Tasks:
1. ✅ **GitHub Actions Workflow Generator**
   - `.github/workflows/deploy.yml` template
   - Secrets sync from TempleDB to GitHub

2. ✅ **GitLab CI Integration**
   - `.gitlab-ci.yml` template

3. ✅ **Deployment Notifications**
   - Slack/Discord webhook on deploy
   - Deployment status dashboard

**Deliverables**:
- [ ] `templedb deploy init-ci <project> --provider github`
- [ ] `templedb deploy init-ci <project> --provider gitlab`

### Phase 5: Advanced Features (Week 7+)

**Goal**: Production-grade deployment features

Tasks:
1. ✅ **Blue-Green Deployment**
   - Deploy new version alongside old
   - Switch traffic atomically
   - Rollback capability

2. ✅ **Canary Deployment**
   - Gradual rollout (1% → 10% → 100%)
   - Automatic rollback on errors

3. ✅ **Deployment Rollback**
   - `templedb deploy rollback <project> --target production`
   - Restore previous deployment from cache

4. ✅ **Health Checks & Monitoring**
   - Post-deployment health checks
   - Integration with monitoring (Prometheus, DataDog)

**Deliverables**:
- [ ] `templedb deploy run <project> --strategy blue-green`
- [ ] `templedb deploy rollback <project>`
- [ ] Health check framework

---

## Conclusion

This architectural review establishes a comprehensive deployment framework for TempleDB-managed projects. The key principles are:

1. **Adaptability**: Deploy to diverse environments (TempleDB-enabled or bare systems)
2. **Fallback Resilience**: Graceful degradation for missing dependencies/secrets
3. **Cathedral Optimization**: Leverage TempleDB infrastructure when available
4. **Developer Experience**: Simple commands with intelligent defaults

**Next Steps**:
1. Review this document with team
2. Prioritize Phase 1 tasks
3. Implement core deployment infrastructure
4. Test with bza, woofs_projects, and a game project

**Success Metrics**:
- [ ] Deploy bza CLI tool with `templedb deploy run bza`
- [ ] Deploy woofs_projects web service with zero manual configuration
- [ ] Deploy a game (client + server) with asset optimization
- [ ] Achieve <5 minute deployment time for typical projects
- [ ] 100% secret fallback coverage (no hardcoded credentials)

---

**Document Status**: Draft for Review
**Author**: TempleDB Architecture Team
**Last Updated**: 2026-03-21
