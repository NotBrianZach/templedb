# TempleDB Terminal UI (TUI)

An interactive, keyboard-driven interface for exploring and managing TempleDB projects.

## Installation

### Option 1: Nix Package (Recommended)

Build and install the TUI as a standalone Nix package with all dependencies bundled:

```bash
# Build the TUI package
nix build .#templedb-tui

# Run directly
./result/bin/templedb-tui

# Or install to your profile
nix profile install .#templedb-tui
templedb-tui

# Or use in nix-shell
nix shell .#templedb-tui
templedb-tui
```

**Advantages:**
- ✅ All dependencies bundled (textual, rich, etc.)
- ✅ Reproducible builds
- ✅ No manual dependency management
- ✅ Works on any system with Nix
- ✅ Integrates with TempleDB's Nix infrastructure

### Option 2: Python + Dependencies

If you don't use Nix, install the `textual` library manually:

```bash
# Using pip
pip install textual rich

# Using Nix shell (temporary)
nix-shell -p python3Packages.textual python3Packages.rich

# Check installation
python3 -c "import textual; print('✓ textual installed')"
```

## Launching the TUI

```bash
templedb tui
```

## Features

### 1. Main Menu

The main menu provides quick access to all major features:

```
┌─────────────────────────────────┐
│          TempleDB               │
│  Database-native project mgmt   │
│                                 │
│  [p] Projects                   │
│  [s] Status                     │
│  [v] VCS (coming soon)          │
│  [x] Secrets (coming soon)      │
│  [?] Help                       │
│  [q] Quit                       │
└─────────────────────────────────┘
```

**Keyboard shortcuts:**
- `p` - Browse projects
- `s` - Show database status
- `v` - Version control (planned)
- `x` - Secrets management (planned)
- `?` - Show help
- `q` - Quit

### 2. Projects Screen

Browse all tracked projects with file counts and statistics.

**Features:**
- List all projects with metadata
- View file counts and lines of code
- Select project to browse files
- Import new projects
- View database status

**Keyboard shortcuts:**
- `↑↓` or `jk` - Navigate list
- `Enter` - Open selected project
- `i` - Import new project
- `s` - Show database status
- `Esc` - Back to main menu
- `q` - Quit

### 3. Files Screen

Browse files within a selected project.

**Features:**
- View all files in project
- See file types, LOC, and sizes
- Incremental search across files
- Select file to view details

**Keyboard shortcuts:**
- `↑↓` or `jk` - Navigate file list
- `/` - Focus search box
- `Enter` - View file details
- `Esc` - Back to projects
- `q` - Quit

**Search:**
- Type to filter files instantly
- Fuzzy matching on file paths
- Results update in real-time

### 4. File Info Screen

View detailed information about a specific file.

**Information displayed:**
- File path and type
- Lines of code
- File size
- Content hash
- Creation/modification timestamps

**Keyboard shortcuts:**
- `Esc` - Back to file list
- `q` - Quit

### 5. Status Screen

View database statistics and health information.

**Information displayed:**
- Database location and size
- Project count
- File count
- Commit count
- Total lines of code

**Keyboard shortcuts:**
- `Esc` - Back
- `q` - Quit

### 6. Import Project Screen

Interactive dialog for importing new projects.

**Features:**
- Enter project path
- Optionally specify custom slug
- Auto-detection from directory
- Real-time import status

**Keyboard shortcuts:**
- `Tab` - Move between fields
- `Enter` - Submit
- `Esc` - Cancel

## Navigation Patterns

### Global Shortcuts

Available everywhere in the TUI:

| Key | Action |
|-----|--------|
| `q` | Quit application |
| `Esc` | Go back / Close current screen |
| `?` | Show help |
| `Ctrl+C` | Force quit |

### List Navigation

In any list view (projects, files):

