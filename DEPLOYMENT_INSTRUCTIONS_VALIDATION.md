# Deployment Instructions Validation & Failure Documentation

**Date**: 2026-03-03
**Status**: Complete
**Version**: 1.0

---

## Overview

Enhanced the deployment instructions generator to automatically validate generated instructions and provide comprehensive failure mode documentation with recovery procedures. This ensures that deployment instructions are accurate, actionable, and production-ready.

## Key Features

### 1. Automatic Validation

Every generated `DEPLOY_INSTRUCTIONS.md` file is automatically validated against the target environment:

- ✅ **Command Availability** - Verifies required commands exist (npm, node, direnv, docker, make)
- ✅ **Dependency Validation** - Checks for lock files and proper dependency configuration
- ✅ **Environment Configuration** - Validates environment variable setup
- ✅ **Run Mode Verification** - Ensures referenced scripts exist in package.json
- ✅ **File Path Validation** - Confirms referenced paths and directories exist

### 2. Validation Report

Each generated instruction file includes a validation report showing:

- **Overall Status** - Pass/Fail indicator
- **Errors** - Critical issues that must be fixed
- **Warnings** - Issues that should be addressed
- **Info** - Informational notices
- **Recommendations** - Specific actions to resolve each issue

### 3. Comprehensive Failure Mode Documentation

Seven common failure modes documented with detailed recovery procedures:

1. **Dependencies Not Installed** - Module not found errors
2. **Environment Variables Missing** - Configuration/connection failures
3. **Build Process Fails** - Compilation and bundling errors
4. **Port Already in Use** - Address binding conflicts
5. **Database Connection Failures** - Database connectivity issues
6. **File Permission Errors** - Access denied errors
7. **Memory/Resource Exhaustion** - Out of memory crashes

Each failure mode includes:
- **Symptoms** - How to recognize the problem
- **Root Causes** - What causes this failure
- **Recovery Procedure** - Step-by-step fix instructions
- **Prevention** - How to avoid the issue

### 4. Emergency Rollback Instructions

Built-in rollback procedures for critical situations:

```bash
# View deployment history
./templedb deploy history PROJECT --target TARGET

# Rollback to previous version
./templedb deploy rollback PROJECT --target TARGET

# Rollback to specific deployment
./templedb deploy rollback PROJECT --target TARGET --to-id ID
```

### 5. Health Check Commands

Standard health check procedures included in every instruction file:

- Process verification
- Port listening checks
- HTTP endpoint testing
- Log monitoring

---

## Implementation Details

### Validation Architecture

```
DeploymentInstructionsGenerator
├── _detect_capabilities()      # Detect project type, framework, scripts
├── validate()                   # Main validation entry point
│   ├── _validate_commands()     # Check command availability
│   ├── _validate_dependencies() # Check dependency configuration
│   ├── _validate_environment()  # Check environment setup
│   ├── _validate_run_modes()    # Check script references
│   └── _validate_file_paths()   # Check file/directory existence
├── generate()                   # Generate instruction content
├── _generate_troubleshooting()  # Generate failure documentation
└── write_to_file()             # Write with validation report
```

### Validation Classes

#### `ValidationIssue`

Represents a single validation issue:

```python
@dataclass
class ValidationIssue:
    severity: str      # 'error', 'warning', 'info'
    category: str      # 'environment', 'dependencies', 'commands', 'configuration'
    message: str       # Description of the issue
    recommendation: Optional[str]  # How to fix it
```

#### `ValidationResult`

Aggregates all validation issues:

```python
@dataclass
class ValidationResult:
    valid: bool                    # Overall pass/fail
    issues: List[ValidationIssue]  # All issues found

    @property
    def errors(self) -> List[ValidationIssue]

    @property
    def warnings(self) -> List[ValidationIssue]
```

### Validation Checks

#### 1. Command Availability

Checks if required commands are available on the system:

```python
def _validate_commands(self) -> List[ValidationIssue]:
    issues = []

    # Check npm/node for Node.js projects
    if self.capabilities.has_package_json:
        if not shutil.which('npm'):
            issues.append(ValidationIssue(
                severity='error',
                category='commands',
                message='npm command not found but package.json exists',
                recommendation='Install Node.js and npm in target environment'
            ))

    # Check direnv if .envrc exists
    if (self.work_dir / ".envrc").exists():
        if not shutil.which('direnv'):
            issues.append(ValidationIssue(
                severity='warning',
                category='commands',
                message='direnv not found but .envrc exists',
                recommendation='Install direnv or manually source environment variables'
            ))

    return issues
```

#### 2. Dependency Configuration

Validates dependency setup:

