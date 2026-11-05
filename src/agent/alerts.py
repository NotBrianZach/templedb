"""Filesystem alert drop-files for terminal and blocked agent events.

Why a file and not just the protocol stream: the stdio event stream only
reaches the client that launched the run. An Emacs that was restarted
mid-run, a second frame on another workspace, a `templedb ai agent`
invocation from cron — none of them see `run.completed`, which is
exactly the moment someone wants to be told about. A drop-file is a
channel with no live reader requirement: the producer writes and exits,
and anything that cares (`templedb-agent.el`'s file-notify watcher,
`inotifywait`, a polling script) picks it up whenever it next looks.

One file per alert, written atomically (tempfile in the same directory
then `os.replace`) because a watcher fires on *create* and would
otherwise race a half-written buffer and read invalid JSON. Filenames
are lexicographically time-ordered so `sorted(os.listdir())` is replay
order.

Writes never raise into the event path. An alert is a courtesy; losing
one must not fail the run that produced it, so every filesystem error
is logged and swallowed.

Consumed by the Emacs side in `integrations/emacs/templedb-agent.el`
(`templedb-agent-alerts-mode`). The payload is deliberately
pre-rendered: `title`/`body`/`urgency` are ready to hand to libnotify so
a consumer needs no knowledge of TempleDB event types to show something
useful.
"""
import itertools
import json
import os
import tempfile
from datetime import datetime

import config
from logger import get_logger
from agent import events as _events

logger = get_logger("AgentAlerts")

# Bump when the payload shape changes incompatibly. Consumers should
# ignore a file whose schema they do not recognise rather than guess.
SCHEMA_VERSION = 1

# event type -> (kind, urgency, default headline)
#
# "Terminal + blocked": the run ended, or it is stuck waiting on the
# human. Deliberately NOT every event — tool.started and assistant.delta
# fire hundreds of times per run and alerting on those would train the
# user to ignore the channel.
_SPECS = {
    _events.RUN_COMPLETED:           ("done",         "normal",   "Run completed"),
    _events.RUN_FAILED:              ("failed",       "critical", "Run failed"),
    _events.RUN_INTERRUPTED:         ("interrupted",  "low",      "Run interrupted"),
    _events.AGENT_ASK_QUESTION:      ("ask",          "critical", "Waiting for your answer"),
    _events.PROVIDER_LOGIN_REQUIRED: ("login",        "critical", "Provider login required"),
    _events.PROVIDER_RATE_LIMITED:   ("rate_limited", "normal",   "Provider rate limited"),
}

ALERT_EVENT_TYPES = frozenset(_SPECS)

_HEADLINES = {
    "done":         "Agent finished",
    "failed":       "Agent failed",
    "interrupted":  "Agent interrupted",
    "ask":          "Agent needs you",
    "login":        "Agent blocked: login",
    "rate_limited": "Agent throttled",
}

# Disambiguates two alerts written in the same microsecond by the same
# process (the ask poller and a run thread can land together).
_counter = itertools.count()


def alert_dir():
    """Directory alerts are written to. Created on demand."""
    path = config.AGENT_ALERT_DIR
    try:
        os.makedirs(path, exist_ok=True)
    except (OSError, ValueError) as e:
        # ValueError covers a path the OS layer rejects outright (an
        # embedded NUL from a mangled env var), which is not an OSError.
        logger.debug(f"alert dir {path} unusable: {e}")
    return path


def _session_context(session_id):
    """Human labels for SESSION_ID. Returns (project_slug, title).

    Best-effort: an alert for a session that has just been deleted is
    still worth delivering, so a failed lookup degrades to (None, None)
    rather than dropping the alert.
    """
    try:
        from db_utils import query_one
        row = query_one(
            """SELECT s.title AS title, p.slug AS slug
                 FROM agent_sessions s
                 LEFT JOIN projects p ON s.project_id = p.id
                WHERE s.id = ?""",
            (session_id,),
        )
    except Exception as e:
        logger.debug(f"session context lookup failed for {session_id}: {e}")
        return None, None
    if not row:
        return None, None
    return row["slug"], row["title"]


