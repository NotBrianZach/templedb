#!/usr/bin/env python3
"""Invariant: a tracked .nix file's relative references are tracked too.

An import that is missing a file its own flake references is broken, and
it is broken silently — nothing fails until someone evaluates it. That
happened: `nixos_anywhere_vultr_woofs/flake.nix` listed
`modules = [ ./configuration.nix ]` while the project tracked no
configuration.nix, for most of a year. The file existed only in a GitHub
repo that was never registered as a mirror, so every TempleDB-side signal
said "lost", the config was reconstructed from the running host instead,
and woofspetsalon.com spent ~40 minutes in emergency mode on 2026-11-11
because the reconstruction could not know about an import it had never
seen.

These tests pin the extractor's judgement, which is where the value and
the false-positive risk both live.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from cli.commands.entity import EntityCommands

refs = EntityCommands._nix_relative_references


# ── What counts as a reference ────────────────────────────────────────────

def test_the_case_that_caused_the_outage():
    """A flake listing a configuration.nix the project does not have."""
    assert './configuration.nix' in refs(
        'modules = [ disko.nixosModules.disko ./configuration.nix ];')


def test_directory_and_parent_references():
    assert './website' in refs('websiteDir = ./website;')
    assert '../shared/common.nix' in refs('imports = [ ../shared/common.nix ];')


def test_trailing_slash_is_normalised():
    assert refs('x = ./website/;') == {'./website'}


def test_multiple_on_one_line():
    assert refs('imports = [ ./a.nix ./b/c.nix ];') == {'./a.nix', './b/c.nix'}


# ── What must NOT count (false positives are how a check gets ignored) ────

def test_quoted_paths_are_strings_not_references():
    """`"./foo"` is a string in nix; nothing imports it."""
    assert refs('root = "/var/www"; x = "./not-a-path";') == set()


def test_modulespath_concatenation_is_not_a_project_reference():
    """The real-world shape: the path half is a string, the reference is
    a variable pointing outside the project."""
    assert refs('imports = [ (modulesPath + "/profiles/qemu-guest.nix") ];') == set()


def test_absolute_and_angle_paths_are_out_of_scope():
    assert refs('x = <nixpkgs>; y = /nix/store/abc; d = "/dev/vda";') == set()


def test_comments_are_ignored():
    assert refs('# imports = [ ./ghost.nix ];\nx = 1;') == set()
    assert refs('/* ./block-commented.nix */ y = 2;') == set()


def test_interpolated_paths_are_skipped_as_unresolvable():
    assert refs('src = ./${name}/thing.nix;') == set()


def test_shell_inside_indented_strings_is_not_a_nix_path():
    """Both of these are real lines from this database that were false
    positives: shell in an installPhase and in an activation script."""
    assert refs("installPhase = ''\n  cp ./server.js $out/\n  cp ./index.html $out/\n'';") == set()
    assert refs("script = ''\n  if [ -f ./public_key.gpg ]; then gpg --import ./public_key.gpg; fi\n'';") == set()
    # A genuine import beside an indented string still counts.
    assert './real.nix' in refs("imports = [ ./real.nix ];\nx = ''\n ./fake.nix\n'';")


def test_build_artefacts_are_not_reported():
    """`./result` and `./node_modules` are untracked by design.

    Reporting them would put noise in every run — and a check people
    learn to skim is a check that is not running. Both shapes appear in
    this very database (templedb/flake.nix, woofs_projects/shopUI).
    """
    assert refs('x = ./result; y = ./node_modules; z = ./result-doc;') == set()
    assert refs('a = ./dist; b = ./target; c = ./.direnv;') == set()
    # ...but a real path that merely lives beside them still counts.
    assert refs('s = ./server.js;') == {'./server.js'}


def test_url_in_a_string_is_not_a_path():
    assert refs('url = "github:NixOS/nixpkgs/nixos-26.05";') == set()


# ── Resolution semantics, exercised through the real checker ──────────────

@pytest.fixture
def checker(monkeypatch):
    """Drive _check_nix_path_references_are_tracked against fake rows."""
    def run(nix_files, tracked_paths):
        rows = [{'slug': 'p', 'path': p, 'body': b} for p, b in nix_files.items()]
        tracked = [{'slug': 'p', 'path': p} for p in tracked_paths]

        import db_utils

        def fake_query_all(sql, *a, **kw):
            return rows if 'content_text' in sql else tracked

        monkeypatch.setattr(db_utils, 'query_all', fake_query_all)
        return EntityCommands._check_nix_path_references_are_tracked(
            EntityCommands.__new__(EntityCommands))
    return run


def test_missing_reference_is_reported(checker):
    issues = checker({'flake.nix': 'modules = [ ./configuration.nix ];'},
                     ['flake.nix'])
    assert len(issues) == 1
    assert 'configuration.nix is not tracked' in issues[0]
    assert 'incomplete' in issues[0]


def test_present_reference_is_silent(checker):
    assert checker({'flake.nix': 'modules = [ ./configuration.nix ];'},
                   ['flake.nix', 'configuration.nix']) == []


def test_directory_reference_satisfied_by_a_file_underneath(checker):
    """`websiteDir = ./website` is satisfied by website/index.html."""
    assert checker({'flake.nix': 'websiteDir = ./website;'},
                   ['flake.nix', 'website/index.html']) == []


def test_reference_resolves_relative_to_the_referring_file(checker):
    assert checker({'nix/sub.nix': 'imports = [ ./other.nix ];'},
                   ['nix/sub.nix', 'nix/other.nix']) == []
    issues = checker({'nix/sub.nix': 'imports = [ ./other.nix ];'},
                     ['nix/sub.nix', 'other.nix'])
    assert len(issues) == 1 and 'nix/other.nix' in issues[0]


def test_reference_escaping_the_project_root_is_reported(checker):
    issues = checker({'flake.nix': 'imports = [ ../outside.nix ];'}, ['flake.nix'])
    assert len(issues) == 1
    assert 'escapes the project root' in issues[0]


def test_self_reference_is_fine(checker):
    assert checker({'default.nix': 'src = ./.;'}, ['default.nix']) == []
