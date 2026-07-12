%% TempleDB NixOS Configuration Logic
%% Declarative validation of NixOS host configs, service deps, port conflicts.
%%
%% Facts loaded from DB: service/6, host_service/2, port_alloc/4, systemd_dep/3
%% Queries: config validation, conflict detection, service ordering

:- use_module(library(lists)).
:- use_module(library(http/json)).

%% ══════════════════════════════════════════════════════════════════
%% FACTS — loaded from DB at runtime
%% ══════════════════════════════════════════════════════════════════

%% service(Project, ServiceName, SystemdUnit, RequiresDB, OpensPort, DynamicUser).
:- dynamic service/6.

%% host_service(Host, ServiceName).
%%   Which services run on which host.
:- dynamic host_service/2.

%% systemd_dep(ServiceName, DependsOn, DepType).
%%   DepType: after | requires | wants
:- dynamic systemd_dep/3.

%% port_alloc(Host, Port, ServiceName, Purpose).
:- dynamic port_alloc/4.

%% host(Name, IP, FlakeAttr).
:- dynamic host/3.

%% requires_db(ServiceName, DBType).
%%   DBType: postgresql | redis | mysql
:- dynamic requires_db/2.

%% ══════════════════════════════════════════════════════════════════
%% RULES
%% ══════════════════════════════════════════════════════════════════

%% Port conflict: two services on same host claim same port
port_conflict(Host, Port, ServiceA, ServiceB) :-
    port_alloc(Host, Port, ServiceA, _),
    port_alloc(Host, Port, ServiceB, _),
    ServiceA @< ServiceB.  % avoid duplicate pairs

%% Missing systemd dependency: service requires a DB but doesn't
%% have the DB service in its after/requires chain
missing_systemd_dep(Service, DBService) :-
    requires_db(Service, postgresql),
    DBService = 'postgresql.service',
    \+ systemd_dep(Service, DBService, _).
missing_systemd_dep(Service, DBService) :-
    requires_db(Service, redis),
    DBService = 'redis.service',
    \+ systemd_dep(Service, DBService, _).

%% Service ordering: transitive systemd dependencies
starts_before(A, B) :- systemd_dep(B, A, after).
starts_before(A, B) :- systemd_dep(B, A, requires).
starts_before(A, C) :-
    starts_before(A, B),
    starts_before(B, C),
    A \= C.

%% Circular systemd dependency
systemd_cycle(Service) :- starts_before(Service, Service).

%% Host is valid if no port conflicts and no systemd cycles
valid_host(Host) :-
    host(Host, _, _),
    \+ port_conflict(Host, _, _, _),
    \+ (host_service(Host, S), systemd_cycle(S)).

%% Services on a host that require a database
host_needs_db(Host, DBType) :-
    host_service(Host, Service),
    requires_db(Service, DBType).

%% All services on a host, ordered by systemd deps
host_service_order(Host, Ordered) :-
    findall(S, host_service(Host, S), Services),
    topo_sort_services(Services, Ordered).

topo_sort_services(Services, Ordered) :-
    topo_sort_svcs_(Services, [], Rev),
    reverse(Rev, Ordered).

topo_sort_svcs_([], Acc, Acc).
topo_sort_svcs_(Remaining, Acc, Ordered) :-
    Remaining \= [],
    select(S, Remaining, Rest),
    forall(
        (systemd_dep(S, Dep, _), member(Dep, Remaining)),
        member(Dep, Acc)
    ),
    !,
    topo_sort_svcs_(Rest, [S|Acc], Ordered).
% Fallback if no valid pick (cycle): take first
topo_sort_svcs_([S|Rest], Acc, Ordered) :-
    topo_sort_svcs_(Rest, [S|Acc], Ordered).

%% ══════════════════════════════════════════════════════════════════
%% JSON OUTPUT
%% ══════════════════════════════════════════════════════════════════

validate_host_json(Host) :-
    (valid_host(Host) -> Valid = @(true) ; Valid = @(false)),
    findall(json([port=P, service_a=A, service_b=B]),
        port_conflict(Host, P, A, B), Conflicts),
    findall(json([service=S, missing=D]),
        (host_service(Host, S), missing_systemd_dep(S, D)), MissingDeps),
    findall(S, (host_service(Host, S), systemd_cycle(S)), Cycles),
    findall(DB, host_needs_db(Host, DB), DBs),
    sort(DBs, UniqueDBs),
    json_write(current_output, json([
        host=Host, valid=Valid,
        port_conflicts=Conflicts,
        missing_systemd_deps=MissingDeps,
        systemd_cycles=Cycles,
        requires_databases=UniqueDBs
    ]), [width(0)]), nl.

all_hosts_json :-
    findall(H, host(H, _, _), Hosts),
    maplist(validate_host_result, Hosts, Results),
    json_write(current_output, json([hosts=Results]), [width(0)]), nl.

validate_host_result(Host, json([host=Host, valid=Valid, issues=IssueCount])) :-
    (valid_host(Host) -> Valid = @(true) ; Valid = @(false)),
    findall(_, port_conflict(Host, _, _, _), PC),
    findall(_, (host_service(Host, S), missing_systemd_dep(S, _)), MD),
    findall(_, (host_service(Host, S), systemd_cycle(S)), SC),
    length(PC, N1), length(MD, N2), length(SC, N3),
    IssueCount is N1 + N2 + N3.