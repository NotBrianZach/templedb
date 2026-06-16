#!/usr/bin/env bash
# End-to-end workflow tests for TempleDB
# Tests all workflows via MCP protocol

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

# Helper functions
log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((TESTS_PASSED++))
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((TESTS_FAILED++))
}

call_mcp_tool() {
    local tool_name=$1
    local arguments=$2
    local timeout=${3:-10}

    timeout "$timeout" bash -c "
(
  echo '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"test\",\"version\":\"1.0\"}}}'
  sleep 0.1
  echo '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"$tool_name\",\"arguments\":$arguments}}'
  sleep 1
) | ./templedb mcp serve 2>/dev/null | tail -1
"
}

check_json_field() {
    local json=$1
    local field=$2
    local expected=$3

    local actual=$(echo "$json" | python3 -c "import sys, json; data = json.load(sys.stdin); print(data$field)" 2>/dev/null || echo "")

    if [[ "$actual" == "$expected" ]]; then
        return 0
    else
        echo "Expected: $expected, Got: $actual" >&2
        return 1
    fi
}

# Start tests
echo "========================================="
echo "TempleDB Workflow End-to-End Tests"
echo "========================================="
echo ""

# Test 1: List workflows
log_info "Test 1: List available workflows"
result=$(call_mcp_tool "templedb_workflow_list" "{}")
if echo "$result" | python3 -c "import sys, json; data = json.load(sys.stdin); content = data.get('result', {}).get('content', [{}])[0].get('text', ''); result = json.loads(content); assert result['count'] >= 3; print('OK')" 2>/dev/null; then
    log_success "Workflow list returns 3+ workflows"
else
    log_error "Workflow list failed"
fi

# Test 2: Validate code intelligence bootstrap workflow
log_info "Test 2: Validate code_intelligence_bootstrap workflow"
result=$(call_mcp_tool "templedb_workflow_validate" '{"workflow":"code_intelligence_bootstrap"}')
if echo "$result" | python3 -c "import sys, json; data = json.load(sys.stdin); content = data.get('result', {}).get('content', [{}])[0].get('text', ''); result = json.loads(content); assert result['valid'] == True; assert result['version'] == '1.0'; print('OK')" 2>/dev/null; then
    log_success "code_intelligence_bootstrap validation passed"
else
    log_error "code_intelligence_bootstrap validation failed"
fi

# Test 3: Validate safe deployment workflow
log_info "Test 3: Validate safe_deployment workflow"
result=$(call_mcp_tool "templedb_workflow_validate" '{"workflow":"safe_deployment"}')
if echo "$result" | python3 -c "import sys, json; data = json.load(sys.stdin); content = data.get('result', {}).get('content', [{}])[0].get('text', ''); result = json.loads(content); assert result['valid'] == True; assert result['version'] == '2.0'; print('OK')" 2>/dev/null; then
    log_success "safe_deployment validation passed (v2.0)"
else
    log_error "safe_deployment validation failed"
fi

# Test 4: Validate impact aware refactoring workflow
log_info "Test 4: Validate impact_aware_refactoring workflow"
result=$(call_mcp_tool "templedb_workflow_validate" '{"workflow":"impact_aware_refactoring"}')
if echo "$result" | python3 -c "import sys, json; data = json.load(sys.stdin); content = data.get('result', {}).get('content', [{}])[0].get('text', ''); result = json.loads(content); assert result['valid'] == True; assert result['phases'] == 5; print('OK')" 2>/dev/null; then
    log_success "impact_aware_refactoring validation passed (5 phases)"
else
    log_error "impact_aware_refactoring validation failed"
fi

# Test 5: Execute code intelligence bootstrap (dry run)
log_info "Test 5: Execute code_intelligence_bootstrap (dry_run)"
result=$(call_mcp_tool "templedb_workflow_execute" '{"workflow":"code_intelligence_bootstrap","project":"templedb","dry_run":true}' 15)
if echo "$result" | python3 -c "import sys, json; data = json.load(sys.stdin); content = data.get('result', {}).get('content', [{}])[0].get('text', ''); result = json.loads(content); assert result['status'] == 'completed'; assert result['dry_run'] == True; assert len(result['phases']) == 2; print('OK')" 2>/dev/null; then
    log_success "code_intelligence_bootstrap dry_run completed"
