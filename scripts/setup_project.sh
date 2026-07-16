#!/usr/bin/env bash
set -e

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "Environment ready."
echo "Next:"
echo "1) cp .env.example .env"
echo "2) put your TUSHARE_TOKEN into .env"
echo "3) python scripts/run_data_layer.py"
