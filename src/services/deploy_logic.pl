%% TempleDB Deployment Logic
%% Declarative deployment dependency resolution and validation.
%%
%% This file is the source of truth for deployment rules.
%% SWI-Prolog evaluates these rules; Python just reads the JSON output.
%% AI-resilient: rules are constraints, not procedures.

:- use_module(library(lists)).
:- use_module(library(http/json)).

%% ══════════════════════════════════════════════════════════════════
%% FACTS — loaded from DB at runtime, but can be declared here too.
%% ══════════════════════════════════════════════════════════════════

% Project types: project(Slug, DeployType).
project(system_config, nixos).
project(bza, cloudflare).
project(templedb, nix_build).
project(math_academy_scraper, static).
project(frontend, cloudflare).
project(emacs_config, nixos).

% Cross-project dependencies: depends_on(Project, Dependency).
depends_on(bza, system_config).
depends_on(frontend, bza).
depends_on(templedb, system_config).

% Machine fleet: machine(Name, Host, FlakeAttr).
machine(zMothership2, '192.168.8.170', zMothership2).
machine(zMothership3, '192.168.8.172', zMothership3).
machine(zStation, '192.168.8.100', zStation).

% Tags: tagged(Machine, Tag).
tagged(zMothership2, gpu).
tagged(zMothership2, laptop).
tagged(zMothership3, gpu).
tagged(zMothership3, server).
tagged(zStation, workstation).

% Fleet targeting: requires_tag(Project, Tag).
requires_tag(bza, server).
deploy_to(Machine, Project) :- tagged(Machine, Tag), requires_tag(Project, Tag).

% Health checks: health_check(Project, URL, ExpectedStatus).
health_check(bza, 'https://aireadalong.com', 200).
health_check(templedb, 'http://localhost:8420', 200).

% Required env vars: requires_env(Project, VarName).
requires_env(bza, 'NEXT_PUBLIC_SUPABASE_URL').
requires_env(bza, 'SUPABASE_SERVICE_ROLE_KEY').
requires_env(bza, 'NEXT_PUBLIC_SUPABASE_ANON_KEY').

% Deployment group ordering (within a project)
group_before(migrations, build, bza).
group_before(build, deploy, bza).
group_before(deploy, health_check, bza).
group_before(build, push_secrets, bza).
group_before(push_secrets, deploy, bza).

%% ══════════════════════════════════════════════════════════════════
%% RULES — pure logic, no side effects
%% ══════════════════════════════════════════════════════════════════

% Transitive dependency
depends_on_transitive(A, B) :- depends_on(A, B).
depends_on_transitive(A, C) :- depends_on(A, B), depends_on_transitive(B, C).

% Cycle detection
has_cycle(X) :- depends_on_transitive(X, X).

% All dependencies (transitive closure)
all_deps(Project, Dep) :- depends_on_transitive(Project, Dep).

% Deployability
can_deploy(Project) :-
    project(Project, _),
    \+ has_cycle(Project).

% Readiness (all deps must also be deployable)
ready_to_deploy(Project) :-
    can_deploy(Project),
    forall(depends_on(Project, Dep), ready_to_deploy(Dep)).

% Valid deployment: known project, known type, no cycles
valid_deploy(Project) :-
    project(Project, Type),
    member(Type, [cloudflare, nixos, nix_build, static]),
    \+ has_cycle(Project).

%% ── Topological Sort ─────────────────────────────────────────────
%% topo_sort(+Projects, -Ordered) — deps come first.

topo_sort(Projects, Ordered) :-
    topo_sort_(Projects, [], Rev),
    reverse(Rev, Ordered).

topo_sort_([], Acc, Acc).
topo_sort_(Remaining, Acc, Ordered) :-
    Remaining \= [],
    select(P, Remaining, Rest),
    forall((depends_on(P, D), member(D, Remaining)), member(D, Acc)),
    !,
    topo_sort_(Rest, [P|Acc], Ordered).

%% ── Parallel Groups ─────────────────────────────────────────────
%% parallel_groups(+Projects, -Groups) — waves that can run simultaneously.

parallel_groups(Projects, Groups) :-
    topo_sort(Projects, Ordered),
    par_groups_(Ordered, Projects, [], Groups).

par_groups_([], _, _, []).
par_groups_(Rem, All, Done, [G|Rest]) :-
    Rem \= [],
    include(deps_ok(All, Done), Rem, G),
    G \= [],
    subtract(Rem, G, Rem2),
    append(Done, G, Done2),
    par_groups_(Rem2, All, Done2, Rest).

deps_ok(All, Done, P) :-
    forall((depends_on(P, D), member(D, All)), member(D, Done)).

%% ── Validation (JSON output) ────────────────────────────────────

mk_hc(Slug, json([url=URL, status=Status])) :-
    health_check(Slug, URL, Status).

validate_one(Slug, Json) :-
    (valid_deploy(Slug) -> V = @(true) ; V = @(false)),
    (can_deploy(Slug)   -> C = @(true) ; C = @(false)),
    (has_cycle(Slug)    -> H = @(true) ; H = @(false)),
    findall(D, all_deps(Slug, D), Deps),
    findall(M, deploy_to(M, Slug), Tgts),
    findall(E, requires_env(Slug, E), Envs),
    findall(HC, mk_hc(Slug, HC), HCs),
    (project(Slug, Ty) -> true ; Ty = unknown),
    Json = json([slug=Slug, type=Ty, valid=V, can_deploy=C,
                 has_cycle=H, deps=Deps, targets=Tgts,
                 required_env=Envs, health_checks=HCs]).

%% batch_json: single entry point — all projects, order, groups, validation.
batch_json :-
    findall(P, project(P, _), Ps),
    maplist(validate_one, Ps, Vs),
    topo_sort(Ps, Ord),
    parallel_groups(Ps, Grps),
    R = json([projects=Vs, deploy_order=Ord, parallel_groups=Grps]),
    json_write(current_output, R, [width(0)]), nl.

%% validate_json(+Slug): single project validation as JSON.
validate_json(Slug) :-
    validate_one(Slug, J),
    json_write(current_output, J, [width(0)]), nl.
