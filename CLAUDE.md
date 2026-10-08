# TempleDB Development Instructions

TempleDB manages this project. Prefer `templedb` commands over raw git
and standard tools. Design docs and project history live in `reports/`
(dated) and `docs/ENTITY_GRAPH_DESIGN.md` — this file is operating
instructions only.

## Read this first: three ways to lose work

**1. `file set` replaces the WHOLE file.** A copy you fetched earlier is
a lock on the entire file: anything committed between your read and your
write is reverted silently, with no conflict. `--verify` does not catch
it — it confirms that what you wrote is what landed, not that you meant
to drop the rest. Always pass `--if-match` on a file you did not just
read:

```bash
templedb source snapshot <slug> <path> --meta     # prints content_hash
templedb file cat <slug> <path> > /tmp/f
# ...patch /tmp/f...
templedb file set <slug> <path> --if-match <hash12> --verify < /tmp/f
```

`--if-match` takes a full sha256 or any prefix of >= 8 hex chars, so the
truncated hashes from `file where`, `source snapshot --meta` and doctor
all work. It exits 2 on mismatch and names both hashes.

**2. Commit the session workspace, not its parent.** Edit workspaces are
per-session: `~/.config/templedb/edit-workspaces/<slug>/<session-name>/`.
The parent `<slug>/` directory may itself look like a project root while
being months stale and containing every other session's tree. Committing
it reverts everything newer and sweeps in thousands of phantom paths.
Always commit the full path including the session name, and get it from
`templedb edit` rather than typing it:

```bash
templedb edit <slug>                       # prints the exact path — use that
templedb commit <slug> <that-path> -m "…"
```

`commit` refuses when half or more of the tracked files are missing from
the directory you handed it, since that almost always means a wrong
path rather than a real purge. Override with `--allow-mass-delete`.
`project checkout --force` likewise refuses a target that *encloses*
other checkouts — its stray-purge would delete every file in them.

