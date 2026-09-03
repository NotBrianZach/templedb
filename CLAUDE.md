# TempleDB Development Instructions

## Dogfooding: Use TempleDB For Everything

This project is managed by TempleDB. Use `templedb` commands instead of
raw `git` and standard tools wherever possible.

## Recommended: CLI-first workflow

The CLI reads/writes SQLite directly and is the safest interface for any
automation, agent, or scripted change. Use this by default:

```bash
# Read files (from DB)
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

## Interactive editing: `templedb edit <slug>`

For a full-editor session on a project (multi-file, LSP, navigation),
use the workspace on-ramp:

```bash
templedb edit templedb              # opens $EDITOR in a writable workspace
templedb edit templedb --no-editor  # just prepare the workspace, don't launch
templedb edit bza src/foo.tsx       # optional: jump directly to a file
```

The workspace lives at `~/.config/templedb/edit-workspaces/<slug>/` and
persists across `templedb edit` invocations. Edit files there normally,
then commit back to the DB:

```bash
templedb commit <slug> ~/.config/templedb/edit-workspaces/<slug> -m "…"
```

For a single-file edit without a full workspace, use
`templedb file edit <slug> <path>` (opens `$EDITOR` on the DB blob).

The FUSE mount at `~/temple/…` was removed in 2026-08 in favor of this
workflow (see `reports/2026-08-29-post-fuse-editing-ux-alternatives-and-recommendation.html`
for the analysis).

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

## Sessions: `TEMPLEDB_SESSION_ID`

`vcs add` / `vcs commit` are scoped to a **session** — a row in
`vcs_sessions` that identifies who staged a file. Parallel agents can
stage into the same project without sweeping each other's work into a
commit, because `vcs commit` only reads rows staged by the current
session.

For a single interactive user in one shell, sessions are invisible:
sequential `templedb` invocations from the same shell auto-share an
implicit session (matched on `author`, `host`, `ppid`), so
`vcs add X; vcs commit -m …` works exactly like it always did.

For multi-agent or auditable workflows, be explicit:

```bash
# Start a named session, export the ID
eval "$(templedb vcs session start --name my-refactor | grep '^  export')"

# All subsequent templedb calls in this shell use session $TEMPLEDB_SESSION_ID
templedb vcs add -p templedb src/foo.py
templedb vcs commit -p templedb -m "refactor foo"

# Or list / inspect
templedb vcs session list --active
templedb vcs session show <id>
templedb vcs status templedb --all    # grouped view of every session's stage
```

`vcs status` displays the current session badge and, when other sessions
have rows staged, prints a `Staged in other sessions` footer so surprise
sweeps aren't possible.

Design and semantics:
`reports/2026-08-20-session-scoped-vcs-staging-design.html`.
Investigation of the related revert regression:
`reports/2026-08-21-vcs-commit-revert-regression-investigation.html`.

## Write-path history and remaining hazards

**Recently fixed (2026-08-04, commits DBB417D8, 40BAE4CF, 189F33CA):**
The "`vcs commit` silently reverts `file set` writes" bug. `templedb
file set` now writes the new `content_hash` into `vcs_working_state`
and mirrors the content to the checkout dir, so a subsequent
`vcs commit` or `vcs status --refresh` no longer clobbers the intended
content. If you observe this class of bug returning, verify those three
commits are in your build.

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

## Source snapshots vs `file_contents` (Phase 1 vocabulary)

As of migration 086, `file_contents` is a **snapshot** table, not an
authoritative-bytes store. The row with `is_current=1` is the most
recent *observation* of a file, not "the truth of the file." Truth of
source code lives in git — TempleDB records what it saw.

Query surface:

```bash
# Current snapshot (equivalent to templedb file cat)
templedb source snapshot <slug> <path>

# Historical snapshot at a specific commit
templedb source snapshot <slug> <path> --rev <commit_hash>

# Metadata only (content_hash, observed_at, source_authority)
templedb source snapshot <slug> <path> --meta

# Every known revision of a file
templedb source revisions <slug> <path>
```

Backing view: `source_snapshots` (columns: `project_slug, file_path,
revision, content_hash, content_text, content_blob, content_type,
file_size_bytes, line_count, observed_at, source_authority`).

Direct SQL still works:

```sql
SELECT * FROM source_snapshots
 WHERE project_slug = 'templedb'
   AND file_path = 'src/foo.py'
   AND revision = 'current';   -- or a real commit_hash
```

This is Phase 1 of the observer/integrator plan. See
`reports/2026-09-02-1430-from-observer-to-integrator-implementation-plan.html`.

## What NOT to do

- Do NOT use `git add`, `git commit`, `git push`, `git status`, `git diff`, `git log`
- Do NOT rely on `templedb vcs commit` for tool-driven / scripted changes — use `templedb commit`
- Do NOT edit files in `~/.config/templedb/checkouts/` directly (read-only, auto-generated by `publish`)
- Do NOT use `grep -r` or `find` for code search — use `templedb graph search`
- Do NOT edit files at `/home/zach/templeDB/` directly — that's the CLI wrapper location

## Project Info

- **Slug**: `templedb`
- **DB**: `~/.local/share/templedb/templedb.sqlite`
- **CLI**: `/home/zach/templeDB/templedb`
- **GUI**: `templedb gui` (port 8420)
- **Interactive editing**: `templedb edit templedb` (opens `$EDITOR` in `~/.config/templedb/edit-workspaces/templedb/`)
