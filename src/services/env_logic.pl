%% TempleDB Environment Variable Logic
%% Declarative env var resolution, secret propagation, and validation.
%%
%% Facts loaded from DB: env_var/5, secret/3, secret_shared/3, project_sibling/2
%% Queries: resolution, missing vars, propagation chains

:- use_module(library(lists)).
:- use_module(library(http/json)).

%% ══════════════════════════════════════════════════════════════════
%% FACTS — loaded from DB at runtime
%% ══════════════════════════════════════════════════════════════════

%% env_var(Project, VarName, Value, ValueType, Scope).
%%   ValueType: static | compound | secret_ref
%%   Scope: project | global
:- dynamic env_var/5.

%% secret(Project, SecretName, Profile).
:- dynamic secret/3.

%% secret_shared(SourceProject, TargetProject, SecretName).
:- dynamic secret_shared/3.

%% project_sibling(ProjectA, ProjectB).
%%   Bidirectional: if A is sibling of B, B is sibling of A.
:- dynamic project_sibling/2.

%% requires_env(Project, VarName).
%%   From deploy_logic.pl or loaded separately.
:- dynamic requires_env/2.

%% ══════════════════════════════════════════════════════════════════
%% RULES
%% ══════════════════════════════════════════════════════════════════

%% Resolution: project scope overrides global
resolves_to(Project, Var, Value) :-
    env_var(Project, Var, Value, _, project), !.
resolves_to(_, Var, Value) :-
    env_var(global, Var, Value, _, global).

%% A var is available to a project if it resolves
var_available(Project, Var) :- resolves_to(Project, Var, _).

%% A var is a secret reference
is_secret_ref(Project, Var) :-
    env_var(Project, Var, _, secret_ref, _).

%% A var uses a compound template (references other vars)
is_compound(Project, Var) :-
    env_var(Project, Var, _, compound, _).

%% Missing required env vars for a project
missing_env(Project, Var) :-
    requires_env(Project, Var),
    \+ var_available(Project, Var).

%% All vars a project can see (project + global, deduped)
visible_vars(Project, Vars) :-
    findall(V, env_var(Project, V, _, _, project), ProjVars),
    findall(V, (env_var(global, V, _, _, global),
                \+ env_var(Project, V, _, _, project)), GlobalVars),
    append(ProjVars, GlobalVars, Vars).

%% Secret is accessible to project (directly or via sharing)
secret_accessible(Project, Name) :- secret(Project, Name, _).
secret_accessible(Project, Name) :-
    secret_shared(_, Project, Name).

%% Secret propagation chain: who has access to a secret
secret_holders(Name, Holders) :-
    findall(P, secret(P, Name, _), Direct),
    findall(P, secret_shared(_, P, Name), Shared),
    append(Direct, Shared, All),
    sort(All, Holders).

%% Projects sharing secrets with each other
shares_secrets_with(A, B) :-
    secret_shared(A, B, _) ; secret_shared(B, A, _).

%% Sibling var inheritance: var from sibling if not locally defined
inherits_from_sibling(Project, Var, Sibling) :-
    project_sibling(Project, Sibling),
    env_var(Sibling, Var, _, _, project),
    \+ env_var(Project, Var, _, _, project).

%% ══════════════════════════════════════════════════════════════════
%% VALIDATION
%% ══════════════════════════════════════════════════════════════════

%% Project env is valid if no required vars are missing
env_valid(Project) :-
    \+ missing_env(Project, _).

%% Orphaned secrets: secrets not used by any project
orphaned_secret(Name) :-
    secret(_, Name, _),
    \+ requires_env(_, Name).

%% ══════════════════════════════════════════════════════════════════
%% JSON OUTPUT
%% ══════════════════════════════════════════════════════════════════

env_audit_json(Project) :-
    findall(V, missing_env(Project, V), Missing),
    findall(V, is_secret_ref(Project, V), SecretRefs),
    findall(V, is_compound(Project, V), Compounds),
    (env_valid(Project) -> Valid = @(true) ; Valid = @(false)),
    visible_vars(Project, Visible),
    json_write(current_output, json([
        project=Project, valid=Valid,
        missing=Missing, secret_refs=SecretRefs,
        compounds=Compounds, visible_vars=Visible
    ]), [width(0)]), nl.

secret_audit_json :-
    findall(json([name=N, holders=H]),
        (secret(_, N, _), secret_holders(N, H)),
        Secrets),
    sort(Secrets, Unique),
    findall(N, orphaned_secret(N), Orphaned),
    json_write(current_output, json([
        secrets=Unique, orphaned=Orphaned
    ]), [width(0)]), nl.