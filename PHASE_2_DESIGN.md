# Phase 2: Hierarchical Agent Dispatch - Design Document

**Date:** 2026-03-19
**Status:** Design Phase
**Inspiration:** [Superpowers](https://github.com/obra/superpowers) by @obra

## Executive Summary

Phase 2 implements **systematic workflow orchestration** for TempleDB by adapting Superpowers' subagent-driven development approach and combining it with our Phase 1 code intelligence capabilities. This creates an AI agent system that can autonomously execute complex, multi-step operations with built-in safety gates and quality checkpoints.

## Key Insights from Superpowers

### 1. Subagent-Driven Development
**Pattern:** Fresh subagent per task with isolated context
- Prevents context pollution
- Enables parallel execution
- Surfaces questions early
- Enforces quality gates

**Adaptation for TempleDB:**
- Use MCP tools to coordinate subagents
- Each workflow step = isolated subagent task
- Leverage code intelligence for informed decisions

### 2. Two-Stage Review
**Pattern:** Spec compliance → Code quality (sequential)
- Stage 1: Does it match requirements?
- Stage 2: Is it well-implemented?
- Never conflate the two

**Adaptation for TempleDB:**
- Stage 1: Validate against workflow definition
- Stage 2: Use code intelligence to assess impact
- Add Stage 3: Run automated validation (tests, type checks)

### 3. Bite-Sized Tasks
**Pattern:** 2-5 minute tasks with complete specifications
- Exact file paths
- Complete code samples
- Precise CLI commands
- Expected outputs

**Adaptation for TempleDB:**
- Each workflow step = single focused action
- Use code intelligence to generate precise task specs
- Include blast radius info for context

### 4. Mandatory Skills
**Pattern:** Skills activate automatically based on context
- Not suggestions, but requirements
- Enforced discipline (TDD, review, etc.)
- No "just this once" exceptions

**Adaptation for TempleDB:**
- Workflows are mandatory for critical operations
- Safety checks cannot be bypassed
- Impact analysis required before changes

### 5. TDD Discipline
**Pattern:** Red-Green-Refactor, no exceptions
- Write test first
- Watch it fail
- Implement minimal code
- Watch it pass
- Refactor safely

**Adaptation for TempleDB:**
- Database migrations: Write rollback first
- Deployments: Validate before deploy
- Secret rotation: Test connection before commit
- Refactoring: Run impact analysis first

## TempleDB Workflow Architecture

### Core Concept: Impact-Aware Workflows

Unlike Superpowers (code-centric), TempleDB workflows leverage **code intelligence** for safer operations:

```
Traditional Workflow:
  Plan → Execute → Validate → Deploy

TempleDB Workflow:
  Plan → Analyze Impact → Generate Tasks → Execute with Gates → Validate → Deploy
         ↑ Code Intelligence ↑
```

### Workflow Execution Flow

```
1. Workflow Trigger (user request or automated)
   ↓
2. Load Workflow Definition
   ↓
3. Execute Pre-Flight Checks
   - Code intelligence queries
   - Impact analysis
   - Dependency validation
   ↓
4. Generate Execution Plan
   - Break into bite-sized tasks
   - Order by dependencies
   - Add validation gates
   ↓
5. For Each Task:
   - Spawn subagent with isolated context
   - Execute task
   - Validate output
   - Checkpoint state
   ↓
6. Post-Flight Validation
   - Run full test suite
   - Verify no regressions
   - Generate deployment report
   ↓
7. Human Sign-Off (critical workflows)
   ↓
8. Finalize & Deploy
```

## Planned Workflows

### Workflow 1: Safe Deployment
**Goal:** Deploy code with systematic safety checks

**Phases:**
1. **Pre-Deploy Analysis**
   - Run code_impact_analysis on changed symbols
   - Check blast radius
   - Identify affected tests
   - Generate testing scope

2. **Test Validation**
   - Run affected tests first (fast feedback)
   - If pass, run full test suite
   - No deployment without green tests

3. **Dependency Ordering**
   - Use dependency graph to order deployments
   - Deploy dependencies before dependents
   - Rollback cascade if failure

4. **Deployment Execution**
   - Deploy to staging first
   - Run smoke tests
   - Deploy to production
   - Monitor for errors

5. **Post-Deploy Verification**
   - Health checks
   - Error rate monitoring
   - Rollback if issues detected

**Validation Gates:**
- ✅ Impact analysis completed
- ✅ Tests pass
- ✅ Staging validation passes
- ✅ Production health checks pass

### Workflow 2: Database Migration (TDD Style)
**Goal:** Safe schema changes with rollback guarantee

**Phases:**
1. **Rollback First (Like TDD Red)**
   - Write DOWN migration
   - Test rollback works
   - Verify no data loss

2. **Forward Migration (Like TDD Green)**
   - Write UP migration
   - Apply to test database
   - Verify data integrity
   - Check performance

3. **Test Coverage**
   - Generate tests for new schema
   - Verify old code still works (compatibility)
   - Test edge cases

4. **Production Execution**
   - Backup database
   - Apply migration
   - Verify data integrity
   - Monitor performance

5. **Rollback if Needed**
   - Use tested DOWN migration
   - Restore from backup if catastrophic

**Validation Gates:**
- ✅ Rollback tested successfully
- ✅ Forward migration tested
- ✅ Data integrity verified
- ✅ Performance acceptable
- ✅ Backup created

### Workflow 3: Secret Rotation
**Goal:** Rotate secrets with zero downtime

**Phases:**
1. **Impact Analysis**
   - code_search for secret usage
   - Identify all consumers
   - Calculate blast radius

2. **Dual-Write Phase**
   - Generate new secret
   - Configure both old and new
   - Test connections with new secret

3. **Gradual Cutover**
   - Update consumers one by one
   - Validate each update
   - Rollback individual failures

4. **Deprecation Phase**
   - Monitor old secret usage
   - When zero, remove old secret
   - Verify no breakage

5. **Cleanup**
   - Remove old secret references
   - Update documentation

**Validation Gates:**
- ✅ All consumers identified
- ✅ New secret validated
- ✅ Each consumer updated successfully
- ✅ Old secret usage = 0
- ✅ No errors detected

### Workflow 4: Impact-Aware Refactoring
**Goal:** Refactor with full awareness of consequences

**Phases:**
1. **Discovery**
   - code_search for target symbols
   - Run impact_analysis
   - Calculate blast radius
   - Review cluster membership

2. **Planning**
   - Generate task list based on dependencies
   - Order tasks by dependency graph
   - Identify testing requirements

3. **Implementation (TDD)**
   - For each affected symbol:
     - Write test capturing current behavior
     - Refactor
     - Verify test still passes
     - Run impact analysis again (verify no surprises)

4. **Integration Testing**
   - Run tests for all affected files
   - Check cross-file dependencies
   - Verify cluster integrity (no broken boundaries)

5. **Code Review**
   - Use show_clusters to verify architectural integrity
   - Check that related code moved together
   - Validate naming consistency

**Validation Gates:**
- ✅ Blast radius assessed
- ✅ Tests written for all changes
- ✅ All tests pass
- ✅ Architectural integrity maintained
- ✅ Code review approved

## TempleDB-Specific Innovations

### 1. Code Intelligence Integration

Every workflow step can query code intelligence:

```python
# Before refactoring
blast_radius = code_impact_analysis("authenticate_user")
if blast_radius.total_affected_symbols > 100:
    suggest_smaller_refactoring()

# During deployment
affected_tests = identify_tests_for_blast_radius(changed_symbols)
run_tests(affected_tests)  # Fast feedback loop
```

### 2. Dependency-Ordered Execution

Use dependency graph for smart ordering:

```python
# Deploy dependencies before dependents
deploy_order = topological_sort(dependency_graph)
for component in deploy_order:
    deploy(component)
    validate(component)
```

### 3. Cluster-Aware Changes

Use clusters to understand architectural impact:

```python
# Check if refactoring crosses cluster boundaries
symbol_cluster = get_cluster("authenticate_user")
related_symbols = get_cluster_members(symbol_cluster)

if changes_span_multiple_clusters(changes):
    warn_architectural_boundary_crossing()
```

### 4. Blast Radius-Driven Testing

Calculate precise testing scope:

```python
# Only run tests for affected code
blast_radius = analyze_impact(changed_symbols)
test_files = get_test_files(blast_radius.affected_files)
run_tests(test_files)  # Much faster than full suite
```

## Implementation Plan

### Phase 2.1: Workflow Engine (2-3 hours)
**Goal:** Core orchestration infrastructure

**Deliverables:**
- `src/services/workflow_orchestrator.py`
- Workflow definition format (YAML/JSON)
- Task execution with checkpoints
- Validation gate system
- TodoWrite integration

**Files:**
```
src/services/workflow_orchestrator.py    (300 lines)
src/workflows/safe_deployment.yaml       (100 lines)
tests/test_workflow_orchestrator.py      (150 lines)
```

### Phase 2.2: MCP Workflow Tools (1-2 hours)
**Goal:** Expose workflows via MCP

**Deliverables:**
- `templedb_workflow_execute`
- `templedb_workflow_status`
- `templedb_workflow_list`
- `templedb_workflow_validate`

**Files:**
```
src/mcp_server.py                        (+200 lines)
```

### Phase 2.3: Safe Deployment Workflow (3-4 hours)
**Goal:** First production workflow

**Deliverables:**
- Safe deployment workflow definition
- Impact-based test selection
- Staging validation
- Production deployment with gates

**Files:**
```
src/workflows/safe_deployment.yaml       (200 lines)
src/services/deployment_workflow.py      (400 lines)
tests/test_safe_deployment.py            (200 lines)
```

### Phase 2.4: Database Migration Workflow (2-3 hours)
**Goal:** TDD-style migrations

**Deliverables:**
- Migration workflow definition
- Rollback-first enforcement
- Data integrity validation
- Backup/restore integration

**Files:**
```
src/workflows/database_migration.yaml    (150 lines)
src/services/migration_workflow.py       (350 lines)
tests/test_migration_workflow.py         (200 lines)
```

### Phase 2.5: Testing & Documentation (2-3 hours)
**Goal:** Validate and document

**Deliverables:**
- End-to-end workflow tests
- Documentation
- Example workflows
- Troubleshooting guide

**Total Estimate:** 10-15 hours

## Workflow Definition Format

### YAML Schema

```yaml
workflow:
  name: "safe-deployment"
  version: "1.0"
  description: "Deploy code with systematic safety checks"

  # Pre-flight checks (run before workflow starts)
  preflight:
    - type: "code_intelligence"
      action: "extract_symbols"
      args:
        project: "${project}"

    - type: "code_intelligence"
      action: "build_graph"
      args:
        project: "${project}"

  # Main workflow phases
  phases:
    - name: "impact_analysis"
      description: "Analyze blast radius of changes"
      tasks:
        - name: "identify_changed_symbols"
          type: "code_search"
          args:
            query: "${changed_files}"

        - name: "analyze_impact"
          type: "code_impact_analysis"
          for_each: "${changed_symbols}"

        - name: "calculate_test_scope"
          type: "custom"
          script: "calculate_test_scope.py"

      validation:
        - type: "assertion"
          condition: "blast_radius < threshold"
          error: "Blast radius too large! Break into smaller changes."

    - name: "test_validation"
      description: "Run tests for affected code"
      tasks:
        - name: "run_affected_tests"
          type: "bash"
          command: "pytest ${affected_test_files}"

        - name: "run_full_suite"
          type: "bash"
          command: "pytest"
          depends_on: "run_affected_tests"

      validation:
        - type: "test_results"
          condition: "all_pass"
          error: "Tests failed! Fix before deploying."

    - name: "deployment"
      description: "Deploy to production"
      requires_human_approval: true

      tasks:
        - name: "deploy_staging"
          type: "deploy"
          target: "staging"

        - name: "smoke_tests"
          type: "bash"
          command: "run_smoke_tests.sh staging"
          depends_on: "deploy_staging"

        - name: "deploy_production"
          type: "deploy"
          target: "production"
          depends_on: "smoke_tests"

      validation:
        - type: "health_check"
          target: "production"
          timeout: 300
          error: "Health check failed! Rolling back..."

      rollback:
        - name: "rollback_production"
          type: "deploy"
          target: "production"
          version: "${previous_version}"

  # Post-flight checks (run after workflow completes)
  postflight:
    - type: "notification"
      action: "send_success_notification"

    - type: "metrics"
      action: "record_deployment_metrics"
```

## Success Criteria

### Technical Success
- ✅ Workflow engine executes multi-phase workflows
- ✅ Validation gates prevent unsafe operations
- ✅ Code intelligence informs workflow decisions
- ✅ Rollback mechanisms work reliably
- ✅ MCP tools expose workflows to AI agents

### Safety Success
- ✅ No production incidents from workflow-managed deployments
- ✅ All changes have verified rollback procedures
- ✅ Impact analysis prevents surprises
- ✅ Testing coverage calculated accurately

### Usability Success
- ✅ AI agents can execute workflows autonomously
- ✅ Human approval points are clear
- ✅ Workflow status is transparent
- ✅ Errors are actionable

## Comparison: Superpowers vs TempleDB Phase 2

| Aspect | Superpowers | TempleDB Phase 2 |
|--------|-------------|------------------|
| **Focus** | Code development | Operations + Code |
| **Coordination** | Git worktrees | MCP tools + TodoWrite |
| **Context** | File-based skills | Code intelligence queries |
| **Validation** | 2-stage review | 3-stage (spec + impact + automated) |
| **Safety** | TDD enforcement | Impact analysis + TDD |
| **Workflow Type** | Development tasks | Deployment + Migration + Ops |
| **Decision Making** | Human + AI | AI-driven with code intelligence |
| **Isolation** | Git branches | Workflow phases + checkpoints |
| **Task Size** | 2-5 minutes | Variable (optimized per phase) |
| **Rollback** | Git revert | Workflow-defined procedures |

## Next Steps

1. **Implement Workflow Engine** (Phase 2.1)
   - Core orchestration
   - Task execution
   - Validation gates
   - Checkpoint system

2. **Add MCP Tools** (Phase 2.2)
   - Workflow execution
   - Status queries
   - Validation

3. **Build Safe Deployment Workflow** (Phase 2.3)
   - Impact-driven testing
   - Staging validation
   - Production deployment

4. **Test End-to-End** (Phase 2.4)
   - Real-world workflows
   - Edge cases
   - Rollback scenarios

Let's start with Phase 2.1!
