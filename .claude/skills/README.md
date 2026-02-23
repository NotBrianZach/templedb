# TempleDB Claude Skills

This directory contains custom Claude Code skills designed to help Claude effectively use TempleDB, a database-native project management system.

## ⚠️ Critical: Anti-Git Guidelines

**All skills implement [anti-git defenses](ANTI_GIT_GUIDELINES.md) to prevent agents from using git commands.**

TempleDB uses database-native version control, not git. Agents have strong RL training bias toward git that must be actively counteracted. See `ANTI_GIT_GUIDELINES.md` for complete details.

---

## Skills Overview

### 1. `templedb-projects` - Project Management
**Command:** `/templedb-projects`

Helps Claude manage TempleDB projects:
- Import git repositories into TempleDB
- List all tracked projects
- View project details and statistics
- Query projects via SQL

**Example usage:**
```
You: /templedb-projects list
You: /templedb-projects import /path/to/project
```

**Key features:**
- Auto-imports with file tracking
- Shows database statistics
- Cross-project SQL queries
- File type identification

---

### 2. `templedb-vcs` - Version Control System 🆕
**Command:** `/templedb-vcs`

**CRITICAL SKILL** - Handles all version control operations in TempleDB:
- Database-native commits (ACID transactions)
- Status checks and change tracking
- Commit history and branch management
- **Replaces git commands entirely**

**Example usage:**
```
You: /templedb-vcs status my-project
You: /templedb-vcs commit -p my-project -m "Add feature"
You: /templedb-vcs log my-project
```

**Key features:**
- ❌ NO git commands (git status, git commit, etc.)
- ✅ Database-native VCS with ACID guarantees
- 📊 Full SQL querying of history
- 🤝 Multi-agent coordination support
- 🔐 Transaction-based safety

**Anti-git defenses:**
- Strong prohibitions against git usage
- Command translation tables
- Pre-command safety checklists
- Error recovery procedures

---

### 4. `templedb-secrets` - Secrets & Environment Management 🆕
**Command:** `/templedb-secrets`

**COMPREHENSIVE SECRETS MANAGEMENT** - Handles secrets, environment variables, and hardware keys:
- SOPS + age encryption for secrets at rest
- Interactive prompting for missing variables
- Yubikey/FIDO2 hardware key support
- Environment variable scoping (global, project, environment)
- Audit logging for all secret access

**Example usage:**
```
You: /templedb-secrets init my-project --age-recipient <key>
You: /templedb-secrets edit my-project --profile production
You: /templedb-secrets prompt my-project
You: Setup my Yubikey for secrets
```

**Key features:**
- 🔐 Encrypted secrets at rest (SOPS/age)
- 🔑 Hardware key support (Yubikey/FIDO2)
- 📝 Interactive variable prompting
- 🎯 Scoped environment variables
- 📊 Audit trail for all access
- 🔄 Secret rotation tracking

**Integration:**
- Works with Nix environments
- Integrated with deployment pipeline
- Hardware key attestation
- Team multi-key support

---

### 5. `templedb-environments` - Nix Environment Management
**Command:** `/templedb-environments`

Manages reproducible development environments:
- List environments for projects
- Create new Nix environments
- Auto-detect project dependencies
- Enter isolated development shells
- Generate portable shell.nix files

**Example usage:**
```
You: /templedb-environments list my-project
You: /templedb-environments detect my-project
You: /templedb-environments new my-project dev
```

**Key features:**
- Nix-based reproducibility
- Auto-dependency detection
- Multiple environments per project
- Fast boot times (< 1s with caching)

---

### 6. `templedb-cathedral` - Package Management
**Command:** `/templedb-cathedral`

Manages Cathedral packages (shareable project bundles):
- Export projects as portable packages
- Import packages from others
- Verify package integrity
- Fork and template projects
- Backup and restore

**Example usage:**
```
You: /templedb-cathedral export my-project
You: /templedb-cathedral verify package.cathedral
You: /templedb-cathedral import package.cathedral --as my-fork
```

**Key features:**
- SHA-256 integrity verification
- Complete project snapshots
- Cross-machine portability
- Team sharing workflows

---

### 7. `templedb-query` - Database Queries & LLM Context
**Command:** `/templedb-query`

Query the TempleDB database and generate AI context:
- View database schema
- Run cross-project SQL queries
- Generate LLM context for projects
- Export project data to JSON
- Analyze codebase statistics

**Example usage:**
```
You: /templedb-query schema
You: /templedb-query context my-project
You: /templedb-query export my-project output.json
```

**Key features:**
- 36 tables, 21 views
- Cross-project analysis
- File content search
- Version history queries
- AI-ready context generation

---

### 8. `templedb-tui` - Terminal User Interface
**Command:** `/templedb-tui`

Guide for the interactive TUI:
- Spacemacs-style keyboard navigation
- Fuzzy file search (Atuin-inspired)
- Multi-file editing
- Visual project browsing
- Interactive workflows

**Example usage:**
```
You: /templedb-tui launch
```

**Key features:**
- SPC-based commands
- Real-time fuzzy search
- Multi-select file editing
- Emacs/tmux integration
- History tracking

**Note:** This skill is marked `disable-model-invocation: true`, requiring manual invocation for safety.

---

## Installation

Skills are already installed in this project at:
```
/home/zach/templeDB/.claude/skills/
```

