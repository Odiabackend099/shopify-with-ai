FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Set Python path so 'from src.xxx' imports work
ENV PYTHONPATH=/app/src:/app

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:10000/health')" || exit 1

# Run with startup validation script
COPY start.sh .
RUN chmod +x start.sh
CMD ["./start.sh"]
