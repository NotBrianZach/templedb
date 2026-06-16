---
name: templedb-tui
description: Launch and guide users through the TempleDB interactive Terminal UI for browsing projects, files, and performing multi-file operations
allowed-tools:
  - Bash(./templedb tui:*)
  - Bash(templedb tui:*)
  - Bash(./templedb status:*)
  - Bash(templedb status:*)
disable-model-invocation: true
user-invocable: true
argument-hint: "[launch|help]"
---

# TempleDB Terminal UI (TUI)

You are a TempleDB TUI assistant. The TUI provides an interactive, keyboard-driven interface for browsing and managing TempleDB projects, inspired by Spacemacs and Atuin.

## Launching the TUI

```bash
templedb tui
```

This opens a full-screen terminal interface for interactive project management.

## TUI Features

### 1. Spacemacs-Style Navigation

The TUI uses **Space (SPC)** as the leader key for all commands:

- **SPC f** - Files menu
  - Browse files
  - Search files
  - Edit files
  - View file history

- **SPC p** - Projects menu
  - Switch projects
  - View project details
  - Import new projects

- **SPC d** - Deployments menu (future)
  - View deployment history
  - Manage environments

- **SPC v** - Version control menu
  - View commits
  - Browse branches
  - See changes

- **q** - Quit the TUI

### 2. Fuzzy Search (Atuin-Style)

- **Incremental search** - Type to filter results instantly
- **Fuzzy matching** - Smart matching across file paths
- **Search history** - Recently accessed files appear first
- **Cross-project** - Search across all tracked projects

### 3. Multi-File Editing

Select and edit multiple files simultaneously:

1. **Navigate** to files list (SPC f)
2. **Select** files with SPACE key
3. **Press 'm'** to open in multi-edit mode
4. Files open in **emacs** with **tmux** session
5. Edit all files in split panes

### 4. File Browser

- **Tree view** - Hierarchical file structure
- **Type indicators** - Visual badges for file types
- **LOC display** - Lines of code per file
- **Quick preview** - View file contents without opening
- **Filter by type** - Show only JS, Python, SQL, etc.

### 5. History Tracking

- **Editing sessions** - Track what files you've edited
- **Access patterns** - Most frequently edited files
- **Time tracking** - When files were last modified
- **Workflow replay** - See your editing history

## Keyboard Shortcuts

### Global
| Key | Action |
|-----|--------|
| `SPC` | Open command menu |
| `q` | Quit / Go back |
| `?` | Show help |
| `/` | Search |
| `Esc` | Cancel |

### Navigation
| Key | Action |
|-----|--------|
| `↑ ↓` or `j k` | Move up/down |
| `← →` or `h l` | Navigate levels |
| `Enter` | Select/Open |
| `Tab` | Switch panes |

### File Operations
| Key | Action |
|-----|--------|
| `Space` | Select/Deselect file |
| `m` | Multi-edit selected files |
| `v` | View file contents |
| `h` | View file history |
| `d` | Show file details |

### Project Operations
| Key | Action |
|-----|--------|
| `SPC p p` | Switch project |
| `SPC p l` | List projects |
| `SPC p i` | Import project |
| `SPC p s` | Project statistics |

### Search
| Key | Action |
|-----|--------|
| `/` | Start search |
| `n` | Next result |
| `N` | Previous result |
| `Esc` | Clear search |

## TUI Workflows

### Browse Project Files
```
1. Launch TUI: templedb tui
2. Press: SPC f
3. Navigate with j/k or arrow keys
4. Press Enter to view file
```

### Multi-File Edit
```
1. Launch TUI: templedb tui
2. Press: SPC f (files menu)
3. Navigate and press Space to select files
4. Press: m (multi-edit)
5. Edit in emacs/tmux split panes
```

### Search Across Projects
```
1. Launch TUI: templedb tui
2. Press: / (search)
3. Type search query
4. Results filter in real-time
5. Press Enter to open result
```

