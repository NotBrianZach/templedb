# CLI semantics and strategy, command by command

Third of the CLI trio. [`CLI_SURFACE.md`](CLI_SURFACE.md) maps the
surface's shape; [`CLI_COMMAND_AUDIT.md`](CLI_COMMAND_AUDIT.md) records
what actually runs. This one asks, for every command: **what does it
mean, and should it exist?**

## How to read the tables

**Class** — two letters and an authority.

| | |
|---|---|
| `R` | read |
| `W` | write (mutates TempleDB) |
| `D` | destructive or outward-facing (leaves the machine, or cannot be undone) |
| `·db` | TempleDB is the home of record — an **originator** fact |
| `·git` `·nix` `·fs` `·net` | a foreign authority declares it; TempleDB **observes** |
| `·derive` | projects one TempleDB representation into another |

The `·db` / foreign split is the distinction the whole codebase rests on
(see the README's declared-vs-derived section). It predicts backup
policy: `·db` facts are gone if the DB is lost; the rest re-derive.

**Verdict** — what should happen to the command.

| | |
|---|---|
| **core** | load-bearing; the noun exists for this |
| **keep** | useful and sound |
| **fix** | broken — see the audit |
| **merge** | overlaps another command; consolidate |
| **alias** | declared alias of a canonical spelling |
| **move** | semantically belongs under a different noun |
| **gate** | destructive and lacks a guard it should have |
| **retire?** | no evidence of use; candidate for removal |

## Status of the `fix` verdicts — re-audited 2026-10-27

Most of them are stale. Re-running the commands this document called
broken: `nixos packages list`, `admin cache list`, `sync network
status` and `validate <slug>` all return correct output now, and
`nixos system status` no longer raises. The `ts_info` `NameError` is
gone (the name is assigned before use), and nothing under `src/`
references the `nixos_packages` table any more. Those were fixed
between 2026-10-08 and now without this document being updated, which
is worth stating plainly: **a `fix` verdict here is a claim about
2026-10-08 and must be re-run before it is believed.**

Two were real, and they split in an instructive way:

- `graph overview` — **fixed 2026-10-27.** It had not merely survived,
  it had regressed: 42s when first measured, 88s when re-measured. The
  cause was a four-way `LEFT JOIN` over independent one-to-many tables
  with `COUNT(DISTINCT ...)` papering over the row multiplication.
  Rewritten as scalar subqueries: **53.3s → 0.005s** at the SQL level,
  88s → under 1s for the whole command, byte-identical output.
- `sync status` — still ~31s, exactly as measured. Unchanged on
  purpose: the time is peer probes over the network, not local query
  work, so it is a design question (cache? `--no-probe`?) rather than a
  bug.

Not re-verified, because running them mutates state or reaches other
machines: `nixos packages add` / `remove`, `sync network setup` /
`sync-all`. Their documented defects have no remaining trace in the
source, but that is code reading, not a behavioural check.

---

# `deploy` — 73 commands

## Semantics of the noun

`deploy` is not one noun. It is **at least eight separate products**
sharing a prefix, and nothing in `templedb deploy --help` tells you
which applies to your project:

| sub-domain | cmds | what "deploy" means here |
|---|---|---|
| generic project deploy | 10 | run a project's deploy on this machine, FHS-isolated |
| Nix closure pipeline | 9 | build → transfer → import → activate a closure on a target |
| fleet / network | 11 | orchestrate many machines as a unit |
| hooks | 6 | replace the standard deploy with a project script |
| targets | 7 | CRUD over named deploy destinations |
| migrations | 5 | **database** migrations — see below |
| triggers / notify | 8 | automation and alerting around deploys |
| packaging | 3 | emit Homebrew / Snap / Steam artifacts |
| blue-green | 3 | two-slot traffic swap |

**The strategic problem: four unrelated commands all mean "deploy it."**
`deploy run` (this machine, FHS), `deploye nix run` (closure to a target),
`deploy project` (Cloudflare/Vercel app platforms), and
`deploy fleet deploy` (a whole network). A user with a project in hand
cannot tell from the surface which one is theirs, and choosing wrong is
not a no-op.

**`deploy migration *` is in the wrong noun.** Five commands about
*database* migrations, while `admin db migrate` also exists. Migrations
are a schema concern, not a deployment concern; the only reason they
live here is that they historically ran during deploys.

**`deploy target` vs `deploy targets *`.** Singular "Manage deployment
targets" alongside a plural group with seven subcommands. One of them is
redundant.

**Zero executed test coverage** (audit) — every leaf mutates or needs
live infrastructure. Combined with being the largest noun and the site
of the exit-code bug found this session, this is the CLI's biggest risk
concentration.

## Commands

### Generic project deploy

| command | semantics | class | verdict |
|---|---|---|---|
| `deploy run` | execute the project's deploy on this host, FHS-isolated by default | `D·fs` | **core** |
| `deploy rollback` | revert to the previous recorded deployment | `D·fs` | core |
| `deploy status` | current deployment state for a project | `R·db` | keep |
| `deploy history` | timestamped deploy log with health results | `R·db` | keep |
| `deploy list` | every project that has been deployed | `R·db` | keep |
| `deploy stats` | aggregate deploy counts/outcomes | `R·db` | keep |
| `deploy path` | print the deployed directory, for `cd $(...)` | `R·db` | keep |
| `deploy shell` | interactive shell inside the deploy env | `W·fs` | keep |
| `deploy exec` | run one command inside the deploy env | `W·fs` | keep |
| `deploy health-check` | run the project's health probes | `R·net` | keep |
| `deploy init` | scaffold deployment configuration | `W·db` | merge → `deploy config` |
| `deploy config` | read/write deployment configuration | `W·db` | **core** |

### Nix closure pipeline

Semantically the most coherent sub-group: a linear pipeline, each stage
separately invocable. `deploy nix run` is the whole chain.

| command | semantics | class | verdict |
|---|---|---|---|
| `deploy nix build` | realise the closure locally | `W·nix` | core |
| `deploy nix transfer` | copy the closure to a target | `D·net` | core |
| `deploy nix import` | register the closure in the target's store | `D·nix` | core |
| `deploy nix activate` | start/enable the systemd unit | `D·nix` | core |
| `deploy nix run` | build + transfer + import + activate | `D·nix` | core |
| `deploy nix health` | post-activation probe | `R·net` | keep |
| `deploy nix install` | install the tool into the *local* nix profile | `W·nix` | keep — name collides with `deploy nixos-install`, which does something else |
| `deploy nix generate-flake` | emit a flake for a CLI tool | `W·fs` | keep |
| `deploy nix add-to-config` | emit a NixOS/home-manager snippet | `R·derive` | keep |

### Fleet / network

| command | semantics | class | verdict |
|---|---|---|---|
| `deploy fleet network create` | define a named set of machines | `W·db` | core |
| `deploy fleet network list` / `info` | read network definitions | `R·db` | keep |
| `deploy fleet machine add` / `remove` | membership CRUD | `W·db` | keep |
| `deploy fleet machine list` | read membership | `R·db` | keep |
| `deploy fleet deploy` | deploy to every machine in a network | `D·net` | core |
| `deploy fleet diff` | dry-run: what a fleet deploy would change | `R·net` | **core** — the only safe way to inspect a fleet deploy |
| `deploy fleet status` | per-machine deploy state | `R·net` | keep |
| `deploy fleet check` | health across machines | `R·net` | keep |
| `deploy fleet ssh` | shell into one machine | `W·net` | keep |
| `deploy fleet destroy` | **terminate every machine in the network** | `D·net` | **gate** — the single most destructive command in the CLI; confirm-by-typing-the-name would be proportionate |

### Hooks

Coherent and well-documented — the only sub-group whose help text was
written as prose (which is why its ten commands were the only ones
`admin schema` could serialise before this session's fix).

| command | semantics | class | verdict |
|---|---|---|---|
| `deploy hooks register` | attach a script that replaces standard deploy | `W·db` | core |
| `deploy hooks remove` | detach it | `W·db` | keep |
| `deploy hooks enable` / `disable` | toggle without unregistering | `W·db` | keep |
| `deploy hooks list` / `show` | read registrations | `R·db` | keep |
| `deploy hooks docs` | print the hook's own documentation | `R·db` | keep |

### Targets, triggers, notifications

| command | semantics | class | verdict |
|---|---|---|---|
| `deploy targets add` / `update` / `remove` / `rm` | named-destination CRUD | `W·db` | keep (`rm` = alias) |
| `deploy targets list` / `ls` / `show` | read destinations | `R·db` | keep (`ls` = alias) |
| `deploy target` | singular entry point, "manage targets" | `W·db` | **merge** → `deploy targets` |
| `deploy trigger add` / `remove` / `enable` | auto-deploy rules | `W·db` | keep |
| `deploy trigger list` | read rules | `R·db` | keep |
| `deploy notify add` / `remove` | deploy alerting config | `W·db` | keep |
| `deploy notify list` | read it | `R·db` | keep |
| `deploy notify test` | send a test alert | `D·net` | keep |

### Migrations — misplaced

| command | semantics | class | verdict |
|---|---|---|---|
| `deploy migration list` / `show` / `status` / `history` | read DB migration state | `R·db` | **move** → `admin db` |
| `deploy migration mark-applied` | record a migration as applied **without running it** | `W·db` | **move** + **gate** — this is the "lie to the migrator" button; `admin db stamp` is the same idea and already lives in the right noun |

### Machine provisioning and packaging

| command | semantics | class | verdict |
|---|---|---|---|
| `deploy bootstrap` | install NixOS on this machine from the DB | `D·nix` | core — overlaps top-level `bootstrap` and `new-machine` |
| `deploy hardware-config` | detect and store this machine's hardware config | `W·nix` | keep |
| `deploy nixos-install` | install the project as a NixOS/home-manager package | `D·nix` | keep — confusable with `deploy nix install` |
| `deploy project` | deploy to an app platform (Cloudflare, Vercel) | `D·net` | core — poorly distinguished from `deploy run` |
| `deploy project-config` / `project-history` | app-platform config and log | `R·db`/`W·db` | merge → `deploy config` / `deploy history` with a scope flag |
| `deploy appstore homebrew` / `snap` | emit packaging manifests | `W·fs` | keep |
| `deploy steam` | build and upload to Steam via SteamPipe | `D·net` | **retire?** — one project's concern in a general tool |
| `deploy bg status` / `swap` / `rollback` | blue-green slot control | `R·db`/`D·net` | keep — no evidence of use found |

---

# `nixos` — 54 commands (35 distinct, 19 aliases)

## Semantics of the noun

Four layers, only one of which touches the machine:

1. **Config-as-data CRUD** — `config`, `host`, `dotfiles`, `packages`.
   The DB is the home of record; `.nix` files are *derived*.
2. **Generation** — `generate`, `generate-all`, `edit-template`:
   DB → `.nix` text.
3. **Activation** — `system *`: the only layer that changes the running
   machine.
4. **Project-type administration** — `set-type`, `list-configs`,
   `init-config`, `import-config`.

This is the clearest instance in the CLI of the declared-vs-derived
model: layer 1 declares, layer 2 derives, layer 3 activates. Naming it
that way in `--help` would remove most of the noun's confusion.

**Layer 4 does not belong here.** `nixos set-type` ("Set project type")
and `nixos list-configs` ("List all nixos-config projects") are
*project* operations that duplicate `project set-category` and
`project list`.

**`nixos detect` is literally the same function as `env detect`** —
confirmed same handler, two nouns.

**`nixos export` is the same function as `storage cathedral export`.**

**Two `status` commands with near-identical names and different
referents:** `nixos status` is the *pipeline* (what needs generating or
rebuilding), `nixos system status` is the *machine*. The second is
broken (audit). Renaming the first to `nixos pipeline-status` would cost
nothing and remove a real ambiguity.

## Commands

### Layer 1 — config as data (DB declares)

| command | semantics | class | verdict |
|---|---|---|---|
| `nixos config set` | set a config key, host-scoped by default | `W·db` | **core** |
| `nixos config get` / `list` | read config keys | `R·db` | core |
| `nixos config update-input` | repin a flake input | `W·db` | core — the session memory warns this is a silent no-op when `flake.nix` pins by rev |
| `nixos config-set` / `-get` / `-list` | flat spellings | — | alias |
| `nixos update-input` | flat spelling | — | alias |
| `nixos host set` / `show` / `list` | per-host config overrides | `W·db`/`R·db` | core |
| `nixos host activate` | bind this machine to a host identity | `W·db` | core |
| `nixos host clone` | copy a host's config to a new hostname | `W·db` | keep |
| `nixos host import` | ingest host values from an existing `.nix` | `W·nix` | keep |
| `nixos dotfiles add` / `remove` | dotfile mapping CRUD | `W·db` | keep |
| `nixos dotfiles list` | mappings and their on-disk status | `R·fs` | keep |
| `nixos dotfiles apply` | materialise the symlinks | `D·fs` | keep |
| `nixos dotfiles-*` (4) | flat spellings | — | alias |
| `nixos packages add` / `remove` | managed-package CRUD | `W·db` | **fixed** — no `nixos_packages` reference remains in src/ (code read 2026-10-27; not run, it mutates) |
| `nixos packages list` | read managed packages | `R·db` | **fixed** — returns real output (verified 2026-10-27) |
| `nixos add-package` / `remove-package` / `list-packages` | flat spellings | — | alias (inherit the same breakage) |

### Layer 2 — generation (DB → .nix)

| command | semantics | class | verdict |
|---|---|---|---|
| `nixos generate` | emit NixOS modules from the DB | `W·derive` | core |
| `nixos generate-all` | emit templates + modules + inputs | `W·derive` | **merge** — boundary with `generate` is undocumented; make it `generate --all` |
| `nixos edit-template` | open `.nix.template` sources in `$EDITOR` | `W·fs` | keep — blocks; unsafe from a tool call |
| `nixos import-config` | ingest an existing NixOS config into the DB | `W·nix` | core — the on-ramp |
| `nixos init-config` | scaffold a minimal `system_config` project | `W·db` | keep |

### Layer 3 — activation (changes the machine)

| command | semantics | class | verdict |
|---|---|---|---|
| `nixos system switch` | build + activate + set boot default | `D·nix` | **core** — the only durable path for this project (see README) |
| `nixos system rebuild` | rebuild the system generation | `D·nix` | core |
| `nixos system home-rebuild` | home-manager only — **evicted at next boot** | `D·nix` | keep — the help text should say it is transient |
| `nixos system test` | activate *without* setting boot default | `D·nix` | keep — "test" understates it; this is a live activation |
| `nixos system rollback` | revert to the previous generation | `D·nix` | core |
| `nixos system status` | machine deployment state | `R·nix` | **fixed** — no longer raises (verified 2026-10-27) |
| `nixos system history` | generation log | `R·db` | keep |
| `nixos system-*` (6) | flat spellings | — | alias |
| `nixos rebuild` / `home-rebuild` | flat spellings | — | alias |
| `nixos status` | **pipeline** state, not machine state | `R·db` | keep — **rename**, collides with `system status` |
| `nixos doctor` | diagnose activation failures | `R·nix` | keep |

### Layer 4 — belongs elsewhere

| command | semantics | class | verdict |
|---|---|---|---|
| `nixos set-type` | set a project's type | `W·db` | **move** → `project set-category` |
| `nixos list-configs` | list nixos-config projects | `R·db` | **move** → `project list --type` |
| `nixos detect` | detect dependencies | `R·fs` | **merge** — identical handler to `env detect` |
| `nixos export` | export a Cathedral package with NixOS modules | `W·fs` | **merge** — identical handler to `storage cathedral export` |

---

# `env` — 37 commands

## Semantics of the noun

`env` means **three unrelated things**, and the ambiguity is in the word
itself:

1. **environment** as a Nix dev shell — `enter`, `generate`, `new`,
   `list`, `detect`
2. **environment variables** — `env var *` (9)
3. **secrets and keys** — `env secret *` (7), `env key *` (9)

…plus `env direnv *` (4), which generates `.envrc`.

Architecturally this is the **best-composed noun in the CLI**.
`env.py:571-574` delegates to four independent modules
(`var`, `secret`, `key`, `direnv`) via a `prefix='env'` parameter, and
`var.py` registers the same handlers again at top level. So `env var set`
and `var set` are **one implementation deliberately exposed under two
nouns** — not accidental duplication. Worth knowing before anyone
"fixes" it.

Strategically the dual exposure is still a cost: 20 command names for
~9 variable operations, and no hint in either `--help` that they are the
same thing.

**Dead code found:** `env.py` carries its own `var_set`, `var_get`,
`var_list`, `var_delete`, `var_export` (lines 175–345, ~170 lines) which
are **registered nowhere and called nowhere** — an older implementation
superseded when `var.py` took over, never deleted. Anyone reading
`env.py` to understand `env var set` reads the wrong code.

## Commands

### Nix dev-shell layer

| command | semantics | class | verdict |
|---|---|---|---|
| `env enter` | open a shell in the project's Nix environment | `W·nix` | **core** |
| `env generate` | emit the Nix expression for it | `W·derive` | core |
| `env new` | create an environment definition | `W·db` | keep |
| `env list` / `ls` | read definitions | `R·db` | keep (`ls` = alias) |
| `env detect` | infer dependencies from project contents | `R·fs` | keep — **same handler as `nixos detect`** |

### Variables — shared with the top-level `var` noun

| command | semantics | class | verdict |
|---|---|---|---|
| `env var set` / `var set` | write a variable at project/tag/global scope | `W·db` | **core** |
| `env var get` / `var get` | read with scope resolution (project+target → project → tag → global) | `R·db` | core |
| `env var list` / `ls` | read, annotated by which scope won | `R·db` | core |
| `env var export` / `var export` | merged vars + secrets, for shell consumption | `R·db` | core |
| `env var edit` / `var edit` | open a value in `$EDITOR` | `W·db` | keep — blocks; unsafe from a tool call |
| `env var unset` / `var unset` | delete a variable | `W·db` | keep |
| `env var tag add` / `remove` | tag-group membership | `W·db` | keep |
| `env var tag list` / `ls` | read tags | `R·db` | keep |

Scope resolution is the real semantic content here and it is only
documented in one flag's help string. It deserves a paragraph in
`--help`, being the thing that decides which value you get.

### Secrets

| command | semantics | class | verdict |
|---|---|---|---|
| `env secret set` / `get` | write/read an individually-encrypted secret | `W·db`/`R·db` | **core** |
| `env secret list` | enumerate (all projects if no slug) | `R·db` | core |
| `env secret delete` | remove a secret | `W·db` | keep |
| `env secret export` | emit in various formats | `R·db` | keep — `D` in effect: plaintext leaves the DB |
| `env secret share-key` | grant another project access | `W·db` | keep |
| `env secret migrate` | convert YAML-era secrets to individual rows | `W·db` | **retire?** — a one-time migration, long since run |

### Keys

The most self-consistent sub-group: a key lifecycle with an explicit
quorum step.

| command | semantics | class | verdict |
|---|---|---|---|
| `env key add` | register an encryption key | `W·db` | core |
| `env key list` / `info` | read the registry | `R·db` | core |
| `env key enable` / `disable` | toggle without revoking | `W·db` | keep |
| `env key revoke` | revoke **with multi-key approval**, re-encrypting everything | `D·db` | core — the quorum requirement is the design's best idea |
| `env key show-revoked` | audit trail of revocations | `R·db` | keep |
| `env key setup-yubikey` | generate an age identity on hardware | `W·fs` | keep |
| `env key test` | round-trip encrypt/decrypt check | `R·db` | keep |

### direnv

| command | semantics | class | verdict |
|---|---|---|---|
| `env direnv generate` / `gen` | emit `.envrc` from DB state | `W·derive` | keep (`gen` = alias) |
| `env direnv diff` | `.envrc` on disk vs DB | `R·fs` | **keep** — a derived-copy drift check, the right shape |
| `env direnv verify` | assert they match | `R·fs` | merge → `diff --exit-code` |

---

# `ai` — 24 commands

## Semantics of the noun

The agent runtime, and the one noun where **TempleDB is the sole
authority** for most of what it records: `agent_sessions`, `tool_calls`
and `edit_intents` have no upstream. Losing the DB loses them, unlike
source bytes which git still holds.

Six sub-domains: agent runtime (11), Claude integration (4), prompts
(5), MCP (2), vibe (1), emacs (1).

**Three separate server entry points** — `ai agent serve` (stdio agent
protocol), `ai mcp serve` (stdio MCP), `ai mcp daemon` (HTTP + hook
socket). All three are long-running and none says so in its help, which
matters because invoking one from a tool call hangs it.

| command | semantics | class | verdict |
|---|---|---|---|
| `ai agent serve` | stdio agent-protocol server | `W·db` | **core** — long-running; help should say so |
| `ai mcp serve` | stdio MCP server | `W·db` | core — same |
| `ai mcp daemon` | shared HTTP + hook-socket daemon | `W·db` | core — same |
| `ai agent sessions` | list agent sessions | `R·db` | core |
| `ai agent log` | the agent work log | `R·db` | core — backs `agent_work_log`, whose 5 all-NULL columns doctor flags |
| `ai agent stop-stale` | kill stray `serve` processes, excluding own ancestry | `D·fs` | **keep** — the ancestry exclusion is why this is safe to run from inside an agent |
| `ai agent doctor` | provider health | `R·net` | keep |
| `ai agent chat` | interactive chat, "for testing" | `W·net` | retire? — help admits it is a test harness |
| `ai agent notify list` / `show` | read queued notifications | `R·db` | keep |
| `ai agent notify drain` | send all unsent | `D·net` | keep |
| `ai agent notify decide` | approve/deny a decision-point | `W·db` | **core** — the human-in-the-loop hook for autonomous runs |
| `ai agent notify test` | enqueue + drain, verifying SMTP | `D·net` | keep — exits 1 without SMTP secrets, correctly |
| `ai claude setup` | install the Claude Code integration | `W·fs` | keep |
| `ai claude status` | integration state | `R·fs` | keep |
| `ai claude launch` | launch with project context | `W·fs` | keep |
| `ai claude hook` | handle a hook callback | `W·db` | core — invoked by the harness, not humans |
| `ai prompt create` / `show` / `list` | prompt-template CRUD | `W·db`/`R·db` | keep |
| `ai prompt project-list` | prompts for one project | `R·db` | merge → `prompt list --project` |
| `ai prompt render` | substitute variables into a template | `R·derive` | keep |
| `ai emacs reload` | reload `templedb-agent.el` via emacsclient | `W·fs` | keep — narrow, but the memory notes the nix-store copy is otherwise inert |
| `ai vibe start` | start a "vibe coding session" | `W·db` | **retire?** — a start with no list, show or stop |

---

# `admin` — 23 commands

## Semantics of the noun

Operator surface for the installation itself rather than any project.
The most coherent noun in the CLI: four tight sub-groups (`db`, `cache`,
`gitserver`, checkout maintenance) plus four introspection commands.

**`admin` is where the declared-vs-derived model is operationally
visible**: `checkout-gc`, `checkout-forget` and `lock-checkouts` all
exist to keep derived copies from claiming authority.

**Four bootstrap-shaped commands exist** — `admin bootstrap`,
`deploy bootstrap`, top-level `bootstrap`, and `new-machine`. Nothing
distinguishes them at the surface.

| command | semantics | class | verdict |
|---|---|---|---|
| `admin status` | DB + system state | `R·db` | core |
| `admin which` | which templedb is running and from where | `R·fs` | **core** — the only way to detect the deployed-build-lags-DB condition |
| `admin schema` | JSON command schema for agents | `R·derive` | **core** — was empty for 422 of 433 commands until this session |
| `admin bootstrap` | set up TempleDB on a new machine | `W·fs` | keep — overlaps three other bootstraps |
| `admin db migrate` | apply pending migrations | `W·db` | core |
| `admin db status` | migration state | `R·db` | core |
| `admin db check` | integrity + locks + WAL + processes | `R·db` | **core** — supersedes `integrity` |
| `admin db integrity` | integrity only | `R·db` | **merge** → `db check` |
| `admin db stamp` | mark all migrations applied without running | `W·db` | **gate** — same hazard as `deploy migration mark-applied`, which should move here |
| `admin db repair` | dump/restore to fix corruption | `D·db` | keep |
| `admin cache list` | cached deployments | `R·db` | **fixed** — lists cached deployments (verified 2026-10-27) |
| `admin cache stats` | cache size/hit data | `R·db` | keep |
| `admin cache cleanup` / `clear` | evict old / all entries | `W·db` | merge — two verbs for one idea, differing only by scope |
| `admin checkout-gc` | drop rows whose directory is gone; retire ended-session trees | `W·db` | **core** — deliberately never deletes directories |
| `admin checkout-forget` | deregister a row whose directory still exists | `W·db` | core — added this session to close that exact gap |
| `admin lock-checkouts` | restore read-only on canonical checkouts | `W·fs` | core |
| `admin gitserver start` / `stop` / `status` | the git daemon the flakes fetch from | `W·fs`/`R·fs` | core — `start` is long-running |
| `admin gitserver list-repos` | what it serves | `R·fs` | keep |
| `admin gitserver config get` / `set` | daemon config | `R·db`/`W·db` | keep |

---

# `file` — 10 commands

## Semantics of the noun

The smallest noun and arguably the best-designed. Every command reads or
writes **through the DB**, never the filesystem — which is the whole
point: the DB is the mediated access path, and the filesystem is a
derived copy.

**Three read commands for one operation.** `file show`, `file cat`
("alias for show") and `file get` ("for programmatic use"). `cat` is a
declared alias; `get` differs only in output framing. Two would do.

**`file where` is the architecture's self-inspection tool** and deserves
promotion. It shows every mirror location of a file *with content-hash
drift* — i.e. it answers "which of my derived copies disagree with the
declaration?", the question behind most of this codebase's sharp edges.
It is buried in a 10-command noun and mentioned in no guidance.

| command | semantics | class | verdict |
|---|---|---|---|
| `file set` | replace file content, routed through EditIntent; auto-stages | `W·db` | **core** — replaces the WHOLE file; `--if-match` is the guard, and since 2026-10-27 a moved base is three-way merged rather than refused (`--no-rebase` for strict CAS) |
| `file show` | print current snapshot | `R·db` | core |
| `file cat` | identical to `show` | `R·db` | alias |
| `file get` | content as a string for programmatic use | `R·db` | merge → `show --raw` |
| `file ls` | list a project's files | `R·db` | core |
| `file where` | every mirror of a file, with hash drift | `R·fs` | **core — promote**; the derived-copy drift detector |
| `file edit` | open in `$EDITOR` | `W·db` | keep — blocks; unsafe from a tool call |
| `file checkout` | materialise one file to disk | `W·fs` | keep |
| `file mark` | set `edit_mode` (immutable / hot-reload / live-sync) | `W·db` | keep — the mode is load-bearing and documented only here |
| `file rm` | stage a deletion; hard-delete on commit, history preserved | `W·db` | keep — "hard-delete" wording undersells that history survives |

---

# `entity` — 10 commands

## Semantics of the noun

The knowledge graph itself: `entities` + `relations` + the observation
archive. This noun is where TempleDB stops being a project manager and
becomes a provenance database.

Coherent and well-factored. Three distinct capabilities:

1. **Query** — `search`, `stats`, `explore` (one hop), `trace`
   (multi-hop BFS), `paths` (shortest path between two)
2. **Analysis** — `dead-imports`
3. **Lifecycle** — `forget` (targeted), `prune-orphans` (sweep),
   `observations` / `observations-gc` (bitemporal archive)

**`entity observations` is the most under-advertised command in the
CLI.** It answers "when did this entity's label or `source_authority`
change?" — the audit trail for the graph itself. Nothing in CLAUDE.md or
the README mentions it.

**`prune-orphans` is the required tail of `checkout-gc`.** gc cascades
and leaves File entities with no source row; ingest never deletes, so
only this clears them. That dependency is recorded in session memory and
in gc's own output, but not in either command's help.

| command | semantics | class | verdict |
|---|---|---|---|
| `entity search` | search every label and `external_ref` | `R·db` | **core** |
| `entity stats` | counts by kind | `R·db` | core |
| `entity explore` | one hop out and in from a node | `R·db` | core |
| `entity trace` | recursive BFS, `--depth` / `--via` | `R·db` | **core** — the five-hop provenance query |
| `entity paths` | shortest path between two entities | `R·db` | keep — the graph-theoretic complement to `trace` |
| `entity dead-imports` | files importing another with no Symbol call landing | `R·db` | keep — genuine static analysis, not bookkeeping |
| `entity observations` | archive history of label / authority changes | `R·db` | **keep — promote**; the graph's own audit trail |
| `entity observations-gc` | drop archive rows past a retention cutoff | `D·db` | keep |
| `entity forget` | delete one entity + relations, recording the removal | `D·db` | keep — records its own deletion, which is the right shape |
| `entity prune-orphans` | delete entities whose source row is gone | `D·db` | **core** — dry-run by default; required after `checkout-gc` |

---

# `project` — 19 commands

## Semantics of the noun

The project registry, plus checkout management. Two problems, both
naming.

**Six `checkout-*` commands are flat-hyphenated in a CLI whose
convention is nested groups** (`vcs session`, `deploy hooks`,
`admin db`). `project checkout`, `-cleanup`, `-diff`, `-list`, `-pull`,
`-status` should be `project checkout {cleanup,diff,list,pull,status}`.
This is the inverse of the `nixos` situation: there the nested form
exists and flat is the alias; here only flat exists.

**`project checkout-cleanup` is the same handler as `admin checkout-gc`**
— one function under two nouns, which is why the checkout-deregister gap
went unnoticed: no single noun owns the concept.

**Four on-ramps with undocumented boundaries:** `create` (DB row, no
directory), `init` (adopt the current directory), `import` (from a
filesystem path), `sync` (re-import). Their help text distinguishes them
in a clause each; a user choosing between them has to read all four.

| command | semantics | class | verdict |
|---|---|---|---|
| `project list` / `ls` | the registry | `R·db` | **core** (`ls` = alias) |
| `project show` | one project's detail | `R·db` | core |
| `project create` | register a project with no directory | `W·db` | core |
| `project init` | adopt the current directory | `W·db` | keep |
| `project import` | ingest from a filesystem path | `W·fs` | **core** — the main on-ramp; walks git history |
| `project sync` | re-import from the filesystem | `W·fs` | keep |
| `project rm` | remove from the DB | `D·db` | keep — prompts unless `--force` |
| `project set-category` | category + Nix flags | `W·db` | keep — **destination for `nixos set-type`** |
| `project set-path` | set `repo_url` and register the tree | `W·db` | keep |
| `project validate` | validate the Nix flake | `R·nix` | keep — narrower than top-level `validate` |
| `project generate-envrc` | emit `.envrc` | `W·derive` | **merge** → `env direnv generate` |
| `project commit` | commit a workspace diff into the DB | `W·db` | core — same as top-level `commit` |
| `project checkout` | materialise a project to a directory | `W·fs` | **core** — `--force` runs a recursive stray-purge; guarded this session |
| `project checkout-list` | registered checkouts | `R·db` | keep → nest |
| `project checkout-status` | one checkout's state | `R·fs` | keep → nest |
| `project checkout-diff` | checkout vs DB | `R·fs` | **keep → nest** — another derived-copy drift check |
| `project checkout-pull` | refresh a checkout from the DB | `W·fs` | keep → nest |
| `project checkout-cleanup` | remove stale checkouts | `W·db` | **merge** → `admin checkout-gc` (same handler) |

---

# `storage` — 20 commands

## Semantics of the noun

Everything about bytes at rest: backups (10), blob storage (6), and the
portable Cathedral package format (4).

**The backup sub-group has an abstraction leak.** `storage backup cloud *`
is provider-generic (`init`, `providers`, `push`, `pull`, `status`,
`test`, `cleanup`) — and then `storage backup gcs` sits beside it as a
single hard-coded provider. Either GCS is a `cloud` provider or the
abstraction is not doing its job.

**The blob sub-group is the best destructive-command design in the CLI.**
`blob gc` is dry-run by default, and `blob deletions` is a standing audit
trail of what it collected. That pairing — a destructive sweep plus a
record of what it swept — is the pattern the rest of the CLI's `gc`
commands should copy.

Context from doctor: blob orphans are within budget now, but a prior
assessment found 54% of the database file was unreachable blob garbage
with no collector. `blob gc` is the answer to that, and it is recent.

| command | semantics | class | verdict |
|---|---|---|---|
| `storage backup local` | local DB snapshot | `W·fs` | **core** |
| `storage backup restore` | restore from a local backup | `D·db` | **core** — the most consequential restore path; no `--dry-run` |
| `storage backup gcs` | upload to GCS using DB credentials | `D·net` | **merge** → `backup cloud push --provider gcs` |
| `storage backup cloud init` | configure a provider | `W·db` | keep |
| `storage backup cloud providers` | what is supported | `R·db` | keep |
| `storage backup cloud push` / `pull` | upload / download | `D·net` | core |
| `storage backup cloud status` | list remote backups | `R·net` | keep |
| `storage backup cloud test` | connectivity check | `R·net` | keep |
| `storage backup cloud cleanup` | retention sweep | `D·net` | keep |
| `storage blob status` | blob storage statistics | `R·db` | core |
| `storage blob list` | large blobs | `R·db` | keep |
| `storage blob gc` | delete unreferenced blobs, **dry-run by default** | `D·db` | **core — the model to copy** |
| `storage blob deletions` | what gc has collected | `R·db` | **keep — the model to copy** |
| `storage blob verify` | integrity check | `R·db` | keep |
| `storage blob migrate` | move blobs between tiers | `W·db` | keep |
| `storage cathedral export` | project → `.cathedral` package | `W·fs` | core — **same handler as `nixos export`** |
| `storage cathedral import` | package → project | `W·db` | core |
| `storage cathedral inspect` | read a package without importing | `R·fs` | **keep** — inspect-before-apply, the right shape |
| `storage cathedral verify` | package integrity | `R·fs` | keep |

---

# `config-ast` (15) + `ast` (6) — two generations of one idea

## The strategic finding

**Two config models exist. Only one is alive. The CLI presents both as
current.**

| | `nixos config *` | `config-ast *` + `ast *` |
|---|---|---|
| model | flat key → value, host-scoped | typed AST nodes in `config_nodes` |
| rows | 208 | 1254 |
| **last write** | **2026-10-04** | **2026-08-05** |
| generate | `nixos generate` / `generate-all` | `config-ast generate` → `ast build` |
| hosts | `nixos host *` (6 cmds) | `config-ast host add` / `list` (5 rows) |
| builds promoted | n/a | **2 of 27**, last 2026-08-04 |
| **status** | **production** | **abandoned migration** |

Measured 2026-10-08. `nixos status` — the live pipeline command — reads
`system_config`, reports `Last rebuild: 2026-10-08`, `Live system: UP TO
DATE`, and tracks pending key changes. `config_nodes` and `ast_builds`
have not been written since early August, and only 2 of 27 AST builds
were ever promoted.

**So `nixos config` is authoritative and `config-ast`/`ast` is a
migration that was started and never finished.**

> **Correction.** The first revision of this document claimed the
> opposite — that `config-ast` was the successor and `nixos config` the
> legacy model — reasoning from the existence of **`config-ast seed`**
> ("Seed config_nodes from existing system_config keys"). That inference
> was wrong. `seed` is the bridge that was *built*, not evidence the
> migration *completed*; the row timestamps show it did not. Published
> before checking, which would have led a reader to deprecate the live
> system. Corrected after measuring write recency on both tables.

The real cost is not two live models — it is **21 commands presented as
current that write to a dormant store**. A user who follows
`config-ast set` will successfully edit `config_nodes` and see no effect
on their machine, because nothing generates from it any more. That is
worse than a missing feature: it is a surface that silently does
nothing.

`ast` is internally clean — content-addressed builds, `ast diff` before
`ast promote` — which makes it a good design that lost its upstream.

**Resolution applied:** `config-ast` and `ast` now say
`INCOMPLETE MIGRATION` in their group help and name the live path.

## Why the migration cannot be completed as conceived

Investigated 2026-10-08 by attempting it. The answer is a precise
instance of this codebase's central failure mode.

**What actually happened:**

| | |
|---|---|
| 2026-08-02, 08-04 | two AST builds **promoted** into the live checkout |
| hence | `configuration.nix:2` reads `# Generated by TempleDB configuration compiler` |
| since 08-04 | **162 lines hand-added to that generated file** |
| `config_nodes` | never updated — last write 2026-08-05 |

So a **derived file became the place where declarations were made.**
The generator cannot be re-run because doing so destroys authored work.
`ast build --host zMothership2` reproduces August's hash
`330c53e69c4e` byte-for-byte and still passes `nix build`; `ast diff`
against live is **687 lines across all three files**. Promoting it would
delete 316 lines of live config.

**The 162 hand-added lines break down as:**

| | lines |
|---|---|
| comments carrying engineering rationale | **86** |
| actual configuration | 76 |

**The only real blocker — comments.** The emitter knows 20 node types
(`AttrSet`, `FnCall`, `With`, `LetIn`, `MultilineString`,
`Interpolation`, …) and **none is a comment**; there is no comment
emission anywhere in `config_compiler.py`, and
`config_nodes.description` is populated on **0 of 1254 rows**. So 86
lines of rationale — including a 20-line explanation of why Magic SysRq
is set to 1 rather than 244 — are dropped.

But *capture* is nearly free: the parser is tree-sitter-based,
tree-sitter already emits `comment` nodes, and `nix_ast_parser.py`
**deliberately discards them** at `:197`, `:351`, `:375`
(`pass  # skip comments`) and `:581`. The expensive part is anchoring —
one field per node cannot express a block explaining a group of
settings, paragraph breaks, trailing inline comments, or a file header.

### Measured: the structure round-trips at 98.8%

An in-memory round trip of the live 593-line `configuration.nix`
(parse → `ConfigNode` → `emit_nix`, no DB writes):

| | |
|---|---|
| nodes parsed | **451** |
| `RawNix` fallbacks (unparsed fragments) | **0** |
| line similarity vs comment-stripped original | **98.8%** |

Both remaining differences are semantically neutral: lambda headers
joined onto one line, and `kernel.sysctl."kernel.sysrq" = 1;` expanded
into nested attrsets — which in Nix is the same thing written
differently.

That includes `voiceAIEnvRenderer`, the 15-line shell script embedded
via `pkgs.writeShellScript`, which parses into `MultilineString` +
`Interpolation` + `FnCall` with no fallback. An earlier revision called
it a second blocker; it is not one for *representation*. It remains an
argument about where it is pleasant to *edit*.

**So the 687-line diff measured the wrong thing** — live against the
*August* AST state, not against what a fresh import would produce.

**Re-seeding still does not help**, for the same reason as before:
`seed` only reads `nixos.*` keys, and `kernel.sysrq`, `lib.mkDefault`
and `brightnessctl` are keys in neither model. The path is
`config-ast import`, not `seed`.

**Re-seeding does not help.** `config-ast seed --dry-run` would rewrite
all 158 `nixos.*` keys and close **none** of the gap: `kernel.sysrq`,
`lib.mkDefault`, `brightnessctl` are keys in neither model. The
hand-edits exist only in the derived file.

`AST_MERGE_SEMANTICS.md` does not cover this either — it specifies
merging *multiple AST inputs* by host-chain priority, not merging AST
output into an edited file.

## The three ways forward

1. **Capture comments, then re-import.** Stop discarding `comment`
   nodes at the four parser sites, add a `Comment` node type carrying an
   anchor, then `config-ast import --replace` the live file over the
   stale August nodes. The structure already works.
2. **Draw a scope boundary** — the AST owns structured settings,
   authored Nix stays in files, and `generate` *merges* rather than
   replaces. A design project, and the merge it needs does not exist.
3. **Retire the AST path.** Honest if nobody will do 1 or 2.

**Recommendation: (1)** — reversing what this document first said. With
the structure round-tripping at 98.8% and zero unparsed fragments,
comments are the single gap and tree-sitter already hands them over.
Option 1 is a bounded change to one parser and one emitter; option 2 is
open-ended.

This also dissolves the "hostile authorship" objection the first
revision raised: **if import round-trips, authorship never moves into
the database.** You keep editing `configuration.nix` as Nix, re-import,
and the AST mirrors it — a lossless index over the file rather than a
replacement for it. The hostility was a property of a DB-as-author
implementation, not of the migration.

The residual judgement call is formatting: the emitter normalises
(joining lambda headers, expanding dotted paths), so a round trip is
semantically faithful but not byte-identical. Either it learns to
preserve those choices, or the project accepts canonical formatting for
generated output — a smaller question than it looks, and `nixfmt`
already implies an answer.

Whichever is chosen, **the invariant worth adding first** is one that
would have caught this in August: *a generated file must not diverge
from what its generator produces.* That is the same shape as
`checkout_matches_db`, applied to `config-ast`.

## `config-ast` commands

| command | semantics | class | verdict |
|---|---|---|---|
| `config-ast import` | parse a `.nix` file into `config_nodes` | `W·nix` | core |
| `config-ast import-all` | import `configuration.nix` + `home.nix` + `flake.nix` | `W·nix` | core |
| `config-ast seed` | populate nodes from old-style `system_config` keys | `W·derive` | keep — the migration bridge, built but never crossed |
| `config-ast set` / `unset` | write / remove a node | `W·db` | core |
| `config-ast enable` / `disable` | toggle a node without removing it | `W·db` | keep |
| `config-ast query` | query nodes | `R·db` | core |
| `config-ast tree` | print the config tree | `R·db` | keep |
| `config-ast stats` | tree statistics | `R·db` | keep |
| `config-ast owners` | which projects own a config path | `R·db` | **keep** — ownership is the hard problem in merged config |
| `config-ast orphans` | nodes with no owning project | `R·db` | **keep** — the drift detector for this model |
| `config-ast generate` | emit `.nix` from the AST | `W·derive` | core — **overlaps `nixos generate`** |
| `config-ast host add` / `list` | host registry | `W·db`/`R·db` | **merge** → `nixos host` (or vice versa; pick one) |

## `ast` commands

| command | semantics | class | verdict |
|---|---|---|---|
| `ast build` | AST → `.nix`, hashed, into a content-addressed build dir | `W·derive` | **core** |
| `ast list` | past builds | `R·db` | keep |
| `ast show` | manifest + file list for a build | `R·db` | keep |
| `ast diff` | two builds, or a build against the live checkout | `R·fs` | **core** — inspect before promote |
| `ast promote` | write a build's files into the live `system_config` checkout | `D·fs` | core |
| `ast deploy` | promote + `nixos-rebuild switch` locally | `D·nix` | keep — **overlaps `nixos system switch`** |

---

# `provenance` — 7 commands

## Semantics of the noun

Thin, named wrappers over `entity trace`. The best-documented noun in
the CLI: the help text carries **workflow letters** (A, B, F) that tie
each command back to the design report that motivated it. That is
provenance about provenance, and it is the right instinct.

Every command exits non-zero when handed a wrong-type argument, which
the audit confirmed is correct behaviour rather than breakage.

| command | semantics | class | verdict |
|---|---|---|---|
| `provenance machine` | Workflow B — what did this machine run, and why | `R·db` | **core** — the five-hop query the whole graph exists for |
| `provenance deployment` | from a deployment to its target + commit | `R·db` | core |
| `provenance commit` | reverse walk: what led to, and uses, this commit | `R·db` | core |
| `provenance intent` | Workflow A — what did this intent apply to | `R·db` | core |
| `provenance report` | Workflow F — which commits did this report motivate | `R·db` | **core** — closes the design-decision loop |
| `provenance callers` | who calls this Python Symbol | `R·db` | **merge** — overlaps `graph callers` |
| `provenance callees` | what does this Symbol call | `R·db` | keep — no `graph` equivalent |

---

# `graph` — 8 commands

## Semantics of the noun

Code structure and content search. The noun that most needed its help
text fixed, and now has it: `graph search`'s help says
**"NOT file contents — use who-uses"** inline, which is exactly the
distinction that made existing code look absent.

| command | semantics | class | verdict |
|---|---|---|---|
| `graph who-uses` | substring scan of file contents | `R·db` | **core** — no tokenisation, so the right tool for underscores and punctuation |
| `graph search` | fuzzy search over names / paths / commit messages | `R·db` | core — help correctly disclaims content search |
| `graph callers` | what calls a symbol | `R·db` | core |
| `graph importers` | what imports a file | `R·db` | core |
| `graph build-deps` | **build** the file dependency graph | `W·db` | keep — a write dressed as a query; name suggests reading |
| `graph deps` | read the project dependency graph | `R·db` | keep |
| `graph overview` | cross-project analysis | `R·db` | **fixed 2026-10-27** — was 42s, had regressed to 88s; four-way join replaced by scalar subqueries, 53.3s → 0.005s, identical output |
| `graph changes` | what changed since last deploy | `R·db` | **move** → `deploy diff` / `deploy status`; it is a deploy question |

---

# `domain` — 14 commands (9 distinct, 5 aliases)

## Semantics of the noun

DNS and domain registration for deployed projects. Small, coherent, no
overlaps with other nouns — the cleanest noun in the CLI after `file`.

Three layers, properly nested: domains, their DNS records, and the
provider credentials used to apply them.

| command | semantics | class | verdict |
|---|---|---|---|
| `domain register` | attach a domain to a project | `W·db` | core |
| `domain list` / `ls` | registered domains | `R·db` | core (`ls` = alias) |
| `domain update` | change domain configuration | `W·db` | keep |
| `domain remove` / `rm` | detach a domain | `W·db` | keep (`rm` = alias) |
| `domain dns configure` | define records for a deploy target | `W·db` | core |
| `domain dns list` / `ls` | read records | `R·db` | keep (`ls` = alias) |
| `domain dns apply` | push records via the provider API | `D·net` | **core** — the only outward-facing command here |
| `domain dns verify` | confirm live DNS matches intent | `R·net` | **keep** — declared-vs-observed check, correctly separated from `apply` |
| `domain provider add` | store provider credentials | `W·db` | core |
| `domain provider list` / `ls` | configured providers | `R·db` | keep (`ls` = alias) |

---

# `sync` — 11 commands

## Semantics of the noun

CRDT replication between machines over Tailscale. **The least healthy
noun in the CLI**: 3 of its 11 commands are broken, one takes 31s, and
two layers overlap.

**Two statuses showing the same thing.** `sync status` ("sync status and
peers", 31s) and `sync network status` ("network and peer status",
broken). Also `sync peers` ("discover Tailscale peers running
TempleDB"). Three commands answering "who can I sync with."

**Two sync-everything verbs.** `sync sync` ("full bidirectional sync
with peer") and `sync network sync-all` ("sync with all online peers",
broken). `sync sync` is also an unfortunate name — the noun repeated as
its own verb.

The `network` sub-group is a Tailscale wrapper whose three broken
commands all share one undefined name (`ts_info`), so the sub-group has
likely never worked in this form.

| command | semantics | class | verdict |
|---|---|---|---|
| `sync init` | enable cr-sqlite CRDT on the database | `W·db` | **core** — without it every graph write raises |
| `sync serve` | run the sync server | `W·net` | core — long-running |
| `sync push` / `pull` | one-directional sync with a peer | `D·net` | core |
| `sync sync` | full bidirectional sync | `D·net` | keep — **rename**; `sync with` or `sync peer` |
| `sync status` | sync state and peers | `R·net` | **fix (perf)** — still ~31s (re-measured 2026-10-27); the time is network peer probes, not local query work |
| `sync peers` | discover Tailscale peers running TempleDB | `R·net` | merge → `sync status` |
| `sync network connect` | connect to Tailscale | `W·net` | keep — the only `network` command that works |
| `sync network status` | network + peer status | `R·net` | **fixed** — real output (verified 2026-10-27) |
| `sync network setup` | install and configure Tailscale | `D·fs` | **fixed** — `ts_info` is assigned before use (code read 2026-10-27; not run, it reaches other machines) |
| `sync network sync-all` | sync with all online peers | `D·net` | **fixed** — `ts_info` is assigned before use (code read 2026-10-27; not run, it syncs to peers) |

---

# `vcs` — 21 commands

## Semantics of the noun

TempleDB's own commit log. The critical semantic fact, and the one the
name hides: **this is not git.** `vcs_commits` rows carry messages,
authors, session ownership and metadata that **never reach git** —
publishing squashes N of them into one `TempleDB materialize (N files)`
commit. Commit messages here are `·db` facts: no upstream holds them.

See the schema discussion in session notes for why `vcs_commits` is
arguably the wrong name and holds two identity regimes (observed git
commits vs native change events) in one table.

**"Modified" means differs from HEAD, not from `file_contents`.** Two
derived views that can disagree, documented in CLAUDE.md because no
`--help` string says it.

**Staging is session-scoped** — the defect that opened this session.
`--session <id|name>` now exists on the four session-scoped commands.

| command | semantics | class | verdict |
|---|---|---|---|
| `vcs status` | working state vs HEAD, with a session badge | `R·db` | **core** |
| `vcs add` | stage files **into the current session** | `W·db` | core |
| `vcs reset` | unstage | `W·db` | keep |
| `vcs commit` | commit this session's staged rows | `W·db` | core |
| `vcs log` | commit history, session-aware | `R·db` | core |
| `vcs show` | one commit, with diff against parent | `R·db` | keep |
| `vcs diff` | diff between file versions | `R·db` | keep |
| `vcs branch` | list / create / delete branches | `W·db` | keep — three verbs in one command |
| `vcs switch` | change active branch | `W·db` | keep |
| `vcs merge` | merge a branch | `W·db` | keep |
| `vcs edit` | make a checkout writable | `W·fs` | **merge** → top-level `edit`, which is the documented path |
| `vcs discard` | drop changes, return to read-only | `D·fs` | keep |
| `vcs export` | export DB commits **to git** | `W·git` | **keep — promote**; the only command that bridges the two logs |
| `vcs import-history` | import full git history into `vcs_commits` | `W·git` | **core** — the layer-1 observation step `ingest git` does *not* perform |
| `vcs session start` | open a named session | `W·db` | **core** — must precede `templedb edit` to own the tree |
| `vcs session current` | the resolved session | `R·db` | core |
| `vcs session list` / `show` | enumerate / detail | `R·db` | keep |
| `vcs session end` | close a session | `W·db` | keep — the safe gc gate |
| `vcs session gc` | reap per each session's `reap_policy` | `D·db` | keep |
| `vcs session prune` | delete old ended sessions with no staged rows | `D·db` | keep |

---

# Remaining nouns

## `intent` — 5 commands

The EditIntent layer: propose, then apply. **The only noun that models a
write as a two-phase proposal**, which is what makes agent edits
auditable. `·db` facts throughout — no upstream authority holds intents.

| command | semantics | class | verdict |
|---|---|---|---|
| `intent create` | propose an edit **without applying it** | `W·db` | **core** |
| `intent apply` | apply a proposed intent, rebasing it onto current content if the file moved since it was proposed (exit 4 on a real conflict, leaving it `proposed`) | `W·db` | core |
| `intent cancel` | abandon a proposal | `W·db` | keep |
| `intent list` | outstanding intents by default | `R·db` | core |
| `intent show` | one intent in full | `R·db` | keep |

## `nix` — 9 commands

Missing from the first pass of this document, and not because it was
overlooked: `nix_store.py` carried a complete `register()` that
`cli/__init__.py` never called, so the group was unreachable from
`--help` and from `admin schema`, which are what the CLI trio measures.
Wired in 2026-10-27. Not to be confused with `nixos` (54 commands),
which builds and switches systems; this group indexes the store.

| command | semantics | class | verdict |
|---|---|---|---|
| `nix scan` | index store paths from the live system closure, then record every `/nix/var/nix/profiles/system-*-link` as a generation | `W·nix` | **core** — and load-bearing in a way the name hides: `scan_generations` is the only backfill for `nix_generations`, so while this was unreachable a generation created by a direct `nixos-rebuild` could never be recorded at all |
| `nix generations` | tracked generations with their VCS commit links | `R·db` | core — the read side of `provenance machine` |
| `nix closure` | closure detail for a store path or generation, with diffs | `R·db` | keep |
| `nix who-uses` | which projects depend on a **package** | `R·db` | keep — but **rename**: `graph who-uses` searches file contents and `entity search` the symbol graph, so three commands share one verb over three different nouns |
| `nix gc-roots` | what is keeping store paths alive | `R·nix` | keep |
| `nix stats` | store totals | `R·db` | keep |
| `nix mark-invalid` | flag store paths that have been GC'd away | `W·db` | keep — reconciles observations against a store that moved under them |
| `nix cache prepare` | stage a closure for binary-cache serving | `W·fs` | keep |
| `nix cache stats` | binary cache counters | `R·db` | keep |

The generations half of `scan` is worth separating from the store-path
half eventually. They have different costs (2,515 paths vs 4 profile
links) and different reasons to run, and today you cannot ask for the
cheap one alone.

## `source` — 2 commands

The snapshot-vs-truth vocabulary made executable. Small and exactly
right.

| command | semantics | class | verdict |
|---|---|---|---|
| `source snapshot` | file content at a revision; `--meta` gives hash + `observed_at` | `R·db` | **core** — the `--if-match` base |
| `source revisions` | every known revision of a file | `R·db` | core |

## `search` — 5 commands

| command | semantics | class | verdict |
|---|---|---|---|
| `search content` | FTS5 over file contents | `R·db` | **core** |
| `search files` | filename search | `R·db` | keep |
| `search reindex` | rebuild the FTS index | `W·db` | **core** — the fix when results look impossibly thin |
| `search query` | natural-language file query | `R·net` | keep |
| `search query-open` | query and open the results | `W·fs` | merge → `query --open` |

## `doctor` / `hygiene` / `reconcile` / `claims` / `report` / `tool` — the assurance layer

Six small nouns that together form TempleDB's self-knowledge. Strategic
note: they are **six nouns for one concern** and a user looking for
"is my data sound?" has no single entry point other than `summary`.

| command | semantics | class | verdict |
|---|---|---|---|
| `doctor entities` | run commuting-diagram invariants, persisted | `R·db` | **core** |
| `doctor history` | invariant results over time — drift, not just state | `R·db` | **core** |
| `reconcile machine` | SSH-probe a machine and diff against the DB | `R·net` | **core** — the only network-active truth check |
| `reconcile history` | past reconcile runs | `R·db` | keep |
| `reconcile schedule` | install/uninstall the daily timer | `W·fs` | keep |
| `hygiene snapshot` | record per-slug dead-import counts now | `W·db` | keep |
| `hygiene history` | recent snapshots | `R·db` | keep |
| `hygiene diff` | newest vs oldest in a rolling window | `R·db` | keep — trend, not state |
| `claims list` | coverage table for a project | `R·db` | keep — propositions carrying their revision |
| `claims show` | one claim: scope, warrant, evidence | `R·db` | keep |
| `report links` | Report ↔ Commit links | `R·db` | keep |
| `report link` | manually assert a link (confidence=confirmed) | `W·db` | keep |
| `report confirm` | promote an auto-detected link | `W·db` | **keep** — human-in-the-loop over inference |
| `report reject` | mark auto-detection wrong | `W·db` | **keep** — recording the negative is unusual and correct |
| `tool list` | recent tool invocations | `R·db` | keep |
| `tool stats` | aggregates | `R·db` | keep |

## `publish` — 5 commands

| command | semantics | class | verdict |
|---|---|---|---|
| `publish run` | commit + materialize + push to every mirror | `D·net` | **core** — refuses to push if the commit step failed, which is right |
| `publish build` | nix-build from the git daemon or checkout | `W·nix` | keep |
| `publish mirror-add` / `-remove` | mirror CRUD | `W·db` | keep — flat-hyphenated against the nested convention |
| `publish mirror-list` | read mirrors | `R·db` | keep — same |

## `reports` — 5 commands

| command | semantics | class | verdict |
|---|---|---|---|
| `reports list` | reports newest-first | `R·db` | keep |
| `reports new` | scaffold from the template | `W·db` | keep |
| `reports reindex` | rebuild `index.html` | `W·db` | keep — shells out to `file set`; now forwards `--session` |
| `reports regenerate-index` | identical | — | alias |
| `reports view` | extract and open in a browser | `W·fs` | keep |

## `handoff` — 5 commands

Cross-session messaging. `·db` throughout, and the only noun modelling
agent-to-agent communication.

| command | semantics | class | verdict |
|---|---|---|---|
| `handoff send` | leave a note for a topic or broadcast | `W·db` | core |
| `handoff list` | notes, filterable by unread | `R·db` | core |
| `handoff show` | read one, marking `read_at` | `W·db` | keep |
| `handoff ack` | acknowledge with an optional note | `W·db` | keep |
| `handoff pop` | show + ack the oldest unacked, atomically | `W·db` | **keep** — the one-call ergonomic for an agent |

## `config` — 5 commands

Dotfile-style config **linking**, distinct from `nixos config` (system
values) and `config-ast` (the AST model). **Three nouns beginning
"config" with three different referents** is the CLI's worst naming
collision.

| command | semantics | class | verdict |
|---|---|---|---|
| `config link` | link a project's config files | `W·fs` | keep — **rename the noun**; `config-link` or fold into `nixos dotfiles` |
| `config unlink` | remove links | `W·fs` | keep |
| `config list` / `ls` | read links | `R·db` | keep (`ls` = alias) |
| `config verify` | check link status | `R·fs` | keep |

## `tutorial` — 8 commands

| command | semantics | class | verdict |
|---|---|---|---|
| `tutorial list` | available tutorials | `R·db` | keep |
| `tutorial run` | run one | `R·db` | keep |
| `tutorial basics` / `quickstart` / `checkout` / `deployment` / `mcp` / `advanced` | six topic shortcuts, all on one dispatcher | `R·db` | **merge** → `tutorial run <topic>`; six names for one handler |

## `var` — 11 commands

Covered under [`env`](#env--37-commands): `var *` and `env var *` are the
same handlers registered twice from `var.py` via a `prefix` parameter.
Deliberate dual exposure, one implementation.

## Singletons — 14 commands

| command | semantics | class | verdict |
|---|---|---|---|
| `summary` | health at a glance: ingest, doctor, reconcile, handoff | `R·db` | **core** — the authoritative orientation command, and the right entry point to the assurance layer |
| `status` | database status | `R·db` | merge → `summary` / `admin status` |
| `edit` | provision a writable workspace; `--editor` opens it | `W·fs` | **core** — returns immediately by default, which is what agents need |
| `commit` | workspace diff → DB commit | `W·db` | **core** (alias of `project commit`) |
| `ingest` | project an authority into the entity graph | `W·derive` | **core** — mostly layer-2 projection, not re-observation |
| `validate` | run all validators (env, nixos, deploy) | `R·db` | **fixed** — reports per-check status and a real verdict (verified 2026-10-27) |
| `gui` | launch the web GUI | `W·net` | keep — long-running; help does not say so |
| `dev` | local dev server with the TempleDB environment | `W·fs` | keep |
| `build` | nix build | `W·nix` | alias of `deploy nix build` |
| `push` | publish to mirrors | `D·net` | alias of `publish run --force` — **`--force` hidden inside an alias is a trap** |
| `reload` | publish + relock + rebuild + migrate | `D·nix` | keep — **home-rebuild only, so its effect is evicted at next boot**; the help does not say so |
| `bootstrap` | set up TempleDB on a new machine | `W·fs` | keep — one of four bootstraps |
| `new-machine` | **(Deprecated)** use `bootstrap` | — | **retire** — already self-labelled |
| `merge from-git` | merge from an external git repo | `W·git` | keep |

---

# Cross-cutting strategy

Ranked by what they cost a user.

### 1. 21 commands write to a dormant store

`config-ast *` (15) and `ast *` (6) operate on `config_nodes`, last
written **2026-08-05**, from which nothing now generates — while
`nixos config *` (production, last written 2026-10-04) is what
`nixos status` and the rebuild path actually read. `config-ast set`
succeeds, changes `config_nodes`, and has no effect on the machine.

A surface that silently does nothing is worse than a missing one.
**Mark `config-ast` and `ast` as an incomplete migration in their group
help.** Do not delete: 1254 nodes and a working content-addressed build
pipeline are real work, and finishing the migration may still be right.
The ask is only that the CLI stop implying it is the current path.

### 2. `deploy` is eight products in one noun

Four commands mean "deploy the thing" (`run`, `nix run`, `project`,
`fleet deploy`) with no way to tell which is yours. `deploy migration *`
is a schema concern misfiled under deployment. 73 commands, **zero
executed test coverage**, and the site of this session's exit-code bug.

### 3. Three nouns called "config"

`config` (file links), `nixos config` (system values), `config-ast`
(AST nodes). Three referents, one word.

### 4. The concept with no owning noun

`checkout` operations live under `project` (6), `admin` (3), and as
top-level `edit`. That is why the deregister gap survived: no single
`--help` listing could show the hole. The same is true of `history`
(`deploy`, `nixos system`, `vcs log`, `reconcile`, `hygiene`,
`doctor`) and `status` (at least eight).

### 5. Under-advertised commands that answer real questions

- `file where` — which derived copies disagree with the declaration
- `entity observations` — the graph's own audit trail
- `vcs export` — the only bridge from the DB log to git
- `ast diff` / `storage cathedral inspect` / `deploy fleet diff` —
  inspect-before-apply, the pattern the destructive commands need more of

### 6. The best patterns, worth copying

- **`storage blob gc`** — dry-run by default, paired with
  `blob deletions` as a standing record of what it collected
- **`env key revoke`** — multi-key quorum on an irreversible act
- **`intent create` / `apply`** — two-phase writes
- **`report confirm` / `reject`** — human adjudication of inference,
  with the negative recorded
- **`provenance`** — help text citing the design workflow it implements

---

# Gate verdicts — resolved 2026-10-27

`deploy fleet destroy` — **stale.** This document calls it "the single
most destructive command in the CLI". It cannot destroy anything: fleet
deployment was retired in migration 130 and the verb now prints an
explanation and exits. `templedb deploy fleet destroy <proj> <net>`
returns the retirement notice. No gate needed on a command that refuses.

`admin db stamp` — **real, gated 2026-10-27.** It had no guard of any
kind. It writes `schema_version` rows for migrations it does not run, so
afterwards `admin db status` reports them applied and `migrate` will
never pick them up — the skipped schema changes become invisible. Now:
lists what it would stamp, requires the database *filename* typed back
(not y/N, which a reflex can supply), takes `--dry-run` to preview, and
`--yes` for bootstrap automation. Refuses on EOF, so an unattended
caller that forgets `--yes` aborts rather than proceeding.

The typed-confirmation helper is `confirm_by_typing` in
`cli/error_handling_utils.py`, next to the existing `confirm_action`.

---

# Executing the plan — batch A, 2026-10-27

Six commands removed outright (463 → 456): `deploy steam`,
`env secret migrate` (and its `secret migrate` twin),
`ai agent chat`, `ai vibe start` (the only verb under `vibe`, so the
noun goes with it), `new-machine`, and `project checkout-cleanup`.

Hard removal, no alias and no deprecation stub, by explicit decision.

## Verify the premise before deleting on this document's word

Five of its merge verdicts were checked against the handlers. **One
held.** This matters more than the deletions:

| verdict | claim | reality |
|---|---|---|
| `project checkout-cleanup` → `admin checkout-gc` | "same handler" | **true** — both bind `checkout_cmd.cleanup_checkouts`. Deleted. |
| `nixos detect` → `env detect` | "identical handler" | **false** — `nixos detect` drives `NixOSGenerator` and prints a file-type distribution; `env detect` shells out to `nix_env_generator.py`. Different features sharing a verb. **Kept.** |
| `nixos export` → `storage cathedral export` | "identical handler" | **false** — `NixOSGenerator` export vs `cathedral_export.export_project`. **Kept.** |
| `provenance callers` → `graph callers` | "overlaps" | overlapping *question*, different substrate: `graph_trace` over `calls` relations vs `knowledge_graph.symbol_callers` with frecency ranking. A merge is real work; deletion would lose a capability. **Kept.** |
| `admin db integrity` → `db check` | "merge" | partly — `check` does cover `PRAGMA integrity_check`, but `integrity` also prints size and per-table row counts, which `check` and `db status` do not. Folding those in has to come first. **Kept.** |

So "identical handler" in this document means "same verb", not "same
code", in two of the three places it appears. Treat every merge verdict
as a hypothesis with a handler to read, exactly like the `fix` verdicts
above.

# Batch B-1, 2026-10-27 — 456 → 448

Eight more removed, each premise checked first:

- **`tutorial basics` / `quickstart` / `checkout` / `deployment` /
  `mcp` / `advanced`** → `tutorial run <topic>`. All six were
  `subparsers.add_parser(name)` in a loop over `cmd.TUTORIALS`, all six
  bound to `cmd.run_tutorial`, and `run` already documents exactly those
  six names in its own help. Output diffed byte-identical with matched
  stdin. The cleanest case in the whole plan.
- **`file get`** → `file show`. The plan says "merge → `show --raw`",
  which overstates the work: `get` is literally
  `return self.show(args)`, so there is no `--raw` behaviour to
  preserve and no flag to add. 797 lines of identical output. Straight
  deletion.
- **`sync peers`** → `sync status`, which already calls
  `discover_tailscale_peers()` and prints a "Tailscale Peers:" section.
  The GUI settings page advertised the removed command to users and now
  names `sync status`.

Running total of verified-vs-claimed on this plan: of 8 merge/alias
premises examined across batches A and B-1, **5 held and 3 were false**.

# Batch B-2, 2026-10-27 — 448 → 447

**`search query-open` → `search query --open`.** Done. Same search, the
results handed to an editor; "open the results" is a flag on a search,
not a different search. `query_files` delegates to `query_open` rather
than reimplementing it, so the two cannot drift. One intentional
difference preserved: the listing default limit is 20 and the opening
default is 10, because opening 20 buffers is not what anyone means.

**A sixth unreachable `register()`**, in `query_open.py`, registering
top-level `query-open` and `query`. Nothing imported the module, so
neither existed; `search.py` registered the same handlers under `search`
and those are the ones that worked. Deleted rather than wired, as with
`schema.py`.

**`nixos generate-all` → `generate --all`: declined, premise too thin.**
Their flag sets barely intersect — `generate` takes a required slug,
`-o/--output`, `--cathedral-path`, `--no-home-manager`,
`--include-templedb`; `generate-all` takes an *optional* slug, `--host`
and `--dry-run`. One command would need a `--help` that lies about which
combinations are valid, because argparse cannot express "only alongside
`--all`", and `slug` would have to change arity based on a flag. They
are also not the same operation: `generate` builds modules for one
ordinary project, `generate-all` renders a whole nixos-config —
templates, managed modules, flake inputs.

The verdict's stated complaint was that "the boundary with `generate` is
undocumented", and that *was* true. Both help strings now name the other
command and say which job is which, which fixes the actual problem
without manufacturing a flag collision. Verdict here revised from
**merge** to **fix (help text)**, done.

# Batch B-3, 2026-10-27 — 447 → 446

**`nixos list-configs` → `project list --type nixos-config`.** Done.
`list_configs` was this exact query with `project_type` pinned to
`'nixos-config'`, so `--type` expresses it generally; `project list`
already had `--nix-only` and `--category`, and this is the third filter
on the same query. The dead `_args_list_configs` stub and the
`list_configs` method went with it. Same project selected as before,
and `--type regular` generalizes.

**`nixos set-type` → `project set-category`: declined, wrong column.**
They are not two spellings of one thing. `set_type` writes
`projects.project_type`; `set_category` writes
`projects.project_category` (plus `is_nix_project` and
`flake_check_status`). Separate columns, separate vocabularies —
`regular` / `nixos-config` / `service` versus `package` / `home-module`
/ `nixos-module` — and the live data varies them independently:
`project_type='regular'` occurs with all three categories. Moving
`set-type` under `set-category` would silently write the wrong field.

`nixos set-type` stays. If anything should move it is the *noun*: a
command that does one `UPDATE projects SET project_type` has no business
living under `nixos`. That is a real move with a real destination
(`project set-type`), which is a different and better change than the
one the verdict asked for.

# Batch B-4, 2026-10-27 — 446 → 444

**`deploy init` → `deploy config --init`.** Done, and this one the
verdict got exactly right. Both took nothing but a slug and both act on
one object — the project's deployment config — so creating it is a third
verb beside `--show` and `--validate`. `config_command` delegates to
`init` rather than inlining it. Two in-code hint strings that told users
to run `deploy init` now say `deploy config <slug> --init`.

**`deploy target` → `deploy targets`.** Done, but *not* as a plain
deletion. The plural group already had add/list/show/update/remove, and
the singular form offered only `--show` and `--set-connection` — but
`--set-connection` was **the only writer anywhere of
`deployment_targets.connection_string`**. `targets update` had
`--host/--region/--provider/--url` and no way to set it. So the
capability moved to `deploy targets update --connection` first, and the
singular command (plus its 118-line orphaned handler) went after.

Two details carried across rather than lost: the `${ENV_VAR}` notice,
because a connection string containing `${…}` resolves at deployment
time and people who do not know that report it as broken; and
`--connection` tests `is not None` instead of truthiness, so an empty
string clears the column. Every neighbouring field treats `""` as "not
supplied", which is right for a hostname and wrong for a value you are
deliberately unsetting.

Verified by writing `postgres://${DB_USER}@localhost/x` to a throwaway
target on `regr-test` and reading the column back verbatim, then
removing the target.

# Batch B-5, 2026-10-27 — 444 → 443

**`admin cache clear` → `admin cache cleanup --all`.** The verdict read
"two verbs for one idea, differing only by scope", which is true of what
they delete and misses the one way they differed that mattered:
`clear` asked for confirmation, `cleanup` did not. Folding them the
obvious way would either have put a prompt on the routine retention
command or taken it off the one that empties the table. So `--all` keeps
the prompt and the default path stays silent, and the convenient
`cleanup` invocation with its 30-day / 10-entry defaults is unchanged.

**A seventh dead `register()`**, in `cache.py` — a classmethod
registering a top-level `cache` group with all four subcommands.
Nothing called it; `admin.py` imports `CacheCommands`, instantiates it
and builds the parsers itself. It had also drifted: it still registered
`clear`, so reviving it would have restored a command that no longer
exists. That is the failure mode of dead registrations in general —
they rot silently and then look authoritative.

**One of the 50 bare `input()` prompts retired.** `cache_clear`'s
confirmation printed "Error: EOF when reading a line" and exited 1 under
a closed stdin. The outcome was safe — nothing deleted — but it read as
a crash rather than a declined prompt, and this path is now reached by a
flag on a routine command, so it meets automation more often. Routed
through the existing `confirm_action`, which treats EOF and ^C as "no":
now prints "Cancelled" and exits 0.

# The dead-registration sweep, 2026-10-27

Seven were found one at a time while opening modules for unrelated
reasons, so the obvious question was how many more there are. The sweep:
67 modules under `src/cli/commands/` define a `register` entrypoint;
`cli/__init__.py` imports 40. The 28-module gap is mostly **not** dead —
`target.py`, `direnv.py`, `secret.py`, `key.py`, `migration.py`,
`network.py`, the four `deploy_*` modules and the `ai` sub-modules are
all registered under a parent by `deploy.py`, `env.py`, `sync.py` or
`ai.py`.

Five had no caller at all. **Three of those should not be deleted**, and
that is the useful finding:

| module | verdict |
|---|---|
| `cloud_backup.py` (491 lines) | **deleted** — `backup.py`'s own header says it "Consolidates system.py (backup/restore) and cloud_backup.py", and `storage backup cloud` covers every verb it offered (init/push/pull/status/providers/cleanup/test). |
| `deploy_steam.py` (525 lines) | **deleted** — its only caller was the `register_under_deploy` line removed in batch A, so this sweep is just finishing that. |
| `llm.py` | **kept** — `templedb_launcher.py` loads and registers it dynamically via `_load_local`. Absent from `--help` only because `_LOCAL` resolves to the nix store in a deployed build, where the file is not a sibling. |
| `test.py` | **kept** — same launcher path. |
| `code.py` | **kept** — self-documents as "NOT REGISTERED — Functionality available via MCP tools. This Click-based CLI is kept for reference". Deliberate, and its `register` calls Click's `add_command`, which the argparse CLI could not accept anyway. |

`vibe.py` is an eighth: its top-level `vibe` group had `start` as its
only verb, `ai.py` registered `ai vibe start` instead, and that was
removed earlier today — so the registration is now dead twice over. The
register went; the module stays because `src/agent/context.py` imports
`VibeCommands` for context generation.

**Method note.** "Defines `register` but is not imported by
`cli/__init__.py`" is a *candidate* filter, not an answer: it has a 23/28
false-positive rate here because registration-under-a-parent is the
normal pattern, and of the 5 it does isolate, 3 are intentional. A
dynamic `_load_local` call and a module whose docstring says "not
registered on purpose" are both invisible to a grep for call sites.

# `storage backup gcs` — declined, and this one would have broken production

The verdict was **merge → `backup cloud push --provider gcs`**. The
target command exists. It cannot work:

```
$ templedb storage backup cloud providers
  ✅ filesystem            Available: Yes
  ❌ gcs                   Available: No (missing dependencies)
  ❌ gdrive                Available: No (missing dependencies)
  ❌ google-cloud-storage  Available: No (missing dependencies)
```

Checked against the deployed closure: `requests` and `cryptography` are
packaged, `google.cloud.storage` and `googleapiclient` are not. The
generic provider needs the latter. `gcs_push` hand-rolls the upload —
signs its own JWT with `cryptography`, posts with `requests` — which is
*why it exists*, not an oversight to tidy away.

And it is load-bearing: `templedb storage backup gcs` is the `ExecStart`
of `templedb-backup.service`, on a daily timer, defined in a different
project (`templedb-backup-service/module.nix`). The rename would have
stopped backups silently — the unit would still fire, the provider would
fail on import, and nothing in the system checks that a backup landed.

A guard now lives in `gcs_push`'s docstring and on its parser, because
the next reader will also see two GCS commands and reach for the obvious
conclusion.

**To do the merge properly:** package `google-cloud-storage`; confirm
`storage backup cloud providers` reports gcs available; port the
credential path (the bespoke one reads the *global* `secret_blobs` row
for `GOOGLE_APPLICATION_CREDENTIALS`, the provider framework expects
`--config`); then rename and update `module.nix` in the same deploy.

That is four steps spanning two projects and a package set, which is a
different proposition from "merge two commands".

# Batch B-6, 2026-10-27 — 443 → 442

**`vcs edit` removed.** The verdict said "merge → top-level `edit`,
which is the documented path". Right destination, wrong reason — these
were never two spellings of one thing:

- top-level `edit` provisions a per-session workspace under
  `edit-workspaces/`, which is diffed against the DB at commit time;
- `vcs edit` called `make_writable()` on the **canonical** checkout,
  recursively chmod-ing `~/.config/templedb/checkouts/<slug>` to
  644/755.

That second thing is the state `checkout_files_are_mode_locked` reports
as a violation and `admin lock-checkouts` exists to undo, and CLAUDE.md
names editing that tree as a thing not to do because the next
materialise overwrites it. It then printed "To save changes: templedb
vcs commit <slug>", which **refuses** — `CheckoutRepository` raises
`NoEditCheckout` for a caller with no edit workspace. The workflow it
advertised could not complete.

So this was not duplication to collapse, it was a command whose purpose
was to create a defect, with instructions that dead-ended.

**The tutorial was teaching it**, in two topics, which is how this
turned into more than a one-line removal. While repointing those, the
surrounding steps turned out to be stale in ways that make the Quick
Start literally unrunnable:

| claim | reality |
|---|---|
| `~/.local/share/templedb/checkouts/` (3 places) | checkouts live under `~/.config/templedb/` |
| `vcs add my-project src/` | `-p` is **required**; the slug is read as a file pattern |
| `vcs commit my-project -m …` | same — `-p` required |
| "Returns checkout to read-only mode after commit" | describes the edit-mode model that just went |
| "Two modes: read-only / edit mode" | there is one mode; the second was removed |

All corrected, plus the checkout topic now states the
checkout-vs-workspace distinction outright rather than implying a mode
toggle. `checkout.py`'s module docstring ("Used by: project checkout,
vcs edit commands") and `scripts/migrate_checkouts_readonly.py`'s
closing hint also pointed at the removed command.

`VCSCommands.edit` (58 lines) went with the command. `make_writable` now
has no caller outside its own module; it is left in `sync/permissions.py`
as a general helper rather than deleted.

One route to the same state remains and is **deliberately kept**:
`project checkout --writable` leaves a fresh checkout writable by
skipping `make_readonly` rather than by chmod-ing afterwards. Unlike
`vcs edit` it takes an arbitrary target directory, so a writable scratch
checkout somewhere other than `checkouts/<slug>` is a legitimate thing
to want. It is only a hazard when aimed at the canonical path, which is
`checkout_files_are_mode_locked`'s job to notice.

# Batch B-7, 2026-10-29 — 442 commands, two declines and a gate

Picked up the three verdicts this document still listed as open for
`deploy`. Two of them were wrong, in the two different ways the rest of
this file keeps warning about.

**`deploy fleet destroy` → gate: void, the command is already inert.**
The verdict calls it "the single most destructive command in the CLI"
and asks for confirm-by-typing. It cannot destroy anything.
`FleetCommands.destroy` returns `self._retired()`, which prints the
shared `_RETIRED` message and exits 1 before reading an argument or
opening the database — fleet deployment went in migration 130, and
`fleet deploy` and `fleet deploy-status` are retired the same way.
Verified against the deployed binary, not just the source.

So the dangerous-looking command was the safe one, and putting a
confirmation prompt on it would have been pure ceremony — worse than
nothing, because a gate implies there is something behind it. The three
parsers stay registered on purpose: `_RETIRED` names
`nixos system-switch` as the replacement, which is a better answer to
`deploy fleet destroy` than `Unknown command`.

**`deploy migration *` → move to `admin db`: declined, different
object.** The verdict reads "Five commands about *database* migrations,
while `admin db migrate` also exists. Migrations are a schema concern,
not a deployment concern." The first sentence is true and the inference
does not follow, because the two sets do not act on the same database:

| | `deploy migration *` | `admin db *` |
|---|---|---|
| migrations come from | `project_files` typed `sql_migration`, per project | the `migrations/` directory in this repo |
| applied-state lives in | `migration_history`, keyed `(project_id, target_name)` | `schema_version` |
| the database acted on | a **tracked project's** database, per deploy target | **TempleDB's own** sqlite file |

`migration_history` holds 21 rows across 2 projects and 3 targets
(2026-02-23 to 2026-07-04), so this is a used feature and not a
vestige. "Which migrations has this project had applied on
*production* versus *staging*" is a deploy question; `--target` is on
every one of the five commands and has no meaning under `admin db`,
where there is one database and no targets. `admin db migration list
<slug>` would be a command whose noun promises the local schema and
whose argument asks about somebody else's.

This is the same shape as the `nixos set-type` decline above — one verb,
two columns — and the running tally is now **of 11 merge/move premises
examined, 6 held and 5 were false.**

**`deploy migration mark-applied` → gate: done, and this one was
real.** It wrote a `migration_history` row claiming a migration ran
when it did not, with no prompt, no `--yes` and no `--dry-run`. After
it, `status` reports the migration applied and `get_pending_migrations`
never returns it again, so the skipped schema change is invisible for
that `(project, target)` pair.

It is `admin db stamp`'s hazard on a worse substrate. `stamp` lies
about TempleDB's own `schema_version`, where the lie is at least local
to the machine you typed it on; this lies about a *deployed project's*
database, and surfaces later as the next thing that assumes a column
exists. Gated the same way, for the same reason — `confirm_by_typing`
with the migration's filename, `--dry-run` to preview, `--yes` for the
one legitimate unattended case (adopting a database whose migrations
really were applied out of band). EOF and ^C are refusals.

Verified all four branches with the tracker write stubbed: correct
filename writes once, wrong filename writes nothing and exits 1,
`--yes` skips the prompt and writes, `--dry-run` writes nothing. The
two refusal paths were also exercised end-to-end through the real CLI.

Deliberately *not* verified by running the accept path for real: doing
so means writing a true "this migration was applied" row for a target
that does not exist, which is the exact falsehood the gate exists to
prevent, and nothing in the CLI can delete a `migration_history` row
afterwards. The throwaway-project route does not work either —
`file set` types a new `migrations/*.sql` as `sql_file`, not
`sql_migration`, so `get_project_migrations` cannot see it and there is
no rescan command that reclassifies.

**A ninth dead `register()`**, in `migration.py` — a 38-line
near-duplicate of `register_subcommands` binding a top-level
`migration` group. `templedb migration list` answers
`Unknown command: 'migration'`; `deploy.py` calls
`register_subcommands` and that is the live path. Deleted.

It illustrates the B-5 point about dead registrations rotting
concretely: had it been left in place, the next person to wire it up
would have restored `mark-applied` **without** the gate added above,
since the gate's flags only exist in the live registration. A dead
`register()` is not inert, it is a stale copy of the surface that
looks authoritative.

Command count unchanged at 442 — nothing this registration bound was
ever reachable, so deleting it removes no command.

# Batch B-8, 2026-10-29 — 442 → 441, and two bugs the verdicts were hiding

Four more verdicts. One merge was right, one was false, and the two
commands involved both turned out to be broken in ways this document
never mentions — which is the pattern worth naming: a verdict that
argues about where a command should live has usually not checked
whether it works.

**`ai prompt project-list` → `prompt list --project`: declined,
different tables.** `list_templates` queries `prompt_templates`
(name, category, version, is_active) and filters on `--category` /
`--active-only`. `list_project_prompts` queries the
`active_project_prompts_view` by `project_id`, ordered by priority.
Different relation, different columns, different output. `--project`
would not be a filter on the existing query, it would be a switch to a
different one — the `nixos set-type` shape again. Tally: of 13
merge/move premises examined, 6 held and 7 were false.

**`project generate-envrc` → `env direnv generate`: declined, and it
emitted a path that cannot exist.** The two commands write different
things. `env direnv generate --write` writes the *expanded*
environment — secrets, vars, the `use nix` directive — as a snapshot.
`project generate-envrc` writes a one-line *shim* that delegates at
shell-entry time, so the values are re-resolved on every `cd`. Static
bake versus dynamic hook; collapsing them would lose the distinction
that makes the shim useful.

The command was broken anyway. It derived an absolute interpreter path
from `__file__`:

```python
templedb_path = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'templedb'))
```

In the deployed build that resolves to
`<store>/lib/python3.13/templedb`. The package keeps its entrypoint in
`<store>/bin`, so the generated `.envrc` named a file that has never
existed and direnv failed on every `cd` into the project. Verified
against the live closure.

Writing *any* absolute store path there is wrong even corrected: the
path rotates on every rebuild and is garbage-collectable, so a
committed `.envrc` pinning one breaks as soon as its generation is
collected. Now emits `eval "$(templedb env direnv)"` and resolves off
PATH, which is what every doc and every other generated artifact
already assumes. The comment that said "use absolute path to templedb
for reliability" had it exactly backwards.

**`env direnv verify` → `diff --exit-code`: done, and the checker could
never pass.** The verdict is right — one comparison with two front
ends. `verify` printed a verdict and exited 1 on a difference; `diff`
rendered hunks and exited 0 either way. So the verdict became a flag,
following git: a diff is not an error unless you ask for it.

Folding them exposed why nobody missed `verify`. The generated `.envrc`
carries a `# Generated: <wall clock>` header, so a file written by
`generate --write` stopped matching the generator **one second later**.
`verify` compared with `.strip()`, which does nothing for a line in the
middle, and therefore answered "differs from TempleDB state" for every
project unconditionally — including one generated moments earlier from
identical data. A checker whose answer does not depend on its input.

So `--exit-code` is only meaningful with the volatile line excluded,
and `_comparable()` drops it. Everything else the header carries
(project, profile, environment) is real state and still compared. The
rendered hunks now come from the same normalized line lists as the
exit status, so output and exit code cannot disagree — the old `diff`
shelled out to `/usr/bin/diff` against a tempfile while `verify`
compared in-process, which is how the two drifted apart in the first
place. `difflib` replaces the subprocess and the tempfile.

Verified: a freshly generated `.envrc` now reports up-to-date and exits
0 where it previously always failed; appending one `export` line gives
exit 1 and a hunk naming it; a missing `.envrc` still exits 1.

**A tenth dead `register()`**, in `direnv.py` — a top-level `direnv`
group with the full generate/diff/verify set. `templedb direnv` answers
`Unknown command: 'direnv'`; `env.py` calls `register_subcommands` and
that is the live path. Deleted. Like `migration.py`'s, it had already
rotted: it still bound `cmd.verify`, so wiring it up would have
restored the command this batch removed.

Count: 442 → 441 for `verify`. The dead registration removes nothing,
because nothing it bound was reachable.

# Batch B-9, 2026-10-29 — 441 → 439, the last of the open verdicts

The four `deploy`/`graph`/`admin` verdicts this document still listed.
Two held, two did not, and in both of the ones that held the document
understated what was there.

**`deploy project-history` → `deploy history`: done, and no scope flag
was needed.** The verdict asked for "`deploy config` / `deploy history`
with a scope flag", which assumes the two look at different scopes.
They do not. Both run the same query — `deployment_history` joined to
`projects` on slug, `ORDER BY started_at DESC LIMIT ?` — and
`project-history` was otherwise a strict subset, with no `--target`.
Confirmed by running both against `system_config`: same rows, same
order.

The one thing it had that the survivor did not was the **rendering**:
one line per deploy against `history`'s six-line block, which is
better for scanning a history and is what anyone reaching for this
command wants. So the capability moved first, as with
`deploy targets --connection` in B-4 — `deploy history --compact`
reproduces the old output byte-for-byte — and then the command went.
`--limit` also gained `-n`, which `project-history` had and `history`
did not.

Compact additionally skips the per-deployment health-check lookup,
which was one query per row.

**`deploy project-config` → `deploy config`: declined, different
schema and the only writer.** Both read `projects.deployment_config`,
but not the same thing inside it: `project-config` reads the
`app_deploy` key through `AppDeployService` / `AppDeployConfig`, while
`deploy config` reads `config.groups` through
`DeploymentConfigManager`. Two different config shapes sharing one JSON
column, with different managers and different validators. A flag that
switched between them would be `prompt list --project` again — one name
over two output schemas.

It is also the **only writer** of the `app_deploy` config anywhere:
`--set JSON` has no counterpart under `deploy config`, whose verbs are
`--show`, `--validate` and `--init`. Deleting it before porting that
would have lost the capability, which is the `deploy target
--set-connection` trap from B-4 exactly.

**`admin db integrity` → `check`: done, and "per-table row counts" was
five tables.** The earlier note here said the merge needed `integrity`'s
"size and per-table row counts" folded in first. Size was already in
`check` (`DB size:`). And the row counts were not per-table — they came
from `get_db_stats()`, which has a hardcoded list of five:
`projects`, `project_files`, `nix_environments`, `vcs_commits`,
`vcs_branches`. Out of 168 tables, and chosen long enough ago that
`entities`, `relations` and `edit_intents` — the three largest things
in the database after `nix_closure_paths` — are all absent.

So rather than preserve the five, `check --tables` counts every table
and orders by count descending, which is the question the five were a
guess at. It is opt-in because 167 lines would bury the health output
the command exists to print. A table that cannot be counted is
reported as a problem rather than skipped: a foreign key pointing at a
dropped table raises at DML time, not schema load, so "COUNT(*) fails
here" is a real finding.

Measured on the live database: `nix_closure_paths` 499,158, `relations`
90,774, `checkout_snapshots` 84,225, `entities` 82,159 — none of which
the retired command could show.

**`graph changes` → `deploy diff` / `deploy status`: declined, the
destination is occupied and means something else.** `graph changes`
reads `deployment_history` for the last success, then `vcs_commits`
after that timestamp and `vcs_working_state` for uncommitted files —
all TempleDB tables, answering "what source has changed since the last
deploy". `deploy fleet diff` shells out through `NixDeployBackend` to
compare *system closures* on remote machines over SSH. Same English
word, nothing in common: one is a source report from the database, the
other is a nix closure diff over the network.

The verdict's underlying complaint is still right, and worth leaving on
the record: `graph changes` touches no graph substrate at all — no
`entities`, no `relations`, no traversal — so `graph` is the wrong
noun. But the honest destination is a new `deploy changes`, not the two
named here, and that is a pure rename: no surface reduction, breakage
for anything scripted against it, and it would have to keep or abandon
its `graph.changes` frecency key. Recorded as a real move with a real
destination, deliberately not taken as part of a reduction pass.

**The GUI was advertising the removed command.** `gui_helpers.py`'s
Database & Backup panel listed `templedb admin db integrity` as the
integrity check, which would now print `Unknown command` for anyone
who copied it out of the browser. Now names `admin db check` and
`check --tables`. Third time a removal in this plan has turned up a
live reference outside the CLI — `sync peers` in B-1 and `vcs edit`'s
tutorial in B-6 were the others — so "grep the GUI and the tutorial"
belongs in the checklist, not just "grep src/".

`docs/SECURITY_THREAT_MODEL.md` mentions `templedb integrity check`,
which is **not** this command: it is an unchecked box in a proposal for
a content-addressable integrity framework. Left alone.

Count: 441 → 439. Final tally on this document's merge/move verdicts —
**of 15 examined, 7 held and 8 were false.** A verdict here is a
hypothesis with a handler to read.

# Batch B-10, 2026-10-29 — `config-ast host`, and the corrected tally

The last open verdict, and the one with the largest thing hiding behind
it.

**`config-ast host add` / `list` → `nixos host`: declined. Merging them
means deciding the config migration, not tidying a surface.** The
verdict reads "merge → `nixos host` (or vice versa; pick one)", and
"pick one" is doing a great deal of work in that sentence. The two
commands do not share a substrate:

| | `config-ast host` | `nixos host` |
|---|---|---|
| stores hosts in | `config_hosts` (5 rows) | `system_config` keys `nixos.host.%` (6 keys) |
| structure | hierarchical — `parent_id`, walked for resolution | flat key/value |
| belongs to | the `config_nodes` AST model (1,390 nodes) | the live `system_config` path |
| generates the machine? | **no** | yes |

`config-ast`'s own registration already says why, and it was written
before this verdict: `config_nodes` was last written 2026-08-05,
nothing generates from it, only 2 of 27 `ast_builds` were ever
promoted, and `config-ast set` succeeds while having no effect on the
machine. It is explicitly **not deprecated** — 1,390 nodes and a
working build pipeline are real work — but it is not the live path
either.

So "pick one" is a choice between abandoning the AST model and
finishing its migration. Either is a legitimate project; neither is a
command merge. The hierarchy is the concrete obstacle: `nixos host`
has no notion of a parent host, so folding `config-ast host` into it
would drop inheritance, and folding the other way would move the live
path onto a model nothing generates from. Left as-is, which is what
the incomplete-migration note already prescribes.

**Corrected tally.** B-9 closed at "of 15 examined, 7 held and 8 were
false". With this one: **of 16 merge/move verdicts examined, 7 held and
9 were false.** Slightly worse than a coin flip, which is the number to
carry forward — every remaining verdict in the tables above is a
hypothesis with a handler to read, and the failure mode is not a bad
merge but a *plausible* one that quietly drops a capability
(`deploy target --set-connection`, `deploy project-config --set`) or
breaks something off-CLI (`storage backup gcs`'s systemd timer, the
GUI panel in B-9, the tutorial in B-6).

The reduction pass ends here at **439 commands**, down from 463: 24
removed, every premise checked first, with three bugs found along the
way that the verdicts were standing on top of — `graph overview`'s
88s join, `project generate-envrc`'s nonexistent interpreter path, and
`env direnv verify`'s comparison that could never succeed.
