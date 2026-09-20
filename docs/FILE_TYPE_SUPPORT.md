# TempleDB File Type Support

Complete reference for all file types tracked by TempleDB.

---

## Overview

TempleDB automatically detects and tracks **100+ file types** including:
- Source code files (20+ languages)
- Configuration files and dotfiles
- Build tools and package managers
- CI/CD configurations
- Infrastructure as Code
- Documentation

Files are detected by pattern matching and stored with metadata (type, component name, line count).

---

## Supported File Types

### Programming Languages (20 languages)

| Language | Extensions | Component Extraction |
|----------|-----------|---------------------|
| Python | `.py` | Yes (class/function) |
| JavaScript | `.js`, `.mjs`, `.cjs` | Yes (function/const) |
| TypeScript | `.ts` | Yes (function/const) |
| React | `.jsx`, `.tsx` | Yes (component) |
| Rust | `.rs` | Yes (fn/struct) |
| Go | `.go` | Yes (func/type) |
| Ruby | `.rb` | Yes (class/module) |
| Java | `.java` | No |
| Kotlin | `.kt` | No |
| Swift | `.swift` | No |
| C | `.c` | No |
| C++ | `.cpp` | No |
| C# | `.cs` | No |
| PHP | `.php` | No |
| Scala | `.scala` | No |
| Clojure | `.clj` | No |
| Elixir | `.ex` | No |
| Erlang | `.erl` | No |
| Haskell | `.hs` | No |
| Lua | `.lua` | No |
| Perl | `.pl` | No |
| R | `.r` | No |
| Emacs Lisp | `.el` | No |

### Shell Configurations

| File | Type | Description |
|------|------|-------------|
| `.bashrc` | bash_config | Bash shell configuration |
| `.bash_profile` | bash_profile | Bash profile |
| `.zshrc` | zsh_config | Zsh configuration |
| `.profile` | shell_profile | Generic shell profile |
| `.fish` | fish_config | Fish shell configuration |
| `.aliases` | shell_aliases | Shell aliases |

### Git Configurations

| File | Type | Description |
|------|------|-------------|
| `.gitignore` | git_ignore | Git ignore patterns |
| `.gitattributes` | git_attributes | Git attributes |
| `.gitmodules` | git_modules | Git submodules |
| `.gitconfig` | git_config | Git configuration |

### Editor Configurations

| File | Type | Description |
|------|------|-------------|
| `.editorconfig` | editor_config | EditorConfig |
| `.prettierrc` | prettier_config | Prettier formatter |
| `.eslintrc*` | eslint_config | ESLint linter |
| `.vimrc` | vim_config | Vim configuration |
| `init.vim` | nvim_config | Neovim configuration |
| `.spacemacs` | emacs_config | Spacemacs configuration |
| `.rubocop.yml` | rubocop | RuboCop linter |
| `.stylelintrc` | stylelint | Stylelint |
| `.flake8` | flake8_config | Flake8 linter |
| `.babelrc` | babel_config | Babel transpiler |
| `.browserslistrc` | browserslist | Browserslist |
| `settings.json` | vscode_settings | VS Code settings (in .vscode/) |

### Version Managers

| File | Type | Description |
|------|------|-------------|
| `.nvmrc` | nvm_rc | Node version |
| `.ruby-version` | ruby_version | Ruby version |
| `.python-version` | python_version | Python version |
| `.node-version` | node_version | Node version |

### CI/CD Configurations

| File | Type | Description |
|------|------|-------------|
| `.travis.yml` | travis_ci | Travis CI |
| `.gitlab-ci.yml` | gitlab_ci | GitLab CI |
| `.github/workflows/*.yml` | github_workflow | GitHub Actions |
| `.circleci/config.yml` | circleci_config | CircleCI |
| `Jenkinsfile` | jenkins_file | Jenkins pipeline |
| `dependabot.yml` | dependabot | Dependabot |

### Package Managers

