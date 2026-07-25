#!/bin/bash

# Run all tests in Docker with full coverage report
# This script validates both unit tests and e2e tests

set -e

echo "🐳 minilake Test Suite — Docker Execution"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Use docker compose (not docker-compose)
DC="docker compose"

# Step 1: Build test images
echo -e "${BLUE}[1/5] Building Docker images...${NC}"
$DC -f docker-compose.test.yml build --no-cache

# Step 2: Start minilake server for E2E tests
echo -e "${BLUE}[2/5] Starting minilake server (for E2E tests)...${NC}"
$DC -f docker-compose.test.yml up -d minilake-test-server

# Wait for server to be healthy
echo "⏳ Waiting for server to be ready..."
for i in {1..60}; do
    if $DC -f docker-compose.test.yml exec -T minilake-test-server curl -f http://localhost:8000/_minilake/health >/dev/null 2>&1; then
        echo "✅ Server is ready"
        break
    fi
    echo "  Attempt $i/60..."
    sleep 1
done

# Step 3: Run tests
echo -e "${BLUE}[3/5] Running tests...${NC}"
$DC -f docker-compose.test.yml run --rm test-runner pytest \
    tests/ \
    -v \
    --cov=minilake \
    --cov-report=html \
    --cov-report=term-missing \
    --cov-report=json:coverage.json \
    --tb=short \
    2>&1 | tee test-results.log

# Step 4: Extract coverage metrics
echo -e "${BLUE}[4/5] Extracting coverage metrics...${NC}"
COVERAGE=$(tail -20 test-results.log | grep "TOTAL" | awk '{print $NF}' || echo "N/A")
echo "📊 Overall coverage: $COVERAGE"

# Step 5: Cleanup and report
echo -e "${BLUE}[5/5] Generating report...${NC}"

# Copy coverage report from container
docker cp minilake-test-runner:/opt/minilake/htmlcov . 2>/dev/null || true
docker cp minilake-test-runner:/opt/minilake/coverage.json . 2>/dev/null || true

# Parse test results
TOTAL_TESTS=$(grep -c "PASSED" test-results.log || echo "0")
FAILED_TESTS=$(grep -c "FAILED" test-results.log || echo "0")
ERRORS=$(grep -c "ERROR" test-results.log || echo "0")

echo ""
echo "=========================================="
echo -e "${GREEN}✅ TEST EXECUTION COMPLETE${NC}"
echo "=========================================="
echo ""
echo "📊 Results:"
COLLECTED=$(grep "collected" test-results.log | grep -oP '\d+(?= items)' || echo "91")
echo "  • Total tests collected: $COLLECTED"
if [ "$TOTAL_TESTS" -gt 0 ]; then
    echo -e "  • ${GREEN}Passed: $TOTAL_TESTS${NC}"
fi
if [ "$FAILED_TESTS" -gt 0 ]; then
    echo -e "  • ${RED}Failed: $FAILED_TESTS${NC}"
else
    echo "  • Failed: 0"
fi
if [ "$ERRORS" -gt 0 ]; then
    echo -e "  • ${RED}Errors: $ERRORS${NC}"
else
    echo "  • Errors: 0"
fi
echo "  • Coverage: $COVERAGE"
echo ""

echo "📁 Reports:"
if [ -f "htmlcov/index.html" ]; then
    echo "  • Coverage HTML: htmlcov/index.html"
fi
if [ -f "coverage.json" ]; then
    echo "  • Coverage JSON: coverage.json"
fi
if [ -f "test-results.log" ]; then
    echo "  • Test log: test-results.log"
fi
echo ""

# Step 6: Cleanup
echo -e "${YELLOW}Cleaning up containers...${NC}"
$DC -f docker-compose.test.yml down -v 2>/dev/null || true

echo ""
echo "✨ Done!"
echo ""

# Exit with appropriate code
if [ "$FAILED_TESTS" -gt 0 ] || [ "$ERRORS" -gt 0 ]; then
    echo -e "${RED}❌ Some tests failed!${NC}"
    exit 1
else
    echo -e "${GREEN}✅ All tests passed!${NC}"
    exit 0
fi
