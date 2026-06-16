"""
Minimal help_utils stub.
Provides fuzzy command suggestions and not-found messages.
"""
import difflib
import sys


def did_you_mean(cmd: str, choices: list) -> list:
    return difflib.get_close_matches(cmd, choices, n=3, cutoff=0.6)


def show_command_not_found(cmd: str, available: list):
    sys.stderr.write(f"Error: Unknown command '{cmd}'\n")
    suggestions = did_you_mean(cmd, available)
    if suggestions:
        sys.stderr.write("Did you mean?\n")
        for s in suggestions:
            sys.stderr.write(f"  templedb {s}\n")
    else:
        sys.stderr.write("Run 'templedb --help' to see available commands.\n")


class CommandHelp:
    def __init__(self, *args, **kwargs):
        pass

    def print(self, *args, **kwargs):
        pass


class CommandExamples:
    def __init__(self, *args, **kwargs):
        pass

    def print(self, *args, **kwargs):
        pass


class RelatedCommands:
    def __init__(self, *args, **kwargs):
        pass

    def print(self, *args, **kwargs):
        pass