| Key | Action |
|-----|--------|
| `↑`/`k` | Move up |
| `↓`/`j` | Move down |
| `PageUp` | Jump up |
| `PageDown` | Jump down |
| `Home` | Go to first item |
| `End` | Go to last item |
| `Enter` | Select item |

### Search

In screens with search:

| Key | Action |
|-----|--------|
| `/` | Focus search input |
| `Esc` | Clear search / unfocus |
| Type | Filter results in real-time |

## Use Cases

### 1. Exploring Projects

```
1. Launch TUI: templedb tui
2. Press 'p' for Projects
3. Navigate with ↑↓ keys
4. Press Enter to browse files
5. Press '/' to search files
6. Press Enter to view file details
```

### 2. Checking Database Status

```
1. Launch TUI: templedb tui
2. Press 's' for Status
3. View statistics
4. Press Esc to return
```

### 3. Importing New Project

```
1. Launch TUI: templedb tui
2. Press 'p' for Projects
3. Press 'i' to import
4. Enter project path
5. Optionally enter slug
6. Click Import button or Tab+Enter
```

### 4. Quick File Search

```
1. Navigate to Files screen
2. Press '/' to search
3. Type search term
4. Results filter instantly
5. Navigate filtered results
6. Press 'v' to view content or Enter for details
```

### 5. Viewing File Content

```
1. Navigate to Files screen
2. Select a file
3. Press 'v' to view content
4. Scroll through the file
5. Press Esc to return
```

### 6. Browsing VCS History

```
1. From Projects screen, select project
2. Press 'v' for VCS menu
3. Press 'c' for commits
4. Navigate commit history
5. Press Enter for details
6. Press 'b' to see branches
```

### 7. Managing Secrets

```
1. From main menu, press 'x'
2. View all secrets by project
3. Select a secret
4. Press 'e' to edit in $EDITOR
5. Or press Enter to view keys
6. Values hidden for security
```

## Available Screens

### 7. VCS Screen

View and manage version control for projects.

**Features:**
- Browse commits with full history
- View branches and their stats
- Per-project or global VCS view
- See commit details

**Keyboard shortcuts:**
- `c` - View commits
- `b` - View branches
- `l` - View log
- `Enter` - View details
- `Esc` - Back
- `q` - Quit

**From Projects:**
- Press `v` on a project to see its VCS info

### 8. Secrets Screen

Manage encrypted secrets across all projects.

**Features:**
- List all secrets by project and profile
- View secret keys (values hidden)
- Edit secrets in $EDITOR
- Create new secrets
- See creation/update timestamps

**Keyboard shortcuts:**
- `e` - Edit selected secret
- `n` - Create new secret
- `Enter` - View secret details
- `Esc` - Back
- `q` - Quit

**Secret Details View:**
- Shows all secret keys without values (for security)
- Edit with `e` to launch $EDITOR
- Values only accessible through CLI export

### 9. File Content Viewer

View file contents directly in the TUI.

**Features:**
- Display text file contents
- Syntax-aware (via file types)
- Scroll through files
- First 500 lines shown (prevents freezing on large files)

**Access:**
- From Files screen, press `v` to view content
- Or press `Enter` for info, then `v` for content

**Keyboard shortcuts:**
- `Esc` - Back to file list
- `q` - Quit
- Arrow keys - Scroll

## Planned Features

The following features are planned for future releases:

### Enhanced VCS Features
- Create new branches in-TUI
- Switch between branches
- View file changes per commit
- Commit creation interface
- Merge conflict resolution

### Enhanced Secrets Features
- Initialize new secrets without CLI
- Copy secret values to clipboard
- Secret rotation tracking
- Audit log viewer

### Search Screen
- Global content search across all projects
- Advanced regex support
- Search history
- Save search queries

### Settings Screen
- Configure TUI preferences
- Set default editor
- Customize key bindings
- Theme selection
- Performance tuning

### Advanced File Operations
- Side-by-side diff viewer
- Blame view (who changed what)
- File history timeline
- Compare versions graphically

