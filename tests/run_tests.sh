#!/bin/bash
# Quick test runner: Start server, run RAG tests, report results

set -e

VENV=".venv"
if [ ! -d "$VENV" ]; then
    echo "❌ Virtual environment not found. Run: python3 -m venv .venv"
    exit 1
fi

source "$VENV/bin/activate"

echo "🧪 Starting RAG Quality Tests..."
echo ""

# Check if server is already running
if curl -s http://127.0.0.1:8000/health > /dev/null 2>&1; then
    echo "✓ Server already running on http://127.0.0.1:8000"
    SERVER_WAS_RUNNING=1
else
    echo "🚀 Starting server..."
    DEBUG_RAG=1 uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/kursbot_test.log 2>&1 &
    SERVER_PID=$!
    echo "   Server PID: $SERVER_PID"

    # Wait for server startup
    for i in {1..10}; do
        if curl -s http://127.0.0.1:8000/health > /dev/null 2>&1; then
            echo "✓ Server ready"
            break
        fi
        sleep 1
    done
    SERVER_WAS_RUNNING=0
fi

echo ""

# Run tests
python3 tests/test_rag_quality.py
TEST_RESULT=$?

echo ""

# Show recent server logs if DEBUG_RAG was on
if [ "$SERVER_WAS_RUNNING" -eq 0 ]; then
    echo "📊 Recent server logs (last 5 RAG queries):"
    grep "\[RAG\]" /tmp/kursbot_test.log | tail -5 || echo "   (no RAG logs)"
    echo ""

    echo "🛑 Stopping server (PID $SERVER_PID)..."
    kill $SERVER_PID 2>/dev/null || true
    sleep 1
fi

exit $TEST_RESULT
