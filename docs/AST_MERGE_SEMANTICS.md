# AST Resolver Merge Semantics

Status: **draft, not implemented** — 2026-08-02
Owner: config-ast resolver
Blocks: phase 2 (promote + deploy from AST)

## The gap this closes

When phase 1's `templedb ast build --nix-build --host zMothership2` was
diff'd against a live build of the same host, the closures diverged by
~168 MB — docker, alsa-utils, sops, hplip, ntfs3g, and a dozen other
packages were missing from the AST-built system.

Root cause: `ConfigCompilerService._resolve_host()` picks a single winner
per named binding. When shared config has
`environment.systemPackages = [15 packages]` and host has
`environment.systemPackages = [3 packages]`, the host's list REPLACES
shared. Nix's actual module system CONCATENATES them.

Same problem for AttrSets that both sides extend: shared
`services.foo = { a = 1; }` and host `services.foo = { b = 2; }`
should yield `{ a = 1; b = 2; }`. Current resolver yields `{ b = 2; }`.

Until this is fixed, AST-driven deploys would silently drop packages
and settings. It is a **hard blocker for phase 2** promote/deploy.

## What nix actually does (the target semantics)

Nix's module system knows each option's *type* because modules declare
options with `mkOption { type = types.X; }`. Merge behavior per type:

| Nix option type          | Merge behavior                                 |
|--------------------------|-------------------------------------------------|
| `types.listOf X`         | Concatenate in module-load order               |
| `types.attrsOf X`        | Merge; on key collision recurse per X's type   |
| `types.submodule`        | Recursively merge sub-options                  |
| `types.bool/int/str/...` | Last-wins by priority (default 100, mkForce 50, mkDefault 1000) |
| Freeform module attrs    | Recursively merge                              |
| `types.uniq (listOf X)`  | Concat + dedup                                 |
| `types.functionTo X`     | Compose                                        |

We do not have option type information in the AST. We're representing
raw expressions, not module option declarations. So we can't perfectly
replicate nix's semantics.

## Approximation the AST can do

Without type info, use *structural* rules based on node type:

| Both sides are... | Merge behavior             |
|-------------------|----------------------------|
| `AttrSet` / `RecAttrSet` | Deep-merge children: collect all named children across all inputs, recurse per name |
| `List`            | Concatenate children in priority order |
| Any leaf (`Bool`, `Int`, `String`, `Path`, `Identifier`, `FnCall`, ...) | Highest-priority input wins |
| Type mismatch (e.g. shared `String`, host `AttrSet`) | Highest-priority input wins entirely |

This gets 95%+ of real configs right. It matches nix's freeform-attrs
behavior exactly. It matches `types.listOf` (without dedup) and
`types.attrsOf` (with structural merge). It's wrong for `types.uniq`
(would allow duplicates) — acceptable rate, and nix will still evaluate
the resulting config (just with harmless duplicate list entries).

## Priority order

For a host resolve, sources ranked lowest → highest priority:

1. Shared (`host_id IS NULL`)
2. Ancestor hosts from `config_hosts.parent_id` chain, root first
3. Target host last

`host_chain(host_name)` currently returns most-specific-first
(`[self, parent, grandparent]`). Merge sequence needs reversed +
shared prepended: `[None, grandparent, parent, self]`. Later inputs
override earlier ones for leaves.

## Concrete cases from real zMothership2 data

| Path | Shared | Host | Current resolver | After fix |
|------|--------|------|------------------|-----------|
| `environment.systemPackages` | `[alsa-utils, cryptsetup, docker, hplip, ...]` (15+) | `[pgadmin4, beep, obs-studio]` | host's 3 only ❌ | 18+ combined ✓ |
| `boot.loader.grub.enable` | not set | `true` | `true` ✓ | `true` ✓ |
| `boot.loader.grub.device` | not set | `"/dev/nvme0n1"` | leaf ✓ | leaf ✓ |
| `services.xserver.videoDrivers` | not set | `["nvidia"]` | `["nvidia"]` ✓ | `["nvidia"]` ✓ |
| `networking.firewall.allowedTCPPorts` | 30+ ports | not set | 30+ ✓ | 30+ ✓ |
| `hardware.nvidia.prime.nvidiaBusId` | not set | `"PCI:01:00:0"` | leaf ✓ | leaf ✓ |
| `virtualisation.docker.enable` | `false` | (not set) | `false` | `false` |
| `fonts.packages` | not set | `[anonymous, corefonts, dejavu, ...]` | host's list ✓ | host's list ✓ |
| `imports` (hypothetical if both set) | `[./shared.nix]` | `[./host-specific.nix]` | one wins ❌ | both ✓ |

Cases marked ✓ under "current resolver" only look correct because one
side is empty. The moment both sides extend, we lose.

## Implementation sketch

Change site: `ConfigCompilerService._build_children()` around
`src/services/config_compiler.py:340`.

Replace the `by_name` winner-pick block with:

```python
if parent.node_type in ('AttrSet', 'RecAttrSet', 'LetIn'):
    by_name: Dict[str, List[ConfigNode]] = {}
    unnamed = []
    for c in candidates:
        (by_name.setdefault(c.name, []).append(c)) if c.name else unnamed.append(c)
    for name, nodes in by_name.items():
        merged = self._merge_by_priority(nodes, host_chain)
        if merged:
            parent.children.append(merged)
    for c in unnamed:
        if self._host_visible(c, host_chain):
            parent.children.append(c)
```

New `_merge_by_priority(nodes, host_chain)`:

