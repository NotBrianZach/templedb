# File Conflicts Analysis - Not Implemented

**Status:** ❌ NOT IMPLEMENTED (and deleted)
**Date:** March 19, 2026
**Decision:** Table marked for deletion instead of implementation

---

## Summary

The `file_conflicts` table was originally planned for optimistic locking in a checkout-based VCS system, but was never implemented and has no code references. After investigation, determined that implementation is not needed.

---

## Table Schema (Before Deletion)

```sql
CREATE TABLE file_conflicts (
    id INTEGER PRIMARY KEY,
    checkout_id INTEGER NOT NULL REFERENCES checkouts(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    base_version INTEGER NOT NULL,           -- Version at checkout
    current_version INTEGER NOT NULL,        -- Current version in DB
    conflict_type TEXT NOT NULL,             -- 'version_mismatch', 'content_diverged'
    detected_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT,
    resolution_strategy TEXT,                -- 'abort', 'force', 'merge', 'manual'
    resolved_by TEXT
);
```

---

## Original Purpose

The table was created in **migration 003** (optimistic locking) to track conflicts when:
1. User checks out a project from database to filesystem (creates checkout record)
2. User makes changes locally
3. User attempts to sync changes back to database
4. System detects that someone else modified the same files
5. Conflict record created for resolution

---

## Why Not Implemented

### 1. No Active Use Case

**Checkout system usage:**
```bash
$ sqlite3 templedb.sqlite "SELECT COUNT(*) FROM checkouts"
9
```

Only 9 checkouts exist, and the checkout command works fine without conflict detection.

### 2. No Code References

Searched entire codebase:
- ❌ No INSERT statements for file_conflicts
- ❌ No conflict detection logic in checkout/sync commands
- ❌ No resolution UI or commands

### 3. Two Competing VCS Systems

TempleDB has **two VCS systems** that don't integrate:

**System A: Database-native storage (checkouts)**
- Files stored in database
- `templedb checkout` extracts to filesystem
- `templedb sync` imports changes back
- file_conflicts was designed for this system
- **Not actively developed**

**System B: Git-style VCS (vcs_working_state, vcs_branches)**
- Files tracked in filesystem (like git)
- `templedb vcs add`, `templedb vcs commit`
- Branch-based workflow
- **Actively used and maintained**

file_conflicts doesn't fit either system well:
- System A: Works fine without conflict detection
- System B: Would need completely different schema (branch-based, not checkout-based)

### 4. Merge Resolver Already Exists

**src/merge_resolver.py** already implements:
- Three-way merge algorithm
- Conflict detection (both_modified, modify_delete, both_added)
- Conflict markers
- Resolution strategies

This handles merges algorithmically without needing persistent conflict records.

### 5. Complex Implementation

Proper implementation would require:
1. **Conflict detection** on sync/push (4-6 hours)
   - Compare base_version vs current_version
   - Detect content divergence
   - Create conflict records

2. **Resolution commands** (3-4 hours)
   - `templedb conflicts list`
   - `templedb conflicts show <id>`
   - `templedb conflicts resolve <id> --strategy <abort|force|merge>`

3. **Integration testing** (2-3 hours)
   - Multi-user scenarios
   - Concurrent modification tests
   - Resolution verification

**Total: 9-13 hours** for a feature with no clear use case.

---

## Alternative: Git-Style Conflict Handling

If conflict handling is needed, it should be for the **git-style VCS** (System B):

```sql
-- Future schema (if needed)
CREATE TABLE vcs_merge_conflicts (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    conflict_type TEXT,  -- 'both_modified', 'modify_delete', etc.
    ours_hash TEXT,      -- Our version content hash
    theirs_hash TEXT,    -- Their version content hash
    base_hash TEXT,      -- Common ancestor
    detected_at TEXT,
    resolved_at TEXT,
    resolution TEXT      -- 'ours', 'theirs', 'merged'
);
```

But this is also not needed yet because:
- No merge/pull commands exist
- Single-user workflow (no conflicts possible)
- Can be added when collaboration features are needed

---

## Migration 040: Table Deletion

The `file_conflicts` table is deleted in **migration 040** along with 17 other unused tables:

```sql
-- File organization (not implemented)
DROP TABLE IF EXISTS file_conflicts;
DROP TABLE IF EXISTS file_tag_assignments;
DROP TABLE IF EXISTS file_tags;
```

**Reasoning:** Table has 0 rows, 0 code references, and no clear path to implementation.

---

## If Conflict Handling Is Needed Later

When collaboration features are actually needed:

### For System A (Database-native storage):
1. Implement version tracking on file_contents
2. Add optimistic locking checks on sync
3. Create conflict records in file_conflicts
4. Build resolution UI

### For System B (Git-style VCS):
1. Wait for merge/pull commands to be needed
2. Create vcs_merge_conflicts table (branch-based)
3. Integrate with merge_resolver.py
4. Use existing three-way merge logic

---

## Comparison to VCS Staging

**VCS Staging (file_conflicts was supposed to be similar):**
- ✅ Commands existed (vcs add, vcs reset)
- ✅ Service methods existed
- ✅ Table existed (vcs_working_state)
- ❌ Had bugs preventing it from working
- ✅ **Outcome**: Fixed bugs, feature now works

**File Conflicts:**
- ❌ No commands exist
- ❌ No service methods exist
- ✅ Table exists (file_conflicts)
- ❌ No integration points
- ✅ **Outcome**: Deleted as unused

---

## Lessons Learned

### Don't Implement Just Because Table Exists

The presence of a database table doesn't mean the feature should be implemented. Consider:
1. **Is it actively used?** (0 rows = no)
2. **Does code reference it?** (0 references = no)
3. **Is there demand?** (no user requests = no)
4. **Is architecture clear?** (two conflicting VCS systems = no)

### Be Honest About Complexity

Original estimate: 4-5 hours
Actual complexity: 9-13 hours + architectural decisions

When a feature requires:
- Significant infrastructure
- Unclear use case
- Architectural changes

It's better to defer than to build something that won't be used.

### Delete Unused Tables Aggressively

Keeping unused tables "just in case" creates:
- Schema bloat
- Maintenance burden
- False expectations

Better to delete and recreate later if actually needed.

---

## Conclusion

The `file_conflicts` table is **deleted in migration 040** rather than implemented because:

1. ✅ No active use case
2. ✅ No code integration
3. ✅ Conflicting VCS architectures
4. ✅ Merge resolver already handles conflicts algorithmically
5. ✅ High implementation cost for unclear benefit

If conflict handling is needed later, it should be:
- **For checkout system**: Reimplement from scratch with clear requirements
- **For git-style VCS**: Create new vcs_merge_conflicts table when merge/pull commands exist

---

**Analysis by:** Claude Code (Sonnet 4.5)
**Recommendation:** Delete (via migration 040)
**Status:** Implemented (table deleted)
