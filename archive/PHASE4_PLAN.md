# Phase 4: Multi-Agent Locking Implementation Plan

**Goal**: Enable safe concurrent editing by multiple agents through optimistic locking and conflict detection

---

## Problem Statement

**Current Situation** (After Phase 3):
- Multiple agents can checkout same project simultaneously ✓
- Multiple agents can commit changes ✓
- **Problem**: Last write wins, no conflict detection

**Example Conflict Scenario**:
```
Time  Agent A              Agent B              Database
────────────────────────────────────────────────────────
T0    Checkout             Checkout             version=1
      app.py (v1)          app.py (v1)

T1    Edit app.py          -                    version=1
      (add feature X)

T2    -                    Edit app.py          version=1
                           (add feature Y)

T3    Commit               -                    version=2
      (feature X saved)                         (contains X)

T4    -                    Commit               version=3
                                                (contains Y, X lost!)
```

**Result**: Agent A's changes silently overwritten! ❌

---

## Solution: Optimistic Locking

### Core Concept

**Optimistic Locking**: Assume conflicts are rare, detect them when they occur

**Version-Based Locking**:
1. Each file content has a `version` number
2. On checkout, record the version
3. On commit, check if version changed
4. If changed → conflict detected → resolution required
5. If unchanged → commit succeeds, increment version

**Modified Scenario with Locking**:
```
Time  Agent A              Agent B              Database
────────────────────────────────────────────────────────
T0    Checkout             Checkout             version=1
      app.py (v1)          app.py (v1)

T1    Edit app.py          -                    version=1
      (add feature X)

T2    -                    Edit app.py          version=1
                           (add feature Y)

T3    Commit               -                    version=2
      (feature X saved)                         (contains X)

T4    -                    Commit               CONFLICT!
                           → version mismatch   version=2 (expected 1)
                           → Agent B notified
                           → Resolution needed
```

**Result**: Conflict detected! Agent B must resolve manually. ✓

---

## Implementation Strategy

### 1. Add Version Tracking

**Schema Changes**:
```sql
-- Add version to file_contents
ALTER TABLE file_contents ADD COLUMN version INTEGER DEFAULT 1;

-- Add checkout snapshot table (track what versions were checked out)
CREATE TABLE IF NOT EXISTS checkout_snapshots (
    id INTEGER PRIMARY KEY,
    checkout_id INTEGER NOT NULL REFERENCES checkouts(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    version INTEGER NOT NULL,
    checked_out_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(checkout_id, file_id)
);

-- Add index for fast version lookups
CREATE INDEX IF NOT EXISTS idx_checkout_snapshots_checkout ON checkout_snapshots(checkout_id);
CREATE INDEX IF NOT EXISTS idx_checkout_snapshots_file ON checkout_snapshots(file_id);
```

**Purpose**:
- `version` on `file_contents`: Track current version of each file
- `checkout_snapshots`: Remember what version each checkout has
- On commit: Compare current version with checked-out version

### 2. Enhance Checkout to Record Versions

**Modified Checkout**:
```python
def checkout(self, args):
    # ... existing checkout logic ...

    # Record snapshot of versions
    with transaction():
        # Get or create checkout record
        checkout_id = ...

        # Record what version each file is at checkout
        for file in files:
            execute("""
                INSERT INTO checkout_snapshots
                (checkout_id, file_id, content_hash, version)
                SELECT ?, pf.id, fc.content_hash, fc.version
                FROM project_files pf
                JOIN file_contents fc ON fc.file_id = pf.id
                WHERE pf.id = ? AND fc.is_current = 1
            """, (checkout_id, file['file_id']), commit=False)
```

### 3. Enhance Commit to Check Versions

**Modified Commit**:
```python
def commit(self, args):
    # ... existing change detection ...

    # Check for conflicts before committing
    conflicts = self._detect_conflicts(project['id'], workspace_dir, changes['modified'])

    if conflicts:
        print("\n⚠️  CONFLICTS DETECTED:")
        for conflict in conflicts:
            print(f"   {conflict['file_path']}")
            print(f"      Your version: {conflict['your_version']}")
            print(f"      Current version: {conflict['current_version']}")
            print(f"      Changed by: {conflict['changed_by']}")

        # Offer resolution strategies
        strategy = self._prompt_resolution_strategy()

        if strategy == 'abort':
            print("Commit aborted")
            return 1
        elif strategy == 'force':
            # Continue with commit (overwrite)
            pass
        elif strategy == 'rebase':
            # Attempt automatic merge
            success = self._attempt_auto_merge(conflicts)
            if not success:
                print("Automatic merge failed, manual resolution required")
                return 1

    # Proceed with commit
    with transaction():
        # ... existing commit logic ...

        # For each modified file, check version
        for change in changes['modified']:
            current_version = query_one("""
                SELECT version FROM file_contents
                WHERE file_id = ? AND is_current = 1
            """, (change.file_id,))

            checkout_version = query_one("""
                SELECT version FROM checkout_snapshots cs
                JOIN checkouts c ON cs.checkout_id = c.id
                WHERE c.project_id = ? AND c.checkout_path = ? AND cs.file_id = ?
            """, (project['id'], str(workspace_dir), change.file_id))

            if current_version['version'] != checkout_version['version']:
                # Version mismatch! Conflict!
                if strategy != 'force':
                    raise ConflictError(f"Version conflict on {change.file_path}")

            # Update with new version
            execute("""
                UPDATE file_contents
                SET content_hash = ?,
                    version = version + 1,
                    updated_at = datetime('now')
                WHERE file_id = ? AND is_current = 1
            """, (change.content.hash_sha256, change.file_id), commit=False)
```