| File | Type | Description |
|------|------|-------------|
| `package.json` | package_json | NPM dependencies |
| `.npmrc` | npm_rc | NPM configuration |
| `.yarnrc` | yarn_rc | Yarn configuration |
| `requirements.txt` | pip_requirements | Python pip |
| `Pipfile` | pipfile | Pipenv |
| `pyproject.toml` | poetry_config | Python Poetry |
| `setup.py` | setup_py | Python setup script |
| `Cargo.toml` | cargo_toml | Rust Cargo config |
| `Cargo.lock` | cargo_lock | Rust lock file |
| `Gemfile` | gemfile | Ruby Bundler |
| `Gemfile.lock` | gemfile_lock | Ruby lock file |
| `go.mod` | go_mod | Go modules |
| `go.sum` | go_sum | Go checksums |
| `composer.json` | composer_json | PHP Composer |

### Build Tools

| File | Type | Description |
|------|------|-------------|
| `Makefile` | makefile | Make build tool |
| `Rakefile` | rakefile | Ruby Rake |
| `build.gradle` | gradle_build | Gradle (Java) |
| `pom.xml` | maven_pom | Maven (Java) |
| `CMakeLists.txt` | cmake | CMake (C/C++) |
| `tsconfig.json` | tsconfig | TypeScript config |
| `jest.config.js` | jest_config | Jest testing |
| `webpack.config.js` | webpack_config | Webpack bundler |
| `vite.config.js` | vite_config | Vite bundler |
| `rollup.config.js` | rollup_config | Rollup bundler |

### Infrastructure as Code

| File | Type | Description |
|------|------|-------------|
| `*.tf` | terraform | Terraform config |
| `*.tfvars` | terraform_vars | Terraform variables |
| `playbook.yml` | ansible_playbook | Ansible playbook |
| `inventory.yml` | ansible_inventory | Ansible inventory |
| `k8s.yml` | kubernetes | Kubernetes manifest |
| `Chart.yaml` | helm_chart | Helm chart |

### Database

| File | Type | Description |
|------|------|-------------|
| `schema.sql` | sql_schema | Database schema |
| `*.sql` (in migrations/) | sql_migration | SQL migration |
| `*.sql` | sql_file | Generic SQL |
| `schema.prisma` | prisma_schema | Prisma ORM |

### Docker

| File | Type | Description |
|------|------|-------------|
| `Dockerfile` | docker_file | Docker image |
| `docker-compose.yml` | docker_compose | Docker Compose |

### Nix

| File | Type | Description |
|------|------|-------------|
| `flake.nix` | nix_flake | Nix flake |
| `shell.nix` | nix_shell | Nix shell env |
| `default.nix` | nix_default | Nix default |
| `*.nix` | nix_file | Generic Nix |

### Testing

| File | Type | Description |
|------|------|-------------|
| `*.test.js` | test_file | Test file |
| `*.spec.js` | spec_file | Spec file |
| `pytest.ini` | pytest_config | Pytest config |

### Platform-Specific

| File | Type | Description |
|------|------|-------------|
| `Procfile` | procfile | Heroku |
| `vercel.json` | vercel_config | Vercel |
| `netlify.toml` | netlify_config | Netlify |
| `railway.json` | railway_config | Railway |
| `*.service` | systemd_service | Systemd service |
| `ecosystem.config.js` | pm2_config | PM2 process manager |

### Documentation

| File | Type | Description |
|------|------|-------------|
| `README` | readme | Plain README |
| `README.md` | markdown | Markdown README |
| `*.md` | markdown | Markdown file |
| `CHANGELOG.md` | changelog | Changelog |
| `LICENSE` | license | License file |
| `CONTRIBUTING.md` | contributing | Contributing guide |
| `SECURITY.md` | security_policy | Security policy |

### Web Assets

| File | Type | Description |
|------|------|-------------|
| `*.css` | css | Stylesheets |
| `*.scss` | scss | Sass stylesheets |
| `*.html` | html | HTML files |
| `robots.txt` | robots_txt | Robots.txt |
| `.htaccess` | htaccess | Apache config |

### Configuration Files

| File | Type | Description |
|------|------|-------------|
| `*.yml`, `*.yaml` | config_yaml | YAML config |
| `*.json` | config_json | JSON config |
| `.env*` | env_file | Environment vars |

---

