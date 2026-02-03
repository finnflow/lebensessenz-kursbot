#!/bin/bash
# Lebensessenz Kursbot - Start Script

echo "🚀 Starting Lebensessenz Kursbot Chat..."
echo ""

# Check if venv exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment not found. Creating..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found!"
    echo "   Please create .env with your OPENAI_API_KEY"
    echo ""
fi

# Initialize database
echo "📦 Initializing database..."
python3 -c "from app.database import init_db; init_db()"

# Run migrations
echo "🔄 Running migrations..."
python3 -m app.migrations

# Start server
echo ""
echo "✨ Starting server on http://localhost:8000"
echo "   Press CTRL+C to stop"
echo ""

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
