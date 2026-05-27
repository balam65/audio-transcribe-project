#!/bin/bash
# ============================================
# Meeting Transcription System — Setup Script
# 100% LOCAL — No paid APIs required
# ============================================

set -e

echo "============================================"
echo "  🎙️  Meeting Transcription System Setup"
echo "  100% Local — No Cloud APIs"
echo "============================================"
echo ""

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# 1. System dependencies
echo "📦 Step 1: Checking system dependencies..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.9+"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  ✅ Python $PYTHON_VERSION found"

# Install system packages
echo "  📥 Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg portaudio19-dev pulseaudio-utils 2>/dev/null || true

# Check for PulseAudio/PipeWire
if command -v pulseaudio &> /dev/null || command -v pipewire &> /dev/null; then
    echo "  ✅ PulseAudio/PipeWire available"
else
    echo "  ⚠️  PulseAudio not found. System audio capture may not work."
fi

# 2. Python virtual environment
echo ""
echo "🐍 Step 2: Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  ✅ Virtual environment created"
else
    echo "  ✅ Virtual environment exists"
fi

source venv/bin/activate

# 3. Install dependencies
echo ""
echo "📥 Step 3: Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r backend/requirements.txt -q
echo "  ✅ Dependencies installed"

# 4. Environment file
echo ""
echo "⚙️  Step 4: Setting up environment..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  ✅ Created .env from .env.example"
else
    echo "  ✅ .env already exists"
fi

# 5. Create data directories
echo ""
echo "📁 Step 5: Creating data directories..."
mkdir -p data/exports
echo "  ✅ Data directories ready"

# 6. Check GPU
echo ""
echo "🖥️  Step 6: Checking GPU..."
if python3 -c "import torch; print(torch.cuda.is_available())" 2>/dev/null | grep -q "True"; then
    echo "  🟢 CUDA GPU detected — will use float16 for maximum speed"
else
    echo "  🔵 No CUDA GPU — will use CPU with int8 (still works great)"
fi

# 7. Check Ollama
echo ""
echo "🧠 Step 7: Checking Ollama for summaries..."
if command -v ollama &> /dev/null; then
    echo "  ✅ Ollama is installed"
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "  ✅ Ollama is running"
    else
        echo "  ⚠️  Ollama is installed but not running. Start with: ollama serve"
    fi
else
    echo "  ⚠️  Ollama not installed. Summaries will be skipped."
    echo "     Install: curl -fsSL https://ollama.com/install.sh | sh"
    echo "     Then:    ollama pull llama3.1"
fi

echo ""
echo "============================================"
echo "  ✅ Setup complete!"
echo "============================================"
echo ""
echo "To start the server:"
echo "  source venv/bin/activate"
echo "  cd backend && python main.py"
echo ""
echo "Then open: http://localhost:8000"
echo ""
echo "🔑 No API keys needed — everything runs locally!"
echo ""
