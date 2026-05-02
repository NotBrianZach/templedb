"""
CLI commands for LLM/AI context generation from TempleDB.
"""
import sys


class LLMCommand:
    def schema(self, args):
        """Print a schema overview for LLM context."""
        from llm_context import TempleDBContext
        with TempleDBContext() as ctx:
            print(ctx.get_schema_overview())
        return 0

    def context(self, args):
        """Generate LLM context for a project."""
        from llm_context import TempleDBContext
        import json
        with TempleDBContext() as ctx:
            data = ctx.get_project_context(args.project)
        print(json.dumps(data, indent=2, default=str))
        return 0

    def prompt(self, args):
        """Generate an LLM prompt for a task, optionally scoped to a project."""
        from llm_context import TempleDBContext
        with TempleDBContext() as ctx:
            print(ctx.generate_llm_prompt(args.task, getattr(args, 'project', None)))
        return 0


def register(cli):
    cmd = LLMCommand()

    import argparse

    llm_parser = cli.subparsers.add_parser("llm", help="LLM/AI context tools")
    llm_sub = llm_parser.add_subparsers(dest="llm_command")

    llm_sub.add_parser("schema", help="Print schema overview for LLM context")

    ctx_p = llm_sub.add_parser("context", help="Generate project context for LLM")
    ctx_p.add_argument("project", help="Project slug")

    prompt_p = llm_sub.add_parser("prompt", help="Generate an LLM prompt for a task")
    prompt_p.add_argument("task", help="Task description")
    prompt_p.add_argument("--project", help="Scope to a specific project")

    def dispatch(args):
        subcmd = getattr(args, 'llm_command', None)
        if subcmd == "schema":
            return cmd.schema(args)
        elif subcmd == "context":
            return cmd.context(args)
        elif subcmd == "prompt":
            return cmd.prompt(args)
        else:
            llm_parser.print_help()
            return 1

    cli.commands["llm"] = dispatch
