# Claude CLI vterm Helpers for Emacs

Emacs Lisp helpers to improve the Claude CLI experience in vterm by solving the conversation history scrolling issue.

## The Problem

When using Claude CLI in Emacs vterm with a long conversation history, pasting content and pressing Enter causes the terminal to scroll through the entire conversation history before processing your input. This is annoying and slow.

## The Solution

This package provides several approaches to solve the scrolling issue:

1. **Clear scrollback before input** - Removes old conversation lines
2. **Smart paste and send** - Manages the paste operation intelligently
3. **Scrollback limiting** - Keeps buffer size manageable
4. **Alternate screen buffer** - Uses terminal features to isolate input

## Installation

### Option 1: Direct Load

Add to your `~/.emacs.d/init.el`:

```elisp
;; Load Claude vterm helpers
(add-to-list 'load-path "/path/to/templeDB/integrations/emacs")

(with-eval-after-load 'vterm
  (require 'claude-vterm-helpers)
  (claude-vterm-setup))
```

### Option 2: use-package

```elisp
(use-package claude-vterm-helpers
  :load-path "/path/to/templeDB/integrations/emacs"
  :after vterm
  :config
  (claude-vterm-setup))
```

### Option 3: Doom Emacs

Add to `~/.doom.d/packages.el`:

```elisp
(package! claude-vterm-helpers
  :recipe (:local-repo "/path/to/templeDB/integrations/emacs"))
```

Add to `~/.doom.d/config.el`:

```elisp
(use-package! claude-vterm-helpers
  :after vterm
  :config
  (claude-vterm-setup))
```

## Usage

### Automatic Mode

The package automatically detects when you're running Claude CLI in vterm and enables `claude-vterm-mode`.

### Keybindings

Once enabled, these keybindings are available in vterm buffers:

| Key         | Function                          | Description                                    |
|-------------|-----------------------------------|------------------------------------------------|
| `C-c C-v`   | `claude-vterm-paste-and-send`     | Paste from clipboard and send (no scroll)      |
| `C-c C-l`   | `claude-vterm-clear-scrollback`   | Clear scrollback buffer                        |
| `C-c C-s`   | `claude-vterm-smart-send`         | Send region or current line                    |
| `C-c C-c`   | `claude-vterm-configure-for-claude` | Configure vterm for optimal Claude usage     |
| `C-c C-a`   | `claude-vterm-use-alternate-screen` | Switch to alternate screen (advanced)        |

### Manual Usage

```elisp
;; Enable in current vterm buffer
M-x claude-vterm-mode

;; Paste without scrolling
M-x claude-vterm-paste-and-send

;; Clear scrollback before next input
M-x claude-vterm-clear-scrollback

;; Configure buffer for Claude
M-x claude-vterm-configure-for-claude
```

## Configuration

### Customize Options

```elisp
;; Clear scrollback automatically before pasting (default: t)
(setq claude-vterm-clear-scrollback-before-paste t)

;; Maximum scrollback lines to keep (default: 1000)
(setq claude-vterm-max-scrollback 1000)

;; Experimental: inhibit repaint on send (default: nil)
(setq claude-vterm-inhibit-repaint-on-send nil)
```

### Example Configuration

```elisp
(with-eval-after-load 'vterm
  (require 'claude-vterm-helpers)

  ;; Customize settings
  (setq claude-vterm-clear-scrollback-before-paste t)
  (setq claude-vterm-max-scrollback 500)  ; Keep less history

  ;; Setup hooks
  (claude-vterm-setup))
```

## How It Works

### 1. Clear Scrollback Approach

Before sending input, the function runs `clear` in the terminal and clears Emacs' internal scrollback buffer. This removes the long conversation history that would otherwise scroll.

**Pros:**
- Simple and reliable
- No conversation history clutter
- Fast

**Cons:**
- Loses conversation history (can't scroll back)

### 2. Smart Input Sending

Uses `vterm-send-string` to send text character-by-character instead of simulating paste, which can trigger different terminal behavior.

**Pros:**
- More control over how text is sent
- Avoids paste-bracket mode issues

**Cons:**
- Slightly slower for very large pastes

### 3. Scrollback Limiting

Automatically trims the vterm buffer to keep only the most recent N lines of conversation.

**Pros:**
- Maintains some history
- Prevents buffer from growing indefinitely
- Better performance

**Cons:**
- Still has some scrolling (but less)

### 4. Alternate Screen Buffer (Advanced)

Uses ANSI escape sequences to switch to an alternate screen buffer, like vim or less do.

**Pros:**
- Completely isolates input from conversation history
- No scrolling at all

**Cons:**
- More complex
- May interfere with Claude CLI's UI
- Experimental

## Recommended Workflow

For the best experience with long Claude CLI conversations:

1. **Use `C-c C-v` instead of paste + Enter** - This is the main fix
2. **Periodically run `C-c C-l`** - Clear scrollback when it gets too long
3. **Keep conversations in files** - Save important parts of conversations to files instead of relying on terminal scrollback

## Troubleshooting

### Mode doesn't auto-enable

The auto-detection looks for "claude" or "anthropic" in the buffer. If it doesn't detect:

```elisp
;; Manually enable
M-x claude-vterm-mode
```

Or always enable for vterm:

```elisp
(add-hook 'vterm-mode-hook #'claude-vterm-mode)
```

### Still scrolling after paste

Make sure you're using `C-c C-v` instead of regular paste. If that doesn't work:

1. Check the setting: `claude-vterm-clear-scrollback-before-paste` should be `t`
2. Try manually clearing first: `C-c C-l` then paste
3. Reduce scrollback limit: `(setq claude-vterm-max-scrollback 100)`

### Lost conversation history

If you need to keep history:

```elisp
;; Don't auto-clear before paste
(setq claude-vterm-clear-scrollback-before-paste nil)

;; Use larger scrollback
(setq claude-vterm-max-scrollback 5000)
```

Then use `C-u C-c C-v` (prefix arg) to paste without clearing.

## Alternative Solutions

If these helpers don't work for you, consider:

1. **Use Claude CLI in tmux** - tmux has better scrollback management
2. **Use terminal emulator instead of vterm** - Try `ansi-term` or external terminal
3. **Save conversation to file** - Use Claude CLI's save/export features
4. **Use web interface** - claude.ai in browser has better UX for long conversations

## Contributing

Found a better solution? Improvements welcome!

File: `/home/zach/templeDB/integrations/emacs/claude-vterm-helpers.el`

## License

Same license as TempleDB project.
