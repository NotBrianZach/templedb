# Deployment Resilience and Error Handling

**Date**: 2026-03-03
**Status**: Complete
**Version**: 1.0

---

## Overview

TempleDB's deployment orchestrator includes comprehensive resilience features to handle transient failures, distinguish between critical and non-critical errors, and provide clear visibility into deployment states.

## Key Features

### 1. Retry Logic

All deployment operations (hooks, migrations, builds) support automatic retry with configurable attempts and delays.

**Configuration:**
```yaml
groups:
  - name: migrations
    order: 1
    file_patterns: ["migrations/*.sql"]
    deploy_command: "psql $DATABASE_URL -f {file}"
    retry_attempts: 3      # Number of retry attempts (1 = no retries)
    retry_delay: 5         # Seconds to wait between retries
```

**Behavior:**
- If a command fails, it will automatically retry up to `retry_attempts` times
- Waits `retry_delay` seconds between attempts
- Shows clear retry messages: `⚠️  Hook failed (attempt 1/3), retrying in 5s...`
- Only fails after all retry attempts exhausted

**Use Cases:**
- **Database connection timeouts**: Temporary network issues
- **NPM registry failures**: Package download timeouts
- **Cloud API rate limits**: Temporary service unavailability
- **Lock conflicts**: Database migration lock contention

### 2. Configurable Timeouts

Each deployment group can have custom timeouts to prevent hanging operations.

**Configuration:**
```yaml
groups:
  - name: migrations
    timeout: 600           # Command timeout in seconds (10 minutes)
    hook_timeout: 30       # Hook timeout in seconds (default: 30)
```

**Default Timeouts:**
- **Hooks**: 30 seconds
- **Migrations**: 300 seconds (5 minutes) - can be overridden
- **Builds**: 600 seconds (10 minutes) - can be overridden
- **Tests**: 300 seconds (5 minutes)

**When to Customize:**
- Large migrations that take > 5 minutes: increase `timeout`
- Complex pre-deploy checks: increase `hook_timeout`
- Long-running builds: increase `timeout`

### 3. Deployment vs Hook Success Distinction

The system now distinguishes between core deployment success and hook failures.

**GroupResult Structure:**
```python
@dataclass
class GroupResult:
    success: bool                    # Overall success (deployment + hooks)
    deployment_success: bool         # Core deployment succeeded
    pre_hook_success: bool           # Pre-deploy hooks succeeded
    post_hook_success: bool          # Post-deploy hooks succeeded
    post_hook_errors: List[str]      # Specific post-hook errors

    @property
    def has_warnings(self) -> bool:
        """Deployment succeeded with warnings (post-hook failures)"""
        return self.deployment_success and not self.post_hook_success
```

**Behavior:**

#### Pre-Deploy Hook Failure
- **Fails the entire group** ❌
- Deployment does not proceed
- Group marked as failed
- Reason: Pre-hooks are prerequisites (e.g., environment validation)

#### Post-Deploy Hook Failure
- **Does NOT fail the deployment** ⚠️
- Core deployment already succeeded
- Group marked with warnings
- Shows: `⚠️  Deployed with warnings - Deployment succeeded but post-hooks failed`
- Reason: Post-hooks are auxiliary (e.g., cache invalidation, notifications)

**Example:**
```
🔧 [1] Deploying: frontend

   Running pre-deploy hooks...
      ✓ npm ci completed

   Building frontend...
      ✓ Build succeeded in 8234ms

   Running post-deploy hooks...
      ⚠️  Hook failed (attempt 1/3), retrying in 5s...
      ⚠️  Hook failed (attempt 2/3), retrying in 5s...
      ✗ Hook failed after 3 attempts: curl -X POST $SLACK_WEBHOOK
      ⚠️  Warning: Post-deploy hook failed but deployment continues

   ⚠️  Deployed with warnings in 8456ms
       Deployment succeeded but post-hooks failed
```

### 4. Continue on Failure

Groups can be configured to not block subsequent groups when they fail.

**Configuration:**
```yaml
groups:
  - name: notifications
    order: 10
    post_deploy:
      - "curl -X POST $SLACK_WEBHOOK"
    continue_on_failure: true   # Don't fail entire deployment if this fails
```

**When to Use:**

✅ **Use `continue_on_failure: true` for:**
- Notification systems (Slack, email, webhooks)
- Analytics tracking
- Cache warming (nice-to-have)
- Documentation generation
- Non-critical integrations