else
    log_error "code_intelligence_bootstrap dry_run failed"
fi

# Test 6: Execute code intelligence bootstrap (real)
log_info "Test 6: Execute code_intelligence_bootstrap (real execution)"
result=$(call_mcp_tool "templedb_workflow_execute" '{"workflow":"code_intelligence_bootstrap","project":"templedb","dry_run":false}' 20)
if echo "$result" | python3 -c "import sys, json; data = json.load(sys.stdin); content = data.get('result', {}).get('content', [{}])[0].get('text', ''); result = json.loads(content); assert result['status'] == 'completed'; assert result['dry_run'] == False; phases = result['phases']; assert phases['symbol_extraction']['status'] == 'completed'; assert phases['dependency_graph']['status'] == 'completed'; print('OK')" 2>/dev/null; then
    log_success "code_intelligence_bootstrap real execution completed"
else
    log_error "code_intelligence_bootstrap real execution failed"
fi

# Test 7: Execute safe deployment (dry run)
log_info "Test 7: Execute safe_deployment (dry_run)"
result=$(call_mcp_tool "templedb_workflow_execute" '{"workflow":"safe_deployment","project":"templedb","variables":{"primary_symbol":"execute_workflow","previous_version":"v2.0.0"},"dry_run":true}' 20)
if echo "$result" | python3 -c "import sys, json; data = json.load(sys.stdin); content = data.get('result', {}).get('content', [{}])[0].get('text', ''); result = json.loads(content); assert result['status'] == 'completed'; assert result['dry_run'] == True; assert len(result['phases']) == 4; print('OK')" 2>/dev/null; then
    log_success "safe_deployment dry_run completed (4 phases)"
else
    log_error "safe_deployment dry_run failed"
fi

# Test 8: Execute impact aware refactoring (dry run)
log_info "Test 8: Execute impact_aware_refactoring (dry_run)"
result=$(call_mcp_tool "templedb_workflow_execute" '{"workflow":"impact_aware_refactoring","project":"templedb","variables":{"target_symbol":"execute_workflow","max_blast_radius":"200"},"dry_run":true}' 25)
if echo "$result" | python3 -c "import sys, json; data = json.load(sys.stdin); content = data.get('result', {}).get('content', [{}])[0].get('text', ''); result = json.loads(content); assert result['status'] == 'completed'; assert result['dry_run'] == True; assert len(result['phases']) == 5; print('OK')" 2>/dev/null; then
    log_success "impact_aware_refactoring dry_run completed (5 phases)"
else
    log_error "impact_aware_refactoring dry_run failed"
fi

# Test 9: Variable interpolation
log_info "Test 9: Workflow variable interpolation"
result=$(call_mcp_tool "templedb_workflow_execute" '{"workflow":"safe_deployment","project":"templedb","variables":{"primary_symbol":"test_symbol","staging_target":"test-staging","production_target":"test-prod"},"dry_run":true}' 20)
if echo "$result" | python3 -c "import sys, json; data = json.load(sys.stdin); content = data.get('result', {}).get('content', [{}])[0].get('text', ''); result = json.loads(content); assert result['status'] == 'completed'; print('OK')" 2>/dev/null; then
    log_success "Variable interpolation working"
else
    log_error "Variable interpolation failed"
fi

# Test 10: Error handling - invalid workflow
log_info "Test 10: Error handling for invalid workflow"
result=$(call_mcp_tool "templedb_workflow_validate" '{"workflow":"nonexistent_workflow"}')
if echo "$result" | python3 -c "import sys, json; data = json.load(sys.stdin); result_data = data.get('result', {}); assert result_data.get('isError') == True; print('OK')" 2>/dev/null; then
    log_success "Invalid workflow error handling works"
else
    log_error "Invalid workflow error handling failed"
fi

# Summary
echo ""
echo "========================================="
echo "Test Summary"
echo "========================================="
echo -e "${GREEN}Passed:${NC} $TESTS_PASSED"
echo -e "${RED}Failed:${NC} $TESTS_FAILED"
echo ""

if [[ $TESTS_FAILED -eq 0 ]]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    exit 1
fi
