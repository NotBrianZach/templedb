#!/usr/bin/env python3
"""
Deployment Instructions Generator

Auto-generates DEPLOY_INSTRUCTIONS.md with context-aware runtime instructions
for deployed projects. Detects run modes, npm scripts, and provides agent-friendly
documentation.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class RunMode:
    """Represents a detected run mode (dev, prod, test)"""
    name: str
    command: str
    script_name: str
    description: str


@dataclass
class ProjectCapabilities:
    """Detected capabilities and metadata about a project"""
    project_type: str = "Unknown"
    framework: Optional[str] = None
    has_package_json: bool = False
    has_package_lock: bool = False
    has_yarn_lock: bool = False
    has_requirements_txt: bool = False
    has_poetry_lock: bool = False
    has_pipfile_lock: bool = False
    has_dockerfile: bool = False
    has_makefile: bool = False
    npm_scripts: Dict[str, str] = field(default_factory=dict)
    run_modes: Dict[str, RunMode] = field(default_factory=dict)
    dependencies: Dict[str, str] = field(default_factory=dict)
    dev_dependencies: Dict[str, str] = field(default_factory=dict)


@dataclass
class ValidationIssue:
    """Represents a validation issue found in instructions"""
    severity: str  # 'error', 'warning', 'info'
    category: str  # 'environment', 'dependencies', 'commands', 'configuration'
    message: str
    recommendation: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of validating deployment instructions"""
    valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == 'error']

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == 'warning']


