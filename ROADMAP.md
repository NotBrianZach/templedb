# TempleDB Roadmap

Future development plans and feature priorities for TempleDB.

---

## Current Version: 0.5.0 (Unreleased)

See [CHANGELOG.md](CHANGELOG.md) for completed features in this release.

**Recent Additions:**
- ✅ Unified CLI with all operations
- ✅ Performance optimizations (connection pooling, query optimization)
- ✅ VCS commands (commit, status, log, branch)
- ✅ Search commands (content, files)
- ✅ Backup/restore functionality
- ✅ Shell completion (bash/zsh)
- ✅ Nix FHS environments with auto-detection

---

## Next Cycle: Version 0.6.0

### Priority 1: Version Control Enhancements

**File Diff Viewer**
- Visual diff between file versions
- Side-by-side and unified diff formats
- Integration with TUI
- CLI command: `templedb vcs diff <file> [version1] [version2]`

**Implementation:**
```python
def cmd_vcs_diff(args):
    """Show diff between file versions"""
    # Query file_versions and file_diffs tables
    # Generate unified or side-by-side diff
    # Color output for terminal
```

**Staging Area Operations**
- `templedb vcs add <files>` - Stage files
- `templedb vcs reset <files>` - Unstage files
- `templedb vcs diff --staged` - Show staged changes

**Merge Request Workflow**
- Create merge requests via CLI
- List and review merge requests
- Approve/reject merge requests
- TUI screen for merge request management

### Priority 2: Search & Analysis

**Full-Text Search with FTS5**
- Migrate content search to SQLite FTS5
- Faster, more powerful search capabilities
- Ranking and relevance scoring
- Search across all projects instantly

**Schema changes:**
```sql
CREATE VIRTUAL TABLE file_contents_fts USING fts5(
    content_text,
    content=file_contents,
    content_rowid=id
);

CREATE TRIGGER file_contents_ai AFTER INSERT ON file_contents BEGIN
  INSERT INTO file_contents_fts(rowid, content_text)
  VALUES (new.id, new.content_text);
END;
```

**Dependency Graph Visualization**
- Map file dependencies across projects
- Generate dependency graphs
- Detect circular dependencies
- Export to GraphViz/Mermaid

**Code Metrics Dashboard**
- Complexity analysis per file
- Code churn metrics
- Test coverage tracking (if test results imported)
- Language distribution

### Priority 3: Real-Time Features

**Watch Mode**
- Auto-update database when files change
- `templedb project watch <project>`
- Uses inotify/fsevents
- Incremental updates (100x faster than re-import)

**Implementation:**
```python
# src/file_watcher.py
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ProjectWatcher(FileSystemEventHandler):
    def on_modified(self, event):
        # Update file_contents
        # Create file_change_event
        # Update VCS working_state
```

**Live TUI Updates**
- Refresh screens automatically when data changes
- Show real-time commit activity
- Monitor environment usage
- Database statistics auto-update

### Priority 4: Deployment & CI/CD

**Deployment Tracking Enhancements**
- Record deployment history
- Track deployment status (pending, success, failed)
- Link deployments to commits
- Rollback capabilities

**CI/CD Integration**
- GitHub Actions integration
- GitLab CI integration
- Store build artifacts in database
- Test result tracking

**Environment Variables Management**
- Secure storage of environment variables
- Per-environment variable sets
- Encryption for sensitive values
- CLI: `templedb env vars set/get/list`

### Priority 5: TUI Enhancements

**Commit Creation in TUI**
- VCS screen: Press 'c' to create commit
- Interactive commit message editor
- Automatic author detection
- Show staged changes before commit

**SQL Query Builder**
- Interactive query construction
- Save and reuse queries
- Export results to CSV/JSON
- Query history

**File Editor Integration**
- Edit files directly from TUI
- Track editing sessions
- Show unsaved changes
- Multi-file editing improvements

**Pagination & Virtual Scrolling**
- Handle large result sets (1000+ rows)
- Lazy loading of data
- Smooth scrolling performance
- Memory efficiency

---

## Future: Version 0.7.0+

### Advanced VCS Features

**Branch Merging**
- Merge branches in database
- Conflict detection
- Interactive conflict resolution
- Merge commit creation

**Cherry-Pick & Rebase**
- Cherry-pick commits between branches
- Interactive rebase
- Commit rewriting
- History linearization

**Tags & Releases**
- Tag commits with semantic versions
- Create releases
- Release notes generation
- Compare releases

### Performance & Scalability

