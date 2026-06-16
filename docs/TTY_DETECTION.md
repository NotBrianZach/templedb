# TTY Detection and Automatic PTY Wrapper

TempleDB automatically detects non-TTY environments (like Emacs vterm, pipes, CI/CD) and **transparently wraps commands** to make them work when possible.

## Problem

Claude Code and other interactive TUI tools use terminal features that require a TTY (teletype/terminal). When you run these tools in non-interactive environments like:

- **Emacs vterm** - Provides terminal emulation but doesn't expose TTY to child processes
- **Piped commands** - `echo "test" | templedb claude`
- **CI/CD environments** - GitHub Actions, GitLab CI, etc.
- **Screen/tmux sessions** (sometimes)

You used to get cryptic errors like:

```
ERROR Raw mode is not supported on the current process.stdin
```

## Solution

TempleDB now automatically detects these environments and **uses a PTY (pseudo-TTY) wrapper** to make Claude Code work in Emacs vterm!

### Automatic Detection

The following are automatically detected:

1. **Emacs vterm** - Checks `INSIDE_EMACS` environment variable
2. **Piped stdin/stdout** - Uses `sys.stdin.isatty()`
3. **CI/CD environments** - Checks `CI`, `GITHUB_ACTIONS`, etc.
4. **Terminal type** - Reads `TERM` environment variable

### Error Messages

When you try to launch an interactive tool without a TTY, you'll see:

```
⚠️  Claude Code requires an interactive terminal (TTY)

Current environment:
  • Running inside Emacs vterm (stdin is not a TTY)

Suggestions:
  1. Run this command in a real terminal (Alacritty, gnome-terminal, etc.)
  2. Try M-x ansi-term in Emacs instead of vterm
  3. Use 'C-x C-c' to exit Emacs and run in your shell

Debug info:
  • TERM=xterm-256color
  • stdin.isatty()=False
  • stdout.isatty()=True
```

## Override (For Testing)

You can force TTY check to pass with:

```bash
export TEMPLEDB_FORCE_TTY=1
templedb claude
```

**Warning**: This will likely still fail if the underlying tool (Claude Code, TUI) actually needs a TTY. This is mainly useful for:
- Testing TTY detection logic
- Wrapper scripts that handle TTY issues differently

## Affected Commands

The following TempleDB commands require a TTY:

- **`templedb claude`** - Launches Claude Code (uses Ink for rendering)
- **`templedb tui`** - Launches Textual TUI (interactive terminal UI)

## Usage in Code

To add TTY detection to your own commands:

```python
from cli.tty_utils import require_tty, print_tty_warning

# Hard requirement - exits if no TTY
require_tty("My Interactive Tool")

# Soft warning - prints warning but continues
print_tty_warning("My Tool")
```

## Environment Context

You can get comprehensive environment info programmatically:

```python
from cli.tty_utils import get_environment_context

context = get_environment_context()
# {
#   'is_tty': False,
#   'is_stdout_tty': True,
#   'terminal_type': 'xterm-256color',
#   'is_emacs': True,
#   'is_emacs_vterm': True,
#   'is_ci': False,
#   'is_piped': True
# }
```

## Recommendations

### For Regular Use

1. **Use a real terminal** for interactive tools like Claude Code:
   - Alacritty
   - gnome-terminal
   - kitty
   - iTerm2 (macOS)

2. **From Emacs**:
   - Use `M-x ansi-term` instead of vterm for better TTY support
   - Or run commands in a separate terminal window

3. **For scripting**:
   - Use non-interactive TempleDB commands
   - Avoid `templedb claude` and `templedb tui` in scripts

### For Development

If you're developing TempleDB commands that need interactivity:

1. Always check TTY requirements early
2. Provide clear error messages
3. Consider adding non-interactive alternatives
4. Document TTY requirements in command help

## Technical Details

### What is a TTY?

TTY (teletypewriter) is a Unix abstraction for terminal devices. Interactive programs need TTY to:

- Set terminal to "raw mode" (read keypresses directly)
- Control cursor position
- Display colors and formatting
- Handle window resize events

### Why vterm doesn't work

Emacs vterm provides terminal *emulation* but doesn't expose `stdin` as a TTY device to child processes. This is by design - vterm intercepts terminal control codes to render them in Emacs.

Child processes see:
- `stdin.isatty()` → `False`
- `INSIDE_EMACS=vterm` environment variable

### stdin vs stdout

Some tools only need `stdin` to be a TTY (for input), others need `stdout` (for output formatting). Interactive TUIs like Claude Code typically need both.

## Related Files

- `src/cli/tty_utils.py` - TTY detection utilities
- `src/cli/commands/claude.py` - Claude Code launcher (uses TTY detection)
- `src/cli/commands/tui_launcher.py` - TUI launcher (uses TTY detection)