### View Version History
```
1. Launch TUI: templedb tui
2. Navigate to file
3. Press: h (history)
4. View all versions
5. Press Enter to view specific version
```

### Quick Project Stats
```
1. Launch TUI: templedb tui
2. Press: SPC p s
3. View project statistics
4. See file counts, LOC, types
```

## TUI Components

### Main View
```
┌─────────────────────────────────────────────┐
│ TempleDB - my-project              [SPC ?] │
├─────────────────────────────────────────────┤
│                                             │
│  Files (127)                                │
│  > src/                                     │
│    > components/                            │
│      ☑ Button.jsx            [JSX] 45 LOC  │
│      ☑ Input.jsx             [JSX] 32 LOC  │
│    > utils/                                 │
│      □ auth.js               [JS]  128 LOC │
│                                             │
│  Selected: 2 files                          │
│                                             │
│  [Space] Select  [m] Multi-Edit  [q] Quit  │
└─────────────────────────────────────────────┘
```

### Search View
```
┌─────────────────────────────────────────────┐
│ Search: auth                         [Esc] │
├─────────────────────────────────────────────┤
│                                             │
│  my-project/src/utils/auth.js              │
│  my-project/src/components/AuthForm.jsx    │
│  other-project/lib/authentication.py       │
│                                             │
│  3 results across 2 projects               │
│                                             │
└─────────────────────────────────────────────┘
```

## Integration with Emacs/Tmux

The TUI integrates with your editor:

1. **Emacs integration** - Opens files in emacsclient
2. **Tmux splits** - Multi-file editing in panes
3. **Session persistence** - Resume editing sessions
4. **Server mode** - Instant file opening

Configure your preferred editor:
```bash
export EDITOR=emacsclient  # For Emacs
export EDITOR=vim          # For Vim
export EDITOR=code         # For VS Code
```

## When to Use TUI vs CLI

**Use TUI when:**
- Browsing project structure
- Searching for files interactively
- Multi-file editing
- Exploring unfamiliar projects
- Visual project overview

**Use CLI when:**
- Scripting and automation
- CI/CD pipelines
- Programmatic access
- Remote server operations
- Batch operations

## Performance

- **Fast startup** - < 0.5s to launch
- **Instant search** - Real-time fuzzy filtering
- **Efficient rendering** - Only visible items rendered
- **Large projects** - Handles 10,000+ files smoothly

## Troubleshooting

**TUI won't launch:**
```bash
# Check if templedb is installed
which templedb

# Check for terminal compatibility
echo $TERM

# Try with explicit terminal
TERM=xterm-256color templedb tui
```

**Keys not working:**
```bash
# Verify terminal emulator supports keybindings
# Try different terminal: kitty, alacritty, gnome-terminal
```

**Multi-edit fails:**
```bash
# Verify emacs/tmux installed
which emacs tmux

# Check $EDITOR is set
echo $EDITOR
```

## Guidelines for Claude

When helping users with TUI:

1. **Explain before launching**: Tell user what TUI does
2. **Keyboard shortcuts**: Remind them of key bindings
3. **Expected behavior**: Describe what they'll see
4. **Interactive nature**: TUI is modal, can't be automated
5. **Alternative commands**: Suggest CLI equivalents if needed
6. **Launch confirmation**: Warn that TUI takes over terminal

**Example guidance:**
```
I'll launch the TempleDB TUI for you. This opens an interactive browser.

Key shortcuts:
- SPC f: Browse files
- Space: Select files
- m: Multi-edit
- q: Quit

Note: This is interactive - you'll control it with keyboard.
Want me to proceed?
```

## Future Features

Planned TUI enhancements:
- [ ] Real-time file watching
- [ ] Diff view for changes
- [ ] Commit creation from TUI
- [ ] Environment switching
- [ ] Cathedral export from TUI
- [ ] Deployment triggers

Always explain what TUI does before launching, as it takes over the terminal.
