#!/usr/bin/env python3
"""
AI commands - consolidated group for Claude Code, vibe, prompt, and MCP.
"""


def register(cli):
    """Register AI commands as subcommands under 'ai' top-level command."""
    from cli.commands.claude import ClaudeCommands
    from cli.commands.vibe import VibeCommands
    from cli.commands.prompt import PromptCommands
    from cli.commands.mcp import MCPCommands

    ai_parser = cli.register_command('ai', None,
        help_text='AI integration (Claude Code, vibe, prompts, MCP)')
    subparsers = ai_parser.add_subparsers(dest='ai_subcommand')

    # --- ai claude ---
    claude_cmd = ClaudeCommands()
    claude_parser = subparsers.add_parser('claude', help='Claude Code integration (launch, hooks, setup)')
    claude_sub = claude_parser.add_subparsers(dest='claude_subcommand')
    cli.commands['ai.claude'] = claude_cmd.launch_claude

    launch_parser = claude_sub.add_parser('launch', help='Launch Claude Code with project context')
    launch_parser.add_argument('--from-db', action='store_true',
                               help='Load prompt from database instead of file')
    launch_parser.add_argument('--project', help='Load project-specific prompt')
    launch_parser.add_argument('--template', help='Template name')
    launch_parser.add_argument('claude_args', nargs='*', help='Additional arguments for claude')
    launch_parser.add_argument('--dry-run', action='store_true',
                               help='Show command without running')
    cli.commands['ai.claude.launch'] = claude_cmd.launch_claude

    hook_parser = claude_sub.add_parser('hook', help='Handle Claude Code hook invocation')
    hook_parser.add_argument('hook_type', nargs='?', help='Hook type (pre-tool, post-tool, notify)')
    hook_parser.add_argument('tool_type', nargs='?', help='Tool type (bash, etc.)')
    cli.commands['ai.claude.hook'] = claude_cmd.hook

    setup_parser = claude_sub.add_parser('setup', help='Set up Claude Code integration')
    setup_parser.add_argument('--force', '-f', action='store_true', help='Overwrite existing settings')
    cli.commands['ai.claude.setup'] = claude_cmd.setup

    status_parser = claude_sub.add_parser('status', help='Show integration status')
    cli.commands['ai.claude.status'] = claude_cmd.status

    # --- ai vibe ---
    vibe_cmd = VibeCommands()
    vibe_parser = subparsers.add_parser('vibe', help='Launch Claude Code with auto-generated project context')
    vibe_sub = vibe_parser.add_subparsers(dest='vibe_subcommand', required=True)

    start_parser = vibe_sub.add_parser('start', help='Start a vibe coding session')
    start_parser.add_argument('projects', nargs='*', help='One or more project names/slugs')
    start_parser.add_argument('--claude-args', nargs='*', default=[], help='Additional arguments for Claude')
    cli.commands['ai.vibe.start'] = vibe_cmd.start

    # --- ai prompt ---
    prompt_cmd = PromptCommands()
    prompt_parser = subparsers.add_parser('prompt', help='Manage AI prompts and templates')
    prompt_sub = prompt_parser.add_subparsers(dest='prompt_subcommand', required=True)

    list_parser = prompt_sub.add_parser('list', help='List prompt templates')
    list_parser.add_argument('--category', help='Filter by category')
    list_parser.add_argument('--active-only', action='store_true',
                            help='Show only active templates')
    cli.commands['ai.prompt.list'] = prompt_cmd.list_templates

    show_parser = prompt_sub.add_parser('show', help='Show template details')
    show_parser.add_argument('name', help='Template name or ID')
    cli.commands['ai.prompt.show'] = prompt_cmd.show_template

    project_list_parser = prompt_sub.add_parser('project-list', help='List project prompts')
    project_list_parser.add_argument('project', help='Project name or slug')
    cli.commands['ai.prompt.project-list'] = prompt_cmd.list_project_prompts

    create_parser = prompt_sub.add_parser('create', help='Create project prompt')
    create_parser.add_argument('project', help='Project name or slug')
    create_parser.add_argument('name', help='Prompt name')
    create_parser.add_argument('--text', help='Prompt text (inline)')
    create_parser.add_argument('--file', help='Read prompt from file')
    create_parser.add_argument('--template', help='Base on template')
    create_parser.add_argument('--format', default='markdown',
                              choices=['markdown', 'json', 'yaml', 'plaintext'])
    create_parser.add_argument('--scope', default='project',
                              choices=['project', 'work-item', 'deployment'])
    create_parser.add_argument('--priority', type=int, default=0)
    create_parser.add_argument('--tags', help='Comma-separated tags')
    create_parser.add_argument('--variables', help='JSON object of variables')
    cli.commands['ai.prompt.create'] = prompt_cmd.create_project_prompt

    render_parser = prompt_sub.add_parser('render', help='Render prompt with variables')
    render_parser.add_argument('name', help='Prompt name')
    render_parser.add_argument('--project', help='Project (for project prompts)')
    render_parser.add_argument('--vars', help='JSON object of variable values')
    render_parser.add_argument('--output', help='Output file (default: stdout)')
    render_parser.add_argument('--log-usage', action='store_true',
                              help='Log this usage in database')
    render_parser.add_argument('--used-by', help='User/agent identifier')
    render_parser.add_argument('--context', help='Usage context')
    cli.commands['ai.prompt.render'] = prompt_cmd.render_prompt

    # --- ai mcp ---
    mcp_cmd = MCPCommands()
    mcp_parser = subparsers.add_parser('mcp', help='Model Context Protocol server')
    mcp_sub = mcp_parser.add_subparsers(dest='mcp_subcommand', required=True)

    serve_parser = mcp_sub.add_parser('serve', help='Start MCP server (stdio transport)')
    cli.commands['ai.mcp.serve'] = mcp_cmd.start_server
