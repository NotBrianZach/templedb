#!/usr/bin/env python3
"""Parse .nix files into config_nodes using tree-sitter.

Uses tree-sitter-nix to parse Nix source code into a concrete syntax tree,
then converts it into TempleDB config_nodes (the IR).

Usage:
    from nix_ast_parser import parse_nix_file, parse_nix_string
    nodes = parse_nix_file('/path/to/file.nix')
    nodes = parse_nix_string('{ x = 1; }')

Each node is a dict ready for insertion into config_nodes:
    {type, name, value, callee, operator, children: [...]}
"""

import ctypes
import glob
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

_logger = logging.getLogger(__name__)


def _find_grammar():
    """Find the tree-sitter-nix grammar .so file."""
    patterns = [
        '/nix/store/*tree-sitter-nix-grammar*/parser',
        '/nix/store/*tree-sitter-nix*/parser',
    ]
    for pat in patterns:
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]  # latest version
    raise FileNotFoundError(
        "tree-sitter-nix grammar not found. Install with: "
        "nix-shell -p tree-sitter-grammars.tree-sitter-nix"
    )


def _load_parser():
    """Load tree-sitter with the Nix grammar."""
    import tree_sitter as ts

    grammar_path = _find_grammar()
    lib = ctypes.cdll.LoadLibrary(grammar_path)
    tree_sitter_nix = lib.tree_sitter_nix
    tree_sitter_nix.restype = ctypes.c_void_p
    lang = ts.Language(tree_sitter_nix())
    parser = ts.Parser(lang)
    return parser


# ── AST node (in-memory, before DB insertion) ────────────────────────────

@dataclass
class ASTNode:
    """Intermediate AST node before insertion into config_nodes."""
    node_type: str
    name: Optional[str] = None
    value: Optional[str] = None
    callee: Optional[str] = None
    operator: Optional[str] = None
    children: List['ASTNode'] = field(default_factory=list)
    sort_order: int = 0

    def add(self, child: 'ASTNode') -> 'ASTNode':
        child.sort_order = len(self.children)
        self.children.append(child)
        return child


# ── Tree-sitter → ASTNode conversion ─────────────────────────────────────

def _text(node, source: bytes) -> str:
    """Get the source text of a tree-sitter node."""
    return source[node.start_byte:node.end_byte].decode()


def _rawnix_fallback(ts_node, source: bytes, where: str) -> ASTNode:
    """Wrap the raw source text as a RawNix node instead of returning None.

    Called from parse sites where we would otherwise silently drop content
    (LetIn body, With body, FnDef body, Conditional branches, Assert body,
    unhandled apply_expression, parenthesized_expression that we couldn't
    unwrap). Logs a warning so silent-drop stops being invisible — the
    flake `outputs = { ... }: let ... in { ... }` case is the canonical
    example that lost its whole body prior to this fix.
    """
    text = _text(ts_node, source) if ts_node is not None else ""
    _logger.warning(
        "nix_ast_parser: RawNix fallback at %s (tree-sitter type=%s, %d bytes) "
        "— parser has no typed handler for this sub-expression; preserving "
        "verbatim so downstream emit round-trips.",
        where, getattr(ts_node, "type", "<none>"), len(text),
    )
    return ASTNode("RawNix", value=text)


