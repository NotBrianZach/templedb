#!/usr/bin/env python3
"""
JSON output utilities for TempleDB CLI.

Enables --json flag support across all commands. Commands call emit() instead
of print(), and get structured JSON output for free when the flag is set.

Usage in a command:
    from cli.json_output import emit, emit_error

    def status(self, args) -> int:
        data = {"branch": "main", "clean": True, "staged": []}
        return emit(args, data, human_fn=lambda d: print(f"On branch {d['branch']}"))

    def not_found(self, args) -> int:
        return emit_error(args, "NOT_FOUND", "Project 'foo' not found",
                          solution="Run: templedb project list")
"""
import json
import sys
from typing import Any, Callable, Optional


def emit(args, data: dict, human_fn: Optional[Callable[[dict], None]] = None) -> int:
    """
    Output data as JSON or call human_fn for human-readable output.

    Args:
        args:     Parsed argparse namespace (checked for .json flag)
        data:     Dict to serialize. Will have {"ok": true} merged in.
        human_fn: Called with data when not in JSON mode. If None, data is
                  printed as pretty JSON regardless (fallback).

    Returns:
        0 (success exit code)
    """
    if getattr(args, 'json', False):
        payload = {"ok": True, **data}
        print(json.dumps(payload))
    else:
        if human_fn:
            human_fn(data)
        else:
            # No human formatter — just print the dict cleanly
            print(json.dumps(data, indent=2))
    return 0


def emit_error(
    args,
    code: str,
    message: str,
    solution: Optional[str] = None,
    exit_code: int = 1,
    **details: Any,
) -> int:
    """
    Output a structured error to stderr (JSON or human-readable).

    Args:
        args:      Parsed argparse namespace
        code:      Machine-readable error code e.g. "NOT_FOUND", "VALIDATION_ERROR"
        message:   Human-readable error message
        solution:  Optional hint for fixing the problem
        exit_code: Exit code to return (default 1)
        **details: Extra fields included in JSON output only

    Returns:
        exit_code
    """
    if getattr(args, 'json', False):
        payload: dict = {"ok": False, "error": code, "message": message}
        if solution:
            payload["solution"] = solution
        payload.update(details)
        print(json.dumps(payload), file=sys.stderr)
    else:
        print(f"Error: {message}", file=sys.stderr)
        if solution:
            print(f"  Hint: {solution}", file=sys.stderr)
    return exit_code


def emit_list(args, items: list, human_fn: Optional[Callable[[list], None]] = None) -> int:
    """
    Convenience wrapper for list results.

    Args:
        args:     Parsed argparse namespace
        items:    List of dicts to serialize
        human_fn: Called with items list when not in JSON mode

    Returns:
        0
    """
    if getattr(args, 'json', False):
        print(json.dumps({"ok": True, "items": items, "count": len(items)}))
    else:
        if human_fn:
            human_fn(items)
        else:
            print(json.dumps(items, indent=2))
    return 0
