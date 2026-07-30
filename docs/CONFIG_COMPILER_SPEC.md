# TempleDB Configuration Compiler

**Status:** Draft
**Date:** 2026-07-30
**Author:** Zach Abel

## Summary

TempleDB becomes a **configuration compiler**. System configuration is stored
as a typed graph of AST nodes in the database. Nix files become generated
build artifacts — never hand-edited. The graph supports project ownership,
host inheritance, semantic queries, and backend-agnostic code generation.

This replaces the current `system_config` key-value table, the
`templedb-managed` marker sections in .nix files, and the regex-based
`nix_codegen.py` generator.

---

## 1. Motivation

### What exists today

The `system_config` table stores flat key-value pairs:

```
nixos.attr.services.openssh.enable = true
nixos.pkg.user.cli_utilities.claude-code = true
nixos.alias.twoWeekGC = nix-collect-garbage --delete-older-than 14d
```

The `nix_codegen.py` generator reads these keys, groups them by prefix
convention, and patches them into .nix files between `# === BEGIN/END
templedb-managed ===` markers. Everything outside the markers is hand-edited.

### Problems

1. **Two sources of truth.** Some config lives in the DB, some in .nix files.
   Edits to either can drift. The `deploy nixos-install` command does regex
   surgery on files to add packages.

2. **No structure.** `nixos.attr.services.openssh.settings.PermitRootLogin`
   encodes a tree as a dotted string. You can't ask "what services are
   enabled?" without string prefix matching. You can't ask "what does project
   X contribute?" at all.

3. **No ownership.** Packages, services, and config attrs aren't linked to
   the projects that need them. Removing a project doesn't clean up its
   config. Adding a project requires manual coordination.

4. **Nix as opaque strings.** Complex expressions (derivations, let bindings,
   function calls) can't be stored — they stay in files. This creates the
   confusing hybrid where "some config is in the DB and some isn't."

5. **One backend.** The system is hardwired to Nix. The same configuration
   concepts (packages, services, firewall rules, users) exist in Docker
   Compose, Kubernetes, Ansible, and Terraform, but there's no path to
   reuse.

### What this spec proposes

Store configuration as a **typed AST** in the database. The AST captures the
full semantic structure — not as Nix source text, but as a graph of typed
nodes that can be serialized to Nix (or any other format).

---

## 2. Core Concepts

### 2.1 Everything is a node

Every piece of configuration is a node in a tree. Nodes have types, parents,
and values. The tree mirrors the logical structure of the configuration.

```
(AttrSet)                          root: "system" scope
  services (AttrSet)
    openssh (AttrSet)
      enable (Bool: true)
      settings (AttrSet)
        PasswordAuthentication (Bool: false)
        PermitRootLogin (String: "no")
    pipewire (AttrSet)
      enable (Bool: true)
      pulse (AttrSet)
        enable (Bool: true)
  networking (AttrSet)
    firewall (AttrSet)
      allowedTCPPorts (List)
        (Int: 22)
        (Int: 80)
        (Int: 443)

(AttrSet)                          root: "home" scope
  home (AttrSet)
    packages (List)
      (Package: "claude-code")
      (Package: "emacs")
      (Package: "nodejs")
```

There is no `attr_path` string. The path `services.openssh.enable` is
recovered by walking parent pointers. The tree *is* the structure.

### 2.2 Node types

Nodes have a `node_type` that determines their semantics and how the backend
serializes them.