**3. Staging is session-scoped.** `vcs add` / `vcs commit` only see rows
staged by the *current* session, and each agent Bash tool call gets a
fresh shell with a fresh session-leader PID and no inherited env. Stage
in one call and commit in another and the commit finds nothing. See
[Sessions](#sessions) for the fix.

## Orientation

```bash
templedb summary                      # health at a glance; authoritative
templedb entity search <keyword>      # search the entity graph
templedb provenance machine <host>    # what motivated the code running there
templedb gui                          # /entities and /summary (port 8420)
```

## Reading code

Source of truth for source code is git; TempleDB records what it
observed. `file_contents` is a snapshot table — the `is_current=1` row is
the most recent *observation*, not "the truth of the file."

```bash
templedb file cat <slug> <path>                      # current snapshot
templedb file ls  <slug> src/ -l                     # with line counts
templedb source snapshot <slug> <path> --rev <hash>  # at a revision
templedb source snapshot <slug> <path> --meta        # hash, observed_at
templedb source revisions <slug> <path>              # every known revision
```

Backing view: `source_snapshots (project_slug, file_path, revision,
content_hash, content_text, content_blob, content_type,
file_size_bytes, line_count, observed_at, source_authority)`.

## Search: pick the right one

Three commands search three different things. Picking wrong makes code
that exists look like it doesn't.

| Command | Searches | Notes |
|---|---|---|
| `search content X` | file contents | FTS5; supports `"phrase"`, `AND`/`OR`/`NOT`, `pre*` |
| `graph who-uses X` | file contents | plain substring, no tokenisation; use for underscores/punctuation |
| `graph search X` | names, paths, commit messages | **not** file contents |

```bash
templedb search content  "apply_standard_pragmas"   # fast, ranked
templedb graph who-uses  "apply_standard_pragmas"   # substring, slower
templedb graph search    "merge_resolver"           # paths + commit messages

templedb graph build-deps <slug>              # dependency graph
templedb graph importers  <slug> src/file     # who imports this?
templedb graph callers    <slug> someFunc     # who calls this?
```

`graph search` returning nothing means "no such path or commit message",
not "this string appears nowhere."

If `search content` results look impossibly thin, the FTS index is
stale: `templedb search reindex`.

## Writing code

**Multi-file work — edit workspace (recommended).** Diffs against the DB
instead of overwriting blind.

```bash
templedb edit <slug>                          # provision workspace, print path
# ...edit files at the printed path...
templedb commit <slug> <that-path> -m "…"
```

`templedb edit` does **not** open an editor and returns immediately —
that is the form agents and scripts want. `--editor` runs `$EDITOR` in
the foreground and blocks until you close it; never use it from a tool
call or the command will appear to hang with no indication why.

**Single file — `file set`.** Routes through EditIntent. Re-read
immediately before writing and pass `--if-match` (see hazard 1).

```bash
cat new_code.py | templedb file set <slug> src/foo.py --if-match <hash12>
templedb file set <slug> src/foo.py --content "..." --skip-intent   # bypass intent
echo "..." | templedb file set <slug> <path> --commit -m "msg"      # write+commit atomically
```

`file set` lands content *without* a commit. "No changes" from
status/add/commit afterwards is expected, not a failed write.

**Verify after any critical write.** Read it back through the same path
everyone else uses:

```bash
templedb file cat <slug> <path> | sha256sum      # must match your source
templedb file cat <slug> <path> | wc -l          # must match your line count
```

For ad-hoc SQL, neither `sqlite3` nor `python3` is reliably on your
shell's PATH. Use the MCP `templedb_query` tool, or a nix shell with
`python3` if you need one outside an MCP client.

## Sessions

A session is a row in `vcs_sessions` identifying who staged a file, so
parallel agents can stage into one project without sweeping each other's
work into a commit. For a single interactive shell they are invisible:
sequential invocations auto-share an implicit session keyed on
(author, host, session-leader PID).

Three ways to steer identity, highest precedence first:

```bash
# 1. --session flag — explicit at the call site, shows up in --help.
templedb vcs add    -p <slug> --session <id|name> <path>
templedb vcs commit -p <slug> --session <id|name> -m "…"
templedb vcs status    <slug> --session <id|name>

# 2. TEMPLEDB_SESSION_ID=<int> — an exact id. Must reference a live row.
# 3. TEMPLEDB_SESSION=<name> — resolved against (author, host, active).
```

Accepted on `vcs add`, `reset`, `commit`, `status`. A name is created if
absent on write commands; `vcs status` resolves strictly and never
creates one, so a typo errors instead of opening a junk session.

**Agent workflows: open the session before `templedb edit`.** The two
functions answering "which session is this?" differ on whether they may
create one. The staging path auto-creates for an unknown name; the
function that stamps the `checkouts` row deliberately never does, so if
`templedb edit` is the *first* call after setting the var, you get the
right directory name and `session_id IS NULL` — an unowned tree that
`admin checkout-gc` cannot clean and that makes `checkout_matches_db`
and `checkout_roles_are_unambiguous` go red.

```bash
templedb vcs session start --name agent-<slug>   # FIRST
export TEMPLEDB_SESSION=agent-<slug>             # then declare it
templedb edit <slug>                             # now the tree is owned
```

Unowned trees fall back to "newest active edit tree wins", which a
materialise elsewhere can change mid-session. So those two doctor checks
going red is usually an unpinned agent rather than dead data.

```bash
templedb vcs session list --active
templedb vcs session current          # the resolved session
templedb vcs session show <id>
templedb vcs session end  <id>
templedb vcs status <slug> --all      # every session's stage, grouped
```

## Committing and publishing

```bash
templedb vcs status <slug> --refresh
templedb vcs add    -p <slug> --all
templedb vcs log    <slug>
templedb vcs diff   <slug> --staged
templedb publish run <slug> -m "msg"          # commit + materialize + push

templedb vcs branch <slug>                    # list
templedb vcs branch <slug> feature-x          # create
templedb vcs switch <slug> feature-x
templedb vcs merge  <slug> feature-x          # add --squash if wanted
templedb vcs branch <slug> -d feature-x       # delete
```

Both `vcs commit -p` and the workspace-diff `templedb commit` work.
Prefer workspace-diff for scripted or multi-file changes because it
diffs against the DB rather than relying on what got staged.

"Modified" in `vcs status` means *differs from HEAD*, not *differs from
`file_contents`* — a file can be byte-identical to `file cat` and still
genuinely uncommitted.

Only `publish run` reconciles DB-vs-HEAD. For `templedb` that pushes to
a public GitHub mirror.

## Rebuilds and the `flake.lock` trap

`flake.lock` is gitignored in `system_config`, so every
`nixos-rebuild --flake .` re-locks from scratch — it reads via
`git+file://` and only sees committed files. `nix flake update <input>`
writes a pin that nixos-rebuild then ignores. The lock is effectively
transient.

The fix is to put the rev directly in `flake.nix`, which is what
`--pin-input` does:

```bash
templedb publish run <slug> -m "…"
templedb publish run system_config --pin-input <slug> -m "bump <slug>"
templedb nixos system-switch system_config --yes
```

Only `nixos system-switch` is durable; a home-rebuild is evicted at the
next boot. A committed fix is inert until a rebuild — use
`TEMPLEDB_DEV_MODE=1` to run DB-current code without one.

## Dev mode: `TEMPLEDB_DEV_MODE=1`

Set it while editing templedb source. The nix-installed binary then
prefers a checkout over the frozen nix package, so `file set` followed by
a `templedb` subcommand picks up the edit with no rebuild.

```bash
export TEMPLEDB_DEV_MODE=1
export TEMPLEDB_DEV_SRC=<workspace>/src    # pin the tree explicitly
templedb <subcommand>
```

Pin `TEMPLEDB_DEV_SRC`: dev mode otherwise prefers an edit workspace that
may hold stale contents. If the chosen tree is behind the DB you get a
one-line stderr warning naming both hashes. Default (unset) is unchanged
behaviour — the frozen package wins.

## Entity graph

A typed graph unifying facts across git, nix, agent-runtime, deployment
and author authorities. Framing in `docs/ENTITY_GRAPH_DESIGN.md`;
per-adapter analysis in `docs/INGEST_ADAPTERS.md`.

`ingest <adapter>` mostly projects TempleDB's own relational tables into
the graph — it does **not** re-read the authority. `ingest git` reads
`vcs_commits`, not git. So a fresh ingest history means "graph matches
tables", not "graph matches git"; only `doctor entities` and `reconcile`
check the authority. Exceptions: `nix` probes `nix-store`, `scip` reads
`.scip` files.

Tables: `entities (kind, external_ref, source_authority, label,
observed_at)`, `relations (from, kind, to, source_authority,
observed_at, attributes_json)`, plus span tables (`edit_intents`,
`report_implementations`, `tool_calls`, `ast_builds`,
`deployment_history`, `nix_generations`).

```bash
templedb ingest all                   # every adapter
templedb ingest <adapter>             # see `templedb ingest --help`
templedb ingest history               # per-adapter freshness

templedb entity stats
templedb entity explore <kind>/<external_ref>          # one hop out + in
templedb entity trace   <kind>/<ref> --depth N --via K1,K2

templedb provenance machine <name>    # deploy archaeology
templedb provenance report  <path>    # report → commit
templedb provenance commit  <hash>    # reverse walk
templedb provenance intent  <id>      # intent → applied-to
```

Ingest ok/err counts in `templedb summary` are **cumulative** — a big
error count is often a long-closed outage. Check
`MIN/MAX(started_at)` in `ingestion_runs` before calling an adapter
broken.

Drift detection — doctor is passive, reconcile is network-active:

```bash
templedb doctor entities              # commuting invariants
templedb doctor history [--check NAME]
templedb reconcile machine <name>     # SSH probe + diff against DB
templedb reconcile machine all
templedb reconcile history [--machine]
```

## Cross-session handoff

```bash
templedb handoff send --topic <t> --subject "..." --body "..."
templedb handoff send --broadcast --subject "..." --body "..."
templedb handoff list [--for SID] [--unread]
templedb handoff show <id>            # marks read
templedb handoff ack  <id> [-m note]  # marks acked
templedb handoff pop  [--for SID]     # show + ack oldest unacked
```

Unread count appears in `templedb status` when non-zero.

## What NOT to do

- Do NOT edit files in `~/.config/templedb/checkouts/` — read-only,
  auto-generated by `publish`. Use `templedb edit <slug>`.
- Do NOT edit files at `/home/zach/templeDB/` — sources only, not the
  installed CLI. Edits there do nothing.
- Do NOT use `grep -r` or `find` for code search — see
  [Search](#search-pick-the-right-one) before concluding code is absent.
- Do NOT commit the parent of a session workspace (hazard 2).
- `git add`/`commit`/`push`/`status`/`diff`/`log` in a git checkout are
  fine — git is authoritative for source; templedb observes via ingest.

## Project info

- **Slug**: `templedb`
- **DB**: `~/.local/share/templedb/templedb.sqlite`
- **CLI**: `~/.nix-profile/bin/templedb` (just `templedb` on PATH).
  `/home/zach/templeDB/templedb` does not exist; pointing a service at
  it fails with `status=203/EXEC`.
- **GUI**: `templedb gui` (port 8420)