### 4. Conflict Detection Logic

```python
def _detect_conflicts(self, project_id, workspace_dir, modified_files):
    """Detect version conflicts for modified files"""
    conflicts = []

    # Get checkout info
    checkout = query_one("""
        SELECT id FROM checkouts
        WHERE project_id = ? AND checkout_path = ?
    """, (project_id, str(workspace_dir)))

    if not checkout:
        # No checkout record, can't detect conflicts
        return []

    for change in modified_files:
        # Get current version in database
        current = query_one("""
            SELECT fc.version, c.author, c.commit_timestamp
            FROM file_contents fc
            LEFT JOIN commit_files cf ON cf.new_content_hash = fc.content_hash
            LEFT JOIN vcs_commits c ON c.id = cf.commit_id
            WHERE fc.file_id = ? AND fc.is_current = 1
        """, (change.file_id,))

        # Get version at checkout
        snapshot = query_one("""
            SELECT version, content_hash
            FROM checkout_snapshots
            WHERE checkout_id = ? AND file_id = ?
        """, (checkout['id'], change.file_id))

        if snapshot and current:
            if current['version'] != snapshot['version']:
                conflicts.append({
                    'file_path': change.file_path,
                    'file_id': change.file_id,
                    'your_version': snapshot['version'],
                    'current_version': current['version'],
                    'changed_by': current['author'],
                    'changed_at': current['commit_timestamp']
                })

    return conflicts
```

### 5. Resolution Strategies

**Strategy 1: Abort**
```python
if strategy == 'abort':
    print("Commit aborted. Please:")
    print("  1. Review conflicts")
    print("  2. Checkout fresh copy")
    print("  3. Manually merge your changes")
    print("  4. Commit again")
    return 1
```

**Strategy 2: Force (Overwrite)**
```python
if strategy == 'force':
    print("⚠️  WARNING: Forcing commit, will overwrite other changes!")
    # Proceed with commit, ignoring version check
    # Version still increments
```

**Strategy 3: Auto-Merge (Simple)**
```python
def _attempt_auto_merge(self, conflicts):
    """Attempt automatic 3-way merge"""
    for conflict in conflicts:
        # Get three versions:
        # 1. Base (version at checkout)
        # 2. Theirs (current in database)
        # 3. Yours (in workspace)

        base = self._get_file_content_at_version(conflict['file_id'], conflict['your_version'])
        theirs = self._get_file_content_current(conflict['file_id'])
        yours = self._read_workspace_file(conflict['file_path'])

        # Simple line-based merge
        merged, has_conflicts = merge_3way(base, theirs, yours)

        if has_conflicts:
            # Create conflict markers file
            conflict_file = workspace_dir / f"{conflict['file_path']}.conflict"
            conflict_file.write_text(merged)
            return False

        # Success, use merged content
        # Update workspace with merged version
        workspace_file = workspace_dir / conflict['file_path']
        workspace_file.write_text(merged)

    return True
```

---

## User Experience

### Happy Path (No Conflicts)

```bash
# Agent A
$ templedb project checkout myproject /tmp/a
$ echo "feature A" >> /tmp/a/app.py
$ templedb project commit myproject /tmp/a -m "Add feature A"
✅ Commit complete!

# Agent B (different file)
$ templedb project checkout myproject /tmp/b
$ echo "feature B" >> /tmp/b/utils.py
$ templedb project commit myproject /tmp/b -m "Add feature B"
✅ Commit complete!
```

### Conflict Detected

```bash
# Agent A
$ templedb project checkout myproject /tmp/a
$ echo "feature A" >> /tmp/a/app.py
$ templedb project commit myproject /tmp/a -m "Add feature A"
✅ Commit complete!

# Agent B (same file!)
$ templedb project checkout myproject /tmp/b
$ echo "feature B" >> /tmp/b/app.py
$ templedb project commit myproject /tmp/b -m "Add feature B"

⚠️  CONFLICTS DETECTED:
   app.py
      Your version: 1
      Current version: 2
      Changed by: agent_a
      Changed at: 2026-02-23 18:30:00

How would you like to resolve?
  [a] Abort commit (recommended)
  [f] Force commit (overwrite other changes)
  [r] Attempt auto-rebase
Choice: a

Commit aborted. Please:
  1. Checkout fresh copy: templedb project checkout myproject /tmp/b-fresh
  2. Manually merge your changes from /tmp/b
  3. Commit again
```

