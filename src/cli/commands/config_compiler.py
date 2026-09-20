"""CLI commands for the configuration compiler.

templedb config-ast {tree, set, unset, enable, disable, generate, seed, host, query, owners, orphans, stats}
"""

import json
import sys
from typing import Optional

from services.config_compiler import ConfigCompilerService


def register(cli):
    """Register config-ast subcommands."""
    parser = cli.register_command('config-ast', handle, help_text='Configuration compiler (AST-based system config)')
    sub = parser.add_subparsers(dest='config_ast_command')

    # tree
    p = sub.add_parser('tree', help='Print config tree')
    p.add_argument('path', nargs='?', help='Subtree path (e.g. services.openssh)')
    p.add_argument('--scope', default='system', choices=['system', 'home', 'flake'])
    p.add_argument('--host', help='Resolve for a specific host')
    p.add_argument('--project', help='Only show nodes owned by project')
    p.add_argument('--ids', action='store_true', help='Show node IDs')
    p.add_argument('--json', action='store_true', dest='as_json', help='JSON output')
    p.add_argument('--raw-nix-count', action='store_true', help='Count RawNix nodes')

    # set
    p = sub.add_parser('set', help='Set a config value')
    p.add_argument('path', help='Attr path (e.g. services.openssh.enable)')
    p.add_argument('value', help='Value to set')
    p.add_argument('--scope', default='system', choices=['system', 'home', 'flake'])
    p.add_argument('--type', default='String', dest='node_type',
                   choices=['Bool', 'Int', 'String', 'Path', 'Package', 'RawNix', 'MultilineString'])
    p.add_argument('--host', help='Host-specific value')
    p.add_argument('--project', help='Owning project slug')
    p.add_argument('--category', help='Category for grouping')
    p.add_argument('--file', dest='from_file', help='Read value from file')

    # unset
    p = sub.add_parser('unset', help='Remove a config node')
    p.add_argument('path', help='Attr path to remove')
    p.add_argument('--scope', default='system', choices=['system', 'home', 'flake'])

    # enable/disable
    p = sub.add_parser('enable', help='Enable a config node')
    p.add_argument('path', help='Attr path')
    p.add_argument('--scope', default='system', choices=['system', 'home', 'flake'])

    p = sub.add_parser('disable', help='Disable a config node')
    p.add_argument('path', help='Attr path')
    p.add_argument('--scope', default='system', choices=['system', 'home', 'flake'])

    # generate
    p = sub.add_parser('generate', help='Generate .nix files from AST')
    p.add_argument('--host', help='Generate for specific host')
    p.add_argument('--scope', choices=['system', 'home', 'flake'], help='Only this scope')
    p.add_argument('--dry-run', action='store_true', help='Print without writing')
    p.add_argument('--backend', default='nix', choices=['nix', 'json'])

    # seed
    p = sub.add_parser('seed', help='Seed config_nodes from existing system_config keys')
    p.add_argument('--dry-run', action='store_true', help='Show what would be seeded')

    # host
    p = sub.add_parser('host', help='Manage hosts')
    host_sub = p.add_subparsers(dest='host_command')
    host_sub.add_parser('list', help='List hosts')
    hp = host_sub.add_parser('add', help='Add a host')
    hp.add_argument('name')
    hp.add_argument('--parent', help='Parent host name')

    # query
    p = sub.add_parser('query', help='Query config nodes')
    p.add_argument('node_type', nargs='?', help='Node type to find (e.g. Package, FnCall)')
    p.add_argument('--callee', help='FnCall callee filter')
    p.add_argument('--project', help='Filter by project')

    # owners
    p = sub.add_parser('owners', help='Show owners of a config path')
    p.add_argument('path', help='Attr path')
    p.add_argument('--scope', default='system', choices=['system', 'home', 'flake'])

    # import
    p = sub.add_parser('import', help='Import a .nix file into config_nodes')
    p.add_argument('file', help='Path to .nix file')
    p.add_argument('--scope', required=True, choices=['system', 'home', 'flake'],
                   help='Which scope to import into')
    p.add_argument('--replace', action='store_true',
                   help='Replace existing nodes in this scope (default: error if non-empty)')
    p.add_argument('--project', help='Assign all leaf nodes to this project')
    p.add_argument('--host', help='Import as an overlay for a specific host. '
                                  'Deep-merges into existing shared (host_id=NULL) AttrSets, '
                                  'tagging only new leaves/subtrees with the host.')

    # import-all
    p = sub.add_parser('import-all', help='Import configuration.nix, home.nix, flake.nix from a directory')
    p.add_argument('dir', help='Directory containing the .nix files')
    p.add_argument('--project', default='system_config', help='Owning project slug')

    # orphans
    sub.add_parser('orphans', help='Find nodes with no project owner')

    # stats
    sub.add_parser('stats', help='Show config tree statistics')


