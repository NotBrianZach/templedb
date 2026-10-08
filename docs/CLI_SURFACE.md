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

## Duplicate names: 15 proper aliases, 19 duplicated handlers

Measured by introspecting the live parser tree, grouping bound methods
by `(__func__, __self__)` — a `grep` over `cli.commands` assignments
cannot do this, because the generic `cmd` variable name is reused in
every module, and `id()` on a bound method is useless since attribute
access creates a fresh object each time. Two earlier estimates in this
document were wrong for exactly those reasons.

```
cli.commands entries                            420
leaf command names                              428
distinct leaf parsers                           413
handlers with >1 dispatch key                    34
  ├─ sharing ONE parser (proper argparse alias)  15   ← correct, keep
  └─ via DISTINCT parsers (duplicate surface)    19   → 25 redundant names
```

**The 15 are fine.** `config list`/`config ls`, `domain remove`/`domain rm`
and friends are registered with `add_parser(..., aliases=['ls'])`, so one
parser answers to both names. Their duplicate `cli.commands` keys are
*required* for dispatch, not redundant.

**The 19 are real duplication**, and almost all `nixos`:

```
nixos config-get       &  nixos config get
nixos dotfiles-add     &  nixos dotfiles add
nixos add-package      &  nixos packages add
nixos system-rollback  &  nixos system rollback
nixos rebuild  &  nixos system-rebuild  &  nixos system rebuild   (3 names)
```

### They cannot become argparse aliases

The two spellings sit at **different subparser depths** — `nixos
config-get` is a child of `nixos`, `nixos config get` is a grandchild
under a `config` group. `aliases=` applies only within a single
subparser, so there is no way to declare them one command. Collapsing
would mean *removing* a spelling.

### …and the decision is already made

**Nested is canonical. Flat is a supported alias, and says so.** All 19
flat spellings already carry it in their help text:

```
$ templedb nixos --help
  system-switch   Switch to system configuration (alias for `nixos system switch`)
  config-get      Get system configuration value (alias for `nixos config get`)
  dotfiles-add    Add dotfile mapping (alias for `nixos dotfiles add`)
```

That matches what the rest of the CLI does, independently measured:

| | |
|---|---|
| leaf commands 3+ tokens deep (nested groups) | **193 of 428** (45%) |
| top-level nouns with sub-groups | **11** — `vcs session`, `deploy hooks`, `admin db`, `domain dns`, `env var tag`, `storage blob`, … |
| leaf tokens containing a hyphen | 66 of 428 (15%) |

Nested noun grouping is the house convention; the flat hyphenated
compound is the minority form. `nixos` already carries all five
sub-groups (`config`, `dotfiles`, `host`, `packages`, `system`), so the
nested structure is load-bearing there and the flat names are a
convenience layer over it.

**So there is nothing to fix, and nothing to break.** The earlier
recommendation to "collapse the redundant names" was wrong three times
over: 15 were already proper aliases, the other 19 cannot be aliased,
and those 19 are already annotated as aliases pointing at the canonical
spelling. Flat forms stay supported — they are shorter, they are what
this project's own history and operational notes use, and removing them
would buy consistency nobody is short of.

**Convention for new commands:** register under the nested group only.
The alias layer exists for commands that predate the groups; growing it
re-creates the ambiguity for no gain.

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
7. ~~**Decide the flat-vs-nested spelling.**~~ **Already decided in the
   code**: nested is canonical, all 19 flat spellings declare
   `(alias for ...)` in their help, and that matches the 45%-nested
   house convention. No change made; flat stays supported. New commands
   go under the nested group only.
8. ~~**Make empty help a doctor invariant.**~~ **Landed 2026-10-08** as
   `cli_help_is_populated`. Verified to catch a stripped `help=` and name
   the offending command. Scoped to commands, not params: the 115
   undocumented params are genuine absence, and failing on them would
   leave the check permanently red.

Items 1-6 and 8 landed 2026-10-08; see
[`reports/2026-10-08-0854`](../reports/2026-10-08-0854-the-cli-as-a-surface-432-commands-and-who-reads-them.html)
for the rollout table and the open questions about surface shape.