## Keyboard-Driven Philosophy

The TUI is designed to be fully keyboard-driven, inspired by tools like:

- **Vim** - Modal editing, hjkl navigation
- **Spacemacs** - Space-based command discovery
- **Lazygit** - Intuitive git TUI
- **Atuin** - Smart incremental search

**Design principles:**
1. **Discoverable** - All features accessible from main menu
2. **Fast** - Keyboard shortcuts for common actions
3. **Consistent** - Same patterns across screens
4. **Helpful** - Footer shows available shortcuts
5. **Responsive** - Real-time search and updates

## Troubleshooting

### "textual not installed"

```bash
pip install textual
# Or
nix-shell -p python3Packages.textual
```

### TUI won't start

```bash
# Check Python version (3.9+ required)
python3 --version

# Check textual is accessible
python3 -c "import textual"

# Try running directly
python3 src/tui.py
```

### Display issues

- Ensure terminal supports colors
- Try resizing terminal window
- Check TERM environment variable:
  ```bash
  echo $TERM  # Should be xterm-256color or similar
  ```

### Navigation doesn't work

- Some terminals don't support all key codes
- Try alternative keys (arrows vs hjkl)
- Check terminal keybindings aren't conflicting

## Performance

The TUI is optimized for large databases:

- **Pagination** - Lists limited to 500 items
- **Incremental search** - Queries run on keystroke
- **Lazy loading** - Data loaded on-demand
- **Efficient queries** - Uses indexed columns

For very large projects:
- Use search (`/`) to filter before browsing
- Use CLI for bulk operations
- Consider project-specific views

## Integration with CLI

The TUI complements the CLI:

| Task | TUI | CLI |
|------|-----|-----|
| **Explore projects** | ✓ Ideal | Use `list` |
| **Browse files** | ✓ Ideal | Use `search` |
| **View file content** | ✓ Ideal | Use `cat` or editor |
| **View status** | ✓ Quick | Use `status` |
| **Import projects** | ✓ Interactive | Use `import` |
| **VCS history** | ✓ Ideal | Use `vcs log` |
| **Manage secrets** | ✓ Browse, ✓ Edit | Use `secret` commands |
| **Batch operations** | ✗ Use CLI | ✓ Ideal |
| **Scripting** | ✗ Use CLI | ✓ Ideal |
| **Checkout/commit** | ✗ Use CLI | ✓ Ideal |
| **Complex queries** | ✗ Use SQL | ✓ Direct sqlite3 |

**General rule:** Use TUI for exploration and discovery, CLI for automation and scripting.

## Customization

The TUI appearance can be customized through CSS-like styling in the code.

**Current theme:** Dark mode with accent colors

To modify colors, edit `src/tui.py`:
```python
class TempleDBTUI(App):
    CSS = """
    # Modify colors here
    """
```

## Contributing

Want to add features to the TUI?

1. TUI code: `src/tui.py`
2. Uses Textual framework: https://textual.textualize.io/
3. Follow existing screen patterns
4. Test with `python3 src/tui.py`
5. Submit PR

**Implemented screens (9 total):**
- ✅ Main Menu
- ✅ Projects Browser
- ✅ Files Browser
- ✅ File Info
- ✅ File Content Viewer
- ✅ Status Screen
- ✅ Import Dialog
- ✅ VCS Menu (Commits, Branches)
- ✅ Secrets Manager

**Priority features for contribution:**
- Diff viewer (compare file versions side-by-side)
- Syntax highlighting in content viewer
- Branch creation/switching in VCS
- Commit creation interface
- Settings screen
- Search history
- Keyboard shortcut customization

## See Also

- **[GETTING_STARTED.md](GETTING_STARTED.md)** - Installation guide
- **[QUICKSTART.md](QUICKSTART.md)** - CLI workflows
- **[README.md](README.md)** - Project overview
- **Textual docs** - https://textual.textualize.io/