### Force Overwrite

```bash
$ templedb project commit myproject /tmp/b -m "Add feature B" --force

⚠️  WARNING: Forcing commit, will overwrite changes by agent_a!

✅ Commit complete!
   (Previous changes have been overwritten)
```

---

## Testing Strategy

### Test 1: Concurrent Non-Conflicting Edits

```python
def test_concurrent_non_conflicting():
    """Two agents edit different files"""

    # Agent A: checkout and edit file1
    checkout("myproject", "/tmp/a")
    edit("/tmp/a/file1.py")

    # Agent B: checkout and edit file2
    checkout("myproject", "/tmp/b")
    edit("/tmp/b/file2.py")

    # Both commit should succeed
    commit("myproject", "/tmp/a", "Edit file1")  # ✓
    commit("myproject", "/tmp/b", "Edit file2")  # ✓
```

### Test 2: Concurrent Conflicting Edits

```python
def test_concurrent_conflicting():
    """Two agents edit same file"""

    # Both checkout
    checkout("myproject", "/tmp/a")
    checkout("myproject", "/tmp/b")

    # Both edit same file
    edit("/tmp/a/app.py")
    edit("/tmp/b/app.py")

    # First commit succeeds
    commit("myproject", "/tmp/a", "Change A")  # ✓

    # Second commit detects conflict
    result = commit("myproject", "/tmp/b", "Change B")
    assert result == CONFLICT_DETECTED  # ✓
```

### Test 3: Force Overwrite

```python
def test_force_overwrite():
    """Test --force flag overwrites conflicts"""

    # Setup conflict
    checkout("myproject", "/tmp/a")
    checkout("myproject", "/tmp/b")
    edit("/tmp/a/app.py")
    edit("/tmp/b/app.py")
    commit("myproject", "/tmp/a", "Change A")

    # Force commit
    commit("myproject", "/tmp/b", "Change B", force=True)  # ✓

    # Verify B's changes are in database
    content = get_file_content("app.py")
    assert "Change B" in content
```

---

## Implementation Files

### 1. Schema Migration

**File**: `migrations/003_optimistic_locking.sql`

### 2. Enhanced Checkout

**File**: `src/cli/commands/checkout.py` (modify)
- Add checkout snapshot recording

### 3. Enhanced Commit

**File**: `src/cli/commands/commit.py` (modify)
- Add conflict detection
- Add resolution strategies
- Add version checking

### 4. Conflict Resolution

**File**: `src/conflict_resolver.py` (NEW)
- Implement merge strategies
- Handle conflict markers

---

## CLI Flags

**New Flags for Commit**:

```bash
templedb project commit <slug> <dir> -m "msg" [options]

Options:
  --force, -f          Force commit, overwrite conflicts
  --strategy <name>    Conflict resolution: abort|force|rebase
  --no-check           Skip version checking (dangerous!)
```

---

## Success Criteria

After Phase 4:
- ✅ Version numbers track file changes
- ✅ Conflicts detected when two agents edit same file
- ✅ User prompted to resolve conflicts
- ✅ --force flag allows overwriting
- ✅ Tests verify concurrent edit safety
- ✅ Documentation explains conflict resolution

---

## Rollout Plan

### Day 1: Schema and Checkout
1. Create migration SQL
2. Apply migration
3. Update checkout to record snapshots
4. Test checkout snapshot recording

### Day 2: Conflict Detection
1. Implement `_detect_conflicts()`
2. Add conflict checking to commit
3. Test conflict detection

### Day 3: Resolution Strategies
1. Implement abort strategy
2. Implement force strategy
3. Add CLI prompts
4. Test resolution workflows

### Day 4: Testing
1. Test concurrent non-conflicting edits
2. Test concurrent conflicting edits
3. Test force overwrite
4. Test version increment

### Day 5: Documentation
1. Document conflict resolution
2. Update README with examples
3. Create troubleshooting guide

---

## Future Enhancements

### Automatic Merge

Implement 3-way merge for automatic conflict resolution:

```python
def merge_3way(base, theirs, yours):
    """Perform 3-way merge"""
    # Use diff3 algorithm
    # Generate merged content with conflict markers if needed
    pass
```

### Conflict Markers

Generate files with conflict markers:

```python
# app.py.conflict
<<<<<<< yours
feature B code
=======
feature A code
>>>>>>> theirs (version 2, by agent_a)
```

### Branch-Based Locking

Extend to support per-branch locking:

```sql
ALTER TABLE checkout_snapshots ADD COLUMN branch_id INTEGER;
```

---

Ready to begin implementation! 🚀
