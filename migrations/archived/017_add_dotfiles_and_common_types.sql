-- Migration 017: Add dotfiles and common file types
-- Date: 2026-02-24
-- Description: Adds support for tracking dotfiles, shell configs,
--              editor configs, and common development file types

-- Add new file types for dotfiles and configurations
INSERT OR IGNORE INTO file_types (name, extension, description) VALUES
-- Shell configurations
('bash_config', '.bashrc', 'Bash shell configuration'),
('zsh_config', '.zshrc', 'Zsh shell configuration'),
('shell_profile', '.profile', 'Shell profile configuration'),
('bash_profile', '.bash_profile', 'Bash profile configuration'),
('fish_config', '.fish', 'Fish shell configuration'),
('shell_aliases', '.aliases', 'Shell aliases file'),

-- Git configurations
('git_ignore', '.gitignore', 'Git ignore patterns'),
('git_attributes', '.gitattributes', 'Git attributes file'),
('git_modules', '.gitmodules', 'Git submodules configuration'),
('git_config', '.gitconfig', 'Git global configuration'),

-- Editor configurations
('editor_config', '.editorconfig', 'EditorConfig file'),
('prettier_config', '.prettierrc', 'Prettier configuration'),
('eslint_config', '.eslintrc', 'ESLint configuration'),
('vim_config', '.vimrc', 'Vim configuration'),
('nvim_config', 'init.vim', 'Neovim configuration'),
('vscode_settings', 'settings.json', 'VS Code settings'),

-- Version managers
('nvm_rc', '.nvmrc', 'Node version manager'),
('ruby_version', '.ruby-version', 'Ruby version specification'),
('python_version', '.python-version', 'Python version specification'),
('node_version', '.node-version', 'Node version specification'),

-- CI/CD configurations
('travis_ci', '.travis.yml', 'Travis CI configuration'),
('gitlab_ci', '.gitlab-ci.yml', 'GitLab CI configuration'),
('github_workflow', 'workflow.yml', 'GitHub Actions workflow'),
('circleci_config', 'config.yml', 'CircleCI configuration'),
('jenkins_file', 'Jenkinsfile', 'Jenkins pipeline'),

-- Package managers and dependencies
('npm_rc', '.npmrc', 'NPM configuration'),
('yarn_rc', '.yarnrc', 'Yarn configuration'),
('pip_requirements', 'requirements.txt', 'Python requirements'),
('pipfile', 'Pipfile', 'Pipenv configuration'),
('poetry_config', 'pyproject.toml', 'Python Poetry configuration'),
('setup_py', 'setup.py', 'Python setup script'),
('cargo_toml', 'Cargo.toml', 'Rust Cargo configuration'),
('cargo_lock', 'Cargo.lock', 'Rust Cargo lock file'),
('gemfile', 'Gemfile', 'Ruby Bundler dependencies'),
('gemfile_lock', 'Gemfile.lock', 'Ruby Bundler lock file'),
('go_mod', 'go.mod', 'Go modules file'),
('go_sum', 'go.sum', 'Go modules checksum'),
('composer_json', 'composer.json', 'PHP Composer dependencies'),

-- Build tools
('makefile', 'Makefile', 'Make build configuration'),
('rakefile', 'Rakefile', 'Ruby Rake build configuration'),
('gradle_build', 'build.gradle', 'Gradle build script'),
('maven_pom', 'pom.xml', 'Maven project configuration'),
('cmake', 'CMakeLists.txt', 'CMake build configuration'),

-- Programming languages
('rust', '.rs', 'Rust source file'),
('go', '.go', 'Go source file'),
('ruby', '.rb', 'Ruby source file'),
('java', '.java', 'Java source file'),
('kotlin', '.kt', 'Kotlin source file'),
('swift', '.swift', 'Swift source file'),
('c', '.c', 'C source file'),
('cpp', '.cpp', 'C++ source file'),
('csharp', '.cs', 'C# source file'),
('php', '.php', 'PHP source file'),
('scala', '.scala', 'Scala source file'),
('clojure', '.clj', 'Clojure source file'),
('elixir', '.ex', 'Elixir source file'),
('erlang', '.erl', 'Erlang source file'),
('haskell', '.hs', 'Haskell source file'),
('lua', '.lua', 'Lua source file'),
('perl', '.pl', 'Perl source file'),
('r', '.r', 'R source file'),

-- Infrastructure as Code
('terraform', '.tf', 'Terraform configuration'),
('terraform_vars', '.tfvars', 'Terraform variables'),
('ansible_playbook', 'playbook.yml', 'Ansible playbook'),
('ansible_inventory', 'inventory.yml', 'Ansible inventory'),
('kubernetes', 'k8s.yml', 'Kubernetes manifest'),
('helm_chart', 'Chart.yaml', 'Helm chart definition'),

-- More Nix files
('nix_shell', 'shell.nix', 'Nix shell environment'),
('nix_default', 'default.nix', 'Nix default expression'),
('nix_file', '.nix', 'Nix expression file'),

-- Platform-specific
('procfile', 'Procfile', 'Heroku Procfile'),
('vercel_config', 'vercel.json', 'Vercel configuration'),
('netlify_config', 'netlify.toml', 'Netlify configuration'),
('railway_config', 'railway.json', 'Railway configuration'),

-- Database
('sql_schema', 'schema.sql', 'Database schema'),
('prisma_schema', 'schema.prisma', 'Prisma schema'),

-- Testing
('jest_config', 'jest.config.js', 'Jest testing configuration'),
('pytest_config', 'pytest.ini', 'Pytest configuration'),
('test_file', '.test.js', 'Test file'),
('spec_file', '.spec.js', 'Spec file'),

-- Documentation
('readme', 'README', 'README file'),
('changelog', 'CHANGELOG.md', 'Changelog file'),
('license', 'LICENSE', 'License file'),
('contributing', 'CONTRIBUTING.md', 'Contributing guidelines'),

-- Linting and formatting
('rubocop', '.rubocop.yml', 'RuboCop configuration'),
('stylelint', '.stylelintrc', 'Stylelint configuration'),
('black_config', 'black.toml', 'Black formatter configuration'),
('flake8_config', '.flake8', 'Flake8 configuration'),

-- Security
('security_policy', 'SECURITY.md', 'Security policy'),
('dependabot', 'dependabot.yml', 'Dependabot configuration'),

-- Misc
('robots_txt', 'robots.txt', 'Robots.txt file'),
('htaccess', '.htaccess', 'Apache htaccess file'),
('browserslist', '.browserslistrc', 'Browserslist configuration'),
('babel_config', '.babelrc', 'Babel configuration'),
('webpack_config', 'webpack.config.js', 'Webpack configuration'),
('vite_config', 'vite.config.js', 'Vite configuration'),
('rollup_config', 'rollup.config.js', 'Rollup configuration');

-- Create index for faster file type lookups
CREATE INDEX IF NOT EXISTS idx_file_types_name ON file_types(name);
CREATE INDEX IF NOT EXISTS idx_file_types_extension ON file_types(extension);

-- Migration metadata
INSERT INTO schema_migrations (version, description, applied_at)
VALUES (17, 'Add dotfiles and common file types', CURRENT_TIMESTAMP)
ON CONFLICT(version) DO NOTHING;
