FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
EXPOSE 5000

ENV PYTHONUNBUFFERED=1
# SECURITY NOTICE:
# The server executes generated code. Default is 127.0.0.1 (localhost).
# Only override HOST to 0.0.0.0 in isolated private container networks (never expose publicly).
ENV HOST=127.0.0.1
ENV PORT=8000

CMD ["python", "ide_server.py"]
