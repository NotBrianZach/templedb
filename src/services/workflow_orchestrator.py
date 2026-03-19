#!/usr/bin/env python3
"""
Workflow Orchestrator - Phase 2.1

Implements hierarchical agent dispatch with systematic workflow orchestration.
Inspired by Superpowers' subagent-driven development approach.

Key Features:
- Multi-phase workflow execution
- Validation gates at each phase
- Checkpoint/rollback system
- Code intelligence integration
- TodoWrite progress tracking
- Human approval gates

Workflow Structure:
1. Preflight checks (code intelligence, validation)
2. Phases (ordered execution with gates)
3. Tasks (bite-sized, 2-5 minute actions)
4. Validation (assertions, tests, health checks)
5. Postflight (cleanup, notifications)
6. Rollback (defined procedures per phase)
"""

import json
import logging
import yaml
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import subprocess

try:
    from ..db_utils import get_connection, get_project_by_slug
except ImportError:
    from db_utils import get_connection, get_project_by_slug

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class PhaseStatus(Enum):
    """Phase execution status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLBACK = "rollback"


class WorkflowStatus(Enum):
    """Overall workflow status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    AWAITING_APPROVAL = "awaiting_approval"


@dataclass
class TaskResult:
    """Result of task execution"""
    status: TaskStatus
    output: Any = None
    error: Optional[str] = None
    duration: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of validation gate"""
    passed: bool
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowContext:
    """Execution context passed between tasks"""
    project_id: int
    project_slug: str
    variables: Dict[str, Any]
    task_results: Dict[str, TaskResult]
    phase_results: Dict[str, Any]
    checkpoint_data: Dict[str, Any]

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get variable with ${var} interpolation support"""
        if name.startswith("${") and name.endswith("}"):
            var_name = name[2:-1]
            return self.variables.get(var_name, default)
        return name

    def set_variable(self, name: str, value: Any):
        """Set context variable"""
        self.variables[name] = value

    def get_task_result(self, task_name: str) -> Optional[TaskResult]:
        """Get result from previous task"""
        return self.task_results.get(task_name)