**Parallel File Processing**
- Multi-threaded file reading (5-10x faster)
- Concurrent hash computation
- Parallel imports for large projects

**Result Caching**
- Cache frequently accessed queries
- Invalidate on updates
- Target: 50-90% cache hit rate
- Redis optional for distributed caching

**Incremental Updates**
- Only process changed files
- Git diff integration
- Target: 100x faster re-imports
- Smart content-addressable storage

**Query Compilation**
- Pre-compile frequent queries
- Prepared statement optimization
- Target: 20-30% faster queries

### LLM & AI Integration

**Advanced Context Generation**
- Semantic code analysis
- Function call graphs
- Data flow analysis
- Automated documentation generation

**AI Code Review**
- Automated PR reviews
- Suggest improvements
- Detect code smells
- Security vulnerability scanning

**Natural Language Queries**
- "Find all API endpoints"
- "Show me files related to authentication"
- Convert natural language to SQL
- Interactive query refinement

### 14. Multi-User & Collaboration 🔴 **Critical Architectural Gap**

**Current State: Single-User Only**

TempleDB currently assumes single-user operation throughout the codebase. This is a fundamental architectural limitation that affects multiple layers:

#### Database Layer Issues
- **SQLite (single writer)**: Only one process can write at a time
  - Concurrent writes cause "database locked" errors
  - No multi-version concurrency control (MVCC) like PostgreSQL
  - No row-level locking
  - No transaction isolation between users
  - No user-based access control at DB level

#### Filesystem & Path Assumptions
- **Absolute paths**: Assumptions about `/home/zach/...` paths throughout
  - ✅ *Partially addressed by CWD-based discovery*
  - ⚠️  Still issues with checkout paths and workspace directories
- User home directory dependencies (`~/.templedb/`, `~/.age/`)
- No multi-tenant project organization
- Shared filesystem conflicts (NFS, network drives)

#### Security & Access Control
- **Age encryption keys**: Stored per-user in home directory
  - `~/.config/sops/age/keys.txt` - single user assumption
  - No key distribution mechanism for teams
  - No shared key management
  - Users must share dangerous private keys OR re-encrypt for each user
- **No authentication system**:
  - No login, sessions, or user identity verification
  - Commands assume `$USER` environment variable (easily spoofed)
  - No password, tokens, or credentials
- **No authorization system**:
  - Any database access = full admin rights
  - No read-only access mode
  - No project-level permissions
  - No file-level access control
  - No concept of "owners" vs "collaborators"
- **Audit logs are unverified**:
  - Stores `$USER` from environment but no verification
  - No cryptographic signatures
  - No non-repudiation

#### Session & State Management
- No concept of "who is currently logged in"
- No session tokens or credentials
- No API authentication for remote access
- No way to track active users

#### Concurrency & Conflict Scenarios
- **File conflicts**: Multiple users editing same file simultaneously
  - Optimistic locking exists but assumes single user will resolve
  - No pessimistic locking available
  - Last-write-wins can lose data
- **Cathedral conflicts**: Exports/imports could clobber other users' work
- **Checkout conflicts**: Multiple users checking out same project
- **Deployment races**: Two users deploying simultaneously

#### Proposed Solutions

**Option A: Client-Server Architecture** ⭐ **Recommended Long-Term**

```
┌─────────────┐         ┌─────────────────┐
│TempleDB CLI │────────▶│ TempleDB Server │
│  (Client)   │◀────────│  (PostgreSQL)   │
└─────────────┘  gRPC   └─────────────────┘
     User 1                    │
                          ┌────┴────┐
┌─────────────┐          │ Auth    │
│TempleDB CLI │──────────│ RBAC    │
│  (Client)   │  gRPC    │ Audit   │
└─────────────┘          └─────────┘
     User 2
```

**Pros:**
- Proper multi-user with PostgreSQL
- Central authentication & authorization
- Network access for remote teams
- Row-level security (RLS)
- ACID compliance with concurrent writes
- Cloud deployment ready
- Mature ecosystem (connection pooling, replication, backups)

**Cons:**
- Major architecture change
- Requires server infrastructure
- Complexity for single-user case
- Database schema migration needed
- Network dependency (but could cache locally)

**Implementation Roadmap:**
- [ ] Design gRPC or REST API
- [ ] User authentication (JWT tokens, sessions)
- [ ] Role-based access control (RBAC) - Owner, Admin, Developer, Viewer
- [ ] Migrate schema from SQLite to PostgreSQL
- [ ] Handle offline mode with local SQLite cache
- [ ] Multi-tenancy design (organizations, teams, projects)
- [ ] Secret sharing with envelope encryption
- [ ] Audit logging with verified identities

