"""Tests for ConfigCompilerService deep-merge resolver.

Design: docs/AST_MERGE_SEMANTICS.md
Implementation: src/services/config_compiler.py:_resolve_position

These tests exercise `_resolve_position` directly with hand-built ConfigNode
fixtures. No DB required.
"""
import sys
from pathlib import Path
from typing import List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from services.config_compiler import ConfigCompilerService, ConfigNode


# Priority ranks used across tests. Shared is rank 0, host X is rank 1.
SHARED = None
HOST_X = 1
PRIO = {SHARED: 0, HOST_X: 1}
SVC = ConfigCompilerService()


_id_counter = [0]
def _node(node_type, name=None, value=None, host_id=None, children=None):
    _id_counter[0] += 1
    n = ConfigNode(
        id=_id_counter[0], parent_id=None, name=name, sort_order=0,
        node_type=node_type, value=value, host_id=host_id, children=[],
    )
    for i, c in enumerate(children or []):
        c.parent_id = n.id
        c.sort_order = i
        n.children.append(c)
    return n


def _index(*roots):
    """Build a children_index from any number of root ConfigNodes."""
    idx = {}
    def walk(n):
        for c in n.children:
            idx.setdefault(n.id, []).append(c)
            walk(c)
    for r in roots:
        walk(r)
    return idx


def _names(children):
    """Return sorted list of resolved-child names for stable assertions."""
    return sorted(c.name for c in children if c.name)


def _values_by_name(children):
    return {c.name: c.value for c in children if c.name}


def test_list_merge_concatenates():
    """shared [a, b] + host [c, d] → [a, b, c, d]"""
    shared = _node('List', name='pkgs', host_id=SHARED, children=[
        _node('Identifier', value='a'), _node('Identifier', value='b')])
    host = _node('List', name='pkgs', host_id=HOST_X, children=[
        _node('Identifier', value='c'), _node('Identifier', value='d')])
    idx = _index(shared, host)
    merged = SVC._resolve_position([shared, host], idx, PRIO)
    assert merged.node_type == 'List'
    assert [c.value for c in merged.children] == ['a', 'b', 'c', 'd']


def test_attrset_deep_merge():
    """shared { a = 1 } + host { b = 2 } → { a = 1; b = 2 }"""
    shared = _node('AttrSet', name='foo', host_id=SHARED, children=[
        _node('Int', name='a', value='1')])
    host = _node('AttrSet', name='foo', host_id=HOST_X, children=[
        _node('Int', name='b', value='2')])
    idx = _index(shared, host)
    merged = SVC._resolve_position([shared, host], idx, PRIO)
    assert merged.node_type == 'AttrSet'
    assert _values_by_name(merged.children) == {'a': '1', 'b': '2'}


def test_leaf_last_wins():
    """shared bool=false + host bool=true → true"""
    shared = _node('Bool', name='enable', value='false', host_id=SHARED)
    host = _node('Bool', name='enable', value='true', host_id=HOST_X)
    idx = _index(shared, host)
    merged = SVC._resolve_position([shared, host], idx, PRIO)
    assert merged.value == 'true'
    assert merged.node_type == 'Bool'


def test_deep_nested_leaf_override():
    """shared: foo.b.c = 1 + host: foo.b.c = 2, foo.b.d = 3 → foo.b.{c=2, d=3}"""
    shared_b = _node('AttrSet', name='b', host_id=SHARED, children=[
        _node('Int', name='c', value='1')])
    shared = _node('AttrSet', name='foo', host_id=SHARED, children=[
        _node('Int', name='a', value='1'), shared_b])
    host_b = _node('AttrSet', name='b', host_id=HOST_X, children=[
        _node('Int', name='c', value='2'),
        _node('Int', name='d', value='3'),
    ])
    host = _node('AttrSet', name='foo', host_id=HOST_X, children=[host_b])
    idx = _index(shared, host)
    merged = SVC._resolve_position([shared, host], idx, PRIO)
    assert _names(merged.children) == ['a', 'b']  # both survive
    assert merged.get_child('a').value == '1'
    b = merged.get_child('b')
    assert _values_by_name(b.children) == {'c': '2', 'd': '3'}  # host c wins, d added


