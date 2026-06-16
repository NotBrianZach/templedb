#!/usr/bin/env bash
# TempleDB Test Runner
#
# Unified test runner for all TempleDB tests using pytest
#
# Usage:
#   ./run_tests.sh                 # Run all tests
#   ./run_tests.sh -v              # Verbose output
#   ./run_tests.sh -k test_name    # Run specific test
#   ./run_tests.sh -m unit         # Run only unit tests
#   ./run_tests.sh -m integration  # Run only integration tests
#   ./run_tests.sh --help          # Show pytest help

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=====================================================================${NC}"
echo -e "${BLUE}TempleDB Test Suite${NC}"
echo -e "${BLUE}=====================================================================${NC}"
echo ""

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}Error: pytest not found${NC}"
    echo ""
    echo "Install pytest with:"
    echo "  pip install pytest"
    echo ""
    echo "Optional plugins:"
    echo "  pip install pytest-cov     # For coverage reports"
    echo "  pip install pytest-xdist   # For parallel execution"
    echo "  pip install pytest-timeout # For test timeouts"
    exit 1
fi

# Check database exists
DB_PATH="${TEMPLEDB_PATH:-$HOME/.local/share/templedb/templedb.sqlite}"
if [ ! -f "$DB_PATH" ]; then
    echo -e "${YELLOW}Warning: Database not found at $DB_PATH${NC}"
    echo "Some tests may fail or be skipped."
    echo ""
fi

# Run pytest with arguments
echo -e "${GREEN}Running tests...${NC}"
echo ""

# If no arguments provided, use default options from pytest.ini
if [ $# -eq 0 ]; then
    pytest tests/
else
    pytest "$@"
fi

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}=====================================================================${NC}"
    echo -e "${GREEN}All tests passed!${NC}"
    echo -e "${GREEN}=====================================================================${NC}"
else
    echo -e "${RED}=====================================================================${NC}"
    echo -e "${RED}Some tests failed${NC}"
    echo -e "${RED}=====================================================================${NC}"
fi

exit $EXIT_CODE
