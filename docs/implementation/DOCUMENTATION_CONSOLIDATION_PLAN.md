# Documentation Consolidation Plan

**Date:** 2026-02-23
**Current:** 26 markdown files (11,327 lines)

## Analysis

### Categories

#### 1. Implementation Details (Archive to `/docs/implementation/`)
These documents describe specific implementation work that's now complete. Valuable for history but not needed for regular use.

| File | Lines | Status | Reason |
|------|-------|--------|--------|
| `CLEANUP_SUMMARY.md` | 147 | Archive | Documents completed cleanup (2026-02-23) |
| `SQL_EXTRACTION_FIXES.md` | 131 | Archive | Documents completed fixes (2026-02-23) |
| `REDUNDANCY_ANALYSIS.md` | 216 | Archive | Documents completed analysis (2026-02-23) |
| `DATABASE_TYPES_GAP_ANALYSIS.md` | 298 | Archive | Gap analysis completed, types added |
| `COMPLEXITY_ANALYSIS.md` | 281 | Archive | Implementation detail, not user-facing |
| `SYNCHRONIZATION_COST_ANALYSIS.md` | 271 | Archive | Supporting detail for DESIGN_PHILOSOPHY.md |
| `REFACTOR_AGE_DIRECT.md` | 233 | Archive | Old refactor plan, completed |
| `RELEASE_PREP_STATUS.md` | 253 | Archive | Stale release prep checklist |

**Total:** 1,830 lines → Archive

#### 2. Critical Reference (Keep in Root)
Documents users need to reference frequently.

| File | Lines | Keep | Reason |
|------|-------|------|--------|
| `README.md` | 526 | ✓ | Main entry point |
| `QUERY_BEST_PRACTICES.md` | 223 | ✓ | Critical: file path uniqueness constraints |
| `DATABASE_CONSTRAINTS.md` | 411 | ✓ | Critical: all uniqueness constraints |
| `CHANGELOG.md` | 369 | ✓ | Version history |
| `MIGRATIONS.md` | 198 | ✓ | Migration history |

**Total:** 1,727 lines → Keep

#### 3. User Guides (Keep in Root or `/docs/`)
Documentation users need for learning/using TempleDB.

| File | Lines | Status | Consolidation Opportunity |
|------|-------|--------|--------------------------|
| `GETTING_STARTED.md` | 320 | Keep | Beginner installation guide |
| `QUICKSTART.md` | 350 | Keep | Advanced workflows |
| `GUIDE.md` | 565 | Keep | Complete user guide |
| `EXAMPLES.md` | 375 | Keep | SQL query examples |
| `FILES.md` | 432 | Keep | File tracking details |
| `TUI.md` | 520 | Keep | TUI documentation |

**Could consolidate:** GETTING_STARTED + QUICKSTART → Single "Getting Started" with sections?
**Total:** 2,562 lines → Keep (possibly merge 2 files)

#### 4. Advanced Topics (Move to `/docs/advanced/`)
Specialized documentation for advanced use cases.

| File | Lines | Status | Reason |
|------|-------|--------|--------|
| `ADVANCED.md` | 1,079 | Move | Performance, Nix, deployment |
| `BUILD.md` | 545 | Move | Building from source |
| `CATHEDRAL.md` | 2,005 | Move | Multi-user/team setup |
| `SECURITY.md` | 185 | Move | Security considerations |

**Total:** 3,814 lines → Move to `/docs/advanced/`

#### 5. Conceptual (Keep in Root)
Core philosophy and project information.

| File | Lines | Keep | Reason |
|------|-------|------|--------|
| `DESIGN_PHILOSOPHY.md` | 582 | ✓ | Core philosophy (referenced in README) |
| `ROADMAP.md` | 470 | ✓ | Future plans |
| `TRIBUTE.md` | 101 | ✓ | Dedication to Terry Davis |
| `RELEASE_NOTES.md` | 241 | ✓ | Current release notes |

**Total:** 1,394 lines → Keep

## Consolidation Actions

### 1. Archive Implementation Details
```bash
mkdir -p docs/implementation
mv CLEANUP_SUMMARY.md docs/implementation/
mv SQL_EXTRACTION_FIXES.md docs/implementation/
mv REDUNDANCY_ANALYSIS.md docs/implementation/
mv DATABASE_TYPES_GAP_ANALYSIS.md docs/implementation/
mv COMPLEXITY_ANALYSIS.md docs/implementation/
mv SYNCHRONIZATION_COST_ANALYSIS.md docs/implementation/
mv REFACTOR_AGE_DIRECT.md docs/implementation/
mv RELEASE_PREP_STATUS.md docs/implementation/
```

