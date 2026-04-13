#!/bin/bash
set -e
echo "[startup] $(date) - Starting Shopify with AI..."
echo "[startup] PYTHONPATH=$PYTHONPATH"
echo "[startup] Testing import..."
python3 -c "from src.api.main import app; print('✓ app loaded:', type(app).__name__)" 2>&1 || {
    echo "✗ Import failed, checking why..."
    python3 -c "import sys; sys.path.insert(0,'src'); from api.main import app" 2>&1
}
echo "[startup] Starting gunicorn..."
exec gunicorn \
    --bind "0.0.0.0:10000" \
    --workers 2 \
    --threads 4 \
    --timeout 120 \
    --capture-output \
    --access-logfile - \
    --error-logfile - \
    "src.api.main:app"
