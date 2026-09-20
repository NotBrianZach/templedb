#!/usr/bin/env python3
"""
PTY (Pseudo-TTY) Wrapper for Running Interactive Commands

This module provides utilities to run interactive commands that require a TTY
in non-TTY environments like Emacs vterm, piped commands, or CI/CD.

Uses Python's built-in pty module to fork a pseudoterminal.
"""
import os
import sys
import pty
import tty
import select
import signal
import termios
import struct
import fcntl
import subprocess
from typing import List, Optional


def get_terminal_size():
    """Get current terminal size."""
    try:
        # Try to get size from stdout
        size = struct.unpack('HHHH', fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, struct.pack('HHHH', 0, 0, 0, 0)))
        return size[0], size[1]
    except:
        # Default fallback
        return 24, 80


def set_pty_size(fd, rows, cols):
    """Set PTY size."""
    try:
        size = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
    except:
        pass


def run_with_pty(command: List[str], env: Optional[dict] = None) -> int:
    """
    Run a command with a pseudo-TTY attached.

    This allows interactive TUI programs (like Claude Code with Ink)
    to work even when stdin is not a TTY.

    Args:
        command: Command and arguments to run
        env: Optional environment variables to pass

    Returns:
        Exit code of the command
    """
    # Prepare environment
    if env is None:
        env = os.environ.copy()

    def read_and_forward(fd):
        """Read from fd and forward to stdout."""
        try:
            data = os.read(fd, 4096)
            if data:
                os.write(sys.stdout.fileno(), data)
            return data
        except OSError:
            return None

    # Use pty.spawn for simpler PTY management
    try:
        # Fork with PTY
        pid, master_fd = pty.fork()

        if pid == 0:
            # Child process - exec the command
            try:
                os.execvpe(command[0], command, env)
            except Exception as e:
                print(f"Error executing command: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            # Parent process - just forward output from PTY to stdout
            try:
                while True:
                    try:
                        # Wait for data from PTY
                        r, _, _ = select.select([master_fd], [], [], 0.1)
                        if master_fd in r:
                            data = read_and_forward(master_fd)
                            if not data:
                                break
                    except (OSError, select.error):
                        break

            except KeyboardInterrupt:
                pass

            # Wait for child to exit
            try:
                _, status = os.waitpid(pid, 0)
                if os.WIFEXITED(status):
                    return os.WEXITSTATUS(status)
                else:
                    return 1
            except:
                return 1

    except Exception as e:
        print(f"PTY error: {e}", file=sys.stderr)
        return 1


def run_with_script_command(command: List[str], env: Optional[dict] = None) -> int:
    """
    Fallback: Run command using the 'script' utility.

    This is less elegant than the PTY approach but works when
    Python's pty module has issues.

    Args:
        command: Command and arguments to run
        env: Optional environment variables

    Returns:
        Exit code of the command
    """
    if env is None:
        env = os.environ.copy()

    # Build script command
    # script -q -c "command" /dev/null
    script_cmd = ['script', '-q', '-c', ' '.join(command), '/dev/null']

    try:
        result = subprocess.run(script_cmd, env=env)
        return result.returncode
    except Exception as e:
        print(f"Error running with script command: {e}", file=sys.stderr)
        return 1


def main():
    """Test the PTY wrapper."""
    if len(sys.argv) < 2:
        print("Usage: pty_wrapper.py <command> [args...]", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1:]
    exit_code = run_with_pty(command)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
