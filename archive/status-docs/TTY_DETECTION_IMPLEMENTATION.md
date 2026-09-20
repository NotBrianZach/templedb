# TTY Detection Implementation Summary

## Overview

Added comprehensive TTY (terminal) detection to TempleDB to handle non-interactive environments gracefully, particularly Emacs vterm where Claude Code's Ink-based UI fails with cryptic errors.

## Problem Solved

**Original Error:**
```
ERROR Raw mode is not supported on the current process.stdin, which Ink uses as
       input stream by default.
```

This occurred when running `templedb claude` or `templedb tui` inside Emacs vterm, which doesn't expose stdin as a TTY to child processes.

## Solution

Created a comprehensive TTY detection system with helpful, context-aware error messages.

## Files Added

### 1. `src/cli/tty_utils.py`
Core TTY detection utilities:

**Functions:**
- `is_tty()` - Check if stdin is a TTY
- `is_stdout_tty()` - Check if stdout is a TTY
- `is_emacs_vterm()` - Detect Emacs vterm specifically
- `is_emacs()` - Detect any Emacs terminal
- `is_ci_environment()` - Detect CI/CD environments
- `is_piped()` - Check if stdin/stdout is piped
- `get_environment_context()` - Comprehensive environment info
- `get_fallback_message()` - Generate context-specific error messages
- `require_tty()` - Exit with error if not a TTY (with override)
- `print_tty_warning()` - Print warning without exiting

**Features:**
- Automatic environment detection
- Context-aware error messages
- Override support via `TEMPLEDB_FORCE_TTY=1`
- Detailed debug information

### 2. `docs/TTY_DETECTION.md`
Complete documentation covering:

- Problem explanation
- Detection mechanisms
- Error message examples
- Override instructions
- Usage in code
- Technical details (what is a TTY, why vterm doesn't work)

### 3. `test_tty_detection.sh`
Test suite covering:

- Environment detection
- Claude command rejection in non-TTY
- TUI command rejection in non-TTY
- Force override functionality
- Help command still works

## Files Modified

### 1. `src/cli/commands/claude.py`
Added TTY check before launching Claude Code:

```python
from cli.tty_utils import require_tty

def launch_claude(self, args) -> int:
    # Check TTY before launching interactive tool
    require_tty("Claude Code", allow_override=True)
    # ... rest of implementation
```

### 2. `src/cli/commands/tui_launcher.py`
Added TTY check before launching TUI:

```python
from cli.tty_utils import require_tty

def launch_tui(self, args) -> int:
    # Check TTY before launching interactive tool
    require_tty("TempleDB TUI", allow_override=True)
    # ... rest of implementation
```

### 3. `README.md`
Added Troubleshooting section with:

- Problem description
- Common causes
- Solutions
- Override instructions
- Link to detailed docs

## Error Message Example

**Before (from Claude Code's Ink):**
```
ERROR Raw mode is not supported on the current process.stdin
 - Read about how to prevent this error on
   https://github.com/vadimdemedes/ink/#israwmodesupported
```

**After (from TempleDB):**
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
  • stdout.isatty()=False
```

## Detection Logic

The system detects:

1. **Emacs vterm** - Checks `INSIDE_EMACS` environment variable for "vterm"
2. **Emacs (general)** - Checks `INSIDE_EMACS` or `EMACS` variables
3. **CI/CD** - Checks `CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, etc.
4. **Piped** - Uses `sys.stdin.isatty()` and `sys.stdout.isatty()`

## Override for Testing

Users can bypass TTY check:

```bash
export TEMPLEDB_FORCE_TTY=1
templedb claude
```

This allows:
- Testing TTY detection logic
- Special wrapper scripts
- Advanced use cases

Note: The underlying tool (Claude Code, TUI) will likely still fail without a real TTY.

## Test Results

All tests pass in Emacs vterm environment:

```
✓ Environment detection works
✓ Claude command rejects non-TTY
✓ TUI command rejects non-TTY
✓ Force override bypasses check
✓ Help command works without TTY
```

## Usage Guidelines

### For Users

1. **Best practice**: Run interactive tools in real terminals
2. **From Emacs**: Use `M-x ansi-term` instead of vterm
3. **For scripts**: Avoid `templedb claude` and `templedb tui`

### For Developers

To add TTY detection to new commands:

```python
from cli.tty_utils import require_tty, print_tty_warning

# Hard requirement (exits if no TTY)
require_tty("My Tool", allow_override=True)

# Soft warning (continues anyway)
print_tty_warning("My Tool")
```

## Benefits

1. **Clear error messages** - Users know exactly what's wrong and how to fix it
2. **Environment-specific advice** - Different suggestions for vterm vs CI vs pipes
3. **Fail fast** - Detect issue before launching tools that will fail
4. **Debug info** - Easy to troubleshoot terminal issues
5. **Override support** - Advanced users can bypass if needed
6. **Comprehensive detection** - Handles many non-TTY scenarios

## Technical Details

### Why vterm doesn't work

Emacs vterm provides terminal **emulation** but doesn't expose stdin as a TTY device to child processes. This is by design - vterm intercepts terminal control codes to render them in Emacs.

Child processes see:
- `stdin.isatty()` → `False`
- `INSIDE_EMACS=vterm` environment variable

Interactive TUIs like Claude Code need:
- Raw mode access to stdin
- Direct cursor control
- Terminal resize events

These require a real TTY device, not emulation.

### Alternative Emacs Solutions

1. **ansi-term** - Provides actual TTY to child processes
2. **shell-mode** - For non-interactive commands
3. **External terminal** - Run in separate window

## Future Enhancements

Potential improvements:

1. Auto-launch in external terminal from vterm
2. Non-interactive mode for Claude Code
3. Web-based UI alternative
4. More specific terminal type detection
5. Per-command TTY requirements configuration

## Conclusion

This implementation transforms a cryptic, low-level error into a helpful, actionable message that guides users to the solution. It demonstrates thoughtful error handling and user experience design.
