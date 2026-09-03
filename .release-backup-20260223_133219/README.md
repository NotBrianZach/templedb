# TempleDB Shell Completion

Shell completion scripts for the `templedb` CLI tool.

## Features

- Auto-complete all commands and subcommands
- Dynamic project name completion (queries database)
- Flag and option completion
- Path completion for file operations

## Installation

### Bash

**Option 1: User-level (Recommended)**

```bash
# Copy to bash completion directory
mkdir -p ~/.local/share/bash-completion/completions
cp completions/templedb.bash ~/.local/share/bash-completion/completions/templedb

# Reload bash
source ~/.bashrc
```

**Option 2: Session-level**

```bash
# Add to ~/.bashrc
echo "source ~/templeDB/completions/templedb.bash" >> ~/.bashrc
source ~/.bashrc
```

**Option 3: System-wide (requires root)**

```bash
sudo cp completions/templedb.bash /etc/bash_completion.d/templedb
```

### Zsh

**Option 1: User-level (Recommended)**

```bash
# Create completions directory if needed
mkdir -p ~/.zsh/completions

# Copy completion file
cp completions/_templedb ~/.zsh/completions/

# Add to ~/.zshrc (if not already present)
echo 'fpath=(~/.zsh/completions $fpath)' >> ~/.zshrc
echo 'autoload -Uz compinit && compinit' >> ~/.zshrc

# Reload zsh
source ~/.zshrc
```

**Option 2: Oh-My-Zsh**

```bash
# Copy to Oh-My-Zsh completions
cp completions/_templedb ~/.oh-my-zsh/completions/

# Reload zsh
source ~/.zshrc
```

**Option 3: System-wide (requires root)**

```bash
sudo cp completions/_templedb /usr/share/zsh/site-functions/
```

## Usage Examples

### Basic Commands

```bash
templedb <TAB>
# Shows: help status tui project env vcs search llm backup restore

templedb project <TAB>
# Shows: import list sync

templedb env <TAB>
# Shows: enter list detect new generate
```

### Project Name Completion

```bash
templedb env enter <TAB>
# Shows: templedb woofs_projects system_config ...

templedb vcs log <TAB>
# Shows all project names from database
```

### Flag Completion

```bash
templedb vcs commit -<TAB>
# Shows: -m -p -b -a --message --project --branch --author

templedb search content "pattern" -<TAB>
# Shows: -p -i --project --ignore-case
```

### Path Completion

```bash
templedb project import ~/pro<TAB>
# Completes directory paths

templedb backup ~/backups/<TAB>
# Completes file paths
```

## Supported Completions

### Commands
- `help`, `status`, `tui`
- `project` (import, list, sync)
- `env` (enter, list, detect, new, generate)
- `vcs` (commit, status, log, branch)
- `search` (content, files)
- `llm` (context, export, schema)
- `backup`, `restore`

### Dynamic Completions
- **Project names**: Queries `templedb project list` for current projects
- **Flags**: Context-aware flag suggestions
- **Paths**: Directory and file completion where appropriate

## Troubleshooting

### Bash: Completion not working

```bash
# Check if bash-completion is installed
dpkg -l | grep bash-completion  # Debian/Ubuntu
rpm -q bash-completion          # Fedora/RHEL

# Check if completion is loaded
complete -p templedb

# Reload manually
source ~/.local/share/bash-completion/completions/templedb
```

### Zsh: Completion not working

```bash
# Check fpath
echo $fpath

# Make sure compinit is called
which compinit

# Rebuild completion cache
rm -f ~/.zcompdump
compinit

# Check if completion is loaded
which _templedb
```

### Slow completion

If project name completion is slow:

```bash
# Check database query time
time templedb project list

# If slow, optimize database (see PERFORMANCE.md)
sqlite3 ~/.local/share/templedb/templedb.sqlite "VACUUM; ANALYZE;"
```

## Performance

- Command/subcommand completion: Instant (static lists)
- Project name completion: ~10-50ms (database query)
- Path completion: Depends on filesystem

Project name queries are cached by the shell, so subsequent completions are faster.

## Customization

Both completion scripts can be customized:

### Bash: Edit `templedb.bash`
- Modify command lists at the top
- Add custom completion logic in case statements

### Zsh: Edit `_templedb`
- Modify subcmd arrays in each function
- Add custom argument specifications

## Contributing

To add completion for new commands:

1. Add command to top-level commands list
2. Create handler function/case for subcommands
3. Add flag/argument completions as needed
4. Test with `templedb <new-cmd> <TAB>`

## See Also

- [Bash Completion Documentation](https://github.com/scop/bash-completion)
- [Zsh Completion System](https://zsh.sourceforge.io/Doc/Release/Completion-System.html)
- [TempleDB CLI Documentation](../README.md)
