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

`src/cli/help_utils.py` is a *stub* — its own header says so — and has
been in every recorded commit. `CommandHelp` and `CommandExamples`
define only `__init__` and `print`, so neither the method nor the
example data ever existed in this tree. "Repairing" the feature would
have meant authoring example content from scratch, so it was removed
instead.

There were **five** dead attribute references, not three, and the last
two were the serious ones:

| site | reference | reachable when |
|---|---|---|
| `deploy.py` | `CommandExamples.DEPLOY_RUN` | `--examples` |
| `deploy_ops.py` | `CommandExamples.DEPLOY_EXEC` | `--examples` |
| `deploy_script.py` | `CommandExamples.DEPLOY_HOOKS` | `--examples` |
| `deploy.py` | `RelatedCommands.AFTER_DEPLOY_RUN` | **every successful non-dry-run `deploy run`** |
| `deploy_script.py` | `RelatedCommands.AFTER_HOOK_REGISTER` | every successful `deploy hooks register` |

`AFTER_DEPLOY_RUN` ran *after* the deployment had already succeeded. The
enclosing `except Exception` then logged
`Deployment failed: type object 'RelatedCommands' has no attribute
'AFTER_DEPLOY_RUN'` and returned **1** — so a successful deploy reported
failure and exited non-zero, and anything gating on exit status saw
every deploy as broken. The error message was actively false.

All five references and the `--examples` flag removed 2026-10-08;
`--examples` now gets a plain argparse rejection.

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

**EOF handling is per-site, not uniform.** 50 of 53 prompts lack
explicit `EOFError` handling, so under a non-interactive invocation (any
agent tool call) what happens is whatever that call site happens to do —
in most cases an uncaught traceback.

The practical exposure is narrower than 50, because most of those sites
are unreachable without opting in: `commit.py`'s eleven prompts fire only
under `--interactive`, and `checkout.py`'s gc confirmations are skipped
by `--force` or `--dry-run`. The risk is concentrated in prompts
reachable on a default invocation.

The model to copy is `nixos.py:279-295`, which is one of the three sites
that gets this right and does two distinct things:

```python
if assume_yes:                      # --yes short-circuits, says what it skipped
    ...
    return True
try:
    answer = input("Generate now? [Y/n] ").strip().lower()
except (EOFError, KeyboardInterrupt):
    print("\nCancelled: no terminal to prompt on. Pass --yes to "
          f"proceed without generating, or run "
          f"`templedb nixos generate {slug}` first.", file=sys.stderr)
    return False
```

It names the flag that resolves the situation instead of dying with
`Cancelled.` or a traceback. `templedb commit` takes the same stance
from the other direction — its `--strategy` help states that "no-TTY
invocations auto-abort by default".

> Earlier revisions of this document claimed `nixos.py:287` was the
> known-bad case and that `--yes` did not cover it. That was carried over
> from a note written 2026-10-01 and is **wrong** as of this measurement:
> the site handles both `--yes` and `EOFError`. Corrected 2026-10-08
> after reading the enclosing block rather than the single line.

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
2. **Remove `--examples`.** Not repair: `help_utils.py` is a stub in all
   recorded history, so `CommandExamples.DEPLOY_RUN` and friends never
   existed either — "repairing" would mean authoring example content
   from scratch. Four dead attribute references, not three; see below.
3. **Give EOF an explicit answer** at prompts reachable on a default
   invocation, following `nixos.py:279-295`. Not a mechanical sweep of
   all 50 — each needs a decision about what the non-interactive answer
   *should* be.
4. **Resolve `-a`** in the `vcs` group — the `add`/`commit` split is the
   one that silently does the wrong thing.
5. **Emit short aliases** in `admin schema` so collisions are at least
   visible to tooling.
6. **Add `admin checkout-forget <path>`** for the deregister gap.
