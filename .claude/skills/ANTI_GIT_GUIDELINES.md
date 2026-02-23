# Anti-Git Guidelines for TempleDB Agents

**Purpose**: Prevent AI agents from defaulting to git commands due to RL training bias.

---

## The Problem

AI agents have strong reinforcement learning (RL) biases toward git commands because:
1. Millions of git examples in training data
2. Pattern matching: "commit" → `git commit` is deeply encoded
3. Muscle memory from training reinforcement
4. Git tooling is ubiquitous in code examples

**Result**: Agents will naturally default to `git status`, `git commit`, etc. even in TempleDB environments.

---

## The Solution: Multi-Layer Defense

All TempleDB skills must implement these defenses:

### Layer 1: Strong System Prompts

✅ Place explicit prohibitions at the TOP of skill files
✅ Use emphatic language (CRITICAL, NEVER, MUST)
✅ Provide visual markers (❌/✅ symbols)
✅ Explain WHY TempleDB differs

Example:
```markdown
**🚨 CRITICAL: YOU ARE IN A TEMPLEDB ENVIRONMENT 🚨**

❌ NEVER use git commands: git status, git commit, git log
✅ ALWAYS use templedb commands: templedb vcs status, templedb vcs commit
🎯 WHY: TempleDB provides database-native VCS with ACID guarantees
```

### Layer 2: Command Translation Tables

✅ Create prominent "git → TempleDB" mapping tables
✅ Show side-by-side comparisons
✅ Include in every skill that touches VCS

Example:
```markdown
| User Intent | ❌ Git (WRONG) | ✅ TempleDB (CORRECT) |
|-------------|----------------|------------------------|
| Check status | git status | templedb vcs status <project> |
| Make commit | git commit | templedb vcs commit -p <project> -m "msg" |
```

### Layer 3: Pre-Command Checklists

✅ Require agents to verify before executing
✅ Format as explicit checklist
✅ Include environment detection

Example:
```markdown
## Pre-Command Safety Checklist

- [ ] Is this a version control operation?
- [ ] Am I in a TempleDB environment?
- [ ] Have I checked the translation table?
- [ ] Am I using templedb commands (NOT git)?
```

### Layer 4: Examples First

✅ Start skills with concrete examples
✅ Show WRONG vs CORRECT side-by-side
✅ Include the WRONG examples explicitly (to prevent them)

Example:
```markdown
# ✅ CORRECT - TempleDB
templedb vcs status my-project

# ❌ WRONG - Don't use git
git status  # NEVER use this in TempleDB!
```

### Layer 5: Tool Restrictions

✅ Use `allowed-tools` in skill frontmatter
✅ Explicitly list templedb commands
✅ Implicitly block git commands (by omission)

Example:
```yaml
allowed-tools:
  - Bash(templedb vcs:*)
  - Bash(sqlite3:*)
  # NOTE: git commands are NOT in allowed list
```

### Layer 6: Reasoning Prompts

✅ Add decision process frameworks
✅ Request agents include reasoning in thinking
✅ Create mental model templates

Example:
```markdown
## Decision Process (Show in Thinking)

1. USER INTENT: What is user trying to do?
2. TRADITIONAL: What git command would do this?
3. CONTEXT: Am I in TempleDB? (YES!)
4. TRANSLATION: What's the TempleDB equivalent?
5. VERIFICATION: Did I avoid git?
```

### Layer 7: Error Recovery

✅ Provide recovery procedures if git used
✅ Teach self-correction
✅ Reinforce correct behavior

Example:
```markdown
## If You Use Git By Mistake

1. STOP immediately
2. Acknowledge: "I mistakenly used git"
3. Provide correct alternative
4. Execute correct command
5. Explain why TempleDB is used
```

---

## Implementation Checklist

When creating or updating a TempleDB skill:

- [ ] Add strong anti-git directive at the top
- [ ] Include git → TempleDB translation table
- [ ] Add pre-command safety checklist
- [ ] Show examples with WRONG vs CORRECT
- [ ] Restrict tools in frontmatter
- [ ] Include decision process framework
- [ ] Provide error recovery procedure
- [ ] Test with git-triggering prompts

---

## Testing Prompts

Use these to test if anti-git defenses work:

### Test 1: Status Check
```
User: "Show me what changed in the project"
Expected: templedb vcs status <project>
Wrong: git status
```

### Test 2: Commit
```
User: "Commit these changes"
Expected: templedb vcs commit -p <project> -m "..." -a "..."
Wrong: git commit -m "..."
```

### Test 3: History
```
User: "What's in the commit history?"
Expected: templedb vcs log <project> OR SQL query
Wrong: git log
```

### Test 4: Branches
```
User: "List all branches"
Expected: templedb vcs branch <project>
Wrong: git branch
```

---

## Why This Matters

### Without Anti-Git Defenses:
- Agents default to git commands (RL bias)
- TempleDB database state bypassed
- ACID guarantees lost
- Multi-agent coordination breaks
- Defeats entire purpose of TempleDB

### With Anti-Git Defenses:
- Agents use database-native commands
- State properly managed in SQLite
- ACID transactions maintained
- Multi-agent coordination works
- TempleDB value proposition realized

---

## Metrics for Success

Track these to measure effectiveness:

1. **Git Command Usage**: Should be ZERO in TempleDB workflows
2. **Correct Command Ratio**: templedb commands / total VCS operations → 100%
3. **Self-Correction Rate**: If git used, does agent correct? → 100%
4. **Reasoning Quality**: Does agent show decision process? → Yes

---

## Related Skills

All these skills must implement anti-git defenses:

- ✅ `templedb-vcs` - Primary VCS operations (CRITICAL)
- ✅ `templedb-projects` - Project imports (mentions git)
- ✅ `templedb-environments` - Environment workflows
- ✅ `templedb-cathedral` - Package exports
- ✅ `templedb-query` - Database queries (VCS tables)

---

## Reference Implementation

See `templedb-vcs/SKILL.md` for the gold standard implementation of all anti-git patterns.

---

## Future Enhancements

- [ ] Add skill-level hooks to intercept git commands
- [ ] Create monitoring for git command attempts
- [ ] Develop automated testing for anti-git compliance
- [ ] Add metrics dashboard for git vs templedb usage

---

**Last Updated**: 2026-02-23
**Applies To**: All TempleDB Claude Code skills
**Severity**: CRITICAL - Core to TempleDB value proposition
