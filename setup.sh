#!/bin/bash

echo "==================================="
echo "    StreamTracks VPS Setup Script  "
echo "==================================="

# 1. Check for Docker
if ! command -v docker &> /dev/null; then
    echo "[ERROR] Docker is not installed. Please install Docker first."
    exit 1
fi

# 2. Check for .env file
if [ ! -f .env ]; then
    echo "[INFO] No .env file found. Creating from .env.example..."
    cp .env.example .env
    echo "[ACTION REQUIRED] Please edit the .env file with your credentials (nano .env) and run this script again."
    exit 1
fi

echo "[INFO] Building Docker image..."
docker compose build --quiet

echo "[INFO] Running Pre-flight Configuration Checks..."
docker compose run --rm bot python app/check_config.py
CHECK_STATUS=$?

if [ $CHECK_STATUS -ne 0 ]; then
    echo "[ERROR] Configuration checks failed. Please fix your .env file and try again."
    exit 1
fi

echo "==================================="
echo " ✅ Setup Complete!"
echo "==================================="
echo "To start the bot in the background, run:"
echo "  docker compose up -d"
echo ""
echo "To view logs, run:"
echo "  docker compose logs -f"
