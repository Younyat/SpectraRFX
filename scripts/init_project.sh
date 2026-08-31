

#!/bin/bash
# Spectrum Lab - Project Initialization Script

set -e  # Exit on error

echo "================================"
echo "Spectrum Lab - Project Setup"
echo "================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'  # No Color

# Check Python
echo "Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python3 not found. Please install Python 3.10+${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python3 found: $(python3 --version)${NC}"

# Check Node.js
echo "Checking Node.js installation..."
if ! command -v node &> /dev/null; then
    echo -e "${RED}Node.js not found. Please install Node.js 18+${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Node.js found: $(node --version)${NC}"

# Backend Setup
echo ""
echo "================================"
echo "Setting up Backend..."
echo "================================"

cd backend

# Create venv if not exists
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null

# Install dependencies
echo "Installing backend dependencies..."
pip install -q --upgrade pip wheel "setuptools<82"
pip install -q -r requirements.txt

echo -e "${GREEN}✓ Backend setup complete${NC}"
cd ..

# Frontend Setup
echo ""
echo "================================"
echo "Setting up Frontend..."
echo "================================"

cd frontend

# Install dependencies
if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install -q
else
    echo "Frontend dependencies already installed"
fi

echo -e "${GREEN}✓ Frontend setup complete${NC}"
cd ..

# Print next steps
echo ""
echo "================================"
echo -e "${GREEN}Setup Complete!${NC}"
echo "================================"
echo ""
echo "To start the application:"
echo ""
echo "1. Backend (Terminal 1):"
echo "   cd backend"
echo "   source venv/bin/activate"
echo "   python -m uvicorn app.main:app --reload"
echo ""
echo "2. Frontend (Terminal 2):"
echo "   cd frontend"
echo "   npm run dev"
echo ""
echo "Then open: http://localhost:5173"
echo ""
echo "API Docs: http://localhost:8000/docs"
echo ""