**Create index:**
```markdown
# Implementation Documentation

Historical implementation details, analyses, and refactor plans.

## Completed Work

### SQL Object Extraction (2026-02-23)
- [Cleanup Summary](CLEANUP_SUMMARY.md) - Redundancy removal
- [SQL Extraction Fixes](SQL_EXTRACTION_FIXES.md) - Bug fixes
- [Redundancy Analysis](REDUNDANCY_ANALYSIS.md) - Duplicate system analysis
- [Database Types Gap Analysis](DATABASE_TYPES_GAP_ANALYSIS.md) - Type coverage expansion

### Performance Analysis
- [Complexity Analysis](COMPLEXITY_ANALYSIS.md) - Storage operation complexity
- [Synchronization Cost Analysis](SYNCHRONIZATION_COST_ANALYSIS.md) - O(k²) vs O(k) verification

### Historical Refactors
- [Age Direct Refactor](REFACTOR_AGE_DIRECT.md) - Removed SOPS dependency
- [Release Prep Status](RELEASE_PREP_STATUS.md) - v0.6.0 preparation
```

### 2. Move Advanced Topics
```bash
mkdir -p docs/advanced
mv ADVANCED.md docs/advanced/
mv BUILD.md docs/advanced/
mv CATHEDRAL.md docs/advanced/
mv SECURITY.md docs/advanced/
```

**Update README.md** to reference new locations:
```markdown
### Advanced Topics
- **[Performance & Optimization](docs/advanced/ADVANCED.md)** - Tuning, Nix, deployment
- **[Building from Source](docs/advanced/BUILD.md)** - Development setup
- **[Multi-User Setup](docs/advanced/CATHEDRAL.md)** - Teams and collaboration
- **[Security](docs/advanced/SECURITY.md)** - Security considerations
```

### 3. Consolidate Getting Started (Optional)

**Option A:** Merge GETTING_STARTED + QUICKSTART
- GETTING_STARTED.md becomes comprehensive guide with "Basic" and "Advanced" sections
- QUICKSTART.md redirects to GETTING_STARTED.md

**Option B:** Keep separate (current structure)
- GETTING_STARTED.md: Installation, basic concepts (beginners)
- QUICKSTART.md: Workflows, advanced usage (existing users)

**Recommendation:** Keep separate - they serve different audiences.

### 4. Update README.md Documentation Index

```markdown
## Documentation

### Essential Reading
- **[README.md](README.md)** - Overview and quick start
- **[DESIGN_PHILOSOPHY.md](DESIGN_PHILOSOPHY.md)** - Why TempleDB exists
- **[GETTING_STARTED.md](GETTING_STARTED.md)** - Installation and setup

### User Guides
- **[GUIDE.md](GUIDE.md)** - Complete user guide
- **[QUICKSTART.md](QUICKSTART.md)** - Advanced workflows
- **[FILES.md](FILES.md)** - File tracking and versioning
- **[TUI.md](TUI.md)** - Terminal UI guide
- **[EXAMPLES.md](EXAMPLES.md)** - SQL query examples

### Critical Reference
- **[QUERY_BEST_PRACTICES.md](QUERY_BEST_PRACTICES.md)** - ⚠️ Query constraints (read this!)
- **[DATABASE_CONSTRAINTS.md](DATABASE_CONSTRAINTS.md)** - All uniqueness constraints

### Advanced Topics
- **[Performance & Optimization](docs/advanced/ADVANCED.md)**
- **[Building from Source](docs/advanced/BUILD.md)**
- **[Multi-User Setup](docs/advanced/CATHEDRAL.md)**
- **[Security](docs/advanced/SECURITY.md)**

### Project Info
- **[CHANGELOG.md](CHANGELOG.md)** - Version history
- **[RELEASE_NOTES.md](RELEASE_NOTES.md)** - Latest release
- **[ROADMAP.md](ROADMAP.md)** - Future plans
- **[TRIBUTE.md](TRIBUTE.md)** - Dedication to Terry Davis
- **[MIGRATIONS.md](MIGRATIONS.md)** - Schema evolution

### Implementation Details
- **[Implementation Docs](docs/implementation/)** - Historical analyses and refactors
```

## Impact Summary

### Before
- **26 files** in root directory
- **11,327 lines** of documentation
- Mixed purposes (user docs + implementation details)
- Hard to navigate

### After
- **18 files** in root (-8)
  - 5 Critical reference
  - 6 User guides
  - 4 Conceptual
  - 3 Project info
- **7,683 lines** in root (-32%)
- **8 files** archived to `docs/implementation/` (1,830 lines)
- **4 files** moved to `docs/advanced/` (3,814 lines)
- Clear separation: user docs vs implementation details
- Easier navigation

## Benefits

### For Users
- ✅ Cleaner root directory (18 vs 26 files)
- ✅ Clear separation: guides vs reference vs advanced
- ✅ Implementation details out of the way
- ✅ Updated README with organized doc index

### For Developers
- ✅ Historical context preserved (in `docs/implementation/`)
- ✅ Advanced topics grouped together
- ✅ Easier to find relevant documentation
- ✅ Clear structure for future docs

### For Maintenance
- ✅ Implementation details clearly marked as historical
- ✅ Reduced clutter in root
- ✅ Better organization for future additions
- ✅ Archive pattern established

## Recommendation

**Implement consolidation:**
1. Create `docs/implementation/` and `docs/advanced/` directories
2. Move 8 implementation documents to archive
3. Move 4 advanced topics to advanced folder
4. Update README.md documentation index
5. Add index files in new directories

**Result:** Cleaner, more navigable documentation structure with 32% fewer files in root.
