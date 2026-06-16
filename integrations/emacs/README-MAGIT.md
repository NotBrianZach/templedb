# TempleDB Magit Integration

Magit-like interface for TempleDB version control in Emacs.

## Installation

### Manual Installation

```elisp
;; Add to your init.el or .emacs
(add-to-list 'load-path "/path/to/templedb/integrations/emacs")
(require 'templedb-magit)

;; Optional: Set custom executable path
(setq templedb-magit-executable "/usr/local/bin/templedb")

;; Optional: Keybindings
(global-set-key (kbd "C-c t s") 'templedb-magit-status)
(global-set-key (kbd "C-c t e") 'templedb-magit-file-edit)
```

### With use-package

```elisp
(use-package templedb-magit
  :load-path "/path/to/templedb/integrations/emacs"
  :bind (("C-c t s" . templedb-magit-status)
         ("C-c t e" . templedb-magit-file-edit))
  :custom
  (templedb-magit-executable "templedb")
  (templedb-magit-auto-refresh t))
```

## Commands

### Status Buffer

#### `M-x templedb-magit-status`

Open TempleDB status buffer for current project (auto-detected from working directory).

#### `M-x templedb-magit-status-project`

Open TempleDB status buffer for a specific project (with completion).

**Example:**
```
M-x templedb-magit-status-project RET woofs_projects RET
```

### File Operations

#### `M-x templedb-magit-file-edit`

Edit a file from a TempleDB project. Prompts for project and file path with completion.

**Example:**
```
M-x templedb-magit-file-edit RET myproject RET src/main.py RET
```

## Status Buffer Keybindings

When in a TempleDB status buffer:

| Key | Command | Description |
|-----|---------|-------------|
| `RET` | `templedb-magit-edit-file` | Edit file at point |
| `e` | `templedb-magit-edit-file` | Edit file at point (alias) |
| `v` | `templedb-magit-show-file` | Show file in read-only buffer |
| `s` | `templedb-magit-stage-file` | Stage file at point |
| `u` | `templedb-magit-unstage-file` | Unstage file at point |
| `c` | `templedb-magit-commit` | Commit staged changes |
| `g` | `templedb-magit-refresh` | Refresh status buffer |
| `q` | `quit-window` | Close status buffer |

## Status Buffer Layout

```
TempleDB Status: myproject

Staged changes (2)
  src/main.py
  src/config.py

Modified (1)
  README.md

Untracked (3)
  temp.txt
  notes.org
  .DS_Store
```

## Workflow Examples

### Basic Commit Workflow

1. Open status buffer: `M-x templedb-magit-status`
2. Navigate to modified file
3. Stage file: `s`
4. Commit: `c`, enter message
5. Refresh: `g`

### Quick File Edit

From any buffer:
1. `M-x templedb-magit-status`
2. Navigate to file
3. Press `RET` to edit
4. Make changes, save
5. Press `g` to refresh status
6. Stage with `s`, commit with `c`

### Review Changes

1. Open status: `M-x templedb-magit-status`
2. Navigate to modified file
3. Press `v` to view in read-only buffer
4. Review changes
5. Press `q` to close viewer
6. Stage with `s` if changes look good

## Integration with Emacs Features

### With Projectile

```elisp
(defun my-templedb-magit-status-projectile ()
  "Open TempleDB status for current Projectile project."
  (interactive)
  (if-let ((project (projectile-project-name)))
      (templedb-magit-status-project project)
    (message "Not in a Projectile project")))

(define-key projectile-command-map (kbd "t") #'my-templedb-magit-status-projectile)
```

### With dired

```elisp
(defun my-templedb-edit-file-at-point ()
  "Edit file at point in dired using TempleDB."
  (interactive)
  (when-let ((file (dired-get-filename))
             (project (templedb-magit--detect-project)))
    (let ((relative-path (file-relative-name file (templedb-magit--get-project-path project))))
      (templedb-magit-file-edit project relative-path))))

;; Bind in dired-mode-map
(define-key dired-mode-map (kbd "C-c t e") #'my-templedb-edit-file-at-point)
```

