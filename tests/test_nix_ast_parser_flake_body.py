"""Regression tests for the nix_ast_parser body-drop bug.

Prior to commit a2763ce5 the parser silently dropped body content in
FnDef / LetIn / With / Conditional / Assert nodes whenever the body
sub-expression didn't have a typed handler. The canonical case was
flake `outputs = { self, nixpkgs, ... }@inputs: let ... in { ... }` —
the entire body vanished from config_nodes, and `ast build --scope
flake` invisibly emitted an unbuildable outputs stub.

These tests lock the fix in by parsing minimal fixtures and asserting
that:
  1. FnDef nodes always have a `body` child (RawNix fallback if the
     sub-expression can't be typed).
  2. The body content is non-empty and includes the source text.
  3. The @-bind form (`outputs = { ... }@inputs: ...`) preserves the
     let/in body.

The tests skip cleanly if tree-sitter-nix isn't installed — CI without
the grammar shouldn't red-fail on parser tests.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _load_parser():
    """Skip the whole module if the parser or grammar isn't available."""
    try:
        from nix_ast_parser import parse_nix_string
        # Force grammar load now so we surface FileNotFoundError here, not
        # later in each test — cleaner skip vs. individual failures.
        parse_nix_string("1")
        return parse_nix_string
    except (FileNotFoundError, OSError, ImportError, ModuleNotFoundError) as e:
        pytest.skip(f"tree-sitter-nix parser/grammar unavailable: {e}",
                    allow_module_level=True)


parse_nix_string = _load_parser()


def _walk(node, pred):
    """Depth-first walk, yielding every node matching pred."""
    if pred(node):
        yield node
    for c in getattr(node, "children", []) or []:
        yield from _walk(c, pred)


def test_fndef_body_preserved_when_typed():
    """Simple typed body: `x: { a = 1; }` — body must be an AttrSet, not dropped."""
    tree = parse_nix_string("x: { a = 1; }")
    assert tree is not None
    fndefs = list(_walk(tree, lambda n: n.node_type == "FnDef"))
    assert fndefs, "no FnDef found in `x: { a = 1; }`"
    fn = fndefs[0]
    body_children = [c for c in fn.children if c.name == "body"]
    assert body_children, "FnDef has no body child"
    body = body_children[0]
    assert body.node_type in ("AttrSet", "RecAttrSet", "RawNix"), \
        f"body typed as {body.node_type}"


def test_flake_outputs_letin_body_preserved():
    """The canonical prior-bug case: outputs = {...}: let ... in {...}."""
    src = """{
      outputs = { self, nixpkgs, ... }: let
        cfg = nixpkgs.lib.nixosSystem { system = "x86_64-linux"; modules = []; };
      in {
        nixosConfigurations.foo = cfg;
      };
    }"""
    tree = parse_nix_string(src)
    assert tree is not None
    # Find every FnDef and confirm each has a non-empty body.
    fndefs = list(_walk(tree, lambda n: n.node_type == "FnDef"))
    assert fndefs, "outputs FnDef not found"
    for fn in fndefs:
        body_children = [c for c in fn.children if c.name == "body"]
        assert body_children, f"FnDef missing body (would be silent-drop bug)"
        body = body_children[0]
        # RawNix fallback is acceptable — the point is the body isn't gone.
        if body.node_type == "RawNix":
            assert body.value, "RawNix body has empty value"
            assert "nixosConfigurations" in body.value or "let" in body.value, \
                "RawNix body text doesn't include source"
        else:
            assert body.node_type in ("LetIn", "AttrSet", "RecAttrSet"), \
                f"typed body is {body.node_type}; expected LetIn/AttrSet"


def test_flake_at_bind_outputs_body_preserved():
    """The `@inputs` form — the specific pattern that triggered the bug in
    system_config/flake.nix. Previously produced FnDef with body-child count 0."""
    src = """{
      outputs = { self, nixpkgs, ... }@inputs: {
        nixosConfigurations.foo = nixpkgs.lib.nixosSystem { system = "x86_64-linux"; modules = []; };
      };
    }"""
    tree = parse_nix_string(src)
    fndefs = list(_walk(tree, lambda n: n.node_type == "FnDef"))
    assert fndefs, "@-bind FnDef not found"
    for fn in fndefs:
        body_children = [c for c in fn.children if c.name == "body"]
        assert body_children, "@-bind FnDef has no body (silent-drop regression)"


def test_letin_body_preserved():
    """LetIn body drop was the sibling bug — protect against it too."""
    tree = parse_nix_string("let x = 1; in { y = x; }")
    letins = list(_walk(tree, lambda n: n.node_type == "LetIn"))
    assert letins, "LetIn not found"
    for li in letins:
        body_children = [c for c in li.children if c.name == "body"]
        assert body_children, "LetIn missing body"