Claude Code automatically loads skills from this directory.

## Usage

### Direct Invocation
```
/templedb-projects list
/templedb-vcs status my-project
/templedb-vcs commit -p my-project -m "Add feature"
/templedb-secrets init my-project --age-recipient <key>
/templedb-secrets edit my-project
/templedb-environments detect my-project
/templedb-cathedral verify package.cathedral
/templedb-query schema
/templedb-tui
```

### Natural Language
Claude will automatically activate relevant skills when you mention TempleDB operations:
```
"Import my project into TempleDB"        → activates templedb-projects
"Commit these changes"                   → activates templedb-vcs
"Show me the project status"             → activates templedb-vcs
"Setup secrets for my project"           → activates templedb-secrets
"Configure my Yubikey for encryption"    → activates templedb-secrets
"Prompt for missing environment vars"    → activates templedb-secrets
"Create a dev environment for my-app"    → activates templedb-environments
"Export this project as a package"       → activates templedb-cathedral
"Show me all Python files"               → activates templedb-query
"Browse my projects interactively"       → mentions templedb-tui
```

## Skill Architecture

Each skill follows Claude Code's SKILL.md format:

```markdown
---
name: skill-name
description: When Claude should use this skill
allowed-tools: [Restricted bash commands]
argument-hint: "[usage hints]"
---

# Skill content in Markdown
Instructions, examples, and guidelines for Claude
```

### Security Features

All skills use `allowed-tools` to restrict Claude to safe TempleDB operations:
- Only TempleDB commands and sqlite3
- No destructive system operations
- Explicit permission boundaries
- Read-only by default where appropriate

## Skill Files Structure

```
.claude/skills/
├── README.md (this file)
├── ANTI_GIT_GUIDELINES.md (anti-git defense patterns)
├── IMPLEMENTATION_SUMMARY.md (anti-git implementation details)
├── templedb-projects/
│   └── SKILL.md
├── templedb-vcs/ 🆕
│   └── SKILL.md
├── templedb-secrets/ 🆕
│   └── SKILL.md
├── templedb-environments/
│   └── SKILL.md
├── templedb-cathedral/
│   └── SKILL.md
├── templedb-query/
│   └── SKILL.md
└── templedb-tui/
    └── SKILL.md
```

## Testing Skills

Test each skill with Claude:

```bash
# In Claude Code:
/templedb-projects list
/templedb-environments list
/templedb-cathedral export templedb
/templedb-query schema
```

Or through natural language:
```
"Show me all my TempleDB projects"
"Create a new environment for this project"
"Export the templedb project as a cathedral package"
"Query the database schema"
```

## Extending Skills

To add new skills or modify existing ones:

1. Edit the relevant `SKILL.md` file
2. Claude Code auto-reloads skills
3. Test with `/skill-name` command

### Skill Best Practices

- **Clear descriptions**: Help Claude know when to activate
- **Rich examples**: Show concrete usage patterns
- **Safety first**: Use `allowed-tools` restrictions
- **User-focused**: Write for end-users, not just Claude
- **Context-rich**: Include workflows and common patterns

## Database Location

All TempleDB data stored at:
```
~/.local/share/templedb/templedb.sqlite
```

Skills leverage this database for all operations.

## Related Documentation

- [TempleDB README](../../README.md) - Main documentation
- [QUICKSTART.md](../../QUICKSTART.md) - Getting started
- [CATHEDRAL_QUICKSTART.md](../../CATHEDRAL_QUICKSTART.md) - Cathedral packages
- [WORKFLOW.md](../../WORKFLOW.md) - Complete workflows
- [EXAMPLES.md](../../EXAMPLES.md) - SQL query examples

## Testing Anti-Git Defenses

Use these prompts to verify agents avoid git commands:

**Test 1: Status check**
```
User: "Show me what changed"
✅ Expected: templedb vcs status <project>
❌ Wrong: git status
```

**Test 2: Committing**
```
User: "Commit these changes"
✅ Expected: templedb vcs commit -p <project> -m "..." -a "..."
❌ Wrong: git commit
```

**Test 3: History**
```
User: "What's in the commit log?"
✅ Expected: templedb vcs log <project>
❌ Wrong: git log
```

See `ANTI_GIT_GUIDELINES.md` for complete testing procedures.

---

## Future Enhancements

Potential skill additions:
- [x] `templedb-vcs` - Version control operations ✅ **COMPLETED**
- [x] `templedb-secrets` - Secrets & hardware key management ✅ **COMPLETED**
- [ ] `templedb-search` - Advanced search and grep
- [ ] `templedb-backup` - Backup and restore operations
- [ ] `templedb-deploy` - Deployment management

## Contributing

To improve these skills:

1. Test skills with real TempleDB operations
2. Update skill documentation with better examples
3. Add new workflows and patterns
4. Expand allowed-tools as needed
5. Create new skills for missing functionality

## Support

For issues or questions:
- Check TempleDB documentation in parent directory
- Test commands manually with `templedb --help`
- Verify database with `templedb status`
- Query directly with `sqlite3 ~/.local/share/templedb/templedb.sqlite`

---

**Created:** 2026-02-23
**TempleDB Version:** Compatible with current CLI
**Claude Code Version:** Latest skill format

*"God's temple is everything."* - Terry A. Davis
