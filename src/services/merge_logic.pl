%% TempleDB VCS Merge Logic
%% Declarative merge conflict resolution strategies.
%%
%% Facts loaded at merge time: conflict/4, file_type/2
%% Queries: resolution strategy, auto-merge eligibility

:- use_module(library(lists)).
:- use_module(library(http/json)).

%% ══════════════════════════════════════════════════════════════════
%% FACTS — loaded at merge time
%% ══════════════════════════════════════════════════════════════════

%% conflict(FilePath, ConflictType, OursHash, TheirsHash).
%%   ConflictType: both_modified | modify_delete | both_added | content_conflict
:- dynamic conflict/4.

%% file_type(FilePath, Type).
%%   Type: source | config | migration | test | doc | lock | generated | asset
:- dynamic file_type/2.

%% file_ext(FilePath, Extension).
:- dynamic file_ext/2.

%% ══════════════════════════════════════════════════════════════════
%% STRATEGY RULES — which conflicts can be auto-resolved
%% ══════════════════════════════════════════════════════════════════

%% Lock files: always take theirs (regenerated)
strategy(File, take_theirs, high) :-
    file_type(File, lock).

%% Generated files: always take theirs (rebuilt)
strategy(File, take_theirs, high) :-
    file_type(File, generated).

%% Migrations: never auto-merge (order-sensitive)
strategy(File, manual, high) :-
    file_type(File, migration).

%% Assets (images, fonts): take theirs unless we modified
strategy(File, take_theirs, medium) :-
    file_type(File, asset),
    conflict(File, both_modified, _, _).

%% Docs: safe to take ours (we're the author)
strategy(File, take_ours, medium) :-
    file_type(File, doc),
    conflict(File, both_modified, _, _).

%% Config files: both modified → needs review
strategy(File, ai_assisted, medium) :-
    file_type(File, config),
    conflict(File, both_modified, _, _).

%% Source code: content conflicts need AI or manual
strategy(File, ai_assisted, medium) :-
    file_type(File, source),
    conflict(File, content_conflict, _, _).

%% Source code: both modified but no line conflicts → try auto-merge
strategy(File, auto_merge, medium) :-
    file_type(File, source),
    conflict(File, both_modified, _, _),
    \+ conflict(File, content_conflict, _, _).

%% modify_delete: flag for review
strategy(File, manual, high) :-
    conflict(File, modify_delete, _, _).

%% both_added: flag for review
strategy(File, manual, high) :-
    conflict(File, both_added, _, _).

%% Fallback: anything not matched gets manual
strategy(File, manual, low) :-
    conflict(File, _, _, _),
    \+ file_type(File, _).

%% ══════════════════════════════════════════════════════════════════
%% FILE TYPE INFERENCE (from extension)
%% ══════════════════════════════════════════════════════════════════

%% Infer file_type from file_ext if not explicitly declared
file_type(File, lock) :-
    \+ file_type_declared(File),
    (file_ext(File, 'lock') ; file_ext(File, 'lock.json')).

file_type(File, migration) :-
    \+ file_type_declared(File),
    atom_string(File, FileStr),
    (sub_string(FileStr, _, _, _, "migration") ;
     sub_string(FileStr, _, _, _, "migrate")).

file_type(File, doc) :-
    \+ file_type_declared(File),
    (file_ext(File, md) ; file_ext(File, txt) ; file_ext(File, rst)).

file_type(File, config) :-
    \+ file_type_declared(File),
    (file_ext(File, json) ; file_ext(File, yaml) ; file_ext(File, yml) ;
     file_ext(File, toml) ; file_ext(File, nix)).

file_type(File, source) :-
    \+ file_type_declared(File),
    (file_ext(File, py) ; file_ext(File, js) ; file_ext(File, ts) ;
     file_ext(File, tsx) ; file_ext(File, rs) ; file_ext(File, go) ;
     file_ext(File, el)).

file_type(File, asset) :-
    \+ file_type_declared(File),
    (file_ext(File, png) ; file_ext(File, jpg) ; file_ext(File, svg) ;
     file_ext(File, woff2) ; file_ext(File, ico)).

file_type(File, generated) :-
    \+ file_type_declared(File),
    atom_string(File, FileStr),
    (sub_string(FileStr, _, _, _, ".min.") ;
     sub_string(FileStr, _, _, _, "dist/") ;
     sub_string(FileStr, _, _, _, "build/")).

%% Helper: was file_type explicitly declared (not inferred)?
file_type_declared(_) :- fail.

%% ══════════════════════════════════════════════════════════════════
%% QUERIES
%% ══════════════════════════════════════════════════════════════════

%% Can all conflicts be auto-resolved?
all_auto_resolvable :-
    forall(conflict(F, _, _, _),
        (strategy(F, S, _), S \= manual)).

%% Conflicts requiring human attention
needs_human(File) :-
    conflict(File, _, _, _),
    strategy(File, manual, _).

%% ══════════════════════════════════════════════════════════════════
%% JSON OUTPUT
%% ══════════════════════════════════════════════════════════════════

merge_plan_json :-
    findall(json([file=F, conflict_type=CT, strategy=S, confidence=C]),
        (conflict(F, CT, _, _), strategy(F, S, C)),
        Plans),
    findall(F, needs_human(F), Manual),
    (all_auto_resolvable -> AutoOk = @(true) ; AutoOk = @(false)),
    length(Plans, Total),
    length(Manual, ManualCount),
    json_write(current_output, json([
        all_auto_resolvable=AutoOk,
        total_conflicts=Total,
        needs_manual=ManualCount,
        manual_files=Manual,
        plan=Plans
    ]), [width(0)]), nl.