FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY src/ ./src/
COPY supabase/ ./supabase/
COPY scripts/ ./scripts/
COPY README.md .
COPY .gitignore .

# Add src/ to PYTHONPATH so "src.api.main" resolves
ENV PYTHONPATH=/app/src

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:10000/health')" || exit 1

# Run with Gunicorn
# Correct import: src.api.main → src/api/main.py
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "2", "--threads", "4", "--timeout", "120", "src.api.main:app"]
