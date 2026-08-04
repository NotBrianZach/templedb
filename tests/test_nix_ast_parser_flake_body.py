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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
