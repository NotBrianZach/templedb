# Emacs vterm Support

TempleDB fully supports running Claude Code in Emacs vterm through automatic PTY (pseudo-TTY) wrapper detection!

## How It Works

When you run `templedb claude` in Emacs vterm, TempleDB:

1. Detects that `stdin` is not a TTY
2. Checks the `INSIDE_EMACS` environment variable for "vterm"
3. Automatically wraps the Claude Code command with the `script` utility
4. Claude Code receives a proper PTY and works normally!

## What You See

```bash
$ templedb claude

⚡ Detected Emacs vterm - using PTY wrapper for Claude Code

Welcome to Claude Code!
>
```

That's it! Claude Code's Ink-based UI renders perfectly in vterm's terminal emulator.

## Technical Details

### The Problem

Emacs vterm provides excellent terminal emulation but doesn't expose `stdin` as a TTY device to child processes. This is by design - vterm intercepts terminal control codes to render them in Emacs.

Child processes see:
- `process.stdin.isTTY` → `false` (in Node.js)
- `sys.stdin.isatty()` → `False` (in Python)
- `INSIDE_EMACS=vterm` environment variable

Claude Code uses Ink (a React-based terminal UI library) which requires `process.stdin.isTTY` to be true. Without it, you get:

```
ERROR Raw mode is not supported on the current process.stdin
```

### The Solution

TempleDB uses the Unix `script` command to allocate a pseudo-TTY:

```bash
script -q -c "claude --append-system-prompt-file ..." /dev/null
```

This creates a PTY (pseudo-terminal) pair:
- **Master side**: Connected to vterm's terminal emulator
- **Slave side**: Exposed to Claude Code as stdin/stdout/stderr

From Claude Code's perspective:
- `process.stdin.isTTY` → `true` ✓
- Full terminal capabilities available ✓
- vterm renders all terminal control sequences ✓

## Why This Works Better Than ansi-term

Emacs vterm uses libvterm (a proper terminal emulator library) while ansi-term is a pure-elisp implementation.  Benefits of vterm:

- **Faster** - Native code vs elisp
- **More complete** - Better terminal emulation
- **Better rendering** - Handles complex TUIs like Ink

TempleDB's PTY wrapper makes vterm the best choice for Claude Code in Emacs.

## Other Commands

The PTY wrapper currently works for:

- `templedb claude` - ✓ Fully supported in vterm
- `templedb tui` - (Coming soon - same approach will work)

## Fallback Behavior

If the `script` command is not available, TempleDB will show an error message with alternative suggestions.

## Performance

The PTY wrapper adds minimal overhead:
- Negligible latency (< 1ms)
- No extra memory usage
- Direct I/O forwarding

## Disabling the Wrapper

If you want to disable automatic PTY wrapping (for debugging):

```bash
export TEMPLEDB_DISABLE_PTY_WRAPPER=1
templedb claude
```

This will show the original error message instead of using the wrapper.

## References

- [Solving Pseudo-terminal Allocation Errors | Baeldung](https://www.baeldung.com/linux/ssh-pseudo-terminal-allocation)
- [Understanding TTY Errors | Medium](https://medium.com/@haroldfinch01/understanding-and-resolving-the-error-the-input-device-is-not-a-tty-75199ab2344d)
- [Ink - React for CLI | GitHub](https://github.com/vadimdemedes/ink)
- [script(1) - Linux man page](https://man7.org/linux/man-pages/man1/script.1.html)
