# TempleDB Documentation

## Quick Links

- **[Workflows](WORKFLOWS.md)** - Execute multi-phase operations with code intelligence
- **[Getting Started](../GETTING_STARTED.md)** - Install and basic usage
- **[MCP Integration](MCP_INTEGRATION.md)** - Use with Claude Code and AI agents

## Core Features

### Workflows
- [Workflows Guide](WORKFLOWS.md) - Quick reference for workflows
- [Phase 2 Design](phases/PHASE_2_DESIGN.md) - Architecture and patterns
- Workflow files: `../workflows/*.yaml`

### Code Intelligence
- [Code Intelligence Status](../CODE_INTELLIGENCE_STATUS.md) - Phase 1 features
- Symbol extraction, dependency graphs, impact analysis
- Hybrid search with BM25 + graph ranking
- Leiden algorithm for architectural boundaries

### MCP Server
- [MCP Integration](MCP_INTEGRATION.md) - MCP server setup
- [MCP Quick Reference](MCP_QUICK_REFERENCE.md) - Available tools
- 46 MCP tools (8 code intelligence + 4 workflow + 34 others)

## Features by Category

### Deployment
- [Deployment Guide](DEPLOYMENT.md) - Deployment modes
- [NixOps4 Integration](NIXOPS4_INTEGRATION.md) - NixOS deployments
- [FHS Deployments](FHS_DEPLOYMENTS.md) - Filesystem Hierarchy Standard

### Secrets Management
- [Secrets Guide](SECRETS.md) - Age-encrypted secrets with Yubikey
- [Multi-Key Setup](MULTI_KEY_SECRET_MANAGEMENT.md) - Multiple Yubikeys
- [Individual Secrets](INDIVIDUAL_SECRETS_DESIGN.md) - Per-secret encryption

### Development
- [Installation](INSTALL.md) - Install TempleDB
- [Examples](../EXAMPLES.md) - Usage examples
- [Design Philosophy](../DESIGN_PHILOSOPHY.md) - Project principles

## Phase Completion Documentation

Detailed implementation docs for each phase:

### Code Intelligence (Phase 1)
- [Phase 1.3](phases/PHASE_1_3_COMPLETE.md) - Dependency graph & impact analysis
- [Phase 1.4](phases/PHASE_1_4_COMPLETE.md) - Call site tracking
- [Phase 1.5](phases/PHASE_1_5_COMPLETE.md) - Code clustering (Leiden)
- [Phase 1.6](phases/PHASE_1_6_COMPLETE.md) - Hybrid search
- [Phase 1.7](phases/PHASE_1_7_COMPLETE.md) - MCP tools for code intelligence

### Workflow Orchestration (Phase 2)
- [Phase 2 Design](phases/PHASE_2_DESIGN.md) - Architecture & patterns
- [Phase 2.1](phases/PHASE_2_1_COMPLETE.md) - Workflow engine
- [Phase 2.2](phases/PHASE_2_2_COMPLETE.md) - MCP workflow tools
- [Phase 2.3](phases/PHASE_2_3_COMPLETE.md) - Safe deployment workflow
- [Phase 2.5](phases/PHASE_2_5_COMPLETE.md) - Testing & docs

## Advanced Topics

- [Migrations](MIGRATIONS.md) - Database schema migrations
- [Vibe Coding](VIBE.md) - AI-assisted development workflow
- [Lock Files](LOCK_FILES.md) - Dependency lock file enforcement
- [Error Handling](ERROR_HANDLING.md) - Structured error handling

## Reference

- [System Config](SYSTEM_CONFIG_REFERENCE.md) - Configuration reference
- [VCS Metadata](VCS_METADATA_GUIDE.md) - Version control tracking
- [Safe Queries](SAFE_QUERIES_USAGE.md) - Parameterized SQL queries

## Legacy Documentation

Older docs in `../archive/` - kept for reference but may be outdated.
