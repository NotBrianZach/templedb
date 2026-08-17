# TempleDB Development Instructions

## Dogfooding: Use TempleDB For Everything

This project is managed by TempleDB. Use `templedb` commands instead of
raw `git` and standard tools wherever possible.

## Recommended: CLI-first workflow

The CLI reads/writes SQLite directly and is the safest interface for any
automation, agent, or scripted change. Use this by default:

```bash
# Read files (from DB, no FUSE required)
templedb file cat templedb src/temple_fuse.py
templedb file ls  templedb
templedb file ls  templedb src/cli/ -l                  # with line counts

# Write files (direct DB write via content_blobs)
templedb file set templedb src/foo.py --content "..."
cat new_code.py | templedb file set templedb src/foo.py
templedb file set templedb src/foo.py --content "..." --verify   # confirm blob landed
templedb file edit templedb src/foo.py                  # $EDITOR round-trip
templedb file checkout templedb src/foo.py -o /tmp/     # extract to disk

# Commit changes safely
templedb project checkout templedb /tmp/tdb-work --writable --force
# ...edit files in /tmp/tdb-work...
templedb commit templedb /tmp/tdb-work -m "your message"
```

`templedb commit` (alias for `templedb project commit`) compares your
workspace directory against DB and creates a commit from filesystem
content. **Use it instead of `templedb vcs commit`** — see "Known bugs"
below.

## VCS: use templedb, not git

```bash
templedb vcs status  templedb --refresh
templedb vcs add     -p templedb --all
templedb vcs log     templedb
templedb vcs diff    templedb --staged
templedb publish run templedb -m "msg"       # commit + materialize + push

# Branches
templedb vcs branch templedb                 # list
templedb vcs branch templedb feature-x       # create
templedb vcs switch templedb feature-x       # switch
templedb vcs merge  templedb feature-x       # merge (add --squash if wanted)
templedb vcs branch templedb -d feature-x    # delete
```

`templedb vcs commit -p <slug> -m "msg"` exists but has a known
correctness bug (see below). Prefer `templedb commit <slug> <workspace>`.

## Search: use templedb graph

```bash
templedb graph search    "merge_resolver"    # NOT grep -r
templedb graph who-uses  SOME_VAR            # cross-project search
templedb graph build-deps templedb           # dependency graph
templedb graph importers templedb src/file   # who imports this?
templedb graph callers   templedb someFunc   # who calls this?
```

## FUSE mount (advanced — for interactive editing only)

There is a FUSE mount at `~/temple/templedb/` that exposes DB content as
a regular filesystem. It's convenient for editing with `vim`/`emacs`
because file-close automatically stages in `vcs_working_state`.

```bash
# Mount if not already mounted
templedb mount ~/temple

# Interactive editing
vim ~/temple/templedb/src/cli/commands/vcs.py
```

**This path is only appropriate for interactive human editing.** Tool-driven
changes and agent workflows must use the CLI — see known bugs.

## Dev mode: `TEMPLEDB_DEV_MODE=1`

When you're actively editing templedb source, set `TEMPLEDB_DEV_MODE=1`
in your shell. The nix-installed `templedb` binary then prefers the
materialized checkout at `~/.config/templedb/checkouts/templedb/src` over
the frozen nix package — so `templedb file set …` followed by `templedb
<subcommand>` picks up the edit immediately, no rebuild needed.

```bash
export TEMPLEDB_DEV_MODE=1
templedb file set templedb src/cli/commands/foo.py --content "..."
templedb foo bar    # runs the new code from the checkout
```

Bonus: if the checkout is behind the DB (e.g. you did `file set` without
`file checkout`), you'll get a one-line stderr warning naming the disk
and DB hashes plus the fix (`templedb publish run templedb`). Silent
otherwise.

Anyone with `direnv` can also `direnv allow` the templedb repo directory
— an `.envrc` there auto-sets the env var when you `cd` in and unsets it
when you leave.

Default (env var unset): behavior unchanged. The frozen nix package
wins, reproducibility preserved. Only enable if you're editing templedb
itself.

Design and options considered:
`reports/2026-08-16-nix-profile-staleness-design.html`.

## Write-path history and remaining hazards

**Recently fixed (2026-08-04, commits DBB417D8, 40BAE4CF, 189F33CA):**
The "`vcs commit` silently reverts `file set` writes" bug. `templedb
file set` now writes the new `content_hash` into `vcs_working_state`
and mirrors the content to the checkout dir, so a subsequent
`vcs commit` or `vcs status --refresh` no longer clobbers the intended
content. If you observe this class of bug returning, verify those three
commits are in your build.

**Still relevant — FUSE write truncation risk.**
Large Edit-tool or piped writes through the `~/temple/templedb/` FUSE
mount have been observed to truncate mid-file. The DB write reports
success, `file cat` returns the truncated content unnoticed, and only a
byte-count or parse check against the intended input catches it.
Verified 2026-08-03 (a `src/services/config_compiler.py` write lost
~100 lines). No fix landed yet.
**Mitigation:** for non-trivial writes, prefer piped `templedb file set
--verify` (returns exit 2 on hash mismatch) over Edit-through-FUSE;
after any write, `wc -l` or `python3 -c "import ast;
ast.parse(open(path).read())"` sanity check.

**Belt-and-suspenders SQL check** (run after any critical write):

```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT fc.line_count, substr(fc.content_hash,1,12)
     FROM file_contents fc
     JOIN project_files pf ON pf.id = fc.file_id
     JOIN projects p ON p.id = pf.project_id
    WHERE p.slug = '<slug>'
      AND pf.file_path = '<path>'
      AND fc.is_current = 1;"
```

## What NOT to do

- Do NOT use `git add`, `git commit`, `git push`, `git status`, `git diff`, `git log`
- Do NOT rely on `templedb vcs commit` for tool-driven / scripted changes — use `templedb commit`
- Do NOT edit files in `~/.config/templedb/checkouts/` directly (read-only, auto-generated by `publish`)
- Do NOT use `grep -r` or `find` for code search — use `templedb graph search`
- Do NOT edit large files through the FUSE mount without a post-write size check
- Do NOT edit files at `/home/zach/templeDB/` directly — that's the CLI wrapper location

## Project Info

- **Slug**: `templedb`
- **DB**: `~/.local/share/templedb/templedb.sqlite`
- **CLI**: `/home/zach/templeDB/templedb`
- **GUI**: `templedb gui` (port 8420)
- **FUSE mount** (interactive editing only): `~/temple/templedb/`