**Option B: Distributed/P2P Architecture**

```
┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│TempleDB CLI │◀─────▶│TempleDB CLI │◀─────▶│TempleDB CLI │
│  (User 1)   │       │  (User 2)   │       │  (User 3)   │
└─────────────┘       └─────────────┘       └─────────────┘
       │                     │                      │
    SQLite               SQLite                SQLite
```

**Pros:**
- No central server needed
- Local-first, offline-friendly
- Peer-to-peer collaboration
- Like Git's distributed model
- No single point of failure

**Cons:**
- Complex conflict resolution (CRDTs required)
- Eventual consistency issues
- Requires distributed systems expertise
- Merge conflicts at database level (complex)
- Harder to enforce authorization

**Implementation:**
- [ ] CRDTs (Conflict-free Replicated Data Types)
- [ ] Vector clocks or Lamport timestamps
- [ ] Sync protocol design
- [ ] Peer discovery mechanism
- [ ] Offline-first architecture
- [ ] Byzantine fault tolerance considerations

**Option C: Hybrid - SQLite + File Locking** ⚠️ **Not Recommended**

Keep SQLite but add explicit file locking for multi-user on shared filesystem.

**Cons:**
- SQLite on NFS is dangerous (corruption risk)
- Still single-writer bottleneck
- Poor performance
- File locking issues (stale locks, lock server crashes)
- Not recommended by SQLite developers

**Option D: "Handoff" Model - Cooperative Locking**

One active user at a time, explicit handoff between users.

**Pros:**
- Minimal changes to current architecture
- Clear ownership model
- No complex concurrency

**Cons:**
- Not true collaboration
- Bottleneck on popular projects
- Frustrating developer experience
- Doesn't scale

**User Management Roadmap**

If we pursue Option A (recommended), here's the phased approach:

**Phase 1: Authentication & Identity (Foundation)**
- [ ] User registration and login
- [ ] Password hashing (bcrypt/argon2)
- [ ] JWT or session-based authentication
- [ ] User profiles (name, email, avatar, preferences)
- [ ] API key generation for automation/CI
- [ ] MFA/2FA support

**Phase 2: Authorization & Access Control**
- [ ] Role-based access control (RBAC):
  - **Owner**: Full control, can delete project
  - **Admin**: Manage users, settings, deployments
  - **Developer**: Read/write code, create commits
  - **Viewer**: Read-only access
- [ ] Project-level permissions
- [ ] Fine-grained permissions (optional):
  - Branch protection rules
  - File-level ACLs
  - Secret access control
- [ ] Team/organization hierarchy
- [ ] Audit logging with verified user identities
- [ ] Permission inheritance

**Phase 3: Concurrent Access & Database Migration**
- [ ] Migrate from SQLite to PostgreSQL
- [ ] Transaction isolation levels (Read Committed, Serializable)
- [ ] Pessimistic locking for critical operations
- [ ] Optimistic locking with user attribution
- [ ] Conflict detection and resolution UI
- [ ] Concurrent file editing with operational transforms
- [ ] Real-time notifications of conflicts

**Phase 4: Shared Secrets & Key Management**
- [ ] Key management service (KMS)
- [ ] Envelope encryption for shared secrets:
  - Data Encryption Key (DEK) per secret
  - Key Encryption Keys (KEK) per user
  - Users can decrypt with their KEK
- [ ] Secret sharing (per-user, per-team, per-project)
- [ ] Key rotation
- [ ] Secret access audit logs
- [ ] Integration with external KMS:
  - HashiCorp Vault
  - AWS Secrets Manager
  - Google Secret Manager
  - Azure Key Vault

**Phase 5: Collaboration Features**
- [ ] User presence indicators ("John is viewing main.py")
- [ ] File checkout/lock status
- [ ] Comments and code discussions
- [ ] Code review workflow (approve, request changes)
- [ ] @mentions and notifications
- [ ] Real-time activity feed
- [ ] Conflict resolution UI

**Remote Sync**
- Sync database state between machines
- Conflict resolution strategies
- Distributed version control
- Central server optional (hybrid mode)
- Push/pull model like git

**Code Review Workflow**
- Review merge requests
- Comment on specific lines of code
- Approve/reject changes
- Track review status
- Request changes
- Mark conversations resolved

### Testing & Quality

**Test Coverage Integration**
- Import coverage reports (lcov, cobertura)
- Track coverage per file
- Visualize untested code
- Coverage trends over time

