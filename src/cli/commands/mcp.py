"""CLI command for starting MCP server."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cli.core import Command


class MCPCommands(Command):
    """MCP server command handlers"""

    def start_server(self, args) -> int:
        """Start the MCP server"""
        # Import and run MCP server
        from mcp_server import main as mcp_main
        mcp_main()
        return 0


def register(cli):
    """Register MCP commands with CLI"""
    cmd = MCPCommands()

    # Create mcp command group
    mcp_parser = cli.register_command(
        'mcp',
        None,
        help_text='Model Context Protocol server'
    )
    subparsers = mcp_parser.add_subparsers(dest='mcp_subcommand', required=True)

    # mcp serve
    serve_parser = subparsers.add_parser('serve', help='Start MCP server (stdio transport)')
    cli.commands['mcp.serve'] = cmd.start_server
