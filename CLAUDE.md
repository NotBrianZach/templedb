# TempleDB Development Instructions

## Where the plan landed

The observer/integrator plan (see
[`reports/2026-09-02-1430-from-observer-to-integrator-implementation-plan.html`](reports/))
completed Phases 0–3 during 2026-09-01 through 2026-09-03. Session recap
at [`reports/2026-09-03-1530-session-recap-*.html`](reports/).

**Current stance**: TempleDB observes source (git is authoritative), owns
intents + relationships + the cross-authority knowledge graph. Six
ingest adapters keep the graph in sync (hourly systemd timer). Ten
doctor invariants + one active-probe reconcile (daily systemd timer)
detect drift. See [`docs/ENTITY_GRAPH_DESIGN.md`](docs/ENTITY_GRAPH_DESIGN.md)
for the categorical framing.

Fastest orientation:
```bash
templedb summary                      # health at a glance
templedb entity search <keyword>      # search the 12k-entity graph
templedb provenance machine <host>    # what motivated the code running there
templedb gui                          # /entities and /summary in the browser
```

Phase 4 (SCIP for cross-language code facts) and Phase 5 (retire
authority-over-source vocabulary — this section IS Phase 5) are the
remaining tranches. Everything else is polish.

## Dogfooding: Use TempleDB For Everything

This project is managed by TempleDB. Use `templedb` commands instead of
raw `git` and standard tools wherever possible.

## Recommended: CLI-first workflow

The CLI reads/writes SQLite directly and is the safest interface for any
automation, agent, or scripted change. Under the observer model
(Phase 3+), edits go through EditIntent, and source snapshots come from
git via ingest adapters. The workflow:

```bash
# Read files (snapshot from DB — populated by ingest)
templedb file cat templedb src/services/vcs_service.py
templedb file ls  templedb src/cli/ -l                  # with line counts

# Read at a specific revision (source_snapshots view — Phase 1)
templedb source snapshot templedb src/foo.py --rev abc123 --meta

# Write files (routes through EditIntent — Phase 2)
templedb file set templedb src/foo.py --content "..."   # creates+applies intent
cat new_code.py | templedb file set templedb src/foo.py
templedb file set templedb src/foo.py --content "..." --skip-intent  # bypass

# Recommended: interactive edit workspace (Phase 0 + edit-workspaces/)
templedb edit templedb                                  # $EDITOR in workspace
# ...edit files in ~/.config/templedb/edit-workspaces/templedb/...
templedb commit templedb ~/.config/templedb/edit-workspaces/templedb -m "..."
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

## Entity graph (Phase 3 vocabulary)

As of migrations 089–095, TempleDB carries a typed knowledge graph
that unifies facts across git, nix, agent-runtime, deployment, and
author authorities. See [`docs/ENTITY_GRAPH_DESIGN.md`](docs/ENTITY_GRAPH_DESIGN.md)
for the categorical framing (entities as objects, relations as
morphisms, first-class spans, commuting-diagram invariants).

**Tables:** `entities (kind, external_ref, source_authority, label,
observed_at)` + `relations (from, kind, to, source_authority, observed_at,
attributes_json)` + first-class span tables (`edit_intents`,
`report_implementations`, `tool_calls`, plus existing `ast_builds`,
`deployment_history`, `nix_generations`).

### Populate the graph

```bash
templedb ingest all                    # all six adapters
templedb ingest {git,agent,intent,reports,nix,deploy}   # one at a time
templedb ingest history                # per-adapter freshness telemetry
```

### Query the graph

```bash
templedb entity stats                                    # counts by kind
templedb entity explore <kind>/<external_ref>            # one hop out + in
templedb entity trace <kind>/<ref> --depth N --via K1,K2 # multi-hop BFS

# Preset workflow queries (thin wrappers over `entity trace`):
templedb provenance machine <name>       # workflow B: deploy archaeology
templedb provenance deployment <id>      # deployment ↔ commit + machine
templedb provenance report <path>        # workflow F: report → commit
templedb provenance commit <hash>        # reverse walk from a commit
templedb provenance intent <id>          # workflow A: intent → applied-to
```

### Reconcile (Workflow D)

Active probing of foreign authorities. Where doctor is passive,
reconcile is network-active:

```bash
templedb reconcile machine <name>        # SSH probe + diff against DB
templedb reconcile machine all           # every fleet_machine
templedb reconcile history [--machine]   # persisted run log (mig 095)

templedb doctor entities                 # passive commuting invariants
templedb doctor history [--check NAME]   # per-check history (mig 092)
```

### Cross-session handoff (Phase 2.5)

```bash
templedb handoff send --topic <t> --subject "..." --body "..."
templedb handoff send --broadcast --subject "..." --body "..."
templedb handoff list [--for SID] [--unread]
templedb handoff show <id>              # marks read
templedb handoff ack <id> [-m note]     # marks acked
templedb handoff pop [--for SID]        # show + ack oldest unacked
```

Unread count appears in `templedb status` when non-zero.

### Web GUI: /entities

`templedb gui` → http://localhost:8420/entities → browse the graph.
Click a kind for the list; click an entity for its detail with
inbound/outbound relations as clickable links.

## What NOT to do

- Do NOT edit files in `~/.config/templedb/checkouts/` directly (read-only,
  auto-generated by `publish`). Use `templedb edit <slug>` for a writable
  workspace under `~/.config/templedb/edit-workspaces/<slug>/`.
- Do NOT use `grep -r` or `find` for code search — use `templedb graph search`
  (raw text) or `templedb entity search` (semantic graph).
- Do NOT edit files at `/home/zach/templeDB/` directly — that's the CLI
  wrapper location.

**Softened under the observer plan** (no longer forbidden):
- `git add`/`commit`/`push`/`status`/`diff`/`log` in a git checkout are fine
  again — git is authoritative for source; templedb observes via ingest.
  See `docs/ENTITY_GRAPH_DESIGN.md` for the framing.
- `templedb vcs commit -p` and `templedb file set` both work correctly in
  the current binary (probed 2026-09-01). The workspace-diff
  `templedb commit <slug> <workspace>` path is still recommended for
  scripted / multi-file changes but not the only option.

## Project Info

- **Slug**: `templedb`
- **DB**: `~/.local/share/templedb/templedb.sqlite`
- **CLI**: `/home/zach/templeDB/templedb`
- **GUI**: `templedb gui` (port 8420)
- **Interactive editing**: `templedb edit templedb` (opens `$EDITOR` in `~/.config/templedb/edit-workspaces/templedb/`)
