#!/usr/bin/env python3
"""
TempleDB Web GUI — FastAPI + HTMX

Route modules live in gui_pages/ and are registered below. This file is
the app object and the registration list, and deliberately nothing else.

It used to also carry its own copy of CSS, _base, _table, _file_link,
_msg, _colorize_diff, _highlight_template, _backup_history_exists and a
full `@app.get("/")` dashboard — ~600 lines duplicating gui_helpers.py
and gui_pages/dashboard.py. Every page had been migrated to gui_pages/
except the dashboard, whose router was never registered here, so the
dead local route kept serving `/` and the dead local nav kept rendering:
18 links against gui_helpers' 28. Landing on the dashboard showed a
partial sidebar and clicking any entry — which left this file for a
gui_pages route — made the other ten appear. Reported 2026-10-03.

The duplication is what made that possible, so the copies are gone
rather than resynced. One nav, in gui_helpers._base.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from logger import get_logger

logger = get_logger("gui")

from fastapi import FastAPI

app = FastAPI(title="TempleDB", docs_url="/api-docs", redoc_url="/api-redoc")


# The dashboard router registers `/`. It goes first because a route that
# is missing from this list is not a 404 — it is whatever else answers
# that path, which is how this bug hid in plain sight for the length of
# the gui_pages migration.
try:
    from gui_pages.dashboard import router as dashboard_router
    app.include_router(dashboard_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page dashboard: {e}')

# ── Page routers ──
try:
    from gui_pages.actions import router as actions_router
    app.include_router(actions_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page actions: {e}')
try:
    from gui_pages.audit import router as audit_router
    app.include_router(audit_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page audit: {e}')
try:
    from gui_pages.code import router as code_router
    app.include_router(code_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page code: {e}')
try:
    from gui_pages.config_ast import router as config_ast_router
    app.include_router(config_ast_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page config_ast: {e}')
try:
    from gui_pages.deploy import router as deploy_router
    app.include_router(deploy_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page deploy: {e}')
try:
    from gui_pages.docs import router as docs_router
    app.include_router(docs_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page docs: {e}')
try:
    from gui_pages.domains import router as domains_router
    app.include_router(domains_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page domains: {e}')
try:
    from gui_pages.env import router as env_router
    app.include_router(env_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page env: {e}')
try:
    from gui_pages.fleet_sync import router as fleet_sync_router
    app.include_router(fleet_sync_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page fleet_sync: {e}')
try:
    from gui_pages.graph import router as graph_router
    app.include_router(graph_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page graph: {e}')
try:
    from gui_pages.nix import router as nix_router
    app.include_router(nix_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page nix: {e}')
try:
    from gui_pages.nix_store import router as nix_store_router
    app.include_router(nix_store_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page nix_store: {e}')
try:
    from gui_pages.projects import router as projects_router
    app.include_router(projects_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page projects: {e}')
try:
    from gui_pages.schema import router as schema_router
    app.include_router(schema_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page schema: {e}')
try:
    from gui_pages.settings import router as settings_router
    app.include_router(settings_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page settings: {e}')
try:
    from gui_pages.systemd import router as systemd_router
    app.include_router(systemd_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page systemd: {e}')
try:
    from gui_pages.tests import router as tests_router
    app.include_router(tests_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page tests: {e}')
try:
    from gui_pages.vcs import router as vcs_router
    app.include_router(vcs_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page vcs: {e}')
try:
    from gui_pages.reports import router as reports_router
    app.include_router(reports_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page reports: {e}')

try:
    from gui_pages.handoffs import router as handoffs_router
    app.include_router(handoffs_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page handoffs: {e}')

try:
    from gui_pages.pending_asks import router as pending_asks_router
    app.include_router(pending_asks_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page pending_asks: {e}')

try:
    from gui_pages.agent_sessions import router as agent_sessions_router
    app.include_router(agent_sessions_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page agent_sessions: {e}')

try:
    from gui_pages.agent_work_log import router as agent_work_log_router
    app.include_router(agent_work_log_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page agent_work_log: {e}')

try:
    from gui_pages.agent_sections import router as agent_sections_router
    app.include_router(agent_sections_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page agent_sections: {e}')

try:
    from gui_pages.entities import router as entities_router
    app.include_router(entities_router)
except Exception as e:
    logger.warning(f'Failed to load GUI page entities: {e}')