def handle(args):
    """Handle config-ast subcommands."""
    svc = ConfigCompilerService()
    cmd = args.config_ast_command

    if cmd == 'tree':
        return _handle_tree(svc, args)
    elif cmd == 'set':
        return _handle_set(svc, args)
    elif cmd == 'unset':
        return _handle_unset(svc, args)
    elif cmd in ('enable', 'disable'):
        return _handle_toggle(svc, args, cmd == 'enable')
    elif cmd == 'generate':
        return _handle_generate(svc, args)
    elif cmd == 'seed':
        return _handle_seed(svc, args)
    elif cmd == 'host':
        return _handle_host(svc, args)
    elif cmd == 'query':
        return _handle_query(svc, args)
    elif cmd == 'owners':
        return _handle_owners(svc, args)
    elif cmd == 'import':
        return _handle_import(svc, args)
    elif cmd == 'import-all':
        return _handle_import_all(svc, args)
    elif cmd == 'orphans':
        return _handle_orphans(svc)
    elif cmd == 'stats':
        return _handle_stats(svc)
    else:
        print("Usage: templedb config-ast {tree|set|unset|enable|disable|generate|seed|host|query|owners|orphans|stats}")
        return 1


def _host_id(svc, host_name):
    if not host_name:
        return None
    h = svc.get_host(host_name)
    if not h:
        print(f"Host '{host_name}' not found", file=sys.stderr)
        sys.exit(1)
    return h['id']


def _handle_tree(svc, args):
    if args.raw_nix_count:
        s = svc.stats()
        print(f"RawNix nodes: {s['raw_nix_count']} / {s['total_nodes']} total")
        return 0

    tree = svc.resolve(args.scope, args.host)

    if args.path:
        for part in args.path.split('.'):
            child = tree.get_child(part)
            if not child:
                print(f"Path '{args.path}' not found in {args.scope} scope", file=sys.stderr)
                return 1
            tree = child

    if args.as_json:
        print(json.dumps(svc.emit_json(tree), indent=2))
    else:
        print(svc.print_tree(tree, show_ids=args.ids))
    return 0


def _handle_set(svc, args):
    value = args.value
    if args.from_file:
        with open(args.from_file) as f:
            value = f.read()

    host_id = _host_id(svc, args.host)
    node_id = svc.set_leaf(
        scope=args.scope, path=args.path, value=value,
        node_type=args.node_type, host_id=host_id,
        category=args.category, project_slug=args.project
    )
    display_val = value[:60] + ('...' if len(value) > 60 else '')
    print(f"Set {args.scope}.{args.path} = {display_val} (node {node_id})")
    return 0


def _handle_unset(svc, args):
    node = svc.find_by_path(args.scope, args.path)
    if not node:
        print(f"Not found: {args.scope}.{args.path}", file=sys.stderr)
        return 1
    svc.remove_node(node['id'])
    print(f"Removed {args.scope}.{args.path}")
    return 0


def _handle_toggle(svc, args, enable):
    node = svc.find_by_path(args.scope, args.path)
    if not node:
        print(f"Not found: {args.scope}.{args.path}", file=sys.stderr)
        return 1
    if enable:
        svc.enable_node(node['id'])
        print(f"Enabled {args.scope}.{args.path}")
    else:
        svc.disable_node(node['id'])
        print(f"Disabled {args.scope}.{args.path}")
    return 0


def _handle_generate(svc, args):
    scopes = [args.scope] if args.scope else ['system', 'home', 'flake']
    for scope in scopes:
        tree = svc.resolve(scope, args.host)
        if args.backend == 'json':
            output = json.dumps(svc.emit_json(tree), indent=2)
        else:
            output = svc.emit_nix(tree)

        print(f"--- {scope} ---")
        print(output)
        print()
    return 0


