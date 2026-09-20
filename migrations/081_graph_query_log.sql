-- Graph command query log: fuels frecency-ranked candidate suggestions when
-- users invoke a graph subcommand without required positional args.

CREATE TABLE IF NOT EXISTS graph_query_log (
    id INTEGER PRIMARY KEY,
    command TEXT NOT NULL,          -- e.g. 'graph.who-uses', 'graph.callers'
    target_kind TEXT,               -- 'env_var', 'secret', 'symbol', 'file', 'project'
    target_key TEXT,                -- normalized target value (name / path / slug)
    project_slug TEXT,              -- optional scoping context
    args_json TEXT,                 -- full args snapshot (JSON) for future use
    executed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_graph_query_log_lookup
    ON graph_query_log(command, target_kind, target_key);
CREATE INDEX IF NOT EXISTS idx_graph_query_log_project
    ON graph_query_log(project_slug);
CREATE INDEX IF NOT EXISTS idx_graph_query_log_time
    ON graph_query_log(executed_at);
