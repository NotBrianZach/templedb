# Vibe Session MCP Tool Guidance

**Date**: 2026-04-07
**Status**: Implemented

## Overview

Enhanced the `vibe start` command to automatically include MCP tool usage guidelines in every session prompt. This ensures Claude Code consistently uses MCP tools instead of falling back to bash commands.

## Changes Made

### Modified: `src/cli/commands/vibe_realtime.py`

Enhanced the `_ensure_project_prompt()` method (line 318) to include comprehensive MCP tool usage guidance in the auto-generated project prompts.

### What Was Added

**1. Session Rules Section**
- Critical MCP tool usage policy
- Pre-flight checklist for every operation
- Common mistakes to avoid with examples

**2. Enhanced MCP Tools Documentation**
- Complete list of available MCP tools by category
- Decision tree for tool selection
- Correct vs incorrect usage examples

**3. Improved Examples**
- Side-by-side comparison of wrong (bash) vs right (MCP) approaches
- Specific tool names and parameters
- Mental model for tool selection

## Session Prompt Structure

Every `vibe start` session now includes:

```
## 📋 SESSION RULES - READ FIRST

**CRITICAL: MCP Tool Usage Policy**

1. ✅ MCP tools ALWAYS preferred over bash commands
2. ✅ Check available tools BEFORE every operation
3. ✅ Bash is ONLY for actual shell operations
4. ✅ For TempleDB operations: Use `templedb_*` MCP tools
5. ✅ For file operations: Use Read/Write/Edit/Grep/Glob tools

[Pre-flight checklist]
[Common mistakes]
[Decision tree]
[Examples]
```

## Benefits

### 1. Automatic Guidance
- No need to manually paste session rules
- Consistent across all vibe sessions
- Part of the workflow, not an afterthought

### 2. Clear Mental Model
- Decision tree shows when to use each tool type
- Examples demonstrate correct patterns
- Mistakes section prevents common errors

### 3. Reduced Context Switching
- Guidelines always present in session context
- No need to refer to external documentation
- Immediate feedback on tool selection

### 4. Better Training
- Claude Code sees correct patterns every session
- Reinforces MCP tool usage over time
- Reduces bash command fallback

## Usage

### Starting a Vibe Session

```bash
# Start vibe session (guidance auto-loaded)
./templedb vibe start myproject

# The project prompt now includes:
# - MCP tool usage policy
# - Available tools list
# - Decision tree
# - Examples
```

### What Claude Code Sees

When a vibe session starts, Claude Code receives:

1. **Project context** (files, metadata, structure)
2. **Session rules** (MCP tool policy) ← NEW
3. **Available tools** (complete list) ← ENHANCED
4. **Decision tree** (tool selection guide) ← NEW
5. **Examples** (correct vs incorrect) ← NEW

## Tool Categories

### TempleDB Operations
- `templedb_project_list`
- `templedb_project_show`
- `templedb_query`
- `templedb_context_generate`
- `templedb_search_files`

### Version Control
- `templedb_vcs_status`
- `templedb_vcs_log`
- `templedb_vcs_commit`
- `templedb_vcs_diff`
- `templedb_vcs_branch`

### File Operations
- `Read`
- `Write`
- `Edit`
- `Grep`
- `Glob`

## Decision Tree

```
Need to query database? → templedb_query
Need project info? → templedb_project_show
Need VCS status? → templedb_vcs_status
Need to read file? → Read tool
Need to search code? → Grep tool
Need actual shell command? → Then use Bash
```

## Examples of Correct Usage

### Database Query
✅ **Correct:** Use `templedb_query` MCP tool
```
SELECT * FROM projects WHERE slug = 'myproject'
```

❌ **Wrong:** Bash sqlite3 command
```bash
bash sqlite3 ~/.templedb/templedb.db "SELECT..."
```

### VCS Status
✅ **Correct:** Use `templedb_vcs_status` MCP tool
```
project: myproject
```

❌ **Wrong:** Bash templedb command
```bash
bash ./templedb vcs status myproject
```

### File Reading
✅ **Correct:** Use `Read` tool
```
file_path: /path/to/file.py
```

❌ **Wrong:** Bash cat command
```bash
bash cat /path/to/file.py
```

## Implementation Details

### Code Location
- File: `src/cli/commands/vibe_realtime.py`
- Method: `_ensure_project_prompt()`
- Lines: 367-450 (prompt_text definition)

### Auto-Generation
- Triggered when `vibe start` is called
- Only creates prompt if project doesn't have one
- Stores in `project_prompts` table
- Scope: `vibe-session`
- Priority: 50

### Persistence
- Prompts stored in database
- Reused across sessions (until regenerated)
- Can be manually edited if needed

## Future Enhancements

### Potential Improvements

1. **Dynamic Tool Detection**
   - Query MCP server for available tools
   - Generate tool list automatically
   - Update guidance based on installed tools

2. **Usage Analytics**
   - Track MCP tool vs bash usage
   - Identify patterns of incorrect usage
   - Provide session-specific reminders

3. **Interactive Tutorial**
   - First-time users get guided walkthrough
   - Show tool selection in real-time
   - Provide immediate feedback on tool choice

4. **Adaptive Guidance**
   - Strengthen guidance after bash usage
   - Reduce guidance as correct usage improves
   - Context-aware suggestions

5. **Tool Shortcuts**
   - Aliases for common MCP operations
   - Quick reference in session
   - Keyboard shortcuts for tool selection

## Testing

### Manual Test
```bash
# 1. Start vibe session
./templedb vibe start testproject

# 2. Verify prompt includes:
# - SESSION RULES section at top
# - MCP tool list
# - Decision tree
# - Examples

# 3. Test Claude Code behavior
# - Ask for database query
# - Verify it uses templedb_query (not bash)
# - Ask for VCS status
# - Verify it uses templedb_vcs_status (not bash)
```

### Expected Behavior
- Claude Code should prefer MCP tools
- Bash commands should only be for actual shell ops (npm, docker, etc.)
- Database/TempleDB operations should use MCP tools
- File operations should use Read/Write/Edit/Grep/Glob

## Rollback

If changes need to be reverted:

```bash
# Revert the file
git checkout HEAD~1 src/cli/commands/vibe_realtime.py

# Or manually remove the SESSION RULES section
# and restore original prompt_text format
```

## Related Documentation

- [Vibe Getting Started](VIBE_GETTING_STARTED.md)
- [MCP Server Documentation](../src/mcp_server.py)
- [CLI Discoverability Improvements](CLI_DISCOVERABILITY_IMPROVEMENTS.md)
- [TempleDB VCS Skill](.claude/skills/templedb-vcs/SKILL.md)

## See Also

- Session rules template
- MCP tool documentation
- Vibe session workflow
- Project prompt system
