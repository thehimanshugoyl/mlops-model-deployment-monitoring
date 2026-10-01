# Production Dockerfile for ML Model Serving & Monitoring Service
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install python dependencies directly
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and pre-trained model artifacts
COPY src/ ./src/
COPY artifacts/ ./artifacts/

# Create a non-privileged user and switch to it for security
RUN useradd -m -u 10001 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Healthcheck probe using built-in Python urllib
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/live')" || exit 1

# Launch production ASGI server
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
