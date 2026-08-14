#!/bin/bash
# ===========================================
# Test Runner Script - Quick test commands
# ===========================================

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}→ $1${NC}"
}

# Parse command line arguments
TEST_TYPE="${1:-all}"

case "$TEST_TYPE" in
    unit)
        print_header "Running Unit Tests"
        pytest -m unit -v
        ;;

    integration)
        print_header "Running Integration Tests"
        pytest -m "integration and not slow and not llm" -v
        ;;

    fast)
        print_header "Running Fast Tests"
        pytest -m "not slow and not llm" -v
        ;;

    slow)
        print_header "Running All Tests (including slow)"
        pytest -v
        ;;

    coverage)
        print_header "Running Tests with Coverage"
        pytest --cov --cov-report=html --cov-report=term-missing
        print_info "Coverage report saved to htmlcov/index.html"
        ;;

    watch)
        print_header "Running Tests in Watch Mode"
        print_info "Tests will re-run on file changes"
        pytest-watch -- -v
        ;;

    ci)
        print_header "Running CI Test Suite"
        print_info "1. Unit tests"
        pytest -m unit -v --junitxml=test-results/junit-unit.xml

        print_info "2. Integration tests"
        pytest -m "integration and not slow and not llm" -v --junitxml=test-results/junit-integration.xml

        print_info "3. Full test suite with coverage"
        pytest --cov --cov-report=xml --cov-report=html --cov-report=term-missing --junitxml=test-results/junit-all.xml

        print_success "CI test suite complete"
        ;;

    failed)
        print_header "Re-running Failed Tests"
        pytest --lf -v
        ;;

    debug)
        print_header "Running Tests with Debug Output"
        pytest -vv -s --tb=long
        ;;

    all|*)
        print_header "Running All Tests"
        pytest -v
        ;;
esac

print_success "Tests complete!"