def test_type_mismatch_host_wins():
    """shared: x = "s" + host: x = { a = 1 } → { a = 1 }"""
    shared = _node('String', name='x', value='"s"', host_id=SHARED)
    host = _node('AttrSet', name='x', host_id=HOST_X, children=[
        _node('Int', name='a', value='1')])
    idx = _index(shared, host)
    merged = SVC._resolve_position([shared, host], idx, PRIO)
    assert merged.node_type == 'AttrSet'
    assert _values_by_name(merged.children) == {'a': '1'}


def test_no_host_binding_shared_used():
    """shared alone → shared value"""
    shared = _node('String', name='stateVersion', value='"25.11"', host_id=SHARED)
    idx = _index(shared)
    merged = SVC._resolve_position([shared], idx, PRIO)
    assert merged.value == '"25.11"'


def test_no_shared_binding_host_used():
    """host alone → host value"""
    host = _node('Bool', name='enable', value='true', host_id=HOST_X)
    idx = _index(host)
    merged = SVC._resolve_position([host], idx, PRIO)
    assert merged.value == 'true'


def test_empty_lists_still_concat():
    """[] + [x] → [x]; [x] + [] → [x]"""
    shared_empty = _node('List', name='pkgs', host_id=SHARED, children=[])
    host_one = _node('List', name='pkgs', host_id=HOST_X, children=[
        _node('Identifier', value='x')])
    idx = _index(shared_empty, host_one)
    m1 = SVC._resolve_position([shared_empty, host_one], idx, PRIO)
    assert [c.value for c in m1.children] == ['x']

    _id_counter[0] = 100
    shared_one = _node('List', name='pkgs', host_id=SHARED, children=[
        _node('Identifier', value='x')])
    host_empty = _node('List', name='pkgs', host_id=HOST_X, children=[])
    idx = _index(shared_one, host_empty)
    m2 = SVC._resolve_position([shared_one, host_empty], idx, PRIO)
    assert [c.value for c in m2.children] == ['x']


def test_letin_type_mismatch_host_wins():
    """LetIn should NOT be merged as if it were an AttrSet.
    shared: LetIn(with vol=... in { ... }) + host: AttrSet { ... } → host AttrSet."""
    shared = _node('LetIn', name='actkbd', host_id=SHARED, children=[
        _node('Binding', name='vol', children=[_node('String', value='"1%"')]),
        _node('AttrSet', children=[_node('Bool', name='enable', value='true')]),
    ])
    host = _node('AttrSet', name='actkbd', host_id=HOST_X, children=[
        _node('Bool', name='enable', value='true'),
        _node('List', name='bindings', children=[]),
    ])
    idx = _index(shared, host)
    merged = SVC._resolve_position([shared, host], idx, PRIO)
    assert merged.node_type == 'AttrSet'
    assert _names(merged.children) == ['bindings', 'enable']
    # LetIn's `vol` binding and unnamed AttrSet body must NOT leak into the merged output
    assert 'vol' not in _names(merged.children)


def test_with_same_callee_concat_inner():
    """shared: with pkgs; [a] + host: with pkgs; [b] → with pkgs; [a b]"""
    shared_list = _node('List', children=[_node('Identifier', value='a')])
    shared_with = _node('With', name='systemPackages', host_id=SHARED, children=[shared_list])
    shared_with.callee = 'pkgs'
    host_list = _node('List', children=[_node('Identifier', value='b')])
    host_with = _node('With', name='systemPackages', host_id=HOST_X, children=[host_list])
    host_with.callee = 'pkgs'
    idx = _index(shared_with, host_with)
    merged = SVC._resolve_position([shared_with, host_with], idx, PRIO)
    assert merged.node_type == 'With'
    assert merged.callee == 'pkgs'
    # Should have one merged List child with [a, b]
    assert len(merged.children) == 1
    assert merged.children[0].node_type == 'List'
    assert [c.value for c in merged.children[0].children] == ['a', 'b']


def test_with_different_callees_host_wins():
    """shared: with pkgs; [a] + host: with lib; [b] → host's `with lib; [b]`"""
    shared_list = _node('List', children=[_node('Identifier', value='a')])
    shared_with = _node('With', name='x', host_id=SHARED, children=[shared_list])
    shared_with.callee = 'pkgs'
    host_list = _node('List', children=[_node('Identifier', value='b')])
    host_with = _node('With', name='x', host_id=HOST_X, children=[host_list])
    host_with.callee = 'lib'
    idx = _index(shared_with, host_with)
    merged = SVC._resolve_position([shared_with, host_with], idx, PRIO)
    assert merged.callee == 'lib'
    assert [c.value for c in merged.children[0].children] == ['b']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
