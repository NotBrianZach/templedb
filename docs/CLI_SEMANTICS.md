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
| `nixos packages add` / `remove` | managed-package CRUD | `W·db` | **fix** — writes to the nonexistent `nixos_packages` table |
| `nixos packages list` | read managed packages | `R·db` | **fix** — `no such table: nixos_packages` |
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
| `nixos system status` | machine deployment state | `R·nix` | **fix** — `AttributeError: get_system_status` |
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
| `admin cache list` | cached deployments | `R·db` | **fix** — `AttributeError: db_utils` |
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
| `file set` | replace file content, routed through EditIntent; auto-stages | `W·db` | **core** — replaces the WHOLE file; `--if-match` is the guard |
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

**Blocker 1 — the emitter cannot represent comments.** It knows 20 node
types (`AttrSet`, `FnCall`, `With`, `LetIn`, `MultilineString`,
`Interpolation`, …) and **none is a comment**; there is no comment
emission anywhere in `config_compiler.py`. `config_nodes.description`
exists and is populated on **0 of 1254 rows**. So 86 lines of
rationale — including a 20-line explanation of why Magic SysRq is set
to 1 rather than 244 — are structurally unrepresentable. In a codebase
whose comments are its institutional memory, that is not a rounding
error.

**Blocker 2 — some of it is authored code, not configuration.** Among
the 76 config lines is `voiceAIEnvRenderer`, a 15-line shell script
embedded via `pkgs.writeShellScript` with Nix interpolation, a
`makeBinPath` call and error handling. Representable in principle
(`MultilineString` + `Interpolation` + `FnCall`); maintaining it as a
node tree would be strictly worse than maintaining it as Nix.

**Re-seeding does not help.** `config-ast seed --dry-run` would rewrite
all 158 `nixos.*` keys and close **none** of the gap: `kernel.sysrq`,
`lib.mkDefault`, `brightnessctl` are keys in neither model. The
hand-edits exist only in the derived file.

`AST_MERGE_SEMANTICS.md` does not cover this either — it specifies
merging *multiple AST inputs* by host-chain priority, not merging AST
output into an edited file.

## The three ways forward

1. **Add a `Comment` node type and emission**, then re-encode 76 config
   lines as nodes and 86 as comments. Unblocks completion; still leaves
   a shell script maintained as a node tree.
2. **Draw a scope boundary** — the AST owns structured settings,
   authored Nix stays in files, and `generate` *merges* rather than
   replaces. Respects both halves, but is a design project, and the
   merge it needs does not exist yet.
3. **Retire the AST path.** Honest if nobody will do 1 or 2; the
   `INCOMPLETE MIGRATION` label already says this much.

**Recommendation: (2).** The AST model is genuinely good at structured
settings and genuinely unable to hold authored prose and embedded
scripts. A generator that replaces its own output will always lose to
the first person who edits the output — which is exactly what happened
here, in August. Option 1 buys completion at the cost of making Nix
authorship hostile; option 3 discards a working, nix-verified build
pipeline.

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
| `graph overview` | cross-project analysis | `R·db` | **fix (perf)** — 42s, pure local query work |
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
| `sync status` | sync state and peers | `R·net` | **fix (perf)** — 31s of peer probes |
| `sync peers` | discover Tailscale peers running TempleDB | `R·net` | merge → `sync status` |
| `sync network connect` | connect to Tailscale | `W·net` | keep — the only `network` command that works |
| `sync network status` | network + peer status | `R·net` | **fix** — `NameError: ts_info` |
| `sync network setup` | install and configure Tailscale | `D·fs` | **fix** — same `NameError` |
| `sync network sync-all` | sync with all online peers | `D·net` | **fix** — `NameError` fires before any sync; has never worked |

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
| `intent apply` | apply a proposed intent | `W·db` | core |
| `intent cancel` | abandon a proposal | `W·db` | keep |
| `intent list` | outstanding intents by default | `R·db` | core |
| `intent show` | one intent in full | `R·db` | keep |

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
| `validate` | run all validators (env, nixos, deploy) | `R·db` | **fix** — reports PASS while a check errors on a missing table |
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
