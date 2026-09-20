#!/usr/bin/env python3
"""
Schema command - introspect CLI command structure and output JSON schemas.

Enables agent-loop capability discovery without documentation:

    templedb admin schema                  # list all commands
    templedb admin schema vcs              # list vcs subcommands
    templedb admin schema vcs status       # full param schema for vcs status
    templedb admin schema --json           # machine-readable (default for schema)
"""
import json
import sys
import argparse


def _action_to_param(action: argparse.Action) -> dict:
    """Convert an argparse Action to a JSON schema-style param dict."""
    param: dict = {}

    # Name: prefer long option, fall back to dest
    if action.option_strings:
        # e.g. ['-m', '--message'] → '--message'
        long = next((s for s in action.option_strings if s.startswith('--')), action.option_strings[0])
        param['name'] = long
        param['flag'] = True
        param['required'] = action.required if hasattr(action, 'required') else False
    else:
        param['name'] = action.dest
        param['flag'] = False
        param['required'] = action.option_strings == [] and not isinstance(action, argparse._SubParsersAction)

    # Type
    if isinstance(action, argparse._StoreTrueAction) or isinstance(action, argparse._StoreFalseAction):
        param['type'] = 'boolean'
        param['default'] = action.default
    elif action.type == int:
        param['type'] = 'integer'
    elif action.type is not None:
        param['type'] = action.type.__name__
    else:
        param['type'] = 'string'

    if action.nargs in ('*', '+', argparse.REMAINDER):
        param['type'] = f"array<{param['type']}>"

    if action.help and action.help != argparse.SUPPRESS:
        param['help'] = action.help

    if action.choices:
        param['choices'] = list(action.choices)

    if action.default is not None and action.default != argparse.SUPPRESS:
        param['default'] = action.default

    return param


def _parser_to_schema(parser: argparse.ArgumentParser, name: str) -> dict:
    """Recursively convert a parser to a command schema dict."""
    schema = {
        'command': name,
        'help': parser.description or '',
        'params': [],
        'subcommands': [],
    }

    for action in parser._actions:
        # Skip help, version, subparsers
        if isinstance(action, (argparse._HelpAction, argparse._VersionAction)):
            continue
        if isinstance(action, argparse._SubParsersAction):
            for sub_name, sub_parser in action.choices.items():
                schema['subcommands'].append(
                    _parser_to_schema(sub_parser, f"{name} {sub_name}")
                )
            continue
        schema['params'].append(_action_to_param(action))

    return schema


def _find_parser(root_schema: dict, path: list) -> dict | None:
    """Walk the schema tree to find a nested command by path tokens."""
    if not path:
        return root_schema
    target = path[0]
    for sub in root_schema.get('subcommands', []):
        # sub['command'] is like "vcs status", path[0] is "status"
        last_token = sub['command'].split()[-1]
        if last_token == target:
            return _find_parser(sub, path[1:])
    return None


class SchemaCommands:
    def schema(self, args) -> int:
        from cli.core import cli as _cli

        # Build full schema from the registered CLI
        root = _parser_to_schema(_cli.parser, 'templedb')

        # If a specific command path was requested, drill down
        path = getattr(args, 'command_path', None) or []
        if path:
            node = _find_parser(root, path)
            if node is None:
                print(
                    json.dumps({"ok": False, "error": "NOT_FOUND",
                                "message": f"Command not found: {' '.join(path)}"}),
                    file=sys.stderr,
                )
                return 1
            print(json.dumps(node, indent=2))
            return 0

        # Default: flat list of all leaf commands with their params
        flat = _flatten(root)
        print(json.dumps({"ok": True, "commands": flat}, indent=2))
        return 0


def _flatten(node: dict, acc: list | None = None) -> list:
    """Flatten the tree into a list of leaf command dicts."""
    if acc is None:
        acc = []
    if node['subcommands']:
        for sub in node['subcommands']:
            _flatten(sub, acc)
    else:
        acc.append({
            'command': node['command'],
            'help': node['help'],
            'params': node['params'],
        })
    return acc


def register(cli):
    cmd = SchemaCommands()

    schema_parser = cli.register_command(
        'schema',
        cmd.schema,
        help_text='Show JSON schema for CLI commands (for agent/scripting use)',
    )
    schema_parser.add_argument(
        'command_path',
        nargs='*',
        metavar='COMMAND',
        help='Optional command path to inspect (e.g. "vcs status"). '
             'Omit to list all commands.',
    )
    cli.commands['schema'] = cmd.schema