class DeploymentInstructionsGenerator:
    """Generates deployment instructions for deployed projects"""

    def __init__(self, work_dir: Path, project: Dict[str, Any], target_name: str):
        """
        Initialize generator

        Args:
            work_dir: Working directory with deployed files
            project: Project metadata from database
            target_name: Deployment target name
        """
        self.work_dir = work_dir
        self.project = project
        self.target_name = target_name
        self.capabilities = self._detect_capabilities()

    def validate(self) -> ValidationResult:
        """
        Validate that generated instructions will work in target environment

        Returns:
            ValidationResult with any issues found
        """
        issues = []

        # Check 1: Verify commands referenced in instructions exist
        issues.extend(self._validate_commands())

        # Check 2: Verify dependencies are installable
        issues.extend(self._validate_dependencies())

        # Check 3: Verify environment configuration is complete
        issues.extend(self._validate_environment())

        # Check 4: Verify run modes are executable
        issues.extend(self._validate_run_modes())

        # Check 5: Verify file paths exist
        issues.extend(self._validate_file_paths())

        # Determine if validation passed
        has_errors = any(i.severity == 'error' for i in issues)

        return ValidationResult(
            valid=not has_errors,
            issues=issues
        )

    def _validate_commands(self) -> List[ValidationIssue]:
        """Validate that referenced commands exist"""
        issues = []
        import shutil

        # Check for npm (if Node.js project)
        if self.capabilities.has_package_json:
            if not shutil.which('npm'):
                issues.append(ValidationIssue(
                    severity='error',
                    category='commands',
                    message='npm command not found but package.json exists',
                    recommendation='Install Node.js and npm in target environment'
                ))
            elif not shutil.which('node'):
                issues.append(ValidationIssue(
                    severity='error',
                    category='commands',
                    message='node command not found but package.json exists',
                    recommendation='Install Node.js in target environment'
                ))

        # Check for direnv (if .envrc exists)
        if (self.work_dir / ".envrc").exists():
            if not shutil.which('direnv'):
                issues.append(ValidationIssue(
                    severity='warning',
                    category='commands',
                    message='direnv not found but .envrc exists',
                    recommendation='Install direnv or manually source environment variables'
                ))

        # Check for docker (if Dockerfile exists)
        if self.capabilities.has_dockerfile:
            if not shutil.which('docker'):
                issues.append(ValidationIssue(
                    severity='warning',
                    category='commands',
                    message='docker not found but Dockerfile exists',
                    recommendation='Install Docker if container deployment is needed'
                ))

        # Check for make (if Makefile exists)
        if self.capabilities.has_makefile:
            if not shutil.which('make'):
                issues.append(ValidationIssue(
                    severity='warning',
                    category='commands',
                    message='make not found but Makefile exists',
                    recommendation='Install make or run commands manually'
                ))

        return issues

    def _validate_dependencies(self) -> List[ValidationIssue]:
        """Validate that dependencies can be installed"""
        issues = []

        if self.capabilities.has_package_json:
            if not self.capabilities.has_package_lock and not self.capabilities.has_yarn_lock:
                issues.append(ValidationIssue(
                    severity='warning',
                    category='dependencies',
                    message='No lock file found (package-lock.json or yarn.lock)',
                    recommendation='Run npm install locally and commit lock file for reproducible builds'
                ))

        # Validate Python lock files
        if self.capabilities.project_type == "Python":
            has_python_lock = (
                self.capabilities.has_poetry_lock or
                self.capabilities.has_pipfile_lock
            )

            if not has_python_lock and self.capabilities.has_requirements_txt:
                issues.append(ValidationIssue(
                    severity='info',
                    category='dependencies',
                    message='No Python lock file found (poetry.lock or Pipfile.lock)',
                    recommendation='Consider using poetry or pipenv for reproducible Python builds'
                ))

            # Check for node_modules (should not be deployed)
            if (self.work_dir / "node_modules").exists():
                issues.append(ValidationIssue(
                    severity='info',
                    category='dependencies',
                    message='node_modules directory found in deployment',
                    recommendation='Consider excluding node_modules and running npm install on target'
                ))

        return issues

    def _validate_environment(self) -> List[ValidationIssue]:
        """Validate environment configuration"""
        issues = []

        # Check if environment files exist
        has_envrc = (self.work_dir / ".envrc").exists()
        has_env = (self.work_dir / ".env").exists()
        has_env_example = (self.work_dir / ".env.example").exists()

        if not has_envrc and not has_env:
            if has_env_example:
                issues.append(ValidationIssue(
                    severity='warning',
                    category='environment',
                    message='No .env or .envrc found, but .env.example exists',
                    recommendation='Copy .env.example to .env and configure values'
                ))
            else:
                issues.append(ValidationIssue(
                    severity='info',
                    category='environment',
                    message='No environment configuration files detected',
                    recommendation='Application may require environment variables to be set manually'
                ))

        # Check for common required environment variables in scripts
        if self.capabilities.npm_scripts:
            for script_name, command in self.capabilities.npm_scripts.items():
                # Look for environment variable references
                if '$' in command or 'process.env' in command:
                    issues.append(ValidationIssue(
                        severity='info',
                        category='environment',
                        message=f'Script "{script_name}" may require environment variables',
                        recommendation='Ensure all required environment variables are configured'
                    ))
                    break  # Only warn once

        return issues

    def _validate_run_modes(self) -> List[ValidationIssue]:
        """Validate that run modes are executable"""
        issues = []

        for mode_name, mode in self.capabilities.run_modes.items():
            # Verify the script exists in package.json
            if mode.script_name not in self.capabilities.npm_scripts:
                issues.append(ValidationIssue(
                    severity='error',
                    category='commands',
                    message=f'Run mode "{mode_name}" references non-existent script "{mode.script_name}"',
                    recommendation=f'Add "{mode.script_name}" script to package.json'
                ))

        # Check for essential run modes
        if self.capabilities.has_package_json:
            if not self.capabilities.run_modes:
                issues.append(ValidationIssue(
                    severity='warning',
                    category='configuration',
                    message='No run modes detected (no start/dev scripts found)',
                    recommendation='Add "start" or "dev" script to package.json'
                ))

        return issues

    def _validate_file_paths(self) -> List[ValidationIssue]:
        """Validate that referenced file paths exist"""
        issues = []

        # Check if work_dir exists
        if not self.work_dir.exists():
            issues.append(ValidationIssue(
                severity='error',
                category='configuration',
                message=f'Work directory does not exist: {self.work_dir}',
                recommendation='Verify deployment completed successfully'
            ))

        # Check for common directories
        common_dirs = ['src', 'lib', 'dist', 'build', 'public']
        found_dirs = [d for d in common_dirs if (self.work_dir / d).exists()]

        if not found_dirs and self.capabilities.project_type != "Unknown":
            issues.append(ValidationIssue(
                severity='info',
                category='configuration',
                message='No common source directories found (src, lib, dist, build, public)',
                recommendation='Verify project structure is correct'
            ))

        return issues

    def _detect_capabilities(self) -> ProjectCapabilities:
        """Detect project capabilities and available run modes"""
        caps = ProjectCapabilities()

        # Check for package.json (Node.js project)
        package_json_path = self.work_dir / "package.json"
        if package_json_path.exists():
            caps.has_package_json = True
            caps.project_type = "Node.js"

            try:
                with open(package_json_path) as f:
                    pkg = json.load(f)

                # Extract npm scripts
                caps.npm_scripts = pkg.get('scripts', {})
                caps.dependencies = pkg.get('dependencies', {})
                caps.dev_dependencies = pkg.get('devDependencies', {})

                # Detect framework
                caps.framework = self._detect_framework(caps.dependencies, caps.dev_dependencies)

                # Detect run modes from scripts
                caps.run_modes = self._detect_run_modes(caps.npm_scripts)
            except Exception as e:
                print(f"Warning: Could not parse package.json: {e}")

        # Check for other project types
        if (self.work_dir / "Dockerfile").exists():
            caps.has_dockerfile = True

        if (self.work_dir / "Makefile").exists():
            caps.has_makefile = True

        # Detect lock files for npm/yarn
        if (self.work_dir / "package-lock.json").exists():
            caps.has_package_lock = True
        if (self.work_dir / "yarn.lock").exists():
            caps.has_yarn_lock = True

        # Python project detection
        if (self.work_dir / "requirements.txt").exists() or (self.work_dir / "setup.py").exists():
            if caps.project_type == "Unknown":
                caps.project_type = "Python"
            caps.has_requirements_txt = (self.work_dir / "requirements.txt").exists()

        # Detect Python lock files
        if (self.work_dir / "poetry.lock").exists():
            caps.has_poetry_lock = True
            if caps.project_type == "Unknown":
                caps.project_type = "Python"
        if (self.work_dir / "Pipfile.lock").exists():
            caps.has_pipfile_lock = True
            if caps.project_type == "Unknown":
                caps.project_type = "Python"

        return caps

    def _detect_framework(self, deps: Dict[str, str], dev_deps: Dict[str, str]) -> Optional[str]:
        """Detect web framework from dependencies"""
        all_deps = {**deps, **dev_deps}

        if 'next' in all_deps:
            return 'Next.js'
        elif 'react' in all_deps:
            return 'React'
        elif 'vue' in all_deps:
            return 'Vue.js'
        elif 'express' in all_deps:
            return 'Express'
        elif '@nestjs/core' in all_deps:
            return 'NestJS'
        elif 'svelte' in all_deps:
            return 'Svelte'

        return None

    def _detect_run_modes(self, scripts: Dict[str, str]) -> Dict[str, RunMode]:
        """Detect available run modes from npm scripts"""
        modes = {}

        # Development mode
        if 'dev' in scripts:
            modes['development'] = RunMode(
                name='development',
                command=scripts['dev'],
                script_name='dev',
                description='Start development server with hot reload'
            )
        elif 'start' in scripts:
            modes['development'] = RunMode(
                name='development',
                command=scripts['start'],
                script_name='start',
                description='Start the application in development mode'
            )

        # Production mode
        if 'start:prod' in scripts:
            modes['production'] = RunMode(
                name='production',
                command=scripts['start:prod'],
                script_name='start:prod',
                description='Start the application in production mode'
            )
        elif 'serve' in scripts:
            modes['production'] = RunMode(
                name='production',
                command=scripts['serve'],
                script_name='serve',
                description='Serve the built application'
            )

        # Test mode
        if 'test' in scripts:
            modes['test'] = RunMode(
                name='test',
                command=scripts['test'],
                script_name='test',
                description='Run test suite'
            )

        # Build mode
        if 'build' in scripts:
            modes['build'] = RunMode(
                name='build',
                command=scripts['build'],
                script_name='build',
                description='Build the application for production'
            )

        return modes

    def generate(self, deployment_result=None) -> str:
        """
        Generate deployment instructions markdown

        Args:
            deployment_result: Optional DeploymentResult for including deployment details

        Returns:
            Markdown content for DEPLOY_INSTRUCTIONS.md
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        content = [
            f"# Deployment Instructions",
            f"",
            f"**Generated**: {timestamp}",
            f"**Auto-generated by TempleDB deployment system**",
            f"",
            f"## Deployment Context",
            f"",
            f"- **Project**: {self.project.get('name', 'Unknown')}",
            f"- **Slug**: {self.project.get('slug', 'Unknown')}",
            f"- **Target**: {self.target_name}",
            f"- **Working Directory**: `{self.work_dir}`",
            f"- **Project Type**: {self.capabilities.project_type}",
        ]

        if self.capabilities.framework:
            content.append(f"- **Framework**: {self.capabilities.framework}")

        content.extend([
            f"",
            f"---",
            f"",
        ])

        # Quick Start section
        content.extend(self._generate_quick_start())

        # Available Run Modes
        if self.capabilities.run_modes:
            content.extend(self._generate_run_modes())

        # Available npm Scripts
        if self.capabilities.npm_scripts:
            content.extend(self._generate_npm_scripts())

        # Environment Setup
        content.extend(self._generate_environment_setup())

        # Agent Instructions
        content.extend(self._generate_agent_instructions())

        # Troubleshooting
        content.extend(self._generate_troubleshooting())

        return "\n".join(content)

    def _generate_quick_start(self) -> List[str]:
        """Generate quick start commands"""
        lines = [
            "## Quick Start",
            "",
            "```bash",
            f"# 1. Navigate to deployment directory",
            f"cd {self.work_dir}",
            "",
        ]

        # Environment loading
        if (self.work_dir / ".envrc").exists():
            lines.extend([
                "# 2. Load environment variables",
                "direnv allow",
                "",
            ])

        # Install dependencies
        if self.capabilities.has_package_json:
            # Use npm ci if package-lock.json exists, yarn if yarn.lock exists
            if self.capabilities.has_package_lock:
                install_cmd = "npm ci"
            elif self.capabilities.has_yarn_lock:
                install_cmd = "yarn install --frozen-lockfile"
            else:
                install_cmd = "npm install"

            lines.extend([
                "# 3. Install dependencies (if needed)",
                install_cmd,
                "",
            ])

        # Install Python dependencies
        if self.capabilities.project_type == "Python":
            if self.capabilities.has_poetry_lock:
                install_cmd = "poetry install --no-dev"
            elif self.capabilities.has_pipfile_lock:
                install_cmd = "pipenv install --deploy"
            elif self.capabilities.has_requirements_txt:
                install_cmd = "pip install -r requirements.txt"
            else:
                install_cmd = None

            if install_cmd:
                lines.extend([
                    "# 3. Install Python dependencies",
                    install_cmd,
                    "",
                ])

        # Build if available
        if 'build' in self.capabilities.run_modes:
            lines.extend([
                "# 4. Build the project",
                "npm run build",
                "",
            ])

        # Start application
        if 'development' in self.capabilities.run_modes:
            mode = self.capabilities.run_modes['development']
            lines.extend([
                f"# 5. Start the application",
                f"npm run {mode.script_name}",
            ])

        lines.extend([
            "```",
            "",
        ])

        return lines

    def _generate_run_modes(self) -> List[str]:
        """Generate available run modes section"""
        lines = [
            "## Available Run Modes",
            "",
        ]

        for mode_name, mode in self.capabilities.run_modes.items():
            lines.extend([
                f"### {mode_name.title()} Mode",
                "",
                f"**Description**: {mode.description}",
                "",
                f"**Command**:",
                f"```bash",
                f"npm run {mode.script_name}",
                f"```",
                "",
            ])

        return lines

    def _generate_npm_scripts(self) -> List[str]:
        """Generate npm scripts listing"""
        lines = [
            "## Available npm Scripts",
            "",
            "| Script | Command |",
            "|--------|---------|",
        ]

        for script_name, command in sorted(self.capabilities.npm_scripts.items()):
            # Escape pipe characters in commands
            escaped_command = command.replace('|', '\\|')
            lines.append(f"| `{script_name}` | `{escaped_command}` |")

        lines.extend(["", ""])

        return lines

    def _generate_environment_setup(self) -> List[str]:
        """Generate environment setup section"""
        lines = [
            "## Environment Configuration",
            "",
        ]

        if (self.work_dir / ".envrc").exists():
            lines.extend([
                "Environment variables are managed via `.envrc` (direnv).",
                "",
                "**To load environment**:",
                "```bash",
                "direnv allow",
                "```",
                "",
            ])
        elif (self.work_dir / ".env").exists():
            lines.extend([
                "Environment variables are stored in `.env` file.",
                "",
                "**Note**: Make sure to configure `.env` with proper values before running.",
                "",
            ])
        else:
            lines.extend([
                "**Note**: No `.env` or `.envrc` file detected. You may need to set environment variables manually.",
                "",
            ])

        return lines

    def _generate_agent_instructions(self) -> List[str]:
        """Generate instructions specifically for AI agents (Claude Code)"""
        lines = [
            "## For AI Agents (Claude Code)",
            "",
            "### Quick Reference",
            "",
        ]

        # Primary run command
        if 'development' in self.capabilities.run_modes:
            mode = self.capabilities.run_modes['development']
            lines.extend([
                f"**To run this application**:",
                f"```bash",
                f"cd {self.work_dir}",
            ])
            if (self.work_dir / ".envrc").exists():
                lines.append("direnv allow")
            lines.extend([
                f"npm run {mode.script_name}",
                f"```",
                "",
            ])

        # Test command
        if 'test' in self.capabilities.run_modes:
            lines.extend([
                "**To run tests**:",
                "```bash",
                "npm test",
                "```",
                "",
            ])

        # Build command
        if 'build' in self.capabilities.run_modes:
            lines.extend([
                "**To rebuild after changes**:",
                "```bash",
                "npm run build",
                "```",
                "",
            ])

        # Project structure hints
        lines.extend([
            "### Project Structure",
            "",
            f"- **Type**: {self.capabilities.project_type}",
        ])

        if self.capabilities.framework:
            lines.append(f"- **Framework**: {self.capabilities.framework}")

        lines.extend([
            f"- **Source**: Look for code in `src/` or similar directories",
            f"- **Tests**: Check `tests/` or `__tests__/` directories",
            "",
        ])

        return lines

    def _generate_troubleshooting(self) -> List[str]:
        """Generate comprehensive troubleshooting section with failure modes and recovery"""
        lines = [
            "## Troubleshooting & Recovery Procedures",
            "",
            "### Common Failure Modes",
            "",
        ]

        # Failure Mode 1: Dependencies
        lines.extend([
            "#### 1. Dependencies Not Installed / Module Not Found",
            "",
            "**Symptoms**:",
            "- `Error: Cannot find module 'xyz'`",
            "- `MODULE_NOT_FOUND` errors",
            "- Application crashes on startup",
            "",
            "**Root Causes**:",
            "- `npm install` not run after deployment",
            "- `node_modules` directory missing or corrupt",
            "- Package versions mismatch",
            "",
            "**Recovery Procedure**:",
            "```bash",
            "# Step 1: Clean install dependencies",
            "cd " + str(self.work_dir),
            "rm -rf node_modules",
        ])

        # Add appropriate install command based on lock file
        if self.capabilities.has_package_lock:
            lines.append("npm ci")
        elif self.capabilities.has_yarn_lock:
            lines.append("yarn install --frozen-lockfile")
        else:
            lines.append("npm install")

        lines.extend([
            "",
            "# Step 2: Verify installation",
            "npm list --depth=0",
            "",
            "# Step 3: Retry the operation that failed",
            "```",
            "",
            "**Prevention**:",
            "- Always commit lock files (package-lock.json or yarn.lock)",
            "- Use `npm ci` or `yarn install --frozen-lockfile` in production",
            "- Never delete lock files during deployment",
            "",
        ])

        # Failure Mode 2: Environment Variables
        lines.extend([
            "#### 2. Environment Variables Missing / Incorrect",
            "",
            "**Symptoms**:",
            "- `undefined` errors for configuration values",
            "- Connection failures to databases/APIs",
            "- Authentication errors",
            "- Features not working as expected",
            "",
            "**Root Causes**:",
            "- `.env` or `.envrc` not loaded",
            "- Environment variables not set in target environment",
            "- Typos in variable names",
            "",
            "**Recovery Procedure**:",
        ])

        if (self.work_dir / ".envrc").exists():
            lines.extend([
                "```bash",
                "# Step 1: Load environment with direnv",
                "cd " + str(self.work_dir),
                "direnv allow",
                "",
                "# Step 2: Verify variables loaded",
                "echo $DATABASE_URL  # Example - check key variables",
                "",
                "# Step 3: If direnv not available, source manually",
                "export $(grep -v '^#' .envrc | xargs)",
                "```",
            ])
        elif (self.work_dir / ".env").exists():
            lines.extend([
                "```bash",
                "# Step 1: Source .env file",
                "cd " + str(self.work_dir),
                "export $(grep -v '^#' .env | xargs)",
                "",
                "# Step 2: Verify variables loaded",
                "env | grep DATABASE  # Example - check key variables",
                "```",
            ])
        else:
            lines.extend([
                "```bash",
                "# Check if environment variables are set",
                "env | grep -i database",
                "env | grep -i api",
                "",
                "# Set required variables manually",
                "export DATABASE_URL='your-database-url'",
                "export API_KEY='your-api-key'",
                "```",
            ])

        lines.extend([
            "",
            "**Prevention**:",
            "- Use `.env.example` as template for required variables",
            "- Validate environment variables before starting application",
            "- Use deployment orchestrator's environment validation",
            "",
        ])

        # Failure Mode 3: Build Failures
        if 'build' in self.capabilities.run_modes:
            lines.extend([
                "#### 3. Build Process Fails",
                "",
                "**Symptoms**:",
                "- Build command exits with error",
                "- TypeScript compilation errors",
                "- Webpack/bundler errors",
                "- Missing output files",
                "",
                "**Root Causes**:",
                "- Missing dependencies",
                "- TypeScript type errors",
                "- Configuration file issues",
                "- Out of memory",
                "",
                "**Recovery Procedure**:",
                "```bash",
                "# Step 1: Clean previous build artifacts",
                "cd " + str(self.work_dir),
                "rm -rf dist/ build/ .next/ .nuxt/  # Remove build outputs",
                "",
                "# Step 2: Clean install dependencies",
                "rm -rf node_modules package-lock.json",
                "npm install",
                "",
                "# Step 3: Rebuild with verbose output",
                "npm run build -- --verbose",
                "",
                "# Step 4: If out of memory, increase Node heap size",
                "export NODE_OPTIONS='--max-old-space-size=4096'",
                "npm run build",
                "```",
                "",
                "**Prevention**:",
                "- Fix all TypeScript/linting errors before deployment",
                "- Test build process locally before deploying",
                "- Ensure adequate memory in target environment",
                "",
            ])

        # Failure Mode 4: Port Already in Use
        lines.extend([
            "#### 4. Port Already in Use",
            "",
            "**Symptoms**:",
            "- `EADDRINUSE` error",
            "- Application fails to start",
            "- Port binding errors",
            "",
            "**Root Causes**:",
            "- Previous instance still running",
            "- Another service using the same port",
            "- Zombie processes",
            "",
            "**Recovery Procedure**:",
            "```bash",
            "# Step 1: Find process using the port (example: port 3000)",
            "lsof -i :3000",
            "# OR",
            "netstat -tulpn | grep :3000",
            "",
            "# Step 2: Kill the process",
            "kill -9 <PID>",
            "",
            "# Step 3: Verify port is free",
            "lsof -i :3000  # Should return nothing",
            "",
            "# Step 4: Restart application",
            "npm run start",
            "```",
            "",
            "**Prevention**:",
            "- Use process managers (PM2, systemd) to handle restarts",
            "- Implement graceful shutdown handling",
            "- Configure unique ports for each service",
            "",
        ])

        # Failure Mode 5: Database Connection Failures
        lines.extend([
            "#### 5. Database Connection Failures",
            "",
            "**Symptoms**:",
            "- Connection timeout errors",
            "- Authentication failed errors",
            "- Database not found errors",
            "",
            "**Root Causes**:",
            "- Incorrect connection string",
            "- Database server not running",
            "- Network/firewall issues",
            "- Invalid credentials",
            "",
            "**Recovery Procedure**:",
            "```bash",
            "# Step 1: Verify database connection string",
            "echo $DATABASE_URL",
            "",
            "# Step 2: Test database connectivity",
            "# For PostgreSQL:",
            "psql $DATABASE_URL -c 'SELECT 1'",
            "",
            "# For MySQL:",
            "mysql -u username -p -h hostname -e 'SELECT 1'",
            "",
            "# Step 3: Check if database server is running",
            "# For PostgreSQL:",
            "pg_isready -h hostname",
            "",
            "# Step 4: Verify credentials are correct",
            "# Check environment variables match database configuration",
            "",
            "# Step 5: Test network connectivity",
            "telnet database-host 5432  # PostgreSQL default port",
            "```",
            "",
            "**Prevention**:",
            "- Use connection pooling and retry logic",
            "- Validate database URL format before deployment",
            "- Test database connectivity in pre-deployment checks",
            "",
        ])

        # Failure Mode 6: Permission Errors
        lines.extend([
            "#### 6. File Permission Errors",
            "",
            "**Symptoms**:",
            "- `EACCES` errors",
            "- Permission denied errors",
            "- Cannot write to file/directory",
            "",
            "**Root Causes**:",
            "- Incorrect file ownership",
            "- Missing write permissions",
            "- Read-only filesystem",
            "",
            "**Recovery Procedure**:",
            "```bash",
            "# Step 1: Check current permissions",
            "ls -la " + str(self.work_dir),
            "",
            "# Step 2: Fix ownership (if needed)",
            "sudo chown -R $USER:$USER " + str(self.work_dir),
            "",
            "# Step 3: Fix permissions",
            "chmod -R u+rwX " + str(self.work_dir),
            "",
            "# Step 4: Ensure writable directories exist",
            "mkdir -p tmp/ logs/ uploads/",
            "chmod 755 tmp/ logs/ uploads/",
            "```",
            "",
            "**Prevention**:",
            "- Deploy with consistent user/group",
            "- Set correct permissions in deployment scripts",
            "- Use dedicated directories for temporary/log files",
            "",
        ])

        # Failure Mode 7: Memory/Resource Exhaustion
        lines.extend([
            "#### 7. Out of Memory / Resource Exhaustion",
            "",
            "**Symptoms**:",
            "- Application crashes with no error",
            "- `JavaScript heap out of memory`",
            "- Slow performance",
            "- Process killed by system",
            "",
            "**Root Causes**:",
            "- Memory leaks",
            "- Insufficient heap size",
            "- Too many concurrent connections",
            "- Large file processing",
            "",
            "**Recovery Procedure**:",
            "```bash",
            "# Step 1: Increase Node.js heap size",
            "export NODE_OPTIONS='--max-old-space-size=4096'",
            "",
            "# Step 2: Check system memory",
            "free -h",
            "top -o %MEM",
            "",
            "# Step 3: Restart with monitoring",
            "node --max-old-space-size=4096 server.js",
            "",
            "# Step 4: Profile memory usage if issue persists",
            "node --inspect server.js",
            "# Connect with Chrome DevTools to profile memory",
            "```",
            "",
            "**Prevention**:",
            "- Profile application for memory leaks",
            "- Implement connection pooling",
            "- Use streaming for large file operations",
            "- Monitor memory usage in production",
            "",
        ])

        # Rollback procedure
        lines.extend([
            "### Emergency Rollback",
            "",
            "If deployment is causing critical issues:",
            "",
            "```bash",
            "# View deployment history",
            f"./templedb deploy history {self.project.get('slug', 'PROJECT')} --target {self.target_name}",
            "",
            "# Rollback to previous version",
            f"./templedb deploy rollback {self.project.get('slug', 'PROJECT')} --target {self.target_name}",
            "",
            "# Rollback to specific deployment ID",
            f"./templedb deploy rollback {self.project.get('slug', 'PROJECT')} --target {self.target_name} --to-id <ID>",
            "```",
            "",
        ])

        # Health checks
        lines.extend([
            "### Health Check Commands",
            "",
            "Verify application is working correctly:",
            "",
            "```bash",
            "# Check if application is running",
            "ps aux | grep node",
            "",
            "# Check process is listening on port",
            "lsof -i :3000  # Replace 3000 with your port",
            "",
            "# Test HTTP endpoint",
            "curl http://localhost:3000/health",
            "",
            "# Check logs for errors",
            "tail -f logs/application.log",
            "# OR if using PM2",
            "pm2 logs",
            "```",
            "",
        ])

        # Getting help
        lines.extend([
            "### Getting Help",
            "",
            "If issues persist:",
            "",
            "1. **Check logs**: Look in `logs/` directory or use `pm2 logs`",
            "2. **Review deployment history**: Use `./templedb deploy history`",
            "3. **Verify environment**: Ensure all environment variables are set",
            "4. **Test locally**: Try running the same commands on your development machine",
            "5. **Rollback**: Use `./templedb deploy rollback` to revert to working version",
            "",
        ])

        return lines

    def write_to_file(self, content: Optional[str] = None, validate: bool = True) -> Path:
        """
        Write instructions to DEPLOY_INSTRUCTIONS.md

        Args:
            content: Optional pre-generated content, will generate if not provided
            validate: If True, validate instructions and include validation report

        Returns:
            Path to written file
        """
        if content is None:
            content = self.generate()

        # Run validation if requested
        if validate:
            validation_result = self.validate()

            # Add validation report to content
            validation_section = self._generate_validation_report(validation_result)
            if validation_section:
                content += "\n\n" + validation_section

        output_path = self.work_dir / "DEPLOY_INSTRUCTIONS.md"
        output_path.write_text(content)

        return output_path

    def _generate_validation_report(self, validation: ValidationResult) -> str:
        """Generate validation report section"""
        if not validation.issues:
            return ""

        lines = [
            "---",
            "",
            "## Validation Report",
            "",
            f"**Status**: {'✅ PASSED' if validation.valid else '❌ FAILED'}",
            "",
        ]

        if validation.errors:
            lines.extend([
                "### ❌ Errors (Must Fix)",
                "",
            ])
            for issue in validation.errors:
                lines.extend([
                    f"**{issue.category.title()}**: {issue.message}",
                    "",
                ])
                if issue.recommendation:
                    lines.extend([
                        f"*Recommendation*: {issue.recommendation}",
                        "",
                    ])

        if validation.warnings:
            lines.extend([
                "### ⚠️  Warnings (Should Fix)",
                "",
            ])
            for issue in validation.warnings:
                lines.extend([
                    f"**{issue.category.title()}**: {issue.message}",
                    "",
                ])
                if issue.recommendation:
                    lines.extend([
                        f"*Recommendation*: {issue.recommendation}",
                        "",
                    ])

        # Info issues
        info_issues = [i for i in validation.issues if i.severity == 'info']
        if info_issues:
            lines.extend([
                "### ℹ️  Information",
                "",
            ])
            for issue in info_issues:
                lines.extend([
                    f"**{issue.category.title()}**: {issue.message}",
                    "",
                ])
                if issue.recommendation:
                    lines.extend([
                        f"*Recommendation*: {issue.recommendation}",
                        "",
                    ])

        lines.extend([
            "---",
            "",
            f"*Validation performed on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])

        return "\n".join(lines)