def _handle_seed(svc, args):
    """Seed config_nodes from existing system_config keys."""
    from db_utils import query_all as qa

    rows = qa("SELECT key, value FROM system_config WHERE key LIKE 'nixos.%' ORDER BY key")
    if not rows:
        print("No nixos.* keys found in system_config")
        return 0

    count = 0
    for row in rows:
        key, value = row['key'], row['value']

        if args.dry_run:
            print(f"  {key} = {value[:80]}")
            count += 1
            continue

        try:
            # nixos.attr.* -> system scope, direct attr path
            if key.startswith('nixos.attr.'):
                attr_path = key.replace('nixos.attr.', '')
                node_type = 'Bool' if value in ('true', 'false') else 'String'
                svc.set_leaf('system', attr_path, value, node_type, project_slug='system_config')
                count += 1

            # nixos.pkg.user.<category>.<package> -> home.packages list
            elif key.startswith('nixos.pkg.user.'):
                rest = key.replace('nixos.pkg.user.', '')
                parts = rest.split('.', 1)
                cat_label = parts[0].replace('_', ' ').title() if len(parts) == 2 else None
                pkg = parts[1] if len(parts) == 2 else parts[0]
                svc.add_list_item('home', 'home.packages', pkg, 'Package',
                                  category=cat_label, project_slug='system_config')
                count += 1

            # nixos.pkg.system.<package> -> environment.systemPackages list
            elif key.startswith('nixos.pkg.system.'):
                pkg = key.replace('nixos.pkg.system.', '')
                svc.add_list_item('system', 'environment.systemPackages', pkg, 'Package',
                                  project_slug='system_config')
                count += 1

            # nixos.alias.<name> -> programs.bash.shellAliases.<name>
            elif key.startswith('nixos.alias.'):
                alias_name = key.replace('nixos.alias.', '')
                svc.set_leaf('home', f'programs.bash.shellAliases.{alias_name}', value,
                              'String', project_slug='system_config')
                count += 1

            # nixos.firewall.tcp -> networking.firewall.allowedTCPPorts
            elif key == 'nixos.firewall.tcp':
                ports = json.loads(value)
                for port in ports:
                    svc.add_list_item('system', 'networking.firewall.allowedTCPPorts',
                                      str(port), 'Int', project_slug='system_config')
                count += len(ports)

            # nixos.flake.input.<name> -> flake inputs
            elif key.startswith('nixos.flake.input.'):
                input_name = key.replace('nixos.flake.input.', '')
                svc.set_leaf('flake', f'inputs.{input_name}.url', value,
                              'String', project_slug='system_config')
                count += 1

        except Exception as e:
            print(f"  ERROR seeding {key}: {e}", file=sys.stderr)

    print(f"Seeded {count} config nodes from system_config")
    return 0


def _handle_host(svc, args):
    if args.host_command == 'list':
        hosts = svc.list_hosts()
        if not hosts:
            print("No hosts configured")
            return 0
        for h in hosts:
            parent = ""
            if h['parent_id']:
                all_hosts = svc.list_hosts()
                parent_name = next((x['name'] for x in all_hosts if x['id'] == h['parent_id']), '?')
                parent = f" (extends {parent_name})"
            print(f"  {h['name']}{parent}")
        return 0
    elif args.host_command == 'add':
        host_id = svc.add_host(args.name, args.parent)
        print(f"Added host '{args.name}' (id={host_id})")
        return 0
    return 1


def _handle_query(svc, args):
    results = svc.query_nodes(
        node_type=args.node_type,
        callee=args.callee,
        project_slug=args.project
    )
    for r in results:
        path = svc.node_path(r['id'])
        val = r['value'] or r['callee'] or ''
        print(f"  {path}: {r['node_type']} = {val}")
    print(f"\n{len(results)} nodes")
    return 0


def _handle_owners(svc, args):
    node = svc.find_by_path(args.scope, args.path)
    if not node:
        print(f"Not found: {args.scope}.{args.path}", file=sys.stderr)
        return 1
    owners = svc.get_owners(node['id'])
    if owners:
        print(f"Owners of {args.path}: {', '.join(owners)}")
    else:
        print(f"{args.path} has no project owner")
    return 0


def _handle_orphans(svc):
    orphans = svc.orphan_nodes()
    if not orphans:
        print("No orphan nodes")
        return 0
    for o in orphans:
        path = svc.node_path(o['id'])
        print(f"  {path}: {o['node_type']} = {o['value'] or ''}")
    print(f"\n{len(orphans)} orphan nodes")
    return 0


