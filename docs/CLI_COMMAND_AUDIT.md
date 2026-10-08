# CLI command audit: what actually runs

A command-by-command pass over all 433 leaf commands, measured
2026-10-08. Companion to [`CLI_SURFACE.md`](CLI_SURFACE.md), which maps
the surface's *shape*; this one records each command's *behaviour*.

The method is the point. `--help` parsing proves a command is
registered, not that it works — every finding below passes `--help`
cleanly. So each safely-runnable command was executed against the
**deployed** binary (dev mode unset) and its exit code and stderr
recorded.

## Coverage, honestly

| | count |
|---|---|
| leaf commands | 433 |
| **executed** | **137** |
| not executed — destructive verb (`deploy`, `rm`, `gc`, `switch`, `push`, …) | 130 |
| not executed — needs review / non-slug argument | 166 |

The 296 unexecuted commands are classified statically only. A command
absent from the broken list below has not been cleared; it has either
passed or not been tried. **Do not read this as "the other 296 work."**

Crash detection reads python exception classes **from stderr only**. An
earlier pass grepped combined output and produced two false positives —
`vcs log` "failed" because one of its commit messages contains the word
`AttributeError`, and `validate` matched its own report text. Exit code
alone is also not a signal: `provenance machine templedb` exits non-zero
because `templedb` is not a Machine, which is correct.

## Broken: 8 commands, 5 root causes

### 1. `NameError: ts_info` — 3 commands

`src/cli/commands/network.py` reads `ts_info` at lines 95, 138 and 178
and **never assigns it** — 4 uses, 0 assignments. The name is a
copy-paste remnant from `sync.py:88`, where `ts_info =
probe_peer(peer["ip"])` does exist.

| command | fails when |
|---|---|
| `sync network status` | ≥1 online peer — prints the header, then raises |
| `sync network setup` | ≥1 online peer (`if online > 0` branch) |
| `sync network sync-all` | **immediately**, on the first peer |

`sync-all` is the worst: `for peer in peers: if not ts_info:` raises
before any sync is attempted, so the command whose entire purpose is
syncing peers cannot ever do it. Only `sync network connect` is
unaffected.

The fix is legible from `sync.py` — assign `probe_peer(peer["ip"])` per
peer — but it is three distinct call sites with slightly different
surrounding intent, so it wants a human decision rather than a blind
substitution.

### 2. Stale table names — 2 commands + 1 silent check failure

Two code paths query tables that do not exist. Both have a real
counterpart under a different name, and in both cases the **columns
differ too**, so this is not a rename that can be patched by
search-and-replace:

| queried | actual table | column drift |
|---|---|---|
| `nixos_packages` | `nixos_managed_packages` | `project_slug`→`project_id`, `name`→`package_name`, `scope`→`install_scope`, `created_at`→`added_at` |
| `nix_services` | `nix_service_metadata` | `opens_port`→`opens_ports` |

- `nixos packages list` and its alias `nixos list-packages` fail with
  `no such table: nixos_packages` (`nixos.py:1076`, `:1081`). The
  write paths at `:1048` and `:1063` target the same missing table, so
  `nixos packages add` / `remove` are presumably broken too — not
  executed, being mutations.
- **`templedb validate <slug>` reports `PASS` and exits 0 while logging
  `no such table: nix_services` to stderr** (`prolog_engine.py:230`).
  Worse than a crash: a validator that passes while one of its own
  checks errored out. The guard comment says "if table exists", so the
  failure is swallowed by design — but the design predates the rename.

### 3. `AttributeError: SystemService.get_system_status` — 2 commands

`nixos system status` and its alias `nixos system-status` raise with a
full traceback. Python's own suggestion is in the error:
`Did you mean: 'get_system_config'?`

### 4. `AttributeError: DeploymentCacheService.db_utils` — 1 command

`admin cache list` → `'DeploymentCacheService' object has no attribute
'db_utils'`. The service reaches for a module as though it were an
instance attribute.

## Slow, not broken

Both succeed (`rc=0`), but exceed the 20s budget a typical agent tool
call allows, so they read as hangs:

| command | wall clock |
|---|---|
| `graph overview` | **42s** |
| `sync status` | **31s** — Tailscale peer probes, 1s socket timeout each |

`graph overview` is pure local query work; 42s is a performance defect
rather than an unavoidable cost.

## Non-zero exits that are correct

Worth recording so a future pass does not re-investigate them:

| command | exit | why it is right |
|---|---|---|
| `doctor entities` | 1 | reports failing invariants; that is its job |
| `admin db check` | 1 | health check reporting findings |
| `config verify` | 1 | verification failure is a result, not a crash |
| `ai agent notify test` | 1 | missing SMTP secrets — configuration, not code |
| `provenance *` (7 cmds) | 1 | `templedb` passed where a machine/commit/intent id is wanted |
| `file where`, `entity explore` | 2 | argparse usage errors from a deliberately wrong arg |

## Per-noun coverage

| noun | cmds | executed | noun | cmds | executed |
|---|---|---|---|---|---|
| `deploy` | 73 | 0 | `var` | 11 | 5 |
| `nixos` | 54 | 12 | `sync` | 11 | 2 |
| `env` | 37 | 15 | `file` | 10 | 5 |
| `ai` | 24 | 8 | `entity` | 10 | 4 |
| `admin` | 23 | 9 | `graph` | 8 | 8 |
| `vcs` | 21 | 7 | `tutorial` | 8 | 7 |
| `storage` | 20 | 6 | `provenance` | 7 | 7 |
| `project` | 19 | 4 | `ast` | 6 | 3 |
| `config-ast` | 15 | 3 | others (27 nouns) | 57 | 32 |
| `domain` | 14 | 7 | | | |

`deploy` — the largest noun at 73 commands — has **zero** executed
coverage, because every leaf is a mutation or needs live infrastructure.
It is also where this session found the exit-code bug that made
successful deploys report failure. That combination is the biggest known
blind spot in the CLI.

## What this suggests

1. **Fix the five root causes.** Three are small (`ts_info`,
   `get_system_status`, `db_utils`); the table drift needs a column
   mapping and a decision about the write paths.
2. **Make `validate` fail loudly.** A check that cannot run should not
   be reported as `PASS`.
3. **A smoke-test suite would have caught all of this.** Every finding
   is reachable by running the command with no arguments and reading
   stderr. 137 commands took minutes to sweep; as a test it would be
   seconds per command and would have caught the `ts_info` regression
   the day it landed.
4. **`deploy` needs a dry-run contract.** 73 commands with no safe
   execution path is why its bugs survive. If every `deploy` leaf
   honoured `--dry-run` as a no-side-effect path, the sweep above would
   extend to it.