def test_with_body_preserved():
    """With body drop was another sibling."""
    tree = parse_nix_string("with pkgs; [ a b c ]")
    withs = list(_walk(tree, lambda n: n.node_type == "With"))
    assert withs, "With not found"
    for w in withs:
        assert w.children, "With has no children (body dropped)"


# ── Formal defaults (follow-up (a) from commit 8fdf6bcc) ──────────
# The parser used to drop the default expression from `x ? default`
# formals, so `extraModules ? []` emitted as bare `extraModules` and
# nix-build failed with "attribute missing". These tests lock in the
# dict-form payload the emit side needs to reconstruct `x ? default`.

import json


def _formal_payload(tree):
    """Extract the JSON payload from the FnDef.params String node."""
    fndefs = list(_walk(tree, lambda n: n.node_type == "FnDef"))
    assert fndefs, "no FnDef"
    fn = fndefs[0]
    params = next((c for c in fn.children if c.name == "params"), None)
    assert params is not None, "no params child"
    assert params.value, "params has no value"
    return json.loads(params.value)


def test_formal_without_default_stays_bare_string():
    """Back-compat: a plain formal `x` still serializes as a bare string."""
    tree = parse_nix_string("{ x, y }: x + y")
    payload = _formal_payload(tree)
    assert payload["formals"] == ["x", "y"], payload


def test_formal_with_default_serializes_as_dict():
    """`extraModules ? []` must become {name, default} so emit can reconstruct."""
    tree = parse_nix_string("{ extraModules ? [] }: extraModules")
    payload = _formal_payload(tree)
    assert payload["formals"] == [{"name": "extraModules", "default": "[]"}], payload


def test_mixed_formals_preserve_both_forms():
    """Mix of bare and defaulted formals in one signature.

    The @-bind identifier lives on the FnDef as a sibling `at_bind`
    String node (not inside the formals payload) — tree-sitter emits
    it between the formals block and the body, and the parser stores
    it there so the body slot doesn't get clobbered.
    """
    tree = parse_nix_string(
        "{ self, extraModules ? [], nixpkgs, x ? [ 1 2 ], ... }@inp: 42"
    )
    payload = _formal_payload(tree)
    assert payload["formals"] == [
        "self",
        {"name": "extraModules", "default": "[]"},
        "nixpkgs",
        {"name": "x", "default": "[ 1 2 ]"},
    ], payload
    assert payload["ellipsis"] is True
    # @-bind lives as a sibling on FnDef, not in the formals payload.
    fn = next(_walk(tree, lambda n: n.node_type == "FnDef"))
    at_bind = next((c for c in fn.children if c.name == "at_bind"), None)
    assert at_bind is not None and at_bind.value == "inp"


def test_formal_default_roundtrips_through_emitter():
    """End-to-end: parse → emit produces identical source for defaulted formals."""
    from services.config_compiler import ConfigCompilerService, ConfigNode

    def to_cn(a, cid=[0]):
        cid[0] += 1
        cn = ConfigNode(
            id=cid[0], parent_id=None, name=a.name, sort_order=0,
            node_type=a.node_type, value=a.value, callee=a.callee,
            operator=a.operator,
        )
        for c in a.children:
            cn.children.append(to_cn(c, cid))
        return cn

    svc = ConfigCompilerService.__new__(ConfigCompilerService)
    src = "{ self, extraModules ? [], nixpkgs, ... }@inp: 42"
    tree = parse_nix_string(src)
    out = svc.emit_nix(to_cn(tree))
    assert out == src, f"round-trip mismatch:\n  IN : {src}\n  OUT: {out}"


# ── inherit / inherit_from (follow-up (b) from commit 8fdf6bcc) ───
# The parser silently dropped every `inherit`-in-AttrSet: _convert_inherit
# looked for identifier children directly, but tree-sitter wraps them in
# an `inherited_attrs` node. Additionally, `inherit (src) name` gets a
# distinct top-level type `inherit_from` that binding_set/attrset_expr
# never matched. Result: `{ inherit templedb bza; }` emitted as `{ }`
# in system_config's flake.nix, three times.


def test_inherit_bare_names_preserved():
    """`{ inherit x y; }` — names must survive parse and re-emit."""
    tree = parse_nix_string("{ inherit x y; }")
    inhs = list(_walk(tree, lambda n: n.node_type == "Inherit"))
    assert len(inhs) == 1, f"expected 1 Inherit, got {len(inhs)}"
    names = [c.value for c in inhs[0].children]
    assert names == ["x", "y"], names
    assert inhs[0].callee is None