❌ **Never use `continue_on_failure: true` for:**
- Database migrations (data integrity)
- Core application builds (broken code)
- Security checks (vulnerabilities)
- Health checks (service availability)

**Behavior:**
- If group fails, deployment continues to next group
- Failed group is recorded in deployment history
- Final deployment status shows partial success
- Useful for "best-effort" operations

### 5. Deployment Status Visibility

Clear visual indicators show deployment state:

| Symbol | Meaning | Behavior |
|--------|---------|----------|
| ✅ | Full success | All operations succeeded |
| ⚠️ | Warnings | Deployment succeeded, post-hooks failed |
| ✗ | Failure | Core deployment or pre-hooks failed |
| ⏭️ | Skipped | Group skipped (no deployment logic) |

## Configuration Examples

### Example 1: Production Database Migrations

```yaml
groups:
  - name: migrations
    order: 1
    file_patterns: ["migrations/*.sql"]
    deploy_command: "psql $DATABASE_URL -f {file}"
    retry_attempts: 3        # Retry on connection failures
    retry_delay: 10          # Wait 10s between retries
    timeout: 900             # 15 minute timeout for large migrations
    hook_timeout: 60         # 1 minute for pre-checks
    pre_deploy:
      - "psql $DATABASE_URL -c 'SELECT 1'"  # Verify connectivity
    post_deploy:
      - "psql $DATABASE_URL -c 'ANALYZE'"   # Update statistics
    continue_on_failure: false  # NEVER continue if migrations fail
```

### Example 2: Frontend Build with Notifications

```yaml
groups:
  - name: frontend
    order: 2
    file_patterns: ["src/**/*.ts", "src/**/*.tsx"]
    build_command: "npm run build"
    test_command: "npm test"
    retry_attempts: 2        # Retry builds (npm transient failures)
    retry_delay: 5
    timeout: 600             # 10 minute build timeout
    pre_deploy:
      - "npm ci"             # Install dependencies
    post_deploy:
      - "npm run upload-sourcemaps"  # Nice-to-have, won't fail deploy
      - "curl -X POST $SLACK_WEBHOOK -d '{\"text\":\"Frontend deployed\"}'"
    continue_on_failure: false
```

### Example 3: Best-Effort Notifications

```yaml
groups:
  - name: notifications
    order: 99
    post_deploy:
      - "curl -X POST $SLACK_WEBHOOK"
      - "curl -X POST $DATADOG_API"
    retry_attempts: 3        # Retry notifications
    retry_delay: 5
    hook_timeout: 30
    continue_on_failure: true  # Don't fail deployment if notifications fail
```

## Error Handling Flow

### 1. Pre-Deploy Hook Failure

```
🔧 [1] Deploying: migrations
   Running pre-deploy hooks...
      ⚠️  Hook failed (attempt 1/3), retrying in 5s...
      Error: Connection refused
      ⚠️  Hook failed (attempt 2/3), retrying in 5s...
      Error: Connection refused
      ⚠️  Hook failed (attempt 3/3), retrying in 5s...
      Error: Connection refused
      ✗ Hook failed after 3 attempts: psql $DATABASE_URL -c 'SELECT 1'

✗ Deployment failed at group: migrations
   Error: Pre-deploy hook failed: psql $DATABASE_URL -c 'SELECT 1'
```

**Result**: Entire deployment fails, no further groups executed.

### 2. Core Deployment Failure

```
🔧 [1] Deploying: migrations
   Running pre-deploy hooks...
      ✓ Connection verified

   Found 3 pending migrations
      Applying: 001_add_users.sql
         ✗ Migration failed: syntax error at line 42
         Error: column "email" does not exist

✗ Deployment failed at group: migrations
   Error: Migration failed
```

**Result**: Deployment fails, rollback may be needed.

### 3. Post-Deploy Hook Failure (with retry)

```
🔧 [2] Deploying: frontend
   Running pre-deploy hooks...
      ✓ npm ci completed

   Building frontend...
      ✓ Build succeeded in 8234ms

   Running post-deploy hooks...
      ⚠️  Hook failed (attempt 1/3), retrying in 5s...
      Error: Slack API returned 429 (rate limit)
      ⚠️  Hook failed (attempt 2/3), retrying in 5s...
      Error: Slack API returned 429 (rate limit)
      ✓ Notification sent

   ✅ Completed in 8456ms
```

**Result**: Deployment succeeds after retry, notification eventually sent.

### 4. Post-Deploy Hook Failure (exhausted retries)