**Static Analysis Integration**
- Import lint results
- Track code quality metrics
- Detect technical debt
- Quality trends dashboard

**Benchmark Tracking**
- Store performance benchmarks
- Compare across versions
- Detect regressions
- Performance trends

### Export & Integration

**Export Formats**
- Export projects to git repositories
- Generate static sites from database
- Export to markdown wiki
- API documentation generation

**API Server**
- REST API for database queries
- GraphQL support
- WebSocket for real-time updates
- Authentication & rate limiting

**IDE Plugins**
- VSCode extension
- Emacs package
- Vim plugin
- JetBrains plugin

### Documentation & DevTools

**Schema Migrations**
- Versioned schema migrations
- Forward and backward migrations
- Automatic migration on upgrade
- Migration testing

**Backup Improvements**
- Scheduled automatic backups
- Incremental backups
- Cloud backup integration (S3, GCS)
- Backup verification

**Developer Tools**
- Database schema visualizer
- Query profiler and analyzer
- Data integrity checker
- Performance monitoring dashboard

---

## Community Features

### Documentation
- Video tutorials
- Interactive guides
- Example projects
- Best practices guide

### Ecosystem
- Plugin system
- Custom file type definitions
- User-contributed queries
- Community-maintained integrations

### Support
- GitHub Discussions
- Discord server
- Stack Overflow tag
- Community forum

---

## Technical Debt & Refactoring

### Code Quality
- Increase test coverage (target: 80%+)
- Add type hints throughout Python code
- Refactor large functions
- Improve error handling

### Documentation
- API documentation for all modules
- Architecture decision records (ADRs)
- Contributing guide
- Development setup guide

### Performance Testing
- Automated performance benchmarks
- Regression testing
- Load testing for large projects
- Memory profiling

---

## Breaking Changes Policy

TempleDB follows semantic versioning:

- **Major version (1.0.0, 2.0.0)**: Breaking schema changes
  - Database migration required
  - CLI interface changes
  - Backward compatibility may break

- **Minor version (0.6.0, 0.7.0)**: New features
  - Schema additions (backward compatible)
  - New commands/flags
  - Existing functionality preserved

- **Patch version (0.5.1, 0.5.2)**: Bug fixes
  - No schema changes
  - No new features
  - Only fixes and optimizations

---

## How to Contribute

### Feature Requests
- Open GitHub issue with `[Feature Request]` tag
- Describe use case and expected behavior
- Discuss design before implementation

### Implementation Process
1. Check roadmap for planned features
2. Discuss approach in GitHub issue
3. Fork and create feature branch
4. Implement with tests
5. Update documentation
6. Submit pull request

### Priority Decision Factors
- User demand (GitHub issues, discussions)
- Implementation complexity
- Performance impact
- Maintenance burden
- Alignment with philosophy

---

## Design Principles

**Database-First**
- SQLite is source of truth
- Everything queryable
- Filesystem is optional cache

**Performance Matters**
- Sub-second response times
- Handle large codebases (100K+ files)
- Memory efficiency
- Optimize hot paths

**User Experience**
- Intuitive CLI
- Powerful TUI
- Clear documentation
- Helpful error messages

**Self-Contained**
- Minimal dependencies
- Easy installation
- Works offline
- No external services required

---

## Version 1.0 Goals

To reach stable 1.0 release, TempleDB should have:

**Core Stability**
- ✅ Comprehensive test suite (80%+ coverage)
- ✅ Stable database schema
- ✅ Migration system
- ✅ Production-ready performance

**Feature Completeness**
- ✅ Full VCS workflow (commit, merge, branch)
- ✅ Advanced search (FTS5)
- ✅ Watch mode for auto-updates
- ✅ Deployment tracking
- ✅ Multi-user support (optional)

**Documentation**
- ✅ Complete user guide
- ✅ API documentation
- ✅ Video tutorials
- ✅ Example projects

**Ecosystem**
- ✅ IDE plugins (VSCode, Emacs)
- ✅ CI/CD integrations
- ✅ API server
- ✅ Community plugins

**Target Date:** TBD (when ready)

---

## Feedback & Discussion

Have ideas for TempleDB's future? Join the discussion:

- GitHub Issues: [Feature requests and bugs](https://github.com/user/templeDB/issues)
- GitHub Discussions: [Ideas and questions](https://github.com/user/templeDB/discussions)
- Email: [maintainer email]

---

*"The cathedral model, in which code is carefully crafted by wizards or small bands of mages working in splendid isolation."* - Eric S. Raymond

**TempleDB Roadmap - Building a temple, one feature at a time**
