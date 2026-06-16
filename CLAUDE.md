# TempleDB Development Instructions

## Dogfooding: Use TempleDB, Not Raw Git

This project is managed by TempleDB. **Use `templedb` commands instead of raw `git` for all VCS operations.**

### VCS Commands (instead of git)

```bash
# Instead of: git status
templedb vcs status templedb --refresh

# Instead of: git add
templedb vcs add -p templedb --all          # stage all
templedb vcs add -p templedb file1 file2    # stage specific files

# Instead of: git commit
templedb vcs commit -p templedb -m "message"

# Instead of: git log
templedb vcs log templedb

# Instead of: git diff
templedb vcs diff templedb --staged

# Instead of: git push (commit + materialize to git + push)
templedb publish run templedb -m "message"

# Branch operations
templedb vcs branch templedb                # list branches
templedb vcs branch templedb feature-x      # create branch
templedb vcs switch templedb feature-x      # switch branch
templedb vcs merge templedb feature-x       # merge into current
templedb vcs merge templedb feature-x --squash  # squash merge
```

### What NOT to do

- Do NOT use `git add`, `git commit`, `git push` directly
- Do NOT edit files in `~/.config/templedb/checkouts/` (read-only, auto-generated)
- Use `templedb publish` to push to GitHub, not `git push`

### Project Info

- **Slug**: `templedb`
- **DB Path**: `~/.local/share/templedb/templedb.sqlite`
- **FUSE Mount**: `~/temple/templedb/` (if mounted)
- **CLI**: `/home/zach/templeDB/templedb`

### Running Queries

```bash
# Use the MCP tools or Python for direct DB queries when needed
python3 -c "
import sqlite3
conn = sqlite3.connect('$HOME/.local/share/templedb/templedb.sqlite')
# your query here
conn.close()
"
```