def _convert(ts_node, source: bytes) -> Optional[ASTNode]:
    """Convert a tree-sitter node to an ASTNode recursively."""
    t = ts_node.type

    # ── Literals ──────────────────────────────────────────────────────

    if t == 'integer_expression':
        return ASTNode('Int', value=_text(ts_node, source))

    if t == 'float_expression':
        return ASTNode('Float', value=_text(ts_node, source))

    if t in ('string_expression', 'string_fragment'):
        # Simple string: get the text content (strip quotes)
        text = _text(ts_node, source)
        # Check if it has interpolation children
        interp_children = [c for c in ts_node.children if c.type == 'interpolation']
        if interp_children:
            return _convert_interpolation(ts_node, source)
        # Strip quotes
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        return ASTNode('String', value=text)

    if t == 'indented_string_expression':
        text = _text(ts_node, source)
        interp_children = [c for c in ts_node.children if c.type == 'interpolation']
        if interp_children:
            return _convert_interpolation(ts_node, source)
        # Strip '' delimiters
        if text.startswith("''") and text.endswith("''"):
            text = text[2:-2]
        return ASTNode('MultilineString', value=text)

    if t == 'path_expression':
        return ASTNode('Path', value=_text(ts_node, source))

    if t == 'identifier':
        return ASTNode('Identifier', value=_text(ts_node, source))

    if t == 'variable_expression':
        val = _text(ts_node, source)
        if val == 'true' or val == 'false':
            return ASTNode('Bool', value=val)
        if val == 'null':
            return ASTNode('Null')
        return ASTNode('Identifier', value=val)

    # ── Containers ────────────────────────────────────────────────────

    if t == 'attrset_expression':
        node = ASTNode('AttrSet')
        for child in ts_node.children:
            if child.type == 'binding_set':
                _convert_binding_set(child, source, node)
            elif child.type == 'inherit':
                inh = _convert_inherit(child, source)
                if inh:
                    node.add(inh)
        return node

    if t == 'rec_attrset_expression':
        node = ASTNode('RecAttrSet')
        for child in ts_node.children:
            if child.type == 'binding_set':
                _convert_binding_set(child, source, node)
        return node

    if t == 'list_expression':
        node = ASTNode('List')
        for child in ts_node.children:
            if child.type in ('[', ']'):
                continue
            converted = _convert(child, source)
            if converted:
                node.add(converted)
        return node

    # ── Expressions ───────────────────────────────────────────────────

    if t == 'let_expression':
        node = ASTNode('LetIn')
        # Skip 'let'/'in' keywords and comments between them and the body.
        # A comment sitting between `in` and the real body used to be picked
        # up as the body (via RawNix fallback) — leaving the actual attrset
        # body silently dropped. Filter them out first so the last remaining
        # non-binding_set child is the real body.
        for child in ts_node.children:
            if child.type == 'binding_set':
                for bc in child.children:
                    if bc.type == 'binding':
                        binding = _convert_binding(bc, source)
                        if binding:
                            node.add(binding)
            elif child.type in ('let', 'in', 'comment'):
                continue
            else:
                body = _convert(child, source)
                if body is None:
                    body = _rawnix_fallback(child, source, "LetIn.body")
                body.name = 'body'
                node.add(body)
        return node

    if t == 'if_expression':
        node = ASTNode('Conditional')
        parts = [c for c in ts_node.children if c.type not in ('if', 'then', 'else')]
        if len(parts) >= 3:
            cond = _convert(parts[0], source) or _rawnix_fallback(parts[0], source, "Conditional.cond")
            then = _convert(parts[1], source) or _rawnix_fallback(parts[1], source, "Conditional.then")
            els  = _convert(parts[2], source) or _rawnix_fallback(parts[2], source, "Conditional.else")
            cond.name = 'cond'; node.add(cond)
            then.name = 'then'; node.add(then)
            els.name  = 'else'; node.add(els)
        return node

    if t == 'with_expression':
        parts = [c for c in ts_node.children if c.type not in ('with', ';')]
        if len(parts) >= 2:
            namespace = _text(parts[0], source)
            body = _convert(parts[1], source)
            if body is None:
                body = _rawnix_fallback(parts[1], source, "With.body")
            node = ASTNode('With', callee=namespace)
            node.add(body)
            return node
        return _rawnix_fallback(ts_node, source, "With.malformed")

    if t == 'assert_expression':
        node = ASTNode('Assert')
        parts = [c for c in ts_node.children if c.type not in ('assert', ';')]
        if len(parts) >= 2:
            cond = _convert(parts[0], source) or _rawnix_fallback(parts[0], source, "Assert.cond")
            body = _convert(parts[1], source) or _rawnix_fallback(parts[1], source, "Assert.body")
            cond.name = 'cond'; node.add(cond)
            body.name = 'body'; node.add(body)
        return node

    if t == 'function_expression':
        node = ASTNode('FnDef')
        # Filter out both ':' and '@' — tree-sitter emits '@' as a literal
        # child between formals and the @-bind identifier. Without stripping
        # it, parts[1] became the '@' fragment and got RawNix-wrapped as the
        # body instead of the real let/attrset body.
        parts = [c for c in ts_node.children if c.type not in (':', '@')]
        if len(parts) >= 2:
            # params
            param_node = parts[0]
            if param_node.type == 'identifier':
                params = ASTNode('String', name='params', value=_text(param_node, source))
                node.add(params)
            elif param_node.type == 'formals':
                params = _convert_formals(param_node, source)
                params.name = 'params'
                node.add(params)
            # Optional `@name` bind between formals and body — e.g.
            # `outputs = { self, ... }@inputs: ...`. Tree-sitter emits
            # this as an intermediate identifier child. If we see one,
            # capture the name and shift the body slot forward, so body
            # doesn't get set to the '@'/'inputs' fragment.
            body_idx = 1
            if len(parts) >= 3 and parts[1].type == 'identifier':
                at_name = _text(parts[1], source)
                node.add(ASTNode('String', name='at_bind', value=at_name))
                body_idx = 2
            # body — fall back to RawNix on unhandled sub-expressions
            # rather than silently dropping (the flake outputs FnDef case).
            body = _convert(parts[body_idx], source)
            if body is None:
                body = _rawnix_fallback(parts[body_idx], source, "FnDef.body")
            body.name = 'body'
            node.add(body)
        return node

    if t == 'apply_expression':
        # Function application: fn arg
        children = [c for c in ts_node.children]
        if len(children) >= 2:
            fn = children[0]
            arg = children[1]
            # Get callee as dotted path
            callee = _text(fn, source)
            arg_node = _convert(arg, source)
            node = ASTNode('FnCall', callee=callee)
            if arg_node:
                node.add(arg_node)
            return node
        return None

    if t == 'select_expression':
        # e.attr or e.attr or default
        parts = [c for c in ts_node.children if c.type != '.']
        if len(parts) >= 2:
            expr = _convert(parts[0], source)
            attr = _text(parts[1], source)
            node = ASTNode('Select', value=attr)
            if expr:
                node.add(expr)
            # Check for 'or default'
            if len(parts) >= 3:
                default = _convert(parts[2], source)
                if default:
                    node.add(default)
            return node
        return None

    if t == 'has_attr_expression':
        parts = [c for c in ts_node.children if c.type != '?']
        if len(parts) >= 2:
            expr = _convert(parts[0], source)
            attr = _text(parts[1], source)
            node = ASTNode('HasAttr', value=attr)
            if expr:
                node.add(expr)
            return node
        return None

    if t == 'binary_expression':
        children = list(ts_node.children)
        if len(children) >= 3:
            left = _convert(children[0], source)
            op = _text(children[1], source)
            right = _convert(children[2], source)
            node = ASTNode('BinOp', operator=op)
            if left: node.add(left)
            if right: node.add(right)
            return node
        return None

    if t == 'unary_expression':
        children = list(ts_node.children)
        if len(children) >= 2:
            op = _text(children[0], source)
            operand = _convert(children[1], source)
            node = ASTNode('UnaryOp', operator=op)
            if operand: node.add(operand)
            return node
        return None

    if t == 'parenthesized_expression':
        # Unwrap parens
        for c in ts_node.children:
            if c.type not in ('(', ')'):
                return _convert(c, source)
        return None

    # ── Fallback: store as RawNix ─────────────────────────────────────

    if t in ('comment', '{', '}', '[', ']', '(', ')', ';', '=', ',',
             'let', 'in', 'if', 'then', 'else', 'with', 'assert',
             'rec', ':', 'ellipses', '...', '@'):
        return None  # skip punctuation/keywords

    # Unknown node type → RawNix
    return ASTNode('RawNix', value=_text(ts_node, source))


