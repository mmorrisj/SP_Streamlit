# ===========================================
# Test Runner Script (PowerShell) - Quick test commands
# ===========================================

param(
    [Parameter(Position=0)]
    [ValidateSet("unit", "integration", "fast", "slow", "coverage", "ci", "failed", "debug", "all")]
    [string]$TestType = "all"
)

function Print-Header {
    param([string]$Message)
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host $Message -ForegroundColor Blue
    Write-Host "========================================" -ForegroundColor Blue
}

function Print-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Print-Info {
    param([string]$Message)
    Write-Host "→ $Message" -ForegroundColor Yellow
}

switch ($TestType) {
    "unit" {
        Print-Header "Running Unit Tests"
        pytest -m unit -v
    }

    "integration" {
        Print-Header "Running Integration Tests"
        pytest -m "integration and not slow and not llm" -v
    }

    "fast" {
        Print-Header "Running Fast Tests"
        pytest -m "not slow and not llm" -v
    }

    "slow" {
        Print-Header "Running All Tests (including slow)"
        pytest -v
    }

    "coverage" {
        Print-Header "Running Tests with Coverage"
        pytest --cov --cov-report=html --cov-report=term-missing
        Print-Info "Coverage report saved to htmlcov/index.html"
    }

    "ci" {
        Print-Header "Running CI Test Suite"

        Print-Info "1. Unit tests"
        pytest -m unit -v --junitxml=test-results/junit-unit.xml

        Print-Info "2. Integration tests"
        pytest -m "integration and not slow and not llm" -v --junitxml=test-results/junit-integration.xml

        Print-Info "3. Full test suite with coverage"
        pytest --cov --cov-report=xml --cov-report=html --cov-report=term-missing --junitxml=test-results/junit-all.xml

        Print-Success "CI test suite complete"
    }

    "failed" {
        Print-Header "Re-running Failed Tests"
        pytest --lf -v
    }

    "debug" {
        Print-Header "Running Tests with Debug Output"
        pytest -vv -s --tb=long
    }

    default {
        Print-Header "Running All Tests"
        pytest -v
    }
}

Print-Success "Tests complete!"