def _handle_stats(svc):
    s = svc.stats()
    print(f"Total nodes:    {s['total_nodes']}")
    print(f"Owned nodes:    {s['owned_nodes']}")
    print(f"RawNix count:   {s['raw_nix_count']}")
    print(f"Hosts:          {s['hosts']}")
    print(f"\nBy type:")
    for t, c in sorted(s['by_type'].items(), key=lambda x: -x[1]):
        print(f"  {t:20s} {c}")
    return 0


def _import_nix_file(svc, filepath, scope, project_slug=None, host_id=None):
    """Parse a .nix file and insert into config_nodes for the given scope.

    Returns (node_count, error_message).
    Handles structural unwrapping: configuration.nix has two FnDef wrappers,
    home.nix has one, flake.nix has none.

    When host_id is set, deep-merges into existing shared (host_id=NULL)
    AttrSets rather than duplicating them: intermediate AttrSets are reused,
    only new leaves and subtrees are inserted with the host tag.
    """
    try:
        from nix_ast_parser import parse_nix_file, ASTNode
    except ImportError:
        return 0, ("nix_ast_parser requires tree-sitter. "
                    "Run inside: nix-shell -p python3Packages.tree-sitter "
                    "tree-sitter-grammars.tree-sitter-nix")

    ast = parse_nix_file(filepath)
    if not ast:
        return 0, f"Failed to parse {filepath}"

    # Merge duplicate AttrSet names (Nix allows services.x = ...; services.y = ...;)
    def merge_attrsets(node):
        if node.node_type not in ('AttrSet', 'RecAttrSet', 'LetIn'):
            for c in node.children:
                merge_attrsets(c)
            return
        merged = {}
        non_named = []
        for c in node.children:
            if c.name and c.node_type in ('AttrSet', 'RecAttrSet'):
                if c.name in merged:
                    for gc in c.children:
                        merged[c.name].add(gc)
                else:
                    merged[c.name] = c
            elif c.name:
                merged[c.name] = c
            else:
                non_named.append(c)
        node.children = list(merged.values()) + non_named
        for i, c in enumerate(node.children):
            c.sort_order = i
        for c in node.children:
            merge_attrsets(c)

    merge_attrsets(ast)

    # Unwrap file-level structure to get bindings + body.
    # System/home configs may have 0, 1, or 2 outer FnDef wrappers depending on
    # whether they take module args and system args separately. Skip past any
    # FnDef wrappers until we hit LetIn or AttrSet.
    bindings = []
    body_children = []

    if scope in ('system', 'home'):
        inner = ast
        while inner.node_type == 'FnDef' and len(inner.children) >= 2:
            inner = inner.children[1]
        if inner.node_type == 'LetIn':
            bindings = [c for c in inner.children if c.node_type == 'Binding']
            body = [c for c in inner.children if c.node_type != 'Binding']
            if body and body[0].node_type == 'AttrSet':
                body_children = body[0].children
        elif inner.node_type == 'AttrSet':
            body_children = inner.children
    elif scope == 'flake':
        # Direct AttrSet
        if ast.node_type == 'AttrSet':
            body_children = ast.children

    if not body_children and not bindings:
        return 0, f"Could not extract config body from {filepath} for scope {scope}"

    # Insert into DB
    from db_utils import execute, query_one
    root_id = svc.get_root(scope)

    def insert_ast(node, parent_db_id):
        # Host-overlay path: reuse existing shared AttrSets under the same name
        # so per-host imports layer onto shared config instead of shadowing it.
        if host_id is not None and node.name and node.node_type in ('AttrSet', 'RecAttrSet'):
            existing = query_one(
                """SELECT id FROM config_nodes
                   WHERE parent_id = ? AND name = ? AND host_id IS NULL
                     AND node_type IN ('AttrSet', 'RecAttrSet')""",
                (parent_db_id, node.name),
            )
            if existing:
                count = 0
                for child in node.children:
                    count += insert_ast(child, existing['id'])
                return count

        node_id = svc.add_node(
            parent_id=parent_db_id, name=node.name, node_type=node.node_type,
            value=node.value, callee=node.callee, operator=node.operator,
            sort_order=node.sort_order, host_id=host_id,
        )
        count = 1
        for child in node.children:
            count += insert_ast(child, node_id)
        return count

    total = 0
    for b in bindings:
        total += insert_ast(b, root_id)
    for child in body_children:
        total += insert_ast(child, root_id)

    # Assign ownership
    if project_slug:
        from db_utils import query_all, query_one
        project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if project:
            pid = project['id']
            leaves = query_all("""SELECT id FROM config_nodes
                                  WHERE node_type NOT IN ('AttrSet','RecAttrSet','List','With','LetIn')
                                  AND id NOT IN (SELECT node_id FROM config_node_owners)""")
            for leaf in leaves:
                execute("INSERT OR IGNORE INTO config_node_owners (node_id, project_id) VALUES (?, ?)",
                        (leaf['id'], pid))

    return total, None