def test_inherit_from_source_preserved():
    """`{ inherit (pkgs) foo bar; }` — source expression + names both survive."""
    tree = parse_nix_string("{ inherit (pkgs) foo bar; }")
    inhs = list(_walk(tree, lambda n: n.node_type == "Inherit"))
    assert len(inhs) == 1, f"expected 1 Inherit, got {len(inhs)}"
    assert inhs[0].callee == "pkgs", inhs[0].callee
    names = [c.value for c in inhs[0].children]
    assert names == ["foo", "bar"], names


def test_inherit_mixed_with_bindings():
    """Bindings and inherits interleave in the same AttrSet."""
    tree = parse_nix_string(
        "{ a = 1; inherit x; inherit (pkgs) y; b = 2; }"
    )
    attrsets = list(_walk(tree, lambda n: n.node_type == "AttrSet"))
    inhs = [c for c in attrsets[0].children if c.node_type == "Inherit"]
    assert len(inhs) == 2, [c.node_type for c in attrsets[0].children]


def test_inherit_roundtrips_through_emitter():
    """End-to-end: parse → emit produces buildable source with all 3 real
    flake.nix inherit forms preserved."""
    from services.config_compiler import ConfigCompilerService, ConfigNode

    def to_cn(a, cid=[0]):
        cid[0] += 1
        cn = ConfigNode(
            id=cid[0], parent_id=None, name=a.name, sort_order=0,
            node_type=a.node_type, value=a.value, callee=a.callee,
            operator=a.operator,
        )
        for c in a.children:
            cn.children.append(to_cn(c, cid))
        return cn

    svc = ConfigCompilerService.__new__(ConfigCompilerService)
    # Real-world case from system_config/flake.nix line 59.
    src = "{ inherit templedb bza; }"
    tree = parse_nix_string(src)
    out = svc.emit_nix(to_cn(tree))
    assert "inherit templedb bza" in out, \
        f"inherit statement dropped in emit:\n  IN : {src}\n  OUT: {out}"


# ── List element parenthesization ────────────────────────────────
# Prior to this fix the emitter never wrapped list elements in
# parens, so a list containing `import (path) inputs` emitted as
# `[ import (path) inputs ]` — Nix then parsed that as three
# separate list elements (`import`, `(path)`, `inputs`) and the
# outer application never happened. The real-world consequence:
# system_config/flake.nix's modules list ends up with `inputs`
# (an attrset containing bza, templedb, ...) as a raw module,
# producing "cannot coerce a set to a string" at nix-build time.
# Any nixos-rebuild against the emitted flake for zMothership2/3/
# zStation failed until this was fixed.


def test_list_wraps_fncall_in_parens():
    """An `import x y` inside a list needs outer parens or Nix mis-parses."""
    from services.config_compiler import ConfigCompilerService, ConfigNode

    def to_cn(a, cid=[0]):
        cid[0] += 1
        cn = ConfigNode(
            id=cid[0], parent_id=None, name=a.name, sort_order=0,
            node_type=a.node_type, value=a.value, callee=a.callee,
            operator=a.operator,
        )
        for c in a.children:
            cn.children.append(to_cn(c, cid))
        return cn

    svc = ConfigCompilerService.__new__(ConfigCompilerService)
    # Direct real-world regression: modules = [ (import (path) inputs) ... ]
    src = "[ (import (builtins.path { path = ./x; name = \"y\"; }) inputs) hardware ]"
    tree = parse_nix_string(src)
    out = svc.emit_nix(to_cn(tree))
    assert "(import" in out, \
        f"import in list missing paren wrap:\n  IN : {src}\n  OUT: {out}"


def test_list_atomic_elements_no_parens():
    """Atomic elements (identifier, path, attrset) don't get bogus parens."""
    from services.config_compiler import ConfigCompilerService, ConfigNode

    def to_cn(a, cid=[0]):
        cid[0] += 1
        cn = ConfigNode(
            id=cid[0], parent_id=None, name=a.name, sort_order=0,
            node_type=a.node_type, value=a.value, callee=a.callee,
            operator=a.operator,
        )
        for c in a.children:
            cn.children.append(to_cn(c, cid))
        return cn

    svc = ConfigCompilerService.__new__(ConfigCompilerService)
    src = "[ 1 2 x.y ./p { a = 1; } ]"
    tree = parse_nix_string(src)
    out = svc.emit_nix(to_cn(tree))
    for atom in ("1", "2", "x.y", "./p"):
        assert f"({atom})" not in out, \
            f"atomic {atom!r} spuriously parenthesized:\n{out}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
