FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app.py security.py ./
COPY templates ./templates
COPY static ./static

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data /tmp/homicmail_attachments && \
    chown -R appuser:appuser /app /tmp/homicmail_attachments
USER appuser

# Environment
ENV FLASK_APP=app.py
ENV PORT=5000

EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')" || exit 1

CMD ["python", "app.py"]