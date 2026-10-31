#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[run.sh] Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "[run.sh] Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo "[run.sh] Seeding demonstration data and running scenarios..."
python seed.py

echo "[run.sh] Starting FastAPI on http://127.0.0.1:8000 ..."
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload