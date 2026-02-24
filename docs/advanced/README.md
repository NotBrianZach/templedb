# Advanced Topics

Specialized documentation for power users, system administrators, and contributors.

---

## Performance & Deployment

### [ADVANCED.md](ADVANCED.md)
**Topics:**
- Performance tuning (connection pooling, WAL mode, batch operations)
- Nix environment management and FHS environments
- Deployment orchestration and multi-component projects
- Database optimization (indexes, query patterns, caching)
- Profiling and benchmarking

**For:** Users optimizing performance, deploying to production, or using Nix environments.

---

## Building & Development

### [BUILD.md](BUILD.md)
**Topics:**
- Building TempleDB from source
- Development environment setup
- Running tests
- Contributing guidelines
- Packaging for different platforms

**For:** Contributors and developers extending TempleDB.

---

## Multi-User & Teams

### [CATHEDRAL.md](CATHEDRAL.md)
**Topics:**
- Cathedral package format (project export/import)
- Multi-user collaboration workflows
- Shared database setup
- Access control patterns
- Team coordination strategies

**For:** Teams sharing projects, system administrators managing shared TempleDB instances.

---

## Security

### [SECURITY.md](SECURITY.md)
**Topics:**
- Secret management with age encryption
- Database access control
- Secure deployment practices
- Key management best practices
- Threat model and security considerations

**For:** Security-conscious users, system administrators, enterprise deployments.

---

## Cloud Backup

### [CLOUD_BACKUP.md](CLOUD_BACKUP.md)
**Topics:**
- Cloud backup setup (Google Drive, AWS S3, Dropbox)
- Automated backup scheduling with cron
- Backup retention policies and cleanup
- Safe restore procedures
- Pluggable provider system

**For:** Users wanting automated backups to cloud storage.

---

## Architecture & Patterns

### [REPOSITORY_PATTERN.md](REPOSITORY_PATTERN.md)
**Topics:**
- Repository pattern implementation
- Clean architecture principles
- Database abstraction layer
- Testing with mocked repositories
- SOLID principles applied

**For:** Developers understanding TempleDB's architecture or contributing code.

### [FILES.md](FILES.md)
**Topics:**
- File tracking and versioning system
- Content-addressable storage
- Deduplication strategy
- Checkout/commit workflows
- Conflict detection

**For:** Understanding how TempleDB stores and tracks files.

---

## VCS & Operations

### [STAGING_OPERATIONS.md](STAGING_OPERATIONS.md)
**Topics:**
- VCS staging area usage
- Selective commits
- Staging workflows
- Command reference

**For:** Users working with TempleDB's version control system.

### [TUI_VCS_ENHANCEMENTS.md](TUI_VCS_ENHANCEMENTS.md)
**Topics:**
- Interactive staging in TUI
- Commit creation from TUI
- Viewing diffs and commit history
- VCS workflows in terminal UI

**For:** Users preferring the terminal UI for VCS operations.

---

## Getting Started with Advanced Features

### If You Want To...

**Improve Performance:**
→ Start with [ADVANCED.md](ADVANCED.md) → Performance Tuning section

**Deploy to Production:**
→ Read [ADVANCED.md](ADVANCED.md) → Deployment + [SECURITY.md](SECURITY.md)

**Set Up Team Collaboration:**
→ Read [CATHEDRAL.md](CATHEDRAL.md) → Multi-User Setup

**Contribute Code:**
→ Read [BUILD.md](BUILD.md) → Development Setup

**Use Nix Environments:**
→ Read [ADVANCED.md](ADVANCED.md) → Nix Environment Management

**Setup Cloud Backups:**
→ Read [CLOUD_BACKUP.md](CLOUD_BACKUP.md) → Quick Start

**Understand VCS Staging:**
→ Read [STAGING_OPERATIONS.md](STAGING_OPERATIONS.md) → Commands

**Learn Architecture:**
→ Read [REPOSITORY_PATTERN.md](REPOSITORY_PATTERN.md) → Overview

---

## Prerequisites

Before diving into advanced topics, you should be familiar with:
- ✓ Basic TempleDB usage ([GETTING_STARTED.md](../../GETTING_STARTED.md))
- ✓ Project import/sync workflows ([GUIDE.md](../../GUIDE.md))
- ✓ SQL querying ([EXAMPLES.md](../../EXAMPLES.md))
- ✓ Database constraints ([QUERY_BEST_PRACTICES.md](../../QUERY_BEST_PRACTICES.md))

---

## Support

For questions about advanced features:
- Check the relevant documentation first
- Search existing issues: https://github.com/anthropics/templedb/issues
- Ask in discussions: https://github.com/anthropics/templedb/discussions
