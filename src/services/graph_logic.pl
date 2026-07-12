%% TempleDB Graph Logic
%% Declarative cross-file dependency resolution and impact analysis.
%%
%% Facts loaded from DB: file_dep/4, symbol/5, symbol_dep/4, cluster_member/3
%% Queries: transitive deps, blast radius, importers, callers, who-uses

:- use_module(library(lists)).
:- use_module(library(http/json)).

%% ══════════════════════════════════════════════════════════════════
%% FACTS — loaded from DB at runtime via assert_fact
%% ══════════════════════════════════════════════════════════════════

%% file_dep(ProjectSlug, ImporterFile, ImportedFile, DepType).
%%   DepType: imports | calls | references | extends | uses_table
:- dynamic file_dep/4.

%% symbol(ProjectSlug, SymbolName, QualifiedName, FilePath, SymbolType).
%%   SymbolType: function | class | method | constant | type
:- dynamic symbol/5.

%% symbol_dep(CallerQName, CalledQName, DepType, Confidence).
%%   DepType: calls | imports | extends | implements | instantiates
:- dynamic symbol_dep/4.

%% cluster_member(ClusterName, SymbolQName, Strength).
:- dynamic cluster_member/3.

%% ══════════════════════════════════════════════════════════════════
%% RULES
%% ══════════════════════════════════════════════════════════════════

%% Transitive file dependencies
file_depends_on(Proj, A, B) :- file_dep(Proj, A, B, _).
file_depends_on(Proj, A, C) :-
    file_dep(Proj, A, B, _),
    file_depends_on(Proj, B, C),
    A \= C.

%% All importers of a file (direct)
importers_of(Proj, File, Importer) :- file_dep(Proj, Importer, File, _).

%% All files imported by a file (direct)
imports_of(Proj, File, Imported) :- file_dep(Proj, File, Imported, _).

%% Transitive symbol dependencies
calls_transitive(A, B) :- symbol_dep(A, B, calls, _).
calls_transitive(A, C) :-
    symbol_dep(A, B, calls, _),
    calls_transitive(B, C),
    A \= C.

%% Callers of a symbol (direct)
caller_of(Symbol, Caller) :- symbol_dep(Caller, Symbol, calls, _).

%% Blast radius: everything affected if Symbol changes
blast_radius(Symbol, Affected) :- caller_of(Symbol, Affected).
blast_radius(Symbol, Affected) :-
    caller_of(Symbol, Mid),
    blast_radius(Mid, Affected),
    Symbol \= Affected.

%% Blast radius count
blast_radius_count(Symbol, Count) :-
    findall(A, blast_radius(Symbol, A), Affs),
    sort(Affs, Unique),
    length(Unique, Count).

%% File blast radius: files affected by changing a file
file_blast_radius(Proj, File, AffectedFile) :-
    file_depends_on(Proj, AffectedFile, File),
    File \= AffectedFile.

%% Circular dependency detection
has_circular_dep(Proj, File) :- file_depends_on(Proj, File, File).
has_circular_symbol_dep(Symbol) :- calls_transitive(Symbol, Symbol).

%% Cluster cohesion: symbols in same cluster that call each other
intra_cluster_dep(Cluster, A, B) :-
    cluster_member(Cluster, A, _),
    cluster_member(Cluster, B, _),
    symbol_dep(A, B, calls, _),
    A \= B.

%% Cross-cluster dependency
cross_cluster_dep(ClusterA, ClusterB, SymA, SymB) :-
    cluster_member(ClusterA, SymA, _),
    cluster_member(ClusterB, SymB, _),
    symbol_dep(SymA, SymB, calls, _),
    ClusterA \= ClusterB.

%% ══════════════════════════════════════════════════════════════════
%% JSON OUTPUT
%% ══════════════════════════════════════════════════════════════════

importers_json(Proj, File) :-
    findall(json([file=F, type=T]), file_dep(Proj, F, File, T), Results),
    json_write(current_output, json([importers=Results]), [width(0)]), nl.

blast_radius_json(Symbol) :-
    findall(A, blast_radius(Symbol, A), Affs),
    sort(Affs, Unique),
    length(Unique, Count),
    json_write(current_output,
        json([symbol=Symbol, affected=Unique, count=Count]),
        [width(0)]), nl.

circular_deps_json(Proj) :-
    findall(F, has_circular_dep(Proj, F), Files),
    sort(Files, Unique),
    json_write(current_output,
        json([project=Proj, circular_files=Unique]),
        [width(0)]), nl.