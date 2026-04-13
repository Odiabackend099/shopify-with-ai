FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Set Python path so 'src.api.main' imports resolve
ENV PYTHONPATH=/app/src:/app

# Expose port
EXPOSE 10000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:10000/health')" || exit 1

# Use Uvicorn worker — required for FastAPI on Gunicorn
CMD ["python", "-m", "gunicorn", "--bind", "0.0.0.0:10000", "--workers", "2", "--worker-class", "uvicorn.workers.UvicornWorker", "--timeout", "120", "src.api.main:app"]
