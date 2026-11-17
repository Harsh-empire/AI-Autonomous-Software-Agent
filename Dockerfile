FROM python:3.11-slim

# Prevent bytecode compilation and buffer stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=127.0.0.1 \
    PORT=8000

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and group
RUN groupadd -r aegis && useradd -r -g aegis -m -d /home/aegis aegis

# Install Python requirements without fallback to catch errors immediately
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy codebase
COPY . .

# Grant non-root ownership
RUN chown -R aegis:aegis /app

# Run as non-root user
USER aegis

EXPOSE 8000
EXPOSE 5000

# Healthcheck monitoring the IDE server
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

CMD ["python", "ide_server.py"]