def _convert_binding_set(ts_node, source: bytes, parent: ASTNode):
    """Convert binding_set children into named children of parent AttrSet."""
    for child in ts_node.children:
        if child.type == 'binding':
            binding = _convert_binding_as_attr(child, source)
            if binding:
                parent.add(binding)
        elif child.type == 'inherit':
            inh = _convert_inherit(child, source)
            if inh:
                parent.add(inh)
        elif child.type == 'comment':
            pass  # skip comments


def _convert_binding_as_attr(ts_node, source: bytes) -> Optional[ASTNode]:
    """Convert a binding (name = expr;) into a named ASTNode.

    For simple attrpaths like 'x = 1', returns the value node with name='x'.
    For nested attrpaths like 'a.b.c = 1', creates nested AttrSets.
    """
    attrpath = None
    value = None
    for child in ts_node.children:
        if child.type == 'attrpath':
            attrpath = child
        elif child.type not in ('=', ';'):
            value = child

    if not attrpath or not value:
        return None

    # Get path parts
    parts = [_text(c, source) for c in attrpath.children if c.type != '.']

    # Convert the value
    val_node = _convert(value, source)
    if not val_node:
        return None

    if len(parts) == 1:
        val_node.name = parts[0]
        return val_node
    else:
        # Nested: a.b.c = val → AttrSet(name=a, children=[AttrSet(name=b, children=[val(name=c)])])
        val_node.name = parts[-1]
        current = val_node
        for part in reversed(parts[:-1]):
            wrapper = ASTNode('AttrSet', name=part)
            wrapper.add(current)
            current = wrapper
        return current


def _convert_binding(ts_node, source: bytes) -> Optional[ASTNode]:
    """Convert a let-binding into a Binding node."""
    attrpath = None
    value = None
    for child in ts_node.children:
        if child.type == 'attrpath':
            attrpath = child
        elif child.type not in ('=', ';'):
            value = child

    if not attrpath or not value:
        return None

    name = _text(attrpath, source)
    val_node = _convert(value, source)
    binding = ASTNode('Binding', name=name)
    if val_node:
        binding.add(val_node)
    return binding