def build_alert(session_id, run_id, event):
    """Render EVENT as an alert payload, or None if it is not alertable."""
    spec = _SPECS.get(event.get("type") or "")
    if not spec:
        return None
    kind, urgency, headline = spec

    slug, session_title = _session_context(session_id)
    summary = event.get("summary") or headline
    data = event.get("data") or {}

    # The ask payload carries the actual question; that is far more
    # useful on a notification than "Waiting for your answer".
    if kind == "ask":
        questions = data.get("questions") or []
        first = questions[0] if questions else None
        if isinstance(first, dict):
            summary = first.get("question") or first.get("header") or summary

    where = slug or "no project"
    body_lines = [summary]
    if session_title:
        body_lines.append(session_title)
    body_lines.append(f"session #{session_id} · {where}")

    return {
        "schema": SCHEMA_VERSION,
        "kind": kind,
        "urgency": urgency,
        "title": f"{_HEADLINES.get(kind, headline)} — {where}",
        "body": "\n".join(body_lines),
        "event_type": event.get("type"),
        "summary": summary,
        "session_id": session_id,
        "session_title": session_title,
        "project_slug": slug,
        "run_id": run_id,
        "sequence": event.get("sequence", 0),
        "ask_id": data.get("ask_id"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "pid": os.getpid(),
    }


def _filename(alert):
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S.%f")
    return (f"{stamp}-s{alert['session_id']}-{alert['kind']}"
            f"-{alert['pid']}-{next(_counter)}.json")


def write_alert(session_id, run_id, event):
    """Write a drop-file for EVENT. Returns its path, or None.

    None means "nothing to alert about" (not an alertable event type, or
    alerts are disabled) *or* that the write failed — callers treat both
    the same, which is why this never raises.
    """
    if not config.AGENT_ALERTS_ENABLED:
        return None
    alert = build_alert(session_id, run_id, event)
    if alert is None:
        return None

    try:
        # Directory resolution is inside the try with the write: a
        # pathological TEMPLEDB_AGENT_ALERT_DIR (nonexistent parent,
        # unwritable, not a directory) must degrade to "no alert", not
        # raise into the run that produced the event.
        directory = alert_dir()
        target = os.path.join(directory, _filename(alert))
        # Same-directory tempfile so os.replace is a rename, not a copy:
        # a cross-device fallback would not be atomic.
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-alert-")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(alert, fh, default=str)
                fh.write("\n")
            os.replace(tmp, target)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.warning(f"alert write failed ({alert['kind']}): {e}")
        return None

    prune(keep=config.AGENT_ALERT_KEEP)
    return target


def read_alerts(limit=None):
    """Return alert payloads oldest-first, each with its `path`.

    Unparseable files are skipped rather than raising: a reader should
    not be stopped by one bad file, and the producer may still be
    mid-rename on a filesystem where that is visible.
    """
    directory = config.AGENT_ALERT_DIR
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith(".json"))
    except OSError:
        return []
    if limit:
        names = names[-limit:]

    out = []
    for name in names:
        path = os.path.join(directory, name)
        try:
            with open(path) as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            continue
        payload["path"] = path
        out.append(payload)
    return out


def prune(keep=None):
    """Delete all but the newest KEEP alert files. Returns the count removed.

    Nothing acknowledges an alert, so without this the directory grows
    forever. Keeping a window rather than deleting on read means a
    consumer that starts late can still see what it missed.
    """
    if keep is None:
        keep = config.AGENT_ALERT_KEEP
    if keep <= 0:
        return 0
    directory = config.AGENT_ALERT_DIR
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith(".json"))
    except OSError:
        return 0
    removed = 0
    for name in names[:-keep] if len(names) > keep else []:
        try:
            os.unlink(os.path.join(directory, name))
            removed += 1
        except OSError:
            pass
    return removed


def clear():
    """Delete every alert file. Returns the count removed."""
    directory = config.AGENT_ALERT_DIR
    try:
        names = [n for n in os.listdir(directory) if n.endswith(".json")]
    except OSError:
        return 0
    removed = 0
    for name in names:
        try:
            os.unlink(os.path.join(directory, name))
            removed += 1
        except OSError:
            pass
    return removed


def install(service):
    """Register the alert writer on an AgentService.

    Called from `AgentService.__init__` so every consumer of the service
    gets alerts — the stdio protocol server, a CLI run, a cron job —
    rather than only the Emacs client.
    """
    service.add_event_callback(
        lambda session_id, run_id, event: write_alert(session_id, run_id, event)
    )
