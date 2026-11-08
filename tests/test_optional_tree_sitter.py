#!/usr/bin/env python3
"""tree-sitter is optional, and the modules that guard for it must prove it.

Both AST services wrap `import tree_sitter` in try/except and set
HAS_TREE_SITTER, which reads as "works without the grammars installed".
It did not: their method signatures annotate `tree_sitter.Tree` /
`tree_sitter.Node`, and an annotation in a `def` is evaluated when the
class body runs — so importing either module without tree-sitter raised
NameError before any guard could run. Three test modules
(test_community_detection, test_dependency_graph, test_impact_analysis)
failed to *collect* for this reason, which looks identical to "those tests
don't exist" in a summary line.

These tests import both modules with tree_sitter forced absent, so the
guard is exercised rather than asserted in a comment.
"""

import builtins
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

MODULES = [
    "services.symbol_extraction_service",
    "services.dependency_graph_service",
    "services.dependency_graph_builder",
]

TS_PREFIXES = ("tree_sitter",)


@pytest.fixture
def without_tree_sitter(monkeypatch):
    """Make `import tree_sitter*` raise, for this test only."""
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.startswith(TS_PREFIXES):
            raise ImportError(f"{name} blocked by test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    # Drop cached copies so the import actually re-executes, and any
    # already-imported tree_sitter cannot satisfy it from sys.modules.
    for name in list(sys.modules):
        if name.startswith(TS_PREFIXES) or name in MODULES:
            monkeypatch.delitem(sys.modules, name, raising=False)
    yield


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports_without_tree_sitter(without_tree_sitter, module_name):
    mod = importlib.import_module(module_name)  # NameError before the fix
    assert mod.HAS_TREE_SITTER is False


def test_symbol_extractor_reports_the_missing_dependency(without_tree_sitter):
    """Degraded means a clear error, not an AttributeError later on."""
    mod = importlib.import_module("services.symbol_extraction_service")

    with pytest.raises(RuntimeError, match="tree-sitter not available"):
        mod.SymbolExtractor()