### With Embark

```elisp
(defun embark-templedb-edit-file (file)
  "Edit FILE with TempleDB."
  (when-let ((project (templedb-magit--detect-project)))
    (let ((relative-path (file-relative-name file (templedb-magit--get-project-path project))))
      (templedb-magit-file-edit project relative-path))))

(define-key embark-file-map (kbd "t") #'embark-templedb-edit-file)
```

## Advanced Configuration

### Custom Status Buffer Display

```elisp
(add-to-list 'display-buffer-alist
             '("\\*templedb-magit:.*\\*"
               (display-buffer-in-side-window)
               (side . right)
               (window-width . 0.4)))
```

### Auto-stage on Save

```elisp
(defun my-templedb-auto-stage ()
  "Auto-stage current file on save if in TempleDB project."
  (when-let* ((project (templedb-magit--detect-project))
              (project-path (templedb-magit--get-project-path project))
              (file-path (buffer-file-name))
              (relative-path (file-relative-name file-path project-path)))
    (condition-case err
        (templedb-magit--stage-file project relative-path)
      (error (message "Failed to auto-stage: %s" err)))))

(add-hook 'after-save-hook #'my-templedb-auto-stage)
```

### Integration with evil-mode

```elisp
(with-eval-after-load 'templedb-magit
  (evil-set-initial-state 'templedb-magit-status-mode 'normal)

  (evil-define-key 'normal templedb-magit-status-mode-map
    (kbd "RET") 'templedb-magit-edit-file
    "e" 'templedb-magit-edit-file
    "v" 'templedb-magit-show-file
    "s" 'templedb-magit-stage-file
    "u" 'templedb-magit-unstage-file
    "c" 'templedb-magit-commit
    "g" 'templedb-magit-refresh
    "q" 'quit-window))
```

## Customization

### Available Options

```elisp
;; Path to templedb executable
(setq templedb-magit-executable "templedb")

;; Auto-refresh after operations
(setq templedb-magit-auto-refresh t)
```

### Custom Faces

```elisp
(set-face-attribute 'templedb-magit-section-heading nil
                    :foreground "cyan"
                    :weight 'bold)

(set-face-attribute 'templedb-magit-filename nil
                    :foreground "white")
```

## Troubleshooting

### "Project not found"

Make sure the project is imported into TempleDB:
```bash
templedb project list
# If not listed:
templedb project import /path/to/project
```

### "File does not exist"

The file might not be synced yet:
```bash
templedb project sync myproject
```

Then refresh the status buffer: `g`

### "Command not found"

Check the executable path:
```elisp
(setq templedb-magit-executable "/full/path/to/templedb")
```

Or ensure templedb is in your PATH:
```bash
which templedb
```

## Comparison with Magit

| Feature | Magit | TempleDB Magit |
|---------|-------|----------------|
| Status buffer | ✓ | ✓ |
| Stage/unstage | ✓ | ✓ |
| Commit | ✓ | ✓ |
| Diff viewing | ✓ | Planned |
| Branch management | ✓ | Planned |
| History/log | ✓ | Planned |
| Rebase | ✓ | N/A (TempleDB model) |
| Cherry-pick | ✓ | N/A (TempleDB model) |
| File editing | - | ✓ (unique) |
| Database queries | - | ✓ (planned) |

## Future Features

- [ ] Inline diff display in status buffer
- [ ] Section folding (TAB to toggle)
- [ ] Branch switcher with completion
- [ ] Commit history browser
- [ ] File blame view
- [ ] Integration with TempleDB code intelligence
- [ ] Visual merge conflict resolver
- [ ] Transient menus (like Magit)
- [ ] Repository statistics dashboard

## See Also

- [FILE_COMMANDS.md](../../docs/FILE_COMMANDS.md) - CLI file commands
- [TempleDB VCS](../../docs/VCS.md) - Version control system docs
- [Magit](https://magit.vc/) - Original inspiration
