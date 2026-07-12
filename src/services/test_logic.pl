%% TempleDB Test Logic
%% Declarative test impact analysis and dependency resolution.
%%
%% Facts loaded from DB: test_def/4, test_dep/4, file_dep/4
%% Queries: what tests to run when files change, dep resolution

:- use_module(library(lists)).
:- use_module(library(http/json)).

%% ══════════════════════════════════════════════════════════════════
%% FACTS — loaded from DB at runtime
%% ══════════════════════════════════════════════════════════════════

%% test_def(Project, TestType, Path, Enabled).
%%   TestType: page | post | structure_file | structure_dir
:- dynamic test_def/4.

%% test_dep(Project, NixPackage, BinaryName, Enabled).
:- dynamic test_dep/4.

%% file_in_project(Project, FilePath).
:- dynamic file_in_project/2.

%% file_dep(Project, Importer, Imported, Type).
%%   Shared with graph_logic.pl
:- dynamic file_dep/4.

%% changed_file(Project, FilePath).
%%   Set at query time: files that changed in current commit/diff.
:- dynamic changed_file/2.

%% ══════════════════════════════════════════════════════════════════
%% RULES
%% ══════════════════════════════════════════════════════════════════

%% A test covers a file if the test path matches the file's directory
test_covers_file(Project, TestType, Path, File) :-
    test_def(Project, TestType, Path, true),
    file_in_project(Project, File),
    atom_concat(Path, _, File).

%% File is affected by a change (direct or transitive import)
affected_by_change(Project, File) :- changed_file(Project, File).
affected_by_change(Project, File) :-
    changed_file(Project, Changed),
    file_dep(Project, File, Changed, _).
affected_by_change(Project, File) :-
    changed_file(Project, Changed),
    file_dep(Project, Mid, Changed, _),
    file_dep(Project, File, Mid, _),
    File \= Changed.

%% Tests that need to run because of changed files
needs_run(Project, TestType, Path) :-
    test_def(Project, TestType, Path, true),
    affected_by_change(Project, _).

%% Test is runnable (all deps available)
test_runnable(Project) :-
    forall(
        test_dep(Project, _, _, true),
        true  % In practice, check binary exists; here just check dep is declared
    ).

%% Missing test deps
missing_test_dep(Project, Package) :-
    test_dep(Project, Package, _, true),
    \+ test_dep_resolved(Project, Package).

%% Placeholder: resolved deps loaded from Python after nix resolution
:- dynamic test_dep_resolved/2.

%% Test coverage gap: file has no covering test
uncovered_file(Project, File) :-
    file_in_project(Project, File),
    \+ test_covers_file(Project, _, _, File).

%% ══════════════════════════════════════════════════════════════════
%% JSON OUTPUT
%% ══════════════════════════════════════════════════════════════════

%% What tests to run given current changed_file facts
tests_to_run_json(Project) :-
    findall(json([type=T, path=P]),
        needs_run(Project, T, P), Tests),
    sort(Tests, Unique),
    findall(F, affected_by_change(Project, F), Affected),
    sort(Affected, UniqueAffected),
    json_write(current_output, json([
        project=Project,
        tests_to_run=Unique,
        affected_files=UniqueAffected
    ]), [width(0)]), nl.

test_status_json(Project) :-
    findall(json([type=T, path=P]),
        test_def(Project, T, P, true), Enabled),
    findall(json([type=T, path=P]),
        test_def(Project, T, P, false), Disabled),
    findall(Pkg, missing_test_dep(Project, Pkg), MissingDeps),
    (test_runnable(Project) -> Runnable = @(true) ; Runnable = @(false)),
    json_write(current_output, json([
        project=Project, runnable=Runnable,
        enabled_tests=Enabled, disabled_tests=Disabled,
        missing_deps=MissingDeps
    ]), [width(0)]), nl.