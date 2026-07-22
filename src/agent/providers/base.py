"""Base provider interface for Temple Agent.

All providers must implement this interface. Events are yielded as dicts
and normalized by the service before storage/transmission.
"""
from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """Base class for AI providers."""

    @abstractmethod
    def doctor(self):
        """Check provider health. Returns dict with 'ok' bool and 'details' list."""

    @abstractmethod
    def start(self, session_external_id=None, model=None):
        """Start or resume a provider session.

        Args:
            session_external_id: Resume an existing provider session if given.
            model: Model to use (provider-specific).

        Returns:
            dict with 'external_session_id' and any provider metadata.
        """

    @abstractmethod
    def send(self, messages, context=None):
        """Send messages and yield normalized events.

        Args:
            messages: List of message dicts with 'role' and 'content_text'.
            context: Optional context dict (project info, files, etc).

        Yields:
            Event dicts from agent.events.make_event().
        """

    @abstractmethod
    def cancel(self):
        """Cancel the current generation. Best-effort."""

    def resume(self, messages, context=None):
        """Resume after interruption. Default: just send again."""
        return self.send(messages, context)

    def normalize_event(self, raw_event):
        """Convert a provider-specific event into a normalized event.
        Default: return as-is (for providers that already yield normalized events).
        """
        return raw_event

    def cleanup(self):
        """Clean up provider resources. Called on session close."""
        pass
