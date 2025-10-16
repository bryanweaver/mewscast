#!/bin/bash
# Local testing script for mewscast

echo "🧪 Mewscast Local Test"
echo "====================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found"
    echo "Copy .env.example to .env and add your credentials"
    exit 1
fi

# Check if venv exists
if [ ! -d venv ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -q -r requirements.txt

# Run the bot
echo ""
echo "🤖 Running bot in test mode..."
echo "================================"
echo ""

cd src
python main.py scheduled

echo ""
echo "================================"
echo "✅ Test complete!"
echo ""
echo "Next steps:"
echo "1. Check if tweet was posted to your timeline"
echo "2. Adjust config.yaml if needed"
echo "3. Push to GitHub and set up Actions for automation"