```
🔧 [2] Deploying: frontend
   Building frontend...
      ✓ Build succeeded in 8234ms

   Running post-deploy hooks...
      ⚠️  Hook failed (attempt 1/3), retrying in 5s...
      ⚠️  Hook failed (attempt 2/3), retrying in 5s...
      ✗ Hook failed after 3 attempts: curl -X POST $SLACK_WEBHOOK
      ⚠️  Warning: Post-deploy hook failed but deployment continues

   ⚠️  Deployed with warnings in 8456ms
       Deployment succeeded but post-hooks failed
```

**Result**: Deployment succeeds with warnings, monitoring alert may fire for post-hook failure.

## Best Practices

### 1. Setting Retry Attempts

**Conservative (default):**
```yaml
retry_attempts: 1  # No retries
```

**Standard (recommended for most):**
```yaml
retry_attempts: 3
retry_delay: 5
```

**Aggressive (for flaky operations):**
```yaml
retry_attempts: 5
retry_delay: 10
```

### 2. Timeout Guidelines

| Operation | Recommended Timeout | Rationale |
|-----------|---------------------|-----------|
| Pre-deploy checks | 30-60s | Quick validation |
| Small migrations | 300s (5min) | Standard timeout |
| Large migrations | 900-1800s (15-30min) | Data-heavy operations |
| NPM builds | 600s (10min) | Compilation time |
| Docker builds | 1200s (20min) | Image layers |
| Post-deploy hooks | 30s | Should be quick |

### 3. Hook Design

**Pre-Deploy Hooks:**
- Keep them fast (< 30s)
- Use for validation only
- Fail fast if requirements not met
- Examples:
  - Database connectivity check
  - Environment variable validation
  - Lock acquisition

**Post-Deploy Hooks:**
- Keep them optional
- Use for cleanup/notifications
- Should not fail deployments
- Examples:
  - Cache invalidation
  - Slack notifications
  - Log aggregation
  - Monitoring updates

### 4. continue_on_failure Guidelines

```yaml
# ❌ BAD: Don't use for critical operations
- name: migrations
  continue_on_failure: true  # NEVER DO THIS

# ✅ GOOD: Use for optional operations
- name: notifications
  continue_on_failure: true  # OK - just notifications
```

## Monitoring and Alerting

### Deployment States to Monitor

1. **Full Success**: All groups succeeded
   - Action: None required
   - Alert: None

2. **Success with Warnings**: Deployment succeeded, post-hooks failed
   - Action: Investigate post-hook failures
   - Alert: Low priority (info/warning level)

3. **Partial Success**: Some groups succeeded, others failed with `continue_on_failure`
   - Action: Investigate failed groups
   - Alert: Medium priority (warning level)

4. **Failure**: Core deployment failed
   - Action: Immediate rollback or fix
   - Alert: High priority (critical level)

### Recommended Alerts

```yaml
# Monitor deployment success rate
alert: DeploymentFailureRate
condition: failure_rate > 10% in last 24h
severity: high

# Monitor post-hook failures
alert: PostHookFailures
condition: post_hook_failures > 5 in last 1h
severity: medium

# Monitor retry exhaustion
alert: RetryExhaustion
condition: retry_exhausted > 3 in last 1h
severity: medium
```

## Troubleshooting

### Issue: Migrations timing out

**Symptoms:**
```
✗ Migration timed out after 5 minutes
```

**Solutions:**
1. Increase timeout:
   ```yaml
   timeout: 1800  # 30 minutes
   ```
2. Split large migrations into smaller chunks
3. Run data migrations separately from schema changes

### Issue: Flaky post-hooks failing deployments

**Symptoms:**
```
⚠️  Hook failed (attempt 3/3): curl $API
```

**Solutions:**
1. Increase retry attempts:
   ```yaml
   retry_attempts: 5
   retry_delay: 10
   ```
2. Move to separate notification group with `continue_on_failure: true`
3. Implement exponential backoff in the hook script itself

### Issue: Pre-hook validation too strict

**Symptoms:**
```
✗ Pre-deploy hook failed: test -f /app/config.json
```

**Solutions:**
1. Make validation less strict (check essentials only)
2. Move non-essential checks to post-deploy
3. Add retry logic for transient checks

## Summary

✅ **Retry logic** prevents transient failure cascades
✅ **Configurable timeouts** prevent operations from hanging
✅ **Deployment/hook distinction** provides clear error attribution
✅ **continue_on_failure** enables best-effort operations
✅ **Clear status indicators** improve operational visibility

These features make TempleDB deployments production-ready with enterprise-grade resilience and error handling.