## Pattern Matching Rules

File detection follows these rules (in order):

1. **Most specific patterns first** - e.g., `schema.sql` before `*.sql`
2. **Exact filename matches** - e.g., `Makefile`, `Dockerfile`
3. **Directory-specific patterns** - e.g., `.github/workflows/*.yml`
4. **Extension patterns** - e.g., `*.py`, `*.rs`
5. **Generic catch-alls last** - e.g., `*.yml`, `*.json`

### Examples

```python
# Specific match
schema.sql → sql_schema

# Migration in path
migrations/001_init.sql → sql_migration

# Generic SQL
queries/users.sql → sql_file

# GitHub Actions
.github/workflows/test.yml → github_workflow

# Generic YAML
config.yml → config_yaml
```

---

## Component Name Extraction

For certain file types, TempleDB extracts the primary component/function name:

### JavaScript/TypeScript
```javascript
// Extracts: MyComponent
export function MyComponent() { }
export const MyComponent = () => { }
export default MyComponent;
```

### Python
```python
# Extracts: MyClass
class MyClass:
    pass

# Or: my_function
def my_function():
    pass
```

### Rust
```rust
// Extracts: my_function
pub fn my_function() { }

// Or: MyStruct
pub struct MyStruct { }
```

### Go
```go
// Extracts: MyFunction
func MyFunction() { }

// Or: MyType
type MyType struct { }
```

### Ruby
```ruby
# Extracts: MyClass
class MyClass
end

# Or: MyModule
module MyModule
end
```

---

## Adding Custom File Types

### Via Database

Add new types to the `file_types` table:

```sql
INSERT INTO file_types (name, extension, description)
VALUES ('my_custom_type', '.custom', 'Custom file type');
```

### Via Scanner Pattern

Edit `src/importer/scanner.py`:

```python
FILE_TYPE_PATTERNS = [
    # Add your pattern (order matters!)
    (r'\.custom$', 'my_custom_type', None),
    # ... existing patterns
]
```

### With Conditional Logic

Use a test function for complex rules:

```python
FILE_TYPE_PATTERNS = [
    (r'\.yml$', 'ansible_playbook',
     lambda p: 'playbook' in p.lower()),
    # ... rest of patterns
]
```

---

## Excluded Directories

These directories are skipped during scanning:

- `node_modules`
- `.git`
- `venv`, `.venv`, `env`
- `__pycache__`
- `dist`, `build`
- `.direnv`
- `.next`
- `target` (Rust)
- `.pytest_cache`
- `coverage`

---

## Testing File Detection

Use the test script:

```bash
python3 scripts/test_file_detection.py
```

This creates 67 test files and verifies 100% detection rate.

---

## Querying File Types

### All Tracked Types

```sql
SELECT name, extension, description
FROM file_types
ORDER BY name;
```

### Files by Type

```sql
SELECT pf.file_path, pf.component_name, pf.lines_of_code
FROM project_files pf
JOIN file_types ft ON pf.file_type_id = ft.id
WHERE ft.name = 'rust'
ORDER BY pf.lines_of_code DESC;
```

### Type Distribution

```sql
SELECT
    ft.name,
    COUNT(*) as file_count,
    SUM(pf.lines_of_code) as total_lines
FROM project_files pf
JOIN file_types ft ON pf.file_type_id = ft.id
WHERE pf.project_id = (SELECT id FROM projects WHERE slug = 'myproject')
GROUP BY ft.name
ORDER BY file_count DESC;
```

---

## Performance

- **Detection speed**: ~3ms per file
- **Pattern matching**: O(n) where n = number of patterns
- **Memory**: Minimal (streaming file scan)

---

## Summary

TempleDB tracks **100+ file types** automatically:
- ✅ **20+ programming languages**
- ✅ **Shell, Git, editor dotfiles**
- ✅ **Package managers and build tools**
- ✅ **CI/CD configurations**
- ✅ **Infrastructure as Code**
- ✅ **Documentation and configs**

All with **zero configuration** required - just import your project!

---

*"God's temple is everything."* - Terry A. Davis

**TempleDB - Where your code finds sanctuary**
