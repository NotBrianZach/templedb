# TempleDB Development Instructions

## Dogfooding: Use TempleDB For Everything

This project is managed by TempleDB. Use `templedb` commands instead of raw `git` and standard tools wherever possible.

### File Access: Use FUSE Mount

Read and write files through the FUSE mount at `~/temple/templedb/`, not `/home/zach/templeDB/`:

```bash
# Read files

# Edit files — writes go to DB and auto-stage for VCS
vim ~/temple/templedb/src/cli/commands/vcs.py
```

If the mount is down: `templedb mount ~/temple`

### File Access Without FUSE (CLI Bypass)

If the FUSE mount is down or stale, use `templedb file` commands to read/write directly from the database:

```bash
templedb file cat templedb src/temple_fuse.py         # read file from DB
templedb file ls templedb                             # list all files
templedb file ls templedb src/cli/ -l                  # list with line counts
templedb file set templedb src/foo.py -c "content"    # write content to DB
cat new_code.py | templedb file set templedb src/foo.py  # pipe content in
templedb file edit templedb src/foo.py                # edit in $EDITOR (DB round-trip)
templedb file checkout templedb src/foo.py -o /tmp/   # extract to filesystem
```

These commands bypass FUSE entirely — they read/write content_blobs in SQLite directly.

### VCS: Use templedb, Not git

```bash
templedb vcs status templedb --refresh       # NOT git status
templedb vcs add -p templedb --all           # NOT git add
templedb vcs commit -p templedb -m "msg"     # NOT git commit
templedb vcs log templedb                    # NOT git log
templedb vcs diff templedb --staged          # NOT git diff
templedb publish run templedb -m "msg"       # NOT git push (commits + materializes + pushes)

# Branches
templedb vcs branch templedb                 # list
templedb vcs branch templedb feature-x       # create
templedb vcs switch templedb feature-x       # switch
templedb vcs merge templedb feature-x        # merge
templedb vcs merge templedb feat --squash    # squash merge
templedb vcs branch templedb -d feature-x    # delete
```

### Search: Use templedb graph

```bash
templedb graph search "merge_resolver"       # NOT grep -r
templedb graph who-uses SOME_VAR             # cross-project search
templedb graph build-deps templedb           # dependency graph
templedb graph importers templedb src/file   # who imports this?
templedb graph callers templedb functionName  # who calls this?
```

### What NOT to Do

- Do NOT use `git add`, `git commit`, `git push`, `git status`, `git diff`, `git log`
- Do NOT edit files at `/home/zach/templeDB/` directly when FUSE is mounted — use `~/temple/templedb/`
- Do NOT use `grep -r` or `find` for code search — use `templedb graph search`
- Do NOT edit files in `~/.config/templedb/checkouts/` (read-only, auto-generated)
- If the FUSE mount is down/stale and `~/temple/` paths fail, use `templedb file` CLI commands (see above) instead of falling back to raw filesystem paths

### Project Info

- **Slug**: `templedb`
- **FUSE Mount**: `~/temple/templedb/`
- **DB**: `~/.local/share/templedb/templedb.sqlite`
- **CLI**: `/home/zach/templeDB/templedb`
- **GUI**: `templedb gui` (port 8420)
