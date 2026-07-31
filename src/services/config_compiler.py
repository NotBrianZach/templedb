"""ConfigCompilerService — AST-based system configuration compiler.

Stores NixOS config as a typed tree of nodes in the database.
Supports project ownership, host inheritance, and code generation.

See: docs/CONFIG_COMPILER_SPEC.md
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from services.base import BaseService
from logger import get_logger
from db_utils import query_all, query_one, execute

logger = get_logger("ConfigCompilerService")


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ── Data classes ──────────────────────────────────────────────────────────

@dataclass
class ConfigNode:
    """In-memory representation of a config_nodes row."""
    id: int
    parent_id: Optional[int]
    name: Optional[str]
    sort_order: int
    node_type: str
    value: Optional[str] = None
    callee: Optional[str] = None
    operator: Optional[str] = None
    scope: Optional[str] = None
    host_id: Optional[int] = None
    enabled: bool = True
    description: Optional[str] = None
    category: Optional[str] = None
    children: List['ConfigNode'] = field(default_factory=list)
    owner_slugs: List[str] = field(default_factory=list)

    def get_child(self, name: str) -> Optional['ConfigNode']:
        """Get a named child."""
        for c in self.children:
            if c.name == name:
                return c
        return None

    def get_children_by_type(self, node_type: str) -> List['ConfigNode']:
        return [c for c in self.children if c.node_type == node_type]


# ── Service ───────────────────────────────────────────────────────────────

class ConfigCompilerService(BaseService):

    # ── Host management ───────────────────────────────────────────────

    def list_hosts(self) -> List[dict]:
        return query_all("SELECT * FROM config_hosts ORDER BY name")

    def get_host(self, name: str) -> Optional[dict]:
        return query_one("SELECT * FROM config_hosts WHERE name = ?", (name,))

    def add_host(self, name: str, parent_name: Optional[str] = None,
                 hw_config: Optional[str] = None, description: Optional[str] = None) -> int:
        parent_id = None
        if parent_name:
            parent = self.get_host(parent_name)
            if not parent:
                raise ValueError(f"Parent host '{parent_name}' not found")
            parent_id = parent['id']
        execute(
            "INSERT INTO config_hosts (name, parent_id, hw_config, description) VALUES (?, ?, ?, ?)",
            (name, parent_id, hw_config, description)
        )
        return query_one("SELECT id FROM config_hosts WHERE name = ?", (name,))['id']

    def host_chain(self, host_name: str) -> List[int]:
        """Return host_id chain from most specific to least, ending with NULL."""
        chain = []
        host = self.get_host(host_name)
        while host:
            chain.append(host['id'])
            if host['parent_id']:
                host = query_one("SELECT * FROM config_hosts WHERE id = ?", (host['parent_id'],))
            else:
                host = None
        return chain  # most specific first, NULL not included (handled separately)

    # ── Tree CRUD ─────────────────────────────────────────────────────

    def get_root(self, scope: str) -> Optional[int]:
        """Get root node_id for a scope."""
        row = query_one("SELECT node_id FROM config_roots WHERE scope = ?", (scope,))
        return row['node_id'] if row else None

    def add_node(self, parent_id: int, name: Optional[str], node_type: str,
                 value: Optional[str] = None, callee: Optional[str] = None,
                 operator: Optional[str] = None, scope: Optional[str] = None,
                 host_id: Optional[int] = None, category: Optional[str] = None,
                 description: Optional[str] = None, sort_order: int = 0) -> int:
        """Insert a node and return its id."""
        now = _now()
        execute(
            """INSERT INTO config_nodes
               (parent_id, name, sort_order, node_type, value, callee, operator,
                scope, host_id, enabled, description, category, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
            (parent_id, name, sort_order, node_type, value, callee, operator,
             scope, host_id, description, category, now, now)
        )
        row = query_one("SELECT last_insert_rowid() as id")
        return row['id']

    def ensure_path(self, scope: str, path: str, host_id: Optional[int] = None) -> int:
        """Ensure an AttrSet path exists under the scope root, creating intermediates.
        Returns the id of the deepest node.

        Example: ensure_path('system', 'services.openssh.settings') creates
        the services, openssh, and settings AttrSet nodes if they don't exist.
        """
        root_id = self.get_root(scope)
        if not root_id:
            raise ValueError(f"No root node for scope '{scope}'")

        current_id = root_id
        parts = path.split('.')
        for part in parts:
            # Look for existing child (global or matching host)
            existing = query_one(
                """SELECT id FROM config_nodes
                   WHERE parent_id = ? AND name = ? AND (host_id IS NULL OR host_id = ?)""",
                (current_id, part, host_id)
            )
            if existing:
                current_id = existing['id']
            else:
                current_id = self.add_node(
                    parent_id=current_id, name=part, node_type='AttrSet',
                    host_id=host_id
                )
        return current_id

    def set_leaf(self, scope: str, path: str, value: str, node_type: str = 'String',
                 host_id: Optional[int] = None, category: Optional[str] = None,
                 project_slug: Optional[str] = None) -> int:
        """Set a leaf value at an attr path, creating intermediates.

        Example: set_leaf('system', 'services.openssh.enable', 'true', 'Bool')
        """
        parts = path.rsplit('.', 1)
        if len(parts) == 2:
            parent_path, leaf_name = parts
            parent_id = self.ensure_path(scope, parent_path, host_id)
        else:
            leaf_name = parts[0]
            parent_id = self.get_root(scope)

        # Check if leaf already exists
        existing = query_one(
            """SELECT id FROM config_nodes
               WHERE parent_id = ? AND name = ? AND (host_id IS ? OR host_id = ?)""",
            (parent_id, leaf_name, host_id, host_id)
        )

        now = _now()
        if existing:
            execute(
                "UPDATE config_nodes SET value = ?, node_type = ?, category = ?, updated_at = ? WHERE id = ?",
                (value, node_type, category, now, existing['id'])
            )
            node_id = existing['id']
        else:
            node_id = self.add_node(
                parent_id=parent_id, name=leaf_name, node_type=node_type,
                value=value, host_id=host_id, category=category
            )

        if project_slug:
            self._set_owner(node_id, project_slug)

        return node_id

    def add_list_item(self, scope: str, path: str, value: str,
                      node_type: str = 'Package', host_id: Optional[int] = None,
                      category: Optional[str] = None,
                      project_slug: Optional[str] = None) -> int:
        """Add an item to a list at the given path.

        If the list doesn't exist, creates it. Does not create duplicates.
        """
        parent_id = self.ensure_path(scope, path, host_id)

        # Check parent is a List (or With containing a List)
        parent = query_one("SELECT node_type FROM config_nodes WHERE id = ?", (parent_id,))
        if parent and parent['node_type'] == 'AttrSet':
            # Need to check if there's a List child, or create one
            list_node = query_one(
                "SELECT id FROM config_nodes WHERE parent_id = ? AND node_type = 'List'",
                (parent_id,)
            )
            if not list_node:
                # Create the list node
                parent_id = self.add_node(parent_id=parent_id, name=None, node_type='List')
            else:
                parent_id = list_node['id']
        elif parent and parent['node_type'] in ('With', 'List'):
            if parent['node_type'] == 'With':
                list_node = query_one(
                    "SELECT id FROM config_nodes WHERE parent_id = ? AND node_type = 'List'",
                    (parent_id,)
                )
                if list_node:
                    parent_id = list_node['id']
                else:
                    parent_id = self.add_node(parent_id=parent_id, name=None, node_type='List')

        # Check for duplicate
        existing = query_one(
            "SELECT id FROM config_nodes WHERE parent_id = ? AND value = ? AND node_type = ?",
            (parent_id, value, node_type)
        )
        if existing:
            return existing['id']

        # Get next sort_order
        max_sort = query_one(
            "SELECT COALESCE(MAX(sort_order), -1) as m FROM config_nodes WHERE parent_id = ?",
            (parent_id,)
        )
        sort_order = (max_sort['m'] + 1) if max_sort else 0

        node_id = self.add_node(
            parent_id=parent_id, name=None, node_type=node_type,
            value=value, sort_order=sort_order, category=category
        )

        if project_slug:
            self._set_owner(node_id, project_slug)

        return node_id

    def remove_node(self, node_id: int):
        """Remove a node and all its descendants (CASCADE)."""
        execute("DELETE FROM config_nodes WHERE id = ?", (node_id,))

    def enable_node(self, node_id: int):
        execute("UPDATE config_nodes SET enabled = 1, updated_at = ? WHERE id = ?", (_now(), node_id))

    def disable_node(self, node_id: int):
        execute("UPDATE config_nodes SET enabled = 0, updated_at = ? WHERE id = ?", (_now(), node_id))

    # ── Ownership ─────────────────────────────────────────────────────

    def _set_owner(self, node_id: int, project_slug: str):
        project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if not project:
            raise ValueError(f"Project '{project_slug}' not found")
        execute(
            "INSERT OR IGNORE INTO config_node_owners (node_id, project_id) VALUES (?, ?)",
            (node_id, project['id'])
        )

    def set_owner(self, node_id: int, project_slug: str):
        self._set_owner(node_id, project_slug)

    def get_owners(self, node_id: int) -> List[str]:
        rows = query_all(
            """SELECT p.slug FROM config_node_owners co
               JOIN projects p ON co.project_id = p.id
               WHERE co.node_id = ?""",
            (node_id,)
        )
        return [r['slug'] for r in rows]

    def orphan_nodes(self) -> List[dict]:
        """Find leaf nodes with no project owner."""
        return query_all(
            """SELECT cn.id, cn.name, cn.node_type, cn.value
               FROM config_nodes cn
               LEFT JOIN config_node_owners co ON cn.id = co.node_id
               WHERE co.node_id IS NULL
                 AND cn.node_type NOT IN ('AttrSet', 'List', 'With', 'LetIn')"""
        )

    # ── Resolver ──────────────────────────────────────────────────────

    def resolve(self, scope: str, host_name: Optional[str] = None) -> ConfigNode:
        """Resolve the full tree for a scope, applying host inheritance.

        Returns an in-memory ConfigNode tree ready for the backend.
        """
        root_id = self.get_root(scope)
        if not root_id:
            raise ValueError(f"No root for scope '{scope}'")

        host_chain = self.host_chain(host_name) if host_name else []

        # Load all enabled nodes for this scope
        all_nodes = query_all(
            """SELECT cn.*, GROUP_CONCAT(p.slug) as owner_slugs
               FROM config_nodes cn
               LEFT JOIN config_node_owners co ON cn.id = co.node_id
               LEFT JOIN projects p ON co.project_id = p.id
               WHERE cn.enabled = 1
               GROUP BY cn.id""",
        )

        # Index by id
        by_id = {}
        for row in all_nodes:
            node = ConfigNode(
                id=row['id'], parent_id=row['parent_id'], name=row['name'],
                sort_order=row['sort_order'], node_type=row['node_type'],
                value=row['value'], callee=row['callee'], operator=row['operator'],
                scope=row['scope'], host_id=row['host_id'], enabled=row['enabled'],
                description=row['description'], category=row['category'],
                owner_slugs=row['owner_slugs'].split(',') if row['owner_slugs'] else []
            )
            by_id[node.id] = node

        # Build tree from root
        root = by_id.get(root_id)
        if not root:
            raise ValueError(f"Root node {root_id} not found or disabled")

        self._build_children(root, by_id, host_chain)
        return root

    def _build_children(self, parent: ConfigNode, by_id: Dict[int, ConfigNode],
                        host_chain: List[int]):
        """Recursively build children, applying host resolution."""
        # Find all direct children of this parent
        candidates = [n for n in by_id.values() if n.parent_id == parent.id]

        if parent.node_type in ('AttrSet', 'LetIn'):
            # Named children: resolve host overrides by name
            by_name: Dict[str, List[ConfigNode]] = {}
            unnamed = []
            for c in candidates:
                if c.name is not None:
                    by_name.setdefault(c.name, []).append(c)
                else:
                    unnamed.append(c)

            for name, nodes in by_name.items():
                winner = self._resolve_host(nodes, host_chain)
                if winner:
                    parent.children.append(winner)

            # Unnamed children (e.g. body of LetIn)
            for c in unnamed:
                if self._host_visible(c, host_chain):
                    parent.children.append(c)

        elif parent.node_type in ('List', 'With', 'FnCall', 'FnDef',
                                   'Binding', 'Conditional', 'Assert',
                                   'BinOp', 'UnaryOp', 'Select', 'HasAttr',
                                   'Interpolation', 'Import'):
            # Ordered children: keep all that are host-visible
            visible = [c for c in candidates if self._host_visible(c, host_chain)]
            parent.children.extend(visible)

        # Sort children
        parent.children.sort(key=lambda c: (c.sort_order, c.name or ''))

        # Recurse
        for child in parent.children:
            self._build_children(child, by_id, host_chain)

    def _resolve_host(self, nodes: List[ConfigNode], host_chain: List[int]) -> Optional[ConfigNode]:
        """Pick the most specific host-matching node."""
        # Priority: exact host match (by chain order) > NULL
        for host_id in host_chain:
            for n in nodes:
                if n.host_id == host_id:
                    return n
        # Fall back to global (NULL)
        for n in nodes:
            if n.host_id is None:
                return n
        return None

    def _host_visible(self, node: ConfigNode, host_chain: List[int]) -> bool:
        """Check if a node is visible for the given host chain."""
        if node.host_id is None:
            return True
        return node.host_id in host_chain

    # ── Tree queries ──────────────────────────────────────────────────

    def node_path(self, node_id: int) -> str:
        """Reconstruct the dotted attr path for a node."""
        parts = []
        current = query_one("SELECT * FROM config_nodes WHERE id = ?", (node_id,))
        while current:
            if current['name']:
                parts.append(current['name'])
            if current['parent_id']:
                current = query_one("SELECT * FROM config_nodes WHERE id = ?", (current['parent_id'],))
            else:
                break
        return '.'.join(reversed(parts))

    def find_by_path(self, scope: str, path: str) -> Optional[dict]:
        """Find a node by its dotted attr path."""
        root_id = self.get_root(scope)
        if not root_id:
            return None
        current_id = root_id
        for part in path.split('.'):
            row = query_one(
                "SELECT id FROM config_nodes WHERE parent_id = ? AND name = ?",
                (current_id, part)
            )
            if not row:
                return None
            current_id = row['id']
        return query_one("SELECT * FROM config_nodes WHERE id = ?", (current_id,))

    def query_nodes(self, node_type: Optional[str] = None,
                    callee: Optional[str] = None,
                    project_slug: Optional[str] = None) -> List[dict]:
        """Query nodes by type, callee, or project."""
        conditions = ["cn.enabled = 1"]
        params = []

        if node_type:
            conditions.append("cn.node_type = ?")
            params.append(node_type)
        if callee:
            conditions.append("cn.callee = ?")
            params.append(callee)

        join = ""
        if project_slug:
            join = """JOIN config_node_owners co ON cn.id = co.node_id
                      JOIN projects p ON co.project_id = p.id"""
            conditions.append("p.slug = ?")
            params.append(project_slug)

        where = " AND ".join(conditions)
        return query_all(f"SELECT cn.* FROM config_nodes cn {join} WHERE {where}", params)

    def stats(self) -> dict:
        """Return summary stats."""
        total = query_one("SELECT COUNT(*) as c FROM config_nodes")['c']
        by_type = query_all(
            "SELECT node_type, COUNT(*) as c FROM config_nodes GROUP BY node_type ORDER BY c DESC"
        )
        raw_nix = query_one(
            "SELECT COUNT(*) as c FROM config_nodes WHERE node_type = 'RawNix'"
        )['c']
        hosts = query_one("SELECT COUNT(*) as c FROM config_hosts")['c']
        owned = query_one(
            "SELECT COUNT(DISTINCT node_id) as c FROM config_node_owners"
        )['c']
        return {
            'total_nodes': total,
            'by_type': {r['node_type']: r['c'] for r in by_type},
            'raw_nix_count': raw_nix,
            'hosts': hosts,
            'owned_nodes': owned,
        }

    # ── Nix backend ───────────────────────────────────────────────────

    def emit_nix(self, node: ConfigNode, indent_level: int = 0) -> str:
        """Emit a ConfigNode tree as Nix source code."""
        ind = "  " * indent_level
        ind1 = "  " * (indent_level + 1)

        match node.node_type:
            case 'AttrSet':
                if not node.children:
                    return '{ }'
                # Collapse: if an AttrSet has a single unnamed List child,
                # emit the list directly (e.g. packages = [ ... ] not packages = { [ ... ] })
                if (len(node.children) == 1
                        and node.children[0].name is None
                        and node.children[0].node_type in ('List', 'With')):
                    return self.emit_nix(node.children[0], indent_level)
                lines = []
                for c in node.children:
                    val = self.emit_nix(c, indent_level + 1)
                    if c.node_type == 'Inherit':
                        lines.append(f"{ind1}{val}")
                    elif c.name:
                        lines.append(f"{ind1}{c.name} = {val};")
                    else:
                        lines.append(f"{ind1}{val}")
                return '{\n' + '\n'.join(lines) + f'\n{ind}}}'

            case 'List':
                if not node.children:
                    return '[ ]'
                items = [f"{ind1}{self.emit_nix(c, indent_level + 1)}" for c in node.children]
                return '[\n' + '\n'.join(items) + f'\n{ind}]'

            case 'Bool':
                return node.value  # "true" or "false"

            case 'Int':
                return node.value

            case 'String':
                escaped = (node.value or '').replace('\\', '\\\\').replace('"', '\\"')
                return f'"{escaped}"'

            case 'Path':
                return node.value

            case 'Package':
                return node.value  # bare ident inside with pkgs;

            case 'Identifier':
                return node.value

            case 'FnCall':
                if node.children:
                    arg = node.children[0]
                    args = self.emit_nix(arg, indent_level)
                    # Wrap lambda/complex args in parens
                    if arg.node_type in ('FnDef', 'LetIn', 'Conditional',
                                          'BinOp', 'With', 'Assert'):
                        args = f'({args})'
                    return f'{node.callee} {args}'
                return node.callee

            case 'FnDef':
                params = node.get_child('params')
                body = node.get_child('body')
                if params and body:
                    return f'{params.value}: {self.emit_nix(body, indent_level)}'
                # Fallback: single unnamed child
                if node.children:
                    return self.emit_nix(node.children[0], indent_level)
                return ''

            case 'LetIn':
                bindings = node.get_children_by_type('Binding')
                body = [c for c in node.children if c.node_type != 'Binding']
                b_lines = []
                for b in bindings:
                    if b.children:
                        val = self.emit_nix(b.children[0], indent_level + 1)
                        b_lines.append(f"{ind1}{b.name} = {val};")
                body_str = self.emit_nix(body[0], indent_level) if body else '{ }'
                return f'let\n' + '\n'.join(b_lines) + f'\n{ind}in\n{ind}{body_str}'

            case 'Binding':
                if node.children:
                    return self.emit_nix(node.children[0], indent_level)
                return node.value or ''

            case 'With':
                if node.children:
                    body = self.emit_nix(node.children[0], indent_level)
                    return f'with {node.callee}; {body}'
                return f'with {node.callee}; {{ }}'

            case 'MultilineString':
                return f"''{node.value or ''}''"

            case 'Interpolation':
                parts = []
                has_newline = False
                for c in node.children:
                    if c.node_type == 'Identifier':
                        parts.append(f'${{{c.value}}}')
                    elif c.node_type == 'Select':
                        parts.append(f'${{{self.emit_nix(c, indent_level)}}}')
                    elif c.node_type in ('String', 'MultilineString'):
                        text = c.value or ''
                        if '\n' in text:
                            has_newline = True
                        parts.append(text)
                    else:
                        parts.append(f'${{{self.emit_nix(c, indent_level)}}}')
                joined = ''.join(parts)
                if has_newline:
                    return f"''{joined}''"
                return f'"{joined}"'

            case 'Conditional':
                cond_n = node.get_child('cond')
                then_n = node.get_child('then')
                else_n = node.get_child('else')
                if cond_n and then_n and else_n:
                    return (f'if {self.emit_nix(cond_n, indent_level)} '
                            f'then {self.emit_nix(then_n, indent_level)} '
                            f'else {self.emit_nix(else_n, indent_level)}')
                return ''

            case 'BinOp':
                if len(node.children) >= 2:
                    left = self.emit_nix(node.children[0], indent_level)
                    right = self.emit_nix(node.children[1], indent_level)
                    return f'{left} {node.operator} {right}'
                return ''

            case 'Inherit':
                names = ' '.join(c.value for c in node.children if c.value)
                if node.callee:
                    return f'inherit ({node.callee}) {names};'
                return f'inherit {names};'

            case 'RecAttrSet':
                if not node.children:
                    return 'rec { }'
                lines = []
                for c in node.children:
                    val = self.emit_nix(c, indent_level + 1)
                    if c.node_type == 'Inherit':
                        lines.append(f"{ind1}{val}")
                    elif c.name:
                        lines.append(f"{ind1}{c.name} = {val};")
                    else:
                        lines.append(f"{ind1}{val}")
                return 'rec {\n' + '\n'.join(lines) + f'\n{ind}}}'

            case 'Float':
                return node.value

            case 'Null':
                return 'null'

            case 'Assert':
                cond = node.get_child('cond') or (node.children[0] if node.children else None)
                body = node.get_child('body') or (node.children[1] if len(node.children) > 1 else None)
                if cond and body:
                    return f'assert {self.emit_nix(cond, indent_level)}; {self.emit_nix(body, indent_level)}'
                return ''

            case 'UnaryOp':
                if node.children:
                    operand = self.emit_nix(node.children[0], indent_level)
                    return f'{node.operator}{operand}'
                return ''

            case 'Select':
                # e.attr or e.attr or default
                if len(node.children) >= 1:
                    expr = self.emit_nix(node.children[0], indent_level)
                    attr = node.value or ''
                    result = f'{expr}.{attr}'
                    if len(node.children) >= 2:
                        default = self.emit_nix(node.children[1], indent_level)
                        result += f' or {default}'
                    return result
                return ''

            case 'HasAttr':
                if len(node.children) >= 1:
                    expr = self.emit_nix(node.children[0], indent_level)
                    return f'{expr} ? {node.value}'
                return ''

            case 'Import':
                return f'import {node.value}'

            case 'RawNix':
                return node.value or ''

            case _:
                logger.warning(f"Unknown node type: {node.node_type}")
                return f'/* unknown: {node.node_type} */'

    # ── File-level generators ───────────────────────────────────────

    def generate_file(self, scope: str, host_name: Optional[str] = None) -> str:
        """Generate a complete .nix file for a scope.

        Wraps the resolved tree in the appropriate file-level structure:
        - system: { self, ... }: { config, lib, pkgs, ... }: let ... in { ... }
        - home: { config, pkgs, lib, ... }: let ... in { ... }
        - flake: { inputs = { ... }; outputs = ...; }
        """
        tree = self.resolve(scope, host_name)

        # Separate let-bindings from body attrs
        bindings = [c for c in tree.children if c.node_type == 'Binding']
        body_children = [c for c in tree.children if c.node_type != 'Binding']

        if scope == 'system':
            return self._generate_system(bindings, body_children)
        elif scope == 'home':
            return self._generate_home(bindings, body_children)
        elif scope == 'flake':
            return self._generate_flake(tree)
        else:
            return self.emit_nix(tree)

    def _generate_system(self, bindings: List[ConfigNode],
                         body_children: List[ConfigNode]) -> str:
        """Generate configuration.nix."""
        lines = [
            "# System-level configuration for NixOS",
            "# Generated by TempleDB configuration compiler",
            "{ self, plandex, nixpkgs-unstable, templedb, ... }:",
            "{ config, lib, pkgs, myHostname, ... }:",
        ]

        if bindings:
            lines.append("let")
            for b in bindings:
                val = self.emit_nix(b.children[0], 1) if b.children else '""'
                lines.append(f"  {b.name} = {val};")
            lines.append("in")

        lines.append("{")
        for child in body_children:
            self._emit_attr_child(child, lines, 1)
        lines.append("}")
        return '\n'.join(lines) + '\n'

    def _generate_home(self, bindings: List[ConfigNode],
                       body_children: List[ConfigNode]) -> str:
        """Generate home.nix."""
        lines = [
            "# Home Manager configuration",
            "# Generated by TempleDB configuration compiler",
            "{ config, pkgs, lib, nixpkgs-unstable, templedb, bza, ... }:",
        ]

        if bindings:
            lines.append("let")
            for b in bindings:
                val = self.emit_nix(b.children[0], 1) if b.children else '""'
                lines.append(f"  {b.name} = {val};")
            lines.append("in")

        lines.append("{")
        for child in body_children:
            self._emit_attr_child(child, lines, 1)
        lines.append("}")
        return '\n'.join(lines) + '\n'

    def _generate_flake(self, tree: ConfigNode) -> str:
        """Generate flake.nix."""
        lines = ["{"]
        for child in tree.children:
            self._emit_attr_child(child, lines, 1)
        lines.append("}")
        return '\n'.join(lines) + '\n'

    def _emit_attr_child(self, child: ConfigNode, lines: List[str], indent: int):
        """Emit a named child as an attribute assignment line."""
        ind = "  " * indent
        if child.name:
            val = self.emit_nix(child, indent)
            lines.append(f"{ind}{child.name} = {val};")
        elif child.node_type == 'Inherit':
            lines.append(f"{ind}{self.emit_nix(child, indent)}")
        else:
            # Unnamed non-inherit (shouldn't happen at top level)
            lines.append(f"{ind}{self.emit_nix(child, indent)};")

    def emit_json(self, node: ConfigNode) -> dict:
        """Emit a ConfigNode tree as a JSON-serializable dict."""
        result = {'type': node.node_type}
        if node.name:
            result['name'] = node.name
        if node.value is not None:
            result['value'] = node.value
        if node.callee:
            result['callee'] = node.callee
        if node.operator:
            result['operator'] = node.operator
        if node.owner_slugs:
            result['owners'] = node.owner_slugs
        if node.category:
            result['category'] = node.category
        if node.host_id is not None:
            host = query_one("SELECT name FROM config_hosts WHERE id = ?", (node.host_id,))
            result['host'] = host['name'] if host else str(node.host_id)
        if node.children:
            if node.node_type == 'AttrSet':
                result['children'] = {}
                for c in node.children:
                    key = c.name or f'_{c.id}'
                    result['children'][key] = self.emit_json(c)
            else:
                result['children'] = [self.emit_json(c) for c in node.children]
        return result

    # ── Tree display ──────────────────────────────────────────────────

    def print_tree(self, node: ConfigNode, indent: int = 0, show_ids: bool = False) -> str:
        """Render a tree as an indented string for CLI display."""
        lines = []
        prefix = "  " * indent

        label_parts = []
        if show_ids:
            label_parts.append(f"[{node.id}]")
        if node.name:
            label_parts.append(node.name)

        type_str = node.node_type
        if node.value is not None:
            type_str += f': {node.value}'
        elif node.callee:
            type_str += f'({node.callee})'

        label_parts.append(f"({type_str})")

        if node.owner_slugs:
            label_parts.append(f"<{','.join(node.owner_slugs)}>")
        if node.host_id is not None:
            host = query_one("SELECT name FROM config_hosts WHERE id = ?", (node.host_id,))
            label_parts.append(f"@{host['name'] if host else node.host_id}")
        if not node.enabled:
            label_parts.append("[DISABLED]")

        lines.append(f"{prefix}{' '.join(label_parts)}")

        for child in node.children:
            lines.append(self.print_tree(child, indent + 1, show_ids))

        return '\n'.join(lines)
