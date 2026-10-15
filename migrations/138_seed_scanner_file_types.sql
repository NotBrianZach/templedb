-- 138_seed_scanner_file_types.sql
--
-- Give `file_types` the vocabulary the scanner actually emits.
--
-- `FILE_TYPE_PATTERNS` in src/importer/scanner.py classifies ~140 types.
-- `file_types` held 66, and the two sets were never reconciled, which bites
-- in two places:
--
--   1. importer/__init__.py:138 — `if file.file_type not in self.file_types:
--      continue`. On project import, every Makefile, Rust source, Cargo.toml,
--      go.mod, README, LICENSE and .gitignore was counted in files_skipped
--      and dropped, because the scanner named a type the table had never
--      heard of.
--
--   2. cli/commands/commit.py::_get_file_type_id — it did not consult the
--      scanner at all; it carried a private 14-entry extension map and, for
--      anything outside it, took `SELECT id FROM file_types LIMIT 1`. That
--      row is `api_route`, which is why all 31 recorded files in
--      templedb-rust — main.rs, Cargo.lock, .gitignore — are typed as API
--      routes. That method now classifies via the scanner and inserts an
--      unknown type instead of coercing it to row 1.
--
-- Seeding the table closes (1) and makes (2) land the right id on the first
-- commit rather than the second. `text_file` and `binary_asset` are the
-- generic fallbacks the scanner uses for a git-tracked path it cannot
-- classify; before this they were simply dropped from the scan.
--
-- Idempotent: INSERT OR IGNORE against the UNIQUE(type_name).

