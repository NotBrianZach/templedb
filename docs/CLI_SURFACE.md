# CLI surface analysis

Companion to [`INGEST_ADAPTERS.md`](INGEST_ADAPTERS.md). That document
asks what each adapter really reads; this one asks what the CLI really
exposes, and where the exposure fails.

Measured 2026-10-08 from `templedb admin schema` plus the argparse
registrations in `src/cli/`. Counts drift; the findings are structural.

Not to be confused with
[`CLI_DISCOVERABILITY_IMPROVEMENTS.md`](CLI_DISCOVERABILITY_IMPROVEMENTS.md),
which is a 2026-04 implementation record. One of its headline features
has since regressed — see "`--examples` is dead" below.

## Shape

| | |
|---|---|
| commands (incl. subcommands) | **432** |
| parameters | **1153** |
| commands nested 2+ levels | 419 |
| LOC under `src/cli/commands/` | **43,742** |

Largest groups by subcommand count: `deploy` 73, `nixos` 54, `env` 37,
`ai` 24, `admin` 22, `vcs` 21, `storage` 20, `project` 19.

Largest modules: `entity.py` **6597**, `nixos.py` 2721, `vcs.py` 2529,
`var.py` 1450, `file.py` 1158, `commit.py` 1112.

432 commands is the headline risk. Nothing enumerates them for a human,
and the one interface that enumerates them for a machine is broken.

## The agent-facing surface is empty

`templedb admin schema` exists specifically to "Show JSON schema for CLI
commands (for agent/scripting use)". It emits 270 KB of JSON. **422 of
432 commands come back with `help: ""`.**

The help is not missing from the CLI — it is missing from the *schema*.
`vcs add` is registered as
`add_parser('add', help='Stage files for commit')` (`vcs.py:2367`) and
`templedb vcs --help` renders that string fine. But:

```python
# src/cli/commands/schema.py:63
'help': parser.description or '',
```

argparse stores the `help=` passed to `add_parser()` on the **parent's**
`_SubParsersAction._choices_actions`, never on the subparser object. A
subparser's `.description` is populated only if you also pass
`description=`. Ten commands do (the `deploy hooks` family); the other
422 don't, so they serialise as empty.

**Fix** is local: when recursing over subparsers
(`schema.py:73-76`), look up the matching entry in
`action._choices_actions` and carry its `.help` down as a fallback.

Two smaller gaps in the same file:

- **Short aliases are discarded** (`schema.py:24` prefers the first
  `--long` form). A consumer cannot learn that `-p` means `--project`,
  and flag collisions are invisible in the schema.
- **115 of 1153 params have no help at all.** That is genuine absence,
  not an extraction artifact.

This matters more than a normal docs gap: agents are the stated
consumer, and the surface they are pointed at describes nothing.

## `--examples` is dead

`CLI_DISCOVERABILITY_IMPROVEMENTS.md` lists `--examples` as
"Implemented ✅". It raises:

```
$ templedb deploy run --examples
Error: type object 'CommandHelp' has no attribute 'show_examples'
```

`CommandHelp` (`src/cli/help_utils.py:24`) now defines only `__init__`
and `print`. Three call sites still invoke the removed method —
`deploy.py:165`, `deploy_ops.py:434`, `deploy_script.py:168` — so every
`--examples` invocation is an `AttributeError`. Reproduced on both the
dev tree and the deployed nix build, so it is not a staleness artifact.

Only 3 commands ever exposed the flag, against a doc that implies
"major commands".

## Discoverability: semantics that live outside `--help`

The `--session` work on 2026-10-07 fixed one instance of a general
pattern: **behaviour that determines whether your command does anything
at all, documented nowhere in `--help`.** Before the fix, staging was
session-scoped, session identity was steerable only by
`TEMPLEDB_SESSION`/`TEMPLEDB_SESSION_ID`, and neither
`vcs add --help` nor `vcs commit --help` mentioned sessions — so
`No changes staged for commit in this session` was unreachable from the
CLI. You had to read `CLAUDE.md`.

Known remaining members of this class:

| load-bearing fact | discoverable from `--help`? |
|---|---|
| staging is session-scoped | **yes**, since the `--session` flag |
| "modified" means *differs from HEAD*, not from `file_contents` | no |
| `ingest <adapter>` projects DB tables, not the authority ([details](INGEST_ADAPTERS.md)) | no |
| `file set` replaces the whole file; `--verify` won't catch a stale base | partially — `--if-match` exists but nothing says why |
| `templedb edit` returns immediately; `--editor` blocks | yes |

The test for this class: *if a user gets a surprising no-op or a silent
revert, could `--help` alone have told them why?*

## Short-flag collisions

Real, and invisible in `admin schema` because short forms are dropped.

- **`-a` inside the `vcs` group** means `--all` on `vcs add` and
  `vcs reset`, but `--author` on `vcs commit`. `vcs commit` has no
  `--all`, so someone who learned `-a` from `add` silently sets an
  author string instead of getting an error.
- **`-s` carries 3 meanings** CLI-wide: `--session`, `--stage`,
  `--status`.

## Destructive posture

| | count |
|---|---|
| commands offering `--dry-run` | 31 |
| commands offering `--force` | 30 |
| `input()` prompts in CLI modules | **53** |
| of those, wrapped against `EOFError` | **3** |

**The EOF trap.** 50 of 53 prompts are bare `input()`. Under a
non-interactive invocation (any agent tool call) EOF raises, and what
happens next is per-call-site rather than uniform. The known-bad one:

```python
# src/cli/commands/nixos.py:287
answer = input("Generate now? [Y/n] ").strip().lower()
```

`--yes` does **not** cover this prompt — that flag only answers
"activate configuration?". EOF here cancels the whole rebuild. The
working incantation is to pipe the answer:

```bash
echo n | templedb nixos system-switch system_config --yes
```

By contrast `templedb commit` handles no-TTY deliberately: its
`--strategy` help states that "no-TTY invocations auto-abort by
default". That is the pattern the other 50 should follow — decide the
non-interactive answer explicitly rather than inheriting whatever
`EOFError` does.

**Guards added 2026-10-07/08**, both default-on:

- `templedb commit` refuses when ≥50% of tracked files are missing from
  the given workspace (floor 10), overridable with
  `--allow-mass-delete`. Previously a wrong `workspace_dir` committed
  the project away as deletions with no threshold.
- `project checkout --force` refuses a target that strictly encloses any
  registered checkout. Its stray-purge walks recursively and unlinks
  anything not in the project's file list, and the old guard skipped
  same-slug rows — which is the common shape, since edit workspaces live
  at `edit-workspaces/<slug>/<session>/`.

**Still unguarded:** there is no way to deregister a checkout whose
directory still exists. `admin checkout-gc` only removes rows whose
directory is *gone*, so a registered-but-inactive row pointing at a live
directory cannot be retired by any command.

## Ranked recommendations

1. **Fix `schema.py:63`** — carry `help` from the parent's
   `_choices_actions`. One-line class of change; turns the agent-facing
   surface from empty to complete for 422 commands.
2. **Either repair or remove `--examples`.** Three call sites currently
   guarantee an `AttributeError`, and a doc advertises them.
3. **Make non-interactive answers explicit** at the 50 bare `input()`
   sites, starting with `nixos.py:287`. Follow `commit`'s auto-abort
   precedent.
4. **Resolve `-a`** in the `vcs` group — the `add`/`commit` split is the
   one that silently does the wrong thing.
5. **Emit short aliases** in `admin schema` so collisions are at least
   visible to tooling.
6. **Add `admin checkout-forget <path>`** for the deregister gap.