| Node Type    | Semantics                                    | Nix serialization               |
|--------------|----------------------------------------------|---------------------------------|
| `AttrSet`    | Named children, each unique by name          | `{ child = ...; }`             |
| `List`       | Ordered children                             | `[ child child ... ]`          |
| `Bool`       | Leaf: true/false                             | `true` / `false`               |
| `Int`        | Leaf: integer                                | `42`                           |
| `String`     | Leaf: string value                           | `"hello"`                      |
| `Path`       | Leaf: filesystem path                        | `./foo.nix`                    |
| `Package`    | Leaf: package name (from pkgs)               | `emacs` (inside `with pkgs;`)  |
| `Identifier` | Leaf: bare reference to a binding            | `myPythonEnv`                  |
| `FnCall`     | Function application: callee + args          | `fetchFromGitHub { ... }`      |
| `FnDef`      | Lambda: params + body                        | `p: with p; [ ... ]`           |
| `LetIn`      | Let-binding block: bindings + body           | `let x = ...; in ...`          |
| `Binding`    | Name-value pair inside LetIn                 | `x = expr;`                    |
| `With`       | With-scope: namespace + body                 | `with pkgs; [ ... ]`           |
| `Import`     | File import                                  | `import ./file.nix`            |
| `Interpolation` | String with embedded expressions          | `"${pkgs.bash}/bin/bash"`      |
| `MultilineString` | Indented string literal                 | `'' ... ''`                    |
| `Conditional`| If-then-else                                 | `if x then y else z`           |
| `BinOp`      | Binary operation (// , ++ , etc.)            | `a // b`                       |
| `Inherit`    | Inherit from scope                           | `inherit foo bar;`             |
| `RawNix`     | Verbatim Nix source (escape hatch)           | emitted as-is                  |

This is not an exhaustive Nix parser. It covers the constructs that actually
appear in NixOS configurations. `RawNix` exists as an escape hatch for
anything not yet modeled, but the goal is to minimize its use.

### 2.3 Why not store Nix source text

Storing `value = "pkgs.python3.withPackages (p: ...)"` as an opaque string
is equivalent to a compiler storing programs as text — it gives up all
ability to analyze, transform, or compose.

Storing the AST instead means:

- **Query:** "Find every `fetchFromGitHub` call" — walk tree for
  `FnCall` nodes where callee = `fetchFromGitHub`.
- **Rename:** Change package `emacs` to `emacs30` — update one leaf node.
  Every backend re-serializes correctly.
- **Validate:** Before generating, check that every `Identifier` node
  resolves to a `Binding` or a known builtin.
- **Diff:** Structural diff between configs, not text diff.
- **Compose:** Merge two project subtrees by tree union, with typed conflict
  detection ("both set `services.openssh.enable` but to different values").

### 2.4 Attribute paths are a tree, not a string

This:

```
services.openssh.enable
```

Is already:

```
services
  openssh
    enable
```

The current system flattens it into a string because SQL likes flat keys.
But TempleDB doesn't have to. The `config_nodes` table stores the actual
tree with `parent_id` pointers. Exactly like a filesystem. Exactly like a
DOM. Exactly like a syntax tree.

The generator walks the tree. Attribute paths are a derived property, not
a stored one.

### 2.5 Ownership is subtrees

Each node can be owned by zero or more projects via a join table. Ownership
propagates: if project `bza` owns the `services.postgresql` AttrSet node,
it implicitly owns all descendants unless another project explicitly claims
a child.

```
Project: bza
  owns -> services.postgresql          (AttrSet)
            enable (Bool: true)         inherited ownership
            package (Package: ...)      inherited ownership

Project: system_config
  owns -> services.openssh             (AttrSet)
  owns -> home.packages.emacs          (Package leaf)
```

**Deployment = subtree union.** To build the full config for a host:

1. Collect all project subtrees assigned to that host.
2. Union them. AttrSet children merge by name. Lists concatenate.
3. Detect conflicts: two projects setting the same leaf to different values
   for the same host (see §5.1 for precise rules).
4. Walk the merged tree through the backend. Emit files.

**Removal is clean.** `templedb config remove-project bza` deletes all nodes
owned exclusively by `bza`. Shared nodes (owned by multiple projects) keep
the other owners. Regenerate. Done.

### 2.6 Host inheritance

Hosts form an inheritance chain. A base host defines common config. Specific
hosts extend it with overrides.

```
config_hosts:
  id=1  name="base"         parent_id=NULL
  id=2  name="zMothership2" parent_id=1
  id=3  name="zMothership3" parent_id=1
  id=4  name="zStation"     parent_id=1
```

Each node has a `host_id`. Nodes with `host_id=NULL` apply everywhere.
Nodes on a child host override nodes at the same tree position from the
parent.

Resolution order (most specific wins):
1. `zMothership2` nodes
2. `base` nodes
3. `NULL` (global) nodes

This replaces the current `mkHost` pattern in `flake.nix` and the
per-host .nix files. The generator produces per-host outputs from the
resolved tree.

### 2.7 The RawNix escape hatch

Some Nix constructs are rare or deeply idiomatic. Rather than model every
possible Nix expression, a `RawNix` leaf node stores verbatim Nix source:

```
Node: RawNix
value: "lib.concatStringsSep \",\" [ \"reconnect\" ... ]"
```

The generator emits it verbatim. It's opaque — can't be queried or
transformed. But it exists so nothing is ever "too complex to store."

The goal is to progressively move things *out* of `RawNix` as the AST
node types are extended. `RawNix` usage is a measurable metric — fewer is
better.

---

## 3. This Is a Compiler

The architecture mirrors a real compiler:

```
config_nodes (DB)        source code
       |
       v
  Resolver               linker (host inheritance, project union)
       |
       v
  Merged AST             intermediate representation
       |
       v
  Analyzer               semantic analysis (validation, type checking)
       |
       v
  Backend                code generator
       |
   +---+---+---+
   |       |       |
  Nix    JSON   (future)    target languages
```

Exactly how GCC compiles. Exactly how Rust compiles. Exactly how SQL
query planners work.

The key insight: Nix is one **backend**, not the representation. The IR
is a typed graph. The graph can be serialized to any format that expresses
the same concepts.

---

## 4. Schema

### 4.1 Tables

```sql
-- Every piece of configuration is a node in a tree.
CREATE TABLE config_nodes (
    id          INTEGER PRIMARY KEY,
    parent_id   INTEGER REFERENCES config_nodes(id) ON DELETE CASCADE,
    name        TEXT,                -- child name within parent (NULL for list items / positional args)
    sort_order  INTEGER DEFAULT 0,   -- ordering for list items and sibling display

    node_type   TEXT NOT NULL
                CHECK(node_type IN (
                    'AttrSet', 'List',
                    'Bool', 'Int', 'String', 'Path', 'Package', 'Identifier',
                    'FnCall', 'FnDef', 'LetIn', 'Binding', 'With',
                    'Import', 'Interpolation', 'MultilineString',
                    'Conditional', 'BinOp', 'Inherit',
                    'RawNix'
                )),

    -- Leaf value (NULL for interior nodes like AttrSet, List)
    value       TEXT,

    -- For FnCall: which function is being called
    callee      TEXT,

    -- For BinOp: which operator
    operator    TEXT CHECK(operator IN ('//', '++', '+', '||', '&&', NULL)),

    -- Scope: which output file this root subtree belongs to
    -- Only meaningful on root-level nodes; children inherit.
    scope       TEXT CHECK(scope IN ('system', 'home', 'flake', NULL)),

    -- Host targeting (NULL = all hosts)
    host_id     INTEGER REFERENCES config_hosts(id) ON DELETE CASCADE,

    -- Enabled flag (disabled nodes + descendants excluded from generation)
    enabled     BOOLEAN DEFAULT 1,

    -- Metadata
    description TEXT,
    category    TEXT,                -- for grouping in output ("Cli Utilities")
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Within an AttrSet parent, named children must be unique per host.
    -- NULL names (list items, positional args) are exempt — SQLite treats
    -- each NULL as distinct in UNIQUE constraints, so multiple list children
    -- with name=NULL are allowed. This is intentional, not accidental.
    UNIQUE(parent_id, name, host_id)
);

CREATE INDEX idx_config_nodes_parent ON config_nodes(parent_id);
CREATE INDEX idx_config_nodes_type ON config_nodes(node_type);
CREATE INDEX idx_config_nodes_host ON config_nodes(host_id);

-- Which project owns which node
CREATE TABLE config_node_owners (
    node_id     INTEGER REFERENCES config_nodes(id) ON DELETE CASCADE,
    project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    PRIMARY KEY (node_id, project_id)
);

-- Host definitions and inheritance
CREATE TABLE config_hosts (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,          -- "zMothership2"
    parent_id   INTEGER REFERENCES config_hosts(id),
    hw_config   TEXT,                          -- relative path to hardware-configuration.nix
    description TEXT
);

-- Root entry points per scope (the generator starts walking here)
CREATE TABLE config_roots (
    id          INTEGER PRIMARY KEY,
    scope       TEXT NOT NULL UNIQUE
                CHECK(scope IN ('system', 'home', 'flake')),
    node_id     INTEGER NOT NULL REFERENCES config_nodes(id),
    description TEXT
);
```

### 4.2 Tree structure examples

**Root structure per scope.**
Each scope has a single root node registered in `config_roots`. Top-level
attrs like `services`, `home`, `networking` are children of this root.

```
id=0   parent=NULL  name=NULL         type=AttrSet  scope="system"   ← config_roots.system
id=1   parent=0     name="services"   type=AttrSet
...
id=9   parent=NULL  name=NULL         type=AttrSet  scope="home"     ← config_roots.home
id=10  parent=9     name="home"       type=AttrSet
...
```

If a scope uses `let...in`, the root is a `LetIn` node. The `AttrSet` body
is a child of the `LetIn`:

```
id=100 parent=NULL  name=NULL         type=LetIn    scope="home"     ← config_roots.home
id=101 parent=100   name="myPyEnv"    type=Binding                   ← let binding
...
id=109 parent=100   name=NULL         type=AttrSet                   ← body (the { home = ...; })
id=110 parent=109   name="home"       type=AttrSet
...
```

**Simple boolean: `services.openssh.enable = true`**

```
id=0   parent=NULL  name=NULL         type=AttrSet  scope="system"
id=1   parent=0     name="services"   type=AttrSet
id=2   parent=1     name="openssh"    type=AttrSet
id=3   parent=2     name="enable"     type=Bool     value="true"
```

**Package list: `home.packages = with pkgs; [ emacs nodejs ]`**

In Nix, `with pkgs;` wraps the *value* of the `packages` attribute, not
the attribute itself. The tree models this: `packages` is an AttrSet child
named "packages", whose value is a `With` node containing a `List`:

```
id=9   parent=NULL  name=NULL         type=AttrSet  scope="home"
id=10  parent=9     name="home"       type=AttrSet
id=11  parent=10    name="packages"   type=With     callee="pkgs"
id=12  parent=11    name=NULL         type=List
id=13  parent=12    name=NULL         type=Package  value="emacs"      sort=0
id=14  parent=12    name=NULL         type=Package  value="nodejs"     sort=1
```

Note: the `With` node is the *value* of the "packages" child. The backend
emits `packages = with pkgs; [ ... ];` because the `With` node is named
"packages" within its parent AttrSet.

**Let binding: `let myPythonEnv = pkgs.python3.withPackages (...); in { ... }`**

The `LetIn` node is the scope root. Its children are `Binding` nodes (the
let-bound names) plus one non-Binding child (the body expression):

```
id=20  parent=NULL  name=NULL          type=LetIn    scope="home"
id=21  parent=20    name="myPythonEnv" type=Binding
id=22  parent=21    name=NULL          type=FnCall   callee="pkgs.python3.withPackages"
id=23  parent=22    name=NULL          type=FnDef
id=24  parent=23    name="params"      type=String   value="p"
id=25  parent=23    name="body"        type=With     callee="p"
id=26  parent=25    name=NULL          type=List
id=27  parent=26    name=NULL          type=Identifier  value="ipython"    sort=0
id=28  parent=26    name=NULL          type=Identifier  value="jupyterlab" sort=1
id=29  parent=20    name=NULL          type=AttrSet                        ← body of let...in
```

**Derivation: `pkgs.stdenv.mkDerivation { pname = "voiceai"; ... }`**

```
id=30  parent=<binding>  name=NULL        type=FnCall   callee="pkgs.stdenv.mkDerivation"
id=31  parent=30         name=NULL        type=AttrSet
id=32  parent=31         name="pname"     type=String   value="voiceai"
id=33  parent=31         name="version"   type=String   value="0.1.0"
id=34  parent=31         name="src"       type=Path     value="./whisper_dictation"
id=35  parent=31         name="buildInputs" type=List
id=36  parent=35         name=NULL        type=Identifier  value="voiceAIPython"  sort=0
id=37  parent=35         name=NULL        type=Identifier  value="pkgs.portaudio" sort=1
```

**String interpolation: `"${pkgs.bash}/bin/bash"`**

```
id=40  parent=<...>  name=NULL   type=Interpolation
id=41  parent=40     name=NULL   type=Identifier  value="pkgs.bash"  sort=0
id=42  parent=40     name=NULL   type=String      value="/bin/bash"  sort=1
```

**Shell script: `programs.bash.initExtra = '' eval "$(direnv hook bash)" ... ''`**

```
id=50  parent=<bash>  name="initExtra"  type=MultilineString
       value="eval \"$(direnv hook bash)\"\nexport EDITOR=emacs\n..."
```

When the script contains Nix interpolations (`${pkgs.xorg.xset}`), it
becomes an `Interpolation` with `MultilineString` and `Identifier` children:

```
id=50  parent=<...>  name="initExtra"  type=Interpolation
id=51  parent=50     name=NULL         type=MultilineString  value="..."  sort=0
id=52  parent=50     name=NULL         type=Identifier  value="pkgs.xorg.xset"  sort=1
id=53  parent=50     name=NULL         type=MultilineString  value="/bin/xset..." sort=2
```

---

## 5. Composition

### 5.1 Subtree union

When building a host's configuration, the compiler collects all enabled
nodes for that host and merges them:

```
Project A contributes:          Project B contributes:
  services                        services
    openssh                         postgresql
      enable: true                    enable: true
                                      package: postgresql_16
  home                            home
    packages                        packages
      emacs                           nodejs
      ripgrep                         typescript
```

Union result:

```
services
  openssh
    enable: true          (from A)
  postgresql
    enable: true          (from B)
    package: postgresql_16 (from B)
home
  packages
    emacs                 (from A)
    ripgrep               (from A)
    nodejs                (from B)
    typescript            (from B)
```

**Rules:**
- `AttrSet` children merge by name. No conflict unless both projects define
  the same named child **for the same host**.
- `List` children concatenate (ordered by `sort_order`, then by source
  project).
- Leaf conflicts (two projects set same leaf to different values **for the
  same `host_id`**) are **errors** reported before generation. The user must
  resolve by adjusting ownership or adding a host override.

**Not a conflict:** two projects (or the same project) setting the same leaf
to different values for *different hosts*. That's the normal case — the
`UNIQUE(parent_id, name, host_id)` constraint allows it. The resolver picks
the right value per host at generation time.

Example — both hosts have postgresql, configured differently:

```
Global (host_id=NULL):
  services.postgresql.enable = true               shared base

zMothership2 (host_id=2):
  services.postgresql.settings.max_connections = 20       dev box
  services.postgresql.settings.shared_buffers = "128MB"

zMothership3 (host_id=3):
  services.postgresql.settings.max_connections = 500      production
  services.postgresql.settings.shared_buffers = "4GB"
  services.postgresql.settings.wal_level = "replica"
```

When generating for zMothership2: `enable = true` (global) + `max_connections
= 20`, `shared_buffers = "128MB"` (host 2). Host 3 nodes are invisible.

When generating for zMothership3: `enable = true` (global) + `max_connections
= 500`, `shared_buffers = "4GB"`, `wal_level = "replica"` (host 3). Host 2
nodes are invisible.

No conflict. Same tree position, different `host_id`. This is the normal
way to express per-machine configuration.

**Interior nodes and host_id.** Host-specific leaf nodes can hang off
global (`host_id=NULL`) interior nodes. The resolver walks the tree and,
at each level, checks if a host-specific version of that child exists. If
so, it takes precedence. Interior AttrSet nodes do NOT need to be
duplicated per host — only the leaves (or subtrees) that actually differ
need host-specific versions. In the postgresql example above,
`services` and `services.postgresql` and `services.postgresql.settings`
are all `host_id=NULL`. Only `max_connections` and `shared_buffers` have
per-host rows.

### 5.2 Host resolution

```
Global (host_id=NULL):
  services.openssh.settings.PermitRootLogin = "no"

zMothership3 (host_id=3):
  services.openssh.settings.PermitRootLogin = "yes"
```

The compiler resolves per-host. For `zMothership3`, the override wins.
For all other hosts, the global value applies.

```sql
-- Effective node at a tree position for a given host
-- Most specific host_id wins, NULL is least specific
ORDER BY
  CASE
    WHEN host_id = :target_host THEN 0
    WHEN host_id = :parent_host THEN 1
    WHEN host_id IS NULL THEN 2
  END
LIMIT 1
```

---

## 6. Generation Pipeline

### 6.1 Stages

```
config_nodes (DB)
      |
      v
  Resolver         host inheritance, project union, conflict detection
      |
      v
  Merged AST       in-memory tree of typed Python objects
      |
      v
  Analyzer         validation: unresolved identifiers, type mismatches,
      |             unused bindings, duplicate list items
      v
  Backend          serialize to target format
      |
   +--+--+
   |     |
  Nix   JSON
```

### 6.2 Resolver

Takes a target host and produces a single merged AST:

1. **Collect** all enabled `config_nodes` where `host_id` matches the target
   host's inheritance chain (or is NULL).
2. **Deduplicate** by tree position: if the same `(parent_id, name)` exists
   at multiple host levels, keep the most specific.
3. **Union** across projects: merge AttrSet children, concatenate List
   children.
4. **Report conflicts** where two projects define different leaf values at
   the same position.

Output: a single rooted tree per scope (system, home, flake).

### 6.3 Nix backend

The Nix backend walks the resolved AST and emits Nix syntax:

```python
def emit(node: ConfigNode) -> str:
    match node.node_type:
        case 'AttrSet':
            children = '\n'.join(
                f'{c.name} = {emit(c)};' for c in node.children
            )
            return f'{{\n{indent(children)}\n}}'
        case 'List':
            items = '\n'.join(emit(c) for c in node.children)
            return f'[\n{indent(items)}\n]'
        case 'Bool':
            return node.value
        case 'Int':
            return node.value
        case 'String':
            return f'"{escape(node.value)}"'
        case 'Package':
            return node.value           # bare ident inside with pkgs;
        case 'Identifier':
            return node.value           # bare reference
        case 'Path':
            return node.value           # ./relative/path
        case 'FnCall':
            args = emit(node.children[0])
            return f'{node.callee} {args}'
        case 'FnDef':
            params = node.get_child('params')
            body = node.get_child('body')
            return f'{params.value}: {emit(body)}'
        case 'LetIn':
            bindings = [c for c in node.children if c.node_type == 'Binding']
            body = [c for c in node.children if c.node_type != 'Binding'][0]
            b_str = '\n'.join(f'{b.name} = {emit(b.children[0])};'
                              for b in bindings)
            return f'let\n{indent(b_str)}\nin\n{emit(body)}'
        case 'With':
            body = emit(node.children[0])
            return f'with {node.callee}; {body}'
        case 'MultilineString':
            return f"''\n{indent(node.value)}\n''"
        case 'Interpolation':
            parts = []
            for c in node.children:
                if c.node_type == 'Identifier':
                    parts.append(f'${{{c.value}}}')
                elif c.node_type in ('String', 'MultilineString'):
                    parts.append(c.value)
                else:
                    parts.append(emit(c))
            return f'"{"".join(parts)}"'
        case 'Conditional':
            cond = emit(node.get_child('cond'))
            then = emit(node.get_child('then'))
            else_ = emit(node.get_child('else'))
            return f'if {cond} then {then} else {else_}'
        case 'BinOp':
            left = emit(node.children[0])
            right = emit(node.children[1])
            return f'{left} {node.operator} {right}'
        case 'Inherit':
            names = ' '.join(c.value for c in node.children)
            return f'inherit {names};'
        case 'Import':
            return f'import {node.value}'
        case 'RawNix':
            return node.value           # verbatim
```

The backend also handles file-level scaffolding:

- **`home.nix`:** Emits `{ config, pkgs, lib, ... }:` header, `let...in`
  block from `LetIn` nodes scoped to `home`, then the home AttrSet body.
- **`configuration.nix`:** Same pattern for system scope. Extra args
  (`templedb`, `bza`) are derived from flake inputs.
- **`flake.nix`:** Emits inputs from flake scope nodes, `mkHost` from a
  template, per-host outputs from `config_hosts`.

These templates are in the backend code (Python). They define the *shape* of
the output files. The data comes from the AST.

### 6.4 JSON backend

Emits the resolved tree as JSON. Useful for debugging, API responses,
and diffing:

```json
{
  "scope": "system",
  "type": "AttrSet",
  "children": {
    "services": {
      "type": "AttrSet",
      "children": {
        "openssh": {
          "type": "AttrSet",
          "children": {
            "enable": { "type": "Bool", "value": "true", "owner": "system_config" }
          }
        }
      }
    }
  }
}
```

### 6.5 Future backends

The same AST can emit:

- **Docker Compose** — `Package` nodes -> image deps, service AttrSets ->
  compose services.
- **Terraform** — infrastructure nodes -> HCL resources.
- **Ansible** — service enables -> playbook tasks.
- **Kubernetes** — service config -> manifests.

This is not a near-term goal, but the architecture supports it without
changing the data model.

---

## 7. Semantic Analysis

Once configuration is an AST, the compiler can perform analysis before
generation.

### 7.1 Validation passes

- **Unresolved identifiers:** Every `Identifier` node must resolve to a
  `Binding` in an ancestor `LetIn`, a known `pkgs.*` attribute, or a
  function parameter.
- **Type checking:** `enable` attrs should be `Bool`. Port lists should
  contain `Int`. Package lists should contain `Package` or `Identifier`.
- **Unused bindings:** `LetIn` bindings that nothing references.
- **Duplicate list items:** Same package appears twice in `home.packages`.
- **Conflict detection:** Two projects set the same leaf differently.

### 7.2 Structural queries

```sql
-- All packages across all projects
SELECT cn.value, p.slug
FROM config_nodes cn
JOIN config_node_owners co ON cn.id = co.node_id
JOIN projects p ON co.project_id = p.id
WHERE cn.node_type = 'Package';

-- All enabled services
SELECT parent.name AS service_name
FROM config_nodes cn
JOIN config_nodes parent ON cn.parent_id = parent.id
JOIN config_nodes grandparent ON parent.parent_id = grandparent.id
WHERE cn.name = 'enable' AND cn.value = 'true'
  AND grandparent.name = 'services';

-- All FnCall nodes (every derivation, fetchFromGitHub, etc.)
SELECT cn.callee, cn.id
FROM config_nodes cn
WHERE cn.node_type = 'FnCall';

-- Nodes with no project owner
SELECT cn.id, cn.name, cn.node_type
FROM config_nodes cn
LEFT JOIN config_node_owners co ON cn.id = co.node_id
WHERE co.node_id IS NULL
  AND cn.node_type NOT IN ('AttrSet', 'List');

-- Reconstruct full attr path for any node
WITH RECURSIVE path(id, name, parent_id, depth) AS (
    SELECT id, name, parent_id, 0 FROM config_nodes WHERE id = :target_id
    UNION ALL
    SELECT cn.id, cn.name, cn.parent_id, p.depth + 1
    FROM config_nodes cn JOIN path p ON cn.id = p.parent_id
)
SELECT group_concat(name, '.') FROM (
    SELECT name FROM path WHERE name IS NOT NULL ORDER BY depth DESC
);
```

### 7.3 Structural diff

Comparing two configs (before/after, or between hosts) is a tree diff:

```
templedb config diff --host zMothership2 --host zMothership3

+ services.postgresql.enable = true      (zMothership3 only)
~ hardware.nvidia.open = false -> true   (value differs)
- wifi.enable = true                     (zMothership2 only)
```

---

## 8. CLI

```bash
# Tree visualization
templedb config tree                     # print full config tree
templedb config tree services            # print subtree
templedb config tree --host zMothership2 # resolved for a host
templedb config tree --project bza       # only nodes owned by bza
templedb config tree --raw-nix-count     # count escape hatch usage

# Node operations
templedb config set services.openssh.enable true
templedb config set home.packages.nodejs --type package --project bza
templedb config set programs.bash.initExtra --type multiline --file ./bash-init.sh
templedb config unset services.osquery.enable
templedb config enable services.tailscale
templedb config disable services.tailscale
templedb config move home.packages.nodejs --to-project bza

# Queries
templedb config query "FnCall[callee=fetchFromGitHub]"
templedb config query "Package"              # all packages
templedb config query "Package" --project bza
templedb config owners services.postgresql   # which projects own this?
templedb config orphans                      # nodes with no project owner

# Hosts
templedb config host list
templedb config host add zStation --parent base
templedb config host diff zMothership2 zMothership3

# Generation
templedb config generate                     # emit all .nix files
templedb config generate --host zMothership2 # for specific host
templedb config generate --dry-run           # preview without writing
templedb config generate --backend json      # JSON export
templedb config diff                         # show what changed vs current files

# Project integration
templedb config add-project bza              # import bza's config requirements
templedb config remove-project bza           # remove bza-owned nodes
templedb config project-impact bza           # what changes if bza is removed?
```

---

## 9. GUI

The `/config` dashboard shows:

- **Tree view** — collapsible tree of all config nodes, color-coded by
  owning project. Click to expand/edit. Inline CRUD.
- **Host matrix** — columns per host, rows per config path. Shows which
  hosts have overrides and their values.
- **Conflict panel** — any merge conflicts from multi-project composition.
- **Generation log** — last generation timestamp, diff from previous.
- **RawNix audit** — list of `RawNix` nodes with candidates for promotion
  to typed nodes. Tracks progress over time.

---

## 10. Migration Path

### 10.1 From existing `system_config` keys

The existing `system_config` table has ~80 keys encoding the same
information this spec models as a tree. Migration:

1. Parse each `nixos.attr.*` key into an AttrSet chain + typed leaf.
2. Parse each `nixos.pkg.user.*` key into a `Package` node under
   `home.packages`.
3. Parse each `nixos.pkg.system.*` key into a `Package` node under
   `environment.systemPackages`.
4. Parse each `nixos.alias.*` key into a `String` node under
   `programs.bash.shellAliases`.
5. Parse `nixos.firewall.tcp` JSON array into `Int` nodes under
   `networking.firewall.allowedTCPPorts`.
6. Parse `nixos.flake.input.*` into the flake inputs subtree.
7. Parse `nixos.host.*` into `config_hosts` rows.

### 10.2 From existing .nix files

The hand-edited portions of `configuration.nix`, `home.nix`, and `flake.nix`
need to be imported into the AST. One-time semi-automated process:

1. **Simple attrs** — already in the DB as `nixos.attr.*`. Direct migration.
2. **Package lists** — already in the DB. Direct migration.
3. **Let bindings** — parse each `let` binding into `LetIn` -> `Binding` ->
   expression subtree. Most are `FnCall` nodes.
4. **Complex nested config** (wireplumber, sudo rules, actkbd, systemd
   mounts) — start as `RawNix` nodes. Progressively decompose into typed
   nodes over time.
5. **`mkHost` / flake structure** — becomes generator template logic, not
   stored data.
6. **File references** (`./xmonad.hs`, `./secrets.yaml`) — become `Path`
   nodes. The files themselves already live in TempleDB's `project_files`.

### 10.3 Phased rollout

**Phase 1: Tables + seed from existing keys.**
Create `config_nodes`, `config_node_owners`, `config_hosts`, `config_roots`.
Migrate existing `system_config` keys into the tree. Generator reads from
`config_nodes` instead of `system_config` but still produces the same
marker-section output.

**Phase 2: Import hand-written nix.**
Import the non-managed portions of configuration.nix and home.nix into the
tree. Complex expressions start as `RawNix`. Generator now produces
*complete* files — no more marker sections and hand-edited regions.

**Phase 3: Fully generated.**
Nix files are pure build artifacts. Delete the static .nix copies from the
`system_config` project's file_contents. `templedb config generate` is the
only way to produce them.

**Phase 4: RawNix reduction.**
Progressively decompose `RawNix` nodes into typed AST nodes. Measured by
`templedb config tree --raw-nix-count`. Goal: zero.

---

## 11. Relationship to Existing TempleDB

### 11.1 project_files

Files like `xmonad.hs`, `secrets.yaml`, shell scripts referenced by
`Path` nodes live in TempleDB's existing `project_files` / `file_contents`
tables. The config compiler doesn't duplicate them — `Path` nodes reference
them by relative path within the project.

### 11.2 code_symbols

The `code_symbols` table tracks functions, classes, and their call
relationships across source code. The config compiler's `FnCall` and
`Identifier` nodes are analogous — they track references within
configuration. Future work could unify these: a `code_symbols` entry for
`myPythonEnv` linking to config nodes that reference it.

### 11.3 nix_store_paths / nix_generations

The nix store integration tracks what's *built*. The config compiler tracks
what's *declared*. Together they close the loop:

```
declared config -> generated .nix -> built store paths -> deployed generations
```

Each step is in the DB.

### 11.4 fleet deployment

Fleet deployment builds and transfers closures to remote machines. With
per-host config resolution, the compiler generates host-specific .nix files
and hands them to the fleet deployer. The host inheritance tree in
`config_hosts` replaces the per-host file convention.

### 11.5 VCS

Config node changes can be committed to TempleDB's VCS like any other
project data. `templedb vcs commit system_config -m "enable tailscale"`
captures the tree state. Diffs show structural changes to config nodes, not
text diffs of generated files.

---

## 12. What This Is Not

- **Not a Nix evaluator.** We don't evaluate expressions, resolve package
  versions, or compute hashes. Nix does that after we generate files.

- **Not a Nix parser.** We don't parse arbitrary .nix files. The one-time
  migration uses targeted extraction. After that, all edits go through
  the AST via CLI/GUI.

- **Not a replacement for the Nix module system.** NixOS modules do merging,
  type-checking, and option declaration at build time. We do similar things
  at a higher level (project ownership, host inheritance), but the generated
  .nix files still go through the normal module system.

---

## 13. Open Questions

1. **FnDef depth.** Lambda bodies can be arbitrarily complex. How deep do we
   model before falling back to `RawNix`? Proposed: model params and the
   top-level body. If the body is complex, decompose recursively. Measure
   depth distribution empirically.

2. **`lib.*` functions.** `lib.mkDefault`, `lib.mkForce`,
   `lib.concatStringsSep` are pervasive. Model as `FnCall` with
   `callee = "lib.mkDefault"`? Or special node types for the common ones?

3. **Module arguments.** Each .nix file starts with `{ config, pkgs, lib,
   ... }:`. These are implicit — the backend knows to emit them. But extra
   arguments (`templedb`, `bza`) come from flake inputs. Should they be
   tracked as data so the backend knows which to include?

4. **Flake lock.** `flake.lock` pins input revisions. Store as config nodes?
   Or keep as a file since it's managed by `nix flake update`?

5. **Incremental generation.** Can we regenerate only files affected by a
   change? For 3-4 files this may not matter, but worth considering for
   larger configs.

6. **Two-way sync.** If someone edits a generated .nix file directly, detect
   and import changes? Or treat generated files as strictly read-only
   (recommended)?

7. **Nix string escaping.** Multiline strings, interpolation, and special
   characters need careful handling in the backend. Define a test suite of
   round-trip cases: AST -> Nix text -> (nix-instantiate parse) -> verify.

8. **Category theory connection.** Project composition as a coproduct
   (pushout) of labeled trees. Host inheritance as a pullback. The merge
   operation is a colimit. Worth formalizing? Would enable proving
   properties like "composition is associative and commutative for
   non-conflicting subtrees."