INSERT OR IGNORE INTO file_types (type_name, category, description) VALUES
  -- Generic fallbacks for a tracked path the classifier does not recognise
  ('text_file',        'documentation',  'Unrecognised text file'),
  ('document',         'documentation',  'reStructuredText / AsciiDoc / Org'),
  ('csv',              'data',           'Comma-separated values'),
  ('latex',            'documentation',  'LaTeX source'),
  ('patch',            'documentation',  'Patch or diff'),

  -- Programming languages the scanner names but the table lacked
  ('rust',             'backend',        'Rust source'),
  ('go',               'backend',        'Go source'),
  ('ruby',             'backend',        'Ruby source'),
  ('java',             'backend',        'Java source'),
  ('kotlin',           'backend',        'Kotlin source'),
  ('swift',            'frontend',       'Swift source'),
  ('c',                'backend',        'C source'),
  ('cpp',              'backend',        'C++ source'),
  ('csharp',           'backend',        'C# source'),
  ('php',              'backend',        'PHP source'),
  ('scala',            'backend',        'Scala source'),
  ('clojure',          'backend',        'Clojure source'),
  ('elixir',           'backend',        'Elixir source'),
  ('erlang',           'backend',        'Erlang source'),
  ('haskell',          'backend',        'Haskell source'),
  ('lua',              'backend',        'Lua source'),
  ('perl',             'backend',        'Perl source'),
  ('r',                'backend',        'R source'),
  ('julia',            'backend',        'Julia source'),
  ('zig',              'backend',        'Zig source'),
  ('powershell',       'infrastructure', 'PowerShell script'),
  ('batch_script',     'infrastructure', 'Windows batch script'),

  -- Build and task runners
  ('makefile',         'infrastructure', 'Makefile'),
  ('justfile',         'infrastructure', 'just task runner'),
  ('taskfile',         'infrastructure', 'Task (go-task) runner'),
  ('rakefile',         'infrastructure', 'Rakefile'),
  ('gradle_build',     'infrastructure', 'Gradle build script'),
  ('maven_pom',        'infrastructure', 'Maven POM'),
  ('cmake',            'infrastructure', 'CMakeLists'),

  -- Package managers and lockfiles
  ('cargo_toml',       'infrastructure', 'Cargo manifest'),
  ('cargo_lock',       'infrastructure', 'Cargo lockfile'),
  ('go_mod',           'infrastructure', 'Go module file'),
  ('go_sum',           'infrastructure', 'Go checksum file'),
  ('gemfile',          'infrastructure', 'Gemfile'),
  ('gemfile_lock',     'infrastructure', 'Gemfile.lock'),
  ('pipfile',          'infrastructure', 'Pipfile'),
  ('pip_requirements', 'infrastructure', 'pip requirements'),
  ('poetry_config',    'infrastructure', 'pyproject.toml'),
  ('setup_py',         'infrastructure', 'setup.py'),
  ('composer_json',    'infrastructure', 'Composer manifest'),
  ('npm_lock',         'infrastructure', 'package-lock.json'),
  ('pnpm_lock',        'infrastructure', 'pnpm-lock.yaml'),
  ('yarn_lock',        'infrastructure', 'yarn.lock'),
  ('lock_file',        'infrastructure', 'Generic lockfile'),
  ('nix_flake_lock',   'infrastructure', 'flake.lock'),
  ('npm_rc',           'infrastructure', '.npmrc'),
  ('yarn_rc',          'infrastructure', '.yarnrc'),

  -- Containers and infrastructure
  ('docker_ignore',    'infrastructure', '.dockerignore'),
  ('caddyfile',        'infrastructure', 'Caddy server config'),
  ('vagrantfile',      'infrastructure', 'Vagrantfile'),
  ('brewfile',         'infrastructure', 'Homebrew Brewfile'),
  ('procfile',         'infrastructure', 'Procfile'),
  ('terraform_vars',   'infrastructure', 'Terraform variables'),
  ('ansible_playbook', 'infrastructure', 'Ansible playbook'),
  ('ansible_inventory','infrastructure', 'Ansible inventory'),
  ('helm_chart',       'infrastructure', 'Helm chart metadata'),
  ('systemd_service',  'infrastructure', 'systemd unit'),
  ('deployment_script','infrastructure', 'Deployment script'),
  ('deployment_config','infrastructure', 'Deployment config'),
  ('pm2_config',       'infrastructure', 'PM2 ecosystem config'),

  -- CI/CD
  ('github_workflow',  'infrastructure', 'GitHub Actions workflow'),
  ('gitlab_ci',        'infrastructure', 'GitLab CI config'),
  ('travis_ci',        'infrastructure', 'Travis CI config'),
  ('circleci_config',  'infrastructure', 'CircleCI config'),
  ('jenkins_file',     'infrastructure', 'Jenkinsfile'),
  ('dependabot',       'infrastructure', 'Dependabot config'),

  -- Interface definitions and data
  ('protobuf',         'backend',        'Protocol Buffers schema'),
  ('graphql',          'backend',        'GraphQL schema or query'),
  ('xml',              'data',           'XML document'),
  ('prisma_schema',    'database',       'Prisma schema'),
  ('config_file',      'infrastructure', 'INI / CFG / CONF / properties'),
  ('config_toml',      'infrastructure', 'TOML config'),

  -- Repo metadata and dotfiles
  ('readme',           'documentation',  'Extensionless README'),
  ('license',          'documentation',  'License text'),
  ('changelog',        'documentation',  'Changelog'),
  ('contributing',     'documentation',  'Contributing guide'),
  ('security_policy',  'documentation',  'Security policy'),
  ('codeowners',       'documentation',  'CODEOWNERS'),
  ('git_ignore',       'infrastructure', '.gitignore'),
  ('git_attributes',   'infrastructure', '.gitattributes'),
  ('git_modules',      'infrastructure', '.gitmodules'),
  ('git_config',       'infrastructure', '.gitconfig'),
  ('editor_config',    'infrastructure', '.editorconfig'),
  ('prettier_config',  'infrastructure', 'Prettier config'),
  ('eslint_config',    'infrastructure', 'ESLint config'),
  ('stylelint',        'infrastructure', 'Stylelint config'),
  ('babel_config',     'infrastructure', 'Babel config'),
  ('browserslist',     'infrastructure', 'Browserslist config'),
  ('flake8_config',    'infrastructure', 'flake8 config'),
  ('rubocop',          'infrastructure', 'RuboCop config'),
  ('pytest_config',    'infrastructure', 'pytest.ini'),
  ('vscode_settings',  'infrastructure', 'VS Code settings'),
  ('vim_config',       'infrastructure', '.vimrc'),
  ('nvim_config',      'infrastructure', 'init.vim'),
  ('bash_config',      'infrastructure', '.bashrc'),
  ('bash_profile',     'infrastructure', '.bash_profile'),
  ('zsh_config',       'infrastructure', '.zshrc'),
  ('shell_profile',    'infrastructure', '.profile'),
  ('shell_aliases',    'infrastructure', 'Shell aliases'),
  ('fish_config',      'infrastructure', 'fish config'),
  ('nvm_rc',           'infrastructure', '.nvmrc'),
  ('ruby_version',     'infrastructure', '.ruby-version'),
  ('python_version',   'infrastructure', '.python-version'),
  ('node_version',     'infrastructure', '.node-version'),
  ('htaccess',         'infrastructure', '.htaccess'),
  ('robots_txt',       'frontend',       'robots.txt'),

  -- Build-tool configs the scanner names individually
  ('jest_config',      'infrastructure', 'Jest config'),
  ('webpack_config',   'infrastructure', 'webpack config'),
  ('vite_config',      'infrastructure', 'Vite config'),
  ('rollup_config',    'infrastructure', 'Rollup config'),
  ('vercel_config',    'infrastructure', 'Vercel config'),
  ('netlify_config',   'infrastructure', 'Netlify config'),
  ('railway_config',   'infrastructure', 'Railway config'),
  ('test_file',        'backend',        'Test file'),
  ('spec_file',        'backend',        'Spec file'),
  ('binary_encrypted', 'infrastructure', 'Encrypted blob (.gpg)'),
  ('text_asc',         'infrastructure', 'ASCII-armoured key or signature');
