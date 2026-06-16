#!/usr/bin/env python3
"""
TTY Detection and Fallback Utilities

Provides detection for non-TTY environments (like Emacs vterm, pipes, etc.)
and graceful fallback mechanisms for CLI tools that require interactive terminals.
"""
import os
import sys
from typing import Optional


def is_tty() -> bool:
    """
    Check if stdin is a TTY (interactive terminal).

    Returns:
        True if stdin is a TTY, False otherwise
    """
    return sys.stdin.isatty()


def is_stdout_tty() -> bool:
    """
    Check if stdout is a TTY.

    Returns:
        True if stdout is a TTY, False otherwise
    """
    return sys.stdout.isatty()


def get_terminal_type() -> Optional[str]:
    """
    Detect the terminal type from environment variables.

    Returns:
        Terminal type string or None
    """
    return os.environ.get('TERM')


def is_emacs_vterm() -> bool:
    """
    Check if running inside Emacs vterm.

    Returns:
        True if inside Emacs vterm, False otherwise
    """
    return 'INSIDE_EMACS' in os.environ and 'vterm' in os.environ.get('INSIDE_EMACS', '')


def is_emacs() -> bool:
    """
    Check if running inside any Emacs terminal.

    Returns:
        True if inside Emacs, False otherwise
    """
    return 'INSIDE_EMACS' in os.environ or 'EMACS' in os.environ


def is_ci_environment() -> bool:
    """
    Check if running in a CI/CD environment.

    Returns:
        True if in CI, False otherwise
    """
    ci_vars = ['CI', 'CONTINUOUS_INTEGRATION', 'GITHUB_ACTIONS', 'GITLAB_CI', 'CIRCLECI']
    return any(var in os.environ for var in ci_vars)


def is_piped() -> bool:
    """
    Check if stdin or stdout is piped.

    Returns:
        True if piped, False otherwise
    """
    return not is_tty() or not is_stdout_tty()


def get_environment_context() -> dict:
    """
    Get comprehensive environment context for debugging.

    Returns:
        Dictionary with environment information
    """
    return {
        'is_tty': is_tty(),
        'is_stdout_tty': is_stdout_tty(),
        'terminal_type': get_terminal_type(),
        'is_emacs': is_emacs(),
        'is_emacs_vterm': is_emacs_vterm(),
        'is_ci': is_ci_environment(),
        'is_piped': is_piped(),
    }


def get_fallback_message(tool_name: str = "this tool") -> str:
    """
    Generate a helpful fallback message for non-TTY environments.

    Args:
        tool_name: Name of the tool that requires TTY

    Returns:
        Formatted error message with suggestions
    """
    context = get_environment_context()

    messages = [
        f"\n⚠️  {tool_name} requires an interactive terminal (TTY)",
        "\nCurrent environment:",
    ]

    if context['is_emacs_vterm']:
        messages.append("  • Running inside Emacs vterm (stdin is not a TTY)")
        messages.append("\nSuggestions:")
        messages.append("  1. Run this command in a real terminal (Alacritty, gnome-terminal, etc.)")
        messages.append("  2. Try M-x ansi-term in Emacs instead of vterm")
        messages.append("  3. Use 'C-x C-c' to exit Emacs and run in your shell")
    elif context['is_emacs']:
        messages.append("  • Running inside Emacs")
        messages.append("\nSuggestions:")
        messages.append("  1. Run this command in a real terminal")
        messages.append("  2. Try M-x shell or M-x eshell in Emacs")
    elif context['is_ci']:
        messages.append("  • Running in CI/CD environment")
        messages.append("\nSuggestions:")
        messages.append("  1. Use non-interactive flags if available")
        messages.append("  2. Provide input via command-line arguments")
    elif context['is_piped']:
        messages.append("  • stdin or stdout is piped/redirected")
        messages.append("\nSuggestions:")
        messages.append("  1. Run without piping: $ templedb command")
        messages.append("  2. Use non-interactive mode if available")
    else:
        messages.append("  • stdin is not a TTY (unknown reason)")
        messages.append("\nSuggestions:")
        messages.append("  1. Run in an interactive terminal")
        messages.append("  2. Check that stdin is not redirected")

    messages.append(f"\nDebug info:")
    messages.append(f"  • TERM={context['terminal_type']}")
    messages.append(f"  • stdin.isatty()={context['is_tty']}")
    messages.append(f"  • stdout.isatty()={context['is_stdout_tty']}")

    return "\n".join(messages)


def require_tty(tool_name: str = "This tool", allow_override: bool = True) -> None:
    """
    Require TTY or exit with helpful message.

    Args:
        tool_name: Name of the tool requiring TTY
        allow_override: Allow TEMPLEDB_FORCE_TTY=1 to skip check

    Raises:
        SystemExit: If not a TTY and override not set
    """
    # Allow force override for testing/special cases
    if allow_override and os.environ.get('TEMPLEDB_FORCE_TTY') == '1':
        return

    if not is_tty():
        print(get_fallback_message(tool_name), file=sys.stderr)
        sys.exit(1)


def print_tty_warning(tool_name: str = "This tool") -> None:
    """
    Print a warning about non-TTY environment without exiting.

    Args:
        tool_name: Name of the tool
    """
    if not is_tty():
        print(f"\n⚠️  Warning: {tool_name} works best in an interactive terminal", file=sys.stderr)
        if is_emacs_vterm():
            print("  • Detected Emacs vterm - some features may not work correctly", file=sys.stderr)
        print("", file=sys.stderr)