def _convert_inherit(ts_node, source: bytes) -> Optional[ASTNode]:
    """Convert an inherit node."""
    node = ASTNode('Inherit')
    # Check for (source) in inherit
    for child in ts_node.children:
        if child.type == 'parenthesized_expression':
            # inherit (source) names...
            inner = [c for c in child.children if c.type not in ('(', ')')]
            if inner:
                node.callee = _text(inner[0], source)
        elif child.type == 'identifier':
            node.add(ASTNode('Identifier', value=_text(child, source)))
        elif child.type == 'attrpath':
            node.add(ASTNode('Identifier', value=_text(child, source)))
    return node if node.children else None


def _convert_formals(ts_node, source: bytes) -> ASTNode:
    """Convert function formals { x, y, ... } into an ASTNode."""
    import json
    formals = []
    has_ellipsis = False
    at_name = None
    for child in ts_node.children:
        if child.type == 'formal':
            for fc in child.children:
                if fc.type == 'identifier':
                    formals.append(_text(fc, source))
        elif child.type == 'ellipses':
            has_ellipsis = True
        elif child.type == 'identifier':
            at_name = _text(child, source)
    params = {'formals': formals, 'ellipsis': has_ellipsis}
    if at_name:
        params['at'] = at_name
    return ASTNode('String', value=json.dumps(params))


def _convert_interpolation(ts_node, source: bytes) -> ASTNode:
    """Convert a string with interpolation into an Interpolation node."""
    node = ASTNode('Interpolation')
    for child in ts_node.children:
        if child.type in ('"', "''"):
            continue
        elif child.type == 'string_fragment':
            node.add(ASTNode('String', value=_text(child, source)))
        elif child.type == 'interpolation':
            # ${ expr }
            for ic in child.children:
                if ic.type not in ('${', '}'):
                    converted = _convert(ic, source)
                    if converted:
                        node.add(converted)
        elif child.type == 'indented_string_fragment':
            node.add(ASTNode('String', value=_text(child, source)))
        else:
            converted = _convert(child, source)
            if converted:
                node.add(converted)
    # If only one String child, simplify
    if len(node.children) == 1 and node.children[0].node_type == 'String':
        return node.children[0]
    return node


# ── Public API ────────────────────────────────────────────────────────────

_parser = None

def _get_parser():
    global _parser
    if _parser is None:
        _parser = _load_parser()
    return _parser


def parse_nix_string(source: str) -> Optional[ASTNode]:
    """Parse a Nix expression string into an ASTNode tree."""
    parser = _get_parser()
    source_bytes = source.encode()
    tree = parser.parse(source_bytes)
    root = tree.root_node

    if root.has_error:
        # Find error nodes
        errors = []
        def find_errors(n):
            if n.type == 'ERROR' or n.is_missing:
                errors.append(f"  line {n.start_point[0]+1}:{n.start_point[1]}: {n.type}")
            for c in n.children:
                find_errors(c)
        find_errors(root)
        raise SyntaxError(f"Nix parse errors:\n" + "\n".join(errors))

    # The root is source_code, usually has one expression child
    for child in root.children:
        if child.type != 'comment':
            return _convert(child, source_bytes)
    return None


def parse_nix_file(path: str) -> Optional[ASTNode]:
    """Parse a .nix file into an ASTNode tree."""
    source = Path(path).read_text()
    return parse_nix_string(source)


def dump_ast(node: ASTNode, indent: int = 0) -> str:
    """Pretty-print an ASTNode tree."""
    lines = []
    prefix = "  " * indent
    parts = [node.node_type]
    if node.name:
        parts.insert(0, node.name)
    if node.value:
        val = node.value[:50] + '...' if len(node.value) > 50 else node.value
        parts.append(f'= {val}')
    if node.callee:
        parts.append(f'callee={node.callee}')
    if node.operator:
        parts.append(f'op={node.operator}')
    lines.append(f"{prefix}({' '.join(parts)})")
    for child in node.children:
        lines.append(dump_ast(child, indent + 1))
    return '\n'.join(lines)


# ── CLI test ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python nix_ast_parser.py <file.nix|expr>")
        sys.exit(1)

    arg = sys.argv[1]
    if Path(arg).exists():
        ast = parse_nix_file(arg)
    else:
        ast = parse_nix_string(arg)

    if ast:
        print(dump_ast(ast))
    else:
        print("No AST produced")