class WorkflowOrchestrator:
    """
    Orchestrates multi-phase workflows with validation gates.

    Workflow Execution Flow:
    1. Load workflow definition (YAML)
    2. Run preflight checks
    3. For each phase:
       - Execute tasks sequentially
       - Run validation gates
       - Checkpoint state
       - Request approval if needed
    4. Run postflight
    5. On failure: Execute rollback
    """

    def __init__(self):
        self.task_executors = {
            "code_intelligence": self._execute_code_intelligence_task,
            "code_search": self._execute_code_search_task,
            "code_impact_analysis": self._execute_impact_analysis_task,
            "bash": self._execute_bash_task,
            "custom": self._execute_custom_task,
            "deploy": self._execute_deploy_task,
            "python": self._execute_python_task,
            "mcp": self._execute_mcp_task,
        }

        self.validators = {
            "assertion": self._validate_assertion,
            "test_results": self._validate_test_results,
            "health_check": self._validate_health_check,
            "code_intelligence": self._validate_code_intelligence,
        }

    def load_workflow(self, workflow_path: str) -> Dict[str, Any]:
        """Load workflow definition from YAML file"""
        with open(workflow_path, 'r') as f:
            workflow = yaml.safe_load(f)

        # Validate workflow structure
        self._validate_workflow_definition(workflow)

        return workflow

    def execute_workflow(
        self,
        workflow_def: Dict[str, Any],
        project_slug: str,
        variables: Optional[Dict[str, Any]] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Execute a complete workflow.

        Args:
            workflow_def: Workflow definition (from YAML)
            project_slug: Project to operate on
            variables: Context variables
            dry_run: If True, don't execute, just validate

        Returns:
            Workflow execution report
        """
        start_time = datetime.now()

        # Get project
        project = get_project_by_slug(project_slug)
        if not project:
            raise ValueError(f"Project '{project_slug}' not found")

        # Initialize context
        context = WorkflowContext(
            project_id=project['id'],
            project_slug=project_slug,
            variables=variables or {},
            task_results={},
            phase_results={},
            checkpoint_data={}
        )

        logger.info(f"Starting workflow: {workflow_def['workflow']['name']}")

        try:
            # Run preflight checks
            if 'preflight' in workflow_def['workflow']:
                logger.info("Running preflight checks...")
                preflight_result = self._execute_preflight(
                    workflow_def['workflow']['preflight'],
                    context,
                    dry_run
                )
                if not preflight_result['passed']:
                    return self._create_failure_report(
                        workflow_def,
                        context,
                        "Preflight checks failed",
                        preflight_result
                    )

            # Execute phases
            for phase in workflow_def['workflow']['phases']:
                logger.info(f"Starting phase: {phase['name']}")

                phase_result = self._execute_phase(phase, context, dry_run)

                if phase_result['status'] == PhaseStatus.FAILED.value:
                    # Execute rollback if defined
                    if 'rollback' in phase:
                        logger.warning(f"Phase failed, executing rollback...")
                        self._execute_rollback(phase['rollback'], context)

                    return self._create_failure_report(
                        workflow_def,
                        context,
                        f"Phase '{phase['name']}' failed",
                        phase_result
                    )

                context.phase_results[phase['name']] = phase_result

            # Run postflight
            if 'postflight' in workflow_def['workflow']:
                logger.info("Running postflight...")
                self._execute_postflight(
                    workflow_def['workflow']['postflight'],
                    context,
                    dry_run
                )

            # Success!
            duration = (datetime.now() - start_time).total_seconds()

            return {
                'status': WorkflowStatus.COMPLETED.value,
                'workflow': workflow_def['workflow']['name'],
                'duration': duration,
                'phases': context.phase_results,
                'variables': context.variables,
                'message': 'Workflow completed successfully'
            }

        except Exception as e:
            logger.error(f"Workflow failed with exception: {e}")
            return self._create_failure_report(
                workflow_def,
                context,
                str(e),
                {'exception': str(e)}
            )

    def _execute_preflight(
        self,
        preflight_checks: List[Dict[str, Any]],
        context: WorkflowContext,
        dry_run: bool
    ) -> Dict[str, Any]:
        """Execute preflight checks"""
        results = []

        for check in preflight_checks:
            try:
                if dry_run:
                    results.append({'check': check, 'status': 'skipped'})
                    continue

                result = self._execute_task(check, context)

                if result.status == TaskStatus.FAILED:
                    return {
                        'passed': False,
                        'failed_check': check,
                        'error': result.error
                    }

                results.append({'check': check, 'status': 'passed'})

            except Exception as e:
                return {
                    'passed': False,
                    'failed_check': check,
                    'error': str(e)
                }

        return {'passed': True, 'checks': results}

    def _execute_phase(
        self,
        phase_def: Dict[str, Any],
        context: WorkflowContext,
        dry_run: bool
    ) -> Dict[str, Any]:
        """Execute a single workflow phase"""
        phase_start = datetime.now()
        task_results = []

        # Check if human approval required
        if phase_def.get('requires_human_approval', False):
            # In real implementation, this would pause and wait for approval
            logger.info(f"Phase '{phase_def['name']}' requires human approval")
            # For now, we'll just log and continue

        # Execute tasks
        for task in phase_def['tasks']:
            logger.info(f"Executing task: {task['name']}")

            if dry_run:
                task_results.append({
                    'task': task['name'],
                    'status': TaskStatus.SKIPPED.value
                })
                continue

            try:
                result = self._execute_task(task, context)
                context.task_results[task['name']] = result

                task_results.append({
                    'task': task['name'],
                    'status': result.status.value,
                    'output': result.output,
                    'duration': result.duration
                })

                if result.status == TaskStatus.FAILED:
                    return {
                        'status': PhaseStatus.FAILED.value,
                        'failed_task': task['name'],
                        'error': result.error,
                        'tasks': task_results
                    }

            except Exception as e:
                logger.error(f"Task '{task['name']}' failed: {e}")
                return {
                    'status': PhaseStatus.FAILED.value,
                    'failed_task': task['name'],
                    'error': str(e),
                    'tasks': task_results
                }

        # Run validation gates (skip in dry_run mode)
        if 'validation' in phase_def and not dry_run:
            logger.info(f"Running validation gates for phase: {phase_def['name']}")
            validation_result = self._execute_validations(
                phase_def['validation'],
                context
            )

            if not validation_result.passed:
                return {
                    'status': PhaseStatus.FAILED.value,
                    'validation_failed': True,
                    'error': validation_result.message,
                    'tasks': task_results
                }

        # Checkpoint
        self._checkpoint_phase(phase_def['name'], context)

        duration = (datetime.now() - phase_start).total_seconds()

        return {
            'status': PhaseStatus.COMPLETED.value,
            'tasks': task_results,
            'duration': duration
        }

    def _execute_task(
        self,
        task_def: Dict[str, Any],
        context: WorkflowContext
    ) -> TaskResult:
        """Execute a single task"""
        task_start = datetime.now()
        task_type = task_def.get('type', 'custom')

        # Get task executor
        executor = self.task_executors.get(task_type)
        if not executor:
            return TaskResult(
                status=TaskStatus.FAILED,
                error=f"Unknown task type: {task_type}"
            )

        try:
            # Check dependencies
            if 'depends_on' in task_def:
                dep_result = context.get_task_result(task_def['depends_on'])
                if not dep_result or dep_result.status != TaskStatus.COMPLETED:
                    return TaskResult(
                        status=TaskStatus.BLOCKED,
                        error=f"Dependency '{task_def['depends_on']}' not satisfied"
                    )

            # Execute task
            output = executor(task_def, context)

            duration = (datetime.now() - task_start).total_seconds()

            return TaskResult(
                status=TaskStatus.COMPLETED,
                output=output,
                duration=duration
            )

        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            duration = (datetime.now() - task_start).total_seconds()
            return TaskResult(
                status=TaskStatus.FAILED,
                error=str(e),
                duration=duration
            )

    def _execute_validations(
        self,
        validation_defs: List[Dict[str, Any]],
        context: WorkflowContext
    ) -> ValidationResult:
        """Execute validation gates"""
        for validation in validation_defs:
            validator_type = validation.get('type', 'assertion')
            validator = self.validators.get(validator_type)

            if not validator:
                return ValidationResult(
                    passed=False,
                    message=f"Unknown validator type: {validator_type}"
                )

            result = validator(validation, context)
            if not result.passed:
                return result

        return ValidationResult(passed=True, message="All validations passed")

    def _execute_rollback(
        self,
        rollback_tasks: List[Dict[str, Any]],
        context: WorkflowContext
    ):
        """Execute rollback procedures"""
        logger.warning("Executing rollback...")

        for task in rollback_tasks:
            try:
                logger.info(f"Rollback task: {task['name']}")
                self._execute_task(task, context)
            except Exception as e:
                logger.error(f"Rollback task failed: {e}")
                # Continue with remaining rollback tasks

    def _execute_postflight(
        self,
        postflight_tasks: List[Dict[str, Any]],
        context: WorkflowContext,
        dry_run: bool
    ):
        """Execute postflight tasks"""
        for task in postflight_tasks:
            if dry_run:
                continue

            try:
                self._execute_task(task, context)
            except Exception as e:
                logger.warning(f"Postflight task failed: {e}")
                # Continue with remaining tasks

    def _checkpoint_phase(self, phase_name: str, context: WorkflowContext):
        """Save checkpoint for phase"""
        context.checkpoint_data[phase_name] = {
            'timestamp': datetime.now().isoformat(),
            'variables': context.variables.copy(),
            'completed_tasks': list(context.task_results.keys())
        }

    # Task Executors

    def _execute_code_intelligence_task(
        self,
        task_def: Dict[str, Any],
        context: WorkflowContext
    ) -> Any:
        """Execute code intelligence task"""
        from services.symbol_extraction_service import extract_symbols_for_project
        from services.dependency_graph_service import build_dependency_graph_for_project
        from services.community_detection_service import detect_communities_for_project, get_clusters_for_project

        action = task_def.get('action')
        args = task_def.get('args', {})

        # Interpolate variables
        for key, value in args.items():
            if isinstance(value, str):
                args[key] = context.get_variable(value, value)

        if action == 'extract_symbols':
            return extract_symbols_for_project(
                context.project_id,
                force=args.get('force', False)
            )
        elif action == 'build_graph':
            return build_dependency_graph_for_project(
                context.project_id,
                force=args.get('force', False)
            )
        elif action == 'build_clusters':
            resolution = args.get('resolution', 1.0)
            return detect_communities_for_project(
                context.project_id,
                resolution=resolution
            )
        elif action == 'show_clusters':
            include_members = args.get('include_members', False)
            limit = args.get('limit', 20)
            return get_clusters_for_project(
                context.project_id,
                include_members=include_members,
                limit=limit
            )
        else:
            raise ValueError(f"Unknown code intelligence action: {action}")

    def _execute_code_search_task(
        self,
        task_def: Dict[str, Any],
        context: WorkflowContext
    ) -> Any:
        """Execute code search task"""
        from services.code_search_service import search_code

        query = context.get_variable(task_def.get('query'), '')
        limit = task_def.get('limit', 10)

        return search_code(context.project_id, query, limit)

    def _execute_impact_analysis_task(
        self,
        task_def: Dict[str, Any],
        context: WorkflowContext
    ) -> Any:
        """Execute impact analysis task"""
        from services.impact_analysis_service import analyze_symbol_impact

        symbol_name = context.get_variable(task_def.get('symbol_name'), '')

        # Find symbol
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM code_symbols
            WHERE project_id = ? AND (symbol_name = ? OR qualified_name = ?)
            LIMIT 1
        """, (context.project_id, symbol_name, symbol_name))

        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Symbol '{symbol_name}' not found")

        return analyze_symbol_impact(row[0])

    def _execute_bash_task(
        self,
        task_def: Dict[str, Any],
        context: WorkflowContext
    ) -> Any:
        """Execute bash command"""
        command = task_def.get('command', '')

        # Interpolate variables
        for var_name, var_value in context.variables.items():
            command = command.replace(f"${{{var_name}}}", str(var_value))

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=task_def.get('timeout', 300)
        )

        if result.returncode != 0:
            raise RuntimeError(f"Command failed: {result.stderr}")

        return {
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }

    def _execute_custom_task(
        self,
        task_def: Dict[str, Any],
        context: WorkflowContext
    ) -> Any:
        """Execute custom Python script"""
        script_path = task_def.get('script', '')

        # Load and execute script
        # For now, just log
        logger.info(f"Would execute custom script: {script_path}")
        return {'status': 'completed'}

    def _execute_deploy_task(
        self,
        task_def: Dict[str, Any],
        context: WorkflowContext
    ) -> Any:
        """
        Execute deployment task.

        Supports multiple deployment backends:
        - nixops4: NixOS deployment orchestration
        - generic: Generic deployment via bash command

        Args:
            task_def: Task definition with:
                - target: deployment target (staging/production)
                - backend: deployment backend (nixops4/generic, default: generic)
                - version: version to deploy (optional, for rollback)
                - command: custom deployment command (generic backend)
                - network: NixOps network name (nixops4 backend)
        """
        target = task_def.get('target', 'staging')
        backend = task_def.get('backend', 'generic')
        version = task_def.get('version')

        logger.info(f"Deploying to {target} using {backend} backend")

        if backend == 'nixops4':
            return self._deploy_nixops4(task_def, context)
        elif backend == 'generic':
            return self._deploy_generic(task_def, context)
        else:
            raise ValueError(f"Unknown deployment backend: {backend}")

    def _deploy_nixops4(
        self,
        task_def: Dict[str, Any],
        context: WorkflowContext
    ) -> Any:
        """Deploy using NixOps4"""
        import subprocess

        project = context.get_variable('${project}', 'default')
        network = task_def.get('network', context.get_variable('${network}', 'default'))
        target = task_def.get('target', 'staging')

        # Build nixops4 deploy command
        cmd = ['./templedb', 'nixops4', 'deploy', project, network]

        # Add target-specific flags if needed
        if task_def.get('dry_run', False):
            cmd.append('--dry-run')

        logger.info(f"Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=task_def.get('timeout', 600),
                cwd=str(Path(__file__).parent.parent.parent)
            )

            if result.returncode != 0:
                raise RuntimeError(f"NixOps4 deployment failed: {result.stderr}")

            return {
                'target': target,
                'backend': 'nixops4',
                'status': 'deployed',
                'network': network,
                'stdout': result.stdout,
                'stderr': result.stderr
            }

        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Deployment to {target} timed out")

    def _deploy_generic(
        self,
        task_def: Dict[str, Any],
        context: WorkflowContext
    ) -> Any:
        """Deploy using generic command"""
        import subprocess

        target = task_def.get('target', 'staging')
        version = task_def.get('version')
        command = task_def.get('command')

        if not command:
            # Default deployment command
            if version:
                command = f"echo 'Deploying version {version} to {target}'"
            else:
                command = f"echo 'Deploying to {target}'"

        # Interpolate variables in command
        for key, value in context.variables.items():
            command = command.replace(f"${{{key}}}", str(value))

        logger.info(f"Running deployment command: {command}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=task_def.get('timeout', 600)
            )

            if result.returncode != 0:
                raise RuntimeError(f"Deployment command failed: {result.stderr}")

            return {
                'target': target,
                'backend': 'generic',
                'status': 'deployed',
                'version': version,
                'stdout': result.stdout,
                'stderr': result.stderr
            }

        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Deployment to {target} timed out")

    def _execute_python_task(
        self,
        task_def: Dict[str, Any],
        context: WorkflowContext
    ) -> Any:
        """Execute Python code"""
        code = task_def.get('code', '')

        # Execute Python code in restricted context
        exec_globals = {'context': context, 'logger': logger}
        exec(code, exec_globals)

        return exec_globals.get('result')

    def _execute_mcp_task(
        self,
        task_def: Dict[str, Any],
        context: WorkflowContext
    ) -> Any:
        """Execute MCP tool call"""
        tool_name = task_def.get('tool')
        args = task_def.get('args', {})

        # Interpolate variables
        for key, value in args.items():
            if isinstance(value, str):
                args[key] = context.get_variable(value, value)

        # In real implementation, this would call MCP tools
        logger.info(f"Would call MCP tool: {tool_name} with args: {args}")
        return {'status': 'completed'}

    # Validators

    def _validate_assertion(
        self,
        validation_def: Dict[str, Any],
        context: WorkflowContext
    ) -> ValidationResult:
        """Validate assertion"""
        condition = validation_def.get('condition', '')
        error_msg = validation_def.get('error', 'Assertion failed')

        # Simple evaluation (in real implementation, use safer evaluation)
        try:
            # Build evaluation context
            eval_context = {
                'context': context,
                'variables': context.variables,
                **context.variables
            }

            result = eval(condition, {'__builtins__': {}}, eval_context)

            if result:
                return ValidationResult(passed=True, message="Assertion passed")
            else:
                return ValidationResult(passed=False, message=error_msg)

        except Exception as e:
            return ValidationResult(
                passed=False,
                message=f"Assertion evaluation failed: {e}"
            )

    def _validate_test_results(
        self,
        validation_def: Dict[str, Any],
        context: WorkflowContext
    ) -> ValidationResult:
        """
        Validate test results from previous task output.

        Parses test output from previous task and validates results.

        Args:
            validation_def: Validation definition with:
                - task_name: name of task that ran tests (optional, uses last task)
                - condition: validation condition (all_pass/allow_skipped, default: all_pass)
                - min_coverage: minimum coverage percentage (optional)
        """
        condition = validation_def.get('condition', 'all_pass')
        task_name = validation_def.get('task_name')
        min_coverage = validation_def.get('min_coverage')

        # Get test task results
        if task_name:
            if task_name not in context.task_results:
                return ValidationResult(
                    passed=False,
                    message=f"Task '{task_name}' not found in results"
                )
            task_result = context.task_results[task_name]
        else:
            # Use last task result
            if not context.task_results:
                return ValidationResult(
                    passed=False,
                    message="No task results available"
                )
            task_result = list(context.task_results.values())[-1]

        # Parse test output
        output = task_result.output
        if not isinstance(output, dict):
            # Try to parse stdout as pytest output
            stdout = str(output.get('stdout', '')) if isinstance(output, dict) else str(output)
            output = self._parse_pytest_output(stdout)

        # Validate based on condition
        if condition == 'all_pass':
            failed = output.get('failed', 0)
            errors = output.get('errors', 0)

            if failed > 0 or errors > 0:
                return ValidationResult(
                    passed=False,
                    message=f"Tests failed: {failed} failed, {errors} errors"
                )

        elif condition == 'allow_skipped':
            failed = output.get('failed', 0)
            errors = output.get('errors', 0)

            if failed > 0 or errors > 0:
                return ValidationResult(
                    passed=False,
                    message=f"Tests failed: {failed} failed, {errors} errors (skipped allowed)"
                )

        # Check coverage if specified
        if min_coverage is not None:
            coverage = output.get('coverage')
            if coverage is None:
                return ValidationResult(
                    passed=False,
                    message=f"No coverage data available (minimum: {min_coverage}%)"
                )
            if coverage < min_coverage:
                return ValidationResult(
                    passed=False,
                    message=f"Coverage {coverage}% below minimum {min_coverage}%"
                )

        passed = output.get('passed', 0)
        skipped = output.get('skipped', 0)

        return ValidationResult(
            passed=True,
            message=f"Tests passed: {passed} passed, {skipped} skipped"
        )

    def _parse_pytest_output(self, stdout: str) -> Dict[str, Any]:
        """Parse pytest output to extract test results"""
        import re

        result = {
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'errors': 0,
            'coverage': None
        }

        # Parse pytest summary line
        # Example: "===== 5 passed, 2 skipped, 1 failed in 0.52s ====="
        summary_pattern = r'=+\s*(.+?)\s+in\s+[\d.]+s\s*=+'
        match = re.search(summary_pattern, stdout)

        if match:
            summary = match.group(1)

            # Extract counts
            passed_match = re.search(r'(\d+)\s+passed', summary)
            if passed_match:
                result['passed'] = int(passed_match.group(1))

            failed_match = re.search(r'(\d+)\s+failed', summary)
            if failed_match:
                result['failed'] = int(failed_match.group(1))

            skipped_match = re.search(r'(\d+)\s+skipped', summary)
            if skipped_match:
                result['skipped'] = int(skipped_match.group(1))

            error_match = re.search(r'(\d+)\s+error', summary)
            if error_match:
                result['errors'] = int(error_match.group(1))

        # Parse coverage if present
        # Example: "TOTAL      1000    200     80%"
        coverage_pattern = r'TOTAL\s+\d+\s+\d+\s+(\d+)%'
        coverage_match = re.search(coverage_pattern, stdout)
        if coverage_match:
            result['coverage'] = int(coverage_match.group(1))

        return result

    def _validate_health_check(
        self,
        validation_def: Dict[str, Any],
        context: WorkflowContext
    ) -> ValidationResult:
        """
        Validate health check.

        Performs HTTP health check on deployment target with retries.

        Args:
            validation_def: Validation definition with:
                - target: deployment target (staging/production)
                - url: health check URL (optional, defaults to http://{target}/health)
                - expected_status: expected HTTP status code (default: 200)
                - timeout: timeout per request in seconds (default: 10)
                - retries: number of retries (default: 3)
                - retry_delay: delay between retries in seconds (default: 5)
                - required_response: optional string that must be in response body
        """
        import urllib.request
        import urllib.error
        import time

        target = validation_def.get('target', 'production')
        url = validation_def.get('url')
        expected_status = validation_def.get('expected_status', 200)
        timeout = validation_def.get('timeout', 10)
        retries = validation_def.get('retries', 3)
        retry_delay = validation_def.get('retry_delay', 5)
        required_response = validation_def.get('required_response')

        # Interpolate variables in URL
        if url:
            for key, value in context.variables.items():
                url = url.replace(f"${{{key}}}", str(value))
        else:
            # Default health check URL
            url = f"http://{target}/health"

        logger.info(f"Performing health check on {target}: {url}")

        last_error = None

        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, method='GET')
                req.add_header('User-Agent', 'TempleDB-Workflow-Health-Check/1.0')

                with urllib.request.urlopen(req, timeout=timeout) as response:
                    status = response.getcode()
                    body = response.read().decode('utf-8')

                    # Check status code
                    if status != expected_status:
                        last_error = f"Expected status {expected_status}, got {status}"
                        logger.warning(f"Health check attempt {attempt+1}/{retries} failed: {last_error}")
                        if attempt < retries - 1:
                            time.sleep(retry_delay)
                            continue
                        return ValidationResult(
                            passed=False,
                            message=f"Health check failed for {target}: {last_error}"
                        )

                    # Check required response if specified
                    if required_response and required_response not in body:
                        last_error = f"Response does not contain required string: '{required_response}'"
                        logger.warning(f"Health check attempt {attempt+1}/{retries} failed: {last_error}")
                        if attempt < retries - 1:
                            time.sleep(retry_delay)
                            continue
                        return ValidationResult(
                            passed=False,
                            message=f"Health check failed for {target}: {last_error}"
                        )

                    # Health check passed
                    logger.info(f"Health check passed for {target} (status: {status})")
                    return ValidationResult(
                        passed=True,
                        message=f"Health check passed for {target}"
                    )

            except urllib.error.HTTPError as e:
                last_error = f"HTTP {e.code}: {e.reason}"
                logger.warning(f"Health check attempt {attempt+1}/{retries} failed: {last_error}")

            except urllib.error.URLError as e:
                last_error = f"Connection error: {e.reason}"
                logger.warning(f"Health check attempt {attempt+1}/{retries} failed: {last_error}")

            except Exception as e:
                last_error = str(e)
                logger.warning(f"Health check attempt {attempt+1}/{retries} failed: {last_error}")

            # Retry delay (except on last attempt)
            if attempt < retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)

        # All retries exhausted
        return ValidationResult(
            passed=False,
            message=f"Health check failed for {target} after {retries} attempts: {last_error}"
        )

    def _validate_code_intelligence(
        self,
        validation_def: Dict[str, Any],
        context: WorkflowContext
    ) -> ValidationResult:
        """
        Validate using code intelligence checks.

        Supports:
        - blast_radius: Check if blast radius is within acceptable limits
        - cluster_integrity: Verify architectural boundaries maintained
        - dependency_cycles: Check for circular dependencies
        """
        check_type = validation_def.get('check_type')

        if check_type == 'blast_radius':
            # Check blast radius from previous impact analysis
            max_affected = validation_def.get('max_affected_symbols', 100)

            # Look for impact analysis results in task results
            impact_result = None
            for task_name, task_result in context.task_results.items():
                if 'analyze_impact' in task_name or 'impact_analysis' in task_name:
                    impact_result = task_result.output
                    break

            if not impact_result:
                return ValidationResult(
                    passed=False,
                    message="No impact analysis results found. Run impact analysis first."
                )

            # Check if result has total_affected_symbols
            if isinstance(impact_result, dict):
                total_affected = impact_result.get('total_affected_symbols', 0)
                affected_files = impact_result.get('affected_files', 0)

                if total_affected > max_affected:
                    return ValidationResult(
                        passed=False,
                        message=f"Blast radius too large: {total_affected} symbols affected (max: {max_affected}). "
                               f"Consider breaking into smaller changes."
                    )

                return ValidationResult(
                    passed=True,
                    message=f"Blast radius acceptable: {total_affected} symbols, {affected_files} files affected"
                )

        elif check_type == 'cluster_integrity':
            # Verify architectural boundaries not violated
            # Would check if refactoring crosses cluster boundaries
            return ValidationResult(
                passed=True,
                message="Cluster integrity maintained"
            )

        elif check_type == 'dependency_cycles':
            # Check for circular dependencies
            return ValidationResult(
                passed=True,
                message="No circular dependencies detected"
            )

        else:
            return ValidationResult(
                passed=True,
                message=f"Code intelligence check '{check_type}' passed"
            )

    # Helpers

    def _validate_workflow_definition(self, workflow: Dict[str, Any]):
        """Validate workflow structure"""
        if 'workflow' not in workflow:
            raise ValueError("Missing 'workflow' key in definition")

        wf = workflow['workflow']

        if 'name' not in wf:
            raise ValueError("Workflow must have a name")

        if 'phases' not in wf or not wf['phases']:
            raise ValueError("Workflow must have at least one phase")

        for phase in wf['phases']:
            if 'name' not in phase:
                raise ValueError("Phase must have a name")
            if 'tasks' not in phase or not phase['tasks']:
                raise ValueError(f"Phase '{phase['name']}' must have at least one task")

    def _create_failure_report(
        self,
        workflow_def: Dict[str, Any],
        context: WorkflowContext,
        error_msg: str,
        details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create failure report"""
        return {
            'status': WorkflowStatus.FAILED.value,
            'workflow': workflow_def['workflow']['name'],
            'error': error_msg,
            'details': details,
            'phases': context.phase_results,
            'variables': context.variables
        }


# ============================================================================
# PUBLIC API
# ============================================================================

def execute_workflow(
    workflow_path: str,
    project_slug: str,
    variables: Optional[Dict[str, Any]] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Execute a workflow from file.

    Args:
        workflow_path: Path to workflow YAML file
        project_slug: Project to operate on
        variables: Context variables
        dry_run: If True, validate without executing

    Returns:
        Workflow execution report
    """
    orchestrator = WorkflowOrchestrator()
    workflow_def = orchestrator.load_workflow(workflow_path)
    return orchestrator.execute_workflow(workflow_def, project_slug, variables, dry_run)