```python
def _merge_by_priority(self, nodes, host_chain):
    # Order sources: shared, then host chain root -> leaf
    ordered = []
    for n in nodes:
        if n.host_id is None: ordered.append(n)
    for host_id in reversed(host_chain):
        for n in nodes:
            if n.host_id == host_id: ordered.append(n)
    if not ordered: return None
    if len(ordered) == 1: return ordered[0]
    return self._merge_nodes(ordered)

def _merge_nodes(self, nodes):
    # All AttrSet-ish: recurse
    if all(n.node_type in ('AttrSet', 'RecAttrSet') for n in nodes):
        merged = ConfigNode(id=nodes[-1].id, ..., children=[])
        by_name, unnamed = {}, []
        for n in nodes:
            for c in n.children:
                (by_name.setdefault(c.name, []).append(c)) if c.name else unnamed.append(c)
        for name, children in by_name.items():
            merged.children.append(self._merge_nodes(children))
        merged.children.extend(unnamed)
        return merged
    # All List: concatenate
    if all(n.node_type == 'List' for n in nodes):
        merged = ConfigNode(id=nodes[-1].id, ..., children=[])
        for n in nodes:
            merged.children.extend(n.children)
        for i, c in enumerate(merged.children):
            c.sort_order = i
        return merged
    # Type mismatch or leaves: highest priority wins
    return nodes[-1]
```

Downstream (emitter, JSON serializer) works unchanged — they walk
`ConfigNode.children` and don't touch merged nodes' identity.

## Test cases (behavior spec)

Concrete cases the fix must pass. Write these as an actual test file:

```
1. list_merge_concatenates
   shared: environment.systemPackages = [a, b]
   host:   environment.systemPackages = [c, d]
   expect: [a, b, c, d]

2. attrset_deep_merge
   shared: services.foo = { a = 1; }
   host:   services.foo = { b = 2; }
   expect: services.foo = { a = 1; b = 2; }

3. leaf_last_wins
   shared: boot.loader.grub.enable = false
   host:   boot.loader.grub.enable = true
   expect: true

4. deep_nested_leaf_override
   shared: services.foo = { a = 1; b = { c = 1; }; }
   host:   services.foo = { b = { c = 2; d = 3; }; }
   expect: services.foo = { a = 1; b = { c = 2; d = 3; }; }

5. type_mismatch_host_wins
   shared: x = "string"
   host:   x = { attr = 1; }
   expect: x = { attr = 1; }

6. no_host_binding_shared_used
   shared: system.stateVersion = "25.11"
   host:   (not set)
   expect: "25.11"

7. no_shared_binding_host_used
   shared: (not set)
   host:   boot.loader.systemd-boot.enable = true
   expect: true

8. empty_lists_still_concat
   shared: [] + host: [x] → [x]
   shared: [x] + host: [] → [x]

9. shared_only_no_host_arg
   resolve(scope='system', host_name=None) returns shared-only tree
   (unchanged from current behavior)
```

## Real-world verification

The definitive test: closure hashes should converge (not necessarily
identical yet, but the 168MB delta should shrink dramatically).

```
before_fix=$(nix build --no-link --print-out-paths \
  "<ast-build-dir>#nixosConfigurations.zMothership2.config.system.build.toplevel")
live=$(nix build --no-link --print-out-paths \
  "<live-checkout>#nixosConfigurations.zMothership2.config.system.build.toplevel")
nix store diff-closures $live $before_fix   # currently 168MB

# apply fix, rebuild AST
after_fix=$(templedb ast build --host zMothership2 --nix-build | ...)
nix store diff-closures $live $after_fix     # target: <10MB
```

If any delta remains after the fix, it's individual bugs (parser gaps,
unhandled node types) that we'd chase one at a time.

## Migration / determinism impact

Every existing `ast_builds` row will emit a different `output_hash`
after this change, because merged trees are richer. Not a real problem
— nothing consumes the table yet.

Option: drop rows in a migration. Cleaner but wastes disk (build dirs
stay). Option: leave rows alone, users rebuild and get new rows. Fine
for phase 1.

I'd leave them alone; running `templedb ast build --host X` a second
time after the fix creates a fresh row + build dir. Old rows stale-but-
harmless.

## Escape hatches deferred

Nix has `mkForce` / `mkOverride` for "replace, don't merge." Rare in
practice — the whole point of the module system is that people
extend, not replace. If a user hits a case that genuinely needs
replacement, we'd add a marker later (e.g. a `_mkForce = true` meta-
attr on a subtree, or a new `MkForce` wrapper node type).

Not blocking phase 2. Ship the deep-merge default first, add escape
hatch when someone actually needs it.

## Rollout

Single PR, single service file. No new tables, no CLI additions, no
migrations. Just:

1. Replace `_resolve_host` + `_host_visible` merge logic in
   `_build_children` with `_merge_by_priority` + `_merge_nodes`.
2. Add unit tests for the 9 cases above.
3. Rebuild AST for zMothership2, verify closure delta shrinks toward
   zero.
4. Update memory: BLOCKING flag removed, phase 2 unblocked.

## Question that could shape this

The only real ambiguity: **should we ship deep-merge as always-on, or
gate it behind a flag per host in `config_hosts`?**

Case for always-on (my recommendation):
- Matches user intent 100% of the time in observed real configs
- Winner-takes-all is currently *broken* semantics; there's no user who
  benefits from it
- Consistent behavior is easier to reason about

Case for per-host flag:
- Would let us migrate hosts one at a time
- Any behavior change is a risk vector

I lean always-on because winner-takes-all was never a designed
semantic — it was an artifact of a resolver that predated real
host-tagged content. No one is relying on the current behavior.