def _handle_import(svc, args):
    """Import a single .nix file."""
    from db_utils import execute, query_all
    import os

    if not os.path.exists(args.file):
        print(f"File not found: {args.file}", file=sys.stderr)
        return 1

    host_id = _host_id(svc, args.host) if getattr(args, 'host', None) else None

    root_id = svc.get_root(args.scope)
    if host_id is not None:
        # Host overlay: clear existing nodes tagged to this host in this scope
        # so re-import is idempotent. Shared (host_id=NULL) nodes are preserved.
        existing = query_all(
            """WITH RECURSIVE tree(id) AS (
                 SELECT id FROM config_nodes WHERE parent_id = ? AND host_id = ?
                 UNION ALL
                 SELECT cn.id FROM config_nodes cn JOIN tree t ON cn.parent_id = t.id
               ) SELECT id FROM tree""",
            (root_id, host_id),
        )
        if existing:
            for c in existing:
                execute("DELETE FROM config_nodes WHERE id = ?", (c['id'],))
            print(f"Cleared {len(existing)} existing nodes for host '{args.host}' in {args.scope}")
    elif root_id:
        # Non-host import into a shared scope: original semantics
        children = query_all("SELECT id FROM config_nodes WHERE parent_id = ?", (root_id,))
        if children and not args.replace:
            print(f"Scope '{args.scope}' already has {len(children)} children. "
                  f"Use --replace to overwrite.", file=sys.stderr)
            return 1
        if args.replace and children:
            for c in children:
                execute("DELETE FROM config_nodes WHERE id = ?", (c['id'],))
            print(f"Cleared {len(children)} existing children from {args.scope} scope")

    count, err = _import_nix_file(svc, args.file, args.scope, args.project, host_id=host_id)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    label = f"{args.scope} scope" + (f" (host {args.host})" if args.host else "")
    print(f"Imported {count} nodes into {label} from {args.file}")
    s = svc.stats()
    print(f"Total: {s['total_nodes']} nodes, {s['raw_nix_count']} RawNix")
    return 0


def _handle_import_all(svc, args):
    """Import all .nix files from a directory."""
    from db_utils import execute, query_all
    import os

    dir_path = args.dir
    files = {
        'system': os.path.join(dir_path, 'configuration.nix'),
        'home': os.path.join(dir_path, 'home.nix'),
        'flake': os.path.join(dir_path, 'flake.nix'),
    }

    # Verify files exist
    for scope, path in files.items():
        if not os.path.exists(path):
            print(f"Missing: {path}", file=sys.stderr)
            return 1

    # Clear all existing nodes
    execute("DELETE FROM config_node_owners")
    execute("DELETE FROM config_roots")
    execute("DELETE FROM config_nodes")

    # Recreate roots
    for scope_name in ('system', 'home', 'flake'):
        root_id = svc.add_node(parent_id=None, name=None, node_type='AttrSet', scope=scope_name)
        execute("INSERT INTO config_roots (scope, node_id, description) VALUES (?, ?, ?)",
                (scope_name, root_id, f'{scope_name} scope root'))

    # Import each file
    total = 0
    for scope, path in files.items():
        print(f"Importing {path} → {scope}...")
        count, err = _import_nix_file(svc, path, scope, args.project)
        if err:
            print(f"  Error: {err}", file=sys.stderr)
            return 1
        print(f"  {count} nodes")
        total += count

    s = svc.stats()
    print(f"\nTotal: {s['total_nodes']} nodes, {s['raw_nix_count']} RawNix, {s['owned_nodes']} owned")
    return 0
