"""Temple Agent event types.

Simple normalized events that flow from providers through the service to clients.
Provider-specific formats are converted into these before reaching Emacs.
"""

# Event type constants
RUN_STARTED = "run.started"
RUN_INTERRUPTED = "run.interrupted"
RUN_COMPLETED = "run.completed"
RUN_FAILED = "run.failed"

ASSISTANT_STARTED = "assistant.started"
ASSISTANT_DELTA = "assistant.delta"
ASSISTANT_COMPLETED = "assistant.completed"

TOOL_STARTED = "tool.started"
TOOL_COMPLETED = "tool.completed"
TOOL_FAILED = "tool.failed"

PROVIDER_RATE_LIMITED = "provider.rate_limited"
PROVIDER_LOGIN_REQUIRED = "provider.login_required"

ALL_TYPES = {
    RUN_STARTED, RUN_INTERRUPTED, RUN_COMPLETED, RUN_FAILED,
    ASSISTANT_STARTED, ASSISTANT_DELTA, ASSISTANT_COMPLETED,
    TOOL_STARTED, TOOL_COMPLETED, TOOL_FAILED,
    PROVIDER_RATE_LIMITED, PROVIDER_LOGIN_REQUIRED,
}

# Session status constants
SESSION_CREATED = "created"
SESSION_RUNNING = "running"
SESSION_WAITING = "waiting"
SESSION_INTERRUPTED = "interrupted"
SESSION_COMPLETED = "completed"
SESSION_FAILED = "failed"
SESSION_CANCELLED = "cancelled"

ALL_SESSION_STATUSES = {
    SESSION_CREATED, SESSION_RUNNING, SESSION_WAITING,
    SESSION_INTERRUPTED, SESSION_COMPLETED, SESSION_FAILED,
    SESSION_CANCELLED,
}

# Run status constants
RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_INTERRUPTED = "interrupted"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_CANCELLED = "cancelled"

# Message roles
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ROLE_TOOL = "tool"
ROLE_TEMPLEDB = "templedb"


def make_event(event_type, summary=None, **data):
    """Create a normalized event dict (without session/run/sequence - added by service)."""
    event = {"type": event_type}
    if summary:
        event["summary"] = summary
    if data:
        event["data"] = data
    return event
