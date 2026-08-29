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

# Agent-to-user asks (fired by the MCP bridge on behalf of the model).
# See migrations/080_agent_pending_asks.sql for the transport table.
AGENT_ASK_QUESTION = "agent.ask.question"   # data: {ask_id, questions}
AGENT_MESSAGE = "agent.message"             # data: {header, body}

# Agent-writable sections (Findings / Todo / Open Questions / dynamic).
# Emitted by MCP tools via agent_pending_events; consumed by Emacs to
# populate the corresponding agent-owned section. Migration 084.
AGENT_SECTION_FINDING_ADD       = "agent.section.finding.add"     # {id, text, refs?}
AGENT_SECTION_FINDING_REMOVE    = "agent.section.finding.remove"  # {id}
AGENT_SECTION_TODO_ADD          = "agent.section.todo.add"        # {id, text, priority?}
AGENT_SECTION_TODO_DONE         = "agent.section.todo.done"       # {id}
AGENT_SECTION_TODO_REMOVE       = "agent.section.todo.remove"     # {id}
AGENT_SECTION_QUESTION_ADD      = "agent.section.question.add"    # {id, text}
AGENT_SECTION_QUESTION_ANSWERED = "agent.section.question.answered" # {id, answer}
AGENT_SECTION_QUESTION_REMOVE   = "agent.section.question.remove" # {id}
AGENT_SECTION_DYNAMIC_WRITE     = "agent.section.dynamic.write"   # {section, id, text, mode?}
AGENT_SECTION_DYNAMIC_REMOVE    = "agent.section.dynamic.remove"  # {section, id?}

ALL_TYPES = {
    RUN_STARTED, RUN_INTERRUPTED, RUN_COMPLETED, RUN_FAILED,
    ASSISTANT_STARTED, ASSISTANT_DELTA, ASSISTANT_COMPLETED,
    TOOL_STARTED, TOOL_COMPLETED, TOOL_FAILED,
    PROVIDER_RATE_LIMITED, PROVIDER_LOGIN_REQUIRED,
    AGENT_ASK_QUESTION, AGENT_MESSAGE,
    AGENT_SECTION_FINDING_ADD, AGENT_SECTION_FINDING_REMOVE,
    AGENT_SECTION_TODO_ADD, AGENT_SECTION_TODO_DONE, AGENT_SECTION_TODO_REMOVE,
    AGENT_SECTION_QUESTION_ADD, AGENT_SECTION_QUESTION_ANSWERED,
    AGENT_SECTION_QUESTION_REMOVE,
    AGENT_SECTION_DYNAMIC_WRITE, AGENT_SECTION_DYNAMIC_REMOVE,
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