```python
def _validate_dependencies(self) -> List[ValidationIssue]:
    issues = []

    # Check for lock files
    has_lock = (self.work_dir / "package-lock.json").exists()
    has_yarn_lock = (self.work_dir / "yarn.lock").exists()

    if not has_lock and not has_yarn_lock:
        issues.append(ValidationIssue(
            severity='warning',
            category='dependencies',
            message='No lock file found (package-lock.json or yarn.lock)',
            recommendation='Run npm install locally and commit lock file'
        ))

    return issues
```

#### 3. Environment Configuration

Checks environment variable setup:

```python
def _validate_environment(self) -> List[ValidationIssue]:
    issues = []

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

    return issues
```

#### 4. Run Mode Verification

Ensures referenced scripts exist:

```python
def _validate_run_modes(self) -> List[ValidationIssue]:
    issues = []

    for mode_name, mode in self.capabilities.run_modes.items():
        if mode.script_name not in self.capabilities.npm_scripts:
            issues.append(ValidationIssue(
                severity='error',
                category='commands',
                message=f'Run mode "{mode_name}" references non-existent script "{mode.script_name}"',
                recommendation=f'Add "{mode.script_name}" script to package.json'
            ))

    return issues
```

#### 5. File Path Validation

Confirms file and directory structure:

```python
def _validate_file_paths(self) -> List[ValidationIssue]:
    issues = []

    if not self.work_dir.exists():
        issues.append(ValidationIssue(
            severity='error',
            category='configuration',
            message=f'Work directory does not exist: {self.work_dir}',
            recommendation='Verify deployment completed successfully'
        ))

    return issues
```

---

## Failure Mode Documentation

### Structure of Each Failure Mode

Each failure mode follows this template:

```markdown
#### N. Failure Mode Name

**Symptoms**:
- List of observable symptoms
- Error messages to look for
- Behavior indicating this failure

**Root Causes**:
- Underlying reasons for failure
- Common misconfigurations
- Environmental issues

**Recovery Procedure**:
```bash
# Step-by-step commands to fix the issue
# With explanatory comments
```

**Prevention**:
- Best practices to avoid this failure
- Configuration recommendations
- Monitoring suggestions
```

### Example: Dependencies Not Installed

```markdown
#### 1. Dependencies Not Installed / Module Not Found

**Symptoms**:
- `Error: Cannot find module 'xyz'`
- `MODULE_NOT_FOUND` errors
- Application crashes on startup

**Root Causes**:
- `npm install` not run after deployment
- `node_modules` directory missing or corrupt
- Package versions mismatch

**Recovery Procedure**:
```bash
# Step 1: Clean install dependencies
cd /path/to/deployment
rm -rf node_modules package-lock.json
npm install

# Step 2: Verify installation
npm list --depth=0

# Step 3: Retry the operation that failed
```

**Prevention**:
- Always run `npm install` after deployment
- Commit `package-lock.json` for reproducible builds
- Use `npm ci` instead of `npm install` in production
```

### Covered Failure Modes

1. **Dependencies Not Installed**
   - Module not found errors
   - Missing node_modules
   - Version mismatches

2. **Environment Variables Missing**
   - Undefined configuration values
   - Connection failures
   - Authentication errors

3. **Build Process Fails**
   - TypeScript compilation errors
   - Webpack/bundler failures
   - Out of memory during build

4. **Port Already in Use**
   - EADDRINUSE errors
   - Port binding conflicts
   - Zombie processes

5. **Database Connection Failures**
   - Connection timeouts
   - Authentication failures
   - Network/firewall issues

6. **File Permission Errors**
   - EACCES errors
   - Read-only filesystems
   - Incorrect ownership

7. **Memory/Resource Exhaustion**
   - Heap out of memory
   - Process crashes
   - Performance degradation

---

## Usage

### Automatic Validation

Validation runs automatically when generating instructions:

```python
from deployment_instructions import DeploymentInstructionsGenerator

generator = DeploymentInstructionsGenerator(
    work_dir=Path('/path/to/deployment'),
    project={'slug': 'myapp', 'name': 'My Application'},
    target_name='production'
)

# Generate and write with validation (default)
output_path = generator.write_to_file()
# Includes validation report in generated file
```

### Manual Validation

Run validation without generating instructions:

```python
# Run validation only
validation = generator.validate()

print(f"Valid: {validation.valid}")
print(f"Errors: {len(validation.errors)}")
print(f"Warnings: {len(validation.warnings)}")

# Check specific issues
for issue in validation.issues:
    print(f"[{issue.severity}] {issue.category}: {issue.message}")
    if issue.recommendation:
        print(f"  → {issue.recommendation}")
```

### Disabling Validation

If needed, validation can be disabled:

```python
# Write without validation report
output_path = generator.write_to_file(validate=False)
```

### Integration with Deployment

The deployment orchestrator automatically validates:

```python
# In DeploymentOrchestrator._generate_deploy_instructions()
generator = DeploymentInstructionsGenerator(
    work_dir=self.work_dir,
    project=self.project,
    target_name=self.target_name
)

# Validate before writing
validation = generator.validate()

# Write with validation report
output_path = generator.write_to_file(validate=True)

# Show validation summary
if validation.errors:
    print(f"   ⚠️  {len(validation.errors)} validation error(s) found")
if validation.warnings:
    print(f"   ⚠️  {len(validation.warnings)} validation warning(s) found")
if validation.valid:
    print(f"   ✓ Validation passed")
```

---

## Example Validation Report

Generated at the end of `DEPLOY_INSTRUCTIONS.md`:

```markdown
---

## Validation Report

**Status**: ⚠️  PASSED WITH WARNINGS

### ⚠️  Warnings (Should Fix)

**Dependencies**: No lock file found (package-lock.json or yarn.lock)

*Recommendation*: Run npm install locally and commit lock file for reproducible builds

**Commands**: direnv not found but .envrc exists

*Recommendation*: Install direnv or manually source environment variables

### ℹ️  Information

**Configuration**: No common source directories found (src, lib, dist, build, public)

*Recommendation*: Verify project structure is correct

---

*Validation performed on 2026-03-03 13:51:40*
```

---

## Benefits

### For Developers

1. **Confidence** - Know that instructions will work in target environment
2. **Faster Debugging** - Clear recovery procedures for common failures
3. **Self-Service** - Can fix issues without external help
4. **Learning** - Understand root causes and prevention

### For Operations

1. **Reduced Support Load** - Self-service troubleshooting
2. **Faster Recovery** - Step-by-step procedures ready
3. **Prevention** - Best practices built into instructions
4. **Consistency** - Same troubleshooting approach across projects

### For AI Agents

1. **Actionable** - Clear commands to execute
2. **Context-Aware** - Instructions match actual environment
3. **Error Recovery** - Knows how to fix common issues
4. **Validation** - Can verify setup is correct

---

## Testing

### Test Validation

```bash
# Create test project
mkdir -p /tmp/test-validation
cd /tmp/test-validation

# Create package.json
cat > package.json << 'EOF'
{
  "name": "test-app",
  "scripts": {
    "start": "node server.js",
    "dev": "nodemon server.js"
  }
}
EOF

# Test validation
python3 << 'PYTHON'
import sys
from pathlib import Path
sys.path.insert(0, 'src')

from deployment_instructions import DeploymentInstructionsGenerator

generator = DeploymentInstructionsGenerator(
    work_dir=Path('/tmp/test-validation'),
    project={'slug': 'test', 'name': 'Test'},
    target_name='production'
)

validation = generator.validate()
print(f"Valid: {validation.valid}")
print(f"Issues: {len(validation.issues)}")

for issue in validation.issues:
    print(f"  [{issue.severity}] {issue.message}")
PYTHON
```

### Test Generated Instructions

```bash
# Generate instructions
python3 << 'PYTHON'
import sys
from pathlib import Path
sys.path.insert(0, 'src')

from deployment_instructions import DeploymentInstructionsGenerator

generator = DeploymentInstructionsGenerator(
    work_dir=Path('/tmp/test-validation'),
    project={'slug': 'test', 'name': 'Test'},
    target_name='production'
)

output_path = generator.write_to_file(validate=True)
print(f"Generated: {output_path}")
PYTHON

# View generated instructions
cat /tmp/test-validation/DEPLOY_INSTRUCTIONS.md
```

---

## Future Enhancements

### Phase 2: Advanced Validation

1. **Runtime Validation**
   - Test database connections
   - Verify API endpoints are reachable
   - Check service dependencies

2. **Security Validation**
   - Scan for exposed secrets
   - Check file permissions
   - Validate SSL/TLS configuration

3. **Performance Validation**
   - Check resource limits
   - Validate cache configuration
   - Test load balancer setup

### Phase 3: Interactive Troubleshooting

1. **Guided Repair**
   - Interactive prompts to fix issues
   - Automatic application of fixes
   - Verification after repair

2. **Health Monitoring**
   - Continuous health checks
   - Automated alerting
   - Self-healing capabilities

3. **Learning System**
   - Track which failures occur most
   - Improve recovery procedures
   - Suggest preventive measures

---

## Summary

✅ **Automatic validation** of deployment instructions
✅ **Comprehensive failure mode documentation** with 7 common scenarios
✅ **Step-by-step recovery procedures** for each failure
✅ **Environment-specific validation** checks
✅ **Validation reports** included in generated instructions
✅ **Emergency rollback** procedures built-in
✅ **Health check commands** for verification

The enhanced deployment instructions provide production-ready, validated documentation that helps developers and AI agents successfully deploy and troubleshoot applications. The comprehensive failure mode coverage ensures quick recovery from common issues, reducing downtime and support burden.
